import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests


try:
    import dotenv
except ImportError:
    dotenv = None


if dotenv and os.path.exists(".env"):
    dotenv.load_dotenv()


PROMPT_VERSION = "paper-artifacts-v3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="AI-enhanced jsonline data file")
    parser.add_argument(
        "--cache",
        default="../data/paper_artifact_cache.jsonl",
        help="Cache for translated abstracts, conclusions, and figure metadata",
    )
    parser.add_argument("--max-figures", type=int, default=8)
    return parser.parse_args()


def normalize_space(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def read_jsonl(path: str) -> List[Dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_cache(path: str) -> Dict[str, Dict]:
    cache = {}
    if not os.path.exists(path):
        return cache
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = item.get("cache_key")
            if key:
                cache[key] = item
    return cache


def append_cache(path: str, item: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def paper_hash(paper: Dict) -> str:
    relevant = {
        "id": paper.get("id"),
        "title": paper.get("title"),
        "summary": paper.get("summary"),
        "ai": paper.get("AI", {}),
        "prompt_version": PROMPT_VERSION,
    }
    payload = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def cache_key(paper: Dict) -> str:
    return f"{PROMPT_VERSION}:{paper.get('id')}:{paper_hash(paper)}"


def llm_enabled() -> bool:
    if os.environ.get("ENABLE_PAPER_ARTIFACTS", "true").lower() in {"0", "false", "no"}:
        return False
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def extract_json_object(text: str) -> Optional[Dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def call_llm_for_text(paper: Dict, conclusion_source: str, figures: List[Dict]) -> Optional[Dict]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = (
        os.environ.get("MODEL_NAME")
        or os.environ.get("OPENAI_MODEL_NAME")
        or "deepseek-chat"
    ).strip()
    if not api_key:
        return None

    prompt_payload = {
        "title": paper.get("title"),
        "abstract": paper.get("summary"),
        "ai_conclusion": (paper.get("AI") or {}).get("conclusion") if isinstance(paper.get("AI"), dict) else "",
        "conclusion_source": conclusion_source[:5000],
        "figures": [
            {
                "figure_label": fig.get("figure_label"),
                "caption_en": fig.get("caption_en"),
            }
            for fig in figures[:8]
        ],
    }
    system_prompt = (
        "You translate and normalize academic paper metadata for a Chinese research webpage. "
        "Be faithful, formal, and concise. Do not invent details."
    )
    user_prompt = (
        "Return only valid JSON with keys: abstract_zh, conclusion_zh, figures. "
        "abstract_zh must be a faithful Chinese translation of the abstract. "
        "conclusion_zh should translate the paper conclusion if provided; otherwise translate the AI conclusion and say it is based on available summary. "
        "figures is a list preserving figure_label and image_url if present, with caption_zh translated from caption_en. "
        f"\n\nInput:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = extract_json_object(content)
        if not parsed:
            return None
        return parsed
    except Exception as exc:
        print(f"Artifact LLM failed for {paper.get('id')}: {exc}", file=sys.stderr)
        return None


def fetch_arxiv_html(paper: Dict) -> Dict[str, str]:
    arxiv_id = paper.get("id")
    if not arxiv_id:
        return {"url": "", "text": ""}
    candidates = [
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    ]
    for url in candidates:
        try:
            response = requests.get(url, timeout=30)
            if response.ok and len(response.text) > 1000:
                return {"url": response.url or url, "text": response.text}
        except Exception:
            continue
    return {"url": "", "text": ""}


def extract_conclusion_from_html(html_text: str) -> str:
    if not html_text:
        return ""
    section_patterns = [
        r"(?is)<section[^>]*>.*?<h[1-6][^>]*>\s*(?:\d+\.?\s*)?(?:conclusion|conclusions|summary and conclusions)[^<]*</h[1-6]>(.*?)</section>",
        r"(?is)<h[1-6][^>]*>\s*(?:\d+\.?\s*)?(?:conclusion|conclusions|summary and conclusions)[^<]*</h[1-6]>(.*?)(?:<h[1-6]|\Z)",
    ]
    for pattern in section_patterns:
        match = re.search(pattern, html_text)
        if match:
            text = normalize_space(match.group(1))
            if len(text) > 80:
                return text[:6000]
    return ""


def extract_figures_from_html(html_text: str, base_url: str, max_figures: int) -> List[Dict]:
    figures = []
    if not html_text:
        return figures
    for idx, match in enumerate(re.finditer(r"(?is)<figure\b.*?</figure>", html_text), start=1):
        block = match.group(0)
        img_match = re.search(r'(?is)<img[^>]+src=["\']([^"\']+)["\']', block)
        caption_match = re.search(r"(?is)<figcaption[^>]*>(.*?)</figcaption>", block)
        caption = normalize_space(caption_match.group(1)) if caption_match else ""
        if not caption:
            continue
        image_url = ""
        if img_match:
            src = html.unescape(img_match.group(1))
            if base_url and "/html/" in base_url:
                image_url = urljoin("https://arxiv.org/html/", src)
            else:
                image_url = urljoin(base_url or "https://arxiv.org/html/", src)
        label_match = re.search(r"(?i)\b(fig(?:ure)?\.?\s*\d+[a-z]?)", caption)
        label = label_match.group(1) if label_match else f"Figure {idx}"
        figures.append(
            {
                "figure_label": label,
                "image_url": image_url,
                "caption_en": caption[:2000],
                "is_key_result": idx <= 5,
            }
        )
        if len(figures) >= max_figures:
            break
    return figures


def fallback_artifacts(paper: Dict, figures: List[Dict]) -> Dict:
    ai = paper.get("AI") if isinstance(paper.get("AI"), dict) else {}
    return {
        "abstract_zh": paper.get("summary", ""),
        "conclusion_zh": ai.get("conclusion", ""),
        "figures": figures,
        "artifact_method": "fallback",
        "prompt_version": PROMPT_VERSION,
    }


def enrich_paper(paper: Dict, cache: Dict[str, Dict], cache_path: str, max_figures: int) -> Dict:
    key = cache_key(paper)
    cached = cache.get(key)
    if cached and isinstance(cached.get("artifacts"), dict):
        paper["artifacts"] = cached["artifacts"]
        return paper

    html_payload = fetch_arxiv_html(paper)
    html_text = html_payload.get("text", "")
    html_url = html_payload.get("url", "")
    conclusion_source = extract_conclusion_from_html(html_text)
    figures = extract_figures_from_html(html_text, html_url, max_figures)
    artifacts = fallback_artifacts(paper, figures)

    if llm_enabled():
        llm_artifacts = call_llm_for_text(paper, conclusion_source, figures)
        if llm_artifacts:
            translated_figures = llm_artifacts.get("figures") if isinstance(llm_artifacts.get("figures"), list) else []
            merged_figures = []
            for idx, fig in enumerate(figures):
                merged = dict(fig)
                if idx < len(translated_figures) and isinstance(translated_figures[idx], dict):
                    merged["caption_zh"] = translated_figures[idx].get("caption_zh", "")
                merged_figures.append(merged)
            artifacts = {
                "abstract_zh": str(llm_artifacts.get("abstract_zh", "")).strip() or artifacts["abstract_zh"],
                "conclusion_zh": str(llm_artifacts.get("conclusion_zh", "")).strip() or artifacts["conclusion_zh"],
                "figures": merged_figures,
                "artifact_method": "llm_html",
                "prompt_version": PROMPT_VERSION,
            }

    paper["artifacts"] = artifacts
    cache_item = {
        "cache_key": key,
        "paper_id": paper.get("id"),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "artifacts": artifacts,
    }
    cache[key] = cache_item
    append_cache(cache_path, cache_item)
    return paper


def main() -> None:
    args = parse_args()
    rows = read_jsonl(args.data)
    cache = load_cache(args.cache)
    enriched = [enrich_paper(row, cache, args.cache, args.max_figures) for row in rows]
    write_jsonl(args.data, enriched)
    print(f"Enriched {len(enriched)} papers with paper artifacts.", file=sys.stderr)


if __name__ == "__main__":
    main()

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import requests


try:
    import dotenv
except ImportError:
    dotenv = None


if dotenv and os.path.exists(".env"):
    dotenv.load_dotenv()


PROMPT_VERSION = "recommend-v2-author-weighted"

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "between",
    "by", "can", "for", "from", "has", "have", "in", "into", "is", "it",
    "its", "may", "of", "on", "or", "our", "that", "the", "their", "this",
    "through", "to", "using", "via", "was", "we", "were", "with", "within",
    "across", "also", "both", "consistent", "eld", "elds", "find", "first",
    "high", "large", "most", "new", "over", "present", "results", "review",
    "study", "such", "than", "these", "total", "two", "which",
}

GENERIC_PROFILE_TERMS = {
    "analysis", "data", "density", "distribution", "early", "evidence",
    "evolution", "field", "fields", "formation", "function", "galactic",
    "galaxies", "galaxy", "local", "mass", "massive", "medium", "model",
    "models", "observations", "observed", "population", "properties",
    "redshift", "redshifts", "sample", "scales", "simulations", "sources",
    "star", "stars", "stellar", "structure", "survey", "surveys", "time",
    "universe", "velocity", "years",
}

HIGH_SIGNAL_SINGLE_TERMS = {
    "alma", "cii", "csst", "dsfgs", "dust", "dusty", "euclid", "halo",
    "herschel", "interferometer", "ism", "jwst", "lens", "lensed",
    "lensing", "magnetic", "molecular", "polarization", "polarized",
    "polarised", "ska", "spt", "starburst", "submillimeter",
}

DEFAULT_KEYWORDS = [
    "strong lens", "strong gravitational lens", "strong lensing",
    "lens model", "lensing", "dark matter", "dm halo", "alma", "ska",
    "interferometer", "dust", "dusty", "dsfgs", "submillimeter",
    "high-redshift", "polarization", "polarized", "polarised", "gas",
    "molecular", "molecular gas", "spt", "herschel", "jwst", "euclid",
    "csst",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="AI-enhanced jsonline data file")
    parser.add_argument(
        "--profile",
        default="../data/zotero_profile.json",
        help="Where to cache the Zotero interest profile",
    )
    parser.add_argument(
        "--cache",
        default="../data/llm_recommendation_cache.jsonl",
        help="LLM recommendation cache keyed by arXiv id and profile hash",
    )
    return parser.parse_args()


def normalize_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values())
    return str(value or "")


def normalize_author(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip().lower()
    value = value.replace(".", "")
    return value


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]{2,}", text.lower())
    return [word for word in words if word not in STOPWORDS]


def ngrams(tokens: List[str], min_n: int = 1, max_n: int = 3) -> Iterable[str]:
    for n in range(min_n, max_n + 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            yield " ".join(tokens[idx : idx + n])


def normalize_term(term: str) -> str:
    term = re.sub(r"\s+", " ", term.lower()).strip()
    return term.replace("high redshift", "high-redshift")


def term_tokens(term: str) -> List[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]{1,}", normalize_term(term))


def is_informative_term(term: str) -> bool:
    term = normalize_term(term)
    tokens = term_tokens(term)
    if not tokens:
        return False
    if term.startswith("astrophysics -"):
        return False
    if term in STOPWORDS or term in GENERIC_PROFILE_TERMS:
        return False
    if len(tokens) == 1:
        return term in HIGH_SIGNAL_SINGLE_TERMS
    generic_count = sum(1 for token in tokens if token in STOPWORDS or token in GENERIC_PROFILE_TERMS)
    return generic_count < len(tokens)


def term_multiplier(term: str) -> float:
    tokens = term_tokens(term)
    if normalize_term(term) in HIGH_SIGNAL_SINGLE_TERMS:
        return 0.85
    if len(tokens) >= 3:
        return 1.4
    if len(tokens) == 2:
        return 1.0
    return 0.25


def term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(normalize_term(term))
    return re.compile(rf"(?<![a-zA-Z0-9]){escaped}(?![a-zA-Z0-9])", re.IGNORECASE)


def clean_author(author: Dict) -> str:
    if "name" in author:
        return author["name"].strip()
    return " ".join(
        part for part in [author.get("firstName", ""), author.get("lastName", "")] if part
    ).strip()


def zotero_request(url: str, params: Dict, api_key: str) -> List[Dict]:
    headers = {"Zotero-API-Key": api_key}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_zotero_items() -> List[Dict]:
    api_key = os.environ.get("ZOTERO_API_KEY", "").strip()
    user_id = os.environ.get("ZOTERO_USER_ID", "").strip()
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "users").strip() or "users"
    library_id = (os.environ.get("ZOTERO_LIBRARY_ID") or user_id).strip()
    collection_key = os.environ.get("ZOTERO_COLLECTION_KEY", "").strip()
    max_items = int(os.environ.get("ZOTERO_MAX_ITEMS") or "300")

    if not api_key or not library_id or library_id == "PLEASE_SET_ME":
        return []

    base = f"https://api.zotero.org/{library_type}/{library_id}"
    if collection_key:
        base = f"{base}/collections/{collection_key}"
    url = f"{base}/items"

    items = []
    start = 0
    while len(items) < max_items:
        params = {
            "format": "json",
            "include": "data",
            "itemType": "-attachment",
            "limit": min(100, max_items - len(items)),
            "start": start,
            "sort": "dateModified",
            "direction": "desc",
        }
        batch = zotero_request(url, params, api_key)
        if not batch:
            break
        items.extend(item.get("data", item) for item in batch)
        if len(batch) < params["limit"]:
            break
        start += len(batch)
    return items


def item_to_reference(item: Dict) -> Dict:
    creators = item.get("creators") or []
    authors = [clean_author(creator) for creator in creators if clean_author(creator)]
    tags = [
        tag.get("tag", "").strip()
        for tag in item.get("tags", [])
        if isinstance(tag, dict) and tag.get("tag")
    ]
    return {
        "title": item.get("title", ""),
        "authors": authors,
        "abstract": item.get("abstractNote", ""),
        "tags": tags,
        "publication": item.get("publicationTitle", ""),
        "date": item.get("date", ""),
        "dateModified": item.get("dateModified", ""),
    }


def fallback_profile() -> Dict:
    fallback = os.environ.get("ZOTERO_FALLBACK_KEYWORDS", "").strip()
    keywords = [
        part.strip().lower()
        for part in (fallback.split(",") if fallback else DEFAULT_KEYWORDS)
        if part.strip()
    ]
    return {
        "source": "fallback",
        "email": os.environ.get("ZOTERO_EMAIL", "lxh9748@163.com"),
        "references_count": 0,
        "keywords": [{"term": term, "weight": 8.0} for term in keywords],
        "authors": [],
        "core_authors": [],
        "summary": "Zotero is not configured yet; using fallback research keywords.",
    }


def build_profile(references: List[Dict]) -> Dict:
    keyword_scores = Counter()
    author_scores = Counter()
    recent_author_scores = Counter()

    for idx, ref in enumerate(references):
        title = normalize_text(ref.get("title"))
        abstract = normalize_text(ref.get("abstract"))
        tags = [normalize_term(tag) for tag in ref.get("tags", []) if tag]
        authors = [normalize_author(author) for author in ref.get("authors", []) if author]
        recency_weight = max(0.0, 1.0 - idx / 80.0)

        for tag in tags:
            if is_informative_term(tag):
                keyword_scores[tag] += 14
        for term in ngrams(tokenize(title), 1, 3):
            term = normalize_term(term)
            if is_informative_term(term):
                keyword_scores[term] += 5 * term_multiplier(term)
        for term in ngrams(tokenize(abstract), 1, 3):
            term = normalize_term(term)
            if is_informative_term(term):
                keyword_scores[term] += 1.0 * term_multiplier(term)
        for author in authors:
            author_scores[author] += 1
            recent_author_scores[author] += recency_weight

    keywords = [
        {"term": term, "weight": round(weight, 3)}
        for term, weight in keyword_scores.most_common(140)
        if len(term) >= 3 and is_informative_term(term)
    ]
    authors = []
    for author, count in author_scores.most_common(100):
        recent = recent_author_scores.get(author, 0.0)
        authors.append({"name": author, "weight": round(count + recent, 3), "count": count})

    core_authors = [
        item for item in authors
        if item.get("count", 0) >= 2 or item.get("weight", 0) >= 2.5
    ][:60]
    top_terms = ", ".join(item["term"] for item in keywords[:12])
    top_authors = ", ".join(item["name"] for item in core_authors[:8])
    summary = f"Interest profile inferred from Zotero papers. Top topics: {top_terms}"
    if top_authors:
        summary += f". Core authors: {top_authors}"
    return {
        "source": "zotero",
        "email": os.environ.get("ZOTERO_EMAIL", "lxh9748@163.com"),
        "references_count": len(references),
        "keywords": keywords,
        "authors": authors,
        "core_authors": core_authors,
        "summary": summary,
    }


def load_or_create_profile(profile_path: str) -> Dict:
    try:
        references = [item_to_reference(item) for item in fetch_zotero_items()]
    except Exception as exc:
        print(f"Zotero fetch failed, using fallback profile: {exc}", file=sys.stderr)
        references = []

    profile = build_profile(references) if references else fallback_profile()
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return profile


def profile_hash(profile: Dict) -> str:
    relevant = {
        "source": profile.get("source"),
        "references_count": profile.get("references_count"),
        "keywords": profile.get("keywords", [])[:80],
        "authors": profile.get("authors", [])[:80],
        "core_authors": profile.get("core_authors", [])[:80],
        "prompt_version": PROMPT_VERSION,
    }
    payload = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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


def cache_key(paper: Dict, prof_hash: str) -> str:
    return f"{PROMPT_VERSION}:{prof_hash}:{paper.get('id') or paper.get('abs') or paper.get('title')}"


def weighted_matches(text_parts: Dict[str, str], terms: List[Dict]) -> Tuple[float, List[str]]:
    score = 0.0
    matched = defaultdict(float)
    field_weights = {
        "title": 4.0,
        "summary": 1.7,
        "ai": 1.2,
        "categories": 0.8,
    }
    lowered_parts = {field: normalize_term(text) for field, text in text_parts.items()}
    for term_info in terms:
        term = normalize_term(term_info["term"])
        if len(term) < 3 or not is_informative_term(term):
            continue
        base_weight = min(float(term_info.get("weight", 1.0)), 80.0)
        pattern = term_pattern(term)
        term_score = 0.0
        for field, text in lowered_parts.items():
            if pattern.search(text):
                field_score = field_weights.get(field, 1.0) * math.log1p(base_weight)
                term_score += min(field_score, 7.0)
        if term_score:
            term_score *= term_multiplier(term)
            score += term_score
            matched[term] += term_score
    top_matches = [term for term, _ in sorted(matched.items(), key=lambda x: x[1], reverse=True)[:8]]
    return score, top_matches


def author_matches(paper: Dict, profile: Dict) -> Tuple[float, List[str]]:
    paper_authors = [normalize_author(author) for author in paper.get("authors", [])]
    paper_author_text = " | ".join(paper_authors)
    matched = []
    score = 0.0
    core_names = {item.get("name") for item in profile.get("core_authors", [])}
    for author in profile.get("authors", []):
        name = normalize_author(author.get("name", ""))
        if not name:
            continue
        if any(name == candidate or name in candidate or candidate in name for candidate in paper_authors):
            matched.append(name)
            base = math.log1p(float(author.get("weight", 1.0))) * 10.0
            score += base * (1.6 if name in core_names else 1.0)
        elif name and name in paper_author_text:
            matched.append(name)
            score += math.log1p(float(author.get("weight", 1.0))) * 4.0
    return score, matched[:8]


def rule_score_paper(item: Dict, profile: Dict) -> Dict:
    ai = item.get("AI") if isinstance(item.get("AI"), dict) else {}
    text_parts = {
        "title": normalize_text(item.get("title")),
        "summary": normalize_text(item.get("summary")),
        "ai": normalize_text(ai),
        "categories": normalize_text(item.get("categories")),
    }
    topic_raw, matched_topics = weighted_matches(text_parts, profile.get("keywords", []))
    author_raw, matched_authors = author_matches(item, profile)
    raw_score = topic_raw + author_raw * 1.8

    score = round(100 * raw_score / (raw_score + 32.0)) if raw_score > 0 else 0
    if matched_topics and not matched_authors:
        score = min(score, 78)
    if matched_authors and matched_topics:
        score = min(max(score, 55), 92)
    elif matched_authors:
        score = min(max(score, 45), 82)
    score = min(score, 94)

    if matched_topics or matched_authors:
        topic_text = ", ".join((matched_authors + matched_topics)[:5])
        reason = f"与 Zotero 兴趣画像中的 {topic_text} 匹配；规则评分已降低泛关键词的影响。"
    elif profile.get("source") == "fallback":
        reason = "Zotero 尚未配置，当前仅根据默认兴趣关键词给出低置信度排序。"
    else:
        reason = "与当前 Zotero 文献画像的直接匹配较弱，建议作为低优先级浏览。"

    return {
        "score": score,
        "stars": score_to_stars(score),
        "reason": reason,
        "matched_topics": matched_topics,
        "matched_authors": matched_authors,
        "profile_source": profile.get("source", "unknown"),
        "scoring_method": "rules",
        "rule_score": score,
    }


def score_to_stars(score: int) -> int:
    if score >= 88:
        return 5
    if score >= 72:
        return 4
    if score >= 50:
        return 3
    if score >= 30:
        return 2
    return 1


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


def llm_enabled() -> bool:
    if os.environ.get("ENABLE_LLM_RECOMMENDATION", "true").lower() in {"0", "false", "no"}:
        return False
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def call_llm_recommendation(item: Dict, profile: Dict, rule_rec: Dict) -> Optional[Dict]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = (
        os.environ.get("MODEL_NAME")
        or os.environ.get("OPENAI_MODEL_NAME")
        or "deepseek-chat"
    ).strip()
    if not api_key:
        return None

    ai = item.get("AI") if isinstance(item.get("AI"), dict) else {}
    profile_payload = {
        "summary": profile.get("summary"),
        "top_keywords": profile.get("keywords", [])[:35],
        "core_authors": profile.get("core_authors", [])[:35],
        "authors": profile.get("authors", [])[:50],
        "source": profile.get("source"),
    }
    paper_payload = {
        "id": item.get("id"),
        "title": item.get("title"),
        "authors": item.get("authors"),
        "categories": item.get("categories"),
        "abstract": item.get("summary"),
        "ai_summary": ai,
        "rule_recommendation": rule_rec,
    }
    system_prompt = (
        "You are a senior academic paper recommender. Score relevance to the user's Zotero library. "
        "Be strict: broad field overlap, telescope names, or generic keywords are not enough for a high score. "
        "Give high scores only when the scientific question, method, data, or recurring/core authors are clearly aligned."
    )
    user_prompt = (
        "Return only valid JSON with these keys: score, reason, topic_fit, method_fit, author_fit, "
        "novelty_fit, negative_reason, confidence. "
        "score is an integer 0-100. Use Chinese for textual fields. "
        "Star calibration implied by score: 88-100 five stars, 72-87 four stars, 50-71 three stars, "
        "30-49 two stars, 0-29 one star.\n\n"
        f"Zotero profile:\n{json.dumps(profile_payload, ensure_ascii=False)}\n\n"
        f"Paper:\n{json.dumps(paper_payload, ensure_ascii=False)}"
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
            timeout=45,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = extract_json_object(content)
        if not parsed:
            return None
        score = max(0, min(100, int(parsed.get("score", 0))))
        return {
            "score": score,
            "stars": score_to_stars(score),
            "reason": str(parsed.get("reason") or rule_rec.get("reason") or "").strip(),
            "topic_fit": str(parsed.get("topic_fit", "")).strip(),
            "method_fit": str(parsed.get("method_fit", "")).strip(),
            "author_fit": str(parsed.get("author_fit", "")).strip(),
            "novelty_fit": str(parsed.get("novelty_fit", "")).strip(),
            "negative_reason": str(parsed.get("negative_reason", "")).strip(),
            "confidence": str(parsed.get("confidence", "")).strip(),
            "matched_topics": rule_rec.get("matched_topics", []),
            "matched_authors": rule_rec.get("matched_authors", []),
            "profile_source": profile.get("source", "unknown"),
            "rule_score": rule_rec.get("rule_score", rule_rec.get("score", 0)),
            "scoring_method": "llm",
            "prompt_version": PROMPT_VERSION,
        }
    except Exception as exc:
        print(f"LLM recommendation failed for {item.get('id')}: {exc}", file=sys.stderr)
        return None


def score_paper(item: Dict, profile: Dict, cache: Dict[str, Dict], cache_path: str, prof_hash: str) -> Dict:
    rule_rec = rule_score_paper(item, profile)
    if not llm_enabled():
        return rule_rec

    key = cache_key(item, prof_hash)
    cached = cache.get(key)
    if cached and isinstance(cached.get("recommendation"), dict):
        rec = cached["recommendation"]
        rec.setdefault("matched_topics", rule_rec.get("matched_topics", []))
        rec.setdefault("matched_authors", rule_rec.get("matched_authors", []))
        return rec

    rec = call_llm_recommendation(item, profile, rule_rec) or rule_rec
    cache_item = {
        "cache_key": key,
        "paper_id": item.get("id"),
        "profile_hash": prof_hash,
        "prompt_version": PROMPT_VERSION,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "recommendation": rec,
    }
    cache[key] = cache_item
    append_cache(cache_path, cache_item)
    return rec


def main() -> None:
    args = parse_args()
    profile = load_or_create_profile(args.profile)
    prof_hash = profile_hash(profile)
    cache = load_cache(args.cache)

    data = []
    with open(args.data, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                item["recommendation"] = score_paper(item, profile, cache, args.cache, prof_hash)
                data.append(item)

    data.sort(
        key=lambda item: (
            item.get("recommendation", {}).get("score", 0),
            item.get("id", ""),
        ),
        reverse=True,
    )

    with open(args.data, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(
        f"Recommended {len(data)} papers using {profile.get('source')} profile "
        f"({profile.get('references_count', 0)} Zotero references, "
        f"LLM={'on' if llm_enabled() else 'off'}, profile_hash={prof_hash}).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

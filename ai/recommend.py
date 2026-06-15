import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Tuple

import dotenv
import requests


if os.path.exists(".env"):
    dotenv.load_dotenv()


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "between",
    "by", "can", "for", "from", "has", "have", "in", "into", "is", "it",
    "its", "may", "of", "on", "or", "our", "that", "the", "their", "this",
    "through", "to", "using", "via", "was", "we", "were", "with", "within",
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
    return parser.parse_args()


def normalize_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values())
    return str(value or "")


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]{2,}", text.lower())
    return [word for word in words if word not in STOPWORDS]


def ngrams(tokens: List[str], min_n: int = 1, max_n: int = 3) -> Iterable[str]:
    for n in range(min_n, max_n + 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            yield " ".join(tokens[idx : idx + n])


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
        "keywords": [{"term": term, "weight": 10.0} for term in keywords],
        "authors": [],
        "summary": "Zotero is not configured yet; using fallback research keywords.",
    }


def build_profile(references: List[Dict]) -> Dict:
    keyword_scores = Counter()
    author_scores = Counter()

    for ref in references:
        title = normalize_text(ref.get("title"))
        abstract = normalize_text(ref.get("abstract"))
        tags = [tag.lower() for tag in ref.get("tags", []) if tag]
        authors = [author.lower() for author in ref.get("authors", []) if author]

        for tag in tags:
            keyword_scores[tag] += 12
        for term in ngrams(tokenize(title), 1, 3):
            keyword_scores[term] += 5
        for term in ngrams(tokenize(abstract), 1, 3):
            keyword_scores[term] += 1
        for author in authors:
            author_scores[author] += 1

    keywords = [
        {"term": term, "weight": round(weight, 3)}
        for term, weight in keyword_scores.most_common(120)
        if len(term) >= 3
    ]
    authors = [
        {"name": author, "weight": count}
        for author, count in author_scores.most_common(60)
    ]
    top_terms = ", ".join(item["term"] for item in keywords[:12])
    return {
        "source": "zotero",
        "email": os.environ.get("ZOTERO_EMAIL", "lxh9748@163.com"),
        "references_count": len(references),
        "keywords": keywords,
        "authors": authors,
        "summary": f"Interest profile inferred from Zotero papers. Top topics: {top_terms}",
    }


def load_or_create_profile(profile_path: str) -> Dict:
    try:
        references = [item_to_reference(item) for item in fetch_zotero_items()]
    except Exception as exc:
        print(f"Zotero fetch failed, using fallback profile: {exc}", file=sys.stderr)
        references = []

    profile = build_profile(references) if references else fallback_profile()
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    with open(profile_path, "w") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return profile


def weighted_matches(text_parts: Dict[str, str], terms: List[Dict]) -> Tuple[float, List[str]]:
    score = 0.0
    matched = defaultdict(float)
    field_weights = {
        "title": 3.5,
        "authors": 2.5,
        "summary": 1.6,
        "ai": 1.2,
        "categories": 1.0,
    }
    lowered_parts = {field: text.lower() for field, text in text_parts.items()}
    for term_info in terms:
        term = term_info["term"].lower()
        if len(term) < 3:
            continue
        base_weight = float(term_info.get("weight", 1.0))
        term_score = 0.0
        for field, text in lowered_parts.items():
            if term in text:
                term_score += field_weights.get(field, 1.0) * math.log1p(base_weight)
        if term_score:
            score += term_score
            matched[term] += term_score
    top_matches = [term for term, _ in sorted(matched.items(), key=lambda x: x[1], reverse=True)[:8]]
    return score, top_matches


def score_paper(item: Dict, profile: Dict) -> Dict:
    ai = item.get("AI") if isinstance(item.get("AI"), dict) else {}
    text_parts = {
        "title": normalize_text(item.get("title")),
        "authors": normalize_text(item.get("authors")),
        "summary": normalize_text(item.get("summary")),
        "ai": normalize_text(ai),
        "categories": normalize_text(item.get("categories")),
    }

    topic_score, matched_topics = weighted_matches(text_parts, profile.get("keywords", []))
    author_score, matched_authors = weighted_matches(
        {"authors": text_parts["authors"]},
        [{"term": author["name"], "weight": author.get("weight", 1)} for author in profile.get("authors", [])],
    )

    raw_score = topic_score + author_score * 1.5
    score = min(100, round(raw_score * 3.2))
    if matched_topics and score < 35:
        score = 35
    if matched_authors and score < 45:
        score = 45

    stars = max(1, min(5, math.ceil(score / 20))) if score else 1
    if matched_topics or matched_authors:
        topic_text = ", ".join((matched_topics + matched_authors)[:5])
        reason = f"与 Zotero 兴趣画像中的 {topic_text} 等主题/作者匹配。"
    elif profile.get("source") == "fallback":
        reason = "Zotero 尚未配置，当前仅根据默认兴趣关键词给出低置信度排序。"
    else:
        reason = "与当前 Zotero 文献画像的直接匹配较弱，建议作为低优先级浏览。"

    return {
        "score": score,
        "stars": stars,
        "reason": reason,
        "matched_topics": matched_topics,
        "matched_authors": matched_authors,
        "profile_source": profile.get("source", "unknown"),
    }


def main() -> None:
    args = parse_args()
    profile = load_or_create_profile(args.profile)

    data = []
    with open(args.data, "r") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                item["recommendation"] = score_paper(item, profile)
                data.append(item)

    data.sort(
        key=lambda item: (
            item.get("recommendation", {}).get("score", 0),
            item.get("id", ""),
        ),
        reverse=True,
    )

    with open(args.data, "w") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(
        f"Recommended {len(data)} papers using {profile.get('source')} profile "
        f"({profile.get('references_count', 0)} Zotero references).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

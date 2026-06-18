import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from interest_policy import classify_topics, evaluate_policy


DATE_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})_AI_enhanced_")


def parse_date(value: object) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def canonical_id(value: object) -> str:
    return re.sub(r"v\d+$", "", str(value or ""))


def load_papers(data_dir: Path) -> List[Dict]:
    versions: Dict[str, List[Dict]] = {}
    for path in sorted(data_dir.glob("*_AI_enhanced_*.jsonl")):
        if path.name.startswith("top_"):
            continue
        match = DATE_FILE.match(path.name)
        fallback_date = parse_date(match.group(1)) if match else None
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    paper = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                paper_date = parse_date(paper.get("date")) or fallback_date
                if not paper_date:
                    continue
                paper["_date"] = paper_date
                key = canonical_id(paper.get("id")) or str(paper.get("title", ""))
                versions.setdefault(key, []).append(paper)

    papers = []
    for key, items in versions.items():
        items.sort(key=lambda item: (item["_date"], str(item.get("id", ""))), reverse=True)
        latest = items[0]
        latest["canonical_id"] = key
        latest["version_count"] = len(items)
        latest["previous_versions"] = [str(item.get("id", "")) for item in items[1:5]]
        papers.append(latest)
    return papers


def compact_paper(paper: Dict) -> Dict:
    ai = paper.get("AI") if isinstance(paper.get("AI"), dict) else {}
    recommendation = paper.get("recommendation") if isinstance(paper.get("recommendation"), dict) else {}
    policy = evaluate_policy(paper)
    score = int(recommendation.get("score", paper.get("selection", {}).get("score", 0)) or 0)
    if policy["mandatory"]:
        score = max(92, score)
    must_read_reason = next(
        (entry["label"] for entry in policy["adjustments"] if entry.get("points", 0) > 0),
        "strong-lensing priority rule",
    ) if policy["mandatory"] else ""
    return {
        "id": paper.get("id"),
        "canonical_id": paper.get("canonical_id"),
        "version_count": paper.get("version_count", 1),
        "previous_versions": paper.get("previous_versions", []),
        "title": paper.get("title", ""),
        "authors": paper.get("authors", []),
        "categories": paper.get("categories", []),
        "summary": ai.get("tldr") or paper.get("summary", ""),
        "date": paper["_date"].strftime("%Y-%m-%d"),
        "url": paper.get("abs") or f"https://arxiv.org/abs/{paper.get('id', '')}",
        "score": score,
        "stars": 5 if policy["mandatory"] else int(recommendation.get("stars", 1) or 1),
        "tier": policy["tier"] if policy["mandatory"] else recommendation.get("tier") or paper.get("selection", {}).get("tier") or policy["tier"],
        "mandatory": policy["mandatory"],
        "score_breakdown": policy["adjustments"] if policy["mandatory"] else recommendation.get("score_breakdown") or paper.get("selection", {}).get("adjustments") or policy["adjustments"],
        "must_read_reason": must_read_reason,
        "topics": classify_topics(paper),
    }


def load_archive_papers(data_dir: Path) -> List[Dict]:
    papers = []
    for path in sorted(data_dir.glob("*_archive.jsonl"), reverse=True):
        fallback_date = parse_date(path.name[:10])
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    paper = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                paper["_date"] = parse_date(paper.get("date")) or fallback_date
                if not paper["_date"]:
                    continue
                paper["canonical_id"] = canonical_id(paper.get("id"))
                paper["version_count"] = 1
                papers.append(paper)
    return papers


def build_payload(papers: Iterable[Dict], scope: str) -> Dict:
    compact = [compact_paper(paper) for paper in papers]
    compact.sort(key=lambda item: (item["mandatory"], item["score"], item["date"]), reverse=True)
    counts = Counter(topic for paper in compact for topic in paper["topics"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": scope,
        "paper_count": len(compact),
        "topics": [{"name": topic, "count": count} for topic, count in counts.most_common()],
        "papers": compact,
    }


def load_reports(data_dir: Path) -> List[Dict]:
    reports = []
    for path in sorted(data_dir.glob("*_selection_report.json"), reverse=True)[:30]:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            report["date"] = path.name[:10]
            reports.append(report)
        except Exception:
            continue
    return reports


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    papers = load_papers(data_dir)
    if not papers:
        return
    latest_date = max(paper["_date"] for paper in papers)
    year_cutoff = latest_date - timedelta(days=365)
    year_papers = [paper for paper in papers if paper["_date"] >= year_cutoff]
    week_cutoff = latest_date - timedelta(days=7)
    week_papers = [paper for paper in papers if paper["_date"] >= week_cutoff]

    year_payload = build_payload(year_papers, "year")
    year_payload["selection_reports"] = load_reports(data_dir)
    all_payload = build_payload(papers, "all")
    weekly = build_payload(week_papers, "week")
    weekly["papers"] = weekly["papers"][:10]
    weekly["must_read"] = [paper for paper in build_payload(week_papers, "week")["papers"] if paper["mandatory"]]
    archive_payload = build_payload(load_archive_papers(data_dir), "archive")

    outputs = {
        "statistics_year.json": year_payload,
        "statistics_all.json": all_payload,
        "weekly_digest.json": weekly,
        "archive_index.json": archive_payload,
    }
    for filename, payload in outputs.items():
        (data_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"Generated {filename}: {payload.get('paper_count', 0)} papers")


if __name__ == "__main__":
    main()

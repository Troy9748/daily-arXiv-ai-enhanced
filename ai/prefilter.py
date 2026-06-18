import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from interest_policy import evaluate_policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select the daily AI processing pool before expensive LLM work.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--report")
    parser.add_argument("--profile", default="../data/zotero_profile.json")
    parser.add_argument("--max-papers", type=int, default=int(os.environ.get("DAILY_RECOMMENDATION_LIMIT", "24")))
    parser.add_argument("--min-score", type=int, default=int(os.environ.get("DAILY_RECOMMENDATION_MIN_SCORE", "35")))
    parser.add_argument("--merge-existing-archive", action="store_true")
    return parser.parse_args()


def load_jsonl(path: Path) -> List[Dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def profile_bonus(paper: Dict, profile: Dict) -> Dict:
    text = (str(paper.get("title", "")) + " " + str(paper.get("summary", ""))).lower()
    matched = []
    raw = 0.0
    for item in profile.get("keywords", [])[:80]:
        term = str(item.get("term", "")).lower().strip()
        if len(term) >= 4 and term in text:
            raw += min(5.0, math.log1p(float(item.get("weight", 1.0))))
            matched.append(term)
    negative = []
    penalty = 0.0
    for item in profile.get("negative_keywords", [])[:80]:
        term = str(item.get("term", "")).lower().strip()
        if len(term) >= 4 and term in text:
            penalty += min(6.0, math.log1p(float(item.get("weight", 1.0))))
            negative.append(term)
    return {"points": max(-25, min(20, round(raw - penalty))), "matched": matched[:6], "negative_matched": negative[:6]}


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    archive_path = Path(args.archive) if args.archive else data_path.with_name(data_path.stem + "_archive.jsonl")
    report_path = Path(args.report) if args.report else data_path.with_name(data_path.stem + "_selection_report.json")
    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    except Exception:
        profile = {}

    rows = load_jsonl(data_path)
    if args.merge_existing_archive and archive_path.exists():
        rows.extend(load_jsonl(archive_path))
        deduped = {}
        for paper in rows:
            deduped[paper.get("id") or paper.get("title")] = paper
        rows = list(deduped.values())
    for paper in rows:
        selection = evaluate_policy(paper)
        bonus = profile_bonus(paper, profile)
        selection["profile_bonus"] = bonus
        selection["score"] = min(100, selection["score"] + bonus["points"])
        if not selection["mandatory"] and selection["score"] >= 42:
            selection["tier"] = "recommended"
        paper["selection"] = selection

    rows.sort(key=lambda paper: (paper["selection"]["mandatory"], paper["selection"]["score"], paper.get("id", "")), reverse=True)
    mandatory = [paper for paper in rows if paper["selection"]["mandatory"]]
    optional = [
        paper for paper in rows
        if not paper["selection"]["mandatory"] and paper["selection"]["score"] >= args.min_score
    ]
    selected = mandatory + optional[:max(0, args.max_papers - len(mandatory))]
    selected_ids = {paper.get("id") for paper in selected}
    archived = [paper for paper in rows if paper.get("id") not in selected_ids]
    for paper in archived:
        paper["selection"]["tier"] = "archive"

    write_jsonl(data_path, selected)
    write_jsonl(archive_path, archived)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_count": len(rows),
        "selected_count": len(selected),
        "archived_count": len(archived),
        "mandatory_count": len(mandatory),
        "limit": args.max_papers,
        "minimum_score": args.min_score,
        "estimated_ai_calls_saved": len(archived) * 3,
        "selected_ids": [paper.get("id") for paper in selected],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()

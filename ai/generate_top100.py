import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


TOP_CONFIGS = [
    ("top_year_100_AI_enhanced.jsonl", 365, 100, "recent year Top 100"),
    ("top_month_20_AI_enhanced.jsonl", 30, 20, "recent month Top 20"),
    ("top_week_10_AI_enhanced.jsonl", 7, 10, "recent week Top 10"),
]


def parse_date(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    for pattern in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], pattern)
        except ValueError:
            continue
    return None


def date_from_path(path: Path) -> Optional[datetime]:
    match = re.match(r"(\d{4}-\d{2}-\d{2})_AI_enhanced_", path.name)
    if not match:
        return None
    return parse_date(match.group(1))


def iter_history_files(data_dir: Path) -> Iterable[Path]:
    language = os.environ.get("LANGUAGE", "").strip()
    pattern = f"*_AI_enhanced_{language}.jsonl" if language else "*_AI_enhanced_*.jsonl"
    for path in sorted(data_dir.glob(pattern)):
        if path.name.startswith("top_"):
            continue
        yield path


def load_papers(data_dir: Path) -> List[Dict]:
    papers = []
    for path in iter_history_files(data_dir):
        fallback_date = date_from_path(path)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    paper = json.loads(line)
                except json.JSONDecodeError:
                    continue
                paper_date = parse_date(paper.get("date")) or fallback_date
                if paper_date:
                    paper["date"] = paper_date.strftime("%Y-%m-%d")
                    paper["_sort_date"] = paper_date
                papers.append(paper)
    return papers


def recommendation_score(paper: Dict) -> Tuple[int, int, str]:
    rec = paper.get("recommendation") if isinstance(paper.get("recommendation"), dict) else {}
    score = int(rec.get("score", 0) or 0)
    stars = int(rec.get("stars", 1) or 1)
    return score, stars, paper.get("id", "")


def dedupe_keep_best(papers: Iterable[Dict]) -> List[Dict]:
    best: Dict[str, Dict] = {}
    for paper in papers:
        key = paper.get("id") or paper.get("abs") or paper.get("title")
        if not key:
            continue
        current = best.get(key)
        if current is None or recommendation_score(paper) > recommendation_score(current):
            best[key] = paper
    return list(best.values())


def build_top_list(papers: List[Dict], days: int, limit: int) -> List[Dict]:
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    filtered = [
        paper for paper in papers
        if isinstance(paper.get("_sort_date"), datetime) and paper["_sort_date"] >= cutoff
    ]
    if not filtered and papers:
        all_dates = [paper["_sort_date"] for paper in papers if isinstance(paper.get("_sort_date"), datetime)]
        latest = max(all_dates) if all_dates else now
        cutoff = latest - timedelta(days=days)
        filtered = [
            paper for paper in papers
            if isinstance(paper.get("_sort_date"), datetime) and paper["_sort_date"] >= cutoff
        ]
    deduped = dedupe_keep_best(filtered)
    deduped.sort(
        key=lambda paper: (
            paper.get("recommendation", {}).get("score", 0),
            paper.get("recommendation", {}).get("stars", 0),
            paper.get("_sort_date", datetime.min),
            paper.get("id", ""),
        ),
        reverse=True,
    )
    result = []
    for paper in deduped[:limit]:
        clean = dict(paper)
        clean.pop("_sort_date", None)
        result.append(clean)
    return result


def write_jsonl(path: Path, rows: List[Dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_markdown(repo_root: Path, jsonl_path: Path) -> None:
    convert_script = repo_root / "to_md" / "convert.py"
    if not convert_script.exists() or not jsonl_path.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(convert_script), "--data", str(jsonl_path)],
            cwd=repo_root / "to_md",
            check=True,
        )
    except Exception as exc:
        print(f"Markdown render skipped for {jsonl_path.name}: {exc}", file=sys.stderr)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    papers = load_papers(data_dir)
    if not papers:
        print("No historical AI-enhanced papers found.", file=sys.stderr)
        return

    generated = {}
    for filename, days, limit, label in TOP_CONFIGS:
        rows = build_top_list(papers, days, limit)
        output = data_dir / filename
        write_jsonl(output, rows)
        generated[filename] = rows
        render_markdown(repo_root, output)
        print(f"Generated {label}: {len(rows)} papers -> {filename}", file=sys.stderr)

    # Keep the old filename working for existing deployments/bookmarks.
    legacy = data_dir / "top_100_AI_enhanced.jsonl"
    write_jsonl(legacy, generated.get("top_year_100_AI_enhanced.jsonl", []))
    render_markdown(repo_root, legacy)
    print("Updated legacy top_100_AI_enhanced.jsonl from recent-year Top 100.", file=sys.stderr)


if __name__ == "__main__":
    main()

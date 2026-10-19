#!/usr/bin/env python3
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch arXiv papers for explicit historical dates using the arXiv API."
    )
    parser.add_argument("dates", nargs="+", help="Dates or ranges, e.g. 2026-06-22 or 2026-06-18:2026-06-23")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--categories",
        default=os.environ.get("CATEGORIES", "astro-ph.GA, astro-ph.CO"),
        help="Comma-separated arXiv categories.",
    )
    parser.add_argument("--max-results-per-category", type=int, default=300)
    parser.add_argument("--force", action="store_true", help="Overwrite non-empty existing raw JSONL files.")
    return parser.parse_args()


def expand_dates(values: List[str]) -> List[date]:
    expanded = []
    for value in values:
        if ":" in value:
            start_raw, end_raw = value.split(":", 1)
            current = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
            while current <= end:
                expanded.append(current)
                current += timedelta(days=1)
        else:
            expanded.append(date.fromisoformat(value))
    return sorted(set(expanded))


def normalize_arxiv_id(value: str) -> str:
    value = value.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", value)


ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def text_of(entry: ET.Element, path: str) -> str:
    element = entry.find(path, ATOM_NS)
    return re.sub(r"\s+", " ", element.text or "").strip() if element is not None else ""


def paper_to_row(entry: ET.Element) -> Dict:
    arxiv_id = normalize_arxiv_id(text_of(entry, "atom:id"))
    categories = [category.attrib["term"] for category in entry.findall("atom:category", ATOM_NS)]
    authors = [text_of(author, "atom:name") for author in entry.findall("atom:author", ATOM_NS)]
    comment = text_of(entry, "arxiv:comment")
    return {
        "id": arxiv_id,
        "categories": categories,
        "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
        "abs": f"https://arxiv.org/abs/{arxiv_id}",
        "authors": authors,
        "title": text_of(entry, "atom:title"),
        "comment": comment or None,
        "summary": text_of(entry, "atom:summary"),
    }


def fetch_xml(url: str) -> ET.Element:
    request = urllib.request.Request(url, headers={"User-Agent": "daily-arxiv-backfill/1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return ET.fromstring(response.read())
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 4:
                raise
            retry_after = error.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 5 * 2**attempt
            print(f"arXiv returned HTTP {error.code}; retrying in {delay}s")
            time.sleep(delay)
        except (TimeoutError, urllib.error.URLError) as error:
            if attempt == 4:
                raise
            delay = 5 * 2**attempt
            print(f"arXiv request failed ({error}); retrying in {delay}s")
            time.sleep(delay)

    raise AssertionError("unreachable")


def fetch_day(day: date, categories: Iterable[str], max_results_per_category: int) -> List[Dict]:
    wanted = set(categories)
    stamp = day.strftime("%Y%m%d")
    category_query = " OR ".join(f"cat:{category}" for category in wanted)
    params = {
        "search_query": f"({category_query}) AND submittedDate:[{stamp}0000 TO {stamp}2359]",
        "start": 0,
        "max_results": max_results_per_category * len(wanted),
    }
    root = fetch_xml(f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}")
    rows_by_id = {row["id"]: row for row in map(paper_to_row, root.findall("atom:entry", ATOM_NS))}
    return list(rows_by_id.values())


def write_jsonl(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    if not categories:
        raise SystemExit("No categories configured.")

    for day in expand_dates(args.dates):
        output = data_dir / f"{day.isoformat()}.jsonl"
        if output.exists() and output.stat().st_size > 0 and not args.force:
            print(f"skip {day.isoformat()}: {output} already exists")
            continue
        rows = fetch_day(day, categories, args.max_results_per_category)
        if not rows:
            raise SystemExit(f"No arXiv papers found for {day.isoformat()}; refusing to write an empty file.")
        write_jsonl(output, rows)
        print(f"wrote {len(rows)} papers for {day.isoformat()} to {output}")


if __name__ == "__main__":
    main()

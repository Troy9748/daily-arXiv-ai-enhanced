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
from datetime import date, datetime, timedelta
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


OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}


def text_of(entry: ET.Element, path: str) -> str:
    element = entry.find(path, OAI_NS)
    return re.sub(r"\s+", " ", element.text or "").strip() if element is not None else ""


def paper_to_row(entry: ET.Element) -> Dict:
    arxiv_id = normalize_arxiv_id(text_of(entry, "arxiv:id"))
    categories = text_of(entry, "arxiv:categories").split()
    authors = []
    for author in entry.findall("arxiv:authors/arxiv:author", OAI_NS):
        name = " ".join(
            filter(
                None,
                [
                    text_of(author, "arxiv:forenames"),
                    text_of(author, "arxiv:keyname"),
                    text_of(author, "arxiv:suffix"),
                ],
            )
        )
        if name:
            authors.append(name)
    comment = text_of(entry, "arxiv:comments")
    return {
        "id": arxiv_id,
        "categories": categories,
        "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
        "abs": f"https://arxiv.org/abs/{arxiv_id}",
        "authors": authors,
        "title": text_of(entry, "arxiv:title"),
        "comment": comment or None,
        "summary": text_of(entry, "arxiv:abstract"),
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

    raise AssertionError("unreachable")


def fetch_day(day: date, categories: Iterable[str], _max_results_per_category: int) -> List[Dict]:
    wanted = set(categories)
    rows_by_id: Dict[str, Dict] = {}
    until = min(day + timedelta(days=4), date.today())
    params = {
        "verb": "ListRecords",
        "from": day.isoformat(),
        "until": until.isoformat(),
        "set": "physics:astro-ph",
        "metadataPrefix": "arXiv",
    }
    while True:
        root = fetch_xml(f"https://oaipmh.arxiv.org/oai?{urllib.parse.urlencode(params)}")
        for entry in root.findall(".//arxiv:arXiv", OAI_NS):
            if text_of(entry, "arxiv:created") != day.isoformat():
                continue
            row = paper_to_row(entry)
            if not wanted.intersection(row["categories"]):
                continue
            rows_by_id[row["id"]] = row
        token = text_of(root, ".//oai:resumptionToken")
        if not token:
            break
        params = {"verb": "ListRecords", "resumptionToken": token}
        time.sleep(3)
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
        write_jsonl(output, rows)
        print(f"wrote {len(rows)} papers for {day.isoformat()} to {output}")


if __name__ == "__main__":
    main()

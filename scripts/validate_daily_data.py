#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def validate(path: Path) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{path} is missing or empty")

    ids = set()
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
            if not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("categories"), list):
                raise ValueError(f"{path}:{line_number}: missing id or categories")
            if row["id"] in ids:
                raise ValueError(f"{path}:{line_number}: duplicate id {row['id']}")
            ids.add(row["id"])
            count += 1

    if count == 0:
        raise ValueError(f"{path} contains no records")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a daily arXiv JSONL output.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        count = validate(args.path)
    except ValueError as error:
        raise SystemExit(f"validation failed: {error}") from error
    print(f"validated {count} records in {args.path}")


if __name__ == "__main__":
    main()

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from recommend import load_or_create_profile, score_paper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing *_AI_enhanced_*.jsonl files",
    )
    parser.add_argument(
        "--profile",
        default="data/zotero_profile.json",
        help="Where to cache the Zotero interest profile",
    )
    parser.add_argument(
        "--language",
        default=os.environ.get("LANGUAGE", ""),
        help="Optional language filter, such as Chinese or English",
    )
    parser.add_argument(
        "--regenerate-md",
        action="store_true",
        help="Regenerate the matching data/YYYY-MM-DD.md files after scoring",
    )
    return parser.parse_args()


def find_ai_files(data_dir: Path, language: str) -> List[Path]:
    pattern = f"*_AI_enhanced_{language}.jsonl" if language else "*_AI_enhanced_*.jsonl"
    return sorted(data_dir.glob(pattern))


def score_file(path: Path, profile: Dict) -> int:
    items = []
    with path.open("r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            item["recommendation"] = score_paper(item, profile)
            items.append(item)

    items.sort(
        key=lambda item: (
            item.get("recommendation", {}).get("score", 0),
            item.get("id", ""),
        ),
        reverse=True,
    )

    with path.open("w") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(items)


def regenerate_markdown(path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    convert_script = repo_root / "to_md" / "convert.py"
    subprocess.run(
        [sys.executable, str(convert_script), "--data", str(path)],
        cwd=repo_root / "to_md",
        check=True,
    )


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    profile_path = Path(args.profile).resolve()
    files = find_ai_files(data_dir, args.language.strip())

    if not files:
        print(f"No AI-enhanced jsonl files found in {data_dir}", file=sys.stderr)
        return

    profile = load_or_create_profile(str(profile_path))
    print(
        f"Using {profile.get('source')} profile "
        f"({profile.get('references_count', 0)} Zotero references).",
        file=sys.stderr,
    )

    total_items = 0
    for path in files:
        count = score_file(path, profile)
        total_items += count
        if args.regenerate_md:
            regenerate_markdown(path)
        print(f"Backfilled {count:4d} papers in {path.name}", file=sys.stderr)

    print(
        f"Backfilled {len(files)} files and {total_items} papers.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

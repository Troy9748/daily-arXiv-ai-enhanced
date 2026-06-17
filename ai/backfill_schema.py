import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


RECOMMEND_PROMPT_VERSION = "recommend-v2-author-weighted"
ARTIFACT_PROMPT_VERSION = "paper-artifacts-v3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--language", default=os.environ.get("LANGUAGE", ""))
    parser.add_argument(
        "--max-files",
        type=int,
        default=int(os.environ.get("BACKFILL_MAX_FILES", "5") or "5"),
        help="Maximum historical files to backfill. Use -1 for all outdated files.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> List[Dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def needs_recommendation_backfill(rows: List[Dict]) -> bool:
    return bool(rows)


def needs_artifact_backfill(rows: List[Dict]) -> bool:
    for row in rows:
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, dict):
            return True
        if not str(artifacts.get("abstract_zh", "")).strip():
            return True
        if not str(artifacts.get("conclusion_zh", "")).strip():
            return True
        if not isinstance(artifacts.get("figures"), list):
            return True
    return False


def iter_files(data_dir: Path, language: str):
    pattern = f"*_AI_enhanced_{language}.jsonl" if language else "*_AI_enhanced_*.jsonl"
    for path in sorted(data_dir.glob(pattern), reverse=True):
        if path.name.startswith("top_"):
            continue
        yield path


def run_step(command: List[str], cwd: Path) -> None:
    print("Running:", " ".join(command), file=sys.stderr)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = (repo_root / args.data_dir).resolve() if not Path(args.data_dir).is_absolute() else Path(args.data_dir)
    ai_dir = repo_root / "ai"
    processed = 0

    for path in iter_files(data_dir, args.language):
        rows = read_jsonl(path)
        if not rows:
            continue
        rec_needed = needs_recommendation_backfill(rows)
        artifact_needed = needs_artifact_backfill(rows)
        if not rec_needed and not artifact_needed:
            continue

        if args.max_files >= 0 and processed >= args.max_files:
            break

        rel_path = os.path.relpath(path, ai_dir)
        print(
            f"Backfilling {path.name}: recommendation={rec_needed}, artifacts={artifact_needed}",
            file=sys.stderr,
        )
        if rec_needed:
            run_step([sys.executable, "recommend.py", "--data", rel_path], ai_dir)
        if artifact_needed:
            run_step([sys.executable, "artifacts.py", "--data", rel_path], ai_dir)
        processed += 1

    print(f"Backfilled {processed} historical files with outdated schema.", file=sys.stderr)


if __name__ == "__main__":
    main()

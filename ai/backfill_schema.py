import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set


RECOMMEND_PROMPT_VERSION = "recommend-v2-author-weighted"
ARTIFACT_PROMPT_VERSION = "paper-artifacts-v4-caption-math"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--language", default=os.environ.get("LANGUAGE", ""))
    parser.add_argument(
        "--current-file",
        default=os.environ.get("CURRENT_DAILY_FILE", ""),
        help="Current daily JSONL filename to exclude from historical backfill.",
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get("BACKFILL_STATE_FILE", "data/backfill_state.json"),
        help="Persistent progress file used to rotate through historical files.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=1,
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
        if any(
            "\\" in str(figure.get("caption_en", "")) and "\\(" not in str(figure.get("caption_en", ""))
            for figure in artifacts.get("figures", [])
            if isinstance(figure, dict)
        ):
            return True
    return False


def iter_files(data_dir: Path, language: str, current_file: str):
    pattern = f"*_AI_enhanced_{language}.jsonl" if language else "*_AI_enhanced_*.jsonl"
    current_name = Path(current_file).name if current_file else ""
    for path in sorted(data_dir.glob(pattern)):
        if path.name.startswith("top_"):
            continue
        if current_name and path.name == current_name:
            continue
        yield path


def load_state(path: Path, language: str) -> Dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    languages = payload.setdefault("languages", {})
    state = languages.setdefault(language or "all", {"completed_files": []})
    if not isinstance(state.get("completed_files"), list):
        state["completed_files"] = []
    return payload


def save_state(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_step(command: List[str], cwd: Path) -> None:
    print("Running:", " ".join(command), file=sys.stderr)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = (repo_root / args.data_dir).resolve() if not Path(args.data_dir).is_absolute() else Path(args.data_dir)
    state_path = (repo_root / args.state_file).resolve() if not Path(args.state_file).is_absolute() else Path(args.state_file)
    ai_dir = repo_root / "ai"
    processed = 0
    files = list(iter_files(data_dir, args.language, args.current_file))
    payload = load_state(state_path, args.language)
    state = payload["languages"][args.language or "all"]
    completed: Set[str] = set(state["completed_files"])
    current_name = Path(args.current_file).name if args.current_file else ""
    if current_name:
        completed.add(current_name)
        state["completed_files"] = sorted(completed)
        save_state(state_path, payload)

    pending = [path for path in files if path.name not in completed]

    print(
        f"Historical backfill: {len(pending)} pending of {len(files)} files; "
        f"current file excluded={Path(args.current_file).name or 'none'}.",
        file=sys.stderr,
    )

    for path in pending:
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
        completed.add(path.name)
        state["completed_files"] = sorted(completed)
        save_state(state_path, payload)

    if pending:
        print(f"Backfilled {processed} historical files; progress saved to {state_path}.", file=sys.stderr)
    else:
        print("Historical backfill is complete; no files will be rescored again.", file=sys.stderr)


if __name__ == "__main__":
    main()

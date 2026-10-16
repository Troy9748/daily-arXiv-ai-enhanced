import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import TestCase, main


SPEC = importlib.util.spec_from_file_location(
    "validate_daily_data", Path(__file__).parents[1] / "scripts/validate_daily_data.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ValidateDailyDataTest(TestCase):
    def write(self, lines):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "daily.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_accepts_valid_unique_rows(self):
        path = self.write([json.dumps({"id": "1", "categories": ["astro-ph.GA"]})])
        self.assertEqual(MODULE.validate(path), 1)

    def test_rejects_empty_and_duplicate_rows(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            MODULE.validate(self.write([]))

        row = json.dumps({"id": "1", "categories": []})
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            MODULE.validate(self.write([row, row]))


if __name__ == "__main__":
    main()

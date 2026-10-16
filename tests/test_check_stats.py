import importlib.util
from pathlib import Path
from unittest import TestCase, main, mock


SPEC = importlib.util.spec_from_file_location(
    "check_stats", Path(__file__).parents[1] / "daily_arxiv/daily_arxiv/check_stats.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CheckStatsTest(TestCase):
    @mock.patch.object(MODULE, "perform_deduplication", return_value="no_data")
    def test_no_data_has_distinct_failure_code(self, _perform):
        with self.assertRaises(SystemExit) as error:
            MODULE.main()
        self.assertEqual(error.exception.code, 3)


if __name__ == "__main__":
    main()

import importlib.util
import io
import urllib.error
from pathlib import Path
from unittest import TestCase, main, mock


SPEC = importlib.util.spec_from_file_location(
    "fetch_arxiv_by_date", Path(__file__).parents[1] / "scripts/fetch_arxiv_by_date.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return b'<feed xmlns="http://www.w3.org/2005/Atom" />'


class FetchQueryTest(TestCase):
    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_retries_rate_limit(self, urlopen, sleep):
        urlopen.side_effect = [
            urllib.error.HTTPError("url", 429, "rate limited", {"Retry-After": "7"}, io.BytesIO()),
            Response(),
        ]

        MODULE.fetch_xml("https://example.test/oai")

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(7)

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_retries_read_timeout(self, urlopen, sleep):
        urlopen.side_effect = [TimeoutError("read timed out"), Response()]

        MODULE.fetch_xml("https://example.test/oai")

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_extracts_only_requested_announcement_date(self):
        parser = MODULE.AnnouncementParser("Tue, 27 Oct 2026")
        parser.feed(
            '<h3>Tue, 27 Oct 2026 (showing 1 entry)</h3>'
            '<a href="/abs/2610.33154" title="Abstract">arXiv:2610.33154</a>'
            '<h3>Mon, 26 Oct 2026 (showing 1 entry)</h3>'
            '<a href="/abs/2610.32837" title="Abstract">arXiv:2610.32837</a>'
        )

        self.assertEqual(parser.ids, ["2610.33154"])


if __name__ == "__main__":
    main()

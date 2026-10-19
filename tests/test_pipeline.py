import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase, main, mock


sys.path.insert(0, str(Path(__file__).parents[1] / "daily_arxiv"))
if importlib.util.find_spec("arxiv") is None:
    arxiv = ModuleType("arxiv")
    arxiv.Client = mock.Mock()
    arxiv.Search = mock.Mock()
    sys.modules["arxiv"] = arxiv
if importlib.util.find_spec("scrapy") is None:
    scrapy = ModuleType("scrapy")
    exceptions = ModuleType("scrapy.exceptions")
    exceptions.DropItem = type("DropItem", (Exception,), {})
    sys.modules.update({"scrapy": scrapy, "scrapy.exceptions": exceptions})

from daily_arxiv.pipelines import DailyArxivPipeline, DropItem


class DailyArxivPipelineTest(TestCase):
    @mock.patch("daily_arxiv.pipelines.arxiv.Client")
    def test_drops_cross_listed_duplicate_after_enrichment(self, client_class):
        paper = SimpleNamespace(
            authors=[SimpleNamespace(name="Author")],
            title="Title",
            categories=["astro-ph.GA", "astro-ph.CO"],
            comment=None,
            summary="Summary",
        )
        client_class.return_value.results.return_value = iter([paper])
        pipeline = DailyArxivPipeline()

        pipeline.process_item({"id": "2610.23016", "categories": ["astro-ph.GA"]}, None)

        with self.assertRaisesRegex(DropItem, "2610.23016"):
            pipeline.process_item({"id": "2610.23016", "categories": ["astro-ph.CO"]}, None)
        self.assertEqual(client_class.return_value.results.call_count, 1)


if __name__ == "__main__":
    main()

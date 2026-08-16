import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from wechat_article_builder import (
    build_wechat_html,
    delete_previous_wechat_files,
    generate_daily_intro,
    journal_abbreviation,
    normalize_hydrology_terms,
)


class BriefBehaviorTests(unittest.TestCase):
    def test_missing_abstract_stops_after_three_attempts(self):
        session = Mock()
        item = {"DOI": "10.1234/test"}
        with (
            patch.object(main, "fetch_openalex_abstract", return_value="") as openalex,
            patch.object(main, "fetch_semantic_scholar_abstract", return_value="") as semantic,
            patch.object(main.time, "sleep"),
        ):
            result = main.resolve_crossref_abstract(session, item, "test@example.com")
        self.assertEqual(result, main.ABSTRACT_NOT_AVAILABLE)
        self.assertEqual(openalex.call_count, 3)
        self.assertEqual(semantic.call_count, 3)

    def test_intro_lists_every_translated_title(self):
        papers = [SimpleNamespace(), SimpleNamespace()]
        entries = [{"chinese_title": "洪水风险"}, {"chinese_title": "干旱预测"}]
        intro = generate_daily_intro(papers, entries, datetime(2026, 8, 14).date())
        self.assertEqual(
            intro,
            "本期共收录 2 篇水文气候相关论文，题目如下：1）洪水风险；2）干旱预测。",
        )

    def test_required_terminology_and_journal_abbreviation(self):
        self.assertEqual(journal_abbreviation("Communications Earth & Environment"), "CEE")
        self.assertEqual(normalize_hydrology_terms("Downscaling and CEAE"), "降尺度 and CEE")

    def test_html_normalizes_downscaling(self):
        paper = SimpleNamespace(
            title="A study",
            authors="A. Author",
            journal="Communications Earth & Environment",
            url="https://example.com",
            doi="10.1234/test",
        )
        _, _, body = build_wechat_html(
            [paper],
            [{"chinese_title": "Downscaling研究", "summary": "downscaling方法"}],
            datetime(2026, 8, 14).date(),
        )
        self.assertIn("CEE", body)
        self.assertIn("降尺度研究", body)
        self.assertNotIn("CEAE", body)
        self.assertNotIn("downscaling", body.lower())

    def test_deletes_only_previous_day_wechat_files(self):
        run_date = datetime(2026, 8, 14, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            yesterday_html = outputs / "wechat-post-2026-08-13.html"
            yesterday_json = outputs / "wechat-post-2026-08-13.json"
            older = outputs / "wechat-post-2026-08-12.html"
            for path in (yesterday_html, yesterday_json, older):
                path.write_text("test", encoding="utf-8")
            removed = delete_previous_wechat_files(run_date, outputs)
            self.assertEqual(set(removed), {yesterday_html, yesterday_json})
            self.assertTrue(older.exists())


if __name__ == "__main__":
    unittest.main()

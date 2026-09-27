import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from wechat_article_builder import (
    CHINESE_TRANSLATION_SYSTEM_PROMPT,
    build_wechat_html,
    delete_previous_wechat_files,
    generate_daily_intro,
    journal_abbreviation,
    normalize_hydrology_terms,
    strip_abstract_heading,
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

    def test_prompt_requires_full_abstract_translation(self):
        prompt = CHINESE_TRANSLATION_SYSTEM_PROMPT.lower()
        self.assertIn("translate each available english abstract completely", prompt)
        self.assertIn("do not summarize", prompt)
        self.assertIn("do not infer content from the title or metadata", prompt)
        self.assertIn("do not add or translate an 'abstract' heading", prompt)

    def test_strips_only_leading_abstract_heading(self):
        self.assertEqual(strip_abstract_heading("Abstract: Flood risk is rising."), "Flood risk is rising.")
        self.assertEqual(strip_abstract_heading("ABSTRACT—Flood risk is rising."), "Flood risk is rising.")
        self.assertEqual(strip_abstract_heading("This abstract describes floods."), "This abstract describes floods.")

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
            [{"chinese_title": "Downscaling研究", "chinese_abstract": "downscaling方法"}],
            datetime(2026, 8, 14).date(),
        )
        self.assertIn("CEE", body)
        self.assertIn("降尺度研究", body)
        self.assertNotIn("CEAE", body)
        self.assertNotIn("downscaling", body.lower())
        self.assertNotIn("摘要翻译", body)
        self.assertNotIn("摘要译文", body)

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



class ScreeningRegressionTests(unittest.TestCase):
    @staticmethod
    def paper(journal="Journal of Hydrology", rank=1, doi="10.1234/test"):
        return main.Paper(
            title="Rainfall-runoff responses in catchments",
            authors="A. Author",
            journal=journal,
            publication_date="2026-09-11",
            doi=doi,
            url=f"https://doi.org/{doi}",
            topic="catchment processes and ungauged prediction",
            topic_rank=rank,
            abstract=main.ABSTRACT_NOT_AVAILABLE,
        )

    def test_reference_article_matches_without_abstract(self):
        item = {
            "title": [
                "A global classification of hydrologic functional diversity "
                "in gauged and ungauged catchments"
            ],
            "DOI": "10.1038/s44221-026-00699-6",
        }
        match = main.match_ranked_topic(item)
        self.assertIsNotNone(match)
        self.assertEqual(match[1], "catchment processes and ungauged prediction")

    def test_related_catchment_terms_match_in_all_metadata_fields(self):
        terms = (
            "Catchment classification",
            "Hydrological functional diversity",
            "Runoff generation",
            "Hydrologic similarity",
            "Prediction in ungauged basins",
            "Rainfall persistence",
            "Hydrological model transferability",
        )
        for field in ("title", "abstract", "subject"):
            for term in terms:
                with self.subTest(field=field, term=term):
                    self.assertIsNotNone(main.match_ranked_topic({field: [term]}))

    def test_rainfall_runoff_dash_variants_match(self):
        for dash in ("-", "–", "—", "‐", "‑", "−", "– "):
            with self.subTest(dash=dash):
                self.assertIsNotNone(
                    main.match_ranked_topic({"title": [f"Rainfall{dash}runoff relationships"]})
                )

    def test_generic_functional_diversity_does_not_match(self):
        self.assertIsNone(
            main.match_ranked_topic(
                {"title": ["A classification of functional diversity in proteins"]}
            )
        )

    def test_existing_flood_topic_keeps_its_rank(self):
        self.assertEqual(
            main.match_ranked_topic({"title": ["Flood prediction in ungauged basins"]}),
            (1, "flood"),
        )

    def test_portfolio_priority_applies_before_topic_and_limit(self):
        ordinary = self.paper(rank=1, doi="10.1234/ordinary")
        for journal in (
            "Nature", "Science", "Science Advances", "Nature Climate Change",
            "Nature Geoscience", "Nature Communications",
            "Communications Earth & Environment", "Nature Sustainability", "Nature Water",
        ):
            with self.subTest(journal=journal):
                priority = self.paper(journal, rank=13, doi="10.1234/priority")
                self.assertEqual(main.select_papers([ordinary, priority], set(), 1), [priority])

    def test_priority_does_not_include_unrelated_science_journals(self):
        ordinary = self.paper(rank=1, doi="10.1234/ordinary")
        unrelated = self.paper("Science of The Total Environment", rank=13)
        self.assertEqual(main.select_papers([unrelated, ordinary], set(), 1), [ordinary])

    def test_sent_priority_papers_are_excluded_and_topic_order_is_preserved(self):
        sent = self.paper("Nature", rank=1, doi="10.1234/sent")
        lower_topic = self.paper("Nature Water", rank=13, doi="10.1234/lower")
        higher_topic = self.paper("Science Advances", rank=2, doi="10.1234/higher")
        ordinary = self.paper(rank=1, doi="10.1234/ordinary")
        self.assertEqual(
            main.select_papers([ordinary, lower_topic, sent, higher_topic], {sent.doi}),
            [higher_topic, lower_topic, ordinary],
        )

    def test_journal_priority_normalizes_case_whitespace_and_html(self):
        ordinary = self.paper(rank=1, doi="10.1234/ordinary")
        priority = self.paper("  Communications Earth &amp; Environment  ", rank=13)
        self.assertEqual(main.select_papers([ordinary, priority], set(), 1), [priority])

    def test_relevance_uses_independent_gpt5_default_and_compatible_request(self):
        papers = [self.paper("Nature Water"), self.paper("Science", doi="10.1234/other")]
        for override, expected in ((None, "gpt-5"), ("", "gpt-5"), ("gpt-5-mini", "gpt-5-mini")):
            with self.subTest(override=override):
                env = {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-4o-mini"}
                if override is not None:
                    env["OPENAI_RELEVANCE_MODEL"] = override
                client = Mock()
                client.chat.completions.create.return_value = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                        "decisions": [
                            {"index": 0, "relevant": True, "reason": "Hydrology"},
                            {"index": 1, "relevant": False, "reason": "Unrelated"},
                        ]
                    })))]
                )
                with (
                    patch.dict(main.os.environ, env, clear=True),
                    patch.object(main, "OpenAI", return_value=client),
                ):
                    self.assertEqual(main.filter_hydroclimate_relevant_papers(papers), [papers[0]])
                kwargs = client.chat.completions.create.call_args.kwargs
                self.assertEqual(kwargs["model"], expected)
                self.assertNotIn("temperature", kwargs)
                self.assertEqual(kwargs["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()

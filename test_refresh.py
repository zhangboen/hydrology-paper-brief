import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import main
import refresh_wechat_post as refresh


class RefreshTests(unittest.TestCase):
    def test_refresh_reconsiders_today_but_excludes_earlier_papers(self):
        today = main.Paper("Today", "", "Nature Water", "2026-09-27", "today", "", "", 13, "")
        earlier = main.Paper("Earlier", "", "Nature", "2026-09-26", "earlier", "", "", 1, "")
        new = main.Paper("New", "", "Journal of Hydrology", "2026-09-27", "new", "", "", 1, "")
        now = datetime(2026, 9, 27, 12, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selected.json"
            source.write_text(json.dumps({"generated_at": now.isoformat(), "papers": [{"doi": "today"}]}))
            with (
                patch.object(main, "get_required_env", return_value="test@example.com"),
                patch.object(main, "load_sent_dois", return_value={"today", "earlier"}),
                patch.object(main, "fetch_candidate_papers", return_value=[earlier, new, today]) as search,
                patch.object(main, "filter_hydroclimate_relevant_papers", side_effect=lambda p: p) as screen,
                patch.object(refresh, "write_wechat_article", return_value=True) as write,
                patch.object(main, "write_selected_papers") as export,
                patch.object(main, "save_sent_dois") as save,
            ):
                self.assertEqual(refresh.refresh(source, now), [today, new])
                search.assert_called_once()
                screen.assert_called_once_with([earlier, new, today])
                write.assert_called_once_with([today, new], now, main.OUTPUTS_DIR)
                export.assert_called_once_with([today, new], now)
                save.assert_called_once_with({"today", "earlier", "new"})

    def test_generation_failure_preserves_doi_history(self):
        now = datetime(2026, 9, 27, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selected.json"
            source.write_text(json.dumps({"generated_at": now.isoformat(), "papers": []}))
            with (
                patch.object(main, "get_required_env", return_value="test@example.com"),
                patch.object(main, "load_sent_dois", return_value={"earlier"}),
                patch.object(main, "fetch_candidate_papers", return_value=[]),
                patch.object(main, "filter_hydroclimate_relevant_papers", return_value=[]),
                patch.object(main, "save_sent_dois") as save,
                patch.object(refresh, "write_wechat_article") as write,
            ):
                with self.assertRaises(RuntimeError):
                    refresh.refresh(source, now)
                save.assert_not_called()
                write.assert_not_called()

    def test_old_source_is_rejected_before_search(self):
        now = datetime(2026, 9, 27, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selected.json"
            source.write_text(json.dumps({"generated_at": "2026-09-26T08:00:00+08:00", "papers": []}))
            with patch.object(main, "fetch_candidate_papers") as search:
                with self.assertRaises(ValueError):
                    refresh.refresh(source, now)
                search.assert_not_called()


if __name__ == "__main__":
    unittest.main()

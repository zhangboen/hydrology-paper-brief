import copy
import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import Mock, patch

import daily


def lesson_fixture():
    return {
        "title": "Small talk that feels natural",
        "concept": {"key": "follow-up-questions", "name_en": "Follow-up questions",
                    "name_zh": "追问", "explanation_zh": "用简短追问延续对话。",
                    "examples": ["How did it go?", "What was that like?"],
                    "common_mistake_zh": "不要只说 yes。"},
        "vocabulary": [dict(term=term, ipa_us="/tɛst/", pronunciation_tip_zh="留意重音。",
                            meaning_zh="测试释义", explain_in_english="A clear explanation.",
                            usage_note_zh="用于日常交流。", examples=["Example one.", "Example two."])
                       for term in ("catch up", "settle in", "a heads-up")],
        "scene": {"title": "Meeting a colleague by the coffee machine", "context_zh": "初次见面",
                  "script_en": "A: " + "This is a sentence for the length validation test. " * 16,
                  "translation_zh": "中文翻译。", "practice_tip_zh": "分角色朗读。"},
        "reading": {"title": "An unexpected conversation", "genre": "personal diary",
                    "text_en": "This is a sentence for the length validation test. " * 26,
                    "summary_zh": "一段对话。", "questions": [
                        {"question": "What happened?", "answer": "A conversation."},
                        {"question": "How did it feel?", "answer": "Natural."}]},
    }


class ValidationTests(unittest.TestCase):
    def test_complete_lesson(self):
        daily.validate(lesson_fixture(), [])

    def test_only_three_new_terms(self):
        lesson = lesson_fixture()
        lesson["vocabulary"].append(copy.deepcopy(lesson["vocabulary"][0]))
        with self.assertRaisesRegex(ValueError, "three"):
            daily.validate(lesson, [])

    def test_duplicate_terms_normalized(self):
        lesson = lesson_fixture()
        lesson["vocabulary"][2]["term"] = "CATCH-UP"
        with self.assertRaisesRegex(ValueError, "repeats"):
            daily.validate(lesson, [])

    def test_prior_history_prevents_repetition(self):
        row = {"concept_key": "old-concept", "concept_name": "Old concept", "terms": ["SETTLE IN"],
               "scene": "Old scene", "reading": "Old reading"}
        with self.assertRaisesRegex(ValueError, "repeats"):
            daily.validate(lesson_fixture(), [row])
        row["terms"] = []
        row["concept_key"] = "follow up questions"
        with self.assertRaisesRegex(ValueError, "already taught"):
            daily.validate(lesson_fixture(), [row])

    def test_reject_short_reading_and_missing_ipa(self):
        lesson = lesson_fixture()
        lesson["reading"]["text_en"] = "Too short."
        with self.assertRaisesRegex(ValueError, "Reading must"):
            daily.validate(lesson, [])
        lesson = lesson_fixture()
        lesson["vocabulary"][0]["ipa_us"] = "test"
        with self.assertRaisesRegex(ValueError, "IPA"):
            daily.validate(lesson, [])

    def test_render_escapes_model_html(self):
        lesson = lesson_fixture()
        lesson["title"] = '<script>alert("x")</script>'
        text, document = daily.render(lesson, "2026-10-01", 1)
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;script&gt;", document)
        self.assertIn("Explain it in English", text)
        self.assertIn("中文理解", text)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.record = {"date": "2026-10-01", "number": 1, "status": "prepared", "lesson": lesson_fixture()}
        self.settings = {"SMTP_HOST": "smtp.example.org", "SMTP_PORT": "465",
                         "SMTP_USER": "sender@example.org", "SMTP_PASSWORD": "dummy",
                         "ENGLISH_RECIPIENT": "recipient@example.org"}

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_settings_fail_before_delivery(self):
        with self.assertRaisesRegex(RuntimeError, "Missing email"):
            daily.smtp_settings()

    @patch("daily.connect_smtp")
    def test_already_sent_does_not_connect(self, connect):
        self.record["status"] = "sent"
        daily.send(self.state, self.record, self.state, False)
        connect.assert_not_called()

    @patch("daily.connect_smtp")
    def test_uncertain_state_blocks_automatic_resend(self, connect):
        for status in ("sending", "delivery_uncertain"):
            self.record["status"] = status
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                daily.send(self.state, self.record, self.state, False)
        connect.assert_not_called()

    def test_acceptance_persists_sent_and_closes(self):
        server = Mock()
        with patch("daily.smtp_settings", return_value=self.settings), patch("daily.connect_smtp", return_value=server):
            daily.send(self.state, self.record, self.state, False)
        server.send_message.assert_called_once()
        server.close.assert_called_once()
        saved = daily.read_json(self.state / "lessons/2026-10-01.json")
        self.assertEqual(saved["status"], "sent")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.org")
        self.assertTrue(message.is_multipart())

    def test_interrupted_submission_is_not_retried(self):
        server = Mock()
        server.send_message.side_effect = smtplib.SMTPServerDisconnected("network lost")
        with patch("daily.smtp_settings", return_value=self.settings), patch("daily.connect_smtp", return_value=server):
            with self.assertRaisesRegex(RuntimeError, "verify inbox"):
                daily.send(self.state, self.record, self.state, False)
        self.assertEqual(self.record["status"], "delivery_uncertain")
        server.send_message.assert_called_once()

    def test_explicit_rejection_allows_later_retry(self):
        server = Mock()
        server.send_message.side_effect = smtplib.SMTPDataError(451, b"try later")
        with patch("daily.smtp_settings", return_value=self.settings), patch("daily.connect_smtp", return_value=server):
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                daily.send(self.state, self.record, self.state, False)
        self.assertEqual(self.record["status"], "prepared")

    def test_state_persistence_failure_prevents_submission(self):
        server = Mock()
        with patch("daily.smtp_settings", return_value=self.settings), patch("daily.connect_smtp", return_value=server), \
             patch("daily.persist", side_effect=RuntimeError("state push failed")):
            with self.assertRaisesRegex(RuntimeError, "push failed"):
                daily.send(self.state, self.record, self.state, True)
        server.send_message.assert_not_called()

    def test_connection_retries_are_bounded(self):
        with patch("daily.smtplib.SMTP_SSL", side_effect=TimeoutError), patch("daily.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "three attempts"):
                daily.connect_smtp(self.settings)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()

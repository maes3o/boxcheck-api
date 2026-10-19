"""Tests for POST /fix-request and GET /fix-request/config.
Telegram is always mocked — no real message is ever sent from the test run."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import main

BASE = {
    "name": "Олена",
    "contact": "@olena_print",
    "note": "Потрібно до п'ятниці",
    "website": "",
    "context": {
        "product": "business_card",
        "printMethod": "offset",
        "critical": 2,
        "warning": 1,
        "info": 0,
        "findings": ["Виліт (Bleed)", "Безпечна зона (Safe Zone)"],
    },
}


def payload(**over):
    p = {**BASE, "context": {**BASE["context"]}}
    p.update(over)
    return p


class FixRequestTests(unittest.TestCase):
    def setUp(self):
        main.limiter.reset()
        self.client = TestClient(main.app)

    @patch("main.send_telegram_message", return_value=True)
    def test_sends_prefixed_message_with_context(self, mock_send):
        resp = self.client.post("/fix-request", json=payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        self.assertTrue(text.startswith("🔧 ЗАЯВКА: Виправте за мене"))
        for expected in ("@olena_print", "Олена", "business_card", "offset",
                         "критичних 2", "попереджень 1", "1. Виліт (Bleed)",
                         "2. Безпечна зона (Safe Zone)", "Нотатка: Потрібно до п'ятниці", "Київ"):
            self.assertIn(expected, text)

    @patch("main.send_telegram_message", return_value=True)
    def test_optional_fields_may_be_omitted(self, mock_send):
        resp = self.client.post("/fix-request", json={"contact": "+380671234567"})
        self.assertEqual(resp.status_code, 200)
        text = mock_send.call_args[0][0]
        self.assertIn("+380671234567", text)
        self.assertNotIn("Критичні проблеми:", text)
        self.assertNotIn("Нотатка:", text)

    @patch("main.send_telegram_message", return_value=True)
    def test_honeypot_returns_success_but_sends_nothing(self, mock_send):
        resp = self.client.post("/fix-request", json=payload(website="http://spam.example"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        mock_send.assert_not_called()

    @patch("main.send_telegram_message")
    def test_contact_is_required(self, mock_send):
        self.assertEqual(self.client.post("/fix-request", json={"note": "x"}).status_code, 422)
        self.assertEqual(self.client.post("/fix-request", json={"contact": "  "}).status_code, 400)
        mock_send.assert_not_called()

    @patch("main.send_telegram_message")
    def test_note_over_500_chars_is_truncated_not_rejected(self, mock_send):
        mock_send.return_value = True
        self.client.post("/fix-request", json=payload(note="я" * 900))
        text = mock_send.call_args[0][0]
        self.assertIn("я" * 500, text)
        self.assertNotIn("я" * 501, text)

    @patch("main.send_telegram_message", return_value=True)
    def test_rejects_more_than_three_findings(self, mock_send):
        ctx = {**BASE["context"], "findings": ["a", "b", "c", "d"]}
        self.assertEqual(self.client.post("/fix-request", json=payload(context=ctx)).status_code, 422)
        mock_send.assert_not_called()

    @patch("main.send_telegram_message", return_value=True)
    def test_unsafe_ids_and_control_chars_are_neutralised(self, mock_send):
        ctx = {**BASE["context"], "product": "x y\nFAKE LINE", "findings": ["ok\x00name"]}
        self.client.post("/fix-request", json=payload(context=ctx, name="A\x07B"))
        text = mock_send.call_args[0][0]
        self.assertNotIn("FAKE LINE", text)
        self.assertNotIn("\x00", text)
        self.assertNotIn("\x07", text)

    @patch("main.send_telegram_message", return_value=False)
    def test_returns_502_when_telegram_fails(self, mock_send):
        resp = self.client.post("/fix-request", json=payload())
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["detail"]["code"], "telegram_failed")

    @patch("main.send_telegram_message", return_value=True)
    def test_rate_limited_per_ip_after_five_requests(self, mock_send):
        codes = [self.client.post("/fix-request", json=payload()).status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])
        self.assertEqual(mock_send.call_count, 5)

    @patch("main.send_telegram_message", return_value=True)
    def test_message_never_contains_file_content_fields(self, mock_send):
        # The payload model has no place for PDF bytes/text: unknown keys are ignored.
        self.client.post("/fix-request", json=payload(pdf_text="SECRET LAYOUT TEXT", file="AAAA"))
        self.assertNotIn("SECRET LAYOUT TEXT", mock_send.call_args[0][0])


class FixRequestConfigTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_reads_card_from_env_each_call(self):
        with patch.dict(os.environ, {"FIX_SERVICE_CARD_NUMBER": "1111 2222 3333 4444", "FIX_SERVICE_CARD_NAME": "Іван І."}):
            self.assertEqual(self.client.get("/fix-request/config").json(),
                             {"cardNumber": "1111 2222 3333 4444", "cardName": "Іван І."})

    def test_empty_strings_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIX_SERVICE_CARD_NUMBER", None)
            os.environ.pop("FIX_SERVICE_CARD_NAME", None)
            self.assertEqual(self.client.get("/fix-request/config").json(), {"cardNumber": "", "cardName": ""})


if __name__ == "__main__":
    unittest.main()

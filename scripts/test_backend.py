"""Backend tests for the feedback endpoint and the unhandled-error Telegram
alert throttle. No real Telegram or Google Sheets API calls are made —
send_telegram_message / send_to_google_sheets are mocked throughout.
Run with: python scripts/test_backend.py
(uses only stdlib unittest + fastapi's bundled TestClient, no new deps)
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi.testclient import TestClient

import main


class FeedbackEndpointTests(unittest.TestCase):
    def setUp(self):
        main.limiter.reset()
        self.client = TestClient(main.app)

    @patch("main.send_telegram_message", return_value=True)
    def test_feedback_sends_message_with_text_and_marker(self, mock_send):
        resp = self.client.post("/api/feedback", json={"message": "The bleed check looks wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        self.assertIn("BoxCheck Feedback", sent_text)
        self.assertIn("The bleed check looks wrong", sent_text)
        self.assertNotIn("Reply to:", sent_text)

    @patch("main.send_telegram_message", return_value=True)
    def test_feedback_includes_email_when_given(self, mock_send):
        resp = self.client.post(
            "/api/feedback",
            json={"message": "Found a bug", "email": "user@example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        sent_text = mock_send.call_args[0][0]
        self.assertIn("Reply to: user@example.com", sent_text)

    @patch("main.send_telegram_message")
    def test_feedback_rejects_empty_message(self, mock_send):
        resp = self.client.post("/api/feedback", json={"message": "   "})
        self.assertEqual(resp.status_code, 400)
        mock_send.assert_not_called()

    @patch("main.send_telegram_message", return_value=False)
    def test_feedback_returns_502_when_telegram_delivery_fails(self, mock_send):
        resp = self.client.post("/api/feedback", json={"message": "Hello"})
        self.assertEqual(resp.status_code, 502)


class FeedbackGoogleSheetsTests(unittest.TestCase):
    def setUp(self):
        main.limiter.reset()
        self.client = TestClient(main.app)
        self._orig_url = main.GOOGLE_SHEETS_WEBHOOK_URL
        main.GOOGLE_SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/fake/exec"

    def tearDown(self):
        main.GOOGLE_SHEETS_WEBHOOK_URL = self._orig_url

    @patch("main.send_telegram_message", return_value=True)
    @patch("main.send_to_google_sheets")
    def test_feedback_duplicates_to_sheets_with_correct_args(self, mock_sheets, mock_telegram):
        resp = self.client.post(
            "/api/feedback",
            json={"message": "Hi there", "email": "user@example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        mock_telegram.assert_called_once()
        mock_sheets.assert_called_once_with("Hi there", "user@example.com")

    def test_send_to_google_sheets_posts_expected_body_directly(self):
        with patch("main.httpx.post") as mock_post:
            main.send_to_google_sheets("Hello sheets", "")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], main.GOOGLE_SHEETS_WEBHOOK_URL)
        self.assertEqual(kwargs["json"], {"feedback": "Hello sheets", "email": ""})

    def test_send_to_google_sheets_swallows_request_failures(self):
        with patch("main.httpx.post", side_effect=httpx.ConnectTimeout("slow script.google.com")):
            try:
                main.send_to_google_sheets("Hello", "")
            except Exception as exc:  # noqa: BLE001 - asserting nothing escapes
                self.fail(f"send_to_google_sheets raised unexpectedly: {exc}")

    @patch("main.send_telegram_message", return_value=True)
    def test_feedback_succeeds_even_when_sheets_delivery_fails(self, mock_telegram):
        with patch("main.httpx.post", side_effect=httpx.ConnectTimeout("slow script.google.com")):
            resp = self.client.post("/api/feedback", json={"message": "Hi"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        mock_telegram.assert_called_once()

    @patch("main.send_to_google_sheets")
    def test_feedback_returns_502_when_telegram_fails_but_still_logs_to_sheets(self, mock_sheets):
        with patch("main.send_telegram_message", return_value=False):
            resp = self.client.post("/api/feedback", json={"message": "Hi"})
        self.assertEqual(resp.status_code, 502)
        mock_sheets.assert_called_once_with("Hi", "")


class ServerErrorNotifyThrottleTests(unittest.TestCase):
    def setUp(self):
        main._error_notify_last_sent.clear()

    @patch("main.send_telegram_message", return_value=True)
    def test_first_error_of_a_type_sends_notification(self, mock_send):
        main.notify_server_error(ValueError("boom"), "/check")
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        self.assertIn("ValueError", sent_text)
        self.assertIn("boom", sent_text)
        self.assertIn("/check", sent_text)

    @patch("main.send_telegram_message", return_value=True)
    def test_repeated_same_type_error_is_throttled(self, mock_send):
        main.notify_server_error(ValueError("boom"), "/check")
        main.notify_server_error(ValueError("boom again"), "/check")
        mock_send.assert_called_once()

    @patch("main.send_telegram_message", return_value=True)
    def test_different_error_type_is_not_throttled(self, mock_send):
        main.notify_server_error(ValueError("boom"), "/check")
        main.notify_server_error(KeyError("missing"), "/check")
        self.assertEqual(mock_send.call_count, 2)

    @patch("main.send_telegram_message", return_value=True)
    def test_throttle_window_expiring_allows_a_new_notification(self, mock_send):
        with patch("main.time.monotonic", return_value=1000.0):
            main.notify_server_error(ValueError("boom"), "/check")
        with patch("main.time.monotonic", return_value=1000.0 + main.ERROR_NOTIFY_THROTTLE_SECONDS + 1):
            main.notify_server_error(ValueError("boom"), "/check")
        self.assertEqual(mock_send.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

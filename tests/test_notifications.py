import unittest
from unittest.mock import MagicMock, patch

import requests

from app.notifications import FailureReport, describe_failure, send_webhook


class DescribeFailureTests(unittest.TestCase):
    def test_no_failure_returns_none(self) -> None:
        self.assertIsNone(describe_failure(0, 0))
        self.assertIsNone(describe_failure(0, 0, "tutto ok, nessun problema qui"))

    def test_pipeline_failure_is_reported(self) -> None:
        report = describe_failure(1, 0)
        self.assertIn("pipeline", report.message)
        self.assertIn("codice di uscita 1", report.message)
        self.assertNotIn("health check", report.message)

    def test_health_failure_is_reported(self) -> None:
        report = describe_failure(0, 1)
        self.assertIn("health check", report.message)
        self.assertNotIn("pipeline:", report.message)

    def test_both_failures_are_reported_together(self) -> None:
        report = describe_failure(1, 1)
        self.assertIn("pipeline", report.message)
        self.assertIn("health check", report.message)

    def test_title_is_stable_and_does_not_leak_internals(self) -> None:
        report = describe_failure(1, 0)
        self.assertEqual("NewBoxOffice: guasto nella pipeline settimanale", report.title)

    def test_prefers_error_lines_from_the_log_over_the_tail(self) -> None:
        log = "\n".join([
            "=== inizio ===",
            "Caricati 20 record weekly su PostgreSQL",
            "Traceback (most recent call last):",
            "RuntimeError: connessione rifiutata",
            "=== fine: pipeline=1 health=0 ===",
        ])
        report = describe_failure(1, 0, log)
        self.assertIn("RuntimeError: connessione rifiutata", report.message)
        self.assertNotIn("Caricati 20 record", report.message)

    def test_falls_back_to_the_log_tail_without_error_markers(self) -> None:
        log = "\n".join(f"riga {i}" for i in range(1, 10))
        report = describe_failure(1, 0, log)
        self.assertIn("riga 9", report.message)
        self.assertNotIn("riga 1\n", report.message)  # solo le ultime righe, non tutto il log

    def test_empty_log_lines_are_ignored(self) -> None:
        report = describe_failure(1, 0, "\n\n   \nsolo questa riga\n\n")
        self.assertIn("solo questa riga", report.message)


class SendWebhookTests(unittest.TestCase):
    REPORT = FailureReport(title="Titolo", message="Messaggio")

    def test_no_url_configured_does_not_attempt_anything(self) -> None:
        with patch("app.notifications.requests.post") as post:
            self.assertFalse(send_webhook(self.REPORT, None))
        post.assert_not_called()

    def test_successful_post_includes_both_slack_and_discord_keys(self) -> None:
        response = MagicMock()
        with patch("app.notifications.requests.post", return_value=response) as post:
            self.assertTrue(send_webhook(self.REPORT, "https://hooks.example/x"))

        response.raise_for_status.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertIn("Titolo", payload["text"])
        self.assertIn("Messaggio", payload["text"])
        self.assertEqual(payload["text"], payload["content"])
        self.assertEqual("https://hooks.example/x", post.call_args.args[0])

    def test_network_failure_is_swallowed_and_reported_as_not_sent(self) -> None:
        with patch("app.notifications.requests.post", side_effect=requests.ConnectionError("down")):
            self.assertFalse(send_webhook(self.REPORT, "https://hooks.example/x"))

    def test_http_error_is_swallowed(self) -> None:
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("app.notifications.requests.post", return_value=response):
            self.assertFalse(send_webhook(self.REPORT, "https://hooks.example/x"))


if __name__ == "__main__":
    unittest.main()

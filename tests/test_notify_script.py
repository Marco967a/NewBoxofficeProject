import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import notify


class NotifyScriptTests(unittest.TestCase):
    def _run(self, argv):
        with patch.object(sys, "argv", ["notify.py", *argv]):
            notify.main()

    def test_no_failure_prints_and_writes_nothing(self) -> None:
        with patch("scripts.notify.send_webhook") as webhook, patch("builtins.print") as mock_print:
            self._run(["--pipeline-exit", "0", "--health-exit", "0"])
        webhook.assert_not_called()
        mock_print.assert_not_called()

    def test_failure_writes_the_out_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "notify.txt"
            with patch("scripts.notify.get_secret", return_value=None):
                self._run(["--pipeline-exit", "1", "--health-exit", "0", "--out", str(out)])

            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("pipeline", content)

    def test_webhook_is_attempted_when_configured(self) -> None:
        with patch("scripts.notify.get_secret", return_value="https://hooks.example/x"), \
                patch("scripts.notify.send_webhook", return_value=True) as webhook:
            self._run(["--pipeline-exit", "1", "--health-exit", "0"])

        webhook.assert_called_once()
        self.assertEqual("https://hooks.example/x", webhook.call_args[0][1])

    def test_missing_log_file_does_not_crash(self) -> None:
        with patch("scripts.notify.get_secret", return_value=None):
            self._run(["--pipeline-exit", "1", "--health-exit", "0", "--log", "C:\\non\\esiste.log"])

    def test_invalid_arguments_exit_with_the_standard_argparse_code(self) -> None:
        script = REPO_ROOT / "scripts" / "notify.py"
        result = subprocess.run(
            [sys.executable, str(script), "--pipeline-exit", "not-a-number"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(2, result.returncode)

    def test_run_swallows_an_unexpected_internal_error_without_raising(self) -> None:
        """run() (usata da __main__) non deve mai lasciar passare un'eccezione: un guasto qui non deve
        mascherare l'esito reale della pipeline con un crash del wrapper di notifica."""
        with patch("scripts.notify.describe_failure", side_effect=RuntimeError("boom")):
            with patch.object(sys, "argv", ["notify.py", "--pipeline-exit", "1", "--health-exit", "0"]):
                notify.run()  # non deve sollevare


if __name__ == "__main__":
    unittest.main()

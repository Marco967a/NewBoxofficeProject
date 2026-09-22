import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import manage_secrets


class ManageSecretsVaultFailureTests(unittest.TestCase):
    def _run(self, argv):
        with patch.object(sys, "argv", ["manage_secrets.py", *argv]):
            manage_secrets.main()

    def test_vault_failure_on_set_exits_cleanly_without_a_raw_traceback(self) -> None:
        with patch("scripts.manage_secrets.getpass.getpass", return_value="un-valore"), \
                patch("scripts.manage_secrets.set_secret", side_effect=RuntimeError("Impossibile scrivere 'x'")):
            with self.assertRaises(SystemExit) as ctx:
                self._run(["set", "x"])

        self.assertIn("Impossibile scrivere", str(ctx.exception))

    def test_vault_failure_on_delete_exits_cleanly(self) -> None:
        with patch("scripts.manage_secrets.delete_secret", side_effect=RuntimeError("Impossibile eliminare 'x'")):
            with self.assertRaises(SystemExit) as ctx:
                self._run(["delete", "x"])

        self.assertIn("Impossibile eliminare", str(ctx.exception))

    def test_successful_set_does_not_raise(self) -> None:
        with patch("scripts.manage_secrets.getpass.getpass", return_value="un-valore"), \
                patch("scripts.manage_secrets.set_secret") as set_secret, \
                patch("scripts.manage_secrets._stored", return_value="un-valore"):
            self._run(["set", "x"])  # non deve sollevare
        set_secret.assert_called_once_with("x", "un-valore")


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import MagicMock, patch

from app.db import get_connection


ENV = {"DB_HOST": "localhost", "DB_NAME": "boxoffice", "DB_USER": "boxoffice_app", "DB_PORT": "5432"}


class GetConnectionContractTests(unittest.TestCase):
    """get_connection è un involucro sottile su psycopg2.connect: qui si verifica solo il contratto
    commit/rollback/close, non riesercitato altrove."""

    def _mock_connect(self):
        conn = MagicMock()
        return patch("app.db.psycopg2.connect", return_value=conn), conn

    def test_commits_and_closes_on_success(self) -> None:
        patcher, conn = self._mock_connect()
        with patch.dict(os.environ, ENV, clear=True), patcher, \
                patch("app.settings.get_secret", return_value="pw"):
            with get_connection() as yielded:
                self.assertIs(conn, yielded)

        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        conn.close.assert_called_once()

    def test_rolls_back_and_closes_on_exception_which_still_propagates(self) -> None:
        patcher, conn = self._mock_connect()
        with patch.dict(os.environ, ENV, clear=True), patcher, \
                patch("app.settings.get_secret", return_value="pw"):
            with self.assertRaises(ValueError):
                with get_connection():
                    raise ValueError("boom")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_owner_role_falls_back_to_app_when_not_configured_and_still_connects(self) -> None:
        """Nessun blocco anticipato: se 'owner' non è configurato si ripiega su 'app' (vedi
        get_db_config), e qui il DDL funziona o fallisce solo quando viene davvero eseguito
        (app/migrations.py traduce un eventuale errore di permessi in un messaggio leggibile)."""
        patcher, conn = self._mock_connect()
        # password dell'app risolta, quella dell'owner no: è il ripiego che si vuole osservare
        secrets = {"db:boxoffice_app": "pw-app", "db:boxoffice_owner": None}
        with patch.dict(os.environ, ENV, clear=True), patcher, \
                patch("app.settings.get_secret", side_effect=lambda name, *a, **k: secrets.get(name)):
            with get_connection(role="owner") as yielded:
                self.assertIs(conn, yielded)

        conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()

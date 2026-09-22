"""Test unitari (nessun Postgres reale) sulla traduzione degli errori di permesso in app/migrations.py.

La copertura end-to-end delle migrazioni (schema reale, checksum, lock) resta in
tests/test_db_integration.py, opt-in con RUN_DB_TESTS=1.
"""
import unittest
from unittest.mock import MagicMock

import psycopg2

from app.migrations import _current_user, _permission_error, apply_pending


class CurrentUserTests(unittest.TestCase):
    def test_reads_user_from_the_dsn_without_a_query(self) -> None:
        conn = MagicMock()
        conn.get_dsn_parameters.return_value = {"user": "boxoffice_app", "dbname": "boxoffice"}

        self.assertEqual("boxoffice_app", _current_user(conn))
        conn.cursor.assert_not_called()  # dopo un errore di permessi la transazione è già abortita

    def test_missing_user_key_falls_back_to_a_placeholder(self) -> None:
        conn = MagicMock()
        conn.get_dsn_parameters.return_value = {}

        self.assertEqual("?", _current_user(conn))


class PermissionErrorTests(unittest.TestCase):
    def test_message_names_the_role_and_the_fix(self) -> None:
        conn = MagicMock()
        conn.get_dsn_parameters.return_value = {"user": "boxoffice_app"}
        original = psycopg2.errors.InsufficientPrivilege("permission denied for schema public")

        error = _permission_error(conn, original)

        self.assertIsInstance(error, RuntimeError)
        self.assertIn("boxoffice_app", str(error))
        self.assertIn("setup_db_roles.py", str(error))
        self.assertIs(original, error.__cause__)  # non perde la traccia originale


class FakeCursor:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self._on_execute(sql)

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []


class ApplyPendingPermissionTests(unittest.TestCase):
    def test_insufficient_privilege_on_the_first_ddl_statement_becomes_a_readable_error(self) -> None:
        """Il caso reale che ha rotto la CI: un unico ruolo per tutto ('app' == superutente altrove,
        ma qui senza CREATE), owner non configurato -> ripiego silenzioso su 'app' -> il DDL fallisce
        qui, non prima: è questo il punto giusto per tradurre l'errore, non un controllo anticipato."""
        conn = MagicMock()
        conn.get_dsn_parameters.return_value = {"user": "boxoffice_app"}

        def on_execute(sql):
            if "CREATE TABLE" in sql:
                raise psycopg2.errors.InsufficientPrivilege("permission denied for schema public")

        conn.cursor.side_effect = lambda: FakeCursor(on_execute)

        with self.assertRaises(RuntimeError) as ctx:
            apply_pending(conn)

        self.assertIn("boxoffice_app", str(ctx.exception))
        self.assertIn("permessi", str(ctx.exception))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_privilege_error_is_not_confused_with_other_database_errors(self) -> None:
        """Un errore diverso (non di permessi) deve restare quello che è, non essere tradotto."""
        conn = MagicMock()

        def on_execute(sql):
            if "CREATE TABLE" in sql:
                raise psycopg2.OperationalError("connessione persa")

        conn.cursor.side_effect = lambda: FakeCursor(on_execute)

        with self.assertRaises(psycopg2.OperationalError):
            apply_pending(conn)


if __name__ == "__main__":
    unittest.main()

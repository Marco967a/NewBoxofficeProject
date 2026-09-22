import os
import unittest
from unittest.mock import patch

from app.db import get_connection


ENV = {"DB_HOST": "localhost", "DB_NAME": "boxoffice", "DB_USER": "boxoffice_app", "DB_PORT": "5432"}


class GetConnectionOwnerRoleTests(unittest.TestCase):
    def test_missing_owner_secret_fails_fast_with_a_clear_message_before_connecting(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), \
                patch("app.db.get_secret", return_value=None) as get_secret, \
                patch("app.db.psycopg2.connect") as connect:
            with self.assertRaises(RuntimeError) as ctx:
                with get_connection(role="owner"):
                    pass

        self.assertIn("owner", str(ctx.exception))
        self.assertIn("setup_db_roles.py", str(ctx.exception))
        get_secret.assert_called_once_with("db:boxoffice_owner")
        connect.assert_not_called()  # niente tentativo di connessione: il fallimento è immediato

    def test_configured_owner_role_connects_normally(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), \
                patch("app.db.get_secret", return_value="pw-owner"), \
                patch("app.db.get_db_config", return_value={**ENV, "password": "pw-owner"}) as get_config, \
                patch("app.db.psycopg2.connect") as connect:
            with get_connection(role="owner"):
                pass

        get_config.assert_called_once_with("owner")
        connect.assert_called_once()

    def test_missing_ro_secret_still_falls_back_silently_to_app(self) -> None:
        """Per 'ro' il ripiego resta silenzioso: degrada solo i permessi, mai un guasto sorprendente."""
        with patch.dict(os.environ, ENV, clear=True), \
                patch("app.db.get_secret", return_value=None) as get_secret, \
                patch("app.db.get_db_config", return_value={**ENV, "password": "pw-app"}) as get_config, \
                patch("app.db.psycopg2.connect") as connect:
            with get_connection(role="ro"):
                pass

        get_secret.assert_not_called()  # la scorciatoia "owner" non si applica a "ro"
        get_config.assert_called_once_with("ro")
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()

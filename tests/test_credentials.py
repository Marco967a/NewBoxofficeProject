import os
import unittest
from unittest.mock import patch

from app.credentials import SERVICE, get_secret
from app.settings import Settings, get_db_config, get_settings

ENV = {
    "DB_HOST": "localhost", "DB_NAME": "boxoffice", "DB_USER": "boxoffice_app", "DB_PORT": "5432",
}


def vault(entries: dict):
    """Deposito finto: sostituisce keyring.get_password, così i test non leggono il deposito reale della macchina."""
    return patch("keyring.get_password", side_effect=lambda service, name: entries.get(name) if service == SERVICE else None)


class GetSecretTests(unittest.TestCase):
    def test_environment_wins_over_the_vault(self) -> None:
        with patch.dict(os.environ, {"X_SECRET": "da-ambiente"}), vault({"nome": "dal-deposito"}):
            self.assertEqual("da-ambiente", get_secret("nome", "X_SECRET"))

    def test_falls_back_to_the_vault(self) -> None:
        with patch.dict(os.environ, {}, clear=True), vault({"nome": "dal-deposito"}):
            self.assertEqual("dal-deposito", get_secret("nome", "X_SECRET"))

    def test_absent_everywhere_is_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True), vault({}):
            self.assertIsNone(get_secret("nome", "X_SECRET"))

    def test_broken_vault_backend_is_treated_as_absent(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("keyring.get_password", side_effect=RuntimeError("nessun backend")):
            self.assertIsNone(get_secret("nome"))


class SettingsFromVaultTests(unittest.TestCase):
    def test_secrets_come_from_the_vault_when_env_has_only_plain_config(self) -> None:
        entries = {"db:boxoffice_app": "pw-app", "tmdb_api_key": "chiave"}
        with patch.dict(os.environ, ENV, clear=True), vault(entries):
            settings = get_settings()

        self.assertEqual("pw-app", settings.db_password)
        self.assertEqual("chiave", settings.tmdb_api_key)
        self.assertEqual("boxoffice_app", settings.db_config["user"])

    def test_password_is_looked_up_for_the_configured_user(self) -> None:
        entries = {"db:boxoffice_app": "pw-app", "db:altro": "pw-altro", "tmdb_api_key": "k"}
        with patch.dict(os.environ, {**ENV, "DB_USER": "altro"}, clear=True), vault(entries):
            self.assertEqual("pw-altro", get_settings().db_password)

    def test_environment_overrides_the_vault(self) -> None:
        with patch.dict(os.environ, {**ENV, "DB_PASSWORD": "pw-env", "TMDB_API_KEY": "k-env"}, clear=True), \
                vault({"db:boxoffice_app": "pw-vault", "tmdb_api_key": "k-vault"}):
            settings = get_settings()
        self.assertEqual(("pw-env", "k-env"), (settings.db_password, settings.tmdb_api_key))

    def test_missing_secrets_are_reported_without_values(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), vault({}):
            with self.assertRaises(RuntimeError) as ctx:
                get_settings()

        message = str(ctx.exception)
        self.assertIn("DB_PASSWORD", message)
        self.assertIn("TMDB_API_KEY", message)
        self.assertIn("manage_secrets.py", message)

    def test_tmdb_is_optional_for_database_only_use(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), vault({"db:boxoffice_app": "pw"}):
            settings = get_settings(require_tmdb=False)
        self.assertEqual("", settings.tmdb_api_key)

    def test_read_token_alone_satisfies_the_tmdb_requirement(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), vault({"db:boxoffice_app": "pw", "tmdb_read_token": "eyJ-token"}):
            settings = get_settings()
        self.assertEqual("eyJ-token", settings.tmdb_read_token)

    def test_settings_dataclass_stays_backward_compatible(self) -> None:
        settings = Settings(tmdb_api_key="k", db_host="h", db_name="d", db_user="u", db_password="p")
        self.assertEqual("", settings.tmdb_read_token)


class DbConfigRoleTests(unittest.TestCase):
    def test_app_role_is_the_configured_user(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), vault({"db:boxoffice_app": "pw-app"}):
            self.assertEqual("boxoffice_app", get_db_config("app")["user"])

    def test_owner_and_ro_use_their_own_credentials(self) -> None:
        entries = {"db:boxoffice_app": "pw-app", "db:boxoffice_owner": "pw-owner", "db:boxoffice_ro": "pw-ro"}
        with patch.dict(os.environ, ENV, clear=True), vault(entries):
            owner, ro = get_db_config("owner"), get_db_config("ro")

        self.assertEqual(("boxoffice_owner", "pw-owner"), (owner["user"], owner["password"]))
        self.assertEqual(("boxoffice_ro", "pw-ro"), (ro["user"], ro["password"]))

    def test_role_user_names_are_configurable(self) -> None:
        env = {**ENV, "DB_OWNER_USER": "mio_owner"}
        with patch.dict(os.environ, env, clear=True), vault({"db:boxoffice_app": "pw", "db:mio_owner": "pw-o"}):
            self.assertEqual("mio_owner", get_db_config("owner")["user"])

    def test_unconfigured_role_falls_back_to_app_never_to_something_stronger(self) -> None:
        with patch.dict(os.environ, ENV, clear=True), vault({"db:boxoffice_app": "pw-app"}):
            fallback = get_db_config("owner")
        self.assertEqual("boxoffice_app", fallback["user"])


if __name__ == "__main__":
    unittest.main()

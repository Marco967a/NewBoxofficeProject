import unittest

from app.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_db_config_includes_default_postgres_port(self) -> None:
        settings = Settings(
            tmdb_api_key="key",
            db_host="localhost",
            db_name="boxoffice",
            db_user="postgres",
            db_password="password",
        )

        self.assertEqual(5432, settings.db_config["port"])

    def test_db_config_uses_configured_port(self) -> None:
        settings = Settings(
            tmdb_api_key="key",
            db_host="localhost",
            db_name="boxoffice",
            db_user="postgres",
            db_password="password",
            db_port=5433,
        )

        self.assertEqual(5433, settings.db_config["port"])


if __name__ == "__main__":
    unittest.main()

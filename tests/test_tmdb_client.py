import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from app.tmdb_client import TMDBClient


SECRET = "super-secret-tmdb-key"


def build_client() -> TMDBClient:
    settings = SimpleNamespace(tmdb_api_key=SECRET, request_timeout=5)
    with patch("app.tmdb_client.get_settings", return_value=settings):
        return TMDBClient()


class TMDBClientTests(unittest.TestCase):
    def test_http_error_does_not_leak_api_key(self) -> None:
        client = build_client()
        response = requests.Response()
        response.status_code = 401
        response.url = f"https://api.themoviedb.org/3/movie/1?api_key={SECRET}"
        client.session = MagicMock()
        client.session.get.return_value = response

        with self.assertRaises(RuntimeError) as ctx:
            client.get_movie_details(1)

        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIn("status=401", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_connection_error_does_not_leak_api_key(self) -> None:
        client = build_client()
        client.session = MagicMock()
        client.session.get.side_effect = requests.ConnectionError(
            f"Max retries exceeded with url: /3/movie/1?api_key={SECRET}"
        )

        with self.assertRaises(RuntimeError) as ctx:
            client.get_movie_details(1)

        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_caller_params_are_not_mutated(self) -> None:
        client = build_client()
        response = MagicMock()
        response.json.return_value = {}
        client.session = MagicMock()
        client.session.get.return_value = response
        params = {"page": 1}

        client._get("/discover/movie", params=params)

        self.assertEqual({"page": 1}, params)


class ImportWithoutSecretsTests(unittest.TestCase):
    def test_setup_logging_does_not_require_secrets(self) -> None:
        from app.logging_config import setup_logging

        with patch.dict("os.environ", {}, clear=True):
            setup_logging()


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from app.tmdb_client import TMDBClient


SECRET = "super-secret-tmdb-key"


def build_client() -> TMDBClient:
    settings = SimpleNamespace(tmdb_api_key=SECRET, request_timeout=5)
    with patch("app.tmdb_client.get_settings", return_value=settings):
        client = TMDBClient()
    client._sleep = lambda seconds: None  # niente attese reali nei test, a meno che non le testino apposta
    return client


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


class TMDBAuthTests(unittest.TestCase):
    TOKEN = "eyJ-read-access-token"

    def _client(self, **settings_kwargs):
        settings = SimpleNamespace(tmdb_api_key=SECRET, request_timeout=5, **settings_kwargs)
        with patch("app.tmdb_client.get_settings", return_value=settings):
            client = TMDBClient()
        client._sleep = lambda seconds: None
        response = MagicMock()
        response.json.return_value = {}
        client.session = MagicMock()
        client.session.get.return_value = response
        return client

    def test_api_key_goes_in_the_query_when_there_is_no_token(self) -> None:
        client = self._client()
        client._get("/movie/1")

        kwargs = client.session.get.call_args.kwargs
        self.assertEqual(SECRET, kwargs["params"]["api_key"])
        self.assertIsNone(kwargs["headers"])

    def test_read_token_goes_in_the_header_and_never_in_the_url(self) -> None:
        client = self._client(tmdb_read_token=self.TOKEN)
        client._get("/movie/1", params={"language": "it-IT"})

        kwargs = client.session.get.call_args.kwargs
        self.assertEqual({"Authorization": f"Bearer {self.TOKEN}"}, kwargs["headers"])
        self.assertEqual({"language": "it-IT"}, kwargs["params"])  # niente api_key nell'URL

    def test_token_is_not_leaked_by_errors(self) -> None:
        client = self._client(tmdb_read_token=self.TOKEN)
        client.session.get.side_effect = requests.ConnectionError(f"boom Bearer {self.TOKEN}")

        with self.assertRaises(RuntimeError) as ctx:
            client._get("/movie/1")

        self.assertNotIn(self.TOKEN, str(ctx.exception))


class TMDBRetryTests(unittest.TestCase):
    @staticmethod
    def _response(status):
        r = MagicMock(status_code=status)
        r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(f"HTTP {status}", response=r)
        r.json.return_value = {"ok": True}
        return r

    def test_rate_limit_is_retried_with_growing_waits_and_then_succeeds(self) -> None:
        client = build_client()
        client.session = MagicMock()
        waits = []
        client._sleep = waits.append
        client.session.get.side_effect = [self._response(429), self._response(503), self._response(200)]

        result = client._get("/movie/1")

        self.assertEqual({"ok": True}, result)
        self.assertEqual([5, 15], waits)
        self.assertEqual(3, client.session.get.call_count)

    def test_exhausted_retries_raise_without_leaking_the_key(self) -> None:
        client = build_client()
        client.session = MagicMock()
        client.session.get.return_value = self._response(429)

        with self.assertRaises(RuntimeError) as ctx:
            client._get("/movie/1")

        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIn("status=429", str(ctx.exception))
        self.assertEqual(4, client.session.get.call_count)  # 1 tentativo + 3 retry

    def test_client_error_is_not_retried(self) -> None:
        client = build_client()
        client.session = MagicMock()
        client.session.get.return_value = self._response(404)

        with self.assertRaises(RuntimeError):
            client._get("/movie/1")

        self.assertEqual(1, client.session.get.call_count)


class TMDBSearchTests(unittest.TestCase):
    def _client_returning(self, payload):
        client = build_client()
        response = MagicMock()
        response.json.return_value = payload
        client.session = MagicMock()
        client.session.get.return_value = response
        return client

    @patch("app.tmdb_client.time.sleep")
    def test_search_movies_uses_italian_and_returns_results(self, _sleep) -> None:
        client = self._client_returning({"results": [{"id": 7, "title": "Odissea"}]})

        results = client.search_movies("Odissea", year=2026)

        self.assertEqual([{"id": 7, "title": "Odissea"}], results)
        params = client.session.get.call_args.kwargs["params"]
        self.assertEqual("Odissea", params["query"])
        self.assertEqual("it-IT", params["language"])
        self.assertEqual(2026, params["year"])
        self.assertEqual("/search/movie", client.session.get.call_args.args[0].split("/3")[1])

    @patch("app.tmdb_client.time.sleep")
    def test_search_movies_without_results_returns_empty_list(self, _sleep) -> None:
        self.assertEqual([], self._client_returning({}).search_movies("x"))

    @patch("app.tmdb_client.time.sleep")
    def test_alternative_titles_are_extracted_for_country(self, _sleep) -> None:
        client = self._client_returning({"titles": [{"title": "Odissea"}, {"title": ""}, {"iso": "x"}]})

        self.assertEqual(["Odissea"], client.get_alternative_titles(9, country="IT"))
        self.assertEqual("IT", client.session.get.call_args.kwargs["params"]["country"])


    @patch("app.tmdb_client.time.sleep")
    def test_release_dates_keep_only_theatrical_dates_of_the_country(self, _sleep) -> None:
        client = self._client_returning({"results": [
            {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2026-07-01T00:00:00.000Z"}]},
            {"iso_3166_1": "IT", "release_dates": [
                {"type": 3, "release_date": "2026-07-16T00:00:00.000Z"},
                {"type": 1, "release_date": "2026-05-10T00:00:00.000Z"},
                {"type": 4, "release_date": "2026-10-01T00:00:00.000Z"},  # digitale: escluso
                {"type": 3, "release_date": "non-una-data"},
                {"type": 3, "release_date": ""},
            ]},
        ]})

        self.assertEqual([date(2026, 5, 10), date(2026, 7, 16)], client.get_release_dates(9))

    @patch("app.tmdb_client.time.sleep")
    def test_release_dates_without_the_country_is_empty(self, _sleep) -> None:
        self.assertEqual([], self._client_returning({"results": []}).get_release_dates(9))


class ImportWithoutSecretsTests(unittest.TestCase):
    def test_setup_logging_does_not_require_secrets(self) -> None:
        from app.logging_config import setup_logging

        with patch.dict("os.environ", {}, clear=True):
            setup_logging()


if __name__ == "__main__":
    unittest.main()

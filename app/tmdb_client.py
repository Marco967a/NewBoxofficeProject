import logging
import time
from datetime import date

import requests

from app.settings import get_settings


logger = logging.getLogger(__name__)


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.tmdb_api_key
        # Il token di lettura viaggia nell'header Authorization: non finisce in URL, log di proxy o cronologie.
        self.read_token = getattr(settings, "tmdb_read_token", "") or ""
        self.timeout = settings.request_timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        headers = None
        if self.read_token:
            headers = {"Authorization": f"Bearer {self.read_token}"}
        else:
            params["api_key"] = self.api_key

        try:
            response = self.session.get(
                f"{self.BASE_URL}{path}",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            # Le eccezioni di requests contengono l'URL completo (api_key inclusa):
            # le sostituiamo per evitare che la chiave finisca nei log.
            status = getattr(exc.response, "status_code", None)
            raise RuntimeError(
                f"TMDB request failed path={path} status={status} error={type(exc).__name__}"
            ) from None

    def get_top_revenue_movies(self, pages: int = 5) -> list[dict]:
        movies = []

        for page in range(1, pages + 1):
            logger.info("Fetching discover/movie page=%s", page)
            data = self._get(
                "/discover/movie",
                params={
                    "sort_by": "revenue.desc",
                    "page": page,
                },
            )
            movies.extend(data.get("results", []))
            time.sleep(0.2)

        return movies

    def get_movie_details(self, movie_id: int) -> dict:
        logger.debug("Fetching details for movie_id=%s", movie_id)
        time.sleep(0.2)
        return self._get(f"/movie/{movie_id}")

    def search_movies(self, query: str, language: str = "it-IT", year: int | None = None) -> list[dict]:
        """Prima pagina dei risultati di ricerca. I titoli tornano localizzati (default: italiano)."""
        params = {"query": query, "language": language, "include_adult": "false"}
        if year is not None:
            params["year"] = year
        time.sleep(0.2)
        return self._get("/search/movie", params=params).get("results", [])

    def get_alternative_titles(self, movie_id: int, country: str = "IT") -> list[str]:
        """Titoli alternativi di un film per un paese (es. il titolo di distribuzione italiano)."""
        time.sleep(0.2)
        data = self._get(f"/movie/{movie_id}/alternative_titles", params={"country": country})
        return [item["title"] for item in data.get("titles", []) if item.get("title")]

    def get_release_dates(self, movie_id: int, country: str = "IT") -> list[date]:
        """Date di uscita in sala (anteprime, limitata, teatrale) di un film in un paese."""
        time.sleep(0.2)
        data = self._get(f"/movie/{movie_id}/release_dates")
        dates = []
        for entry in data.get("results", []):
            if entry.get("iso_3166_1") != country:
                continue
            for release in entry.get("release_dates", []):
                if release.get("type") not in (1, 2, 3) or not release.get("release_date"):
                    continue
                try:
                    dates.append(date.fromisoformat(release["release_date"][:10]))
                except ValueError:
                    continue
        return sorted(set(dates))

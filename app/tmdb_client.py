import logging
import time
import requests

from app.settings import get_settings


logger = logging.getLogger(__name__)


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.tmdb_api_key
        self.timeout = settings.request_timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        params["api_key"] = self.api_key

        response = self.session.get(
            f"{self.BASE_URL}{path}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

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

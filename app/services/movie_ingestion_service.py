import logging

from app.db import get_connection
from app.repositories.movie_repository import MovieRepository
from app.tmdb_client import TMDBClient


logger = logging.getLogger(__name__)


class MovieIngestionService:
    def __init__(self):
        self.tmdb_client = TMDBClient()
        self.movie_repository = MovieRepository()

    def bootstrap_top_revenue_movies(self, pages: int = 5, batch_size: int = 25) -> int:
        logger.info("Starting bootstrap_top_revenue_movies pages=%s batch_size=%s", pages, batch_size)

        discover_results = self.tmdb_client.get_top_revenue_movies(pages=pages)
        logger.info("Discovered %s movie candidates", len(discover_results))

        unique_ids = []
        seen = set()

        for movie in discover_results:
            movie_id = movie.get("id")
            if movie_id and movie_id not in seen:
                seen.add(movie_id)
                unique_ids.append(movie_id)

        logger.info("Unique movie ids to enrich: %s", len(unique_ids))

        total_saved = 0
        batch = []

        with get_connection() as conn:
            self.movie_repository.create_table(conn)

            for idx, movie_id in enumerate(unique_ids, start=1):
                try:
                    details = self.tmdb_client.get_movie_details(movie_id)
                    batch.append(details)
                    logger.info("[%s/%s] fetched %s", idx, len(unique_ids), details.get("title"))
                except Exception as exc:
                    logger.exception("Failed to fetch movie_id=%s: %s", movie_id, exc)
                    continue

                if len(batch) >= batch_size:
                    saved = self.movie_repository.upsert_movies(conn, batch)
                    total_saved += saved
                    logger.info("Persisted batch of %s movies (total_saved=%s)", saved, total_saved)
                    batch.clear()

            if batch:
                saved = self.movie_repository.upsert_movies(conn, batch)
                total_saved += saved
                logger.info("Persisted final batch of %s movies (total_saved=%s)", saved, total_saved)

        logger.info("Bootstrap completed. total_saved=%s", total_saved)
        return total_saved
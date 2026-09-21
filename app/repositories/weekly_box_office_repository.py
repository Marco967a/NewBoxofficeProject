import logging

from psycopg2.extras import execute_values

from app.repositories.source_movie_repository import SourceMovieRepository


logger = logging.getLogger(__name__)


def _get(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


class WeeklyBoxOfficeRepository:
    def __init__(self, source_movie_repository: SourceMovieRepository | None = None):
        self.source_movie_repository = source_movie_repository or SourceMovieRepository()

    @staticmethod
    def _dedupe_by_week_and_title(records: list) -> list:
        """Un film compare una volta per settimana (chiave naturale): tiene il rank migliore."""
        kept: dict[tuple, object] = {}
        for record in sorted(records, key=lambda r: _get(r, "rank") if _get(r, "rank") is not None else 0):
            key = (
                _get(record, "source_name"),
                _get(record, "territory", "IT"),
                _get(record, "week_start"),
                _get(record, "external_movie_title"),
            )
            if key in kept:
                logger.warning(
                    "Titolo duplicato nella stessa settimana, scartato rank=%s: %s",
                    _get(record, "rank"), key,
                )
                continue
            kept[key] = record
        return list(kept.values())

    def upsert_records(self, conn, records: list, ingestion_run_id: int | None = None) -> int:
        if not records:
            return 0

        records = self._dedupe_by_week_and_title(records)

        # Film sorgente (ID ComingSoon) -> riferimento e movie_id già risolto, se esiste.
        source_refs = self.source_movie_repository.upsert_many(
            conn,
            [
                {
                    "source_name": _get(r, "source_name"),
                    "source_movie_id": _get(r, "source_movie_id"),
                    "title": _get(r, "external_movie_title"),
                    "url": _get(r, "source_url"),
                }
                for r in records
                if _get(r, "source_movie_id")
            ],
        )

        rows = []
        for r in records:
            source_movie_id = _get(r, "source_movie_id")
            ref_id, resolved_movie_id = source_refs.get(
                (_get(r, "source_name"), str(source_movie_id)), (None, None)
            ) if source_movie_id else (None, None)

            rows.append(
                (
                    _get(r, "source_name"),
                    _get(r, "territory", "IT"),
                    _get(r, "week_start"),
                    _get(r, "week_end"),
                    _get(r, "rank"),
                    _get(r, "movie_id") or resolved_movie_id,
                    ref_id,
                    _get(r, "external_movie_title"),
                    _get(r, "distributor"),
                    _get(r, "weekly_gross"),
                    _get(r, "total_gross"),
                    _get(r, "screen_count"),
                    _get(r, "weeks_in_release"),
                    ingestion_run_id,
                )
            )

        # movie_id e source_movie_ref non vengono mai azzerati da un caricamento che non li conosce.
        sql = """
            INSERT INTO weekly_box_office (
                source_name, territory, week_start, week_end, rank, movie_id, source_movie_ref,
                external_movie_title, distributor, weekly_gross,
                total_gross, screen_count, weeks_in_release, ingestion_run_id
            )
            VALUES %s
            ON CONFLICT (source_name, territory, week_start, external_movie_title)
            DO UPDATE SET
                week_end = EXCLUDED.week_end,
                rank = EXCLUDED.rank,
                movie_id = COALESCE(EXCLUDED.movie_id, weekly_box_office.movie_id),
                source_movie_ref = COALESCE(EXCLUDED.source_movie_ref, weekly_box_office.source_movie_ref),
                distributor = EXCLUDED.distributor,
                weekly_gross = EXCLUDED.weekly_gross,
                total_gross = EXCLUDED.total_gross,
                screen_count = EXCLUDED.screen_count,
                weeks_in_release = EXCLUDED.weeks_in_release,
                ingestion_run_id = EXCLUDED.ingestion_run_id,
                updated_at = now()
        """

        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=100)

        return len(rows)

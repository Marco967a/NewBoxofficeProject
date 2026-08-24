# app/services/weekly_box_office_service.py
import logging

from app.db import get_connection
from app.repositories.ingestion_run_repository import IngestionRunRepository
from app.repositories.movie_repository import MovieRepository
from app.repositories.weekly_box_office_repository import WeeklyBoxOfficeRepository


logger = logging.getLogger(__name__)


class WeeklyBoxOfficeService:
    def __init__(self):
        self.run_repository = IngestionRunRepository()
        self.movie_repository = MovieRepository()
        self.weekly_repository = WeeklyBoxOfficeRepository()

    @staticmethod
    def _get_record_value(record, field_name, default=None):
        if isinstance(record, dict):
            return record.get(field_name, default)
        return getattr(record, field_name, default)

    def _normalize_record(self, record: object, source_name: str) -> dict:
        return {
            "source_name": self._get_record_value(record, "source_name", source_name),
            "territory": self._get_record_value(record, "territory", "IT"),
            "week_start": self._get_record_value(record, "week_start"),
            "week_end": self._get_record_value(record, "week_end"),
            "rank": self._get_record_value(record, "rank"),
            "external_movie_title": self._get_record_value(record, "external_movie_title"),
            "distributor": self._get_record_value(record, "distributor"),
            "weekly_gross": self._get_record_value(record, "weekly_gross"),
            "screen_count": self._get_record_value(record, "screen_count"),
            "weeks_in_release": self._get_record_value(record, "weeks_in_release"),
            "movie_id": None,
        }

    def load_weekly_records(self, records: list, source_name: str, dry_run: bool = False) -> int:
        records_read = len(records)
        if dry_run:
            logger.info(
                "Dry run completed source=%s read=%s written=0",
                source_name,
                records_read,
            )
            return 0

        records_written = 0

        with get_connection() as conn:
            self.run_repository.create_table(conn)
            self.movie_repository.create_table(conn)
            self.weekly_repository.create_table(conn)

            run_id = self.run_repository.start_run(
                conn,
                pipeline_name="weekly_box_office",
                source_name=source_name,
            )

            try:
                enriched_records = [
                    self._normalize_record(record, source_name=source_name)
                    for record in records
                ]

                records_written = self.weekly_repository.upsert_records(
                    conn,
                    enriched_records,
                    ingestion_run_id=run_id,
                )

                self.run_repository.finish_run(
                    conn,
                    run_id=run_id,
                    status="success",
                    records_read=records_read,
                    records_written=records_written,
                )

                logger.info(
                    "Weekly load completed source=%s read=%s written=%s",
                    source_name, records_read, records_written
                )
                return records_written

            except Exception as exc:
                self.run_repository.finish_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    records_read=records_read,
                    records_written=records_written,
                    error_message=str(exc),
                )
                logger.exception("Weekly load failed source=%s", source_name)
                raise
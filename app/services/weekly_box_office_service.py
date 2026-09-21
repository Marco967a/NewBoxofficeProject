# app/services/weekly_box_office_service.py
import logging
from datetime import date, timedelta

from app.db import get_connection
from app.migrations import ensure_schema_current
from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice_for_date
from app.repositories.ingestion_run_repository import IngestionRunRepository
from app.repositories.raw_snapshot_repository import RawSnapshotRepository
from app.repositories.weekly_box_office_repository import WeeklyBoxOfficeRepository
from app.validation import validate_weekly_records


logger = logging.getLogger(__name__)


class WeeklyBoxOfficeService:
    def __init__(self):
        self.run_repository = IngestionRunRepository()
        self.snapshot_repository = RawSnapshotRepository()
        self.weekly_repository = WeeklyBoxOfficeRepository()

    @staticmethod
    def _get_record_value(record, field_name, default=None):
        if isinstance(record, dict):
            return record.get(field_name, default)
        return getattr(record, field_name, default)

    def _normalize_record(self, record: object, source_name: str) -> dict:
        return {
            # Il source_name passato dal chiamante ha la precedenza: altrimenti un run di test
            # ("comingsoon_test") scriverebbe righe indistinguibili da quelle di produzione.
            "source_name": source_name,
            "territory": self._get_record_value(record, "territory", "IT"),
            "week_start": self._get_record_value(record, "week_start"),
            "week_end": self._get_record_value(record, "week_end"),
            "rank": self._get_record_value(record, "rank"),
            "external_movie_title": self._get_record_value(record, "external_movie_title"),
            "distributor": self._get_record_value(record, "distributor"),
            "weekly_gross": self._get_record_value(record, "weekly_gross"),
            "total_gross": self._get_record_value(record, "total_gross"),
            "screen_count": self._get_record_value(record, "screen_count"),
            "weeks_in_release": self._get_record_value(record, "weeks_in_release"),
            "movie_id": self._get_record_value(record, "movie_id"),
            "source_movie_id": self._get_record_value(record, "source_movie_id"),
            "source_url": self._get_record_value(record, "source_url"),
        }

    def load_weekly_records(
        self,
        records: list,
        source_name: str,
        dry_run: bool = False,
        snapshots: list | None = None,
        pipeline_name: str = "weekly_box_office",
    ) -> int:
        """Carica i record. `snapshots`: pagine grezze (oggetti con .url e .html) da conservare.

        `pipeline_name` distingue i run non ordinari (es. recuperi da archivio) da quelli settimanali,
        che sono gli unici considerati dall'health check sulla freschezza.
        """
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
            ensure_schema_current(conn)

            run_id = self.run_repository.start_run(
                conn,
                pipeline_name=pipeline_name,
                source_name=source_name,
            )
            for snapshot in snapshots or []:
                self.snapshot_repository.insert(
                    conn,
                    ingestion_run_id=run_id,
                    source_name=source_name,
                    url=snapshot.url,
                    payload=snapshot.html,
                )
            # Run e pagina grezza vanno committati subito: in caso di errore il rollback dei dati
            # non deve portarsi via la riga del run (i fallimenti resterebbero senza traccia) né
            # la pagina scaricata (che permette di rielaborare senza riscaricare).
            conn.commit()

            try:
                enriched_records = [
                    self._normalize_record(record, source_name=source_name)
                    for record in records
                ]

                for warning in validate_weekly_records(enriched_records):
                    logger.warning("Data quality source=%s %s", source_name, warning)

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
                # Annulla le scritture parziali, poi registra il fallimento e committa il solo run.
                conn.rollback()
                self.run_repository.finish_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    records_read=records_read,
                    records_written=0,
                    error_message=str(exc),
                )
                conn.commit()
                logger.exception("Weekly load failed source=%s", source_name)
                raise

    def load_historical_weekly_records(self, start_date: date, weeks: int, source_name: str = "comingsoon") -> int:
        if weeks <= 0:
            return 0

        # ComingSoon espone solo la classifica corrente: per date passate il parser solleva
        # un errore invece di inventare dati. Le settimane non recuperabili vengono saltate.
        all_records = []
        seen_weeks = set()
        skipped = 0
        current_date = start_date
        for _ in range(weeks):
            try:
                records_for_date = parse_comingsoon_weekly_boxoffice_for_date(current_date)
            except RuntimeError as exc:
                skipped += 1
                logger.warning("Settimana del %s non recuperabile, saltata: %s", current_date, exc)
            else:
                first = records_for_date[0] if records_for_date else None
                week_key = (
                    self._get_record_value(first, "week_start"),
                    self._get_record_value(first, "week_end"),
                )
                if first is not None and week_key not in seen_weeks:
                    seen_weeks.add(week_key)
                    all_records.extend(records_for_date)
            current_date = current_date - timedelta(days=7)

        if skipped:
            logger.warning("Backfill: %s/%s settimane non recuperabili", skipped, weeks)

        if not all_records:
            return 0

        return self.load_weekly_records(all_records, source_name=source_name)

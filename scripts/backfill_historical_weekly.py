import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice_for_date
from app.services.weekly_box_office_service import WeeklyBoxOfficeService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill storico dei box office da ComingSoon")
    parser.add_argument("--start-date", required=True, help="Data iniziale del backfill (YYYY-MM-DD)")
    parser.add_argument("--weeks", type=int, required=True, help="Numero di settimane da recuperare")
    parser.add_argument("--source-name", default="comingsoon", help="Nome sorgente usato per l'ingestion run")
    return parser


def build_backfill_dates(start_date: date, weeks: int) -> List[date]:
    dates: List[date] = []
    current_date = start_date
    for _ in range(weeks):
        dates.append(current_date)
        current_date = current_date - timedelta(days=7)
    return dates


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    service = WeeklyBoxOfficeService()
    dates = build_backfill_dates(start_date, args.weeks)

    logger.info("Avvio backfill storico per %s settimane a partire da %s", args.weeks, start_date)

    all_records = []

    for current_date in dates:
        try:
            logger.info("Recupero settimana %s", current_date)
            records = parse_comingsoon_weekly_boxoffice_for_date(current_date)
            if not records:
                logger.warning("Nessun record recuperato per %s", current_date)
                continue
            all_records.extend(records)
            all_records.extend(records)
        except Exception as exc:
            logger.exception("Errore durante il recupero della settimana %s: %s", current_date, exc)

    if not all_records:
        logger.error("Nessun record recuperato; backfill interrotto")
        raise SystemExit(1)

    try:
        written = service.load_weekly_records(all_records, source_name=args.source_name)
        logger.info("Backfill completato: %s record caricati", written)
    except Exception as exc:
        logger.exception("Errore durante il caricamento del backfill: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

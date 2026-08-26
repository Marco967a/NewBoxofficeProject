import argparse
import logging
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    service = WeeklyBoxOfficeService()
    logger.info("Avvio backfill storico per %s settimane a partire da %s", args.weeks, start_date)

    try:
        written = service.load_historical_weekly_records(
            start_date=start_date,
            weeks=args.weeks,
            source_name=args.source_name,
        )
        if not written:
            logger.error("Nessun record recuperato; backfill interrotto")
            raise SystemExit(1)
        logger.info("Backfill completato: %s record caricati", written)
    except Exception as exc:
        logger.exception("Errore durante il caricamento del backfill: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

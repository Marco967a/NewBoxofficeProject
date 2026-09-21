"""Recupera dalla Wayback Machine le settimane ComingSoon mancanti nel database.

ComingSoon non ha archivio: si possono recuperare solo le settimane di cui l'Internet Archive ha uno
snapshot. Le altre restano buchi (vedi scripts/health_check.py). Uso: --dry-run per vedere cosa si trova.
"""
import argparse
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection
from app.health import missing_weeks
from app.migrations import ensure_schema_current
from app.parsers.comingsoon_parser import COMINGSOON_URL
from app.services.weekly_box_office_service import WeeklyBoxOfficeService
from app.validation import validate_weekly_records
from app.wayback import list_snapshots, recover_week

# Il CDX indicizza l'URL senza schema; la slash finale non cambia il risultato.
ARCHIVED_URL = "comingsoon.it/cinema/boxoffice"


def main() -> None:
    parser = argparse.ArgumentParser(description="Recupero da Wayback delle settimane ComingSoon mancanti")
    parser.add_argument("--source-name", default="comingsoon")
    parser.add_argument("--territory", default="IT")
    parser.add_argument("--weeks", type=int, default=12, help="Finestra (settimane) in cui cercare i buchi")
    parser.add_argument("--dry-run", action="store_true", help="Mostra cosa si troverebbe senza scrivere sul database")
    parser.add_argument("--max-attempts", type=int, default=5, help="Snapshot da provare per settimana")
    parser.add_argument("--delay", type=float, default=2.0, help="Pausa (s) tra due richieste a Wayback")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with get_connection() as conn:
        ensure_schema_current(conn)
        missing = missing_weeks(conn, args.source_name, args.territory, args.weeks)

    if not missing:
        print("Nessuna settimana mancante.")
        return
    print(f"Settimane mancanti: {', '.join(str(d) for d in missing)}")

    snapshots = list_snapshots(ARCHIVED_URL, missing[0] + timedelta(days=3), missing[-1] + timedelta(days=10))
    print(f"Snapshot di Wayback nel periodo: {len(snapshots)}")

    service = WeeklyBoxOfficeService()
    recovered, not_found = [], []
    for week in missing:
        result = recover_week(
            week, COMINGSOON_URL, snapshots, max_attempts=args.max_attempts, delay_seconds=args.delay
        )
        if result is None:
            not_found.append(week)
            print(f"  {week}: nessuno snapshot utilizzabile")
            continue

        warnings = validate_weekly_records(result.records)
        print(f"  {week}: {len(result.records)} righe da {result.url}" + (f" ({len(warnings)} avvisi)" if warnings else ""))
        for warning in warnings:
            print(f"      ! {warning}")

        if not args.dry_run:
            written = service.load_weekly_records(
                result.records,
                source_name=args.source_name,
                snapshots=[result],
                pipeline_name="weekly_box_office_recovery",
            )
            print(f"      scritte {written} righe")
        recovered.append(week)
        time.sleep(args.delay)

    print(
        f"\nRecuperate {len(recovered)}/{len(missing)} settimane"
        + (" (dry-run, nulla scritto)" if args.dry_run else "")
        + (f"; non recuperabili: {', '.join(str(d) for d in not_found)}" if not_found else "")
    )
    if recovered and not args.dry_run:
        print("Ora esegui: python scripts/resolve_matches.py   (collega i film nuovi a TMDB)")


if __name__ == "__main__":
    main()

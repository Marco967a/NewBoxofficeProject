#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports like `app` work
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice
from app.services.weekly_box_office_service import WeeklyBoxOfficeService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load weekly box office data from ComingSoon")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse records without writing them to the database",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    records = parse_comingsoon_weekly_boxoffice()
    print(f"Parsed records: {len(records)}")

    svc = WeeklyBoxOfficeService()
    if args.dry_run:
        print("Dry run enabled: no records will be written to the database.")

    written = svc.load_weekly_records(
        records=records,
        source_name="comingsoon",
        dry_run=args.dry_run,
    )
    print(f"Records written: {written}")

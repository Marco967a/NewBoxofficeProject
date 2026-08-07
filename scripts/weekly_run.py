import argparse
from datetime import date

from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice
from app.services.weekly_box_office_service import WeeklyBoxOfficeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carica i dati box office da ComingSoon")
    parser.add_argument(
        "--historical-start-date",
        help="Data iniziale per il backfill storico (formato YYYY-MM-DD)",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=1,
        help="Numero di settimane da caricare quando si usa --historical-start-date",
    )
    parser.add_argument(
        "--source-name",
        default="comingsoon",
        help="Nome sorgente usato per l'ingestion run",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    weekly_service = WeeklyBoxOfficeService()

    if args.historical_start_date:
        start_date = date.fromisoformat(args.historical_start_date)
        total_weekly = weekly_service.load_historical_weekly_records(
            start_date=start_date,
            weeks=args.weeks,
            source_name=args.source_name,
        )
        print(f"Caricati {total_weekly} record weekly storici su PostgreSQL")
        return

    print("Parsing box office da ComingSoon...")
    weekly_records = parse_comingsoon_weekly_boxoffice()
    print(f"Trovati {len(weekly_records)} record di box office")

    total_weekly = weekly_service.load_weekly_records(
        records=weekly_records,
        source_name=args.source_name,
    )
    print(f"Caricati {total_weekly} record weekly su PostgreSQL")


if __name__ == "__main__":
    main()

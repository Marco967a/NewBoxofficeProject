from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice
from app.services.weekly_box_office_service import WeeklyBoxOfficeService


def main() -> None:
    print("Parsing box office da ComingSoon...")
    weekly_records = parse_comingsoon_weekly_boxoffice()
    print(f"Trovati {len(weekly_records)} record di box office")

    weekly_service = WeeklyBoxOfficeService()
    total_weekly = weekly_service.load_weekly_records(
        records=weekly_records,
        source_name="comingsoon",
    )
    print(f"Caricati {total_weekly} record weekly su PostgreSQL")


if __name__ == "__main__":
    main()

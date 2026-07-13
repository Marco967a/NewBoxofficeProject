from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice
from app.services.weekly_box_office_service import WeeklyBoxOfficeService

if __name__ == "__main__":
    records = parse_comingsoon_weekly_boxoffice()
    print(f"Parsed records: {len(records)}")

    svc = WeeklyBoxOfficeService()
    written = svc.load_weekly_records(records=records, source_name="comingsoon")
    print(f"Records written: {written}")

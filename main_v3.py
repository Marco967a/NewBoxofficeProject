from app.services.movie_ingestion_service import MovieIngestionService
from app.services.weekly_box_office_service import WeeklyBoxOfficeService
from app.parsers.comingsoon_parser import parse_comingsoon_weekly_boxoffice


def main():
    print("Avvio pipeline di ingestion...")

    print("=== PHASE 1: Bootstrap Movies ===")
    movie_service = MovieIngestionService()
    total_movies = movie_service.bootstrap_top_revenue_movies(pages=5, batch_size=25)
    print(f"Salvati {total_movies} film su PostgreSQL")

    print("=== PHASE 2: Weekly Box Office ===")
    print("Parsing box office da ComingSoon...")
    weekly_records = parse_comingsoon_weekly_boxoffice()
    print(f"Trovati {len(weekly_records)} record di box office")

    weekly_service = WeeklyBoxOfficeService()
    total_weekly = weekly_service.load_weekly_records(
        records=weekly_records,
        source_name="comingsoon"
    )
    print(f"Caricati {total_weekly} record weekly su PostgreSQL")

    print("=== Pipeline completato ===")


if __name__ == "__main__":
    main()
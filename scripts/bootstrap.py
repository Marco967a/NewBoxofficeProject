from app.services.movie_ingestion_service import MovieIngestionService


def main() -> None:
    print("Avvio bootstrap TMDB...")
    movie_service = MovieIngestionService()
    total_movies = movie_service.bootstrap_top_revenue_movies(pages=5, batch_size=25)
    print(f"Salvati {total_movies} film su PostgreSQL")


if __name__ == "__main__":
    main()

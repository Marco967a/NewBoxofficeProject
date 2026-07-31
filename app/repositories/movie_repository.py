from psycopg2.extras import execute_values


class MovieRepository:
    def create_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    release_date DATE,
                    revenue BIGINT DEFAULT 0,
                    budget BIGINT DEFAULT 0,
                    popularity DOUBLE PRECISION DEFAULT 0,
                    vote_average DOUBLE PRECISION DEFAULT 0,
                    runtime INTEGER,
                    original_language TEXT,
                    genres TEXT,
                    overview TEXT,
                    tagline TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

    def _normalize_movie(self, movie: dict) -> tuple:
        genres_str = ", ".join(
            genre["name"] for genre in movie.get("genres", []) if "name" in genre
        )

        return (
            movie["id"],
            movie["title"],
            movie.get("release_date") or None,
            movie.get("revenue", 0),
            movie.get("budget", 0),
            movie.get("popularity", 0),
            movie.get("vote_average", 0),
            movie.get("runtime"),
            movie.get("original_language"),
            genres_str,
            movie.get("overview"),
            movie.get("tagline"),
            movie.get("status"),
        )

    def upsert_movies(self, conn, movies: list[dict]) -> int:
        if not movies:
            return 0

        rows = [self._normalize_movie(movie) for movie in movies]

        sql = """
            INSERT INTO movies (
                id, title, release_date, revenue, budget,
                popularity, vote_average, runtime, original_language,
                genres, overview, tagline, status
            )
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                release_date = EXCLUDED.release_date,
                revenue = EXCLUDED.revenue,
                budget = EXCLUDED.budget,
                popularity = EXCLUDED.popularity,
                vote_average = EXCLUDED.vote_average,
                runtime = EXCLUDED.runtime,
                original_language = EXCLUDED.original_language,
                genres = EXCLUDED.genres,
                overview = EXCLUDED.overview,
                tagline = EXCLUDED.tagline,
                status = EXCLUDED.status,
                updated_at = NOW()
        """

        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=100)

        return len(rows)


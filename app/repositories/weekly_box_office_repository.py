from psycopg2.extras import execute_values


class WeeklyBoxOfficeRepository:
    def create_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS weekly_box_office (
                    id BIGSERIAL PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    territory TEXT NOT NULL DEFAULT 'IT',
                    week_start DATE NOT NULL,
                    week_end DATE NOT NULL,
                    rank INTEGER NOT NULL,
                    movie_id INTEGER,
                    external_movie_title TEXT NOT NULL,
                    distributor TEXT,
                    weekly_gross NUMERIC(14,2),
                    screen_count INTEGER,
                    weeks_in_release INTEGER,
                    ingestion_run_id BIGINT REFERENCES ingestion_runs(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE (source_name, territory, week_start, week_end, rank)
                )
            """)
            cur.execute("ALTER TABLE weekly_box_office DROP COLUMN IF EXISTS weekly_admissions")
            cur.execute("ALTER TABLE weekly_box_office DROP COLUMN IF EXISTS is_italian")

    def upsert_records(self, conn, records: list, ingestion_run_id: int | None = None) -> int:
        if not records:
            return 0

        def get(r, key, default=None):
            if isinstance(r, dict):
                return r.get(key, default)
            return getattr(r, key, default)

        rows = [
            (
                get(r, "source_name"),
                get(r, "territory", "IT"),
                get(r, "week_start"),
                get(r, "week_end"),
                get(r, "rank"),
                get(r, "movie_id"),
                get(r, "external_movie_title"),
                get(r, "distributor"),
                get(r, "weekly_gross"),
                get(r, "screen_count"),
                get(r, "weeks_in_release"),
                ingestion_run_id,
            )
            for r in records
        ]

        sql = """
            INSERT INTO weekly_box_office (
                source_name, territory, week_start, week_end, rank, movie_id,
                external_movie_title, distributor, weekly_gross,
                screen_count, weeks_in_release, ingestion_run_id
            )
            VALUES %s
            ON CONFLICT (source_name, territory, week_start, week_end, rank)
            DO UPDATE SET
                movie_id = EXCLUDED.movie_id,
                external_movie_title = EXCLUDED.external_movie_title,
                distributor = EXCLUDED.distributor,
                weekly_gross = EXCLUDED.weekly_gross,
                screen_count = EXCLUDED.screen_count,
                weeks_in_release = EXCLUDED.weeks_in_release,
                ingestion_run_id = EXCLUDED.ingestion_run_id,
                updated_at = NOW()
        """

        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=100)

        return len(rows)

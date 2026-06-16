# app/repositories/weekly_box_office_repository.py
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
                    weekly_admissions INTEGER,
                    screen_count INTEGER,
                    weeks_in_release INTEGER,
                    is_italian BOOLEAN,
                    ingestion_run_id BIGINT REFERENCES ingestion_runs(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE (source_name, territory, week_start, week_end, rank)
                )
            """)

    def upsert_weekly_records(self, conn, records: list, ingestion_run_id: int) -> int:
        if not records:
            return 0

        rows = [
            (
                r.source_name,
                r.territory,
                r.week_start,
                r.week_end,
                r.rank,
                r.movie_id,
                r.external_movie_title,
                r.distributor,
                r.weekly_gross,
                r.weekly_admissions,
                r.screen_count,
                r.weeks_in_release,
                r.is_italian,
                ingestion_run_id,
            )
            for r in records
        ]

        sql = """
            INSERT INTO weekly_box_office (
                source_name, territory, week_start, week_end, rank, movie_id,
                external_movie_title, distributor, weekly_gross, weekly_admissions,
                screen_count, weeks_in_release, is_italian, ingestion_run_id
            )
            VALUES %s
            ON CONFLICT (source_name, territory, week_start, week_end, rank)
            DO UPDATE SET
                movie_id = EXCLUDED.movie_id,
                external_movie_title = EXCLUDED.external_movie_title,
                distributor = EXCLUDED.distributor,
                weekly_gross = EXCLUDED.weekly_gross,
                weekly_admissions = EXCLUDED.weekly_admissions,
                screen_count = EXCLUDED.screen_count,
                weeks_in_release = EXCLUDED.weeks_in_release,
                is_italian = EXCLUDED.is_italian,
                ingestion_run_id = EXCLUDED.ingestion_run_id,
                updated_at = NOW()
        """

        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=100)

        return len(rows)

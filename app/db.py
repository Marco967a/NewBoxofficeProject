from contextlib import contextmanager
import psycopg2
from psycopg2.extras import execute_values

from app.settings import get_settings


@contextmanager
def get_connection():
    settings = get_settings()
    conn = psycopg2.connect(**settings.db_config)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_weekly_tables():
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id BIGSERIAL PRIMARY KEY,
            pipeline_name TEXT NOT NULL,
            source_name TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMP,
            status TEXT NOT NULL,
            records_read INTEGER DEFAULT 0,
            records_written INTEGER DEFAULT 0,
            error_message TEXT
        );

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
        );
        """)

        cur.close()


def insert_weekly_records(records, ingestion_run_id=None, conn=None):
    """Insert or update weekly records.

    Args:
        records: iterable of dicts or objects with attributes
        ingestion_run_id: optional ingestion run id to store
        conn: optional existing DB connection to use
    """
    if not records:
        return
    # Normalize records (support both dicts and objects with attributes)
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
            get(r, "weekly_admissions"),
            get(r, "screen_count"),
            get(r, "weeks_in_release"),
            get(r, "is_italian"),
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

    if conn is None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, page_size=100)
    else:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=100)
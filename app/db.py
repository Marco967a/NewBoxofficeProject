from contextlib import contextmanager
import psycopg2

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
    conn = get_connection()
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

    conn.commit()
    cur.close()
    conn.close()


def insert_weekly_records(records):
    if not records:
        return

    conn = get_connection()
    cur = conn.cursor()

    for record in records:
        cur.execute("""
            INSERT INTO weekly_box_office (
                source_name,
                territory,
                week_start,
                week_end,
                rank,
                movie_id,
                external_movie_title,
                distributor,
                weekly_gross,
                weekly_admissions,
                screen_count,
                weeks_in_release,
                is_italian
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                updated_at = NOW()
        """, (
            record.get("source_name"),
            record.get("territory", "IT"),
            record.get("week_start"),
            record.get("week_end"),
            record.get("rank"),
            record.get("movie_id"),
            record.get("external_movie_title"),
            record.get("distributor"),
            record.get("weekly_gross"),
            record.get("weekly_admissions"),
            record.get("screen_count"),
            record.get("weeks_in_release"),
            record.get("is_italian"),
        ))

    conn.commit()
    cur.close()
    conn.close()
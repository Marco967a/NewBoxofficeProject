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

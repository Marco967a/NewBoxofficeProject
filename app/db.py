from contextlib import contextmanager
import psycopg2

from app.settings import get_db_config, get_settings


@contextmanager
def get_connection(role: str = "app"):
    """Connessione con commit/rollback automatici.

    `role`: 'app' (pipeline, resolver, recupero), 'owner' (solo migrazioni: unico ruolo con DDL) o 'ro'
    (sola lettura: health check e analisi). Se 'owner'/'ro' non sono configurati nel deposito, si ripiega
    su 'app' (vedi get_db_config): innocuo per 'ro' (read-only), e altrettanto innocuo per 'owner' quando
    'app' ha già i permessi di DDL (es. un unico superutente usato per tutto, come nella CI). Se invece
    davvero mancano i permessi, il DDL fallisce con un errore chiaro: vedi app/migrations.py.
    """
    config = get_settings(require_tmdb=False).db_config if role == "app" else get_db_config(role)
    conn = psycopg2.connect(**config)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

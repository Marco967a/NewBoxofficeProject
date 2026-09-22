from contextlib import contextmanager
import psycopg2

from app.credentials import get_secret
from app.roles import RoleNames
from app.settings import get_db_config, get_settings


@contextmanager
def get_connection(role: str = "app"):
    """Connessione con commit/rollback automatici.

    `role`: 'app' (pipeline, resolver, recupero), 'owner' (solo migrazioni: unico ruolo con DDL) o 'ro'
    (sola lettura: health check e analisi).

    `get_db_config("ro")` ripiega in silenzio su 'app' se 'ro' non è configurato: innocuo, perché 'app'
    ha comunque i permessi di lettura. Per 'owner' invece no: proseguire con un ruolo senza DDL farebbe
    fallire la migrazione a metà, con un errore Postgres poco chiaro invece che un messaggio comprensibile
    subito, prima ancora di aprire la connessione.
    """
    if role == "owner":
        owner = RoleNames.from_env().owner
        if not get_secret(f"db:{owner}"):
            raise RuntimeError(
                f"Ruolo owner ('{owner}') non configurato nel deposito credenziali: le migrazioni "
                "richiedono un ruolo con privilegi DDL. Esegui: python scripts/setup_db_roles.py"
            )
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

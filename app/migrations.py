"""Migrazioni SQL versionate (migrations/NNN_nome.sql), tracciate in schema_migrations."""
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg2

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_FILENAME = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")
# Serializza le esecuzioni concorrenti di migrate.py (chiave arbitraria dell'advisory lock).
_LOCK_KEY = 726_001


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str
    checksum: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise ValueError(f"Nome migrazione non valido: {path.name} (atteso NNN_nome.sql)")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(match.group(1), match.group(2), sql, hashlib.sha256(sql.encode("utf-8")).hexdigest())
        )

    versions = [m.version for m in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("Versioni di migrazione duplicate")
    return migrations


def _applied(conn) -> dict[str, str]:
    """Versioni già applicate (version -> checksum), senza creare nulla."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migrations') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {}
        cur.execute("SELECT version, checksum FROM schema_migrations")
        return dict(cur.fetchall())


def pending_migrations(conn, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    applied = _applied(conn)
    pending = []
    for migration in load_migrations(directory):
        if migration.version in applied:
            if applied[migration.version] != migration.checksum:
                raise RuntimeError(
                    f"La migrazione {migration.version}_{migration.name} è stata modificata dopo "
                    "l'applicazione: crea una nuova migrazione invece di editare quella vecchia."
                )
        else:
            pending.append(migration)
    return pending


def ensure_schema_current(conn) -> None:
    """Sola lettura: fallisce se ci sono migrazioni da applicare."""
    pending = pending_migrations(conn)
    if pending:
        raise RuntimeError(
            f"Schema DB non aggiornato ({len(pending)} migrazioni da applicare, "
            f"prossima: {pending[0].version}_{pending[0].name}). Esegui: python scripts/migrate.py"
        )


def _current_user(conn) -> str:
    # Non una query: dopo un errore di permessi la transazione è già abortita, quindi niente SELECT.
    return conn.get_dsn_parameters().get("user", "?")


def _permission_error(conn, exc: psycopg2.errors.InsufficientPrivilege) -> RuntimeError:
    """Messaggio comprensibile per un DDL rifiutato per permessi, invece del solo errore Postgres.

    get_db_config("owner") ripiega in silenzio su 'app' quando l'owner non è configurato nel deposito
    (innocuo se 'app' ha comunque privilegi sufficienti, es. un unico superutente come in CI): qui è
    dove si scopre se quel ripiego bastava o no.
    """
    user = _current_user(conn)
    error = RuntimeError(
        f"Il ruolo '{user}' non ha i permessi per creare/modificare tabelle. Se il ruolo owner non è "
        "ancora configurato nel deposito credenziali, esegui: python scripts/setup_db_roles.py "
        "(oppure imposta DB_OWNER_USER/DB_OWNER_PASSWORD)."
    )
    error.__cause__ = exc
    return error


def apply_pending(conn, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Applica le migrazioni mancanti, una transazione ciascuna. Ritorna quelle applicate."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()
    except psycopg2.errors.InsufficientPrivilege as exc:
        error = _permission_error(conn, exc)
        conn.rollback()
        raise error

    applied_now = []
    for migration in load_migrations(directory):
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            # Riletto dopo il lock: un altro processo potrebbe averla appena applicata.
            already = migration.version in _applied(conn)
            if already:
                conn.rollback()
                continue

            logger.info("Applico migrazione %s_%s", migration.version, migration.name)
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
            conn.commit()
            applied_now.append(migration)
        except psycopg2.errors.InsufficientPrivilege as exc:
            error = _permission_error(conn, exc)
            conn.rollback()
            raise error
        except Exception:
            conn.rollback()
            raise

    # Verifica finale dei checksum delle migrazioni già presenti.
    pending_migrations(conn, directory)
    return applied_now

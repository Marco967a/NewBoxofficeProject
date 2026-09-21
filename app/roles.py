"""Ruoli PostgreSQL a privilegi minimi.

    <prefisso>_owner  proprietario di database e oggetti; l'unico con DDL (usato solo da scripts/migrate.py)
    <prefisso>_app    pipeline, resolver, recupero: SELECT/INSERT/UPDATE (e DELETE dove serve), nessun DDL
    <prefisso>_ro     sola lettura: health check e analisi
    <prefisso>_test   solo per i test locali: può creare e distruggere database temporanei

Nessuno di questi ruoli è superutente: un superutente può eseguire comandi sul sistema (COPY ... PROGRAM)
e leggere qualsiasi file del server, quindi una password trapelata equivarrebbe a compromettere l'utente Windows.
I privilegi sono dichiarati tabella per tabella in TABLE_PRIVILEGES: una tabella nuova non è accessibile a nessuno
finché non viene aggiunta qui (un test lo verifica), perché «tutto a tutti» è il modo in cui i privilegi si allargano.
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass

import psycopg2
from psycopg2 import sql

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleNames:
    owner: str = "boxoffice_owner"
    app: str = "boxoffice_app"
    ro: str = "boxoffice_ro"
    test: str = "boxoffice_test"

    @classmethod
    def with_prefix(cls, prefix: str) -> "RoleNames":
        return cls(f"{prefix}_owner", f"{prefix}_app", f"{prefix}_ro", f"{prefix}_test")

    @classmethod
    def from_env(cls) -> "RoleNames":
        return cls(
            owner=os.getenv("DB_OWNER_USER", cls.owner),
            app=os.getenv("DB_USER", cls.app),
            ro=os.getenv("DB_RO_USER", cls.ro),
            test=os.getenv("TEST_DB_USER", cls.test),
        )


# tabella/vista -> (privilegi del ruolo app, privilegi del ruolo ro)
TABLE_PRIVILEGES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ingestion_runs": (("SELECT", "INSERT", "UPDATE"), ("SELECT",)),
    "movies": (("SELECT", "INSERT", "UPDATE"), ("SELECT",)),
    "weekly_box_office": (("SELECT", "INSERT", "UPDATE"), ("SELECT",)),
    "source_movies": (("SELECT", "INSERT", "UPDATE", "DELETE"), ("SELECT",)),  # DELETE: unificazione dei film legacy
    "raw_snapshots": (("SELECT", "INSERT"), ("SELECT",)),
    "match_candidates": (("SELECT", "INSERT", "DELETE"), ("SELECT",)),
    "schema_migrations": (("SELECT",), ("SELECT",)),  # l'app la legge per verificare che lo schema sia aggiornato
    "weekly_box_office_quarantine": (("SELECT",), ("SELECT",)),
    "v_weekly_enriched": (("SELECT",), ("SELECT",)),
}

_KIND_SQL = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}
_SCRAM_ITERATIONS = 4096


def generate_password() -> str:
    return secrets.token_urlsafe(32)


def scram_verifier(password: str) -> str:
    """Verificatore SCRAM-SHA-256: a PostgreSQL si passa questo, così la password in chiaro non compare
    nemmeno nei log del server (che registra l'istruzione se un ALTER ROLE fallisce)."""
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _SCRAM_ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${_SCRAM_ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def _upsert_role(cur, name: str, password: str, createdb: bool = False) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(
        sql.SQL("{} ROLE {} WITH LOGIN NOSUPERUSER {} NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(
            sql.SQL(verb),
            sql.Identifier(name),
            sql.SQL("CREATEDB" if createdb else "NOCREATEDB"),
            sql.Literal(scram_verifier(password)),
        )
    )


def _existing_roles(cur, names: list[str]) -> set[str]:
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (names,))
    return {row[0] for row in cur.fetchall()}


def transfer_ownership(cur, owner: str) -> list[str]:
    """Rende `owner` proprietario di tabelle e viste dello schema public (le sequenze seguono le loro tabelle)."""
    cur.execute(
        """
        SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm') ORDER BY c.relname
        """
    )
    moved = []
    for relname, relkind in cur.fetchall():
        cur.execute(
            sql.SQL("ALTER {} {} OWNER TO {}").format(
                sql.SQL(_KIND_SQL[relkind]), sql.Identifier(relname), sql.Identifier(owner)
            )
        )
        moved.append(relname)
    return moved


def apply_object_grants(cur, names: RoleNames) -> list[str]:
    """Riapplica da zero i privilegi su tabelle, viste, sequenze e schema. Idempotente.

    Ritorna le tabelle/viste senza una voce in TABLE_PRIVILEGES: restano inaccessibili ai ruoli app e ro.
    Si esegue dopo ogni migrazione (scripts/migrate.py lo fa da solo).
    """
    present = _existing_roles(cur, [names.app, names.ro])
    grantees = [sql.SQL("PUBLIC")] + [sql.Identifier(r) for r in (names.app, names.ro) if r in present]

    cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    for role in (names.app, names.ro):
        if role in present:
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))

    cur.execute(
        """
        SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S') ORDER BY c.relname
        """
    )
    unknown = []
    for relname, relkind in cur.fetchall():
        target = sql.SQL("{} {}").format(
            sql.SQL("SEQUENCE" if relkind == "S" else "TABLE"), sql.Identifier(relname)
        )
        cur.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(target, sql.SQL(", ").join(grantees)))

        if relkind == "S":
            if names.app in present:
                cur.execute(sql.SQL("GRANT USAGE, SELECT ON {} TO {}").format(target, sql.Identifier(names.app)))
            continue

        spec = TABLE_PRIVILEGES.get(relname)
        if spec is None:
            unknown.append(relname)
            logger.warning("Nessun privilegio definito per '%s' in app/roles.py: non concesso ai ruoli app/ro", relname)
            continue
        for role, privileges in ((names.app, spec[0]), (names.ro, spec[1])):
            if role in present:
                cur.execute(
                    sql.SQL("GRANT {} ON {} TO {}").format(
                        sql.SQL(", ").join(sql.SQL(p) for p in privileges), target, sql.Identifier(role)
                    )
                )
    return unknown


def setup_roles(
    admin_config: dict,
    database: str,
    names: RoleNames,
    passwords: dict[str, str],
    include_test_role: bool = True,
) -> dict:
    """Crea/aggiorna i ruoli, assegna proprietà e privilegi di `database`. Richiede un amministratore.

    `passwords`: chiavi 'owner', 'app', 'ro' (e 'test'). Idempotente: si può rieseguire (anche per ruotare le password).
    """
    conn = psycopg2.connect(**{**admin_config, "dbname": "postgres"})
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _upsert_role(cur, names.owner, passwords["owner"])
            _upsert_role(cur, names.app, passwords["app"])
            _upsert_role(cur, names.ro, passwords["ro"])
            if include_test_role:
                _upsert_role(cur, names.test, passwords["test"], createdb=True)

            db = sql.Identifier(database)
            cur.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(db, sql.Identifier(names.owner)))
            cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
            for role in (names.owner, names.app, names.ro):
                cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, sql.Identifier(role)))
            # TEMP serve alla pipeline (tabella temporanea nell'unificazione dei film legacy)
            cur.execute(sql.SQL("GRANT TEMPORARY ON DATABASE {} TO {}").format(db, sql.Identifier(names.app)))
    finally:
        conn.close()

    conn = psycopg2.connect(**{**admin_config, "dbname": database})
    try:
        with conn.cursor() as cur:
            moved = transfer_ownership(cur, names.owner)
            unknown = apply_object_grants(cur, names)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ownership_transferred": moved, "objects_without_privileges": unknown}


# --- verifica -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    role: str
    statement: str
    expected: str  # 'allowed' | 'denied'
    ok: bool
    detail: str


_PROBES: dict[str, list[tuple[str, str]]] = {
    "app": [
        ("allowed", "SELECT count(*) FROM weekly_box_office"),
        ("allowed", "SELECT count(*) FROM v_weekly_enriched"),
        ("allowed", "CREATE TEMP TABLE _probe_temp (x int)"),
        ("denied", "CREATE TABLE _probe (x int)"),
        ("denied", "DROP TABLE weekly_box_office"),
        ("denied", "TRUNCATE weekly_box_office"),
        ("denied", "DELETE FROM weekly_box_office"),
        ("denied", "ALTER TABLE weekly_box_office ADD COLUMN _probe int"),
        ("denied", "CREATE ROLE _probe_role"),
        ("denied", "COPY (SELECT 1) TO PROGRAM 'echo probe'"),
        ("denied", "SELECT pg_read_file('postgresql.conf')"),
    ],
    "ro": [
        ("allowed", "SELECT count(*) FROM weekly_box_office"),
        ("allowed", "SELECT count(*) FROM v_weekly_enriched"),
        ("denied", "INSERT INTO ingestion_runs (pipeline_name, source_name, status) VALUES ('p', 's', 'running')"),
        ("denied", "UPDATE weekly_box_office SET rank = rank"),
        ("denied", "DELETE FROM source_movies"),
        ("denied", "CREATE TABLE _probe (x int)"),
        ("denied", "CREATE TEMP TABLE _probe_temp (x int)"),
    ],
    "owner": [
        ("allowed", "SELECT count(*) FROM weekly_box_office"),
        ("allowed", "CREATE TABLE _probe (x int)"),
        ("denied", "CREATE ROLE _probe_role"),
        ("denied", "COPY (SELECT 1) TO PROGRAM 'echo probe'"),
        ("denied", "SELECT pg_read_file('postgresql.conf')"),
    ],
}


def verify_roles(configs: dict[str, dict]) -> list[Check]:
    """Prova con le credenziali reali di ogni ruolo cosa può e cosa NON può fare.

    Ogni istruzione gira in una transazione che viene sempre annullata: nulla resta scritto, anche
    nel caso (da segnalare) in cui un'operazione vietata risulti permessa.
    """
    results = []
    for role, probes in _PROBES.items():
        if role not in configs:
            continue
        conn = psycopg2.connect(**configs[role])
        try:
            for expected, statement in probes:
                with conn.cursor() as cur:
                    try:
                        cur.execute(statement)
                        allowed, detail = True, "eseguita"
                    except psycopg2.errors.InsufficientPrivilege:
                        allowed, detail = False, "permesso negato"
                    except psycopg2.Error as exc:
                        allowed, detail = None, f"errore inatteso: {type(exc).__name__}"
                    finally:
                        conn.rollback()
                ok = allowed is not None and (allowed == (expected == "allowed"))
                results.append(Check(role, statement, expected, ok, detail))
        finally:
            conn.close()
    return results

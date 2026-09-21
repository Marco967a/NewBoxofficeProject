"""Applica le migrazioni SQL del database (o ne mostra lo stato con --status).

Si connette come ruolo *owner* (l'unico con DDL) se configurato, altrimenti come ruolo applicativo.
Dopo le migrazioni riapplica i privilegi dei ruoli app/ro (app/roles.py).
"""
import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection
from app.migrations import apply_pending, load_migrations, pending_migrations
from app.roles import RoleNames, apply_object_grants


def _apply_grants(conn) -> None:
    names = RoleNames.from_env()
    with conn.cursor() as cur:
        cur.execute("SELECT current_user")
        current = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)", ([names.app, names.ro],))
        roles_present = cur.fetchone()[0]
        if current == names.app or not roles_present:
            return  # ruoli non separati (es. CI, sviluppo con un solo utente): niente da riapplicare
        unknown = apply_object_grants(cur, names)
    conn.commit()
    if unknown:
        print(
            f"ATTENZIONE: nessun privilegio definito per {', '.join(unknown)}: aggiungili a TABLE_PRIVILEGES "
            "in app/roles.py e riesegui questo comando. Fino ad allora i ruoli app/ro non vi accedono."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrazioni del database boxoffice")
    parser.add_argument("--status", action="store_true", help="Mostra le migrazioni da applicare senza eseguirle")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with get_connection(role="owner") as conn:
        if args.status:
            pending = {m.version for m in pending_migrations(conn)}
            for migration in load_migrations():
                state = "DA APPLICARE" if migration.version in pending else "applicata"
                print(f"{migration.version}_{migration.name}: {state}")
            return

        applied = apply_pending(conn)
        _apply_grants(conn)
        print(f"Migrazioni applicate: {len(applied)}" if applied else "Schema già aggiornato.")


if __name__ == "__main__":
    main()

"""Crea i ruoli PostgreSQL a privilegi minimi, ne assegna i privilegi e ne conserva le password nel deposito.

Va eseguito da un amministratore (superutente). Le password dei ruoli vengono generate a caso, salvate nel
deposito credenziali e mai stampate. Idempotente: rieseguirlo riallinea i privilegi; con --rotate cambia le password.

    python scripts/setup_db_roles.py --database boxoffice --database boxoffice_dev
    python scripts/setup_db_roles.py --verify-only
"""
import argparse
import dataclasses
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.credentials import get_secret, set_secret, vault_backend_name
from app.roles import RoleNames, generate_password, setup_roles, verify_roles
from app.settings import get_settings


def _admin_config(args) -> dict:
    """Credenziali dell'amministratore: ambiente, deposito 'db:<admin>', ambiente attuale (--admin-from-env) o richiesta."""
    base = get_settings(require_tmdb=False)
    if args.admin_from_env:
        return {**base.db_config, "dbname": "postgres"}
    password = os.getenv("PG_ADMIN_PASSWORD") or get_secret(f"db:{args.admin_user}")
    if not password:
        password = getpass.getpass(f"Password di '{args.admin_user}' (amministratore PostgreSQL): ")
    return {**base.db_config, "user": args.admin_user, "password": password, "dbname": "postgres"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ruoli PostgreSQL a privilegi minimi")
    parser.add_argument("--database", action="append", help="Database da configurare (ripetibile; default: DB_NAME)")
    parser.add_argument("--admin-user", default="postgres")
    parser.add_argument("--admin-from-env", action="store_true",
                        help="Usa DB_USER/DB_PASSWORD attuali come amministratore (passaggio iniziale)")
    parser.add_argument("--rotate", action="store_true", help="Genera nuove password per tutti i ruoli")
    parser.add_argument("--no-test-role", action="store_true", help="Non creare il ruolo per i test locali")
    parser.add_argument("--verify-only", action="store_true", help="Non modifica nulla: verifica i permessi dei ruoli")
    args = parser.parse_args()

    names = RoleNames.from_env()
    base = get_settings(require_tmdb=False)
    databases = args.database or [base.db_name]
    print(f"Deposito credenziali: {vault_backend_name()}")

    admin = None
    if not args.verify_only:
        admin = _admin_config(args)
        # Durante la transizione DB_USER è ancora l'amministratore: il ruolo applicativo non può essere lui.
        if names.app == admin["user"]:
            names = dataclasses.replace(names, app=RoleNames.app)
            print(f"DB_USER coincide con l'amministratore: il ruolo applicativo sarà '{names.app}'.")
    role_of = {"owner": names.owner, "app": names.app, "ro": names.ro, "test": names.test}

    if not args.verify_only:
        # salva la password dell'amministratore nel deposito: non deve restare in chiaro in .env
        if not args.admin_from_env and not get_secret(f"db:{args.admin_user}"):
            set_secret(f"db:{args.admin_user}", admin["password"])
        elif args.admin_from_env and not get_secret(f"db:{admin['user']}"):
            set_secret(f"db:{admin['user']}", admin["password"])
            print(f"Password di '{admin['user']}' salvata nel deposito ('db:{admin['user']}').")

        passwords = {}
        for key, role in role_of.items():
            if key == "test" and args.no_test_role:
                continue
            existing = None if args.rotate else get_secret(f"db:{role}")
            passwords[key] = existing or generate_password()
            set_secret(f"db:{role}", passwords[key])  # nel deposito PRIMA che nel database: niente password perse

        for database in databases:
            result = setup_roles(admin, database, names, passwords, include_test_role=not args.no_test_role)
            print(f"[{database}] proprietà trasferita per: {', '.join(result['ownership_transferred'])}")
            if result["objects_without_privileges"]:
                print(f"[{database}] ATTENZIONE, senza privilegi definiti: {', '.join(result['objects_without_privileges'])}")

    print("\nVerifica dei permessi (ogni prova è annullata):")
    failures = 0
    for database in databases:
        configs = {}
        for key in ("app", "ro", "owner"):
            password = get_secret(f"db:{role_of[key]}")
            if password:
                configs[key] = {**base.db_config, "dbname": database, "user": role_of[key], "password": password}
        for check in verify_roles(configs):
            mark = "OK " if check.ok else "KO "
            failures += not check.ok
            print(f"  [{database}] {mark} {check.role:<5} {check.expected:<7} {check.statement[:70]:<70} -> {check.detail}")
    print(f"\nEsito: {'tutto come previsto' if not failures else f'{failures} verifiche FALLITE'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

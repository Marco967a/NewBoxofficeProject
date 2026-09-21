"""Gestione dei segreti nel deposito credenziali del sistema (Gestione credenziali di Windows).

    python scripts/manage_secrets.py list                 # quali segreti ci sono (mai i valori)
    python scripts/manage_secrets.py set tmdb_read_token  # chiede il valore senza mostrarlo
    python scripts/manage_secrets.py get db:postgres --show
    python scripts/manage_secrets.py delete tmdb_api_key
    python scripts/manage_secrets.py import-env --strip   # sposta i segreti di .env nel deposito

Nomi: tmdb_api_key, tmdb_read_token, db:<ruolo> (es. db:boxoffice_app).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.credentials import KNOWN_NAMES, delete_secret, get_secret, set_secret, vault_backend_name
from app.roles import RoleNames
from app.settings import ENV_PATH

# (variabile di .env, nome nel deposito); nome vuoto = dipende da DB_USER (db:<utente>)
ENV_TO_VAULT = (("TMDB_API_KEY", "tmdb_api_key"), ("TMDB_READ_TOKEN", "tmdb_read_token"), ("DB_PASSWORD", ""))


def _stored(name: str):
    """Valore nel deposito, ignorando le variabili d'ambiente (serve a sapere cosa c'è davvero nel deposito)."""
    return get_secret(name)


def cmd_list(_args) -> None:
    names = RoleNames.from_env()
    known = [*KNOWN_NAMES, *(f"db:{r}" for r in (names.owner, names.app, names.ro, names.test, "postgres"))]
    print(f"Deposito: {vault_backend_name()}")
    for name in dict.fromkeys(known):
        value = _stored(name)
        print(f"  {name:<24} {'presente (' + str(len(value)) + ' caratteri)' if value else 'assente'}")
    from_env = [v for v in ("TMDB_API_KEY", "TMDB_READ_TOKEN", "DB_PASSWORD") if os.getenv(v)]
    if from_env:
        print(f"\nATTENZIONE: nell'ambiente/.env ci sono ancora segreti in chiaro: {', '.join(from_env)}")


def cmd_set(args) -> None:
    value = sys.stdin.readline().rstrip("\r\n") if args.stdin else getpass.getpass(f"Valore di '{args.name}': ")
    if not value:
        raise SystemExit("Valore vuoto: niente da salvare.")
    set_secret(args.name, value)
    if _stored(args.name) != value:
        raise SystemExit("Verifica fallita: il valore letto dal deposito non coincide.")
    print(f"'{args.name}' salvato nel deposito ({len(value)} caratteri).")


def cmd_get(args) -> None:
    value = _stored(args.name)
    if not value:
        raise SystemExit(f"'{args.name}' non è nel deposito.")
    print(value if args.show else f"'{args.name}' presente ({len(value)} caratteri). Usa --show per stamparlo.")


def cmd_delete(args) -> None:
    print("Eliminato." if delete_secret(args.name) else f"'{args.name}' non era nel deposito.")


def cmd_import_env(args) -> None:
    """Sposta nel deposito i segreti presenti in .env e (con --strip) li toglie dal file, dopo aver verificato."""
    if not ENV_PATH.exists():
        raise SystemExit(f"{ENV_PATH} non esiste.")
    text = ENV_PATH.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    db_user = values.get("DB_USER", "")
    to_move = {}
    for env_key, vault_name in ENV_TO_VAULT:
        if values.get(env_key):
            name = vault_name or (f"db:{db_user}" if db_user else None)
            if name:
                to_move[env_key] = (name, values[env_key])

    if not to_move:
        print("Nessun segreto in .env: niente da importare.")
        return

    for env_key, (name, value) in to_move.items():
        existing = _stored(name)
        if existing and existing != value:
            raise SystemExit(f"'{name}' esiste già nel deposito con un valore diverso: non lo sovrascrivo.")
        set_secret(name, value)
        if _stored(name) != value:
            raise SystemExit(f"Verifica fallita per '{name}': .env non è stato modificato.")
        print(f"  {env_key} -> deposito '{name}' (verificato)")

    if args.strip:
        keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in to_move]
        ENV_PATH.write_bytes((newline.join(keep) + newline).encode("utf-8"))
        print(f"Righe rimosse da .env: {', '.join(to_move)}")
    else:
        print("`.env` non modificato: rieseguire con --strip per rimuovere i segreti dal file.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gestione dei segreti nel deposito credenziali")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p = sub.add_parser("set")
    p.add_argument("name")
    p.add_argument("--stdin", action="store_true", help="Legge il valore dallo standard input (automazione)")
    p.set_defaults(func=cmd_set)
    p = sub.add_parser("get")
    p.add_argument("name")
    p.add_argument("--show", action="store_true", help="Stampa il valore in chiaro")
    p.set_defaults(func=cmd_get)
    p = sub.add_parser("delete")
    p.add_argument("name")
    p.set_defaults(func=cmd_delete)
    p = sub.add_parser("import-env")
    p.add_argument("--strip", action="store_true", help="Rimuove i segreti da .env dopo averli spostati")
    p.set_defaults(func=cmd_import_env)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

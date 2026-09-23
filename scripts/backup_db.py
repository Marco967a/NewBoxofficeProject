"""Backup del database con pg_dump (formato custom) in backups/.

Usa il ruolo owner (che possiede tutti gli oggetti); la password passa a pg_dump solo tramite la variabile
d'ambiente PGPASSWORD del processo figlio, mai nella riga di comando. Ripristino:
    pg_restore -h localhost -U <admin> -d <database_vuoto> backups/<file>.dump

Dopo ogni backup applica una retention automatica (--keep-days/--keep-min) sui dump dello stesso
database: i backup sono manuali e irregolari (prima di operazioni rischiose), quindi senza pulizia
la cartella cresce senza limite.
"""
import argparse
import glob
import os
import shutil
import subprocess  # nosec B404 - solo pg_dump, con argomenti fissi e senza shell
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.settings import get_db_config

BACKUP_DIR = REPO_ROOT / "backups"


def find_pg_dump() -> str:
    found = shutil.which("pg_dump")
    if found:
        return found
    candidates = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise SystemExit("pg_dump non trovato: aggiungi la cartella bin di PostgreSQL al PATH.")


def select_backups_to_prune(paths_with_mtime, keep_days: int, keep_min: int, now: datetime | None = None):
    """Quali dump cancellare: tiene sempre i `keep_min` più recenti, poi tra i restanti
    quelli più vecchi di `keep_days`. `paths_with_mtime`: iterabile di (path, datetime)."""
    by_age_desc = sorted(paths_with_mtime, key=lambda item: item[1], reverse=True)
    candidates = by_age_desc[keep_min:]
    cutoff = (now or datetime.now()) - timedelta(days=keep_days)
    return [path for path, mtime in candidates if mtime < cutoff]


def prune_old_backups(database: str, keep_days: int, keep_min: int) -> None:
    existing = [
        (Path(p), datetime.fromtimestamp(Path(p).stat().st_mtime))
        for p in glob.glob(str(BACKUP_DIR / f"{database}_*.dump"))
    ]
    to_delete = select_backups_to_prune(existing, keep_days, keep_min)
    for path in to_delete:
        path.unlink()
        print(f"Backup rimosso (retention {keep_days}g, minimo {keep_min}): {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup del database")
    parser.add_argument("--label", default="manuale", help="Etichetta nel nome del file")
    parser.add_argument("--database", help="Database da salvare (default: DB_NAME)")
    parser.add_argument("--keep-days", type=int, default=30, help="Cancella i dump più vecchi di N giorni (default: 30)")
    parser.add_argument("--keep-min", type=int, default=3, help="Ma tiene sempre almeno gli ultimi N dump (default: 3)")
    args = parser.parse_args()

    config = get_db_config("owner")
    database = args.database or config["dbname"]
    BACKUP_DIR.mkdir(exist_ok=True)
    output = BACKUP_DIR / f"{database}_{args.label}_{datetime.now():%Y%m%d_%H%M%S}.dump"

    command = [
        find_pg_dump(), "-h", str(config["host"]), "-p", str(config["port"]), "-U", config["user"],
        "-d", database, "-Fc", "-f", str(output),
    ]
    env = {**os.environ, "PGPASSWORD": config["password"]}
    subprocess.run(command, env=env, check=True)  # nosec B603 - argomenti da configurazione, nessuna shell
    print(f"Backup creato: {output} ({output.stat().st_size} byte)")

    prune_old_backups(database, args.keep_days, args.keep_min)


if __name__ == "__main__":
    main()

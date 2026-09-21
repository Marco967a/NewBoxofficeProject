"""Controlli di salute della pipeline e dei dati. Esce con codice 1 se c'è almeno un FAIL."""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection
from app.health import FAIL, WARN, run_health_checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Health check del database boxoffice")
    parser.add_argument("--source-name", default="comingsoon")
    parser.add_argument("--territory", default="IT")
    parser.add_argument("--max-age-days", type=int, default=8, help="Età massima dell'ultimo run riuscito")
    parser.add_argument("--gap-weeks", type=int, default=12, help="Finestra (settimane) per cercare i buchi")
    parser.add_argument("--strict", action="store_true", help="Considera fallimento anche i WARN")
    args = parser.parse_args()

    with get_connection(role="ro") as conn:  # sola lettura: i controlli non scrivono nulla
        results = run_health_checks(
            conn, args.source_name, args.territory, args.max_age_days, args.gap_weeks
        )

    for r in results:
        print(f"[{r.level:<4}] {r.name}: {r.message}")

    fails = sum(r.level == FAIL for r in results)
    warns = sum(r.level == WARN for r in results)
    print(f"\nEsito: {fails} FAIL, {warns} WARN")
    if fails or (args.strict and warns):
        sys.exit(1)


if __name__ == "__main__":
    main()

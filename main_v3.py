import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bootstrap import main as bootstrap_main
from scripts.weekly_run import main as weekly_main


def main():
    print("Avvio pipeline di ingestion...")

    print("=== PHASE 1: Bootstrap Movies ===")
    bootstrap_main()

    print("=== PHASE 2: Weekly Box Office ===")
    weekly_main()

    print("=== Pipeline completato ===")


if __name__ == "__main__":
    main()
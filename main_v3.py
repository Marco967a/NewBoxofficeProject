from scripts.resolve_matches import main as resolve_main
from scripts.weekly_run import main as weekly_main


def main():
    print("Avvio pipeline di ingestion...")

    print("=== PHASE 1: Weekly Box Office ===")
    weekly_main()

    print("=== PHASE 2: Match film (movie_id) ===")
    resolve_main()

    print("=== Pipeline completato ===")


if __name__ == "__main__":
    main()

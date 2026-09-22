"""Collega i film dei box office ai film TMDB (popola source_movies.movie_id e weekly_box_office.movie_id)."""
import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.movie_matching_service import MovieMatchingService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Risoluzione dei match box office -> TMDB")
    parser.add_argument("--source-name", default="comingsoon")
    parser.add_argument("--dry-run", action="store_true", help="Valuta i match senza scrivere sul database")
    parser.add_argument("--limit", type=int, help="Massimo numero di film da abbinare in questa esecuzione")
    parser.add_argument(
        "--retry", action="store_true",
        help="Riprova anche i film 'needs_review' e 'no_match' (i match manuali non si toccano mai)",
    )
    parser.add_argument("--skip-legacy", action="store_true", help="Non collegare le righe storiche senza ID")
    parser.add_argument("--review", action="store_true", help="Mostra i match incerti con i candidati e termina")
    parser.add_argument("--set", type=int, metavar="ID", help="Match manuale: id di source_movies (vedi --review)")
    parser.add_argument("--tmdb-id", type=int, help="ID TMDB da usare con --set")
    parser.add_argument("--no-match", type=int, metavar="ID", help="Segna il film come non presente su TMDB")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(message)s")
    service = MovieMatchingService()

    if args.set is not None:
        if args.tmdb_id is None:
            raise SystemExit("--set richiede --tmdb-id")
        result = service.set_manual_match(args.set, args.tmdb_id)
        print(f"Match manuale: {result['source']!r} -> tmdb={result['tmdb_id']} ({result['tmdb_title']!r})")
        return

    if args.no_match is not None:
        print(f"Segnato come non presente su TMDB: {service.set_no_match(args.no_match)!r}")
        return

    if args.review:
        queue = service.review_queue(args.source_name)
        if not queue:
            print("Nessun match da rivedere.")
        for item in queue:
            print(f"\n#{item['id']}  {item['title']!r}  (ComingSoon id={item['source_movie_id']})")
            for c in item["candidates"]:
                print(f"    tmdb={c['tmdb_id']:<8} score={c['score']:.3f}  {c['title']!r} / {c['original_title']!r}  {c['release_date']}")
        if queue:
            print("\nPer confermare: python scripts/resolve_matches.py --set <ID> --tmdb-id <TMDB>")
            print("Per escludere:  python scripts/resolve_matches.py --no-match <ID>")
        return

    if not args.skip_legacy and not args.dry_run:
        counts = service.link_legacy_rows(args.source_name)
        print(f"Righe storiche: {counts}")

    statuses = ("unmatched", "needs_review", "no_match") if args.retry else ("unmatched",)
    summary = service.resolve_pending(
        source_name=args.source_name, statuses=statuses, limit=args.limit, dry_run=args.dry_run
    )
    for line in summary.lines:
        print(line)
    print(
        f"\nTotale {summary.total}: auto={summary.auto} da_rivedere={summary.needs_review} "
        f"senza_match={summary.no_match} errori={summary.errors}" + (" (dry-run)" if args.dry_run else "")
    )
    if summary.stopped_early:
        print(
            "\nATTENZIONE: interrotto prima di aver provato tutti i film in coda (connessione al database "
            "persa). Riesegui questo comando per riprendere dai film rimasti."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection

QUERY_COUNT = "SELECT COUNT(*) FROM weekly_box_office WHERE source_name = %s"
QUERY_SAMPLE = "SELECT week_start, week_end, rank, external_movie_title, weekly_gross FROM weekly_box_office WHERE source_name = %s ORDER BY week_start DESC, rank ASC LIMIT 5"
QUERY_COVERAGE = "SELECT COUNT(movie_id), COUNT(*) FROM weekly_box_office WHERE source_name = %s"
QUERY_STATUSES = (
    "SELECT match_status, COUNT(*) FROM source_movies WHERE source_name = %s GROUP BY 1 ORDER BY 1"
)
# Righe settimanali il cui movie_id non coincide con quello del film sorgente (dovrebbero essere 0)
QUERY_INCONSISTENT = """
    SELECT COUNT(*) FROM weekly_box_office w
    JOIN source_movies s ON s.id = w.source_movie_ref
    WHERE w.source_name = %s AND w.movie_id IS DISTINCT FROM s.movie_id
"""
QUERY_UNLINKED = "SELECT COUNT(*) FROM weekly_box_office WHERE source_name = %s AND source_movie_ref IS NULL"

if __name__ == '__main__':
    source = 'comingsoon'
    with get_connection(role="ro") as conn:
        with conn.cursor() as cur:
            cur.execute(QUERY_COUNT, (source,))
            count = cur.fetchone()[0]
            print(f"Rows for source '{source}': {count}")

            cur.execute(QUERY_SAMPLE, (source,))
            rows = cur.fetchall()
            print("Sample rows:")
            for r in rows:
                print(r)

            cur.execute(QUERY_COVERAGE, (source,))
            with_movie, total = cur.fetchone()
            pct = f"{100 * with_movie / total:.0f}%" if total else "n/d"
            print(f"\nCopertura movie_id: {with_movie}/{total} righe ({pct})")

            cur.execute(QUERY_STATUSES, (source,))
            print("Stato dei match:", dict(cur.fetchall()))

            cur.execute(QUERY_INCONSISTENT, (source,))
            inconsistent = cur.fetchone()[0]
            cur.execute(QUERY_UNLINKED, (source,))
            unlinked = cur.fetchone()[0]
            print(f"Righe con movie_id incoerente rispetto a source_movies: {inconsistent} (atteso 0)")
            print(f"Righe senza film sorgente collegato: {unlinked} (atteso 0 dopo resolve_matches.py)")
            if inconsistent:
                sys.exit(1)

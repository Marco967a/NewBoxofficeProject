import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection

QUERY_COUNT = "SELECT COUNT(*) FROM weekly_box_office WHERE source_name = %s"
QUERY_SAMPLE = "SELECT week_start, week_end, rank, external_movie_title, weekly_gross FROM weekly_box_office WHERE source_name = %s ORDER BY week_start DESC, rank ASC LIMIT 5"

if __name__ == '__main__':
    source = 'comingsoon'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(QUERY_COUNT, (source,))
            count = cur.fetchone()[0]
            print(f"Rows for source '{source}': {count}")

            cur.execute(QUERY_SAMPLE, (source,))
            rows = cur.fetchall()
            print("Sample rows:")
            for r in rows:
                print(r)

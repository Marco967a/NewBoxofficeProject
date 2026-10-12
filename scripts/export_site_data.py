"""Esporta i KPI per il sito pubblico in un JSON statico.

Se l'health check segnala un FAIL non scrive nulla: chi chiama (run_weekly.ps1) salta il push
e il sito resta con l'ultimo JSON buono, riconoscibile dal suo "generated_at".
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import get_connection
from app.health import FAIL, WARN, run_health_checks

TREND_WEEKS = 8
TOP_N = 5


def _num(value):
    return float(value) if isinstance(value, Decimal) else value


def _latest_week(conn, source_name, territory):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(week_start) FROM weekly_box_office WHERE source_name = %s AND territory = %s",
            (source_name, territory),
        )
        return cur.fetchone()[0]


def _weekly_trend(conn, source_name, territory, weeks):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_start, sum(weekly_gross), count(*)
            FROM weekly_box_office
            WHERE source_name = %s AND territory = %s
            GROUP BY week_start
            ORDER BY week_start DESC
            LIMIT %s
            """,
            (source_name, territory, weeks),
        )
        rows = cur.fetchall()
    return [
        {"week_start": str(week_start), "total_gross": _num(total), "titles": count}
        for week_start, total, count in reversed(rows)
    ]


def _top_titles(conn, source_name, territory, week_start, limit):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rank, external_movie_title, weekly_gross, screen_count
            FROM weekly_box_office
            WHERE source_name = %s AND territory = %s AND week_start = %s
            ORDER BY rank
            LIMIT %s
            """,
            (source_name, territory, week_start, limit),
        )
        rows = cur.fetchall()
    return [
        {"rank": rank, "title": title, "weekly_gross": _num(gross), "screen_count": screens}
        for rank, title, gross, screens in rows
    ]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_payload(payload: dict) -> list[str]:
    """Controlla che il JSON abbia la forma che il sito si aspetta; ritorna i problemi trovati."""
    problems = []

    for key in ("source", "territory", "currency", "latest_week", "note"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            problems.append(f"{key}: stringa non vuota attesa")
    if not isinstance(payload.get("has_quality_warnings"), bool):
        problems.append("has_quality_warnings: booleano atteso")

    for key in ("generated_at", "latest_week"):
        try:
            datetime.fromisoformat(str(payload.get(key)))
        except ValueError:
            problems.append(f"{key}: data ISO non valida")

    trend = payload.get("weekly_trend")
    if not isinstance(trend, list) or not trend:
        problems.append("weekly_trend: lista non vuota attesa")
    else:
        for i, row in enumerate(trend):
            if not (isinstance(row, dict) and isinstance(row.get("week_start"), str)
                    and _is_number(row.get("total_gross")) and isinstance(row.get("titles"), int)):
                problems.append(f"weekly_trend[{i}]: week_start, total_gross, titles attesi")

    top = payload.get("top_titles")
    if not isinstance(top, list) or not top:
        problems.append("top_titles: lista non vuota attesa")
    else:
        for i, row in enumerate(top):
            if not (isinstance(row, dict) and isinstance(row.get("rank"), int)
                    and isinstance(row.get("title"), str) and row["title"]
                    and _is_number(row.get("weekly_gross"))
                    and (row.get("screen_count") is None or isinstance(row["screen_count"], int))):
                problems.append(f"top_titles[{i}]: rank, title, weekly_gross (screen_count opzionale) attesi")

    return problems


def build_payload(conn, source_name: str, territory: str) -> dict:
    results = run_health_checks(conn, source_name, territory)
    if any(r.level == FAIL for r in results):
        failed = "; ".join(f"{r.name}: {r.message}" for r in results if r.level == FAIL)
        raise SystemExit(f"health check in FAIL, nessun export: {failed}")

    latest_week = _latest_week(conn, source_name, territory)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_name,
        "territory": territory,
        "currency": "EUR",
        "latest_week": str(latest_week),
        "has_quality_warnings": any(r.level == WARN for r in results),
        "note": (
            "Dati aggregati dal box office italiano (fonte: ComingSoon). "
            "Alcune settimane storiche possono mancare o presentare piccole anomalie di fonte."
        ),
        "weekly_trend": _weekly_trend(conn, source_name, territory, TREND_WEEKS),
        "top_titles": _top_titles(conn, source_name, territory, latest_week, TOP_N),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Esporta i KPI del box office per il sito pubblico")
    parser.add_argument("--source-name", default="comingsoon")
    parser.add_argument("--territory", default="IT")
    parser.add_argument("--out", default=str(REPO_ROOT / "site_data" / "boxoffice.json"))
    args = parser.parse_args()

    with get_connection(role="ro") as conn:
        payload = build_payload(conn, args.source_name, args.territory)

    problems = validate_payload(payload)
    if problems:
        raise SystemExit("payload non valido, nessun export: " + "; ".join(problems))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scritto {out_path} ({len(payload['weekly_trend'])} settimane, {len(payload['top_titles'])} titoli)")


if __name__ == "__main__":
    main()

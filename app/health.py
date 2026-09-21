"""Controlli di salute e qualità sul database (usati da scripts/health_check.py e dallo scheduler).

Ogni controllo ritorna un livello: OK, WARN (da guardare) o FAIL (la pipeline non sta funzionando
o i dati sono incoerenti). Solo i FAIL fanno uscire scripts/health_check.py con codice diverso da 0.
"""
from dataclasses import dataclass

OK, WARN, FAIL = "OK", "WARN", "FAIL"

# La classifica del weekend (giovedì-domenica) compare entro lunedì e resta fino al weekend dopo:
# oltre 10 giorni dall'inizio dell'ultima settimana ne manca una, oltre 14 è un guasto.
LATEST_WEEK_WARN_DAYS = 10
LATEST_WEEK_FAIL_DAYS = 14
MIN_ROWS_PER_WEEK = 10
MIN_MOVIE_ID_COVERAGE = 0.85


@dataclass(frozen=True)
class CheckResult:
    name: str
    level: str
    message: str


def _one(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _all(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def check_last_run(conn, source_name: str, max_age_days: int) -> CheckResult:
    name = "ultimo run"
    last = _one(
        conn,
        """
        SELECT status, started_at, error_message
        FROM ingestion_runs
        WHERE pipeline_name = 'weekly_box_office' AND source_name = %s
        ORDER BY id DESC LIMIT 1
        """,
        (source_name,),
    )
    if last is None:
        return CheckResult(name, FAIL, f"nessun run registrato per '{source_name}'")

    status, _, error = last
    if status == "failed":
        return CheckResult(name, FAIL, f"l'ultimo run è fallito: {(error or '')[:150]}")

    age = _one(
        conn,
        """
        SELECT EXTRACT(EPOCH FROM (now() - max(COALESCE(finished_at, started_at)))) / 86400
        FROM ingestion_runs
        WHERE pipeline_name = 'weekly_box_office' AND source_name = %s AND status = 'success'
        """,
        (source_name,),
    )[0]
    if age is None:
        return CheckResult(name, FAIL, "nessun run concluso con successo")
    if age > max_age_days:
        return CheckResult(name, FAIL, f"ultimo run riuscito {age:.1f} giorni fa (massimo {max_age_days})")
    if status == "running":
        return CheckResult(name, WARN, "un run risulta ancora in corso (o interrotto senza esito)")
    return CheckResult(name, OK, f"ultimo run riuscito {age:.1f} giorni fa")


def check_latest_week(conn, source_name: str, territory: str) -> CheckResult:
    name = "ultima settimana"
    row = _one(
        conn,
        """
        SELECT week_start, current_date - week_start AS age_days, count(*)
        FROM weekly_box_office
        WHERE source_name = %s AND territory = %s
        GROUP BY week_start
        ORDER BY week_start DESC
        LIMIT 1
        """,
        (source_name, territory),
    )
    if row is None:
        return CheckResult(name, FAIL, "nessun dato in weekly_box_office")

    week_start, age_days, n_rows = row
    if age_days > LATEST_WEEK_FAIL_DAYS:
        return CheckResult(name, FAIL, f"ultima settimana {week_start} ({age_days} giorni fa): mancano dati recenti")
    if age_days > LATEST_WEEK_WARN_DAYS:
        return CheckResult(name, WARN, f"ultima settimana {week_start} ({age_days} giorni fa): probabile settimana mancante")
    if n_rows < MIN_ROWS_PER_WEEK:
        return CheckResult(name, WARN, f"settimana {week_start} con sole {n_rows} righe (attese almeno {MIN_ROWS_PER_WEEK})")
    return CheckResult(name, OK, f"settimana {week_start}, {n_rows} righe")


def missing_weeks(conn, source_name: str, territory: str, weeks: int) -> list:
    """Giovedì delle settimane mancanti nelle ultime `weeks`, a partire dalla prima settimana mai caricata."""
    rows = _all(
        conn,
        """
        WITH bounds AS (
            SELECT min(week_start) AS lo, max(week_start) AS hi
            FROM weekly_box_office WHERE source_name = %s AND territory = %s
        ),
        expected AS (
            SELECT (hi - g * 7) AS ws, lo FROM bounds, generate_series(0, %s) AS g
        )
        SELECT ws FROM expected e
        WHERE e.ws >= e.lo - 3
          AND NOT EXISTS (
              SELECT 1 FROM weekly_box_office w
              WHERE w.source_name = %s AND w.territory = %s
                AND w.week_start BETWEEN e.ws - 3 AND e.ws + 3)
        ORDER BY ws
        """,
        (source_name, territory, weeks, source_name, territory),
    )
    return [r[0] for r in rows]


def check_gaps(conn, source_name: str, territory: str, weeks: int) -> CheckResult:
    """Settimane mancanti nelle ultime `weeks`, a partire dalla prima settimana mai caricata."""
    name = "buchi nello storico"
    missing = missing_weeks(conn, source_name, territory, weeks)
    if not missing:
        return CheckResult(name, OK, f"nessuna settimana mancante nelle ultime {weeks}")
    shown = ", ".join(str(d) for d in missing[:6]) + (" …" if len(missing) > 6 else "")
    return CheckResult(name, WARN, f"{len(missing)} settimane mancanti nelle ultime {weeks}: {shown}")


def check_integrity(conn, source_name: str) -> list[CheckResult]:
    results = []

    inconsistent = _one(
        conn,
        """
        SELECT count(*) FROM weekly_box_office w
        JOIN source_movies s ON s.id = w.source_movie_ref
        WHERE w.source_name = %s AND w.movie_id IS DISTINCT FROM s.movie_id
        """,
        (source_name,),
    )[0]
    results.append(
        CheckResult("coerenza movie_id", FAIL, f"{inconsistent} righe con movie_id diverso da source_movies")
        if inconsistent else CheckResult("coerenza movie_id", OK, "weekly e source_movies allineati")
    )

    unlinked = _one(
        conn,
        "SELECT count(*) FROM weekly_box_office WHERE source_name = %s AND source_movie_ref IS NULL",
        (source_name,),
    )[0]
    results.append(
        CheckResult("righe collegate", WARN, f"{unlinked} righe senza film sorgente: esegui scripts/resolve_matches.py")
        if unlinked else CheckResult("righe collegate", OK, "tutte le righe hanno un film sorgente")
    )

    pending = dict(_all(
        conn,
        """
        SELECT match_status, count(*) FROM source_movies
        WHERE source_name = %s AND match_status IN ('unmatched', 'needs_review') GROUP BY 1
        """,
        (source_name,),
    ))
    parts = []
    if pending.get("unmatched"):
        parts.append(f"{pending['unmatched']} da abbinare (scripts/resolve_matches.py)")
    if pending.get("needs_review"):
        parts.append(f"{pending['needs_review']} da rivedere (scripts/resolve_matches.py --review)")
    results.append(
        CheckResult("coda match", WARN, "; ".join(parts)) if parts else CheckResult("coda match", OK, "nessun match in sospeso")
    )

    ambiguous = _all(
        conn,
        """
        SELECT external_movie_title FROM weekly_box_office
        WHERE source_name = %s AND movie_id IS NOT NULL
        GROUP BY external_movie_title HAVING count(DISTINCT movie_id) > 1
        ORDER BY 1
        """,
        (source_name,),
    )
    if ambiguous:
        titles = ", ".join(repr(r[0]) for r in ambiguous[:4]) + (" …" if len(ambiguous) > 4 else "")
        results.append(CheckResult(
            "coerenza titoli", WARN, f"{len(ambiguous)} titoli abbinati a più film TMDB (da rivedere): {titles}"
        ))
    else:
        results.append(CheckResult("coerenza titoli", OK, "ogni titolo è abbinato a un solo film TMDB"))
    return results


def check_latest_week_coverage(conn, source_name: str, territory: str) -> CheckResult:
    name = "copertura movie_id"
    row = _one(
        conn,
        """
        SELECT count(movie_id), count(*)
        FROM weekly_box_office
        WHERE source_name = %s AND territory = %s
          AND week_start = (SELECT max(week_start) FROM weekly_box_office WHERE source_name = %s AND territory = %s)
        """,
        (source_name, territory, source_name, territory),
    )
    with_id, total = row
    if not total:
        return CheckResult(name, WARN, "nessuna riga nell'ultima settimana")
    ratio = with_id / total
    text = f"{with_id}/{total} righe dell'ultima settimana ({ratio:.0%})"
    return CheckResult(name, OK if ratio >= MIN_MOVIE_ID_COVERAGE else WARN, text)


def check_anomalies(conn, source_name: str, territory: str, weeks: int) -> CheckResult:
    """Anomalie della sorgente nelle ultime settimane: classifica non ordinata per incasso, totale < weekend."""
    name = "anomalie sorgente"
    rows = _all(
        conn,
        """
        SELECT week_start, rank, external_movie_title, weekly_gross, total_gross, prev_gross
        FROM (
            SELECT week_start, rank, external_movie_title, weekly_gross, total_gross,
                   lag(weekly_gross) OVER (PARTITION BY week_start ORDER BY rank) AS prev_gross
            FROM weekly_box_office
            WHERE source_name = %s AND territory = %s
              AND week_start >= (SELECT max(week_start) FROM weekly_box_office
                                 WHERE source_name = %s AND territory = %s) - %s * 7
        ) t
        WHERE (prev_gross IS NOT NULL AND weekly_gross > prev_gross)
           OR (total_gross IS NOT NULL AND total_gross < weekly_gross)
        ORDER BY week_start DESC, rank
        """,
        (source_name, territory, source_name, territory, weeks),
    )
    if not rows:
        return CheckResult(name, OK, f"nessuna anomalia nelle ultime {weeks + 1} settimane")
    examples = "; ".join(f"{r[0]} #{r[1]} {r[2]!r}" for r in rows[:3]) + (" …" if len(rows) > 3 else "")
    return CheckResult(name, WARN, f"{len(rows)} righe sospette (dato di sorgente da verificare): {examples}")


def run_health_checks(
    conn,
    source_name: str = "comingsoon",
    territory: str = "IT",
    max_age_days: int = 8,
    gap_weeks: int = 12,
) -> list[CheckResult]:
    return [
        check_last_run(conn, source_name, max_age_days),
        check_latest_week(conn, source_name, territory),
        check_gaps(conn, source_name, territory, gap_weeks),
        *check_integrity(conn, source_name),
        check_latest_week_coverage(conn, source_name, territory),
        check_anomalies(conn, source_name, territory, weeks=3),
    ]

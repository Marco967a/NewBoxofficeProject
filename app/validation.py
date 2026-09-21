"""Controlli di qualità sui record box office settimanali.

I controlli non scartano nulla: restituiscono avvisi leggibili, perché le anomalie
possono venire dalla sorgente (es. ComingSoon che pubblica "504.61" invece di "504.610").
"""
from collections import defaultdict

MIN_ROWS_PER_WEEK = 10
MAX_ROWS_PER_WEEK = 20


def _get(record, field, default=None):
    if isinstance(record, dict):
        return record.get(field, default)
    return getattr(record, field, default)


def validate_weekly_records(records: list) -> list[str]:
    """Ritorna la lista degli avvisi di qualità per i record forniti."""
    warnings: list[str] = []
    by_week = defaultdict(list)
    for record in records:
        by_week[(_get(record, "week_start"), _get(record, "week_end"))].append(record)

    for (week_start, week_end), rows in by_week.items():
        label = f"{week_start}..{week_end}"

        if not MIN_ROWS_PER_WEEK <= len(rows) <= MAX_ROWS_PER_WEEK:
            warnings.append(
                f"[{label}] {len(rows)} righe, atteso tra {MIN_ROWS_PER_WEEK} e {MAX_ROWS_PER_WEEK}"
            )

        ranks = [_get(r, "rank") for r in rows]
        if len(set(ranks)) != len(ranks):
            warnings.append(f"[{label}] rank duplicati")

        titles = [_get(r, "external_movie_title") for r in rows]
        if len(set(titles)) != len(titles):
            warnings.append(f"[{label}] titoli duplicati (ne verrà conservato uno solo)")

        ordered = sorted(rows, key=lambda r: _get(r, "rank"))
        previous = None
        for row in ordered:
            gross = _get(row, "weekly_gross")
            total = _get(row, "total_gross")
            title = _get(row, "external_movie_title")
            rank = _get(row, "rank")

            if gross is not None and total is not None and total < gross:
                warnings.append(
                    f"[{label}] rank {rank} '{title}': total_gross {total} < weekly_gross {gross}"
                )
            if previous is not None and gross is not None and gross > previous[1]:
                warnings.append(
                    f"[{label}] rank {rank} '{title}' incassa {gross}, "
                    f"più del rank {previous[0]} ({previous[1]}): classifica non ordinata"
                )
            if gross is not None:
                previous = (rank, gross)

    return warnings

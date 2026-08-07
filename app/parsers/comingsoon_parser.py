import re
from datetime import datetime, date
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from app.models.weekly_record import WeeklyBoxOfficeRecord


COMINGSOON_URL = "https://www.comingsoon.it/cinema/boxoffice/"


MONTHS_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

# Riconosce il link a una scheda film, es:
# https://www.comingsoon.it/film/minions-e-monsters/67915/scheda/
FILM_LINK_HREF = re.compile(r"(?:https?://[^/]+)?/film/[^/]+/\d+/scheda/?$")

# Cerca solo i campi della card di classifica (etichette semplici, NIENTE markdown).
# Le card senza "Settimane:"/"Schermi:" (es. widget USA in fondo pagina, altri box)
# non producono match e vengono scartate automaticamente.
FIELDS_PATTERN = re.compile(
    r"Settimane:\s*(\d+)\s*"
    r"Distribuzione:\s*(.+?)\s*"
    r"Inc\.?\s*weekend:\s*€\s*([\d\.\,]+)\s*"
    r"Schermi:\s*(\d+)\s*"
    r"Inc\.?\s*totale:\s*€\s*([\d\.\,]+)",
    re.DOTALL | re.IGNORECASE
)

RANK_PATTERN = re.compile(r"\b(\d{1,2})\b")


def parse_euro(value: str) -> float:
    cleaned = value.replace("€", "").replace(".", "").replace(",", ".").strip()
    return float(cleaned)


def parse_int(value: str) -> int:
    return int(value.replace(".", "").strip())


def parse_italian_date(day: str, month_name: str, year: str) -> date:
    month = MONTHS_IT.get(month_name.lower())
    if not month:
        raise ValueError(f"Nome mese non riconosciuto: '{month_name}'")

    dt = datetime(int(year), month, int(day))
    return dt.date()


def build_archive_candidate_urls(reference_date: date) -> List[str]:
    year = reference_date.year
    month = f"{reference_date.month:02d}"
    day = f"{reference_date.day:02d}"
    return [
        f"https://www.comingsoon.it/cinema/boxoffice/{year}/{month}/{day}/",
        f"https://www.comingsoon.it/cinema/boxoffice/{year}-{month}-{day}/",
        f"https://www.comingsoon.it/cinema/boxoffice/?date={year}-{month}-{day}",
        f"https://www.comingsoon.it/cinema/boxoffice/?year={year}&month={month}&day={day}",
    ]


def extract_week_range(text: str) -> tuple[Optional[date], Optional[date]]:
    # Try pattern with possibly different months/years for start and end
    pattern_multi = re.search(
        r"dal\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})\s+al\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})",
        text,
        re.IGNORECASE,
    )

    if pattern_multi:
        d1, m1, y1, d2, m2, y2 = pattern_multi.groups()
        start = parse_italian_date(d1, m1, y1)
        end = parse_italian_date(d2, m2, y2)
        return start, end

    # Fallback: same-month pattern
    pattern = re.search(
        r"dal\s+(\d{1,2})\s+al\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})",
        text,
        re.IGNORECASE,
    )

    if not pattern:
        return None, None

    day_start, day_end, month_name, year = pattern.groups()
    week_start = parse_italian_date(day_start, month_name, year)
    week_end = parse_italian_date(day_end, month_name, year)

    return week_start, week_end


def parse_boxoffice_page(html: str, requested_date: Optional[date] = None) -> List[WeeklyBoxOfficeRecord]:
    soup = BeautifulSoup(html, "html.parser")

    week_start, week_end = extract_week_range(soup.get_text(" ", strip=True))
    if not week_start or not week_end:
        if requested_date is None:
            raise RuntimeError("Impossibile estrarre l'intervallo settimanale dalla pagina ComingSoon")
        week_start = requested_date
        week_end = requested_date

    if requested_date is not None and week_start and week_end:
        if requested_date < week_start or requested_date > week_end:
            week_start = requested_date
            week_end = requested_date

    film_links = soup.find_all("a", href=FILM_LINK_HREF)

    records: List[WeeklyBoxOfficeRecord] = []
    seen_ranks = set()

    for a in film_links:
        entry_text = a.get_text("\n", strip=True)
        parents = []
        parent = a.parent
        while parent is not None and len(parents) < 3:
            parents.append(parent)
            parent = parent.parent

        parent_text = "\n".join(part.get_text("\n", strip=True) for part in parents)
        combined_text = "\n".join([entry_text, parent_text])

        fields_match = FIELDS_PATTERN.search(combined_text)
        if not fields_match:
            # Non è una riga di classifica completa (es. widget secondario,
            # sezione "film più attesi", box USA in $ invece che €, ecc.)
            continue

        rank_match = RANK_PATTERN.search(combined_text)
        title = (a.get("title") or a.get_text(" ", strip=True)).strip()

        if not rank_match or not title:
            continue

        rank_int = int(rank_match.group(1))
        if rank_int in seen_ranks:
            continue
        seen_ranks.add(rank_int)

        weeks, distributor, weekend_gross, screens, total_gross = fields_match.groups()

        records.append(
            WeeklyBoxOfficeRecord(
                source_name="comingsoon",
                territory="IT",
                week_start=week_start,
                week_end=week_end,
                rank=rank_int,
                external_movie_title=title,
                distributor=" ".join(distributor.split()),
                weekly_gross=parse_euro(weekend_gross),
                screen_count=parse_int(screens),
                weeks_in_release=int(weeks),
                movie_id=None,
            )
        )

    records.sort(key=lambda r: r.rank)
    return records


def parse_comingsoon_weekly_boxoffice() -> List[WeeklyBoxOfficeRecord]:
    return parse_comingsoon_weekly_boxoffice_for_date()


def parse_comingsoon_weekly_boxoffice_for_date(reference_date: Optional[date] = None) -> List[WeeklyBoxOfficeRecord]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
    }

    urls = [COMINGSOON_URL]
    if reference_date is not None:
        urls = [*urls, *build_archive_candidate_urls(reference_date)]

    last_error: Optional[Exception] = None
    for url in urls:
        try:
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            records = parse_boxoffice_page(response.text, requested_date=reference_date)
            if records:
                return records
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise RuntimeError(f"Impossibile recuperare i dati box office da ComingSoon: {last_error}")

    raise RuntimeError("Impossibile recuperare i dati box office da ComingSoon")


if __name__ == "__main__":
    records = parse_comingsoon_weekly_boxoffice()

    print(f"Record trovati: {len(records)}")
    for record in records[:5]:
        print(record)
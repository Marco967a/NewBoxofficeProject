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


def parse_comingsoon_weekly_boxoffice() -> List[WeeklyBoxOfficeRecord]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
    }
    response = requests.get(COMINGSOON_URL, timeout=30, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    week_start, week_end = extract_week_range(soup.get_text(" ", strip=True))
    if not week_start or not week_end:
        raise RuntimeError("Impossibile estrarre l'intervallo settimanale dalla pagina ComingSoon")

    film_links = soup.find_all("a", href=FILM_LINK_HREF)

    records: List[WeeklyBoxOfficeRecord] = []
    seen_ranks = set()

    for a in film_links:
        entry_text = a.get_text("\n", strip=True)

        fields_match = FIELDS_PATTERN.search(entry_text)
        if not fields_match:
            # Non è una riga di classifica completa (es. widget secondario,
            # sezione "film più attesi", box USA in $ invece che €, ecc.)
            continue

        rank_match = RANK_PATTERN.search(entry_text)
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
                weekly_admissions=None,
                screen_count=parse_int(screens),
                weeks_in_release=int(weeks),
                is_italian=None,
                movie_id=None,
            )
        )

    records.sort(key=lambda r: r.rank)
    return records


if __name__ == "__main__":
    records = parse_comingsoon_weekly_boxoffice()

    print(f"Record trovati: {len(records)}")
    for record in records[:5]:
        print(record)
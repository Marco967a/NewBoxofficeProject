import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup


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


def parse_euro(value: str) -> float:
    cleaned = value.replace("€", "").replace(".", "").replace(",", ".").strip()
    return float(cleaned)


def parse_int(value: str) -> int:
    return int(value.replace(".", "").strip())


def parse_italian_date(day: str, month_name: str, year: str) -> str:
    month = MONTHS_IT[month_name.lower()]
    dt = datetime(int(year), month, int(day))
    return dt.strftime("%Y-%m-%d")


def extract_week_range(text: str) -> tuple[Optional[str], Optional[str]]:
    pattern = re.search(
        r"dal\s+(\d{1,2})\s+al\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})",
        text,
        re.IGNORECASE
    )

    if not pattern:
        return None, None

    day_start, day_end, month_name, year = pattern.groups()
    week_start = parse_italian_date(day_start, month_name, year)
    week_end = parse_italian_date(day_end, month_name, year)

    return week_start, week_end


def extract_top_section(text: str) -> str:
    if "I film più attesi" in text:
        return text.split("I film più attesi")[0]
    return text


def parse_comingsoon_weekly_boxoffice() -> List[Dict]:
    response = requests.get(COMINGSOON_URL, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    raw_text = soup.get_text("\n", strip=True)
    top_text = extract_top_section(raw_text)

    week_start, week_end = extract_week_range(top_text)

    pattern = re.compile(
        r"\n(\d+)\n"                                  # rank
        r"(.+?)\n"                                    # title
        r"\*\*Settimane:\*\*\s*(\d+)\s*"              # weeks_in_release
        r"\*\*Distribuzione:\*\*\s*(.+?)\s*"          # distributor
        r"\*\*Inc\. weekend:\*\*\s*€([\d\.\,]+)\s*"   # weekly_gross
        r"\*\*Schermi:\*\*\s*(\d+)\s*"                # screen_count
        r"\*\*Inc\. totale:\*\*\s*€([\d\.\,]+)",      # total_gross
        re.DOTALL
    )

    matches = pattern.findall(top_text)
    records = []

    for match in matches:
        rank, title, weeks, distributor, weekend_gross, screens, total_gross = match

        records.append({
            "source_name": "comingsoon",
            "territory": "IT",
            "week_start": week_start,
            "week_end": week_end,
            "rank": int(rank),
            "movie_id": None,
            "external_movie_title": " ".join(title.split()),
            "distributor": " ".join(distributor.split()),
            "weekly_gross": parse_euro(weekend_gross),
            "weekly_admissions": None,
            "screen_count": parse_int(screens),
            "weeks_in_release": int(weeks),
            "is_italian": None,
            "total_gross": parse_euro(total_gross),
        })

    return records


if __name__ == "__main__":
    records = parse_comingsoon_weekly_boxoffice()

    print(f"Record trovati: {len(records)}")
    for record in records[:5]:
        print(record)
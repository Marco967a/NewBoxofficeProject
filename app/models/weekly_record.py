# app/models/weekly_record.py
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class WeeklyBoxOfficeRecord:
    source_name: str
    territory: str
    week_start: date
    week_end: date
    rank: int
    external_movie_title: str
    distributor: Optional[str] = None
    weekly_gross: Optional[float] = None
    screen_count: Optional[int] = None
    weeks_in_release: Optional[int] = None
    movie_id: Optional[int] = None
    total_gross: Optional[float] = None
import unittest
from datetime import date

from app.repositories.weekly_box_office_repository import WeeklyBoxOfficeRepository, _title_key


def _rec(title, rank, week_start=date(2026, 9, 17)):
    return {"source_name": "comingsoon", "territory": "IT", "week_start": week_start,
            "external_movie_title": title, "rank": rank}


class TitleKeyTests(unittest.TestCase):
    def test_matches_postgres_lower_btrim(self) -> None:
        # deve restare equivalente a lower(btrim(...)) usato dalla colonna generata title_key
        self.assertEqual("cars: motori ruggenti", _title_key("  Cars: Motori Ruggenti  "))
        self.assertEqual("cars: motori ruggenti", _title_key("cars: motori ruggenti"))

    def test_internal_spacing_is_preserved_not_collapsed(self) -> None:
        # solo trim, non compattazione degli spazi interni: deve seguire esattamente btrim()
        self.assertNotEqual(_title_key("Cars:  Motori Ruggenti"), _title_key("Cars: Motori Ruggenti"))

    def test_none_is_treated_as_empty(self) -> None:
        self.assertEqual("", _title_key(None))


class DedupeByWeekAndTitleTests(unittest.TestCase):
    def test_same_title_different_casing_and_edge_spacing_is_deduplicated(self) -> None:
        # solo maiuscole e spazi ai bordi: la spaziatura interna resta invariata in entrambi
        records = [_rec("Cars: Motori Ruggenti", rank=2), _rec("  cars: motori ruggenti  ", rank=1)]

        result = WeeklyBoxOfficeRepository._dedupe_by_week_and_title(records)

        self.assertEqual(1, len(result))
        self.assertEqual(1, result[0]["rank"])  # tiene il rank migliore (più basso)

    def test_different_titles_are_not_merged(self) -> None:
        records = [_rec("Blue", rank=1), _rec("Blue Film", rank=2)]

        result = WeeklyBoxOfficeRepository._dedupe_by_week_and_title(records)

        self.assertEqual(2, len(result))

    def test_same_title_in_different_weeks_is_not_merged(self) -> None:
        records = [_rec("Odissea", rank=1, week_start=date(2026, 9, 10)), _rec("Odissea", rank=1, week_start=date(2026, 9, 17))]

        result = WeeklyBoxOfficeRepository._dedupe_by_week_and_title(records)

        self.assertEqual(2, len(result))


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from app.validation import validate_weekly_records


def _week(grosses, totals=None, start=date(2026, 9, 17), end=date(2026, 9, 20)):
    totals = totals or [g * 2 for g in grosses]
    return [
        {
            "week_start": start,
            "week_end": end,
            "rank": i,
            "external_movie_title": f"Film {i}",
            "weekly_gross": g,
            "total_gross": t,
        }
        for i, (g, t) in enumerate(zip(grosses, totals), start=1)
    ]


class ValidateWeeklyRecordsTests(unittest.TestCase):
    def test_clean_week_has_no_warnings(self) -> None:
        self.assertEqual([], validate_weekly_records(_week([1000 - i for i in range(10)])))

    def test_flags_rank_not_ordered_by_gross(self) -> None:
        grosses = [1000, 900, 800, 50, 700, 600, 500, 400, 300, 200]  # come Coyote vs. Acme: "504.61"
        warnings = validate_weekly_records(_week(grosses))

        self.assertEqual(1, len(warnings))
        self.assertIn("rank 5", warnings[0])

    def test_flags_total_lower_than_weekly(self) -> None:
        grosses = [1000 - i for i in range(10)]
        totals = [g * 2 for g in grosses]
        totals[2] = 10
        warnings = validate_weekly_records(_week(grosses, totals))

        self.assertTrue(any("total_gross" in w and "rank 3" in w for w in warnings))

    def test_flags_unexpected_row_count_and_duplicate_ranks(self) -> None:
        rows = _week([100, 90, 80])
        rows[1]["rank"] = 1
        warnings = validate_weekly_records(rows)

        self.assertTrue(any("3 righe" in w for w in warnings))
        self.assertTrue(any("rank duplicati" in w for w in warnings))

    def test_weeks_are_checked_independently(self) -> None:
        rows = _week([1000 - i for i in range(10)]) + _week(
            [500 - i for i in range(10)], start=date(2026, 9, 10), end=date(2026, 9, 13)
        )
        self.assertEqual([], validate_weekly_records(rows))


if __name__ == "__main__":
    unittest.main()

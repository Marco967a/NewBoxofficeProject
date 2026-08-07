import unittest
from datetime import date

from scripts.backfill_historical_weekly import build_backfill_dates


class BackfillHistoricalWeeklyTests(unittest.TestCase):
    def test_build_backfill_dates_returns_weekly_sequence(self) -> None:
        dates = build_backfill_dates(date(2024, 2, 15), weeks=3)

        self.assertEqual(
            [date(2024, 2, 15), date(2024, 2, 8), date(2024, 2, 1)],
            dates,
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from unittest.mock import patch

from scripts.backfill_historical_weekly import main


class BackfillHistoricalWeeklyTests(unittest.TestCase):
    @patch("scripts.backfill_historical_weekly.WeeklyBoxOfficeService")
    def test_main_delegates_historical_loading_to_service(self, service_mock) -> None:
        service_mock.return_value.load_historical_weekly_records.return_value = 3

        with patch(
            "scripts.backfill_historical_weekly.sys.argv",
            [
                "backfill_historical_weekly.py",
                "--start-date",
                "2024-02-15",
                "--weeks",
                "3",
            ],
        ):
            main()

        service_mock.return_value.load_historical_weekly_records.assert_called_once_with(
            start_date=date(2024, 2, 15),
            weeks=3,
            source_name="comingsoon",
        )


if __name__ == "__main__":
    unittest.main()

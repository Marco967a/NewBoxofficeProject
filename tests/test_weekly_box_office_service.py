import unittest
from datetime import date
from unittest.mock import Mock, patch

from app.services.weekly_box_office_service import WeeklyBoxOfficeService


class WeeklyBoxOfficeServiceTests(unittest.TestCase):
    @patch("app.services.weekly_box_office_service.parse_comingsoon_weekly_boxoffice_for_date")
    @patch("app.services.weekly_box_office_service.WeeklyBoxOfficeService.load_weekly_records")
    def test_load_historical_weekly_records_uses_multiple_dates(self, load_weekly_records_mock, parser_mock) -> None:
        parser_mock.side_effect = [
            [Mock(week_start=date(2024, 2, 15))],
            [Mock(week_start=date(2024, 2, 8))],
        ]
        load_weekly_records_mock.return_value = 2

        service = WeeklyBoxOfficeService()
        result = service.load_historical_weekly_records(date(2024, 2, 15), weeks=2)

        self.assertEqual(2, result)
        self.assertEqual(2, parser_mock.call_count)
        load_weekly_records_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

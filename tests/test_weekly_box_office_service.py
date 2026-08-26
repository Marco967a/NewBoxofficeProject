import unittest
from datetime import date
from unittest.mock import MagicMock, Mock, patch

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

        loaded_records = load_weekly_records_mock.call_args[0][0]
        self.assertEqual(2, len(loaded_records))

    @patch("app.services.weekly_box_office_service.get_connection")
    @patch("app.services.weekly_box_office_service.WeeklyBoxOfficeRepository")
    @patch("app.services.weekly_box_office_service.MovieRepository")
    @patch("app.services.weekly_box_office_service.IngestionRunRepository")
    def test_load_weekly_records_preserves_weekly_gross_and_weeks_in_release(
        self,
        ingestion_repo_mock,
        movie_repo_mock,
        weekly_repo_mock,
        get_connection_mock,
    ) -> None:
        mock_conn = Mock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_conn
        mock_ctx.__exit__.return_value = None
        get_connection_mock.return_value = mock_ctx

        mock_run_repo = Mock()
        mock_run_repo.start_run.return_value = 101
        ingestion_repo_mock.return_value = mock_run_repo

        mock_movie_repo = Mock()
        movie_repo_mock.return_value = mock_movie_repo

        mock_weekly_repo = Mock()
        mock_weekly_repo.upsert_records.return_value = 1
        weekly_repo_mock.return_value = mock_weekly_repo

        service = WeeklyBoxOfficeService()
        record = Mock(
            source_name="comingsoon",
            territory="IT",
            week_start=date(2024, 2, 2),
            week_end=date(2024, 2, 8),
            rank=1,
            external_movie_title="Film Test",
            distributor="Warner Bros. Inc.",
            weekly_gross=1234567.0,
            total_gross=2345678.0,
            screen_count=600,
            weeks_in_release=4,
        )

        written = service.load_weekly_records([record], source_name="comingsoon")

        self.assertEqual(1, written)
        mock_weekly_repo.upsert_records.assert_called_once()
        passed_records = mock_weekly_repo.upsert_records.call_args[0][1]
        self.assertEqual(1, len(passed_records))
        self.assertEqual(1234567.0, passed_records[0].weekly_gross)
        self.assertEqual(2345678.0, passed_records[0].total_gross)
        self.assertEqual(4, passed_records[0].weeks_in_release)


if __name__ == "__main__":
    unittest.main()

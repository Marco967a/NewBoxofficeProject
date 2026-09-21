import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, Mock, patch

from app.services.weekly_box_office_service import WeeklyBoxOfficeService


class WeeklyBoxOfficeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Il controllo dello schema richiede un DB vero: qui non serve.
        patcher = patch("app.services.weekly_box_office_service.ensure_schema_current")
        patcher.start()
        self.addCleanup(patcher.stop)

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
    @patch("app.services.weekly_box_office_service.IngestionRunRepository")
    def test_load_weekly_records_preserves_weekly_gross_and_weeks_in_release(
        self,
        ingestion_repo_mock,
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
        self.assertEqual(1234567.0, passed_records[0]["weekly_gross"])
        self.assertEqual(2345678.0, passed_records[0]["total_gross"])
        self.assertEqual(4, passed_records[0]["weeks_in_release"])

    def test_load_weekly_records_accepts_dict_records(self):
        service = WeeklyBoxOfficeService()

        class DummyRunRepository:
            def start_run(self, conn, pipeline_name, source_name):
                return 42

            def finish_run(self, conn, run_id, status, records_read, records_written, error_message=None):
                pass

        class DummyWeeklyRepository:
            def __init__(self):
                self.last_rows = None

            def upsert_records(self, conn, records, ingestion_run_id=None):
                self.last_rows = records
                return len(records)

        service.run_repository = DummyRunRepository()
        service.weekly_repository = DummyWeeklyRepository()

        @contextmanager
        def fake_get_connection():
            yield Mock()

        import app.services.weekly_box_office_service as weekly_service_module

        original = weekly_service_module.get_connection
        weekly_service_module.get_connection = fake_get_connection
        try:
            written = service.load_weekly_records(
                [
                    {
                        "source_name": "comingsoon",
                        "territory": "IT",
                        "week_start": "2024-01-01",
                        "week_end": "2024-01-07",
                        "rank": 1,
                        "external_movie_title": "Film A",
                        "distributor": "Distributor",
                        "weekly_gross": 123.45,
                        "screen_count": 200,
                        "weeks_in_release": 4,
                    }
                ],
                source_name="comingsoon",
            )
            self.assertEqual(written, 1)
            self.assertEqual(service.weekly_repository.last_rows[0]["movie_id"], None)
        finally:
            weekly_service_module.get_connection = original

    @patch("app.services.weekly_box_office_service.parse_comingsoon_weekly_boxoffice_for_date")
    @patch("app.services.weekly_box_office_service.WeeklyBoxOfficeService.load_weekly_records")
    def test_historical_skips_unrecoverable_weeks_and_dedupes_same_week(self, load_mock, parser_mock) -> None:
        same_week = [Mock(week_start=date(2026, 9, 17), week_end=date(2026, 9, 20))]
        parser_mock.side_effect = [same_week, same_week, RuntimeError("no archivio")]
        load_mock.return_value = 1

        result = WeeklyBoxOfficeService().load_historical_weekly_records(date(2026, 9, 18), weeks=3)

        self.assertEqual(1, result)
        loaded_records = load_mock.call_args[0][0]
        self.assertEqual(1, len(loaded_records))

    @patch("app.services.weekly_box_office_service.parse_comingsoon_weekly_boxoffice_for_date")
    def test_historical_returns_zero_when_no_week_is_recoverable(self, parser_mock) -> None:
        parser_mock.side_effect = RuntimeError("no archivio")

        result = WeeklyBoxOfficeService().load_historical_weekly_records(date(2026, 5, 4), weeks=2)

        self.assertEqual(0, result)

    def _service_with_connection(self, weekly_repo):
        run_repo = Mock()
        run_repo.start_run.return_value = 7
        service = WeeklyBoxOfficeService()
        service.run_repository = run_repo
        service.weekly_repository = weekly_repo
        conn = Mock()

        @contextmanager
        def fake_get_connection():
            yield conn

        return service, run_repo, conn, fake_get_connection

    def test_failed_load_records_failed_run_and_commits_it(self) -> None:
        weekly_repo = Mock()
        weekly_repo.upsert_records.side_effect = RuntimeError("boom")
        service, run_repo, conn, fake_get_connection = self._service_with_connection(weekly_repo)

        with patch("app.services.weekly_box_office_service.get_connection", fake_get_connection):
            with self.assertRaises(RuntimeError):
                service.load_weekly_records([{"rank": 1}], source_name="comingsoon")

        finish_kwargs = run_repo.finish_run.call_args.kwargs
        self.assertEqual("failed", finish_kwargs["status"])
        self.assertEqual("boom", finish_kwargs["error_message"])
        # start_run committato prima dei dati, poi rollback dei dati e commit del solo "failed"
        self.assertEqual(["commit", "rollback", "commit"], [c[0] for c in conn.method_calls])

    def test_source_name_argument_wins_over_record_source_name(self) -> None:
        weekly_repo = Mock()
        weekly_repo.upsert_records.return_value = 1
        service, _, _, fake_get_connection = self._service_with_connection(weekly_repo)

        with patch("app.services.weekly_box_office_service.get_connection", fake_get_connection):
            service.load_weekly_records(
                [{"source_name": "comingsoon", "rank": 1}], source_name="comingsoon_test"
            )

        rows = weekly_repo.upsert_records.call_args[0][1]
        self.assertEqual("comingsoon_test", rows[0]["source_name"])


if __name__ == "__main__":
    unittest.main()

import unittest
from contextlib import contextmanager

from app.services.weekly_box_office_service import WeeklyBoxOfficeService


class DummyRunRepository:
    def create_table(self, conn):
        pass

    def start_run(self, conn, pipeline_name, source_name):
        return 42

    def finish_run(self, conn, run_id, status, records_read, records_written, error_message=None):
        pass


class DummyMovieRepository:
    def create_table(self, conn):
        pass


class DummyWeeklyRepository:
    def __init__(self):
        self.last_rows = None

    def create_table(self, conn):
        pass

    def upsert_records(self, conn, records, ingestion_run_id=None):
        self.last_rows = records
        return len(records)


class WeeklyBoxOfficeServiceTests(unittest.TestCase):
    def test_load_weekly_records_accepts_dict_records(self):
        service = WeeklyBoxOfficeService()
        service.run_repository = DummyRunRepository()
        service.movie_repository = DummyMovieRepository()
        service.weekly_repository = DummyWeeklyRepository()

        @contextmanager
        def fake_get_connection():
            yield object()

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


if __name__ == "__main__":
    unittest.main()

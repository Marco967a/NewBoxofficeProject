import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import psycopg2

from app.services.movie_matching_service import MovieMatchingService


def _pending(n):
    return [{"id": i, "title": f"Film {i}", "first_week_start": None, "first_weeks_in_release": None}
            for i in range(1, n + 1)]


class FakeConn:
    def __init__(self):
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


@contextmanager
def _cm(conn):
    yield conn


@contextmanager
def _cm_failing_on_exit(conn, exc):
    """Come app.db.get_connection: fallisce nel commit finale, dopo che il corpo del with è già uscito."""
    yield conn
    raise exc


class ResolvePendingConnectionLossTests(unittest.TestCase):
    def _service(self):
        service = MovieMatchingService(tmdb_client=MagicMock())
        service.source_movie_repository = MagicMock()
        service.movie_repository = MagicMock()
        return service

    def test_broken_connection_stops_the_loop_instead_of_retrying_every_remaining_item(self) -> None:
        service = self._service()
        service.source_movie_repository.list_for_matching.return_value = _pending(3)
        conn = FakeConn()

        with patch("app.services.movie_matching_service.get_connection", return_value=_cm(conn)), \
                patch("app.services.movie_matching_service.ensure_schema_current"), \
                patch.object(service, "evaluate", side_effect=[
                    ([], MagicMock(status="no_match", best=None, reason="")),
                    psycopg2.OperationalError("connessione persa"),
                    AssertionError("non deve essere raggiunto: il terzo film non va tentato"),
                ]):
            summary = service.resolve_pending()

        self.assertTrue(summary.stopped_early)
        self.assertEqual(1, summary.errors)
        self.assertEqual(1, summary.no_match)
        self.assertEqual(2, summary.total)  # il terzo film non è mai stato tentato
        self.assertTrue(any("connessione al database persa" in ln for ln in summary.lines))

    def test_ordinary_per_film_errors_do_not_stop_the_loop(self) -> None:
        service = self._service()
        service.source_movie_repository.list_for_matching.return_value = _pending(2)
        conn = FakeConn()

        with patch("app.services.movie_matching_service.get_connection", return_value=_cm(conn)), \
                patch("app.services.movie_matching_service.ensure_schema_current"), \
                patch.object(service, "evaluate", side_effect=[
                    RuntimeError("TMDB non ha risposto"),
                    ([], MagicMock(status="no_match", best=None, reason="")),
                ]):
            summary = service.resolve_pending()

        self.assertFalse(summary.stopped_early)
        self.assertEqual(1, summary.errors)
        self.assertEqual(1, summary.no_match)
        self.assertEqual(2, summary.total)  # entrambi i film sono stati tentati

    def test_connection_lost_only_on_final_commit_still_returns_the_partial_summary(self) -> None:
        """Se la connessione muore solo alla chiusura del `with` (dopo l'ultimo item), il riepilogo
        parziale va comunque restituito, non perso in un'eccezione non gestita."""
        service = self._service()
        service.source_movie_repository.list_for_matching.return_value = _pending(1)
        conn = FakeConn()
        cm = _cm_failing_on_exit(conn, psycopg2.OperationalError("commit fallito in chiusura"))

        with patch("app.services.movie_matching_service.get_connection", return_value=cm), \
                patch("app.services.movie_matching_service.ensure_schema_current"), \
                patch.object(service, "evaluate", return_value=([], MagicMock(status="no_match", best=None, reason=""))):
            summary = service.resolve_pending()  # non deve sollevare

        self.assertEqual(1, summary.no_match)
        self.assertFalse(summary.stopped_early)  # il guasto è arrivato dopo, non durante l'iterazione
        self.assertEqual(0, summary.errors)  # l'item era già andato a buon fine: non lo si conta come errore
        self.assertTrue(any("connessione al database persa alla chiusura" in ln for ln in summary.lines))


if __name__ == "__main__":
    unittest.main()

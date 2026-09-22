"""Test di integrazione su un Postgres reale.

Disattivati di default. Con RUN_DB_TESTS=1 usano le credenziali di .env per creare un database
temporaneo (boxoffice_test_<random>), applicarvi le migrazioni e distruggerlo alla fine:
non toccano mai il database configurato in DB_NAME.
"""
import os
import unittest
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

RUN = os.getenv("RUN_DB_TESTS") == "1"

if RUN:
    import psycopg2

    from app.credentials import get_secret
    from app.migrations import apply_pending, ensure_schema_current, pending_migrations
    from app.parsers.comingsoon_parser import FetchResult
    from app.repositories.weekly_box_office_repository import WeeklyBoxOfficeRepository
    from app.services.weekly_box_office_service import WeeklyBoxOfficeService
    from app.settings import get_settings


def _test_db_config() -> dict:
    """Connessione per creare/distruggere i database temporanei.

    In locale il ruolo dedicato ai test (TEST_DB_USER, predefinito 'boxoffice_test': può creare database ma non è
    superutente), con la password nel deposito credenziali; in CI, dove non c'è, le impostazioni normali.
    """
    base = get_settings(require_tmdb=False).db_config
    user = os.getenv("TEST_DB_USER", "boxoffice_test")
    password = get_secret(f"db:{user}", "TEST_DB_PASSWORD")
    return {**base, "user": user, "password": password} if password else base


def _record(title, rank, sid=None, gross=1000.0, week_start=date(2026, 9, 17), **extra):
    return {
        "source_name": "comingsoon",
        "territory": "IT",
        "week_start": week_start,
        "week_end": week_start + timedelta(days=3),
        "rank": rank,
        "external_movie_title": title,
        "distributor": "Dist",
        "weekly_gross": gross,
        "total_gross": gross * 2,
        "screen_count": 100,
        "weeks_in_release": 1,
        "movie_id": None,
        "source_movie_id": sid,
        "source_url": f"https://example.test/film/{sid}" if sid else None,
        **extra,
    }


class _DatabaseTestCase(unittest.TestCase):
    """Base: crea un DB temporaneo migrato per classe e lo svuota a ogni test."""

    @classmethod
    def setUpClass(cls):
        base = _test_db_config()
        cls.dbname = f"boxoffice_test_{uuid.uuid4().hex[:8]}"
        admin = psycopg2.connect(**{**base, "dbname": "postgres"})
        admin.autocommit = True
        admin.cursor().execute(f"CREATE DATABASE {cls.dbname}")
        admin.close()
        cls.config = {**base, "dbname": cls.dbname}

        conn = psycopg2.connect(**cls.config)
        try:
            apply_pending(conn)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        admin = psycopg2.connect(**{**_test_db_config(), "dbname": "postgres"})
        admin.autocommit = True
        admin.cursor().execute(f"DROP DATABASE IF EXISTS {cls.dbname} WITH (FORCE)")
        admin.close()

    def setUp(self):
        self.conn = psycopg2.connect(**self.config)
        self.addCleanup(self.conn.close)
        with self.conn.cursor() as cur:
            cur.execute(
                "TRUNCATE raw_snapshots, weekly_box_office, source_movies, movies, ingestion_runs RESTART IDENTITY CASCADE"
            )
        self.conn.commit()
        self.repo = WeeklyBoxOfficeRepository()

    def q(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None

    def _service_db(self):
        settings = SimpleNamespace(db_config=self.config)
        return patch("app.db.get_settings", return_value=settings)


@unittest.skipUnless(RUN, "imposta RUN_DB_TESTS=1 per eseguire i test su Postgres")
class DatabaseIntegrationTests(_DatabaseTestCase):
    # --- migrazioni -------------------------------------------------------------------------

    def test_migrations_are_all_applied_and_schema_is_current(self):
        self.assertEqual([], pending_migrations(self.conn))
        ensure_schema_current(self.conn)
        self.assertEqual([], apply_pending(self.conn))  # idempotente

    def test_tampered_migration_checksum_is_detected(self):
        self.q("UPDATE schema_migrations SET checksum = 'x' WHERE version = '001'")
        self.conn.commit()
        try:
            with self.assertRaises(RuntimeError):
                pending_migrations(self.conn)
        finally:
            self.conn.rollback()
            from app.migrations import load_migrations
            first = load_migrations()[0]
            self.q("UPDATE schema_migrations SET checksum = %s WHERE version = '001'", (first.checksum,))
            self.conn.commit()

    # --- upsert settimanale -----------------------------------------------------------------

    def test_upsert_links_source_movies_and_is_idempotent(self):
        rows = [_record("Film A", 1, "10"), _record("Film B", 2, "20")]
        self.assertEqual(2, self.repo.upsert_records(self.conn, rows))
        self.assertEqual(2, self.repo.upsert_records(self.conn, rows))
        self.conn.commit()

        self.assertEqual([(2,)], self.q("SELECT count(*) FROM weekly_box_office"))
        self.assertEqual([(2,)], self.q("SELECT count(*) FROM source_movies"))
        self.assertEqual([(2,)], self.q("SELECT count(source_movie_ref) FROM weekly_box_office"))

    def test_reranking_updates_same_rows_without_duplicates_or_collisions(self):
        self.repo.upsert_records(self.conn, [_record("Film A", 1, "10", 900), _record("Film B", 2, "20", 800)])
        # rank scambiati nello stesso batch: con la vecchia chiave (rank) sovrascriveva il film sbagliato
        self.repo.upsert_records(self.conn, [_record("Film A", 2, "10", 700), _record("Film B", 1, "20", 950)])
        self.conn.commit()

        self.assertEqual(
            [("Film B", 1), ("Film A", 2)],
            self.q("SELECT external_movie_title, rank FROM weekly_box_office ORDER BY rank"),
        )

    def test_movie_id_is_preserved_and_resolved_from_source_movies(self):
        self.q("INSERT INTO movies (id, title) VALUES (555, 'Film A (TMDB)')")
        self.repo.upsert_records(self.conn, [_record("Film A", 1, "10")])
        self.q(
            "UPDATE source_movies SET movie_id = 555, match_status = 'manual' WHERE source_movie_id = '10'"
        )
        self.q("UPDATE weekly_box_office SET movie_id = 555 WHERE external_movie_title = 'Film A'")

        # un nuovo caricamento (movie_id sconosciuto) non deve azzerarlo
        self.repo.upsert_records(self.conn, [_record("Film A", 1, "10", 1200)])
        self.assertEqual([(555,)], self.q("SELECT movie_id FROM weekly_box_office"))

        # una settimana nuova dello stesso film eredita il match dal film sorgente
        self.repo.upsert_records(self.conn, [_record("Film A", 3, "10", week_start=date(2026, 9, 24))])
        self.conn.commit()
        self.assertEqual(
            [(555,), (555,)], self.q("SELECT movie_id FROM weekly_box_office ORDER BY week_start")
        )

    def test_duplicate_title_in_same_week_keeps_best_rank(self):
        written = self.repo.upsert_records(
            self.conn, [_record("Stesso Titolo", 5, "1", 100), _record("Stesso Titolo", 3, "2", 300)]
        )
        self.conn.commit()

        self.assertEqual(1, written)
        self.assertEqual([(3,)], self.q("SELECT rank FROM weekly_box_office"))

    def test_casing_or_edge_whitespace_change_updates_the_same_row_instead_of_duplicating_it(self):
        self.repo.upsert_records(self.conn, [_record("Cars: Motori Ruggenti", 1, "401", 900)])
        # stessa settimana, stesso film, ma la sorgente ha cambiato maiuscole/spazi ai bordi
        # (title_key normalizza solo con lower(btrim(...)): la spaziatura interna resta invariata)
        written = self.repo.upsert_records(self.conn, [_record("  cars: motori ruggenti  ", 1, "401", 800)])
        self.conn.commit()

        self.assertEqual(1, written)
        self.assertEqual(
            [("  cars: motori ruggenti  ", 800.0)],
            self.q("SELECT external_movie_title, weekly_gross FROM weekly_box_office"),
        )

    def test_two_different_titles_in_the_same_batch_with_different_casing_do_not_collide(self):
        # "Blue" e "BLUE FILM" normalizzano a chiavi diverse: devono restare due righe distinte
        written = self.repo.upsert_records(
            self.conn, [_record("Blue", 5, "1", 100), _record("BLUE FILM", 6, "2", 90)]
        )
        self.conn.commit()

        self.assertEqual(2, written)
        self.assertEqual(
            {"Blue", "BLUE FILM"},
            {row[0] for row in self.q("SELECT external_movie_title FROM weekly_box_office")},
        )

    def test_legacy_rows_without_source_id_still_upsert(self):
        self.repo.upsert_records(self.conn, [_record("Vecchio", 1, None, 500)])
        self.repo.upsert_records(self.conn, [_record("Vecchio", 1, "77", 600)])  # ora arriva l'ID
        self.conn.commit()

        self.assertEqual([(1,)], self.q("SELECT count(*) FROM weekly_box_office"))
        self.assertEqual([(1,)], self.q("SELECT count(source_movie_ref) FROM weekly_box_office"))

    # --- vincoli ----------------------------------------------------------------------------

    def test_constraints_reject_bad_rows(self):
        bad_window = _record("X", 1)
        bad_window["week_end"] = date(2026, 9, 1)
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.repo.upsert_records(self.conn, [bad_window])
        self.conn.rollback()

        with self.assertRaises(psycopg2.errors.ForeignKeyViolation):
            self.repo.upsert_records(self.conn, [_record("Y", 1, movie_id=999999)])
        self.conn.rollback()

        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.q("INSERT INTO source_movies (source_name, source_movie_id, title, match_status) "
                   "VALUES ('s', '1', 't', 'auto')")  # 'auto' richiede un movie_id
        self.conn.rollback()

    # --- servizio end-to-end ----------------------------------------------------------------

    def _service(self):
        settings = SimpleNamespace(db_config=self.config)
        return patch("app.db.get_settings", return_value=settings)

    def test_service_success_persists_run_snapshot_and_rows(self):
        snapshot = FetchResult(url="https://example.test/box", html="<html>raw</html>", records=[])
        with self._service():
            written = WeeklyBoxOfficeService().load_weekly_records(
                [_record("Film A", 1, "10"), _record("Film B", 2, "20")],
                source_name="comingsoon",
                snapshots=[snapshot],
            )
        self.assertEqual(2, written)
        self.assertEqual([("success", 2)], self.q("SELECT status, records_written FROM ingestion_runs"))
        self.assertEqual([("<html>raw</html>",)], self.q("SELECT payload FROM raw_snapshots"))
        self.assertEqual([(True,)], self.q("SELECT finished_at > started_at FROM ingestion_runs"))

    def test_service_failure_keeps_failed_run_and_snapshot_but_no_rows(self):
        snapshot = FetchResult(url="https://example.test/box", html="<html>raw</html>", records=[])
        bad = _record("Film A", 1, "10")
        bad["rank"] = 0  # viola CHECK (rank > 0)
        with self._service():
            with self.assertRaises(psycopg2.errors.CheckViolation):
                WeeklyBoxOfficeService().load_weekly_records([bad], source_name="comingsoon", snapshots=[snapshot])
        self.conn.rollback()

        self.assertEqual([("failed",)], self.q("SELECT status FROM ingestion_runs"))
        self.assertEqual([(1,)], self.q("SELECT count(*) FROM raw_snapshots"))
        self.assertEqual([(0,)], self.q("SELECT count(*) FROM weekly_box_office"))


class FakeTMDB:
    """TMDB finto: risposte fisse per ricerca, titoli alternativi e dettagli."""

    def __init__(self, search=None, alternatives=None, details=None, failing_queries=(), release_dates=None):
        self.search = search or {}
        self.release_dates = release_dates or {}
        self.alternatives = alternatives or {}
        self.details = details or {}
        self.failing_queries = set(failing_queries)
        self.detail_calls = []

    def search_movies(self, query, language="it-IT", year=None):
        if query in self.failing_queries:
            raise RuntimeError("TMDB down")
        return self.search.get(query, [])

    def get_alternative_titles(self, movie_id, country="IT"):
        return self.alternatives.get(movie_id, [])

    def get_release_dates(self, movie_id, country="IT"):
        return self.release_dates.get(movie_id, [])

    def get_movie_details(self, movie_id):
        self.detail_calls.append(movie_id)
        return self.details[movie_id]


def _tmdb_result(tmdb_id, title, release="2026-07-15", original=None, popularity=200.0):
    return {"id": tmdb_id, "title": title, "original_title": original or title,
            "release_date": release, "popularity": popularity}


def _details(tmdb_id, title, original=None):
    return {"id": tmdb_id, "title": title, "original_title": original or title,
            "release_date": "2026-07-15", "genres": [{"name": "Avventura"}], "revenue": 0, "budget": 0}


@unittest.skipUnless(RUN, "imposta RUN_DB_TESTS=1 per eseguire i test su Postgres")
class MatchingIntegrationTests(_DatabaseTestCase):
    def setUp(self):
        super().setUp()
        from app.services.movie_matching_service import MovieMatchingService
        self.Service = MovieMatchingService
        self.repo = WeeklyBoxOfficeRepository()

    def seed(self, title, sid, weeks_in_release=10, week_start=date(2026, 9, 17)):
        self.repo.upsert_records(
            self.conn, [_record(title, 1, sid, week_start=week_start, weeks_in_release=weeks_in_release)]
        )
        self.conn.commit()

    def resolve(self, tmdb, **kwargs):
        with self._service_db():
            return self.Service(tmdb_client=tmdb).resolve_pending(**kwargs)

    def ref_id(self, sid):
        return self.q("SELECT id FROM source_movies WHERE source_movie_id = %s", (sid,))[0][0]

    def test_clear_match_is_automatic_and_propagates_movie_id(self):
        self.seed("Odissea", "66812")
        tmdb = FakeTMDB(
            search={"Odissea": [_tmdb_result(100, "Odissea", original="The Odyssey")]},
            details={100: _details(100, "The Odyssey")},
        )

        summary = self.resolve(tmdb)

        self.assertEqual((1, 0, 0, 0), (summary.auto, summary.needs_review, summary.no_match, summary.errors))
        self.assertEqual([(100, "The Odyssey")], self.q("SELECT id, original_title FROM movies"))
        self.assertEqual(
            [(100, "auto", "tmdb_search")],
            self.q("SELECT movie_id, match_status, match_method FROM source_movies"),
        )
        self.assertEqual([(100,)], self.q("SELECT movie_id FROM weekly_box_office"))

    def test_only_matched_films_are_downloaded_into_movies(self):
        self.seed("Odissea", "1")
        self.seed("Titolo Ignoto", "2")
        tmdb = FakeTMDB(
            search={"Odissea": [_tmdb_result(100, "Odissea")]},
            details={100: _details(100, "Odissea")},
        )

        self.resolve(tmdb)

        self.assertEqual([100], tmdb.detail_calls)
        self.assertEqual([(1,)], self.q("SELECT count(*) FROM movies"))

    def test_ambiguous_match_goes_to_review_with_candidates_and_writes_no_movie_id(self):
        self.seed("Michael", "5", weeks_in_release=1)
        tmdb = FakeTMDB(search={"Michael": [
            _tmdb_result(1, "Michael", release="2026-09-16", popularity=90),
            _tmdb_result(2, "Michael", release="2026-09-16", popularity=80),
        ]})

        summary = self.resolve(tmdb)

        self.assertEqual(1, summary.needs_review)
        self.assertEqual([("needs_review", None)], self.q("SELECT match_status, movie_id FROM source_movies"))
        self.assertEqual([(2,)], self.q("SELECT count(*) FROM match_candidates"))
        self.assertEqual([(None,)], self.q("SELECT movie_id FROM weekly_box_office"))
        self.assertEqual([(0,)], self.q("SELECT count(*) FROM movies"))
        with self._service_db():
            queue = self.Service(tmdb_client=tmdb).review_queue()
        self.assertEqual(1, len(queue))
        self.assertEqual({1, 2}, {c["tmdb_id"] for c in queue[0]["candidates"]})

    def test_no_candidates_is_no_match(self):
        self.seed("Film Locale", "9")

        summary = self.resolve(FakeTMDB())

        self.assertEqual(1, summary.no_match)
        self.assertEqual([("no_match",)], self.q("SELECT match_status FROM source_movies"))

    def test_italian_alternative_title_turns_review_into_auto(self):
        self.seed("Odissea", "66812")
        tmdb = FakeTMDB(
            search={"Odissea": [_tmdb_result(100, "The Odyssey")]},
            alternatives={100: ["Odissea"]},
            details={100: _details(100, "The Odyssey")},
        )

        self.assertEqual(1, self.resolve(tmdb).auto)

    def test_italian_release_date_picks_the_right_homonym(self):
        self.seed("Election Day", "5", weeks_in_release=11, week_start=date(2026, 9, 17))  # uscita stimata 2026-07-09
        tmdb = FakeTMDB(
            search={"Election Day": [
                _tmdb_result(1, "Election Day", release="2026-07-09", popularity=50),
                _tmdb_result(2, "Election Day", release="2026-07-09", popularity=40),
            ]},
            release_dates={1: [date(2024, 11, 1)], 2: [date(2026, 7, 9)]},
            details={2: _details(2, "Election Day")},
        )

        summary = self.resolve(tmdb)

        self.assertEqual(1, summary.auto)
        self.assertEqual([(2,)], self.q("SELECT movie_id FROM source_movies"))

    def test_tmdb_error_on_one_film_does_not_stop_the_others(self):
        self.seed("Odissea", "1")
        self.seed("Rotto", "2")
        tmdb = FakeTMDB(
            search={"Odissea": [_tmdb_result(100, "Odissea")]},
            details={100: _details(100, "Odissea")},
            failing_queries={"Rotto"},
        )

        summary = self.resolve(tmdb)

        self.assertEqual((1, 1), (summary.auto, summary.errors))
        self.assertEqual([("Odissea", "auto"), ("Rotto", "unmatched")],
                         self.q("SELECT title, match_status FROM source_movies ORDER BY title"))

    def test_manual_match_overrides_and_is_never_touched_by_the_resolver(self):
        self.seed("Odissea", "1")
        tmdb = FakeTMDB(
            search={"Odissea": [_tmdb_result(100, "Odissea")]},
            details={100: _details(100, "Odissea"), 200: _details(200, "Altro Film")},
        )
        self.resolve(tmdb)
        ref = self.ref_id("1")

        with self._service_db():
            self.Service(tmdb_client=tmdb).set_manual_match(ref, 200)
        self.assertEqual([(200, "manual")], self.q("SELECT movie_id, match_status FROM source_movies"))
        self.assertEqual([(200,)], self.q("SELECT movie_id FROM weekly_box_office"))

        # anche riprovando tutti gli stati, il match manuale non viene riproposto né cambiato
        summary = self.resolve(tmdb, statuses=("unmatched", "needs_review", "no_match", "auto", "manual"))
        self.assertEqual(0, summary.total)
        self.assertEqual([(200,)], self.q("SELECT movie_id FROM weekly_box_office"))

    def test_manual_no_match_is_not_retried_and_clears_movie_id(self):
        self.seed("Odissea", "1")
        tmdb = FakeTMDB(search={"Odissea": [_tmdb_result(100, "Odissea")]}, details={100: _details(100, "Odissea")})
        self.resolve(tmdb)
        ref = self.ref_id("1")

        with self._service_db():
            self.Service(tmdb_client=tmdb).set_no_match(ref)

        self.assertEqual([(None,)], self.q("SELECT movie_id FROM weekly_box_office"))
        self.assertEqual(0, self.resolve(tmdb, statuses=("unmatched", "needs_review", "no_match")).total)

    def test_dry_run_writes_nothing(self):
        self.seed("Odissea", "1")
        tmdb = FakeTMDB(search={"Odissea": [_tmdb_result(100, "Odissea")]}, details={100: _details(100, "Odissea")})

        summary = self.resolve(tmdb, dry_run=True)

        self.assertEqual(1, summary.auto)
        self.assertEqual([("unmatched",)], self.q("SELECT match_status FROM source_movies"))
        self.assertEqual([(0,)], self.q("SELECT count(*) FROM movies"))

    def test_link_legacy_rows_links_creates_and_adopts_existing_movie_id(self):
        self.q("INSERT INTO movies (id, title) VALUES (555, 'Vecchio Film')")
        legacy_old = _record("Vecchio Film", 1, None, week_start=date(2026, 7, 9), movie_id=555)
        # il vecchio codice valorizzava movie_id solo su una settimana: le altre restavano NULL
        later_week = _record("Vecchio Film", 4, None, week_start=date(2026, 7, 23))
        legacy_odissea = _record("odissea ", 2, None, week_start=date(2026, 7, 23))
        self.repo.upsert_records(self.conn, [legacy_old, later_week, legacy_odissea])
        self.repo.upsert_records(self.conn, [_record("Odissea", 1, "66812")])
        self.conn.commit()

        with self._service_db():
            counts = self.Service(tmdb_client=FakeTMDB()).link_legacy_rows()

        self.assertEqual(1, counts["linked_to_real"])  # "odissea " -> film reale (titolo senza maiuscole/spazi)
        self.assertEqual(1, counts["legacy_created"])  # "Vecchio Film" non ha un ID reale
        self.assertEqual(1, counts["adopted_existing_movie_id"])
        self.assertEqual(1, counts["synced_weekly_movie_id"])  # la settimana successiva eredita 555
        self.assertEqual(
            [(555,), (555,)],
            self.q("SELECT movie_id FROM weekly_box_office WHERE external_movie_title = 'Vecchio Film' ORDER BY week_start"),
        )
        self.assertEqual([(0,)], self.q("SELECT count(*) FROM weekly_box_office WHERE source_movie_ref IS NULL"))
        self.assertEqual(
            [("legacy:vecchio film", 555, "auto", "legacy_exact_title")],
            self.q("SELECT source_movie_id, movie_id, match_status, match_method FROM source_movies "
                   "WHERE source_movie_id LIKE 'legacy:%'"),
        )

        with self._service_db():  # idempotente
            again = self.Service(tmdb_client=FakeTMDB()).link_legacy_rows()
        self.assertEqual(0, sum(again.values()))

    def _legacy_and_real(self, legacy_movie_id=None, real_status="unmatched", real_movie_id=None):
        """Film 'Michael' presente come legacy (settimana vecchia) e, dopo un recupero, con ID reale."""
        for mid in (555, 777):
            self.q("INSERT INTO movies (id, title) VALUES (%s, 'Michael') ON CONFLICT DO NOTHING", (mid,))
        # 1. il film esiste solo come riga storica: viene collegato a un film 'legacy'
        self.repo.upsert_records(self.conn, [_record("Michael", 1, None, week_start=date(2026, 7, 9), movie_id=legacy_movie_id)])
        self.conn.commit()
        with self._service_db():
            self.Service(tmdb_client=FakeTMDB()).link_legacy_rows()
        self.assertEqual([("legacy:michael",)], self.q("SELECT source_movie_id FROM source_movies"))

        # 2. un recupero da archivio porta lo stesso film con il suo ID reale
        self.repo.upsert_records(self.conn, [_record("Michael", 1, "9001", week_start=date(2026, 7, 16))])
        self.q("UPDATE source_movies SET match_status = %s, movie_id = %s WHERE source_movie_id = '9001'",
               (real_status, real_movie_id))
        self.conn.commit()
        with self._service_db():
            return self.Service(tmdb_client=FakeTMDB()).link_legacy_rows()

    def test_legacy_film_is_promoted_into_the_real_one_and_keeps_its_match(self):
        counts = self._legacy_and_real(legacy_movie_id=555)

        self.assertEqual(1, counts["promoted_rows"])
        self.assertEqual(1, counts["legacy_removed"])
        self.assertEqual([("9001", 555, "auto")], self.q("SELECT source_movie_id, movie_id, match_status FROM source_movies"))
        self.assertEqual([(555,), (555,)], self.q("SELECT movie_id FROM weekly_box_office ORDER BY week_start"))
        self.assertEqual([(1,)], self.q("SELECT count(DISTINCT source_movie_ref) FROM weekly_box_office"))

    def test_conflicting_matches_are_not_merged(self):
        counts = self._legacy_and_real(legacy_movie_id=555, real_status="auto", real_movie_id=777)

        self.assertEqual(0, counts["promoted_rows"])
        self.assertEqual([(2,)], self.q("SELECT count(*) FROM source_movies"))  # entrambi restano, da rivedere
        self.assertEqual([(2,)], self.q("SELECT count(DISTINCT movie_id) FROM weekly_box_office"))

    def test_unmatched_legacy_is_promoted_without_match(self):
        counts = self._legacy_and_real()

        self.assertEqual(1, counts["promoted_rows"])
        self.assertEqual([("9001", None, "unmatched")], self.q("SELECT source_movie_id, movie_id, match_status FROM source_movies"))

    def test_new_run_of_a_legacy_film_moves_it_to_the_real_source_id(self):
        self.repo.upsert_records(self.conn, [_record("Film X", 1, None)])
        self.conn.commit()
        with self._service_db():
            self.Service(tmdb_client=FakeTMDB()).link_legacy_rows()

        self.repo.upsert_records(self.conn, [_record("Film X", 1, "321")])  # ora arriva l'ID reale
        self.conn.commit()

        self.assertEqual(
            [("321",)],
            self.q("SELECT s.source_movie_id FROM weekly_box_office w JOIN source_movies s ON s.id = w.source_movie_ref"),
        )


@unittest.skipUnless(RUN, "imposta RUN_DB_TESTS=1 per eseguire i test su Postgres")
class HealthAndViewIntegrationTests(_DatabaseTestCase):
    def setUp(self):
        super().setUp()
        from app import health
        self.health = health

    def add_run(self, days_ago, status="success", error=None):
        self.q(
            "INSERT INTO ingestion_runs (pipeline_name, source_name, started_at, finished_at, status,"
            " records_read, records_written, error_message)"
            " VALUES ('weekly_box_office', 'comingsoon', now() - make_interval(days => %s),"
            " now() - make_interval(days => %s), %s, 20, 20, %s)",
            (days_ago, days_ago, status, error),
        )
        self.conn.commit()

    def seed_week(self, days_ago, n=12, sid_prefix=""):
        week_start = date.today() - timedelta(days=days_ago)
        rows = [
            _record(f"Film {sid_prefix}{i}", i, f"{sid_prefix}{week_start:%m%d}-{i}", gross=10000.0 - i * 100,
                    week_start=week_start)
            for i in range(1, n + 1)
        ]
        self.repo.upsert_records(self.conn, rows)
        self.conn.commit()
        return week_start

    def check(self, fn, *args):
        result = fn(self.conn, *args)
        self.conn.rollback()
        return result

    # --- ultimo run -------------------------------------------------------------------------

    def test_last_run_levels(self):
        self.assertEqual("FAIL", self.check(self.health.check_last_run, "comingsoon", 8).level)  # nessun run

        self.add_run(days_ago=2)
        self.assertEqual("OK", self.check(self.health.check_last_run, "comingsoon", 8).level)

    def test_last_run_too_old_is_fail(self):
        self.add_run(days_ago=20)
        result = self.check(self.health.check_last_run, "comingsoon", 8)
        self.assertEqual("FAIL", result.level)
        self.assertIn("giorni fa", result.message)

    def test_failed_last_run_is_fail_even_if_an_older_run_succeeded(self):
        self.add_run(days_ago=5)
        self.add_run(days_ago=1, status="failed", error="boom")
        result = self.check(self.health.check_last_run, "comingsoon", 8)
        self.assertEqual("FAIL", result.level)
        self.assertIn("boom", result.message)

    # --- ultima settimana e buchi -----------------------------------------------------------

    def test_latest_week_levels(self):
        self.assertEqual("FAIL", self.check(self.health.check_latest_week, "comingsoon", "IT").level)  # vuoto

        self.seed_week(days_ago=4)
        self.assertEqual("OK", self.check(self.health.check_latest_week, "comingsoon", "IT").level)

    def test_latest_week_stale_and_short(self):
        self.seed_week(days_ago=12)
        self.assertEqual("WARN", self.check(self.health.check_latest_week, "comingsoon", "IT").level)
        self.seed_week(days_ago=3, n=4, sid_prefix="x")
        result = self.check(self.health.check_latest_week, "comingsoon", "IT")
        self.assertEqual("WARN", result.level)
        self.assertIn("4 righe", result.message)

    def test_latest_week_very_old_is_fail(self):
        self.seed_week(days_ago=30)
        self.assertEqual("FAIL", self.check(self.health.check_latest_week, "comingsoon", "IT").level)

    def test_gaps_are_reported_but_not_before_the_first_week(self):
        for days_ago in (28, 21, 7, 0):  # manca 14 giorni fa
            self.seed_week(days_ago, n=2, sid_prefix=f"g{days_ago}-")
        result = self.check(self.health.check_gaps, "comingsoon", "IT", 12)
        self.assertEqual("WARN", result.level)
        self.assertIn("1 settimane mancanti", result.message)
        self.assertIn(str(date.today() - timedelta(days=14)), result.message)

    def test_no_gaps_when_weeks_are_consecutive(self):
        for days_ago in (14, 7, 0):
            self.seed_week(days_ago, n=2, sid_prefix=f"g{days_ago}-")
        self.assertEqual("OK", self.check(self.health.check_gaps, "comingsoon", "IT", 12).level)

    # --- integrità e anomalie ---------------------------------------------------------------

    def test_integrity_detects_inconsistent_movie_id_and_pending_queue(self):
        self.seed_week(days_ago=3, n=3)
        self.q("INSERT INTO movies (id, title) VALUES (1, 'X')")
        self.q("UPDATE weekly_box_office SET movie_id = 1 WHERE rank = 1")  # source_movies.movie_id resta NULL
        self.q("UPDATE source_movies SET match_status = 'needs_review' WHERE source_movie_id LIKE '%-2'")
        self.conn.commit()

        by_name = {r.name: r for r in self.health.check_integrity(self.conn, "comingsoon")}
        self.conn.rollback()

        self.assertEqual("FAIL", by_name["coerenza movie_id"].level)
        self.assertEqual("WARN", by_name["coda match"].level)
        self.assertIn("1 da rivedere", by_name["coda match"].message)
        self.assertIn("2 da abbinare", by_name["coda match"].message)

    def test_unlinked_rows_are_reported(self):
        self.repo.upsert_records(self.conn, [_record("Vecchio", 1, None)])
        self.conn.commit()
        by_name = {r.name: r for r in self.health.check_integrity(self.conn, "comingsoon")}
        self.conn.rollback()
        self.assertEqual("WARN", by_name["righe collegate"].level)

    def test_anomalies_flag_unordered_ranking_and_total_below_weekend(self):
        self.seed_week(days_ago=3, n=6)
        self.q("UPDATE weekly_box_office SET weekly_gross = 999999 WHERE rank = 4")  # più del rank 3
        self.q("UPDATE weekly_box_office SET total_gross = 1 WHERE rank = 6")
        self.conn.commit()

        result = self.check(self.health.check_anomalies, "comingsoon", "IT", 3)

        self.assertEqual("WARN", result.level)
        self.assertIn("2 righe sospette", result.message)

    def test_title_mapped_to_two_tmdb_films_is_flagged(self):
        self.q("INSERT INTO movies (id, title) VALUES (1, 'A'), (2, 'B')")
        self.repo.upsert_records(self.conn, [_record("Michael", 1, "1", week_start=date(2026, 7, 9)),
                                              _record("Michael", 1, "2", week_start=date(2026, 7, 16))])
        self.q("UPDATE weekly_box_office w SET movie_id = s.source_movie_id::int FROM source_movies s WHERE s.id = w.source_movie_ref")
        self.q("UPDATE source_movies SET movie_id = source_movie_id::int, match_status = 'auto'")
        self.conn.commit()

        by_name = {r.name: r for r in self.health.check_integrity(self.conn, "comingsoon")}
        self.conn.rollback()

        self.assertEqual("WARN", by_name["coerenza titoli"].level)
        self.assertIn("'Michael'", by_name["coerenza titoli"].message)

    def test_missing_weeks_returns_the_thursdays_to_recover(self):
        for days_ago in (21, 7, 0):  # manca 14 giorni fa
            self.seed_week(days_ago, n=2, sid_prefix=f"g{days_ago}-")

        result = self.health.missing_weeks(self.conn, "comingsoon", "IT", 12)
        self.conn.rollback()

        self.assertEqual([date.today() - timedelta(days=14)], result)

    def test_recovery_runs_use_their_own_pipeline_name_and_do_not_count_as_fresh_runs(self):
        from app.services.weekly_box_office_service import WeeklyBoxOfficeService
        from app.parsers.comingsoon_parser import FetchResult

        snapshot = FetchResult(url="https://web.archive.org/web/1id_/x", html="<html>archivio</html>", records=[])
        with self._service_db():
            WeeklyBoxOfficeService().load_weekly_records(
                [_record("Film A", 1, "10")], source_name="comingsoon", snapshots=[snapshot],
                pipeline_name="weekly_box_office_recovery",
            )

        self.assertEqual([("weekly_box_office_recovery", "success")], self.q("SELECT pipeline_name, status FROM ingestion_runs"))
        self.assertEqual([("https://web.archive.org/web/1id_/x",)], self.q("SELECT url FROM raw_snapshots"))
        # un recupero da archivio non deve far credere che la pipeline settimanale sia in salute
        self.assertEqual("FAIL", self.check(self.health.check_last_run, "comingsoon", 8).level)

    def test_healthy_dataset_has_no_fail(self):
        self.add_run(days_ago=1)
        for days_ago in (7, 0):
            self.seed_week(days_ago, n=12, sid_prefix=f"h{days_ago}-")
        self.q("INSERT INTO movies (id, title) VALUES (1, 'X')")
        self.q("UPDATE source_movies SET movie_id = 1, match_status = 'auto'")
        self.q("UPDATE weekly_box_office SET movie_id = 1")
        self.conn.commit()

        results = self.health.run_health_checks(self.conn)
        self.conn.rollback()

        self.assertEqual([], [r for r in results if r.level == "FAIL"], results)

    # --- vista ------------------------------------------------------------------------------

    def test_view_enriches_matched_rows_and_keeps_unmatched(self):
        self.q("INSERT INTO movies (id, title, original_title, genres) VALUES (7, 'The Odyssey', 'The Odyssey', 'Avventura')")
        self.repo.upsert_records(self.conn, [
            _record("Odissea", 1, "66812", gross=1000.0, screen_count=200),
            _record("Sconosciuto", 2, "1", gross=500.0, screen_count=0),
        ])
        self.q("UPDATE source_movies SET movie_id = 7, match_status = 'auto', match_method = 'tmdb_search',"
               " match_confidence = 0.99 WHERE source_movie_id = '66812'")
        self.q("UPDATE weekly_box_office SET movie_id = 7 WHERE external_movie_title = 'Odissea'")
        self.conn.commit()

        rows = self.q("SELECT external_movie_title, tmdb_title, genres, gross_per_screen, match_status, source_movie_id"
                      " FROM v_weekly_enriched ORDER BY rank")
        self.conn.rollback()

        self.assertEqual(("Odissea", "The Odyssey", "Avventura", 5.0, "auto", "66812"), rows[0])
        self.assertEqual(("Sconosciuto", None, None, None, "unmatched", "1"), rows[1])  # screen_count 0: niente divisione


def _admin_config():
    """Connessione da superutente per creare ruoli (settings in CI, deposito 'db:postgres' in locale) o None."""
    base = get_settings(require_tmdb=False).db_config
    candidates = [base]
    vault_password = get_secret("db:postgres")
    if vault_password:
        candidates.append({**base, "user": "postgres", "password": vault_password})
    for config in candidates:
        try:
            conn = psycopg2.connect(**{**config, "dbname": "postgres"})
        except psycopg2.Error:
            continue
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            is_super = cur.fetchone()[0]
        conn.close()
        if is_super:
            return config
    return None


@unittest.skipUnless(RUN, "imposta RUN_DB_TESTS=1 per eseguire i test su Postgres")
class RolesIntegrationTests(unittest.TestCase):
    """Ruoli a privilegi minimi veri, con nomi a prefisso casuale (mai i ruoli reali), ripuliti a fine test."""

    @classmethod
    def setUpClass(cls):
        from app.roles import RoleNames, generate_password, setup_roles

        cls.admin = _admin_config()
        if cls.admin is None:
            raise unittest.SkipTest("serve un superutente PostgreSQL per creare i ruoli di prova")

        cls.names = RoleNames.with_prefix(f"t{uuid.uuid4().hex[:6]}")
        cls.passwords = {key: generate_password() for key in ("owner", "app", "ro", "test")}
        cls.dbname = f"boxoffice_roles_{uuid.uuid4().hex[:8]}"

        admin = psycopg2.connect(**{**cls.admin, "dbname": "postgres"})
        admin.autocommit = True
        admin.cursor().execute(f"CREATE DATABASE {cls.dbname}")
        admin.close()

        conn = psycopg2.connect(**{**cls.admin, "dbname": cls.dbname})
        try:
            apply_pending(conn)  # come farebbe un amministratore: gli oggetti nascono di proprietà dell'admin
        finally:
            conn.close()
        cls.setup_result = setup_roles(cls.admin, cls.dbname, cls.names, cls.passwords)

    @classmethod
    def tearDownClass(cls):
        admin = psycopg2.connect(**{**cls.admin, "dbname": "postgres"})
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {cls.dbname} WITH (FORCE)")
            for role in (cls.names.owner, cls.names.app, cls.names.ro, cls.names.test):
                cur.execute(f"DROP ROLE IF EXISTS {role}")
        admin.close()

    def config(self, key):
        role = getattr(self.names, key)
        return {**self.admin, "dbname": self.dbname, "user": role, "password": self.passwords[key]}

    def connect(self, key):
        conn = psycopg2.connect(**self.config(key))
        self.addCleanup(conn.close)
        return conn

    def test_roles_can_log_in_with_scram_hashed_passwords(self):
        for key in ("owner", "app", "ro"):
            self.connect(key)  # se il verificatore SCRAM non fosse valido, il login fallirebbe
        # il ruolo dei test si autentica (verificatore valido) ma non ha accesso al database applicativo
        config = {**self.config("test"), "dbname": "postgres"}
        psycopg2.connect(**config).close()
        with self.assertRaises(psycopg2.OperationalError) as ctx:
            psycopg2.connect(**self.config("test"))
        self.assertIn("CONNECT", str(ctx.exception))

    def test_roles_are_not_superusers_and_only_the_test_role_can_create_databases(self):
        with self.connect("ro").cursor() as cur:
            cur.execute(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = ANY(%s) ORDER BY 1",
                ([self.names.owner, self.names.app, self.names.ro, self.names.test],),
            )
            rows = {r[0]: r[1:] for r in cur.fetchall()}
        self.assertEqual({(False, False, False)}, {rows[r] for r in (self.names.owner, self.names.app, self.names.ro)})
        self.assertEqual((False, True, False), rows[self.names.test])

    def test_every_check_of_verify_roles_passes(self):
        from app.roles import verify_roles

        checks = verify_roles({key: self.config(key) for key in ("app", "ro", "owner")})

        failed = [c for c in checks if not c.ok]
        self.assertEqual([], failed, failed)
        self.assertGreaterEqual(len(checks), 20)

    def test_ownership_moved_to_the_owner_role(self):
        with self.connect("ro").cursor() as cur:
            cur.execute(
                "SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'S')"
            )
            self.assertEqual([(self.names.owner,)], cur.fetchall())
            cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (self.dbname,))
            self.assertEqual((self.names.owner,), cur.fetchone())

    def test_every_table_and_view_has_declared_privileges(self):
        """Se una migrazione aggiunge una tabella, va dichiarata in TABLE_PRIVILEGES (app/roles.py)."""
        from app.roles import TABLE_PRIVILEGES

        with self.connect("ro").cursor() as cur:
            cur.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')"
            )
            actual = {r[0] for r in cur.fetchall()}
        self.assertEqual([], self.setup_result["objects_without_privileges"])
        self.assertEqual(set(), actual - set(TABLE_PRIVILEGES), "tabelle senza privilegi dichiarati")

    def test_new_table_is_invisible_to_app_and_ro_until_declared(self):
        from app.roles import apply_object_grants

        owner = self.connect("owner")
        with owner.cursor() as cur:
            cur.execute("CREATE TABLE tabella_nuova (x int)")
            unknown = apply_object_grants(cur, self.names)
        owner.commit()
        try:
            self.assertEqual(["tabella_nuova"], unknown)
            for key in ("app", "ro"):
                conn = self.connect(key)
                with conn.cursor() as cur, self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("SELECT * FROM tabella_nuova")
                conn.rollback()
        finally:
            with owner.cursor() as cur:
                cur.execute("DROP TABLE tabella_nuova")
            owner.commit()

    def test_grants_are_idempotent(self):
        from app.roles import apply_object_grants

        owner = self.connect("owner")
        with owner.cursor() as cur:
            first = apply_object_grants(cur, self.names)
            second = apply_object_grants(cur, self.names)
        owner.commit()
        self.assertEqual(first, second)

    def test_the_whole_pipeline_runs_with_the_least_privilege_app_role(self):
        """Nessuna operazione della pipeline deve richiedere più di quanto concesso al ruolo app."""
        from app.health import run_health_checks
        from app.services.movie_matching_service import MovieMatchingService

        patch_app = patch("app.db.get_settings", return_value=SimpleNamespace(db_config=self.config("app")))
        repo = WeeklyBoxOfficeRepository()
        snapshot = FetchResult(url="https://example.test/box", html="<html>grezzo</html>", records=[])
        weekly = [_record(f"Film {i}", i, str(100 + i), gross=9000.0 - i, weeks_in_release=3) for i in range(1, 13)]

        with patch_app:
            # 1. caricamento weekly: INSERT/UPDATE su tabelle e sequenze, run e snapshot
            written = WeeklyBoxOfficeService().load_weekly_records(
                weekly, source_name="comingsoon", snapshots=[snapshot]
            )
            # 2. film storico da unificare (DELETE su source_movies + tabella temporanea)
            app_conn = self.connect("app")
            repo.upsert_records(app_conn, [_record("Film 1", 1, None, week_start=date(2026, 9, 10))])
            app_conn.commit()
            service = MovieMatchingService(tmdb_client=FakeTMDB(
                search={f"Film {i}": [_tmdb_result(1000 + i, f"Film {i}", release="2026-09-01")] for i in range(1, 13)},
                details={1000 + i: _details(1000 + i, f"Film {i}") for i in range(1, 13)},
            ))
            counts = service.link_legacy_rows()
            # 3. match: INSERT su movies, UPDATE su source_movies e weekly, candidati
            summary = service.resolve_pending()

        self.assertEqual(12, written)
        self.assertEqual(12, summary.auto)
        self.assertGreaterEqual(counts["linked_to_real"] + counts["legacy_created"], 1)

        # 4. health check e vista con il ruolo di sola lettura
        ro = self.connect("ro")
        results = run_health_checks(ro)
        ro.rollback()
        self.assertEqual([], [r for r in results if r.level == "FAIL" and r.name != "ultima settimana"], results)
        with ro.cursor() as cur:
            cur.execute("SELECT count(*) FROM v_weekly_enriched WHERE movie_id IS NOT NULL")
            self.assertGreaterEqual(cur.fetchone()[0], 12)
        ro.rollback()


if __name__ == "__main__":
    unittest.main()

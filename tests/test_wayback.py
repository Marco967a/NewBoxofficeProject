import unittest
from datetime import date
from unittest.mock import MagicMock

import requests

from app import wayback
from app.wayback import candidate_timestamps, list_snapshots, recover_week, snapshot_url

URL = "https://www.comingsoon.it/cinema/boxoffice/"


def page(week_text: str, n_rows: int = 12) -> str:
    """Pagina ComingSoon minimale con `n_rows` righe di classifica."""
    rows = "".join(
        f'<div><a href="/film/film-{i}/{100 + i}/scheda/" title="Film {i}">{i} Film {i}</a>'
        f"<span>Settimane: 1 Distribuzione: Dist Inc. weekend: €{10000 - i * 100:,} Schermi: 100 "
        f"Inc. totale: €{20000 - i * 100:,}</span></div>".replace(",", ".")
        for i in range(1, n_rows + 1)
    )
    return f"<html><body><h1>{week_text}</h1>{rows}</body></html>"


WEEK_JUL16 = "dal 16 al 19 luglio 2026"
WEEK_JUL23 = "dal 23 al 26 luglio 2026"


class CandidateTimestampTests(unittest.TestCase):
    SNAPS = ["20260716130000", "20260719230000", "20260720141519", "20260721140216", "20260726100000", "20260727090000"]

    def test_only_snapshots_in_the_window_latest_first(self) -> None:
        # finestra per il giovedì 16/07: da domenica 19/07 a domenica 26/07
        self.assertEqual(
            ["20260726100000", "20260721140216", "20260720141519", "20260719230000"],
            candidate_timestamps(date(2026, 7, 16), self.SNAPS),
        )

    def test_no_snapshot_in_window(self) -> None:
        self.assertEqual([], candidate_timestamps(date(2026, 8, 13), self.SNAPS))


class RecoverWeekTests(unittest.TestCase):
    def test_picks_latest_snapshot_that_really_shows_the_week(self) -> None:
        pages = {
            "20260726100000": page(WEEK_JUL23),  # più recente ma di un'altra settimana: da scartare
            "20260721140216": page(WEEK_JUL16),
            "20260720141519": page(WEEK_JUL16, n_rows=11),
        }
        fetch = MagicMock(side_effect=lambda ts, url: pages[ts])

        result = recover_week(date(2026, 7, 16), URL, list(pages), fetch=fetch, delay_seconds=0)

        self.assertEqual(snapshot_url("20260721140216", URL), result.url)
        self.assertEqual(12, len(result.records))
        self.assertEqual(date(2026, 7, 16), result.records[0].week_start)
        self.assertEqual("101", result.records[0].source_movie_id)  # l'ID film ComingSoon viene catturato

    def test_url_uses_the_raw_id_variant(self) -> None:
        self.assertEqual(
            "https://web.archive.org/web/20260721140216id_/https://www.comingsoon.it/cinema/boxoffice/",
            snapshot_url("20260721140216", URL),
        )

    def test_incomplete_snapshot_is_rejected(self) -> None:
        pages = {"20260721140216": page(WEEK_JUL16, n_rows=4)}
        result = recover_week(date(2026, 7, 16), URL, list(pages), fetch=lambda ts, url: pages[ts], delay_seconds=0)
        self.assertIsNone(result)

    def test_unparsable_or_failing_snapshot_is_skipped(self) -> None:
        pages = {"20260726100000": "<html>nessuna classifica</html>", "20260721140216": page(WEEK_JUL16)}

        result = recover_week(date(2026, 7, 16), URL, list(pages), fetch=lambda ts, url: pages[ts], delay_seconds=0)
        self.assertIsNotNone(result)  # la pagina senza classifica viene saltata, la successiva va bene

        boom = MagicMock(side_effect=requests.ConnectionError("down"))
        self.assertIsNone(recover_week(date(2026, 7, 16), URL, list(pages), fetch=boom, delay_seconds=0))

    def test_returns_none_without_candidates_and_respects_max_attempts(self) -> None:
        fetch = MagicMock()
        self.assertIsNone(recover_week(date(2026, 8, 13), URL, ["20260721140216"], fetch=fetch, delay_seconds=0))
        fetch.assert_not_called()

        many = [f"2026072{d}100000" for d in range(0, 7)]
        wrong = MagicMock(return_value=page(WEEK_JUL23))
        recover_week(date(2026, 7, 16), URL, many, fetch=wrong, max_attempts=2, delay_seconds=0)
        self.assertEqual(2, wrong.call_count)


class RetryTests(unittest.TestCase):
    @staticmethod
    def response(status):
        r = MagicMock(status_code=status, text="ok")
        r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(f"HTTP {status}", response=r)
        return r

    def test_transient_errors_are_retried_with_growing_waits(self) -> None:
        session = MagicMock()
        session.get.side_effect = [self.response(503), requests.ReadTimeout("lento"), self.response(200)]
        waits = []

        result = wayback._get(session, "u", sleep=waits.append, timeout=1)

        self.assertEqual("ok", result.text)
        self.assertEqual([5, 15], waits)

    def test_gives_up_after_the_last_attempt(self) -> None:
        session = MagicMock()
        session.get.return_value = self.response(503)
        waits = []

        with self.assertRaises(requests.HTTPError):
            wayback._get(session, "u", sleep=waits.append, timeout=1)

        self.assertEqual(4, session.get.call_count)
        self.assertEqual([5, 15, 45], waits)

    def test_client_errors_are_not_retried(self) -> None:
        session = MagicMock()
        session.get.return_value = self.response(404)

        with self.assertRaises(requests.HTTPError):
            wayback._get(session, "u", sleep=lambda s: None, timeout=1)

        self.assertEqual(1, session.get.call_count)


class ListSnapshotsTests(unittest.TestCase):
    def test_parses_cdx_json_skipping_header_and_sorting(self) -> None:
        session = MagicMock()
        response = MagicMock(text="[...]", status_code=200)
        response.json.return_value = [["timestamp"], ["20260915140659"], ["20260721140216"], ["20260721140216"]]
        session.get.return_value = response

        result = list_snapshots("comingsoon.it/cinema/boxoffice", date(2026, 7, 19), date(2026, 9, 20), session=session)

        self.assertEqual(["20260721140216", "20260915140659"], result)
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(("20260719", "20260920"), (params["from"], params["to"]))
        self.assertIn("progetto personale", session.get.call_args.kwargs["headers"]["User-Agent"])

    def test_empty_index_returns_empty_list(self) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(text="", status_code=200)
        self.assertEqual([], list_snapshots("x", date(2026, 1, 1), date(2026, 1, 2), session=session))

    def test_user_agent_does_not_contain_personal_data(self) -> None:
        self.assertNotIn("@", wayback.USER_AGENT)


if __name__ == "__main__":
    unittest.main()

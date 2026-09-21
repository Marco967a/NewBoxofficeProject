import unittest
from datetime import date

from app.matching import (
    Candidate,
    date_score,
    decide,
    estimate_italian_release,
    italian_release_score,
    normalize_title,
    query_variants,
    score_candidate,
    title_similarity,
)


def cand(score, tmdb_id=1, popularity=10.0):
    return Candidate(tmdb_id, "T", "T", date(2026, 1, 1), popularity, score, 1.0, score)


class TitleTests(unittest.TestCase):
    def test_normalize_removes_accents_punctuation_and_case(self) -> None:
        self.assertEqual("cos e l amore", normalize_title("Cos'è l'Amore?"))
        self.assertEqual("spider man brand new day", normalize_title("Spider-Man: Brand New Day"))
        self.assertEqual("", normalize_title(None))

    def test_identical_after_normalization_is_perfect(self) -> None:
        self.assertEqual(1.0, title_similarity("Amori & Incantesimi 2", "Amori & incantesimi 2"))

    def test_leading_article_is_ignored(self) -> None:
        self.assertGreaterEqual(title_similarity("Il Bene Comune", "Bene Comune"), 0.95)
        self.assertGreaterEqual(title_similarity("The Dog Stars", "Dog Stars"), 0.95)

    def test_prefix_subtitle_is_tolerated(self) -> None:
        self.assertGreaterEqual(
            title_similarity("The Dog Stars - Le Stelle Dopo la Fine", "The Dog Stars"), 0.85
        )

    def test_candidate_extending_the_source_title_is_weaker_than_the_reverse(self) -> None:
        # la sorgente ha il sottotitolo in più: indizio forte
        self.assertGreaterEqual(title_similarity("Titolo Uno - sottotitolo lungo", "Titolo Uno"), 0.88)
        # il candidato ha il sottotitolo in più: quasi sempre un altro film
        self.assertLess(title_similarity("Election Day", "Election Day - The Day Thailand Voted"), 0.8)

    def test_unrelated_titles_score_low(self) -> None:
        self.assertLess(title_similarity("Odissea", "Toy Story 5"), 0.4)

    def test_empty_or_non_latin_titles_score_zero(self) -> None:
        self.assertEqual(0.0, title_similarity("Odissea", ""))
        self.assertEqual(0.0, title_similarity("Odissea", "哪吒"))

    def test_single_word_prefix_is_not_enough(self) -> None:
        # "Blue" non deve diventare un match forte di "Blue Beetle"
        self.assertLess(title_similarity("Blue", "Blue Beetle"), 0.85)


class DateTests(unittest.TestCase):
    def test_estimated_release_counts_back_from_current_week(self) -> None:
        self.assertEqual(date(2026, 7, 16), estimate_italian_release(date(2026, 9, 17), 10))
        self.assertEqual(date(2026, 9, 17), estimate_italian_release(date(2026, 9, 17), 1))
        self.assertEqual(date(2026, 9, 17), estimate_italian_release(date(2026, 9, 17), None))

    def test_date_score_bands(self) -> None:
        est = date(2026, 7, 16)
        self.assertEqual(1.0, date_score(est, date(2026, 7, 16)))
        self.assertEqual(1.0, date_score(est, date(2026, 7, 20)))  # TMDB poco dopo l'Italia
        self.assertEqual(1.0, date_score(est, date(2026, 5, 1)))  # anteprima precedente
        self.assertLess(date_score(est, date(2025, 8, 1)), 0.6)  # quasi un anno prima
        self.assertEqual(0.0, date_score(est, date(1999, 1, 1)))  # remake/omonimo
        self.assertEqual(0.0, date_score(est, date(2027, 1, 1)))  # uscirà molto dopo
        self.assertEqual(0.4, date_score(est, None))  # data ignota: neutro-prudente
        self.assertEqual(0.4, date_score(None, date(2026, 1, 1)))


class ItalianReleaseTests(unittest.TestCase):
    EST = date(2026, 7, 16)

    def test_score_bands(self) -> None:
        self.assertEqual(1.0, italian_release_score(self.EST, [date(2026, 7, 16)]))
        self.assertEqual(1.0, italian_release_score(self.EST, [date(2026, 7, 9), date(2026, 12, 1)]))  # basta una data vicina
        self.assertLess(italian_release_score(self.EST, [date(2026, 8, 20)]), 0.5)
        self.assertEqual(0.0, italian_release_score(self.EST, [date(2024, 12, 11)]))

    def test_no_data_means_fallback(self) -> None:
        self.assertIsNone(italian_release_score(self.EST, []))
        self.assertIsNone(italian_release_score(self.EST, None))
        self.assertIsNone(italian_release_score(None, [date(2026, 7, 16)]))

    def test_it_release_confirms_a_re_release_with_an_old_tmdb_date(self) -> None:
        old = {"id": 1, "title": "Cars", "original_title": "Cars", "release_date": "2006-06-08", "popularity": 50}
        without = score_candidate("Cars", date(2026, 9, 17), old)
        confirmed = score_candidate("Cars", date(2026, 9, 17), old, None, [date(2026, 9, 17)])
        self.assertLess(without.score, 0.85)
        self.assertGreaterEqual(confirmed.score, 0.85)

    def test_it_release_far_from_estimate_contradicts_a_homonym(self) -> None:
        homonym = {"id": 2, "title": "Election Day", "original_title": "Election Day",
                   "release_date": "2026-07-09", "popularity": 20}
        c = score_candidate("Election Day", date(2026, 7, 9), homonym, None, [date(2024, 11, 1)])
        self.assertEqual(0.0, c.date_score)
        self.assertLess(c.score, 0.85)


class DecisionTests(unittest.TestCase):
    def test_clear_winner_is_auto(self) -> None:
        d = decide([cand(0.95, 1), cand(0.5, 2)])
        self.assertEqual("auto", d.status)
        self.assertEqual(1, d.best.tmdb_id)

    def test_high_score_but_tight_margin_needs_review(self) -> None:
        self.assertEqual("needs_review", decide([cand(0.92, 1), cand(0.88, 2)]).status)

    def test_medium_score_needs_review(self) -> None:
        self.assertEqual("needs_review", decide([cand(0.7, 1)]).status)

    def test_low_score_or_no_candidates_is_no_match(self) -> None:
        self.assertEqual("no_match", decide([cand(0.3, 1)]).status)
        empty = decide([])
        self.assertEqual("no_match", empty.status)
        self.assertIsNone(empty.best)


class ScoreCandidateTests(unittest.TestCase):
    RESULT = {
        "id": 42,
        "title": "The Odyssey",
        "original_title": "The Odyssey",
        "release_date": "2026-07-15",
        "popularity": 300.0,
    }

    def test_same_title_and_compatible_date_is_auto_grade(self) -> None:
        c = score_candidate("The Odyssey", date(2026, 7, 16), self.RESULT)
        self.assertGreaterEqual(c.score, 0.85)

    def test_italian_alternative_title_rescues_a_different_title(self) -> None:
        without = score_candidate("Odissea", date(2026, 7, 16), self.RESULT)
        with_alt = score_candidate("Odissea", date(2026, 7, 16), self.RESULT, ["Odissea"])
        self.assertLess(without.score, 0.85)  # senza il titolo IT resterebbe solo "da rivedere"
        self.assertGreaterEqual(with_alt.score, 0.85)

    def test_same_title_wrong_decade_is_not_auto(self) -> None:
        old = {**self.RESULT, "release_date": "1997-01-01"}
        self.assertNotEqual("auto", decide([score_candidate("The Odyssey", date(2026, 7, 16), old)]).status)

    def test_invalid_release_date_is_tolerated(self) -> None:
        c = score_candidate("X", date(2026, 7, 16), {**self.RESULT, "release_date": "boh"})
        self.assertIsNone(c.release_date)


class QueryVariantTests(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(["Odissea"], query_variants("Odissea"))
        self.assertEqual(
            ["The Dog Stars - Le Stelle Dopo la Fine", "The Dog Stars"],
            query_variants("The Dog Stars - Le Stelle Dopo la Fine"),
        )
        self.assertEqual(
            ["...Che Dio Perdona a Tutti", "Che Dio Perdona a Tutti"],
            query_variants("...Che Dio Perdona a Tutti"),
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from app.parsers.comingsoon_parser import (
    build_archive_candidate_urls,
    parse_boxoffice_page,
)


class ComingSoonParserArchiveUrlTests(unittest.TestCase):
    def test_build_archive_candidate_urls_includes_common_patterns(self) -> None:
        urls = build_archive_candidate_urls(date(2024, 2, 15))

        self.assertTrue(urls)
        self.assertIn("https://www.comingsoon.it/cinema/boxoffice/2024/02/15/", urls)
        self.assertIn("https://www.comingsoon.it/cinema/boxoffice/2024-02-15/", urls)
        self.assertIn("https://www.comingsoon.it/cinema/boxoffice/?date=2024-02-15", urls)
        self.assertIn("https://www.comingsoon.it/cinema/boxoffice/?year=2024&month=02&day=15", urls)

    def test_parse_boxoffice_page_extracts_records_from_html(self) -> None:
        html = """
        <html><body>
        <div>dal 2 febbraio 2024 al 8 febbraio 2024</div>
        <a href="/film/film-test/123/scheda/" title="Film Test">
            1 Film Test
        </a>
        <div>
            Settimane: 4 Distribuzione: Warner Bros. Inc. weekend: €1.234.567 Schermi: 600 Inc. totale: €2.345.678
        </div>
        </body></html>
        """

        records = parse_boxoffice_page(html)

        self.assertEqual(1, len(records))
        self.assertEqual("Film Test", records[0].external_movie_title)
        self.assertEqual(date(2024, 2, 2), records[0].week_start)
        self.assertEqual(date(2024, 2, 8), records[0].week_end)
        self.assertEqual(1234567.0, records[0].weekly_gross)
        self.assertEqual(4, records[0].weeks_in_release)


if __name__ == "__main__":
    unittest.main()

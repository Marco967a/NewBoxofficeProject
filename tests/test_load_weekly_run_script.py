import unittest
from unittest.mock import Mock, patch

from scripts.weekly_run import main


class WeeklyRunScriptTests(unittest.TestCase):
    @patch("scripts.weekly_run.WeeklyBoxOfficeService")
    @patch("scripts.weekly_run.parse_comingsoon_weekly_boxoffice")
    def test_main_loads_parsed_records(self, parser_mock, service_mock) -> None:
        parser_mock.return_value = [Mock()]
        service_mock.return_value.load_weekly_records.return_value = 1

        with patch("scripts.weekly_run.sys.argv", ["weekly_run.py"]):
            main()

        service_mock.return_value.load_weekly_records.assert_called_once_with(
            records=parser_mock.return_value,
            source_name="comingsoon",
        )

    @patch("scripts.weekly_run.parse_comingsoon_weekly_boxoffice", return_value=[])
    def test_main_fails_when_parser_returns_no_records(self, _parser_mock) -> None:
        with patch("scripts.weekly_run.sys.argv", ["weekly_run.py"]):
            with self.assertRaises(RuntimeError):
                main()


if __name__ == "__main__":
    unittest.main()

import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.export_site_data import validate_payload

VALID = {
    "generated_at": "2026-09-22T19:31:28.975600+00:00",
    "source": "comingsoon",
    "territory": "IT",
    "currency": "EUR",
    "latest_week": "2026-09-17",
    "has_quality_warnings": False,
    "note": "nota",
    "weekly_trend": [{"week_start": "2026-09-17", "total_gross": 6391944.0, "titles": 20}],
    "top_titles": [
        {"rank": 1, "title": "Film", "weekly_gross": 1440852.0, "screen_count": 345},
        {"rank": 2, "title": "Altro", "weekly_gross": 10.0, "screen_count": None},
    ],
}


class ValidatePayloadTests(unittest.TestCase):
    def test_valid_payload_has_no_problems(self) -> None:
        self.assertEqual(validate_payload(VALID), [])

    def test_committed_sample_is_valid(self) -> None:
        sample = json.loads((REPO_ROOT / "site_data" / "boxoffice.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_payload(sample), [])

    def test_missing_key_is_reported(self) -> None:
        payload = copy.deepcopy(VALID)
        del payload["currency"]
        self.assertTrue(any(p.startswith("currency") for p in validate_payload(payload)))

    def test_empty_top_titles_is_reported(self) -> None:
        payload = copy.deepcopy(VALID)
        payload["top_titles"] = []
        self.assertTrue(any(p.startswith("top_titles") for p in validate_payload(payload)))

    def test_non_numeric_gross_is_reported(self) -> None:
        payload = copy.deepcopy(VALID)
        payload["top_titles"][0]["weekly_gross"] = "1.000"
        self.assertTrue(any(p.startswith("top_titles[0]") for p in validate_payload(payload)))

    def test_invalid_date_is_reported(self) -> None:
        payload = copy.deepcopy(VALID)
        payload["generated_at"] = "ieri"
        self.assertTrue(any(p.startswith("generated_at") for p in validate_payload(payload)))


if __name__ == "__main__":
    unittest.main()

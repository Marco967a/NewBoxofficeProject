import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backup_db import select_backups_to_prune

NOW = datetime(2026, 9, 23, 12, 0, 0)


def _dump(name: str, days_old: int):
    return Path(name), NOW - timedelta(days=days_old)


class SelectBackupsToPruneTests(unittest.TestCase):
    """Logica pura di retention: nessun filesystem reale, solo (path, mtime) finti."""

    def test_fewer_than_keep_min_deletes_nothing(self) -> None:
        backups = [_dump("a.dump", 100), _dump("b.dump", 200)]
        self.assertEqual(select_backups_to_prune(backups, keep_days=30, keep_min=3, now=NOW), [])

    def test_recent_backups_beyond_keep_min_are_kept(self) -> None:
        backups = [_dump("a.dump", 1), _dump("b.dump", 2), _dump("c.dump", 3), _dump("d.dump", 5)]
        self.assertEqual(select_backups_to_prune(backups, keep_days=30, keep_min=3, now=NOW), [])

    def test_old_backups_beyond_keep_min_are_deleted(self) -> None:
        backups = [
            _dump("recent1.dump", 1),
            _dump("recent2.dump", 2),
            _dump("recent3.dump", 3),
            _dump("old.dump", 60),
        ]
        self.assertEqual(
            select_backups_to_prune(backups, keep_days=30, keep_min=3, now=NOW), [Path("old.dump")]
        )

    def test_old_backup_within_keep_min_window_is_kept(self) -> None:
        backups = [_dump("only_old.dump", 60)]
        self.assertEqual(select_backups_to_prune(backups, keep_days=30, keep_min=3, now=NOW), [])


if __name__ == "__main__":
    unittest.main()

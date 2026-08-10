import subprocess
import sys
import unittest
from pathlib import Path


class LoadWeeklyRunScriptTests(unittest.TestCase):
    def test_load_weekly_run_script_runs_from_repo_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/load_weekly_run.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=600,
        )

        self.assertEqual(
            0,
            result.returncode,
            msg=f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()

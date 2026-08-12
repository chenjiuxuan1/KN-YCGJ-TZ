"""Offline tests for the new governance remote_scripts (no infra required)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "remote_scripts"


def run_script(name, *argv, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), *argv],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60,
    )
    return result


class SrZombieQueryTests(unittest.TestCase):
    def test_query_candidates_dry_run(self):
        result = run_script("sr_zombie_query.py", "--country", "cn",
                            "--operation", "query_candidates", "--batch-id", "202606", "--dry-run")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["success"])
        self.assertIn("gov_sr_zombie_detail_202606_start", payload["sql"])

    def test_validate_queries_start_end_counts(self):
        result = run_script("sr_zombie_query.py", "--country", "cn",
                            "--operation", "validate", "--batch-id", "202606", "--dry-run")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIn("start_cnt", payload["sql"])
        self.assertIn("end_cnt", payload["sql"])

    def test_bad_batch_id_rejected(self):
        result = run_script("sr_zombie_query.py", "--country", "cn",
                            "--operation", "query_candidates", "--batch-id", "abcdef", "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["success"])


class GovernanceReleaseTests(unittest.TestCase):
    def test_wrong_token_refused(self):
        result = run_script("governance_release.py", "--country", "cn", "--action", "freeze_table",
                            "--table-schema", "ads", "--table-name", "t", "--confirm-token", "WRONG")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "RELEASE_CONFIRM_REJECTED")

    def test_freeze_dry_run_builds_rename(self):
        result = run_script("governance_release.py", "--country", "cn", "--action", "freeze_table",
                            "--table-schema", "ads", "--table-name", "t", "--batch-id", "202606",
                            "--confirm-token", "SECRET", env_extra={"GOVERNANCE_CONFIRM_TOKEN": "SECRET"})
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["dry_run"])
        self.assertIn("RENAME", payload["result"]["sqls"][0])

    def test_disable_ds_task_dry_run(self):
        result = run_script("governance_release.py", "--country", "cn", "--action", "disable_ds_task",
                            "--project-code", "1", "--workflow-code", "2", "--task-name", "t",
                            "--confirm-token", "SECRET", env_extra={"GOVERNANCE_CONFIRM_TOKEN": "SECRET"})
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["success"])


class WeeklyGovernanceTests(unittest.TestCase):
    def test_missing_data_reports_clean_error(self):
        # Accepts the OpenAPI/n8n contract (window args + dry-run) and returns a
        # clean JSON error when the required data files are not provided.
        result = run_script("weekly_governance.py", "--country", "cn",
                            "--window-start", "2026-08-03", "--window-end", "2026-08-09", "--dry-run")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "WEEKLY_GOVERNANCE_NO_DATA")


if __name__ == "__main__":
    unittest.main()

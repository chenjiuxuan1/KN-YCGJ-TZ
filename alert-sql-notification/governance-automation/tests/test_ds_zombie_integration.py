import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from governance_automation.ds_zombie_repository import build_scan_sql
from governance_automation.ds_zombie_store import candidate_upsert_sql


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_scan_sql_contains_relations_instances_and_dependent_tasks(self):
        sql = build_scan_sql(country="th", lookback_days=30)
        for table in (
            "t_ds_workflow_task_relation",
            "t_ds_task_definition",
            "t_ds_process_instance",
            "t_ds_schedules",
        ):
            self.assertIn(table, sql)
        self.assertTrue(sql.lstrip().upper().startswith("WITH"))
        self.assertNotIn("DELETE ", sql.upper())


class StoreTests(unittest.TestCase):
    def test_candidate_upsert_has_idempotent_key(self):
        sql = candidate_upsert_sql("governance.ds_zombie_workflow")
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertIn("batch_id", sql)
        self.assertIn("workflow_code", sql)
        self.assertIn("score_version", sql)


class CliTests(unittest.TestCase):
    def test_cli_has_no_password_argument(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "remote_scripts/ds_zombie_scan.py"), "--help"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--password", result.stdout)
        self.assertIn("--dry-run", result.stdout)


class WorkflowTests(unittest.TestCase):
    def _load_builder(self):
        path = ROOT / "tools/build_ds_zombie_scan_workflow.py"
        spec = importlib.util.spec_from_file_location("workflow_builder", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_generated_workflow_preserves_country_routes_without_bulk_json(self):
        workflow = self._load_builder().build_workflow()
        names = {node["name"] for node in workflow["nodes"]}
        self.assertIn("按国家分流", names)
        self.assertNotIn("Build Zombie Workflow Candidates", names)
        self.assertNotIn("Parse DS Metadata Result", names)
        commands = [
            node["parameters"]["command"]
            for node in workflow["nodes"]
            if node["type"] == "n8n-nodes-base.ssh"
        ]
        self.assertEqual(len(commands), 6)
        self.assertTrue(all("ds_zombie_scan.py" in command for command in commands))
        raw = json.dumps(workflow, ensure_ascii=False)
        self.assertNotIn("DS_DB_PASSWORD='", raw)


if __name__ == "__main__":
    unittest.main()

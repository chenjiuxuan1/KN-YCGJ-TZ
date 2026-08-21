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
            "t_ds_workflow_instance",
            "t_ds_schedules",
        ):
            self.assertIn(table, sql)
        self.assertIn("workflow_definition_code AS workflow_code", sql)
        self.assertIn("schedule_active", sql)
        self.assertIn("active_instance_present", sql)
        self.assertNotIn("process_definition_code", sql)
        self.assertNotIn("DELETE ", sql.upper())

    def test_philippines_uses_workflow_schema(self):
        sql = build_scan_sql(country="ph", lookback_days=30)
        for table in (
            "t_ds_workflow_definition",
            "t_ds_workflow_task_relation",
            "t_ds_workflow_instance",
            "t_ds_schedules",
        ):
            self.assertIn(table, sql)
        self.assertIn("workflow_definition_code AS workflow_code", sql)
        self.assertNotIn("t_ds_process_definition", sql)

    def test_dynamic_month_window_adds_total_runs_window(self):
        sql = build_scan_sql(country="th", lookback_days=30, inactive_months=3)
        self.assertIn("INTERVAL 3 MONTH", sql)
        self.assertIn("total_runs_window", sql)
        self.assertIn("scan_window_unit", sql)
        self.assertIn("'month'", sql)

    def test_default_window_falls_back_to_days(self):
        sql = build_scan_sql(country="th", lookback_days=30)
        self.assertIn("INTERVAL 30 DAY", sql)
        self.assertIn("total_runs_window", sql)
        self.assertIn("'day'", sql)

    def test_legacy_schema_uses_process_tables(self):
        sql = build_scan_sql(country="pk", lookback_days=30, schema="legacy")
        for table in (
            "t_ds_process_definition",
            "t_ds_process_task_relation",
            "t_ds_process_instance",
        ):
            self.assertIn(table, sql)
        self.assertIn("process_definition_code AS workflow_code", sql)
        self.assertIn("rel.process_definition_version = wd.version", sql)
        self.assertNotIn("t_ds_workflow_definition", sql)
        self.assertNotIn("t_ds_workflow_instance", sql)
        self.assertNotIn("workflow_definition_code", sql)

    def test_legacy_schema_metadata_exporter(self):
        from governance_automation.ds_metadata_exporter import build_ds_task_metadata_sql
        sql = build_ds_task_metadata_sql(country="pk", schema="legacy")
        self.assertIn("JOIN t_ds_process_definition pd", sql)
        self.assertIn("JOIN t_ds_process_task_relation rel", sql)
        self.assertIn("rel.process_definition_code = pd.code", sql)
        self.assertNotIn("t_ds_workflow_definition", sql)
        self.assertNotIn("t_ds_workflow_task_relation", sql)

    def test_schema_resolver_and_detection(self):
        from governance_automation.ds_schema import (
            build_schema_probe_sql, detect_ds_schema, ds_schema_names, resolve_ds_schema,
        )
        self.assertEqual(resolve_ds_schema("new"), "new")
        self.assertEqual(resolve_ds_schema("legacy"), "legacy")
        self.assertEqual(resolve_ds_schema("v2"), "legacy")
        self.assertEqual(resolve_ds_schema(None, "ph"), "new")
        self.assertEqual(ds_schema_names("legacy")["workflow_definition"], "t_ds_process_definition")
        self.assertEqual(detect_ds_schema([{"table_name": "t_ds_process_definition"}]), "legacy")
        self.assertEqual(detect_ds_schema([{"table_name": "t_ds_workflow_definition"}]), "new")
        self.assertIsNone(detect_ds_schema([]))
        probe = build_schema_probe_sql()
        self.assertIn("information_schema.tables", probe)
        self.assertIn("t_ds_workflow_definition", probe)
        self.assertIn("t_ds_process_definition", probe)
        self.assertNotIn("DELETE ", probe.upper())

    def test_scan_sql_readonly_with_schema(self):
        for schema in (None, "new", "legacy"):
            sql = build_scan_sql(country="pk", lookback_days=30, schema=schema)
            self.assertNotIn("DELETE ", sql.upper())
            self.assertNotIn("UPDATE ", sql.upper())
            self.assertNotIn("DROP ", sql.upper())


    def test_project_name_filters_by_exact_match(self):
        sql = build_scan_sql(country="mx", lookback_days=30, project_name="巴基斯坦-智能贷后")
        self.assertIn("p.name = '巴基斯坦-智能贷后'", sql)
        self.assertNotIn("p.name LIKE", sql)
        self.assertIn("NULL IS NULL OR p.name = ''", build_scan_sql(country="mx", lookback_days=30))

    def test_workflow_and_task_use_fuzzy_like_with_escape(self):
        sql = build_scan_sql(country="mx", lookback_days=30, workflow_name="运营监控", task_name="推送")
        self.assertIn("wd.name LIKE CONCAT('%', '运营监控', '%') ESCAPE '\\'", sql)
        self.assertIn("td.name LIKE CONCAT('%', '推送', '%') ESCAPE '\\'", sql)

    def test_like_literal_escapes_wildcards_and_backslash(self):
        from governance_automation.ds_zombie_repository import quote_like_literal
        self.assertEqual(quote_like_literal("100%done"), "'100\\\\%done'")
        self.assertEqual(quote_like_literal("a_b"), "'a\\\\_b'")
        self.assertEqual(quote_like_literal("a\\b"), "'a\\\\\\\\b'")
        self.assertEqual(quote_like_literal("a'b"), "'a''b'")


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
        request = next(node for node in workflow["nodes"] if node["name"] == "Build Manual Scan Request")
        self.assertIn("country:'th'", request["parameters"]["jsCode"])
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

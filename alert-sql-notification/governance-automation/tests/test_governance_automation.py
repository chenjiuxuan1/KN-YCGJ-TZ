import unittest
import tempfile
import importlib.util
import os
import sys
from pathlib import Path

from governance_automation.level_classifier import classify_governance_level, score_abnormal_sql
from governance_automation.governance_store import upsert_governance_records
from governance_automation.action_planner import plan_abnormal_sql_action, plan_ds_zombie_action
from governance_automation.ds_metadata_exporter import build_ds_task_metadata_sql, quote_sql_literal
from governance_automation.ds_resource_enricher import enrich_task_row_with_resources, extract_resource_refs
from governance_automation.ds_task_matcher import enrich_abnormal_rows_with_ds_task, match_ds_task
from governance_automation.feedback_ingest import apply_abnormal_sql_feedback
from governance_automation.notification_payloads import build_notification_payload
from governance_automation.owner_resolver import build_project_owner_index, resolve_ds_task_owner, resolve_special_group
from governance_automation.pipeline import run_weekly_governance
from governance_automation.sql_fingerprint import build_sql_fingerprint
from governance_automation.weekly_aggregator import aggregate_abnormal_sql


class GovernanceAutomationTests(unittest.TestCase):
    def test_ds_country_config_uses_password_environment_variable(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        old_value = os.environ.get("MX_DS_DB_PASSWORD")
        os.environ["MX_DS_DB_PASSWORD"] = "test-password"
        try:
            connection = module.configured_ds_mysql_connection("mx")
        finally:
            if old_value is None:
                os.environ.pop("MX_DS_DB_PASSWORD", None)
            else:
                os.environ["MX_DS_DB_PASSWORD"] = old_value

        self.assertEqual(connection.host, "rm-2ev5479nuworkbb0x.mysql.rds.aliyuncs.com")
        self.assertEqual(connection.database, "dolphin_scheduler")
        self.assertEqual(connection.user, "e_ds")
        self.assertEqual(connection.password, "test-password")

    def test_remote_ds_host_gate_allows_only_configured_ds_ips(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        allowed, meta = module.ds_host_gate("ph", "worker host 10.20.84.22:1234")
        self.assertTrue(allowed)
        self.assertEqual(meta["ds_host_gate"], "matched")
        self.assertEqual(meta["matched_ds_host_ips"], ["10.20.84.22"])

        allowed, meta = module.ds_host_gate("ph", "10.20.99.99")
        self.assertFalse(allowed)
        self.assertEqual(meta["ds_host_gate_reason"], "alert-host-ip-not-in-ds-allowlist")

        allowed, meta = module.ds_host_gate("ph", "")
        self.assertTrue(allowed)
        self.assertEqual(meta["ds_host_gate"], "unverified")
        self.assertEqual(meta["ds_host_gate_reason"], "missing-alert-host-ip")

    def test_remote_ds_match_does_not_treat_derived_mv_task_as_target_table(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        rows, meta = module.pick_best_match(
            "insert into dwt.dwt_user_behavior_base_snap select * from dwd.dwd_w_user",
            [
                {
                    "project_name": "实验平台",
                    "workflow_name": "标签准备",
                    "task_name": "dwt_user_behavior_base_snap_hot_mv",
                    "task_type": "SQL",
                    "script_content": "REFRESH MATERIALIZED VIEW dwt.dwt_user_behavior_base_snap_hot_mv WITH SYNC MODE;",
                }
            ],
        )

        self.assertEqual(rows, [])
        self.assertEqual(meta["match_info"], "no-match")

    def test_remote_ds_match_allows_exact_target_task_name(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        rows, meta = module.pick_best_match(
            "insert into dwt.dwt_user_behavior_base_snap select * from dwd.dwd_w_user",
            [
                {
                    "project_name": "实验平台",
                    "workflow_name": "标签准备",
                    "task_name": "dwt_user_behavior_base_snap",
                    "task_type": "SQL",
                    "script_content": "REFRESH MATERIALIZED VIEW dwt.dwt_user_behavior_base_snap WITH SYNC MODE;",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_name"], "dwt_user_behavior_base_snap")
        self.assertEqual(meta["confidence"], "high")

    def test_remote_ds_match_rejects_quality_check_definition_candidates(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        rows, meta = module.pick_best_match(
            "insert into ads.ads_user_stat select * from dwd.dwd_w_user",
            [
                {
                    "project_name": "菲律宾数仓-数据质量",
                    "workflow_name": "每12小时校验2级表数据(D-1)",
                    "task_name": "ADS层数据校验",
                    "task_type": "SHELL",
                    "script_content": "select count(*) from ads.ads_user_stat join dwd.dwd_w_user on 1 = 1",
                }
            ],
        )

        self.assertEqual(rows, [])
        self.assertEqual(meta["match_info"], "no-match")

    def test_remote_ds_match_prefers_sql_template_and_account_hits(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        rows, meta = module.pick_best_match(
            "insert into ads.ads_user_stat select * from dwd.dwd_user where dt = '2026-07-14' and user_id = 123",
            [
                {
                    "project_name": "strategy",
                    "workflow_name": "superset_strategy_daily",
                    "task_name": "ads_user_stat_sync",
                    "task_type": "SQL",
                    "task_creator": "e_superset_strategy",
                    "script_content": "insert into ads.ads_user_stat select * from dwd.dwd_user where dt = '2026-07-15' and user_id = 456",
                }
            ],
            primary_account="e_superset_strategy",
            account_hints=["e_superset_strategy"],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(meta["confidence"], "high")
        self.assertTrue(meta["matched_sql_template"])
        self.assertIn("strategy", meta["matched_account_hits"])

    def test_remote_ds_recent_instance_query_uses_account_prefilter_then_fallback(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        captured_sql: list[str] = []

        def fake_query_mysql_rows(connection, sql, timeout=180):
            captured_sql.append(sql)
            return [] if len(captured_sql) == 1 else [{"task_name": "matched"}]

        original_query = module.query_mysql_rows
        module.query_mysql_rows = fake_query_mysql_rows
        try:
            rows, meta = module.query_recent_instances(
                module.MysqlConnection("host", "3306", "db", "user", "pwd"),
                "insert into ads.ads_user_stat select * from dwd.dwd_user",
                alert_time="2026-07-14 10:05:00",
                after_minutes=5,
                limit=20,
                primary_account="e_ds_aifox",
                account_hints=["e_ds_aifox"],
                precise_window_minutes=15,
                fallback_window_minutes=60,
            )
        finally:
            module.query_mysql_rows = original_query

        self.assertEqual(len(rows), 1)
        self.assertEqual(meta["instance_query_mode"], "time_window_account_prefilter_fallback")
        self.assertEqual(meta["instance_time_start"], "2026-07-14 09:05:00")
        self.assertEqual(meta["instance_time_end"], "2026-07-14 10:10:00")
        self.assertEqual(len(captured_sql), 2)
        self.assertIn("LOWER(COALESCE(project_owner.user_name, '')) LIKE '%aifox%'", captured_sql[0])
        self.assertIn("aifox", captured_sql[0])
        self.assertNotIn("LIKE '%aifox%'", captured_sql[1])

    def test_remote_ds_instance_fallback_rejects_temporary_target_without_log_evidence(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        rows, meta = module.score_instance_matches(
            """
            create table dm_tmp.phi_sd_okr_1204_15d as
            select * from hive.dwb_paimon.dwb_r_ask_loan_result r
            join hive.dwd.dwd_w_apply a on r.ask_loan_result_user_uuid = a.user_uuid
            """,
            [
                {
                    "project_name": "菲律宾数仓-正式环境",
                    "workflow_name": "DWD_PAIMON-20260713133552354",
                    "task_name": "dwd_app_ask_loan_result",
                    "task_type": "SHELL",
                    "instance_start_time": "2026-07-13 13:38:50",
                    "instance_log_path": "/not/readable.log",
                }
            ],
            log_limit=0,
        )

        self.assertEqual(rows, [])
        self.assertEqual(meta["match_info"], "no-match")
        self.assertTrue(meta["temporary_target_mode"])

    def test_remote_ds_instance_fallback_matches_temporary_target_with_log_evidence(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        source_sql = """
            create table dm_tmp.phi_sd_okr_1204_15d as
            select * from hive.dwb_paimon.dwb_r_ask_loan_result r
            join hive.dwd.dwd_w_apply a on r.ask_loan_result_user_uuid = a.user_uuid
            join hive.dwb_paimon.dwb_r_apply_result_extend e on r.id = e.apply_result_id
        """
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("worker log start\n")
            handle.write(source_sql)
            log_path = handle.name
        try:
            rows, meta = module.score_instance_matches(
                source_sql,
                [
                    {
                        "project_name": "菲律宾数仓-正式环境",
                        "workflow_name": "DWD_PAIMON-20260713133552354",
                        "task_name": "dwd_app_ask_loan_result",
                        "task_type": "SHELL",
                        "instance_start_time": "2026-07-13 13:38:50",
                        "instance_log_path": log_path,
                    }
                ],
                log_limit=1,
            )
        finally:
            os.unlink(log_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_name"], "dwd_app_ask_loan_result")
        self.assertEqual(rows[0]["ds_match_confidence"], "high")
        self.assertTrue(meta["temporary_target_mode"])

    def test_remote_ds_instance_fallback_rejects_quality_check_for_write_sql_without_write_log(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        source_sql = """
            update dwd.dwd_asset_main
               set etl_update_time = current_timestamp
              from hive.dwb_paimon.dwb_r2_asset t
             where dwd.dwd_asset_main.asset_id = t.asset_id
        """
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("select count(*) from dwd.dwd_asset_main where dt = current_date\n")
            handle.write("select count(*) from hive.dwb_paimon.dwb_r2_asset where dt = current_date\n")
            log_path = handle.name
        try:
            rows, meta = module.score_instance_matches(
                source_sql,
                [
                    {
                        "project_name": "菲律宾数仓-数据质量",
                        "workflow_name": "每12小时校验2级表数据(D-1)",
                        "task_name": "DWD层数据校验",
                        "task_type": "SHELL",
                        "instance_start_time": "2026-07-14 10:00:00",
                        "instance_log_path": log_path,
                    }
                ],
                log_limit=1,
            )
        finally:
            os.unlink(log_path)

        self.assertEqual(rows, [])
        self.assertEqual(meta["match_info"], "no-match")
        self.assertTrue(meta["instance_match_candidates"][0]["quality_check_task"])

    def test_remote_ds_instance_fallback_never_accepts_quality_check_tasks(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        source_sql = "insert into ads.ads_user_stat select * from dwd.dwd_w_user"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(source_sql)
            log_path = handle.name
        try:
            rows, meta = module.score_instance_matches(
                source_sql,
                [
                    {
                        "project_name": "菲律宾数仓-数据质量",
                        "workflow_name": "每12小时校验2级表数据(D-1)",
                        "task_name": "ADS层数据校验",
                        "task_type": "SHELL",
                        "instance_start_time": "2026-07-14 10:00:00",
                        "instance_log_path": log_path,
                    }
                ],
                log_limit=1,
            )
        finally:
            os.unlink(log_path)

        self.assertEqual(rows, [])
        self.assertEqual(meta["match_info"], "no-match")
        self.assertTrue(meta["instance_match_candidates"][0]["quality_check_task"])
        self.assertEqual(meta["instance_match_candidates"][0]["confidence"], "low")

    def test_remote_ds_recent_instance_query_uses_time_window_without_name_prefilter(self):
        script_path = Path(__file__).resolve().parents[1] / "remote_scripts" / "ds_match_candidate_query.py"
        spec = importlib.util.spec_from_file_location("ds_match_candidate_query", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["ds_match_candidate_query"] = module
        spec.loader.exec_module(module)

        captured = {}

        def fake_query_mysql_rows(connection, sql, timeout=180):
            captured["sql"] = sql
            captured["timeout"] = timeout
            return []

        original_query = module.query_mysql_rows
        module.query_mysql_rows = fake_query_mysql_rows
        try:
            _, meta = module.query_recent_instances(
                module.MysqlConnection("host", "3306", "db", "user", "pwd"),
                "insert into dwd.dwd_asset_main select * from hive.dwb_paimon.dwb_r2_asset",
                alert_time="2026-07-14 10:05:00",
                before_minutes=30,
                after_minutes=5,
                limit=50,
            )
        finally:
            module.query_mysql_rows = original_query

        sql = captured["sql"]
        self.assertIn("ti.start_time <= '2026-07-14 10:10:00'", sql)
        self.assertIn("ti.end_time IS NULL OR ti.end_time >= '2026-07-14 09:35:00'", sql)
        self.assertIn("TIMESTAMPDIFF(SECOND, ti.start_time, '2026-07-14 10:05:00')", sql)
        self.assertNotIn("LOWER(ti.name) LIKE", sql)
        self.assertEqual(meta["instance_query_mode"], "time_window_then_log_scoring")

    def test_sql_fingerprint_masks_literals(self):
        left = build_sql_fingerprint("select * from t where dt = '2026-07-01' and user_id = 123")
        right = build_sql_fingerprint("select * from t where dt = '2026-07-02' and user_id = 456")
        self.assertEqual(left.fingerprint, right.fingerprint)

    def test_project_owner_wins(self):
        index = build_project_owner_index([{"项目名称": "API首贷监控", "所属用户": "xubozhang"}])
        result = resolve_ds_task_owner({"项目名称": "API首贷监控", "所属用户": "admin"}, index)
        self.assertEqual(result.owner, "xubozhang")
        self.assertEqual(result.status, "resolved")

    def test_system_accounts_become_pending(self):
        result = resolve_ds_task_owner(
            {"项目名称": "DW_DM", "所属用户": "deploy", "创建用户": "deploy", "修改用户": "admin"},
            {},
        )
        self.assertEqual(result.status, "pending")
        self.assertTrue(result.need_manual_confirm)

    def test_mexico_aifox_special_group_wins(self):
        result = resolve_special_group(
            cluster="starrocks_mex",
            account="e_ds_aifox",
            departments=["唯渡"],
            contacts=["杜艳华"],
            emails=["elsadu@weidu.co"],
        )
        self.assertEqual(result["channel"], "mexico_aifox_group")

    def test_a_level_for_repeated_history(self):
        level = classify_governance_level({"cluster": "starrocks_mex", "history_alert_count": 5})
        self.assertEqual(level.level, "A")

    def test_abnormal_sql_score_combines_history_and_resource_risk(self):
        score = score_abnormal_sql(
            {
                "cluster": "starrocks_mex",
                "source_type": "ds",
                "alert_count": 2,
                "history_alert_count": 3,
                "max_mem_usage": 55 * 1024**3,
                "max_scan_rows": 2_000_000_000,
                "owner_name": "owner",
                "killed": "false",
            }
        )
        self.assertEqual(score.level, "A")
        self.assertGreaterEqual(score.score, 70)
        self.assertIn("历史同指纹告警次数", score.reason)

    def test_abnormal_sql_score_keeps_single_low_risk_as_d(self):
        score = score_abnormal_sql(
            {
                "cluster": "starrocks_mex",
                "source_type": "superset",
                "alert_count": 1,
                "history_alert_count": 0,
                "max_mem_usage": 10 * 1024**3,
                "killed": "false",
            }
        )
        self.assertEqual(score.level, "D")
        self.assertEqual(score.score, 0)

    def test_abnormal_sql_score_treats_false_string_as_false(self):
        score = score_abnormal_sql(
            {
                "cluster": "starrocks_mex",
                "source_type": "ds",
                "alert_count": 1,
                "history_alert_count": 0,
                "killed": "false",
            }
        )
        self.assertNotEqual(score.level, "A")

    def test_csv_false_killed_is_not_truthy(self):
        rows = [
            {
                "country": "th",
                "cluster": "starrocks_th",
                "source_type": "DS",
                "user": "e_ds_dim",
                "query_id": "q1",
                "raw_sql": "select count(*) from t where dt = '2026-07-01'",
                "mem_usage": "1000",
                "killed": "false",
            }
        ]
        records = aggregate_abnormal_sql(rows)
        self.assertFalse(records[0]["killed"])
        self.assertNotEqual(records[0]["governance_level"], "A")

    def test_upsert_merges_same_fingerprint(self):
        existing = [
            {
                "country": "mx",
                "cluster": "starrocks_mex",
                "source_type": "ds",
                "query_user": "e_ds_aifox",
                "sql_fingerprint": "fp1",
                "alert_count": 2,
                "first_alert_time": "2026-07-01 10:00:00",
                "last_alert_time": "2026-07-01 11:00:00",
                "max_mem_usage": 10,
            }
        ]
        incoming = [
            {
                "country": "mx",
                "cluster": "starrocks_mex",
                "source_type": "ds",
                "query_user": "e_ds_aifox",
                "sql_fingerprint": "fp1",
                "alert_count": 1,
                "first_alert_time": "2026-07-02 10:00:00",
                "last_alert_time": "2026-07-02 11:00:00",
                "max_mem_usage": 20,
            }
        ]
        result = upsert_governance_records(existing, incoming)
        self.assertEqual(result[0]["alert_count"], 3)
        self.assertEqual(result[0]["first_alert_time"], "2026-07-01 10:00:00")
        self.assertEqual(result[0]["last_alert_time"], "2026-07-02 11:00:00")
        self.assertEqual(result[0]["max_mem_usage"], 20)

    def test_weekly_pipeline_outputs_real_tables(self):
        result = run_weekly_governance(
            project_owner_rows=[{"项目名称": "API首贷监控", "所属用户": "xubozhang"}],
            task_metadata_rows=[
                {
                    "项目名称": "API首贷监控",
                    "所属用户": "admin",
                    "工作流名称": "api_monitor",
                    "任务名": "api_first_loan",
                    "创建用户": "admin",
                    "修改用户": "admin",
                }
            ],
            abnormal_sql_rows=[
                {
                    "country": "mx",
                    "cluster": "starrocks_mex",
                    "source_type": "DS",
                    "user": "e_ds_aifox",
                    "query_id": "q1",
                    "raw_sql": "select * from t where dt = '2026-07-01'",
                    "mem_usage": str(80 * 1024**3),
                    "killed": "true",
                    "alert_time": "2026-07-21 10:00:00",
                    "ds_project": "API首贷监控",
                    "ds_workflow": "api_monitor",
                    "ds_task": "api_first_loan",
                }
            ],
            existing_governance_rows=[],
            governance_week="2026-W30",
        )
        self.assertEqual(len(result["ds_task_owner_resolved"]), 1)
        self.assertEqual(len(result["abnormal_sql_governance_weekly"]), 1)
        self.assertEqual(len(result["ds_task_match_results"]), 1)
        record = result["abnormal_sql_governance_weekly"][0]
        self.assertEqual(record["governance_level"], "A")
        self.assertEqual(record["notify_route"], "mexico_aifox_group")
        self.assertEqual(len(result["notify_candidates"]), 1)
        self.assertEqual(len(result["abnormal_sql_governance_form"]), 1)

    def test_ds_task_matcher_finds_task_by_sql_fingerprint(self):
        match = match_ds_task(
            {
                "query_id": "q1",
                "raw_sql": "select * from fox_ods.ods_fox_chat_event_log where date(create_at) >= date('2025-08-02') and user_id = 456",
            },
            [
                {
                    "项目名称": "API首贷监控",
                    "工作流名称": "api_monitor",
                    "任务名": "api_first_loan",
                    "script_content": "select * from fox_ods.ods_fox_chat_event_log where date(create_at) >= date('2025-08-01') and user_id = 123",
                }
            ],
        )
        self.assertEqual(match.status, "matched")
        self.assertEqual(match.project_name, "API首贷监控")
        self.assertEqual(match.workflow_name, "api_monitor")
        self.assertEqual(match.task_name, "api_first_loan")

    def test_shell_resource_content_can_be_matched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            resource = root / "starrocks_workflow" / "api" / "api_first_loan.sql"
            resource.parent.mkdir(parents=True)
            resource.write_text(
                "select * from fox_ods.ods_fox_chat_event_log where date(create_at) >= date('2025-08-01')",
                encoding="utf-8",
            )

            task = enrich_task_row_with_resources(
                {
                    "项目名称": "API首贷监控",
                    "工作流名称": "api_monitor",
                    "任务名": "api_first_loan",
                    "任务类型": "SHELL",
                    "script": "sh dolphinscheduler/resource/deploy/resources/starrocks_workflow/api/api_first_loan.sql",
                },
                [root],
            )
            match = match_ds_task(
                {
                    "query_id": "q1",
                    "raw_sql": "select * from fox_ods.ods_fox_chat_event_log where date(create_at) >= date('2025-08-02')",
                },
                [task],
            )
            self.assertEqual(task["resource_resolve_status"], "resolved")
            self.assertEqual(match.status, "matched")
            self.assertEqual(match.task_name, "api_first_loan")

    def test_extract_resource_refs_from_resource_list_json(self):
        refs = extract_resource_refs(
            {
                "资源列表": '[{"resourceName":"starrocks_workflow/dim/dim_feature_dic.sql"}]',
                "script": "bash dim_feature_dic.sh",
            }
        )
        self.assertIn("starrocks_workflow/dim/dim_feature_dic.sql", refs)
        self.assertIn("dim_feature_dic.sh", refs)

    def test_ds_task_matcher_outputs_pending_when_no_script_hit(self):
        enriched, matches, pending = enrich_abnormal_rows_with_ds_task(
            [{"query_id": "q1", "raw_sql": "select * from unknown_table"}],
            [{"项目名称": "DW", "工作流名称": "wf", "任务名": "task", "script_content": "select * from known_table"}],
        )
        self.assertEqual(enriched[0]["ds_task_match_status"], "pending")
        self.assertEqual(matches[0]["match_status"], "pending")
        self.assertEqual(len(pending), 1)

    def test_ds_metadata_sql_contains_required_tables_and_script_content(self):
        sql = build_ds_task_metadata_sql(country="mx", project_name="API首贷监控")
        self.assertIn("t_ds_project", sql)
        self.assertIn("t_ds_workflow_definition", sql)
        self.assertIn("t_ds_workflow_task_relation", sql)
        self.assertIn("t_ds_task_definition", sql)
        self.assertIn("script_content", sql)
        self.assertIn("'mx'", sql)
        self.assertIn("'API首贷监控'", sql)

    def test_quote_sql_literal_escapes_single_quote(self):
        self.assertEqual(quote_sql_literal("a'b"), "'a''b'")

    def test_feedback_updates_governance_record(self):
        records = [{"governance_id": "g1", "owner_name": "old", "governance_status": "待认领"}]
        feedback = [
            {
                "governance_id": "g1",
                "actual_owner": "new_owner",
                "rectify_method": "优化SQL",
                "rectify_status": "处理中",
                "filled_by": "new_owner",
            }
        ]
        updated = apply_abnormal_sql_feedback(records, feedback)
        self.assertEqual(updated[0]["owner_name"], "new_owner")
        self.assertEqual(updated[0]["rectify_method"], "优化SQL")
        self.assertEqual(updated[0]["feedback_status"], "processed")

    def test_action_planner_builds_offline_candidate(self):
        action = plan_abnormal_sql_action(
            {"governance_id": "g1", "governance_week": "2026-W30"},
            {"can_offline_ds": "是", "actual_owner": "owner"},
        )
        self.assertEqual(action["action_type"], "offline_candidate")
        self.assertTrue(action["requires_second_confirm"])

    def test_action_planner_closes_when_csv_false_string(self):
        action = plan_abnormal_sql_action(
            {"governance_id": "g1", "governance_week": "2026-W30", "still_exists": "false", "is_overdue": "false"},
            {"rectify_status": "已整改", "actual_owner": "owner"},
        )
        self.assertEqual(action["action_type"], "close")

    def test_ds_zombie_action_planner_keeps_used_task(self):
        action = plan_ds_zombie_action(
            {"zombie_governance_id": "z1", "governance_week": "2026-W30"},
            {"still_in_use": "是"},
        )
        self.assertEqual(action["action_type"], "continue_observe")

    def test_ds_zombie_action_planner_handles_csv_true_string(self):
        action = plan_ds_zombie_action(
            {"zombie_governance_id": "z1", "governance_week": "2026-W30", "is_overdue": "true"},
            {},
        )
        self.assertEqual(action["action_type"], "escalate")

    def test_mexico_group_notification_payload_has_no_mentions(self):
        payload = build_notification_payload(
            {
                "governance_id": "g1",
                "governance_week": "2026-W30",
                "notify_channel": "group_bot",
                "notify_route": "mexico_aifox_group",
                "notify_bot_id": "e10c0656-a479-4053-a9cd-18b4d1fe4c87",
                "owner_email": "elsadu@weidu.co",
                "cluster": "starrocks_mex",
                "query_user": "e_ds_aifox",
            }
        )
        self.assertEqual(payload["botId"], "e10c0656-a479-4053-a9cd-18b4d1fe4c87")
        self.assertEqual(payload["mentions"], [])

    def test_sidecar_notification_payload_uses_owner_email(self):
        payload = build_notification_payload(
            {
                "governance_id": "g1",
                "governance_week": "2026-W30",
                "notify_channel": "sidecar",
                "owner_name": "xubozhang",
                "owner_email": "xubozhang@kn.group",
            }
        )
        self.assertEqual(payload["target_email"], "xubozhang@kn.group")
        self.assertIn("targetEmail", payload["payload_json"])


if __name__ == "__main__":
    unittest.main()

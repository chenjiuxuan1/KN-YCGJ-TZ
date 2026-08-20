import unittest

from governance_automation.ds_task_lineage import build_table_consumers, extract_task_table_evidence


class TaskLineageTests(unittest.TestCase):
    def test_extracts_write_and_read_tables_and_excludes_cte(self):
        evidence = extract_task_table_evidence(
            "WITH base AS (SELECT * FROM raw.orders) "
            "INSERT OVERWRITE dw.order_summary SELECT * FROM base JOIN dim.users u ON 1=1"
        )
        self.assertEqual(evidence.write_tables, ("dw.order_summary",))
        self.assertEqual(evidence.read_tables, ("dim.users", "raw.orders"))
        self.assertEqual(evidence.status, "available")

    def test_extracts_target_from_insert_overwrite_into_syntax(self):
        evidence = extract_task_table_evidence(
            "INSERT OVERWRITE INTO dw.order_summary SELECT * FROM raw.orders"
        )
        self.assertEqual(evidence.write_tables, ("dw.order_summary",))
        self.assertEqual(evidence.read_tables, ("raw.orders",))

    def test_does_not_treat_python_import_as_a_read_table(self):
        evidence = extract_task_table_evidence(
            "from pyhive import hive\n"
            "from collections import defaultdict\n"
            "INSERT INTO hive.temp.orders SELECT * FROM hive.raw.orders"
        )
        # catalog-prefixed names collapse to the last two segments so they can
        # match the same physical table written as db.table elsewhere.
        self.assertEqual(evidence.write_tables, ("temp.orders",))
        self.assertEqual(evidence.read_tables, ("raw.orders",))

    def test_backtick_and_catalog_prefixed_spellings_collapse_to_same_key(self):
        plain = extract_task_table_evidence(
            "SELECT * FROM dm_wd_efficiency.ai_case_repay_call_detail"
        )
        backtick = extract_task_table_evidence(
            "SELECT * FROM `dm_wd_efficiency`.`ai_case_repay_call_detail`"
        )
        catalog = extract_task_table_evidence(
            "SELECT * FROM catalog.dm_wd_efficiency.ai_case_repay_call_detail"
        )
        self.assertEqual(plain.read_tables, ("dm_wd_efficiency.ai_case_repay_call_detail",))
        self.assertEqual(backtick.read_tables, plain.read_tables)
        self.assertEqual(catalog.read_tables, plain.read_tables)

    def test_write_target_accepts_per_segment_backticks(self):
        evidence = extract_task_table_evidence(
            "INSERT OVERWRITE INTO `dm_wd_efficiency`.`ai_case_repay_call_detail` "
            "SELECT * FROM raw.orders"
        )
        self.assertEqual(evidence.write_tables, ("dm_wd_efficiency.ai_case_repay_call_detail",))
        self.assertEqual(evidence.read_tables, ("raw.orders",))

    def test_merged_writer_and_reader_reference_same_normalized_table(self):
        consumers = build_table_consumers([
            {
                "workflow_code": "writer", "project_name": "项目A", "workflow_name": "写入流程",
                "task_name": "写回收明细", "active": False,
                "sql": "INSERT INTO `dm_wd_efficiency`.`ai_case_repay_call_detail` SELECT * FROM raw.orders",
            },
            {
                "workflow_code": "reader", "project_name": "项目B", "workflow_name": "消费流程",
                "task_name": "读回收明细", "active": True,
                "sql": "SELECT * FROM catalog.dm_wd_efficiency.ai_case_repay_call_detail",
            },
        ])
        self.assertIn("dm_wd_efficiency.ai_case_repay_call_detail", consumers)
        self.assertTrue(consumers["dm_wd_efficiency.ai_case_repay_call_detail"][0]["active"])

    def test_dynamic_script_is_incomplete_not_empty(self):
        evidence = extract_task_table_evidence("spark.sql(sql_text)")
        self.assertEqual(evidence.status, "incomplete")
        self.assertEqual(evidence.write_tables, ())

    def test_extracts_resource_references_without_returning_sql(self):
        evidence = extract_task_table_evidence(
            "", {"resourceList": [{"fullName": "/etl/load_orders.sql"}]}
        )
        self.assertEqual(evidence.resource_refs, ("/etl/load_orders.sql",))

    def test_active_reader_becomes_high_confidence_consumer(self):
        consumers = build_table_consumers([
            {"workflow_code": "writer", "project_name": "项目A", "workflow_name": "写入流程", "task_name": "写订单", "active": False, "sql": "insert into dw.orders select * from raw.orders"},
            {"workflow_code": "reader", "project_name": "项目B", "workflow_name": "消费流程", "task_name": "读订单", "active": True, "sql": "select * from dw.orders"},
        ])
        self.assertEqual(consumers["dw.orders"][0]["task_name"], "读订单")
        self.assertTrue(consumers["dw.orders"][0]["active"])


if __name__ == "__main__":
    unittest.main()

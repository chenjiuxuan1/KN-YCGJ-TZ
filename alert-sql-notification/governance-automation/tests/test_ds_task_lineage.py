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
        self.assertEqual(evidence.write_tables, ("hive.temp.orders",))
        self.assertEqual(evidence.read_tables, ("hive.raw.orders",))

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

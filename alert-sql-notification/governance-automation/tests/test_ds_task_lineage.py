import unittest

from governance_automation.ds_task_lineage import extract_task_table_evidence


class TaskLineageTests(unittest.TestCase):
    def test_extracts_write_and_read_tables_and_excludes_cte(self):
        evidence = extract_task_table_evidence(
            "WITH base AS (SELECT * FROM raw.orders) "
            "INSERT OVERWRITE dw.order_summary SELECT * FROM base JOIN dim.users u ON 1=1"
        )
        self.assertEqual(evidence.write_tables, ("dw.order_summary",))
        self.assertEqual(evidence.read_tables, ("dim.users", "raw.orders"))
        self.assertEqual(evidence.status, "available")

    def test_dynamic_script_is_incomplete_not_empty(self):
        evidence = extract_task_table_evidence("spark.sql(sql_text)")
        self.assertEqual(evidence.status, "incomplete")
        self.assertEqual(evidence.write_tables, ())

    def test_extracts_resource_references_without_returning_sql(self):
        evidence = extract_task_table_evidence(
            "", {"resourceList": [{"fullName": "/etl/load_orders.sql"}]}
        )
        self.assertEqual(evidence.resource_refs, ("/etl/load_orders.sql",))


if __name__ == "__main__":
    unittest.main()

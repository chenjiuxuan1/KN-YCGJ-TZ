"""Read-only DolphinScheduler metadata query used by the zombie scanner."""

from typing import Any, Dict, List, Optional

from .ds_metadata_exporter import query_mysql_records, quote_sql_literal


def build_scan_sql(
    *, country: str, lookback_days: int = 30, project_name: str = "",
    workflow_name: str = "", task_name: str = ""
) -> str:
    """Return one read-only query whose rows contain workflow, task and run evidence."""
    days = max(1, min(int(lookback_days), 365))
    is_legacy_process_schema = country == "ph"
    definition_table = "t_ds_process_definition" if is_legacy_process_schema else "t_ds_workflow_definition"
    relation_table = "t_ds_process_task_relation" if is_legacy_process_schema else "t_ds_workflow_task_relation"
    instance_table = "t_ds_process_instance" if is_legacy_process_schema else "t_ds_workflow_instance"
    definition_code_column = "process_definition_code" if is_legacy_process_schema else "workflow_definition_code"
    definition_version_column = "process_definition_version" if is_legacy_process_schema else "workflow_definition_version"
    return f"""
SELECT {quote_sql_literal(country)} AS country,
       p.code AS project_code, p.name AS project_name,
       wd.code AS workflow_code, wd.name AS workflow_name,
       wd.release_state AS workflow_online, wd.update_time AS last_update_time,
       u.user_name AS owner_name,
       rel.pre_task_code, rel.post_task_code,
       td.code AS task_code, td.name AS task_name, td.task_type, td.task_params,
       COALESCE(ss.schedule_online, 0) AS schedule_online,
       ist.last_run_time, ist.last_success_time, ist.last_failure_time,
       COALESCE(ist.total_runs_30d, 0) AS total_runs_30d,
       COALESCE(ist.failed_runs_30d, 0) AS failed_runs_30d
FROM t_ds_project p
JOIN {definition_table} wd ON wd.project_code = p.code
LEFT JOIN t_ds_user u ON u.id = wd.user_id
LEFT JOIN {relation_table} rel
  ON rel.project_code = wd.project_code
 AND rel.{definition_code_column} = wd.code
 AND rel.{definition_version_column} = wd.version
LEFT JOIN t_ds_task_definition td
  ON td.project_code = rel.project_code
 AND td.code = rel.post_task_code
 AND td.version = rel.post_task_version
LEFT JOIN (
  SELECT {definition_code_column} AS workflow_code,
         MAX(start_time) AS last_run_time,
         MAX(CASE WHEN state = 7 THEN end_time END) AS last_success_time,
         MAX(CASE WHEN state IN (6,9) THEN end_time END) AS last_failure_time,
         SUM(start_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)) AS total_runs_30d,
         SUM(start_time >= DATE_SUB(NOW(), INTERVAL {days} DAY) AND state IN (6,9)) AS failed_runs_30d
  FROM {instance_table}
  GROUP BY {definition_code_column}
) ist ON ist.workflow_code = wd.code
LEFT JOIN (
  SELECT {definition_code_column} AS workflow_code,
         MAX(CASE WHEN release_state = 1 THEN 1 ELSE 0 END) AS schedule_online
  FROM t_ds_schedules
  GROUP BY {definition_code_column}
) ss ON ss.workflow_code = wd.code
WHERE ({quote_sql_literal(project_name or None)} IS NULL OR p.name = {quote_sql_literal(project_name or None)})
  AND ({quote_sql_literal(workflow_name or None)} IS NULL OR wd.name = {quote_sql_literal(workflow_name or None)})
  AND ({quote_sql_literal(task_name or None)} IS NULL OR td.name = {quote_sql_literal(task_name or None)})
ORDER BY wd.code, td.code
""".strip()


class DsZombieRepository:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def fetch_scan_rows(self, **filters: Any) -> List[Dict[str, Any]]:
        sql = build_scan_sql(**filters)
        return query_mysql_records(sql=sql, **self.config)

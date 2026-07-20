"""Read-only DolphinScheduler metadata query used by the zombie scanner."""

from typing import Any, Dict, List, Optional

from .ds_metadata_exporter import query_mysql_records, quote_sql_literal


def build_scan_sql(
    *, country: str, lookback_days: int = 30, project_name: str = "",
    workflow_name: str = "", task_name: str = ""
) -> str:
    """Return one read-only query whose rows contain workflow, task and run evidence."""
    days = max(1, min(int(lookback_days), 365))
    return f"""
SELECT {quote_sql_literal(country)} AS country,
       p.code AS project_code, p.name AS project_name,
       wd.code AS workflow_code, wd.name AS workflow_name,
       wd.release_state AS workflow_online, wd.update_time AS last_update_time,
       u.user_name AS owner_name,
       rel.pre_task_code, rel.post_task_code,
       td.code AS task_code, td.name AS task_name, td.task_type, td.task_params,
       COALESCE(ss.schedule_online, 0) AS schedule_online,
       COALESCE(ss.schedule_active, 0) AS schedule_active,
       ist.last_run_time, ist.last_success_time, ist.last_failure_time,
       COALESCE(ist.total_runs_30d, 0) AS total_runs_30d,
       COALESCE(ist.failed_runs_30d, 0) AS failed_runs_30d,
       COALESCE(ist.active_instance_present, 0) AS active_instance_present
FROM t_ds_project p
JOIN t_ds_workflow_definition wd ON wd.project_code = p.code
LEFT JOIN t_ds_user u ON u.id = wd.user_id
LEFT JOIN t_ds_workflow_task_relation rel
  ON rel.project_code = wd.project_code
 AND rel.workflow_definition_code = wd.code
 AND rel.workflow_definition_version = wd.version
LEFT JOIN t_ds_task_definition td
  ON td.project_code = rel.project_code
 AND td.code = rel.post_task_code
 AND td.version = rel.post_task_version
LEFT JOIN (
  SELECT workflow_definition_code AS workflow_code,
         MAX(start_time) AS last_run_time,
         MAX(CASE WHEN state = 7 THEN end_time END) AS last_success_time,
         MAX(CASE WHEN state IN (6,9) THEN end_time END) AS last_failure_time,
         SUM(start_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)) AS total_runs_30d,
         SUM(start_time >= DATE_SUB(NOW(), INTERVAL {days} DAY) AND state IN (6,9)) AS failed_runs_30d,
         MAX(CASE WHEN state IN (0,1,2,4,8,10,11) THEN 1 ELSE 0 END) AS active_instance_present
  FROM t_ds_workflow_instance
  GROUP BY workflow_definition_code
) ist ON ist.workflow_code = wd.code
LEFT JOIN (
  SELECT workflow_definition_code AS workflow_code,
         MAX(CASE WHEN release_state = 1 THEN 1 ELSE 0 END) AS schedule_online,
         MAX(CASE WHEN release_state = 1
                       AND start_time <= NOW()
                       AND end_time >= NOW() THEN 1 ELSE 0 END) AS schedule_active
  FROM t_ds_schedules
  GROUP BY workflow_definition_code
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

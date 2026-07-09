"""Export DolphinScheduler task metadata used by abnormal SQL matching."""

from __future__ import annotations

import os
from typing import Any


DS_TASK_METADATA_SQL = """
SELECT
  %(country_literal)s AS country,
  p.name AS `项目名称`,
  COALESCE(project_owner.user_name, '') AS `所属用户`,
  p.create_time AS `项目创建时间`,
  p.update_time AS `项目更新时间`,
  pd.name AS `工作流名称`,
  pd.release_state AS `工作流状态`,
  COALESCE(workflow_owner.user_name, '') AS `创建用户`,
  COALESCE(workflow_owner.user_name, '') AS `修改用户`,
  pd.create_time AS `工作流创建时间`,
  pd.update_time AS `工作流更新时间`,
  td.name AS `任务名`,
  td.task_type AS `任务类型`,
  td.flag AS `任务上下线状态`,
  td.task_params AS `task_params`,
  CONCAT_WS(
    '\\n',
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.rawScript')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.sql')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.script')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.statement')), 'null')
  ) AS `script_content`,
  NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.datasource')), 'null') AS `数据源`,
  NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.datasourceName')), 'null') AS `数据源名称`,
  NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.resourceList')), 'null') AS `资源列表`
FROM t_ds_project p
JOIN t_ds_workflow_definition pd
  ON pd.project_code = p.code
LEFT JOIN t_ds_user project_owner
  ON project_owner.id = p.user_id
LEFT JOIN t_ds_user workflow_owner
  ON workflow_owner.id = pd.user_id
JOIN t_ds_workflow_task_relation rel
  ON rel.project_code = pd.project_code
 AND rel.workflow_definition_code = pd.code
 AND rel.workflow_definition_version = pd.version
JOIN t_ds_task_definition td
  ON td.project_code = rel.project_code
 AND td.code = rel.post_task_code
 AND td.version = rel.post_task_version
WHERE 1 = 1
  AND (%(project_name_filter)s IS NULL OR p.name = %(project_name_filter)s)
  AND (%(workflow_name_filter)s IS NULL OR pd.name = %(workflow_name_filter)s)
  AND (%(task_name_filter)s IS NULL OR td.name = %(task_name_filter)s)
ORDER BY p.name, pd.name, td.name
""".strip()


def quote_sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def build_ds_task_metadata_sql(
    *,
    country: str,
    project_name: str | None = None,
    workflow_name: str | None = None,
    task_name: str | None = None,
) -> str:
    return DS_TASK_METADATA_SQL % {
        "country_literal": quote_sql_literal(country),
        "project_name_filter": quote_sql_literal(project_name),
        "workflow_name_filter": quote_sql_literal(workflow_name),
        "task_name_filter": quote_sql_literal(task_name),
    }


def read_mysql_config_from_env(prefix: str = "DS_DB") -> dict[str, Any]:
    return {
        "host": os.getenv(f"{prefix}_HOST", ""),
        "port": int(os.getenv(f"{prefix}_PORT", "3306")),
        "user": os.getenv(f"{prefix}_USER", ""),
        "password": os.getenv(f"{prefix}_PASSWORD", ""),
        "database": os.getenv(f"{prefix}_DATABASE", ""),
        "charset": os.getenv(f"{prefix}_CHARSET", "utf8mb4"),
    }


def query_mysql_records(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sql: str,
    charset: str = "utf8mb4",
) -> list[dict[str, Any]]:
    try:
        import pymysql
    except ImportError as error:
        raise RuntimeError("缺少 pymysql，请先安装 pymysql，或只使用 --print-sql 导出 SQL 后在数据库中执行。") from error

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset=charset,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()

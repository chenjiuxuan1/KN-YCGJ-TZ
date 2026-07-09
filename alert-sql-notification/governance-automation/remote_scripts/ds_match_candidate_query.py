#!/usr/bin/env python3
"""Query DolphinScheduler task candidates for abnormal SQL matching.

This script is designed to run on each country jump host or DS host. It discovers
the actual DolphinScheduler metadata MySQL connection from the running Java
process environment instead of trusting static application.yaml files.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


COUNTRY_BY_CLUSTER = {
    "starrocks_cn": "cn",
    "starrocks_ine": "ine",
    "starrocks_id": "ine",
    "starrocks_mex": "mx",
    "starrocks_mx": "mx",
    "starrocks_pak": "pk",
    "starrocks_pk": "pk",
    "starrocks_ph": "ph",
    "starrocks_th": "th",
}

VALID_COUNTRIES = {"cn", "ine", "mx", "ph", "pk", "th"}


DS_COUNTRY_CONFIG = {
    "cn": {
        "host": "rm-uf60p909s1lpp1urp.mysql.rds.aliyuncs.com",
        "port": "3306",
        "database": "cn_dolphin",
        "user": "cn_dolphin",
        "password_env": "CN_DS_DB_PASSWORD",
    },
    "ine": {
        "host": "192.168.25.249",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "INE_DS_DB_PASSWORD",
    },
    "mx": {
        "host": "rm-2ev5479nuworkbb0x.mysql.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "MX_DS_DB_PASSWORD",
    },
    "ph": {
        "host": "10.20.81.11",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "a_dolphinscheduler",
        "password_env": "PH_DS_DB_PASSWORD",
    },
    "pk": {
        "host": "rm-gs5zsdzr5kr0sh70p.mysql.singapore.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "PK_DS_DB_PASSWORD",
    },
    "th": {
        "host": "rm-gs533qw7xj1e7wdp7.mysql.singapore.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "a_dolphinscheduler",
        "password_env": "TH_DS_DB_PASSWORD",
    },
}


SCRIPT_CONTENT_EXPR = r"""CONCAT_WS(
    '\n',
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.rawScript')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.sql')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.script')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.statement')), 'null'),
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(td.task_params, '$.resourceList')), 'null')
  )"""


DS_TASK_CANDIDATE_SQL_TEMPLATE = r"""
SELECT
  p.name AS project_name,
  COALESCE(project_owner.user_name, '') AS project_owner,
  wd.code AS workflow_code,
  wd.version AS workflow_version,
  wd.name AS workflow_name,
  wd.release_state AS workflow_release_state,
  COALESCE(workflow_owner.user_name, '') AS workflow_owner,
  td.code AS task_code,
  td.version AS task_version,
  td.name AS task_name,
  td.task_type AS task_type,
  td.flag AS task_flag,
  COALESCE(task_owner.user_name, workflow_owner.user_name, '') AS task_creator,
  {script_content_expr} AS script_content,
  {script_content_expr} AS sql_content
FROM t_ds_project p
JOIN t_ds_workflow_definition wd
  ON wd.project_code = p.code
JOIN t_ds_workflow_task_relation rel
  ON rel.project_code = wd.project_code
 AND rel.workflow_definition_code = wd.code
 AND rel.workflow_definition_version = wd.version
JOIN t_ds_task_definition td
  ON td.project_code = rel.project_code
 AND td.code = rel.post_task_code
 AND td.version = rel.post_task_version
LEFT JOIN t_ds_user project_owner
  ON project_owner.id = p.user_id
LEFT JOIN t_ds_user workflow_owner
  ON workflow_owner.id = wd.user_id
LEFT JOIN t_ds_user task_owner
  ON task_owner.id = td.user_id
WHERE {script_content_expr} IS NOT NULL
  {script_filter_sql}
ORDER BY p.name, wd.name, td.name
LIMIT {limit}
""".strip()


TABLE_RE = re.compile(r"\b(?:from|join|into|overwrite|update|table)\s+([`\"]?[a-zA-Z_][\w.]*)", re.I)
ACTION_RE = re.compile(r"\b(create|insert|update|delete|replace|alter|drop|truncate)\b", re.I)
CTE_RE = re.compile(r"(?:\bwith|,)\s+([a-zA-Z_][\w]*)\s+as\s*\(", re.I)
INSERT_TARGET_RE = re.compile(r"\binsert\s+(?:overwrite\s+)?(?:into\s+)?(?:table\s+)?([`\"]?[a-zA-Z_][\w.]*)", re.I)
CREATE_TARGET_RE = re.compile(r"\bcreate\s+(?:table\s+)?(?:if\s+not\s+exists\s+)?([`\"]?[a-zA-Z_][\w.]*)", re.I)
UPDATE_TARGET_RE = re.compile(r"\bupdate\s+([`\"]?[a-zA-Z_][\w.]*)", re.I)
NON_TABLE = {"select", "table", "values", "if", "exists", "as", "where"}


@dataclass(frozen=True)
class MysqlConnection:
    host: str
    port: str
    database: str
    user: str
    password: str


def normalize_country(country: str = "", cluster: str = "") -> str:
    country_value = str(country or "").strip().lower()
    if country_value == "id":
        country_value = "ine"
    if country_value in VALID_COUNTRIES:
        return country_value

    cluster_value = str(cluster or "").strip().lower()
    if cluster_value in COUNTRY_BY_CLUSTER:
        return COUNTRY_BY_CLUSTER[cluster_value]
    if "mex" in cluster_value or "mx" in cluster_value:
        return "mx"
    if "ine" in cluster_value or "indo" in cluster_value or "id" in cluster_value:
        return "ine"
    if "pak" in cluster_value or "pk" in cluster_value:
        return "pk"
    if "ph" in cluster_value:
        return "ph"
    if "th" in cluster_value:
        return "th"
    if "cn" in cluster_value or "china" in cluster_value:
        return "cn"
    return ""


def run_command(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 120) -> str:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(message)
    return result.stdout


def find_ds_pid() -> str:
    output = run_command(["ps", "-ef"])
    candidates: list[tuple[int, str]] = []
    for line in output.splitlines():
        lower = line.lower()
        if "java" not in lower or "dolphinscheduler" not in lower:
            continue
        parts = line.split()
        if len(parts) <= 1 or not parts[1].isdigit():
            continue
        score = 0
        if "api" in lower:
            score += 30
        if "master" in lower:
            score += 20
        if "server" in lower:
            score += 10
        candidates.append((score, parts[1]))
    if not candidates:
        raise RuntimeError("DS_PROCESS_NOT_FOUND")
    candidates.sort(reverse=True)
    return candidates[0][1]


def read_process_env(pid: str) -> dict[str, str]:
    with open(f"/proc/{pid}/environ", "rb") as handle:
        raw = handle.read().decode("utf-8", errors="ignore")
    env: dict[str, str] = {}
    for item in raw.split("\0"):
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    return env


def pick_env(env: dict[str, str], *patterns: str) -> str:
    for key, value in env.items():
        upper = key.upper()
        if value and all(pattern in upper for pattern in patterns):
            return value
    return ""


def parse_mysql_jdbc_url(url: str) -> tuple[str, str, str]:
    match = re.search(r"jdbc:mysql://([^:/?]+)(?::(\d+))?/([^?]+)", url or "")
    if not match:
        raise RuntimeError("SPRING_DATASOURCE_URL_NOT_FOUND_OR_UNSUPPORTED")
    return match.group(1), match.group(2) or "3306", match.group(3)


def configured_ds_mysql_connection(country: str) -> MysqlConnection | None:
    config = DS_COUNTRY_CONFIG.get(country)
    if not config:
        return None
    password_env = str(config.get("password_env", ""))
    password = os.environ.get(password_env, "")
    if not password:
        return None
    return MysqlConnection(
        host=str(config["host"]),
        port=str(config["port"]),
        database=str(config["database"]),
        user=str(config["user"]),
        password=password,
    )


def discover_ds_mysql_connection(args: argparse.Namespace, env: dict[str, str]) -> MysqlConnection:
    explicit = MysqlConnection(
        host=args.ds_db_host or os.environ.get("DS_DB_HOST", ""),
        port=args.ds_db_port or os.environ.get("DS_DB_PORT", "3306"),
        database=args.ds_db_name or os.environ.get("DS_DB_NAME", ""),
        user=args.ds_db_user or os.environ.get("DS_DB_USER", ""),
        password=args.ds_db_password or os.environ.get("DS_DB_PASSWORD", ""),
    )
    if explicit.host and explicit.database and explicit.user and explicit.password:
        return explicit

    configured = configured_ds_mysql_connection(normalize_country(args.country, args.cluster))
    if configured:
        return configured

    url = (
        env.get("SPRING_DATASOURCE_URL")
        or env.get("SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL")
        or pick_env(env, "SPRING", "DATASOURCE", "URL")
    )
    host, port, database = parse_mysql_jdbc_url(url)
    user = (
        env.get("SPRING_DATASOURCE_USERNAME")
        or env.get("SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_USERNAME")
        or pick_env(env, "SPRING", "DATASOURCE", "USERNAME")
    )
    password = (
        env.get("SPRING_DATASOURCE_PASSWORD")
        or env.get("SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_PASSWORD")
        or pick_env(env, "SPRING", "DATASOURCE", "PASSWORD")
    )
    if not user or not password:
        raise RuntimeError("SPRING_DATASOURCE_USERNAME_OR_PASSWORD_NOT_FOUND")
    return MysqlConnection(host=host, port=port, database=database, user=user, password=password)


def discover_wattrel_connection(args: argparse.Namespace) -> MysqlConnection | None:
    host = args.wattrel_host or os.environ.get("WATTREL_DB_HOST") or os.environ.get("DB_HOST", "")
    port = args.wattrel_port or os.environ.get("WATTREL_DB_PORT") or os.environ.get("DB_PORT", "3306")
    database = args.wattrel_db or os.environ.get("WATTREL_DB_NAME") or os.environ.get("DB_NAME", "")
    user = args.wattrel_user or os.environ.get("WATTREL_DB_USER") or os.environ.get("DB_USER", "")
    password = args.wattrel_password or os.environ.get("WATTREL_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
    if not any([host, database, user, password]):
        return None
    if not all([host, database, user, password]):
        raise RuntimeError("WATTREL_DB_CONFIG_INCOMPLETE")
    return MysqlConnection(host=host, port=port, database=database, user=user, password=password)


def query_mysql_rows(connection: MysqlConnection, sql: str) -> list[dict[str, str]]:
    env = os.environ.copy()
    env["MYSQL_PWD"] = connection.password
    raw = run_command(
        [
            "mysql",
            "-h" + connection.host,
            "-P" + connection.port,
            "-u" + connection.user,
            "--default-character-set=utf8mb4",
            "--batch",
            "--raw",
            connection.database,
            "-e",
            sql,
        ],
        env=env,
        timeout=180,
    )
    reader = csv.DictReader(raw.splitlines(), delimiter="\t")
    return [dict(row) for row in reader]


def decode_base64_text(value: str) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value.encode("utf-8"), validate=False).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def normalize_sql_text(sql: str) -> str:
    text = str(sql or "")
    text = re.sub(r"--[^\n]*", " ", text)
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    return " ".join(text.lower().split())


def extract_sql_tables(sql: str) -> list[str]:
    normalized = normalize_sql_text(sql)
    cte_names = {match.group(1).lower() for match in CTE_RE.finditer(normalized)}
    tables: list[str] = []
    seen: set[str] = set()
    for match in TABLE_RE.finditer(normalized):
        table = str(match.group(1) or "").strip("`\"").lower()
        if not table or table in NON_TABLE or table in cte_names:
            continue
        if table not in seen:
            seen.add(table)
            tables.append(table)
    # Prefer fully-qualified names first; they are much more selective.
    tables.sort(key=lambda value: (0 if "." in value else 1, len(value)))
    return tables


def extract_action_tables(sql: str) -> tuple[str, list[str]]:
    normalized = normalize_sql_text(sql)
    if not normalized:
        return "", []
    action_match = ACTION_RE.search(normalized)
    action = action_match.group(1).lower() if action_match else normalized.split(" ", 1)[0].lower()
    return action, extract_sql_tables(normalized)


def extract_target_tables(sql: str) -> list[str]:
    normalized = normalize_sql_text(sql)
    targets: list[str] = []
    seen: set[str] = set()
    for pattern in (INSERT_TARGET_RE, CREATE_TARGET_RE, UPDATE_TARGET_RE):
        for match in pattern.finditer(normalized):
            table = str(match.group(1) or "").strip("`\"").lower()
            if not table or table in NON_TABLE or table in seen:
                continue
            seen.add(table)
            targets.append(table)
    return targets


def is_subset(left: list[str], right: list[str]) -> bool:
    right_set = set(right)
    return all(item in right_set for item in left)


def same_set(left: list[str], right: list[str]) -> bool:
    return len(left) == len(right) and is_subset(left, right)


def table_leaf(table: str) -> str:
    return str(table or "").split(".")[-1]


def normalize_name_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def target_task_name_matches(targets: list[str], task_name: str) -> bool:
    """Return true only when the task name is the target table name itself.

    Derived task names such as ``dwt_user_behavior_base_snap_hot_mv`` should not
    be treated as an exact owner for target table ``dwt_user_behavior_base_snap``.
    Those are usually materialized views or helper jobs and create false DS
    ownership matches.
    """
    task_token = normalize_name_token(task_name)
    if not task_token:
        return False
    for target in targets:
        full_token = normalize_name_token(target)
        leaf_token = normalize_name_token(table_leaf(target))
        if task_token in {full_token, leaf_token}:
            return True
    return False


def table_matches(left: str, right: str) -> bool:
    left_value = str(left or "").lower()
    right_value = str(right or "").lower()
    if not left_value or not right_value:
        return False
    return left_value == right_value or table_leaf(left_value) == table_leaf(right_value)


def count_table_overlap(left: list[str], right: list[str]) -> int:
    matched_right: set[int] = set()
    count = 0
    for left_table in left:
        for index, right_table in enumerate(right):
            if index in matched_right:
                continue
            if table_matches(left_table, right_table):
                matched_right.add(index)
                count += 1
                break
    return count


def candidate_sql(row: dict[str, str]) -> str:
    return str(
        row.get("sql_content")
        or row.get("script_content")
        or row.get("raw_script")
        or row.get("sql_text")
        or row.get("script_text")
        or row.get("statement_text")
        or row.get("resource_list")
        or ""
    )


def pick_best_match(source_sql: str, rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    source_action, source_tables = extract_action_tables(source_sql)
    source_targets = extract_target_tables(source_sql)
    meta: dict[str, Any] = {
        "match_mode": "remote_weighted_target_table",
        "source_action": source_action,
        "source_target_tables": source_targets,
        "source_tables": source_tables,
        "raw_candidate_count": len(rows),
        "match_info": "no-match",
    }
    if not source_action or not source_tables:
        meta["match_info"] = "no-action-or-table"
        return [], meta

    exact: list[tuple[dict[str, str], list[str]]] = []
    superset: list[tuple[dict[str, str], list[str]]] = []
    scored: list[tuple[float, dict[str, str], list[str], dict[str, Any]]] = []
    for row in rows:
        row_action, row_tables = extract_action_tables(candidate_sql(row))
        target_overlap = count_table_overlap(source_targets, row_tables)
        table_overlap = count_table_overlap(source_tables, row_tables)
        action_match = row_action == source_action
        task_name_match = target_task_name_matches(source_targets, str(row.get("task_name", "")))
        score = (
            (3000 if task_name_match else 0)
            + (1000 if target_overlap else 0)
            + (200 if action_match else 0)
            + (table_overlap * 10)
        )
        if target_overlap and row_action and not action_match:
            score -= 80
        score_meta = {
            "row_action": row_action,
            "row_tables": row_tables,
            "task_name_match": task_name_match,
            "target_overlap": target_overlap,
            "table_overlap": table_overlap,
            "score": score,
        }
        if task_name_match or target_overlap or table_overlap >= 3:
            scored.append((score, row, row_tables, score_meta))

        if row_action != source_action or not is_subset(source_tables, row_tables):
            continue
        if same_set(source_tables, row_tables):
            exact.append((row, row_tables))
        else:
            superset.append((row, row_tables))

    if exact:
        best, tables = exact[0]
        best["ds_match_remote_info"] = f"exact({len(exact)})"
        best["ds_match_confidence"] = "high"
        meta["match_info"] = best["ds_match_remote_info"]
        meta["confidence"] = "high"
        meta["matched_tables"] = tables
        return [best], meta

    if superset:
        superset.sort(key=lambda item: len([table for table in item[1] if table not in source_tables]))
        best, tables = superset[0]
        extra = len([table for table in tables if table not in source_tables])
        best["ds_match_remote_info"] = f"superset(+{extra})"
        best["ds_match_confidence"] = "high"
        meta["match_info"] = best["ds_match_remote_info"]
        meta["confidence"] = "high"
        meta["matched_tables"] = tables
        return [best], meta

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best, tables, score_meta = scored[0]
        confidence = "medium" if (score_meta["task_name_match"] or score_meta["target_overlap"]) else "low"
        if score_meta["task_name_match"]:
            confidence = "high"
        elif score_meta["target_overlap"] and score_meta["table_overlap"] >= 5 and score_meta["row_action"] == source_action:
            confidence = "high"
        best["ds_match_remote_info"] = (
            f"scored(score={int(best_score)},taskName={int(score_meta['task_name_match'])},target={score_meta['target_overlap']},tables={score_meta['table_overlap']})"
        )
        best["ds_match_confidence"] = confidence
        meta["match_info"] = best["ds_match_remote_info"]
        meta["confidence"] = confidence
        meta["matched_tables"] = tables
        meta["matched_table_overlap"] = score_meta["table_overlap"]
        meta["matched_target_overlap"] = score_meta["target_overlap"]
        meta["matched_task_name"] = bool(score_meta["task_name_match"])
        return [best], meta

    return [], meta


def build_script_filter_sql(source_sql: str, max_terms: int = 12) -> tuple[str, list[str]]:
    targets = extract_target_tables(source_sql)
    tables = extract_sql_tables(source_sql)
    if not tables:
        return "", []
    terms: list[str] = []
    for table in targets + tables:
        if table not in terms:
            terms.append(table)
    terms = terms[:max_terms]
    lowered_script = "LOWER(" + SCRIPT_CONTENT_EXPR + ")"
    like_parts = []
    for table in terms:
        # table tokens come from a restrictive regex, but keep SQL escaping anyway.
        escaped = table.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
        like_parts.append(f"{lowered_script} LIKE '%{escaped}%' ESCAPE '\\\\'")
    return "AND (" + "\n    OR ".join(like_parts) + ")", terms


def success_response(
    country: str,
    pid: str,
    connection: MysqlConnection,
    rows: list[dict[str, str]],
    wattrel_connection: MysqlConnection | None = None,
    filter_tables: list[str] | None = None,
    match_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ds_pid": pid,
        "mysql_host": connection.host,
        "mysql_port": connection.port,
        "mysql_database": connection.database,
        "mysql_user": connection.user,
        "wattrel_configured": bool(wattrel_connection),
        "filter_tables": filter_tables or [],
    }
    if match_meta:
        meta.update(match_meta)
    if wattrel_connection:
        meta["wattrel_host"] = wattrel_connection.host
        meta["wattrel_port"] = wattrel_connection.port
        meta["wattrel_database"] = wattrel_connection.database
        meta["wattrel_user"] = wattrel_connection.user
    return {
        "success": True,
        "country": country,
        "candidate_count": len(rows),
        "data": rows,
        "meta": meta,
        "error": None,
    }


def error_response(country: str, error: Exception) -> dict[str, Any]:
    return {
        "success": False,
        "country": country,
        "candidate_count": 0,
        "data": [],
        "meta": {},
        "error": {
            "code": "DS_MATCH_CANDIDATE_QUERY_FAILED",
            "message": str(error),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query DS task candidates for abnormal SQL matching.")
    parser.add_argument("--country", default="", help="Country code: cn, ine, mx, ph, pk, th.")
    parser.add_argument("--cluster", default="", help="StarRocks cluster, used to infer country when country is empty.")
    parser.add_argument("--limit", type=int, default=3000, help="Max DS task candidates to return.")
    parser.add_argument("--sql-text-b64", default="", help="Base64-encoded abnormal SQL text for DB-side filtering.")
    parser.add_argument("--ds-db-host", default="", help="Optional DS metadata MySQL host override.")
    parser.add_argument("--ds-db-port", default="", help="Optional DS metadata MySQL port override.")
    parser.add_argument("--ds-db-user", default="", help="Optional DS metadata MySQL user override.")
    parser.add_argument("--ds-db-password", default="", help="Optional DS metadata MySQL password override.")
    parser.add_argument("--ds-db-name", default="", help="Optional DS metadata MySQL database override.")
    parser.add_argument("--wattrel-host", default="", help="Optional wattrel MySQL host.")
    parser.add_argument("--wattrel-port", default="", help="Optional wattrel MySQL port.")
    parser.add_argument("--wattrel-user", default="", help="Optional wattrel MySQL user.")
    parser.add_argument("--wattrel-password", default="", help="Optional wattrel MySQL password.")
    parser.add_argument("--wattrel-db", default="", help="Optional wattrel MySQL database name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    country = normalize_country(args.country, args.cluster)
    if not country:
        print(json.dumps(error_response("", RuntimeError("INVALID_COUNTRY_OR_CLUSTER")), ensure_ascii=False))
        return
    try:
        pid = ""
        env: dict[str, str] = {}
        configured = configured_ds_mysql_connection(country)
        if configured:
            connection = configured
        else:
            pid = find_ds_pid()
            env = read_process_env(pid)
            connection = discover_ds_mysql_connection(args, env)
        wattrel_connection = discover_wattrel_connection(args)
        source_sql = decode_base64_text(args.sql_text_b64)
        script_filter_sql, filter_tables = build_script_filter_sql(source_sql)
        sql = DS_TASK_CANDIDATE_SQL_TEMPLATE.format(
            limit=max(1, int(args.limit)),
            script_content_expr=SCRIPT_CONTENT_EXPR,
            script_filter_sql=script_filter_sql,
        )
        rows = query_mysql_rows(connection, sql)
        rows, match_meta = pick_best_match(source_sql, rows) if source_sql else (rows[:1], {})
        print(
            json.dumps(
                success_response(country, pid, connection, rows, wattrel_connection, filter_tables, match_meta),
                ensure_ascii=False,
            )
        )
    except Exception as error:
        print(json.dumps(error_response(country, error), ensure_ascii=False))


if __name__ == "__main__":
    main()

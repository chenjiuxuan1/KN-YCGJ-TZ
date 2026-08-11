#!/usr/bin/env python3
"""Gated resource-release actions for data governance.

Supported actions:
  - freeze_table:      StarRocks D11-style Rename freeze (no Drop).
  - disable_ds_task:   Offline a DolphinScheduler task via its OpenAPI (guarded).

Safety rules (mirror governance principles, 误删除容忍度 0):
  - Requires --confirm-token equal to env GOVERNANCE_CONFIRM_TOKEN.
  - Defaults to --dry-run; real actions only run when --no-dry-run AND token matches.
  - Never drops / deletes. Disable/freeze only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.ds_metadata_exporter import query_mysql_records, read_mysql_config_from_env

VALID_COUNTRIES = ("cn", "ph", "ine", "mx", "th", "pk")
VALID_ACTIONS = ("disable_ds_task", "freeze_table")


def confirm_token_from_env() -> str:
    return str(os.getenv("GOVERNANCE_CONFIRM_TOKEN", "")).strip()


def safe_identifier(value: str) -> str:
    return str(value or "").strip().replace("`", "")


def build_freeze_sql(table_schema: str, table_name: str, batch_id: str) -> list[str]:
    schema = safe_identifier(table_schema)
    table = safe_identifier(table_name)
    if not schema or not table:
        raise ValueError("freeze_table 需要 table_schema 与 table_name")
    frozen = f"disabled_{date.today().strftime('%Y%m%d')}_{table}"
    start_table = f"governance.gov_sr_zombie_detail_{batch_id}_start"
    return [
        f"ALTER TABLE `{schema}`.`{table}` RENAME `{frozen}`",
        (
            f"UPDATE {start_table}\n"
            f"SET status = '已冻结', process_status = '备份完成',\n"
            f"    frozen_table_name = '{frozen}', freeze_at = NOW(), updated_at = NOW()\n"
            f"WHERE table_schema = '{schema}' AND table_name = '{table}'"
        ),
    ]


def run_starrocks(sqls: list[str], db_prefix: str) -> int:
    config = read_mysql_config_from_env(db_prefix)
    if not config["host"] or not config["user"]:
        raise RuntimeError(f"缺少 {db_prefix}_HOST / {db_prefix}_USER 环境变量，无法连接 StarRocks")
    import pymysql
    connection = pymysql.connect(
        host=config["host"], port=config["port"], user=config["user"],
        password=config["password"], database=config["database"] or "governance",
        charset=config.get("charset", "utf8mb4"),
    )
    try:
        affected = 0
        with connection.cursor() as cursor:
            for sql in sqls:
                cursor.execute(sql)
                affected += cursor.rowcount
        connection.commit()
        return affected
    finally:
        connection.close()


def disable_ds_task(args) -> dict:
    base = str(os.getenv("DS_API_BASE", "")).strip().rstrip("/")
    token = str(os.getenv("DS_API_TOKEN", "")).strip()
    if not base or not token:
        return {"code": "DS_API_NOT_CONFIGURED",
                "message": "未配置 DS_API_BASE/DS_API_TOKEN，无法执行 disable_ds_task"}
    if not args.project_code or not args.workflow_code or not args.task_name:
        return {"code": "DS_DISABLE_MISSING_ARGS",
                "message": "disable_ds_task 需要 project_code/workflow_code/task_name"}
    url = f"{base}/dolphinscheduler/projects/{args.project_code}/process-definition/{args.workflow_code}/offline"
    body = json.dumps({"name": args.task_name}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "token": token})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:1000]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gated resource release; stdout is a bounded JSON summary."
    )
    parser.add_argument("--country", required=True, choices=VALID_COUNTRIES)
    parser.add_argument("--action", required=True, choices=VALID_ACTIONS)
    parser.add_argument("--batch-id", default=date.today().strftime("%Y%m"))
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--project-code", default="")
    parser.add_argument("--workflow-code", default="")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--table-schema", default="")
    parser.add_argument("--table-name", default="")
    parser.add_argument("--db-prefix", default="SR")
    parser.add_argument("--no-dry-run", action="store_true")
    args = parser.parse_args()

    def payload(**extra):
        base = {"success": False, "country": args.country, "action": args.action,
                "batch_id": args.batch_id, "dry_run": not args.no_dry_run}
        base.update(extra)
        return base

    token = str(args.confirm_token or "").strip()
    if not token or token != confirm_token_from_env():
        print(json.dumps(payload(error={"code": "RELEASE_CONFIRM_REJECTED",
                                        "message": "confirm_token 缺失或不匹配，拒绝执行写操作"}),
                         ensure_ascii=False, separators=(",", ":")))
        return 1

    try:
        if args.action == "freeze_table":
            sqls = build_freeze_sql(args.table_schema, args.table_name, args.batch_id)
            if args.no_dry_run:
                affected = run_starrocks(sqls, args.db_prefix)
                result = {"affected": affected}
            else:
                result = {"sqls": sqls}
            print(json.dumps({**payload(), "success": True, "result": result},
                             ensure_ascii=False, separators=(",", ":")))
            return 0
        if args.action == "disable_ds_task":
            if args.no_dry_run:
                result = disable_ds_task(args)
            else:
                result = {"dry_run": True, "would_offline": {
                    "project_code": args.project_code, "workflow_code": args.workflow_code,
                    "task_name": args.task_name}}
            print(json.dumps({**payload(), "success": True, "result": result},
                             ensure_ascii=False, separators=(",", ":")))
            return 0
    except Exception as exc:  # noqa: BLE001 - remote script reports bounded error payload
        print(json.dumps(payload(error={"code": "RELEASE_FAILED", "message": str(exc)[:500]}),
                         ensure_ascii=False, separators=(",", ":")))
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

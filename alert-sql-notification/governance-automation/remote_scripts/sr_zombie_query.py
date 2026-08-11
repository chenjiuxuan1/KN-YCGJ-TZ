#!/usr/bin/env python3
"""Read-only StarRocks zombie table governance queries.

Query the governance.gov_sr_zombie_detail_* / whitelist tables for the D1
candidate identification flow.  This script only issues SELECT / SHOW / count
statements; it never renames, backs up, or drops tables.  Table and column
references follow 僵尸表自动化流程操作文档.md.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.ds_metadata_exporter import (
    query_mysql_records,
    read_mysql_config_from_env,
)

VALID_COUNTRIES = ("cn", "ph", "ine", "mx", "th", "pk")
VALID_OPERATIONS = ("query_candidates", "query_detail_all", "query_whitelist", "validate")
BATCH_RE = re.compile(r"^\d{6}$")
SYSTEM_SCHEMAS = ("information_schema", "mysql", "sys", "_statistics_", "starrocks_audit_db__", "governance")


def as_bool(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "是")


def sanitize_batch_id(batch_id: str) -> str:
    value = str(batch_id or "").strip()
    if not value:
        return date.today().strftime("%Y%m")
    if not BATCH_RE.match(value):
        raise ValueError("batch_id 必须为 yyyyMM 格式（如 202606）")
    return value


def build_sql(operation: str, batch_id: str, min_size_gb: float, limit: int) -> str:
    batch = sanitize_batch_id(batch_id)
    start_table = f"governance.gov_sr_zombie_detail_{batch}_start"
    end_table = f"governance.gov_sr_zombie_detail_{batch}_end"
    if operation == "query_candidates":
        return (
            f"SELECT table_schema, table_name, table_rows, size_gb, pv_30d, uv_30d, "
            f"status, process_status, biz_decision\n"
            f"FROM {start_table}\n"
            f"WHERE size_gb >= {float(min_size_gb)}\n"
            f"ORDER BY size_gb DESC\n"
            f"LIMIT {int(limit)}"
        )
    if operation == "query_detail_all":
        return (
            f"SELECT batch_id, table_schema, table_name, table_rows, size_gb, pv_30d, uv_30d, "
            f"status, process_status, biz_decision, owner, non_offline_reason, remark\n"
            f"FROM governance.gov_sr_zombie_detail_all\n"
            f"WHERE batch_id = '{batch}'\n"
            f"ORDER BY size_gb DESC\n"
            f"LIMIT {int(limit)}"
        )
    if operation == "query_whitelist":
        return (
            f"SELECT table_schema, table_name, reason, source, owner, created_at\n"
            f"FROM governance.gov_sr_zombie_whitelist\n"
            f"ORDER BY updated_at DESC\n"
            f"LIMIT {int(limit)}"
        )
    if operation == "validate":
        return (
            f"SELECT "
            f"(SELECT COUNT(*) FROM {start_table}) AS start_cnt, "
            f"(SELECT COUNT(*) FROM {end_table}) AS end_cnt"
        )
    raise ValueError(f"不支持的 operation: {operation}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only StarRocks zombie table query; stdout is a bounded JSON summary."
    )
    parser.add_argument("--country", required=True, choices=VALID_COUNTRIES)
    parser.add_argument("--operation", choices=VALID_OPERATIONS, default="query_candidates")
    parser.add_argument("--batch-id", default="", help="治理批次 yyyyMM，缺省当月")
    parser.add_argument("--min-size-gb", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--db-prefix", default="SR", help="环境变量前缀（SR => SR_HOST/SR_PORT/...）")
    parser.add_argument("--dry-run", action="store_true", help="只打印 SQL，不连接数据库")
    args = parser.parse_args()

    try:
        sql = build_sql(args.operation, args.batch_id, args.min_size_gb, args.limit)
    except ValueError as exc:
        print(json.dumps({"success": False, "country": args.country, "operation": args.operation,
                          "error": {"code": "SR_ZOMBIE_QUERY_BAD_REQUEST", "message": str(exc)[:300]}},
                         ensure_ascii=False, separators=(",", ":")))
        return 1

    if args.dry_run:
        payload = {"success": True, "country": args.country, "operation": args.operation,
                   "batch_id": sanitize_batch_id(args.batch_id), "dry_run": True, "sql": sql, "rows": []}
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0

    try:
        config = read_mysql_config_from_env(args.db_prefix)
        if not config["host"] or not config["user"]:
            raise RuntimeError(f"缺少 {args.db_prefix}_HOST / {args.db_prefix}_USER 环境变量，无法连接 StarRocks")
        rows = query_mysql_records(
            host=config["host"], port=config["port"], user=config["user"],
            password=config["password"], database=config["database"] or "governance",
            sql=sql, charset=config.get("charset", "utf8mb4"),
        )
        payload = {"success": True, "country": args.country, "operation": args.operation,
                   "batch_id": sanitize_batch_id(args.batch_id), "row_count": len(rows),
                   "rows": rows[:args.limit]}
    except Exception as exc:  # noqa: BLE001 - remote script reports bounded error payload
        payload = {"success": False, "country": args.country, "operation": args.operation,
                   "error": {"code": "SR_ZOMBIE_QUERY_FAILED", "message": str(exc)[:500]}}
    print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

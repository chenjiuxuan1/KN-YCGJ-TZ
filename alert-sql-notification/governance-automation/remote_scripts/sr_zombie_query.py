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
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VALID_COUNTRIES = ("cn", "ph", "ine", "mx", "th", "pk")
VALID_OPERATIONS = ("query_candidates", "query_detail_all", "query_whitelist", "validate")
BATCH_RE = re.compile(r"^\d{6}$")
SYSTEM_SCHEMAS = ("information_schema", "mysql", "sys", "_statistics_", "starrocks_audit_db__", "_starrocks_audit_db_", "governance")
DEFAULT_BASE_URL = "http://172.20.0.234:4888"
COUNTRY_GATEWAY_MAP = {"cn": "cn", "ine": "id", "mx": "mx", "ph": "ph", "pk": "pk", "th": "th"}


def gateway_execute(base_url, token, country, sql, page_size=100, timeout_sec=60):
    url = base_url.rstrip("/") + "/api/rust/v1/sr-sandboxes/sql-executions"
    payload = {
        "taskName": "governance-zombie-table-query",
        "country": country,
        "purpose": "agent",
        "accessMode": "local",
        "sqlMode": "query",
        "sql": sql,
        "page": 1,
        "pageSize": page_size,
        "timeoutSec": timeout_sec,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"网关 HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接网关 {url}: {exc.reason}") from exc
    data = json.loads(text) if text else {}
    if not data.get("success"):
        raise RuntimeError("网关返回失败: " + str(data)[:500])
    return data.get("data", {})


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
    start_table = f"testdb.gov_sr_zombie_detail_{batch}_start"
    end_table = f"testdb.gov_sr_zombie_detail_{batch}_end"
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
            f"FROM testdb.gov_sr_zombie_detail_all\n"
            f"WHERE batch_id = '{batch}'\n"
            f"ORDER BY size_gb DESC\n"
            f"LIMIT {int(limit)}"
        )
    if operation == "query_whitelist":
        return (
            f"SELECT table_schema, table_name, reason, source, owner, created_at\n"
            f"FROM testdb.gov_sr_zombie_whitelist\n"
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




DETAIL_COLUMNS = (
    "batch_id VARCHAR(32)",
    "table_schema VARCHAR(256)",
    "table_name VARCHAR(256)",
    "table_rows BIGINT",
    "size_bytes BIGINT",
    "size_gb DOUBLE",
    "pv_30d BIGINT",
    "uv_30d BIGINT",
    "status VARCHAR(64)",
    "process_status VARCHAR(64)",
    "biz_decision VARCHAR(64)",
    "owner VARCHAR(256)",
    "non_offline_reason VARCHAR(1024)",
    "remark VARCHAR(1024)",
    "frozen_table_name VARCHAR(256)",
    "freeze_at DATETIME",
    "backup_snapshot VARCHAR(1024)",
    "backup_at DATETIME",
    "action_error VARCHAR(1024)",
    "created_at DATETIME",
    "updated_at DATETIME",
)


def ensure_governance_tables(base_url, token, gw_country, batch_id):
    """CREATE TABLE IF NOT EXISTS the zombie governance tables in testdb."""
    cols = ", ".join(DETAIL_COLUMNS)
    batch = sanitize_batch_id(batch_id)
    statements = [
        f"CREATE TABLE IF NOT EXISTS testdb.gov_sr_zombie_detail_{batch}_start ({cols})",
        f"CREATE TABLE IF NOT EXISTS testdb.gov_sr_zombie_detail_{batch}_end ({cols})",
        f"CREATE TABLE IF NOT EXISTS testdb.gov_sr_zombie_detail_all ({cols})",
        "CREATE TABLE IF NOT EXISTS testdb.gov_sr_zombie_whitelist (table_schema VARCHAR(256), table_name VARCHAR(256), reason VARCHAR(1024), source VARCHAR(256), owner VARCHAR(256), created_at DATETIME, updated_at DATETIME)",
    ]
    for statement in statements:
        gateway_execute(base_url, token, gw_country, statement, page_size=1, timeout_sec=60)

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
    parser.add_argument("--token", default="", help="Fuxi Gateway token；缺省读 FUXI_API_TOKEN")
    parser.add_argument("--base-url", default="", help="Fuxi Gateway 地址；缺省读 FUXI_BASE_URL")
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
        token = (args.token or os.environ.get("FUXI_API_TOKEN", "")).strip()
        if not token:
            raise RuntimeError("缺少 FUXI_API_TOKEN / --token，无法调用 Fuxi Gateway")
        base_url = (args.base_url or os.environ.get("FUXI_BASE_URL", "")).strip().rstrip("/") or DEFAULT_BASE_URL
        gw_country = COUNTRY_GATEWAY_MAP.get(args.country, args.country)
        data = gateway_execute(
            base_url, token, gw_country, sql,
            page_size=max(int(args.limit), 1),
        )
        rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
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

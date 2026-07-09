#!/usr/bin/env python3
"""Export DS task metadata from DolphinScheduler metadata database."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.ds_metadata_exporter import (
    build_ds_task_metadata_sql,
    query_mysql_records,
    read_mysql_config_from_env,
)
from governance_automation.io_utils import write_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Export DolphinScheduler task metadata.")
    parser.add_argument("--country", required=True, help="Country code, e.g. cn/ine/mx/ph/pk/th.")
    parser.add_argument("--host", default="", help="DS metadata MySQL host. Can use DS_DB_HOST env.")
    parser.add_argument("--port", type=int, default=0, help="DS metadata MySQL port. Can use DS_DB_PORT env.")
    parser.add_argument("--user", default="", help="DS metadata MySQL user. Can use DS_DB_USER env.")
    parser.add_argument("--password", default="", help="DS metadata MySQL password. Can use DS_DB_PASSWORD env.")
    parser.add_argument("--database", default="", help="DS metadata MySQL database. Can use DS_DB_DATABASE env.")
    parser.add_argument("--project-name", default="", help="Optional DS project filter.")
    parser.add_argument("--workflow-name", default="", help="Optional DS workflow filter.")
    parser.add_argument("--task-name", default="", help="Optional DS task filter.")
    parser.add_argument("--output", default="", help="CSV/JSON output path.")
    parser.add_argument("--print-sql", action="store_true", help="Only print SQL and do not connect to MySQL.")
    args = parser.parse_args()

    sql = build_ds_task_metadata_sql(
        country=args.country,
        project_name=args.project_name or None,
        workflow_name=args.workflow_name or None,
        task_name=args.task_name or None,
    )
    if args.print_sql:
        print(sql)
        return

    env_config = read_mysql_config_from_env()
    config = {
        "host": args.host or env_config["host"],
        "port": args.port or env_config["port"],
        "user": args.user or env_config["user"],
        "password": args.password or env_config["password"],
        "database": args.database or env_config["database"],
        "charset": env_config["charset"],
    }
    missing = [key for key in ("host", "user", "password", "database") if not config[key]]
    if missing:
        raise SystemExit("缺少 DS 元数据库连接信息：" + ", ".join(missing) + "。可先使用 --print-sql。")
    if not args.output:
        raise SystemExit("缺少 --output。")

    rows = query_mysql_records(sql=sql, **config)
    write_records(args.output, rows)
    print(f"exported ds task metadata rows: {len(rows)}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()

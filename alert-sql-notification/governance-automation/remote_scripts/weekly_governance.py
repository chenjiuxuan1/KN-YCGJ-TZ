#!/usr/bin/env python3
"""Weekly abnormal-SQL governance remote wrapper.

Reuses the first-version weekly pipeline (governance_automation.pipeline).
Input data (project owners / DS task metadata / abnormal SQL rows) must be
provided as CSV/JSON files; when any is missing this script returns a clean
JSON error instead of crashing.  --window-start / --window-end follow the
OpenAPI contract.  This wrapper never writes to any DB; it only writes output
CSV files when --output-dir is provided and --dry-run is not set.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.io_utils import read_records, write_records
from governance_automation.pipeline import run_weekly_governance

VALID_COUNTRIES = ("cn", "ph", "ine", "mx", "th", "pk")
REQUIRED_DATA_FILES = ("project-owners", "ds-task-metadata", "abnormal-sql")


def default_week_start() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def week_from_window_start(window_start: str) -> str:
    value = str(window_start or "").strip()
    try:
        parsed = datetime.fromisoformat(value).date() if value else date.today()
    except ValueError:
        parsed = date.today()
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly abnormal-SQL governance; stdout is a bounded JSON summary."
    )
    parser.add_argument("--country", required=True, choices=VALID_COUNTRIES)
    parser.add_argument("--window-start", default="", help="yyyy-MM-dd，缺省本周一")
    parser.add_argument("--window-end", default="", help="yyyy-MM-dd，缺省今天")
    parser.add_argument("--governance-week", default="", help="e.g. 2026-W30；缺省由 window-start 推导")
    parser.add_argument("--project-owners", default="", help="CSV/JSON project owner mapping.")
    parser.add_argument("--ds-task-metadata", default="", help="CSV/JSON DS task metadata.")
    parser.add_argument("--abnormal-sql", default="", help="CSV/JSON abnormal SQL rows.")
    parser.add_argument("--existing-governance", default="", help="Optional existing governance table.")
    parser.add_argument("--output-dir", default="", help="Optional dir to write output CSV files.")
    parser.add_argument("--top-n", type=int, default=50, help="Bounded sample rows in summary.")
    parser.add_argument("--dry-run", action="store_true", help="不写输出文件，只返回摘要")
    args = parser.parse_args()

    window_start = str(args.window_start or default_week_start())
    window_end = str(args.window_end or date.today().isoformat())
    governance_week = str(args.governance_week or week_from_window_start(window_start))

    missing = [flag for flag in REQUIRED_DATA_FILES if not getattr(args, flag.replace("-", "_"))]
    if missing:
        payload = {
            "success": False, "country": args.country,
            "governance_week": governance_week, "window_start": window_start, "window_end": window_end,
            "error": {"code": "WEEKLY_GOVERNANCE_NO_DATA",
                      "message": f"缺少数据文件：{', '.join(missing)}；请由 n8n 聚合后以文件传入"},
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 1

    try:
        existing = read_records(args.existing_governance) if args.existing_governance else []
        result = run_weekly_governance(
            project_owner_rows=read_records(args.project_owners),
            task_metadata_rows=read_records(args.ds_task_metadata),
            abnormal_sql_rows=read_records(args.abnormal_sql),
            existing_governance_rows=existing,
            governance_week=governance_week,
        )
        if args.output_dir and not args.dry_run:
            out = Path(args.output_dir)
            for name in ("ds_task_owner_resolved", "ds_owner_pending_confirm", "ds_task_match_results",
                         "ds_task_match_pending", "abnormal_sql_governance_weekly",
                         "abnormal_sql_governance_form", "notify_candidates"):
                write_records(out / f"{name}.csv", result[name])
        summary = {
            "success": True,
            "country": args.country,
            "governance_week": governance_week,
            "window_start": window_start,
            "window_end": window_end,
            "dry_run": args.dry_run,
            "counts": {key: len(value) for key, value in result.items()},
            "samples": {key: value[:args.top_n] for key, value in result.items()},
        }
    except Exception as exc:  # noqa: BLE001 - remote script reports bounded error payload
        summary = {"success": False, "country": args.country,
                   "governance_week": governance_week,
                   "error": {"code": "WEEKLY_GOVERNANCE_FAILED", "message": str(exc)[:500]}}
    print(json.dumps(summary, ensure_ascii=False, default=str, separators=(",", ":")))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

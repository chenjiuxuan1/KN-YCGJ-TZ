#!/usr/bin/env python3
"""Weekly abnormal-SQL governance remote wrapper.

Reuses the first-version weekly pipeline (governance_automation.pipeline).
Inputs are provided as CSV/JSON files; stdout is a bounded JSON summary for
n8n.  This wrapper never writes to any DB; it only writes output CSV files
when --output-dir is provided (safe, additive).
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.io_utils import read_records, write_records
from governance_automation.pipeline import run_weekly_governance

VALID_COUNTRIES = ("cn", "ph", "ine", "mx", "th", "pk")


def default_week() -> str:
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly abnormal-SQL governance; stdout is a bounded JSON summary."
    )
    parser.add_argument("--country", required=True, choices=VALID_COUNTRIES)
    parser.add_argument("--project-owners", required=True, help="CSV/JSON project owner mapping.")
    parser.add_argument("--ds-task-metadata", required=True, help="CSV/JSON DS task metadata.")
    parser.add_argument("--abnormal-sql", required=True, help="CSV/JSON abnormal SQL rows.")
    parser.add_argument("--existing-governance", default="", help="Optional existing governance table.")
    parser.add_argument("--governance-week", default=default_week(), help="e.g. 2026-W30.")
    parser.add_argument("--output-dir", default="", help="Optional dir to write output CSV files (safe/additive).")
    parser.add_argument("--top-n", type=int, default=50, help="Bounded sample rows in summary.")
    args = parser.parse_args()

    def fail(payload):
        print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
        return 1

    try:
        existing = read_records(args.existing_governance) if args.existing_governance else []
        result = run_weekly_governance(
            project_owner_rows=read_records(args.project_owners),
            task_metadata_rows=read_records(args.ds_task_metadata),
            abnormal_sql_rows=read_records(args.abnormal_sql),
            existing_governance_rows=existing,
            governance_week=args.governance_week,
        )
        if args.output_dir:
            out = Path(args.output_dir)
            for name in ("ds_task_owner_resolved", "ds_owner_pending_confirm", "ds_task_match_results",
                         "ds_task_match_pending", "abnormal_sql_governance_weekly",
                         "abnormal_sql_governance_form", "notify_candidates"):
                write_records(out / f"{name}.csv", result[name])
        summary = {
            "success": True,
            "country": args.country,
            "governance_week": args.governance_week,
            "counts": {key: len(value) for key, value in result.items()},
            "samples": {key: value[:args.top_n] for key, value in result.items()},
        }
    except Exception as exc:  # noqa: BLE001 - remote script reports bounded error payload
        return fail({"success": False, "country": args.country,
                     "governance_week": args.governance_week,
                     "error": {"code": "WEEKLY_GOVERNANCE_FAILED", "message": str(exc)[:500]}})
    print(json.dumps(summary, ensure_ascii=False, default=str, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the first-version weekly abnormal SQL governance pipeline.

This is the concrete entrypoint for v1. It does not assume a specific data
source. Upstream systems only need to provide CSV/JSON files matching the
documented field contract.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.io_utils import read_records, write_records
from governance_automation.pipeline import run_weekly_governance


def default_week() -> str:
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run weekly abnormal SQL governance pipeline.")
    parser.add_argument("--project-owners", required=True, help="CSV/JSON project owner mapping.")
    parser.add_argument("--ds-task-metadata", required=True, help="CSV/JSON DS task metadata.")
    parser.add_argument("--abnormal-sql", required=True, help="CSV/JSON abnormal SQL rows.")
    parser.add_argument("--existing-governance", default="", help="Optional CSV/JSON existing governance table.")
    parser.add_argument("--output-dir", required=True, help="Directory for output CSV files.")
    parser.add_argument("--governance-week", default=default_week(), help="Governance week, e.g. 2026-W30.")
    args = parser.parse_args()

    existing_governance = read_records(args.existing_governance) if args.existing_governance else []
    result = run_weekly_governance(
        project_owner_rows=read_records(args.project_owners),
        task_metadata_rows=read_records(args.ds_task_metadata),
        abnormal_sql_rows=read_records(args.abnormal_sql),
        existing_governance_rows=existing_governance,
        governance_week=args.governance_week,
    )

    output_dir = Path(args.output_dir)
    write_records(output_dir / "ds_task_owner_resolved.csv", result["ds_task_owner_resolved"])
    write_records(output_dir / "ds_owner_pending_confirm.csv", result["ds_owner_pending_confirm"])
    write_records(output_dir / "ds_task_match_results.csv", result["ds_task_match_results"])
    write_records(output_dir / "ds_task_match_pending.csv", result["ds_task_match_pending"])
    write_records(output_dir / "abnormal_sql_governance_weekly.csv", result["abnormal_sql_governance_weekly"])
    write_records(output_dir / "abnormal_sql_governance_form.csv", result["abnormal_sql_governance_form"])
    write_records(output_dir / "notify_candidates.csv", result["notify_candidates"])

    print(f"wrote outputs to {output_dir}")
    print(f"resolved owners: {len(result['ds_task_owner_resolved'])}")
    print(f"pending owners: {len(result['ds_owner_pending_confirm'])}")
    print(f"ds task matches: {len(result['ds_task_match_results'])}")
    print(f"ds task match pending: {len(result['ds_task_match_pending'])}")
    print(f"governance records: {len(result['abnormal_sql_governance_weekly'])}")
    print(f"user confirmation rows: {len(result['abnormal_sql_governance_form'])}")
    print(f"notify candidates: {len(result['notify_candidates'])}")


if __name__ == "__main__":
    main()

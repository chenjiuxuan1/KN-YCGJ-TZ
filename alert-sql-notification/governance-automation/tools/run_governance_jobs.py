#!/usr/bin/env python3
"""Run first-version governance jobs in parallel when inputs are available."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.action_planner import plan_abnormal_sql_action, plan_ds_zombie_action
from governance_automation.feedback_ingest import apply_abnormal_sql_feedback, build_feedback_index
from governance_automation.io_utils import read_records, write_records
from governance_automation.pipeline import run_weekly_governance


@dataclass
class JobResult:
    name: str
    status: str
    outputs: list[str]
    summary: dict[str, int | str]


def default_week() -> str:
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def run_weekly_job(args: argparse.Namespace) -> JobResult:
    existing_governance = read_records(args.existing_governance) if args.existing_governance else []
    result = run_weekly_governance(
        project_owner_rows=read_records(args.project_owners),
        task_metadata_rows=read_records(args.ds_task_metadata),
        abnormal_sql_rows=read_records(args.abnormal_sql),
        existing_governance_rows=existing_governance,
        governance_week=args.governance_week,
    )

    output_dir = Path(args.output_dir)
    outputs = {
        "ds_task_owner_resolved": output_dir / "ds_task_owner_resolved.csv",
        "ds_owner_pending_confirm": output_dir / "ds_owner_pending_confirm.csv",
        "ds_task_match_results": output_dir / "ds_task_match_results.csv",
        "ds_task_match_pending": output_dir / "ds_task_match_pending.csv",
        "abnormal_sql_governance_weekly": output_dir / "abnormal_sql_governance_weekly.csv",
        "abnormal_sql_governance_form": output_dir / "abnormal_sql_governance_form.csv",
        "notify_candidates": output_dir / "notify_candidates.csv",
    }
    for key, path in outputs.items():
        write_records(path, result[key])

    return JobResult(
        name="weekly_abnormal_sql_governance",
        status="success",
        outputs=[str(path) for path in outputs.values()],
        summary={
            "resolved_owners": len(result["ds_task_owner_resolved"]),
            "pending_owners": len(result["ds_owner_pending_confirm"]),
            "ds_task_matches": len(result["ds_task_match_results"]),
            "ds_task_match_pending": len(result["ds_task_match_pending"]),
            "governance_records": len(result["abnormal_sql_governance_weekly"]),
            "confirmation_rows": len(result["abnormal_sql_governance_form"]),
            "notify_candidates": len(result["notify_candidates"]),
        },
    )


def run_abnormal_feedback_job(args: argparse.Namespace, governance_records_path: Path | None = None) -> JobResult:
    input_path = governance_records_path or Path(args.feedback_governance_records)
    feedback_rows = read_records(args.abnormal_feedback)
    governance_records = read_records(input_path)
    updated_records = apply_abnormal_sql_feedback(governance_records, feedback_rows)
    feedback_index = build_feedback_index(feedback_rows, "governance_id")

    now = datetime.now()
    action_candidates = []
    for record in updated_records:
        governance_id = str(record.get("governance_id") or "").strip()
        feedback = feedback_index.get(governance_id)
        if feedback:
            action_candidates.append(plan_abnormal_sql_action(record, feedback, now=now))

    output_dir = Path(args.output_dir)
    updated_path = output_dir / "abnormal_sql_governance_weekly_updated.csv"
    actions_path = output_dir / "governance_action_candidates.csv"
    write_records(updated_path, updated_records)
    write_records(actions_path, action_candidates)

    return JobResult(
        name="abnormal_sql_feedback",
        status="success",
        outputs=[str(updated_path), str(actions_path)],
        summary={
            "updated_governance_records": len(updated_records),
            "feedback_rows": len(feedback_rows),
            "action_candidates": len(action_candidates),
            "input_governance_records": str(input_path),
        },
    )


def row_key(row: dict[str, object]) -> str:
    return str(row.get("zombie_governance_id") or row.get("governance_id") or "").strip()


def run_ds_zombie_job(args: argparse.Namespace) -> JobResult:
    zombie_records = read_records(args.ds_zombie_records)
    feedback_rows = read_records(args.ds_zombie_feedback)
    feedback_index = {row_key(row): row for row in feedback_rows if row_key(row)}

    now = datetime.now()
    action_candidates = []
    for record in zombie_records:
        feedback = feedback_index.get(row_key(record))
        if feedback:
            action_candidates.append(plan_ds_zombie_action(record, feedback, now=now))

    output_dir = Path(args.output_dir)
    actions_path = output_dir / "ds_zombie_action_candidates.csv"
    write_records(actions_path, action_candidates)

    return JobResult(
        name="ds_zombie_actions",
        status="success",
        outputs=[str(actions_path)],
        summary={
            "zombie_records": len(zombie_records),
            "feedback_rows": len(feedback_rows),
            "action_candidates": len(action_candidates),
        },
    )


def has_weekly_inputs(args: argparse.Namespace) -> bool:
    return bool(args.project_owners and args.ds_task_metadata and args.abnormal_sql)


def has_ds_zombie_inputs(args: argparse.Namespace) -> bool:
    return bool(args.ds_zombie_records and args.ds_zombie_feedback)


def has_abnormal_feedback_inputs(args: argparse.Namespace) -> bool:
    return bool(args.abnormal_feedback and (args.feedback_governance_records or has_weekly_inputs(args)))


def print_result(result: JobResult) -> None:
    print(f"[{result.status}] {result.name}")
    for key, value in result.summary.items():
        print(f"  {key}: {value}")
    for output in result.outputs:
        print(f"  output: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run governance jobs in parallel where possible.")
    parser.add_argument("--project-owners", default="", help="CSV/JSON project owner mapping.")
    parser.add_argument("--ds-task-metadata", default="", help="CSV/JSON DS task metadata.")
    parser.add_argument("--abnormal-sql", default="", help="CSV/JSON abnormal SQL rows.")
    parser.add_argument("--existing-governance", default="", help="Optional CSV/JSON existing abnormal SQL governance table.")
    parser.add_argument("--abnormal-feedback", default="", help="Optional CSV/JSON abnormal SQL user feedback.")
    parser.add_argument("--feedback-governance-records", default="", help="Optional CSV/JSON governance records for feedback job.")
    parser.add_argument("--ds-zombie-records", default="", help="Optional CSV/JSON DS zombie governance table.")
    parser.add_argument("--ds-zombie-feedback", default="", help="Optional CSV/JSON DS zombie feedback table.")
    parser.add_argument("--output-dir", required=True, help="Directory for output CSV files.")
    parser.add_argument("--governance-week", default=default_week(), help="Governance week, e.g. 2026-W30.")
    parser.add_argument("--max-workers", type=int, default=3, help="Maximum parallel jobs.")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    results: list[JobResult] = []
    parallel_jobs: list[tuple[str, Callable[[], JobResult]]] = []

    if has_weekly_inputs(args):
        parallel_jobs.append(("weekly", lambda: run_weekly_job(args)))
    if has_ds_zombie_inputs(args):
        parallel_jobs.append(("ds_zombie", lambda: run_ds_zombie_job(args)))

    weekly_result: JobResult | None = None
    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        future_to_name = {executor.submit(job): name for name, job in parallel_jobs}
        for future in as_completed(future_to_name):
            result = future.result()
            results.append(result)
            if result.name == "weekly_abnormal_sql_governance":
                weekly_result = result

    if args.abnormal_feedback:
        feedback_records_path = Path(args.feedback_governance_records) if args.feedback_governance_records else None
        if not feedback_records_path and weekly_result:
            feedback_records_path = Path(args.output_dir) / "abnormal_sql_governance_weekly.csv"
        if feedback_records_path:
            results.append(run_abnormal_feedback_job(args, feedback_records_path))

    if not results:
        raise SystemExit("No runnable jobs. Provide weekly, feedback, or DS zombie inputs.")

    for result in results:
        print_result(result)


if __name__ == "__main__":
    main()

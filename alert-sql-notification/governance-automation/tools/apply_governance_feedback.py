#!/usr/bin/env python3
"""Apply abnormal SQL governance feedback and produce action candidates."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.action_planner import plan_abnormal_sql_action
from governance_automation.feedback_ingest import apply_abnormal_sql_feedback, build_feedback_index
from governance_automation.io_utils import read_records, write_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply abnormal SQL governance feedback.")
    parser.add_argument("--governance-records", required=True, help="CSV/JSON current abnormal SQL governance table.")
    parser.add_argument("--feedback", required=True, help="CSV/JSON user feedback table.")
    parser.add_argument("--output-updated", required=True, help="CSV/JSON updated governance table.")
    parser.add_argument("--output-actions", required=True, help="CSV/JSON action candidate output.")
    args = parser.parse_args()

    governance_records = read_records(args.governance_records)
    feedback_rows = read_records(args.feedback)
    updated_records = apply_abnormal_sql_feedback(governance_records, feedback_rows)
    feedback_index = build_feedback_index(feedback_rows, "governance_id")

    now = datetime.now()
    action_candidates = []
    for record in updated_records:
        governance_id = str(record.get("governance_id") or "").strip()
        feedback = feedback_index.get(governance_id)
        if feedback:
            action_candidates.append(plan_abnormal_sql_action(record, feedback, now=now))

    write_records(args.output_updated, updated_records)
    write_records(args.output_actions, action_candidates)

    print(f"updated governance records: {len(updated_records)}")
    print(f"processed feedback rows: {len(feedback_rows)}")
    print(f"action candidates: {len(action_candidates)}")


if __name__ == "__main__":
    main()

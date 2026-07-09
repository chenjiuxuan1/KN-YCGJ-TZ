#!/usr/bin/env python3
"""Plan DS zombie task governance actions from user feedback."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.action_planner import plan_ds_zombie_action
from governance_automation.io_utils import read_records, write_records


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("zombie_governance_id") or row.get("governance_id") or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan DS zombie task action candidates.")
    parser.add_argument("--zombie-records", required=True, help="CSV/JSON DS zombie governance table.")
    parser.add_argument("--feedback", required=True, help="CSV/JSON DS zombie user feedback table.")
    parser.add_argument("--output-actions", required=True, help="CSV/JSON action candidate output.")
    args = parser.parse_args()

    zombie_records = read_records(args.zombie_records)
    feedback_rows = read_records(args.feedback)
    feedback_index = {row_key(row): row for row in feedback_rows if row_key(row)}

    now = datetime.now()
    action_candidates = []
    for record in zombie_records:
        feedback = feedback_index.get(row_key(record))
        if feedback:
            action_candidates.append(plan_ds_zombie_action(record, feedback, now=now))

    write_records(args.output_actions, action_candidates)

    print(f"zombie records: {len(zombie_records)}")
    print(f"processed feedback rows: {len(feedback_rows)}")
    print(f"action candidates: {len(action_candidates)}")


if __name__ == "__main__":
    main()

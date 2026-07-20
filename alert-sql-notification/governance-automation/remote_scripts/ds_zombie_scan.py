#!/usr/bin/env python3
"""Scan DS workflows locally and print only one bounded n8n summary."""

import argparse
from collections import OrderedDict
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.ds_dependency_graph import build_dependency_graph
from governance_automation.ds_metadata_exporter import read_mysql_config_from_env
from governance_automation.ds_zombie_classifier import classify_workflow
from governance_automation.ds_zombie_models import WorkflowSnapshot
from governance_automation.ds_zombie_pipeline import build_summary
from governance_automation.ds_zombie_repository import DsZombieRepository
from governance_automation.ds_zombie_store import GovernanceStore


def as_bool(value):
    if value is None:
        return None
    return str(value).lower() in ("1", "true", "online")


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None


def scan(args):
    config = read_mysql_config_from_env()
    missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
    if missing:
        raise RuntimeError("missing DS environment: " + ",".join(missing))
    rows = DsZombieRepository(config).fetch_scan_rows(
        country=args.country, lookback_days=args.lookback_days,
        project_name=args.project_name, workflow_name=args.workflow_name, task_name=args.task_name,
    )
    workflows, relations, tasks = OrderedDict(), [], []
    for row in rows:
        code = str(row.get("workflow_code") or "")
        workflows.setdefault(code, row)
        relations.append({
            "workflow_code": code,
            "pre_task_code": str(row.get("pre_task_code") or ""),
            "post_task_code": str(row.get("post_task_code") or ""),
        })
        tasks.append({
            "workflow_code": code, "task_code": str(row.get("task_code") or ""),
            "task_type": row.get("task_type"), "task_params": row.get("task_params"),
        })
    graph = build_dependency_graph(relations, tasks)
    candidates = []
    for code, row in workflows.items():
        snapshot = WorkflowSnapshot(
            country=args.country, project_code=str(row.get("project_code") or ""), workflow_code=code,
            project_name=str(row.get("project_name") or ""), workflow_name=str(row.get("workflow_name") or ""),
            owner_name=str(row.get("owner_name") or ""), last_update_time=parse_time(row.get("last_update_time")),
            last_run_time=parse_time(row.get("last_run_time")), last_success_time=parse_time(row.get("last_success_time")),
            last_failure_time=parse_time(row.get("last_failure_time")), total_runs_30d=int(row.get("total_runs_30d") or 0),
            failed_runs_30d=int(row.get("failed_runs_30d") or 0), schedule_online=as_bool(row.get("schedule_online")),
            workflow_online=as_bool(row.get("workflow_online")), instance_scan_complete=True,
            dependency_scan_complete=graph.scan_complete[code], upstream_workflows=tuple(sorted(graph.workflow_upstream[code])),
            downstream_workflows=tuple(sorted(graph.workflow_downstream[code])),
        )
        result = classify_workflow(snapshot, score_version=args.score_version)
        candidates.append({
            "country": args.country, "batch_id": args.batch_id, "score_version": args.score_version,
            "project_code": snapshot.project_code, "project_name": snapshot.project_name,
            "workflow_code": code, "workflow_name": snapshot.workflow_name, "owner_name": snapshot.owner_name,
            "level": result.level, "score_total": result.score_total, "action": result.action,
            "protected_by_dependency": result.protected_by_dependency,
            "protected_by_uncertainty": result.protected_by_uncertainty,
            "upstream_count": len(snapshot.upstream_workflows), "downstream_count": len(snapshot.downstream_workflows),
            "reasons": list(result.reasons), "evidence": {"upstream": snapshot.upstream_workflows, "downstream": snapshot.downstream_workflows},
        })
    persisted = 0
    if args.write_to_db and not args.dry_run:
        gov = read_mysql_config_from_env("GOVERNANCE_DB")
        persisted = GovernanceStore(gov, os.getenv("GOVERNANCE_DB_TABLE", "ds_zombie_workflow_governance")).persist(candidates)
    return build_summary(args.country, args.batch_id, args.score_version, len(workflows), candidates, persisted, args.top_limit)


def main():
    parser = argparse.ArgumentParser(description="DS zombie workflow scan; stdout is a bounded JSON summary.")
    parser.add_argument("--country", required=True, choices=("cn", "ph", "ine", "mx", "th", "pk"))
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--min-stale-months", type=int, default=3)
    parser.add_argument("--project-name", default="")
    parser.add_argument("--workflow-name", default="")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--score-version", default="v1")
    parser.add_argument("--top-limit", type=int, default=20)
    parser.add_argument("--write-to-db", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        payload = scan(args)
    except Exception as exc:
        payload = {"success": False, "country": args.country, "batch_id": args.batch_id,
                   "error": {"code": "DS_ZOMBIE_SCAN_FAILED", "message": str(exc)[:500]}}
    print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Scan DS workflows locally and print only one bounded n8n summary."""

import argparse
from collections import Counter, OrderedDict
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
from governance_automation.ds_zombie_dependency_policy import assess_downstream_activity
from governance_automation.ds_zombie_models import ScoreResult
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


def build_downstream_details(code, graph, workflows, task_names):
    """Return human-readable consumers of ``code`` for the CSV export."""
    details = []
    for item in graph.evidence:
        if item.get("target_workflow_code") != code or item.get("parse_status") != "SUCCESS":
            continue
        source_code = str(item.get("source_workflow_code") or "")
        source = workflows.get(source_code, {})
        task_code = str(item.get("source_task_code") or "")
        task_name = task_names.get((source_code, task_code), "")
        details.append({
            "项目名称": str(source.get("project_name") or "未知项目"),
            "工作流名称": str(source.get("workflow_name") or source_code or "未知工作流"),
            "任务名称": task_name or task_code or "未识别任务",
            "依赖类型": dependency_type_name(item.get("dependency_type")),
            "工作流编码": source_code,
            "任务编码": task_code,
        })
    return sorted(details, key=lambda item: (item["项目名称"], item["工作流名称"], item["任务名称"], item["依赖类型"]))


def format_downstream_details(details):
    if not details:
        return "无下游依赖"
    return " | ".join(
        "项目名称：{项目名称}；工作流：{工作流名称}；任务：{任务名称}；类型：{依赖类型}".format(**item)
        for item in details
    )


def dependency_type_name(value):
    return {
        "DEPENDENT": "依赖任务",
        "SUB_PROCESS": "子工作流",
    }.get(str(value or "").upper(), "未知依赖")


def build_upstream_details(code, graph, workflows, task_names):
    """Return the workflows and tasks the current workflow depends on."""
    details = []
    for item in graph.evidence:
        if item.get("source_workflow_code") != code or item.get("parse_status") != "SUCCESS":
            continue
        target_code = str(item.get("target_workflow_code") or "")
        target = workflows.get(target_code, {})
        target_task_code = str(item.get("target_task_code") or "")
        details.append({
            "项目名称": str(target.get("project_name") or "未知项目"),
            "工作流名称": str(target.get("workflow_name") or target_code or "未知工作流"),
            "任务名称": task_names.get((target_code, target_task_code), "") or target_task_code or "工作流级依赖",
            "依赖类型": dependency_type_name(item.get("dependency_type")),
        })
    return sorted(details, key=lambda item: (item["项目名称"], item["工作流名称"], item["任务名称"], item["依赖类型"]))


def format_upstream_details(details):
    if not details:
        return "无上游依赖"
    return " | ".join(
        "项目名称：{项目名称}；工作流：{工作流名称}；任务：{任务名称}；类型：{依赖类型}".format(**item)
        for item in details
    )


def scan(args):
    config = read_mysql_config_from_env()
    missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
    if missing:
        raise RuntimeError("missing DS environment: " + ",".join(missing))
    rows = DsZombieRepository(config).fetch_scan_rows(
        country=args.country, lookback_days=args.lookback_days,
        project_name=args.project_name, workflow_name=args.workflow_name, task_name=args.task_name,
    )
    workflows, relations, tasks, task_names = OrderedDict(), [], [], {}
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
            "task_name": str(row.get("task_name") or ""), "task_type": row.get("task_type"),
            "task_params": row.get("task_params"),
        })
        task_names[(code, str(row.get("task_code") or ""))] = str(row.get("task_name") or "")
    graph = build_dependency_graph(relations, tasks)
    all_rows = []
    for code, row in workflows.items():
        downstream = tuple(sorted(graph.workflow_downstream[code]))
        downstream_assessment = assess_downstream_activity(
            downstream_codes=downstream, workflows=workflows
        )
        dependent_downstream = tuple(sorted({
            item["source_workflow_code"] for item in graph.evidence
            if item.get("target_workflow_code") == code
            and item.get("dependency_type") == "DEPENDENT"
        }))
        sub_process_downstream = tuple(sorted({
            item["source_workflow_code"] for item in graph.evidence
            if item.get("target_workflow_code") == code
            and item.get("dependency_type") == "SUB_PROCESS"
        }))
        upstream_details = build_upstream_details(code, graph, workflows, task_names)
        downstream_details = build_downstream_details(code, graph, workflows, task_names)
        snapshot = WorkflowSnapshot(
            country=args.country, project_code=str(row.get("project_code") or ""), workflow_code=code,
            project_name=str(row.get("project_name") or ""), workflow_name=str(row.get("workflow_name") or ""),
            owner_name=str(row.get("owner_name") or ""), last_update_time=parse_time(row.get("last_update_time")),
            last_run_time=parse_time(row.get("last_run_time")), last_success_time=parse_time(row.get("last_success_time")),
            last_failure_time=parse_time(row.get("last_failure_time")), total_runs_30d=int(row.get("total_runs_30d") or 0),
            failed_runs_30d=int(row.get("failed_runs_30d") or 0), schedule_online=as_bool(row.get("schedule_online")),
            schedule_active=as_bool(row.get("schedule_active")), workflow_online=as_bool(row.get("workflow_online")),
            active_instance_present=as_bool(row.get("active_instance_present")), instance_scan_complete=True,
            dependency_scan_complete=graph.scan_complete[code], upstream_workflows=tuple(sorted(graph.workflow_upstream[code])),
            downstream_workflows=downstream_assessment.active_codes,
        )
        result = classify_workflow(snapshot, score_version=args.score_version)
        if downstream_assessment.review_codes and result.level == "A":
            result = ScoreResult(
                "B", "OWNER_CONFIRMATION", result.score_total,
                result.reasons + ("存在未活跃下游依赖，需负责人确认",), result.score_detail,
            )
        all_rows.append({
            "country": args.country, "batch_id": args.batch_id, "score_version": args.score_version,
            "project_code": snapshot.project_code, "project_name": snapshot.project_name,
            "workflow_code": code, "workflow_name": snapshot.workflow_name, "owner_name": snapshot.owner_name,
            "level": result.level, "score_total": result.score_total, "action": result.action,
            "protected_by_dependency": result.protected_by_dependency,
            "protected_by_uncertainty": result.protected_by_uncertainty,
            "upstream_count": len(snapshot.upstream_workflows), "downstream_count": len(downstream),
            "source_schedule_online": snapshot.schedule_online,
            "source_schedule_active": snapshot.schedule_active,
            "source_workflow_online": snapshot.workflow_online,
            "source_active_instance_present": snapshot.active_instance_present,
            "active_downstream_count": len(downstream_assessment.active_codes),
            "review_downstream_count": len(downstream_assessment.review_codes),
            "dependent_downstream_count": len(dependent_downstream),
            "sub_process_downstream_count": len(sub_process_downstream),
            "upstream_dependency_detail": format_upstream_details(upstream_details),
            "downstream_dependency_detail": format_downstream_details(downstream_details),
            "reasons": list(result.reasons),
            "evidence": {
                "upstream": snapshot.upstream_workflows,
                "upstream_details": upstream_details,
                "active_downstream": downstream_assessment.active_codes,
                "review_downstream": downstream_assessment.review_codes,
                "dependent_downstream": dependent_downstream,
                "sub_process_downstream": sub_process_downstream,
                "downstream_details": downstream_details,
            },
        })
    candidates = all_rows if args.include_retained else [row for row in all_rows if row["level"] != "D"]
    persisted = 0
    if args.write_to_db and not args.dry_run:
        gov = read_mysql_config_from_env("GOVERNANCE_DB")
        persisted = GovernanceStore(gov, os.getenv("GOVERNANCE_DB_TABLE", "ds_zombie_workflow_governance")).persist(candidates)
    scanned_levels = Counter(str(row.get("level") or "C") for row in all_rows)
    return build_summary(
        args.country, args.batch_id, args.score_version, len(workflows), candidates, persisted, args.top_limit,
        scanned_level_summary={level: scanned_levels.get(level, 0) for level in "ABCD"},
    )


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
    parser.add_argument("--top-limit", type=int, default=0,
                        help="Maximum CSV candidates to return; 0 returns all candidates.")
    parser.add_argument("--include-retained", action="store_true",
                        help="Also export D-level workflows retained by active-use protection.")
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

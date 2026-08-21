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
from governance_automation.ds_metadata_exporter import (
    detect_connected_ds_schema, read_mysql_config_from_env,
)
from governance_automation.ds_schema import (
    build_schema_probe_sql, resolve_ds_schema, SCHEMA_PROBE_TABLES,
)
from governance_automation.ds_zombie_classifier import classify_workflow
from governance_automation.ds_zombie_dependency_policy import assess_downstream_activity
from governance_automation.ds_zombie_models import ScoreResult
from governance_automation.ds_zombie_models import WorkflowSnapshot
from governance_automation.ds_zombie_pipeline import build_summary
from governance_automation.ds_zombie_repository import DsZombieRepository
from governance_automation.ds_zombie_store import GovernanceStore
from governance_automation.ds_task_lineage import (
    build_table_consumers, extract_task_table_evidence, parse_task_params, task_script,
)

try:
    from ds_match_candidate_query import DS_COUNTRY_CONFIG
except Exception:  # pragma: no cover - optional fallback
    DS_COUNTRY_CONFIG = {}


DEPENDENCY_DETAIL_AVAILABLE = "available"
DEPENDENCY_DETAIL_NONE = "none"
DEPENDENCY_DETAIL_INCOMPLETE = "incomplete"
DEPENDENCY_DETAIL_UNAVAILABLE = "unavailable"


def as_bool(value):
    if value is None:
        return None
    return str(value).lower() in ("1", "true", "online")


def builtin_ds_config(country):
    builtin = DS_COUNTRY_CONFIG.get(country) or {}
    return {
        "host": builtin.get("host", ""),
        "port": int(builtin.get("port", "3306")),
        "user": builtin.get("user", ""),
        "password": os.environ.get(str(builtin.get("password_env", "")), ""),
        "database": builtin.get("database", ""),
        "charset": "utf8mb4",
    }


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


def dependency_detail_status(downstream_count, details, scan_complete):
    if not scan_complete:
        return DEPENDENCY_DETAIL_INCOMPLETE
    if int(downstream_count or 0) == 0:
        return DEPENDENCY_DETAIL_NONE
    return DEPENDENCY_DETAIL_AVAILABLE if details else DEPENDENCY_DETAIL_UNAVAILABLE


def format_downstream_for_status(status, downstream_count, details):
    if status == DEPENDENCY_DETAIL_NONE:
        return "无下游依赖"
    if status == DEPENDENCY_DETAIL_AVAILABLE:
        return format_downstream_details(details)
    if status == DEPENDENCY_DETAIL_INCOMPLETE:
        return "下游依赖解析不完整，需补充证据"
    return "已识别 %s 个下游依赖，但明细未返回；请部署最新扫描脚本" % downstream_count


def build_task_rows(workflow_row, tasks, table_consumers=None):
    table_consumers = table_consumers or {}
    rows = []
    for task in sorted(tasks, key=lambda item: (str(item.get("task_name") or ""), str(item.get("task_code") or ""))):
        params = parse_task_params(task.get("task_params"))
        evidence = extract_task_table_evidence(task_script(params), params)
        consumers = []
        for table in evidence.write_tables:
            consumers.extend(item for item in table_consumers.get(table, []) if item["workflow_code"] != workflow_row["workflow_code"])
        active_consumers = [item for item in consumers if item["active"]]
        consumer_details = " | ".join(
            "项目名称：{project_name}；工作流：{workflow_name}；任务：{task_name}；读取表：{table}".format(table=table, **item)
            for table in evidence.write_tables for item in table_consumers.get(table, [])
            if item["workflow_code"] != workflow_row["workflow_code"]
        )
        row = dict(workflow_row)
        row.update({
            "record_granularity": "任务级",
            "candidate_task_code": str(task.get("task_code") or ""),
            "candidate_task_name": str(task.get("task_name") or "未命名任务"),
            "candidate_task_type": str(task.get("task_type") or "未知"),
            "candidate_write_tables": "|".join(evidence.write_tables) or "未识别写表",
            "candidate_read_tables": "|".join(evidence.read_tables) or "未识别读表",
            "task_resource_refs": "|".join(evidence.resource_refs) or "无资源引用",
            "task_lineage_status": evidence.status,
            "table_lineage_downstream_detail": consumer_details or ("未识别写表" if not evidence.write_tables else "未发现内嵌SQL消费者，待 Router 增强"),
            "table_lineage_confidence": "高" if active_consumers else "未确认",
            "table_lineage_source": "内嵌任务SQL" if consumers else "待 Router 增强",
            "table_lineage_status": "已确认" if active_consumers else ("待增强" if evidence.write_tables else "不适用"),
            "downstream_protection_basis": (
                "活跃任务表血缘保护" if active_consumers else workflow_row.get("downstream_protection_basis", "无保护证据")
            ),
        })
        if evidence.status == "incomplete":
            row["reasons"] = list(row.get("reasons", [])) + ["任务 SQL 为动态内容，表血缘待补充"]
        rows.append(row)
    if rows:
        return rows
    fallback = dict(workflow_row)
    fallback.update({
        "record_granularity": "工作流级兜底",
        "candidate_task_code": "",
        "candidate_task_name": "工作流级评估",
        "candidate_task_type": "无任务定义",
        "candidate_write_tables": "未识别写表",
        "candidate_read_tables": "未识别读表",
        "task_resource_refs": "无资源引用",
        "task_lineage_status": "incomplete",
        "table_lineage_downstream_detail": "任务定义缺失，未执行表血缘扫描",
        "table_lineage_confidence": "未扫描",
        "table_lineage_source": "未扫描",
        "table_lineage_status": "不完整",
        "downstream_protection_basis": workflow_row.get("downstream_protection_basis", "无保护证据"),
    })
    return [fallback]


def run_schema_check(args, config):
    probe_sql = build_schema_probe_sql()
    try:
        from governance_automation.ds_metadata_exporter import query_mysql_records
        rows = query_mysql_records(sql=probe_sql, **config)
    except Exception as exc:
        return {"success": False, "country": args.country,
                "probe_sql": probe_sql, "error": str(exc)[:500]}
    found = sorted({str(row.get("table_name") or "") for row in rows})
    from governance_automation.ds_schema import detect_ds_schema
    detected = detect_ds_schema(rows)
    tables = {
        "new": SCHEMA_PROBE_TABLES["new"],
        "legacy": SCHEMA_PROBE_TABLES["legacy"],
    }
    recommendation = {
        "new": tables["new"],
        "legacy": tables["legacy"],
        None: "无法识别（两套表都不存在，请确认 database 是否正确或联系平台）",
    }[detected]
    return {
        "success": True, "country": args.country, "detected_schema": detected,
        "found_tables": found, "probe_sql": probe_sql,
        "recommended_scan_table": recommendation,
        "hint": "使用 --schema new|legacy 可覆盖自动探测",
    }


def resolve_scan_schema(args, config):
    if args.schema != "auto":
        return resolve_ds_schema(args.schema)
    detected = detect_connected_ds_schema(config=config)
    if detected is None:
        raise RuntimeError(
            "无法自动识别 DS schema：数据库中不存在 %s 也 %s，请先运行 --schema-check 诊断。"
            % (SCHEMA_PROBE_TABLES["new"], SCHEMA_PROBE_TABLES["legacy"])
        )
    return detected


def scan(args):
    config = read_mysql_config_from_env()
    missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
    if missing:
        config = builtin_ds_config(args.country)
        missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
    if missing:
        raise RuntimeError("missing DS environment: " + ",".join(missing))
    schema_name = resolve_scan_schema(args, config)
    rows = DsZombieRepository(config).fetch_scan_rows(
        country=args.country, lookback_days=args.lookback_days,
        inactive_months=args.min_stale_months,
        project_name=args.project_name, workflow_name=args.workflow_name, task_name=args.task_name,
        release_state=args.release_state, schema=schema_name,
    )
    workflows, relations, tasks, tasks_by_workflow, task_names = OrderedDict(), [], [], OrderedDict(), {}
    for row in rows:
        code = str(row.get("workflow_code") or "")
        workflows.setdefault(code, row)
        relations.append({
            "workflow_code": code,
            "pre_task_code": str(row.get("pre_task_code") or ""),
            "post_task_code": str(row.get("post_task_code") or ""),
        })
        task = {
            "workflow_code": code, "task_code": str(row.get("task_code") or ""),
            "task_name": str(row.get("task_name") or ""), "task_type": row.get("task_type"),
            "task_params": row.get("task_params"),
        }
        tasks.append(task)
        tasks_by_workflow.setdefault(code, OrderedDict()).setdefault(task["task_code"], task)
        task_names[(code, task["task_code"])] = task["task_name"]
    graph = build_dependency_graph(relations, tasks)
    table_consumers = build_table_consumers([
        {
            "project_name": workflows.get(code, {}).get("project_name"),
            "workflow_code": code,
            "workflow_name": workflows.get(code, {}).get("workflow_name"),
            "task_code": task.get("task_code"), "task_name": task.get("task_name"),
            "sql": task_script(parse_task_params(task.get("task_params"))),
            "params": parse_task_params(task.get("task_params")),
            "active": bool(as_bool(workflows.get(code, {}).get("schedule_active")))
                or int(workflows.get(code, {}).get("total_runs_window") or workflows.get(code, {}).get("total_runs_30d") or 0) > 0
                or bool(as_bool(workflows.get(code, {}).get("active_instance_present"))),
        }
        for code, group in tasks_by_workflow.items() for task in group.values()
    ])
    workflow_rows = []
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
        detail_status = dependency_detail_status(len(downstream), downstream_details, graph.scan_complete[code])
        task_evidences = [
            extract_task_table_evidence(task_script(parse_task_params(task.get("task_params"))), parse_task_params(task.get("task_params")))
            for task in tasks_by_workflow.get(code, {}).values()
        ]
        has_active_table_consumer = any(
            consumer["active"]
            for evidence in task_evidences for table in evidence.write_tables
            for consumer in table_consumers.get(table, []) if consumer["workflow_code"] != code
        )
        window_value = int(row.get("scan_window_value") or 30)
        window_label = ("%d个月" % window_value) if str(row.get("scan_window_unit") or "day") == "month" else ("%d天" % window_value)
        snapshot = WorkflowSnapshot(
            country=args.country, project_code=str(row.get("project_code") or ""), workflow_code=code,
            project_name=str(row.get("project_name") or ""), workflow_name=str(row.get("workflow_name") or ""),
            owner_name=str(row.get("owner_name") or ""), last_update_time=parse_time(row.get("last_update_time")),
            last_run_time=parse_time(row.get("last_run_time")), last_success_time=parse_time(row.get("last_success_time")),
            last_failure_time=parse_time(row.get("last_failure_time")), total_runs_30d=int(row.get("total_runs_30d") or 0),
            failed_runs_30d=int(row.get("failed_runs_30d") or 0),
            total_runs_window=int(row.get("total_runs_window") or 0),
            failed_runs_window=int(row.get("failed_runs_window") or 0),
            inactive_months=int(args.min_stale_months or 0), scan_window_label=window_label,
            schedule_online=as_bool(row.get("schedule_online")),
            schedule_active=as_bool(row.get("schedule_active")), workflow_online=as_bool(row.get("workflow_online")),
            active_instance_present=as_bool(row.get("active_instance_present")), instance_scan_complete=True,
            dependency_scan_complete=graph.scan_complete[code], upstream_workflows=tuple(sorted(graph.workflow_upstream[code])),
            downstream_workflows=downstream_assessment.active_codes,
        )
        result = classify_workflow(snapshot, score_version=args.score_version)
        if snapshot.workflow_online is False:
            schedule_status, schedule_status_cn = "OFFLINE", "已下线"
        elif snapshot.schedule_active:
            schedule_status, schedule_status_cn = "SCHEDULE_ACTIVE", "定时调度中"
        elif snapshot.schedule_online:
            schedule_status, schedule_status_cn = "SCHEDULE_STOPPED", "定时已停"
        else:
            schedule_status, schedule_status_cn = "MANUAL_ONLINE", "上线手动"
        if has_active_table_consumer:
            result = ScoreResult(
                "D", "RETAIN_AND_ASSESS", result.score_total,
                result.reasons + ("存在活跃任务表血缘下游",), result.score_detail,
                protected_by_dependency=True,
            )
        if downstream_assessment.review_codes and result.level == "A":
            result = ScoreResult(
                "B", "OWNER_CONFIRMATION", result.score_total,
                result.reasons + ("存在未活跃下游依赖，需负责人确认",), result.score_detail,
            )
        workflow_rows.append({
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
            "schedule_status": schedule_status,
            "schedule_status_cn": schedule_status_cn,
            "source_active_instance_present": snapshot.active_instance_present,
            "active_downstream_count": len(downstream_assessment.active_codes),
            "review_downstream_count": len(downstream_assessment.review_codes),
            "dependent_downstream_count": len(dependent_downstream),
            "sub_process_downstream_count": len(sub_process_downstream),
            "upstream_dependency_detail": format_upstream_details(upstream_details),
            "dependency_detail_status": detail_status,
            "downstream_dependency_detail": format_downstream_for_status(detail_status, len(downstream), downstream_details),
            "downstream_protection_basis": (
                "存在活跃显式下游依赖" if downstream_assessment.active_codes else
                "存在待确认显式下游依赖" if downstream_assessment.review_codes else
                "无显式下游依赖"
            ),
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
    workflow_candidates = workflow_rows if args.include_retained else [row for row in workflow_rows if row["level"] != "D"]
    candidates = []
    for row in workflow_candidates:
        candidates.extend(build_task_rows(row, list(tasks_by_workflow.get(row["workflow_code"], {}).values()), table_consumers))
    persisted = 0
    if args.write_to_db and not args.dry_run:
        gov = read_mysql_config_from_env("GOVERNANCE_DB")
        persisted = GovernanceStore(gov, os.getenv("GOVERNANCE_DB_TABLE", "ds_zombie_workflow_governance")).persist(workflow_candidates)
    scanned_levels = Counter(str(row.get("level") or "C") for row in workflow_rows)
    first_row = next(iter(workflow_rows), {})
    window_value = int(first_row.get("scan_window_value") or (args.lookback_days if not args.min_stale_months else args.min_stale_months))
    window_unit = "month" if str(first_row.get("scan_window_unit") or "") == "month" or args.min_stale_months else "day"
    scan_window = "%d%s" % (window_value, "个月" if window_unit == "month" else "天")
    return build_summary(
        args.country, args.batch_id, args.score_version, len(workflows), candidates, persisted, args.top_limit,
        scanned_level_summary={level: scanned_levels.get(level, 0) for level in "ABCD"},
        scan_window=scan_window,
    )


def main():
    parser = argparse.ArgumentParser(description="DS zombie workflow scan; stdout is a bounded JSON summary.")
    parser.add_argument("--country", required=True, choices=("cn", "ph", "ine", "mx", "th", "pk"))
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--min-stale-months", type=int, default=3,
                        help="动态零访问窗口：判定'近N个月零运行'的月数（如 3=近3个月无人访问才判僵尸，0 回退到 lookback-days 天窗口）")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--workflow-name", default="")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--score-version", default="v1")
    parser.add_argument("--release-state", choices=("all", "online", "offline"), default="online",
                        help="扫描工作流的上线状态：online=仅上线(默认)、offline=仅下线、all=全部")
    parser.add_argument("--top-limit", type=int, default=0,
                        help="Maximum CSV candidates to return; 0 returns all candidates.")
    parser.add_argument("--include-retained", action="store_true",
                        help="Also export D-level workflows retained by active-use protection.")
    parser.add_argument("--write-to-db", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schema", choices=("auto", "new", "legacy"), default="auto",
                        help="DS 元数据表结构：auto=自动探测(默认)、new=t_ds_workflow_definition、legacy=t_ds_process_definition")
    parser.add_argument("--schema-check", action="store_true",
                        help="只读诊断：探测 DS 数据库实际使用哪套元数据表并退出，不做扫描")
    args = parser.parse_args()
    try:
        config = read_mysql_config_from_env()
        missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
        if missing:
            config = builtin_ds_config(args.country)
        if args.schema_check:
            payload = run_schema_check(args, config)
        else:
            payload = scan(args)
    except Exception as exc:
        payload = {"success": False, "country": args.country, "batch_id": args.batch_id,
                   "error": {"code": "DS_ZOMBIE_SCAN_FAILED", "message": str(exc)[:500]}}
    print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

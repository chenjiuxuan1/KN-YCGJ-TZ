"""First-version production pipeline for weekly abnormal SQL governance."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .ds_task_matcher import enrich_abnormal_rows_with_ds_task
from .governance_store import upsert_governance_records
from .level_classifier import score_abnormal_sql
from .owner_resolver import (
    build_project_owner_index,
    resolve_ds_task_owner,
    resolve_special_group,
)
from .weekly_aggregator import aggregate_abnormal_sql


def build_governance_id(record: dict[str, Any]) -> str:
    parts = [
        record.get("country"),
        record.get("cluster"),
        record.get("source_type"),
        record.get("query_user"),
        str(record.get("sql_fingerprint") or "")[:12],
    ]
    return "-".join(str(part or "").strip().lower().replace(" ", "_") for part in parts if part)


def resolve_ds_owners(
    project_owner_rows: list[dict[str, Any]],
    task_metadata_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project_index = build_project_owner_index(project_owner_rows)
    resolved_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []

    for row in task_metadata_rows:
        resolution = resolve_ds_task_owner(row, project_index)
        output = {
            "country": row.get("国家") or row.get("country") or "",
            "ds_env": row.get("DS环境") or row.get("ds_env") or "",
            "project_name": row.get("项目名称") or row.get("project_name") or "",
            "workflow_name": row.get("工作流名称") or row.get("workflow_name") or "",
            "task_name": row.get("任务名") or row.get("task_name") or "",
            "task_type": row.get("任务类型") or row.get("task_type") or "",
            "task_online_status": row.get("任务上下线状态") or row.get("task_online_status") or "",
            "script": row.get("script") or "",
            "datasource": row.get("数据源") or row.get("datasource") or "",
            "datasource_user": row.get("数据源用户") or row.get("datasource_user") or "",
            "datasource_jdbc_url": row.get("数据源jdbcUrl") or row.get("datasource_jdbc_url") or "",
            "project_owner": row.get("所属用户") or row.get("project_owner") or "",
            "task_owner_candidate": row.get("所属用户") or row.get("project_owner_raw") or "",
            "workflow_create_user": row.get("创建用户") or row.get("workflow_create_user") or "",
            "workflow_update_user": row.get("修改用户") or row.get("workflow_update_user") or "",
            "resolved_owner": resolution.owner,
            "resolved_owner_email": resolution.owner_email,
            "resolved_owner_group": resolution.owner_group,
            "resolved_owner_source": resolution.source,
            "owner_resolve_status": resolution.status,
            "owner_resolve_reason": resolution.reason,
            "need_manual_confirm": resolution.need_manual_confirm,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        resolved_rows.append(output)
        if resolution.status != "resolved":
            pending_rows.append(
                {
                    "country": output["country"],
                    "project_name": output["project_name"],
                    "workflow_name": output["workflow_name"],
                    "task_name": output["task_name"],
                    "current_owner_candidate": output["task_owner_candidate"],
                    "system_account_hit": True,
                    "reason": resolution.reason,
                    "suggested_owner": "",
                    "confirmed_owner": "",
                    "confirmed_owner_email": "",
                    "confirmed_by": "",
                    "confirmed_at": "",
                    "status": "pending",
                    "remark": "",
                }
            )
    return resolved_rows, pending_rows


def build_owner_index(resolved_owner_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    index = {}
    for row in resolved_owner_rows:
        key = (
            str(row.get("project_name") or "").strip().lower(),
            str(row.get("workflow_name") or "").strip().lower(),
            str(row.get("task_name") or "").strip().lower(),
        )
        index[key] = row
    return index


def attach_owner_to_record(record: dict[str, Any], owner_index: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
    key = (
        str(record.get("ds_project") or "").strip().lower(),
        str(record.get("ds_workflow") or "").strip().lower(),
        str(record.get("ds_task") or "").strip().lower(),
    )
    owner = owner_index.get(key)
    output = dict(record)
    if owner and owner.get("owner_resolve_status") == "resolved":
        output["owner_name"] = owner.get("resolved_owner", "")
        output["owner_email"] = owner.get("resolved_owner_email", "")
        output["owner_group"] = owner.get("resolved_owner_group", "")
        output["owner_source"] = owner.get("resolved_owner_source", "")
        output["owner_resolve_status"] = "resolved"
    elif owner:
        output["owner_name"] = ""
        output["owner_email"] = ""
        output["owner_group"] = ""
        output["owner_source"] = "ds_owner_pending"
        output["owner_resolve_status"] = owner.get("owner_resolve_status", "pending")
    else:
        output.setdefault("owner_resolve_status", "pending")
        output.setdefault("owner_source", "not_matched")
    return output


def apply_special_group_route(record: dict[str, Any]) -> dict[str, Any]:
    special = resolve_special_group(
        cluster=str(record.get("cluster") or ""),
        account=str(record.get("query_user") or ""),
        departments=[str(record.get("department") or "")],
        contacts=[str(record.get("owner_name") or "")],
        emails=[str(record.get("owner_email") or "")],
    )
    output = dict(record)
    if special:
        output["notify_channel"] = "group_bot"
        output["notify_route"] = special["channel"]
        output["notify_bot_id"] = special["bot_id"]
        output["notify_route_reason"] = special["reason"]
        output["owner_source"] = "special_group_rule"
        output["owner_resolve_status"] = "resolved"
    elif output.get("owner_email"):
        output["notify_channel"] = "sidecar"
    else:
        output["notify_channel"] = "pending_owner"
    return output


def enrich_governance_records(
    weekly_records: list[dict[str, Any]],
    resolved_owner_rows: list[dict[str, Any]],
    governance_week: str,
    deadline_days: int = 7,
) -> list[dict[str, Any]]:
    owner_index = build_owner_index(resolved_owner_rows)
    deadline = (datetime.now().date() + timedelta(days=deadline_days)).isoformat()
    enriched: list[dict[str, Any]] = []

    for record in weekly_records:
        item = attach_owner_to_record(record, owner_index)
        item = apply_special_group_route(item)
        score = score_abnormal_sql(item)
        item["governance_level"] = score.level
        item["governance_score"] = score.score
        item["level_reason"] = score.reason
        item["score_components"] = "|".join(
            f"{component.key}:{component.score}:{component.reason}" for component in score.components
        )
        item["governance_week"] = governance_week
        item["governance_id"] = build_governance_id(item)
        item.setdefault("deadline", deadline)
        item.setdefault("rectify_method", "")
        item.setdefault("governance_status", "待认领")
        item.setdefault("is_overdue", False)
        item.setdefault("still_exists", "")
        item.setdefault("last_review_time", "")
        item.setdefault("last_notify_time", "")
        item.setdefault("notify_count", 0)
        item.setdefault("remark", "")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item.setdefault("created_at", now)
        item["updated_at"] = now
        enriched.append(item)
    return enriched


def build_notify_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for record in records:
        if record.get("governance_level") != "A":
            continue
        if record.get("notify_channel") == "pending_owner":
            continue
        candidates.append(record)
    return candidates


def build_user_confirmation_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record.get("governance_level") not in {"A", "B"}:
            continue
        rows.append(
            {
                "governance_id": record.get("governance_id", ""),
                "governance_week": record.get("governance_week", ""),
                "country": record.get("country", ""),
                "cluster": record.get("cluster", ""),
                "source_type": record.get("source_type", ""),
                "query_user": record.get("query_user", ""),
                "sql_fingerprint": record.get("sql_fingerprint", ""),
                "sample_sql_url": record.get("sample_sql_url", ""),
                "ds_project": record.get("ds_project", ""),
                "ds_workflow": record.get("ds_workflow", ""),
                "ds_task": record.get("ds_task", ""),
                "owner_name": record.get("owner_name", ""),
                "owner_email": record.get("owner_email", ""),
                "governance_level": record.get("governance_level", ""),
                "governance_score": record.get("governance_score", ""),
                "level_reason": record.get("level_reason", ""),
                "score_components": record.get("score_components", ""),
                "alert_count": record.get("alert_count", ""),
                "history_alert_count": record.get("history_alert_count", ""),
                "first_alert_time": record.get("first_alert_time", ""),
                "last_alert_time": record.get("last_alert_time", ""),
                "deadline": record.get("deadline", ""),
                "owner_confirmed": "",
                "actual_owner": "",
                "actual_owner_email": "",
                "rectify_method": "",
                "rectify_status": "",
                "keep_required": "",
                "keep_reason": "",
                "can_offline_ds": "",
                "expected_finish_date": "",
                "user_remark": "",
            }
        )
    return rows


def run_weekly_governance(
    *,
    project_owner_rows: list[dict[str, Any]],
    task_metadata_rows: list[dict[str, Any]],
    abnormal_sql_rows: list[dict[str, Any]],
    existing_governance_rows: list[dict[str, Any]],
    governance_week: str,
) -> dict[str, list[dict[str, Any]]]:
    resolved_owners, pending_owners = resolve_ds_owners(project_owner_rows, task_metadata_rows)
    enriched_abnormal_rows, ds_task_matches, ds_task_match_pending = enrich_abnormal_rows_with_ds_task(
        abnormal_sql_rows,
        task_metadata_rows,
    )
    weekly_records = aggregate_abnormal_sql(enriched_abnormal_rows)
    enriched_records = enrich_governance_records(weekly_records, resolved_owners, governance_week)
    governance_records = upsert_governance_records(existing_governance_rows, enriched_records)
    notify_candidates = build_notify_candidates(governance_records)
    user_confirmation_rows = build_user_confirmation_rows(governance_records)
    return {
        "ds_task_owner_resolved": resolved_owners,
        "ds_owner_pending_confirm": pending_owners,
        "ds_task_match_results": ds_task_matches,
        "ds_task_match_pending": ds_task_match_pending,
        "abnormal_sql_governance_weekly": governance_records,
        "abnormal_sql_governance_form": user_confirmation_rows,
        "notify_candidates": notify_candidates,
    }

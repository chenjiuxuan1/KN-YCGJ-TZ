"""Match abnormal SQL records back to DS project/workflow/task metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sql_fingerprint import build_sql_fingerprint, normalize_sql


SCRIPT_FIELDS = (
    "resolved_script_content",
    "resource_content",
    "shell_content",
    "script_content",
    "script_text",
    "sql_content",
    "task_sql",
    "raw_script",
    "rawScript",
    "操作",
    "sql",
    "script",
    "task_params",
)


@dataclass(frozen=True)
class DsTaskMatch:
    status: str
    project_name: str = ""
    workflow_name: str = ""
    task_name: str = ""
    match_method: str = ""
    match_score: float = 0.0
    reason: str = ""


def text(value: Any) -> str:
    return str(value or "").strip()


def task_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = text(row.get(key))
        if value:
            return value
    return ""


def has_ds_identity(row: dict[str, Any]) -> bool:
    return bool(text(row.get("ds_project")) and text(row.get("ds_workflow")) and text(row.get("ds_task")))


def get_abnormal_sql(row: dict[str, Any]) -> str:
    return task_value(row, "raw_sql", "sql", "operation_sql", "操作", "query_sql")


def get_task_script(row: dict[str, Any]) -> str:
    parts = []
    for field in SCRIPT_FIELDS:
        value = text(row.get(field))
        if value:
            parts.append(value)
    return "\n".join(parts)


def build_task_identity(row: dict[str, Any], status: str, method: str, score: float, reason: str) -> DsTaskMatch:
    return DsTaskMatch(
        status=status,
        project_name=task_value(row, "项目名称", "project_name"),
        workflow_name=task_value(row, "工作流名称", "workflow_name"),
        task_name=task_value(row, "任务名", "task_name"),
        match_method=method,
        match_score=score,
        reason=reason,
    )


def match_score(abnormal_sql: str, task_script: str) -> tuple[float, str]:
    abnormal_normalized = normalize_sql(abnormal_sql)
    task_normalized = normalize_sql(task_script)
    if not abnormal_normalized or not task_normalized:
        return 0.0, ""

    abnormal_fp = build_sql_fingerprint(abnormal_sql).fingerprint
    task_fp = build_sql_fingerprint(task_script).fingerprint
    if abnormal_fp == task_fp:
        return 1.0, "fingerprint"

    if abnormal_normalized in task_normalized:
        ratio = len(abnormal_normalized) / max(len(task_normalized), 1)
        return max(0.85, min(0.99, ratio)), "normalized_sql_contained_in_task_script"

    if task_normalized in abnormal_normalized:
        ratio = len(task_normalized) / max(len(abnormal_normalized), 1)
        return max(0.75, min(0.95, ratio)), "task_script_contained_in_normalized_sql"

    return 0.0, ""


def match_ds_task(
    abnormal_row: dict[str, Any],
    task_metadata_rows: list[dict[str, Any]],
    *,
    min_score: float = 0.85,
) -> DsTaskMatch:
    if has_ds_identity(abnormal_row):
        return DsTaskMatch(
            status="already_provided",
            project_name=text(abnormal_row.get("ds_project")),
            workflow_name=text(abnormal_row.get("ds_workflow")),
            task_name=text(abnormal_row.get("ds_task")),
            match_method="input_fields",
            match_score=1.0,
            reason="异常 SQL 明细已包含 DS 项目、工作流、任务",
        )

    abnormal_sql = get_abnormal_sql(abnormal_row)
    if not abnormal_sql:
        return DsTaskMatch(status="pending", reason="异常 SQL 明细中没有可用于匹配的 SQL 内容")

    candidates: list[DsTaskMatch] = []
    for task_row in task_metadata_rows:
        score, method = match_score(abnormal_sql, get_task_script(task_row))
        if score >= min_score:
            candidates.append(
                build_task_identity(
                    task_row,
                    status="matched",
                    method=method,
                    score=score,
                    reason="通过异常 SQL 与 DS 任务脚本内容匹配",
                )
            )

    candidates.sort(key=lambda item: item.match_score, reverse=True)
    if not candidates:
        return DsTaskMatch(status="pending", reason="未在 DS 任务脚本内容中匹配到该异常 SQL")
    if len(candidates) > 1 and candidates[0].match_score == candidates[1].match_score:
        return DsTaskMatch(status="ambiguous", reason="多个 DS 任务匹配分数相同，需要人工确认")
    return candidates[0]


def enrich_abnormal_rows_with_ds_task(
    abnormal_rows: list[dict[str, Any]],
    task_metadata_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    enriched_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []

    for row in abnormal_rows:
        item = dict(row)
        match = match_ds_task(item, task_metadata_rows)
        item["ds_task_match_status"] = match.status
        item["ds_task_match_method"] = match.match_method
        item["ds_task_match_score"] = match.match_score
        item["ds_task_match_reason"] = match.reason

        if match.status in {"already_provided", "matched"}:
            item["ds_project"] = match.project_name
            item["ds_workflow"] = match.workflow_name
            item["ds_task"] = match.task_name

        output = {
            "query_id": text(item.get("query_id")),
            "cluster": text(item.get("cluster")),
            "query_user": text(item.get("user") or item.get("query_user")),
            "ds_project": text(item.get("ds_project")),
            "ds_workflow": text(item.get("ds_workflow")),
            "ds_task": text(item.get("ds_task")),
            "match_status": match.status,
            "match_method": match.match_method,
            "match_score": match.match_score,
            "match_reason": match.reason,
        }
        match_rows.append(output)
        if match.status not in {"already_provided", "matched"}:
            pending_rows.append(output)
        enriched_rows.append(item)

    return enriched_rows, match_rows, pending_rows

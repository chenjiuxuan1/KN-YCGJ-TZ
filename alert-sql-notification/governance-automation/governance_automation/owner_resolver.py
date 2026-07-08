"""Resolve DS and abnormal SQL owners from project, task, and contact data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


SYSTEM_ACCOUNTS = {
    "admin",
    "deploy",
    "root",
    "system",
    "ds",
    "dolphinscheduler",
    "default",
    "",
}


@dataclass(frozen=True)
class OwnerResolution:
    owner: str
    owner_email: str = ""
    owner_group: str = ""
    source: str = ""
    status: str = "pending"
    reason: str = ""
    need_manual_confirm: bool = True


def normalize_user(value: Any) -> str:
    return str(value or "").strip().lower().replace("u_", "", 1)


def normalize_project(value: Any) -> str:
    return str(value or "").strip()


def is_system_account(value: Any) -> bool:
    return normalize_user(value) in SYSTEM_ACCOUNTS


def first_non_system(values: Iterable[Any]) -> str:
    for value in values:
        user = normalize_user(value)
        if user and not is_system_account(user):
            return user
    return ""


def build_project_owner_index(project_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in project_rows:
        project_name = normalize_project(row.get("项目名称") or row.get("project_name"))
        if not project_name:
            continue
        owner = normalize_user(row.get("所属用户") or row.get("project_owner"))
        index[project_name] = {
            "owner": owner,
            "email": str(row.get("负责人邮箱") or row.get("project_owner_email") or "").strip(),
            "group": str(row.get("部门群") or row.get("owner_group") or "").strip(),
            "raw": row,
        }
    return index


def resolve_ds_task_owner(
    task_row: dict[str, Any],
    project_owner_index: dict[str, dict[str, Any]],
) -> OwnerResolution:
    project_name = normalize_project(task_row.get("项目名称") or task_row.get("project_name"))
    project_owner = project_owner_index.get(project_name, {})

    project_owner_user = normalize_user(project_owner.get("owner"))
    if project_owner_user and not is_system_account(project_owner_user):
        return OwnerResolution(
            owner=project_owner_user,
            owner_email=str(project_owner.get("email") or ""),
            owner_group=str(project_owner.get("group") or ""),
            source="project_owner_mapping",
            status="resolved",
            reason="命中项目级负责人表",
            need_manual_confirm=False,
        )

    task_owner = first_non_system(
        [
            task_row.get("所属用户"),
            task_row.get("project_owner_raw"),
            task_row.get("修改用户"),
            task_row.get("workflow_update_user"),
            task_row.get("创建用户"),
            task_row.get("workflow_create_user"),
        ]
    )
    if task_owner:
        return OwnerResolution(
            owner=task_owner,
            source="task_metadata_candidate",
            status="resolved",
            reason="项目级负责人缺失或为系统账号，使用任务级候选负责人",
            need_manual_confirm=False,
        )

    return OwnerResolution(
        owner="",
        source="",
        status="pending",
        reason="项目级负责人、所属用户、创建用户、修改用户均为空或为系统账号，需要人工确认",
        need_manual_confirm=True,
    )


def resolve_special_group(
    *,
    cluster: str,
    account: str,
    departments: Iterable[str] = (),
    contacts: Iterable[str] = (),
    emails: Iterable[str] = (),
) -> dict[str, Any] | None:
    signal_text = "\n".join([*(departments or []), *(contacts or []), *(emails or [])]).lower()
    normalized_cluster = str(cluster or "").strip().lower()
    normalized_account = normalize_user(account)

    is_mexico = normalized_cluster in {"starrocks_mex", "starrocks_mx", "mex", "mx", "mexico"}
    if is_mexico and normalized_account == "e_ds_aifox":
        return {
            "channel": "mexico_aifox_group",
            "bot_id": "e10c0656-a479-4053-a9cd-18b4d1fe4c87",
            "reason": "命中墨西哥 e_ds_aifox 账号级专属群规则",
        }

    if "许诺" in signal_text or "lunaxu@kn.group" in signal_text:
        return {
            "channel": "operation_group",
            "bot_id": "66f4d55a-1ca1-45fc-aaf7-f7e9f4dfa302",
            "reason": "命中运营群规则",
        }

    if "唯渡" in signal_text or "杜艳华" in signal_text or "elsadu" in signal_text or "@weidu.co" in signal_text:
        return {
            "channel": "weidu_group",
            "bot_id": "9ce66a04-5acf-4f84-9fc0-c213760bae05",
            "reason": "命中唯渡群规则",
        }

    return None


"""Plan next governance actions from user feedback and review results."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def text(value: Any) -> str:
    return str(value or "").strip()


def is_yes(value: Any) -> bool:
    return text(value) in {"是", "yes", "true", "1", "Y", "y"}


def boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = text(value).lower()
    if normalized in {"是", "yes", "true", "1", "y"}:
        return True
    if normalized in {"否", "no", "false", "0", "n"}:
        return False
    return None


def build_action_id(governance_type: str, governance_id: str, action_type: str) -> str:
    raw = f"{governance_type}-{governance_id}-{action_type}"
    return raw.lower().replace(" ", "_")[:160]


def plan_abnormal_sql_action(
    governance_record: dict[str, Any],
    feedback: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    feedback = feedback or {}
    governance_id = text(governance_record.get("governance_id"))
    still_exists = boolish(governance_record.get("still_exists"))
    is_overdue = boolish(governance_record.get("is_overdue")) is True
    rectify_status = text(feedback.get("rectify_status"))
    can_offline_ds = is_yes(feedback.get("can_offline_ds"))
    keep_required = is_yes(feedback.get("keep_required"))

    action_type = "continue_observe"
    reason = "默认继续观察"
    risk_level = "low"
    requires_second_confirm = False

    if keep_required:
        action_type = "continue_observe"
        reason = "用户填写需要保留，进入保留观察"
    elif rectify_status == "已整改" and still_exists is False:
        action_type = "close"
        reason = "用户确认已整改且复核未再出现"
    elif rectify_status == "已整改" and still_exists is True:
        action_type = "escalate"
        reason = "用户确认已整改但复核仍出现，需要重新治理"
        risk_level = "medium"
    elif can_offline_ds:
        action_type = "offline_candidate"
        reason = "用户确认可下线 DS，进入下线候选"
        risk_level = "high"
        requires_second_confirm = True
    elif is_overdue:
        action_type = "escalate"
        reason = "已超期仍未完成闭环，升级提醒"
        risk_level = "medium"

    return {
        "action_id": build_action_id("abnormal_sql", governance_id, action_type),
        "governance_type": "abnormal_sql",
        "governance_id": governance_id,
        "governance_week": text(governance_record.get("governance_week")),
        "action_type": action_type,
        "action_reason": reason,
        "risk_level": risk_level,
        "requires_second_confirm": requires_second_confirm,
        "confirm_owner": text(feedback.get("actual_owner") or governance_record.get("owner_name")),
        "confirm_deadline": (now.date() + timedelta(days=3)).isoformat() if requires_second_confirm else "",
        "execution_status": "pending",
        "execution_result": "",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def plan_ds_zombie_action(
    zombie_record: dict[str, Any],
    feedback: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    feedback = feedback or {}
    governance_id = text(zombie_record.get("zombie_governance_id") or zombie_record.get("governance_id"))
    still_in_use = is_yes(feedback.get("still_in_use"))
    can_offline = is_yes(feedback.get("can_offline"))
    keep_required = is_yes(feedback.get("keep_required"))

    action_type = "continue_observe"
    reason = "默认继续观察"
    risk_level = "low"
    requires_second_confirm = False

    if still_in_use or keep_required:
        action_type = "continue_observe"
        reason = "用户确认仍在使用或需要保留"
    elif can_offline:
        action_type = "offline_candidate"
        reason = "用户确认可下线，进入下线候选"
        risk_level = "high"
        requires_second_confirm = True
    elif boolish(zombie_record.get("is_overdue")) is True:
        action_type = "escalate"
        reason = "疑似僵尸任务超期未反馈，升级提醒"
        risk_level = "medium"

    return {
        "action_id": build_action_id("ds_zombie_task", governance_id, action_type),
        "governance_type": "ds_zombie_task",
        "governance_id": governance_id,
        "governance_week": text(zombie_record.get("governance_week")),
        "action_type": action_type,
        "action_reason": reason,
        "risk_level": risk_level,
        "requires_second_confirm": requires_second_confirm,
        "confirm_owner": text(feedback.get("actual_owner") or zombie_record.get("owner_name")),
        "confirm_deadline": (now.date() + timedelta(days=3)).isoformat() if requires_second_confirm else "",
        "execution_status": "pending",
        "execution_result": "",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

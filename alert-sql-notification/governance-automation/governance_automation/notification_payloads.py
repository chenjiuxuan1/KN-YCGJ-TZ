"""Build notification payloads for n8n from governance notify candidates."""

from __future__ import annotations

import json
from typing import Any


GROUP_ALERT_ENDPOINT = "https://tv-service-alert.kuainiu.chat/alert/v2/array"


def text(value: Any) -> str:
    return str(value or "").strip()


def split_emails(value: Any) -> list[str]:
    raw = text(value)
    if not raw:
        return []
    separators = [",", ";", "，", "；", "\n"]
    parts = [raw]
    for separator in separators:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [part.strip() for part in parts if "@" in part]


def build_governance_message(record: dict[str, Any]) -> str:
    lines = [
        "StarRocks 大查询治理提醒",
        "",
        f"治理等级：{text(record.get('governance_level'))}",
        f"等级原因：{text(record.get('level_reason'))}",
        f"集群：{text(record.get('cluster'))}",
        f"用户：{text(record.get('query_user'))}",
        f"来源：{text(record.get('source_type'))}",
        f"SQL 指纹：{text(record.get('sql_fingerprint'))}",
        f"本轮告警次数：{text(record.get('alert_count'))}",
        f"历史告警次数：{text(record.get('history_alert_count'))}",
        f"首次告警：{text(record.get('first_alert_time'))}",
        f"末次告警：{text(record.get('last_alert_time'))}",
        f"截止日期：{text(record.get('deadline'))}",
    ]
    if text(record.get("sample_sql_url")):
        lines.append(f"SQL 详情：{text(record.get('sample_sql_url'))}")
    if text(record.get("ds_project")) or text(record.get("ds_workflow")) or text(record.get("ds_task")):
        lines.extend(
            [
                "",
                "DS 信息：",
                f"项目：{text(record.get('ds_project'))}",
                f"工作流：{text(record.get('ds_workflow'))}",
                f"任务：{text(record.get('ds_task'))}",
            ]
        )
    lines.extend(
        [
            "",
            "请在治理表中确认负责人、整改方式和处理状态。",
            f"治理记录 ID：{text(record.get('governance_id'))}",
        ]
    )
    return "\n".join(lines)


def build_group_mentions(record: dict[str, Any]) -> list[str]:
    route = text(record.get("notify_route"))
    if route in {"operation_group", "mexico_aifox_group"}:
        return []
    if route == "weidu_group":
        return split_emails(record.get("owner_email"))
    return split_emails(record.get("owner_email"))


def build_notification_payload(record: dict[str, Any]) -> dict[str, Any]:
    channel = text(record.get("notify_channel"))
    message = build_governance_message(record)
    if channel == "group_bot":
        mentions = build_group_mentions(record)
        return {
            "governance_id": text(record.get("governance_id")),
            "governance_week": text(record.get("governance_week")),
            "notify_channel": "group_bot",
            "notify_route": text(record.get("notify_route")),
            "endpoint": GROUP_ALERT_ENDPOINT,
            "botId": text(record.get("notify_bot_id")),
            "message": message,
            "mentions": mentions,
            "payload_json": json.dumps(
                {
                    "botId": text(record.get("notify_bot_id")),
                    "message": message,
                    "mentions": mentions,
                },
                ensure_ascii=False,
            ),
        }

    return {
        "governance_id": text(record.get("governance_id")),
        "governance_week": text(record.get("governance_week")),
        "notify_channel": "sidecar",
        "notify_route": text(record.get("notify_route") or "owner_sidecar"),
        "target_email": text(record.get("owner_email")),
        "target_name": text(record.get("owner_name")),
        "message": message,
        "payload_json": json.dumps(
            {
                "targetEmail": text(record.get("owner_email")),
                "targetName": text(record.get("owner_name")),
                "message": message,
            },
            ensure_ascii=False,
        ),
    }


def build_notification_payloads(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads = []
    for record in records:
        if text(record.get("notify_channel")) == "pending_owner":
            continue
        payloads.append(build_notification_payload(record))
    return payloads

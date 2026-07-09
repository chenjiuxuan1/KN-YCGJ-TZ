"""In-memory upsert helpers for governance records.

These helpers model the intended table behavior. n8n or database code can
reuse the same merge rules when writing to Google Sheets, MySQL, or StarRocks.
"""

from __future__ import annotations

from typing import Any


UPSERT_KEY_FIELDS = ("country", "cluster", "source_type", "query_user", "sql_fingerprint")


def governance_key(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field) or "").strip().lower() for field in UPSERT_KEY_FIELDS)


def _max_numeric(left: Any, right: Any) -> float:
    def parse(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(parse(left), parse(right))


def _min_non_empty(left: Any, right: Any) -> str:
    values = [str(left or "").strip(), str(right or "").strip()]
    values = [value for value in values if value]
    return min(values) if values else ""


def _max_non_empty(left: Any, right: Any) -> str:
    values = [str(left or "").strip(), str(right or "").strip()]
    values = [value for value in values if value]
    return max(values) if values else ""


def merge_governance_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = {**existing, **incoming}
    merged["alert_count"] = int(float(existing.get("alert_count") or 0)) + int(float(incoming.get("alert_count") or 0))
    merged["history_alert_count"] = max(
        int(float(existing.get("history_alert_count") or 0)),
        int(float(incoming.get("history_alert_count") or 0)),
        merged["alert_count"],
    )
    merged["first_alert_time"] = _min_non_empty(existing.get("first_alert_time"), incoming.get("first_alert_time"))
    merged["last_alert_time"] = _max_non_empty(existing.get("last_alert_time"), incoming.get("last_alert_time"))
    for field in ("max_mem_usage", "max_cpu_time", "max_exec_time", "max_scan_rows"):
        merged[field] = _max_numeric(existing.get(field), incoming.get(field))
    if str(existing.get("governance_status") or "") in {"已关闭", "closed"}:
        merged["governance_status"] = "待认领"
    return merged


def upsert_governance_records(
    existing_records: list[dict[str, Any]],
    incoming_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {governance_key(record): dict(record) for record in existing_records}
    for record in incoming_records:
        key = governance_key(record)
        if key in by_key:
            by_key[key] = merge_governance_record(by_key[key], record)
        else:
            new_record = dict(record)
            new_record.setdefault("history_alert_count", new_record.get("alert_count", 0))
            new_record.setdefault("governance_status", "待认领")
            by_key[key] = new_record
    return list(by_key.values())


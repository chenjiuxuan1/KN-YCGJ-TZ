"""Apply user feedback to governance records."""

from __future__ import annotations

from typing import Any


def build_feedback_index(feedback_rows: list[dict[str, Any]], key_field: str = "governance_id") -> dict[str, dict[str, Any]]:
    index = {}
    for row in feedback_rows:
        key = str(row.get(key_field) or "").strip()
        if key:
            index[key] = row
    return index


def apply_abnormal_sql_feedback(
    governance_records: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    feedback_index = build_feedback_index(feedback_rows, "governance_id")
    updated = []
    for record in governance_records:
        item = dict(record)
        feedback = feedback_index.get(str(record.get("governance_id") or "").strip())
        if feedback:
            item["owner_name"] = feedback.get("actual_owner") or item.get("owner_name", "")
            item["owner_email"] = feedback.get("actual_owner_email") or item.get("owner_email", "")
            item["rectify_method"] = feedback.get("rectify_method") or item.get("rectify_method", "")
            item["governance_status"] = feedback.get("rectify_status") or item.get("governance_status", "")
            item["keep_required"] = feedback.get("keep_required") or ""
            item["keep_reason"] = feedback.get("keep_reason") or ""
            item["can_offline_ds"] = feedback.get("can_offline_ds") or ""
            item["expected_finish_date"] = feedback.get("expected_finish_date") or ""
            item["feedback_filled_by"] = feedback.get("filled_by") or ""
            item["feedback_filled_at"] = feedback.get("filled_at") or ""
            item["feedback_status"] = "processed"
        updated.append(item)
    return updated


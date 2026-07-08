"""Aggregate abnormal SQL rows into weekly governance records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .level_classifier import score_abnormal_sql
from .sql_fingerprint import build_sql_fingerprint


def _max_numeric(values: list[Any]) -> float:
    result = 0.0
    for value in values:
        try:
            result = max(result, float(value or 0))
        except (TypeError, ValueError):
            continue
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "已kill", "killed"}


def aggregate_abnormal_sql(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    fingerprints: dict[tuple[str, str, str, str], Any] = {}

    for row in rows:
        fp = build_sql_fingerprint(str(row.get("raw_sql") or row.get("sql") or ""))
        country = str(row.get("country") or "").strip().lower()
        cluster = str(row.get("cluster") or "").strip().lower()
        source_type = str(row.get("source_type") or "").strip().lower()
        user = str(row.get("user") or row.get("query_user") or "").strip().lower()
        key = (country, cluster, source_type, fp.fingerprint + "::" + user)
        grouped[key].append(row)
        fingerprints[key] = fp

    records: list[dict[str, Any]] = []
    for (country, cluster, source_type, fingerprint_user), items in grouped.items():
        fp = fingerprints[(country, cluster, source_type, fingerprint_user)]
        alert_times = sorted(str(item.get("alert_time") or "") for item in items if item.get("alert_time"))
        sample = items[-1]
        record = {
            "country": country,
            "cluster": cluster,
            "source_type": source_type,
            "query_user": str(sample.get("user") or sample.get("query_user") or ""),
            "executor": str(sample.get("executor") or ""),
            "sql_fingerprint": fp.fingerprint,
            "sql_fingerprint_text": fp.normalized_sql[:1000],
            "fingerprint_version": fp.version,
            "sample_query_id": str(sample.get("query_id") or ""),
            "sample_sql_url": str(sample.get("sql_url") or sample.get("optimized_sql_url") or ""),
            "alert_count": len(items),
            "first_alert_time": alert_times[0] if alert_times else "",
            "last_alert_time": alert_times[-1] if alert_times else "",
            "max_mem_usage": _max_numeric([item.get("mem_usage") for item in items]),
            "max_cpu_time": _max_numeric([item.get("cpu_time") for item in items]),
            "max_exec_time": _max_numeric([item.get("exec_time") for item in items]),
            "max_scan_rows": _max_numeric([item.get("scan_rows") for item in items]),
            "killed": any(_as_bool(item.get("killed")) for item in items),
            "ds_project": str(sample.get("ds_project") or ""),
            "ds_workflow": str(sample.get("ds_workflow") or ""),
            "ds_task": str(sample.get("ds_task") or ""),
        }
        score = score_abnormal_sql(record)
        record["governance_level"] = score.level
        record["governance_score"] = score.score
        record["level_reason"] = score.reason
        record["score_components"] = "|".join(
            f"{component.key}:{component.score}:{component.reason}" for component in score.components
        )
        records.append(record)

    return sorted(records, key=lambda row: (row["governance_level"], -int(row.get("governance_score") or 0), -int(row["alert_count"])))

"""A/B/C/D abnormal SQL governance scoring rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MEMORY_THRESHOLDS_BYTES = {
    "starrocks_ine": 60 * 1024**3,
    "starrocks_pak": 50 * 1024**3,
    "starrocks_ph": 50 * 1024**3,
    "starrocks_th": 50 * 1024**3,
    "starrocks_mex": 50 * 1024**3,
    "starrocks_cn": 50 * 1024**3,
}

CPU_THRESHOLDS_SECONDS = {
    "starrocks_ine": 3000,
    "starrocks_pak": 2000,
    "starrocks_ph": 2000,
    "starrocks_th": 2000,
    "starrocks_mex": 2000,
    "starrocks_cn": 2000,
}

SCAN_ROWS_THRESHOLD = 1_500_000_000
EXEC_TIME_THRESHOLD_SECONDS = 1000


@dataclass(frozen=True)
class GovernanceLevel:
    level: str
    reason: str


@dataclass(frozen=True)
class ScoreComponent:
    key: str
    score: int
    reason: str


@dataclass(frozen=True)
class AbnormalSqlScore:
    level: str
    score: int
    reason: str
    components: tuple[ScoreComponent, ...]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "已kill", "killed", "已杀死"}


def _add_ratio_component(
    components: list[ScoreComponent],
    *,
    key: str,
    value: float,
    threshold: float,
    full_score: int,
    high_score: int,
    base_score: int,
    label: str,
    unit: str = "",
) -> None:
    if value <= 0 or threshold <= 0:
        return
    ratio = value / threshold
    if ratio >= 2:
        score = full_score
        suffix = "超过阈值 2 倍"
    elif ratio >= 1.5:
        score = high_score
        suffix = "超过阈值 1.5 倍"
    elif ratio >= 1:
        score = base_score
        suffix = "超过阈值"
    else:
        return
    value_text = f"{value:.0f}{unit}" if unit else f"{value:.0f}"
    components.append(ScoreComponent(key, score, f"{label}{suffix}（当前 {value_text}，阈值 {threshold:.0f}{unit}）"))


def score_abnormal_sql(record: dict[str, Any]) -> AbnormalSqlScore:
    cluster = str(record.get("cluster") or "").lower()
    history_alert_count = int(as_float(record.get("history_alert_count")))
    current_week_alert_count = int(as_float(record.get("alert_count") or record.get("current_week_alert_count")))
    max_mem_usage = as_float(record.get("max_mem_usage") or record.get("mem_usage"))
    max_cpu_time = as_float(record.get("max_cpu_time") or record.get("cpu_time"))
    max_exec_time = as_float(record.get("max_exec_time") or record.get("exec_time"))
    max_scan_rows = as_float(record.get("max_scan_rows") or record.get("scan_rows"))
    killed = as_bool(record.get("killed"))
    source_type = str(record.get("source_type") or "").lower()
    last_week_notified = as_bool(record.get("last_week_notified"))
    still_exists = as_bool(record.get("still_exists"))
    owner_resolved = bool(record.get("owner_name") or record.get("resolved_owner"))
    memory_threshold = MEMORY_THRESHOLDS_BYTES.get(cluster, 50 * 1024**3)
    cpu_threshold = CPU_THRESHOLDS_SECONDS.get(cluster, 2000)
    components: list[ScoreComponent] = []

    if str(record.get("governance_status") or "").strip().lower() in {"已关闭", "closed"}:
        return AbnormalSqlScore("D", 0, "已关闭后偶发或无需处理", tuple())

    if history_alert_count >= 10:
        components.append(ScoreComponent("history_alert_count", 85, "历史同指纹告警次数 >= 10"))
    elif history_alert_count >= 5:
        components.append(ScoreComponent("history_alert_count", 70, "历史同指纹告警次数 >= 5"))
    elif history_alert_count >= 3:
        components.append(ScoreComponent("history_alert_count", 35, "历史同指纹告警次数 >= 3"))
    elif history_alert_count >= 2:
        components.append(ScoreComponent("history_alert_count", 20, "历史同指纹告警次数 >= 2"))

    if current_week_alert_count >= 5:
        components.append(ScoreComponent("current_week_alert_count", 80, "本周同指纹告警次数 >= 5"))
    elif current_week_alert_count >= 3:
        components.append(ScoreComponent("current_week_alert_count", 70, "本周同指纹告警次数 >= 3"))
    elif current_week_alert_count >= 2:
        components.append(ScoreComponent("current_week_alert_count", 30, "本周同指纹重复出现"))

    _add_ratio_component(
        components,
        key="memory",
        value=max_mem_usage,
        threshold=memory_threshold,
        full_score=60,
        high_score=45,
        base_score=25,
        label="内存峰值",
        unit="B",
    )
    _add_ratio_component(
        components,
        key="cpu",
        value=max_cpu_time,
        threshold=cpu_threshold,
        full_score=45,
        high_score=32,
        base_score=18,
        label="CPU 耗时",
        unit="s",
    )
    _add_ratio_component(
        components,
        key="exec_time",
        value=max_exec_time,
        threshold=EXEC_TIME_THRESHOLD_SECONDS,
        full_score=35,
        high_score=25,
        base_score=15,
        label="执行耗时",
        unit="s",
    )
    _add_ratio_component(
        components,
        key="scan_rows",
        value=max_scan_rows,
        threshold=SCAN_ROWS_THRESHOLD,
        full_score=25,
        high_score=18,
        base_score=10,
        label="扫描行数",
    )

    if killed and source_type == "ds":
        components.append(ScoreComponent("killed_ds", 70, "DS 来源且已触发自动 Kill"))
    elif killed:
        components.append(ScoreComponent("killed", 35, "已触发自动 Kill"))

    if last_week_notified and still_exists:
        components.append(ScoreComponent("still_exists", 70, "上周已通知且本周仍出现"))

    if source_type == "ds" and owner_resolved:
        components.append(ScoreComponent("ds_owner_resolved", 15, "DS 来源且负责人已识别"))
    elif source_type == "ds":
        components.append(ScoreComponent("ds_source", 10, "DS 来源任务"))

    components.sort(key=lambda item: item.score, reverse=True)
    total_score = min(100, sum(item.score for item in components))

    if total_score >= 70:
        level = "A"
    elif total_score >= 45:
        level = "B"
    elif total_score >= 20:
        level = "C"
    else:
        level = "D"

    reason = "；".join(item.reason for item in components[:3]) if components else "单次触发且资源风险较低"
    return AbnormalSqlScore(level, total_score, reason, tuple(components))


def classify_governance_level(record: dict[str, Any]) -> GovernanceLevel:
    score = score_abnormal_sql(record)
    return GovernanceLevel(score.level, score.reason)

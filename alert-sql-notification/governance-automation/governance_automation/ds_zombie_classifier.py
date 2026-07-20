from datetime import datetime, timezone
from typing import Dict, List

from .ds_zombie_models import EvidenceState, ScoreResult, WorkflowSnapshot


def _days_since(value, now):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, (now - value).days)


def classify_workflow(
    snapshot: WorkflowSnapshot, now: datetime = None, score_version: str = "v1"
) -> ScoreResult:
    if score_version != "v1":
        raise ValueError("unsupported score version: %s" % score_version)
    now = now or datetime.now(timezone.utc)
    detail: Dict[str, int] = {}
    reasons: List[str] = []
    update_days = _days_since(snapshot.last_update_time, now)
    run_days = _days_since(snapshot.last_run_time, now)

    if update_days is not None and update_days >= 365:
        detail["stale_update_12m"] = 30
        reasons.append("超过12个月未更新")
    elif update_days is not None and update_days >= 180:
        detail["stale_update_6m"] = 20
        reasons.append("超过6个月未更新")
    elif update_days is not None and update_days >= 90:
        detail["stale_update_3m"] = 10
        reasons.append("超过3个月未更新")

    if snapshot.instance_scan_complete:
        if snapshot.total_runs_30d == 0:
            detail["zero_runs_30d"] = 25
            reasons.append("近30天零运行")
        if run_days is None or run_days >= 180:
            detail["stale_run_6m"] = 25
            reasons.append("超过6个月未运行")
    else:
        reasons.append("运行实例证据不完整")

    if snapshot.schedule_active is False:
        detail["schedule_offline"] = 10
        reasons.append("无当前生效上线调度")

    score = sum(detail.values())
    has_downstream = bool(snapshot.downstream_workflows)
    uncertain = not snapshot.dependency_scan_complete or not snapshot.instance_scan_complete
    recent_active = bool(snapshot.total_runs_30d and snapshot.total_runs_30d > 0)

    if snapshot.access_evidence == EvidenceState.UNKNOWN:
        reasons.append("访问证据未接入")
    if snapshot.confirmed_retention:
        reasons.append("负责人已确认保留")
        return ScoreResult("D", "KEEP_CONFIRMED", score, tuple(reasons), detail)
    if snapshot.workflow_online is True:
        reasons.append("工作流定义仍上线")
        return ScoreResult("D", "KEEP_ACTIVE", score, tuple(reasons), detail)
    if snapshot.active_instance_present is True:
        reasons.append("存在运行中或等待中的实例")
        return ScoreResult("D", "KEEP_ACTIVE", score, tuple(reasons), detail)
    if has_downstream:
        reasons.append("存在跨工作流下游依赖")
        return ScoreResult(
            "D", "RETAIN_AND_ASSESS", score, tuple(reasons), detail,
            protected_by_dependency=True,
        )
    if recent_active or (run_days is not None and run_days <= 30):
        reasons.append("近期仍有运行")
        return ScoreResult("D", "KEEP_ACTIVE", score, tuple(reasons), detail)
    if uncertain:
        reasons.append("上下游或运行证据不完整")
        return ScoreResult(
            "C", "COLLECT_EVIDENCE", score, tuple(reasons), detail,
            protected_by_uncertainty=True,
        )
    if snapshot.resource_reference_count or snapshot.data_reference_count:
        reasons.append("存在资源或数据引用")
        return ScoreResult("B", "OWNER_CONFIRMATION", score, tuple(reasons), detail)
    if score >= 60:
        return ScoreResult("A", "REQUEST_DECOMMISSION_CONFIRMATION", score, tuple(reasons), detail)
    if score >= 30:
        return ScoreResult("B", "OWNER_CONFIRMATION", score, tuple(reasons), detail)
    return ScoreResult("C", "OBSERVE", score, tuple(reasons), detail)

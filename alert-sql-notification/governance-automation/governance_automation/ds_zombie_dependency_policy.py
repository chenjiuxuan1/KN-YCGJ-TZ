"""Classify downstream references by whether the consumer is still active."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


@dataclass(frozen=True)
class DownstreamAssessment:
    active_codes: Tuple[str, ...]
    review_codes: Tuple[str, ...]


def _truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "online")


def assess_downstream_activity(
    *, downstream_codes: Tuple[str, ...], workflows: Mapping[str, Mapping[str, Any]]
) -> DownstreamAssessment:
    """Hard-protect only consumers that are scheduled, recent, or still executing."""
    active, review = [], []
    for code in downstream_codes:
        row = workflows.get(code)
        if not row:
            review.append(code)
            continue
        if (
            _truthy(row.get("schedule_active"))
            or int(row.get("total_runs_30d") or 0) > 0
            or _truthy(row.get("active_instance_present"))
        ):
            active.append(code)
        else:
            review.append(code)
    return DownstreamAssessment(tuple(active), tuple(review))

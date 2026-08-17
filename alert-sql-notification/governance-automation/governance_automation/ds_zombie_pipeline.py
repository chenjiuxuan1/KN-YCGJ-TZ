from collections import Counter, defaultdict, deque
from itertools import groupby
from typing import Any, Dict, Iterable, List

MAX_TOP_CANDIDATES = 200


def _project_bucket_key(row: Dict[str, Any]) -> str:
    return str(row.get("project_code") or row.get("workflow_code") or "")


def _stratify_by_project(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort by score_total desc, but round-robin across projects within each
    tied score so a handful of early-created (low workflow_code) projects
    can't consume the whole top-N budget when many rows share a score."""
    ordered = sorted(rows, key=lambda row: int(row.get("score_total") or 0), reverse=True)
    result: List[Dict[str, Any]] = []
    for _, group_iter in groupby(ordered, key=lambda row: int(row.get("score_total") or 0)):
        group = list(group_iter)
        if len(group) <= 1:
            result.extend(group)
            continue
        buckets: Dict[str, deque] = defaultdict(deque)
        bucket_order: List[str] = []
        for row in group:
            key = _project_bucket_key(row)
            if key not in buckets:
                bucket_order.append(key)
            buckets[key].append(row)
        while bucket_order:
            for key in list(bucket_order):
                result.append(buckets[key].popleft())
                if not buckets[key]:
                    bucket_order.remove(key)
    return result


def build_summary(
    country: str,
    batch_id: str,
    score_version: str,
    scanned_workflows: int,
    candidates: Iterable[Dict[str, Any]],
    persisted_count: int,
    top_limit: int = 0,
    scanned_level_summary: Dict[str, int] = None,
) -> Dict[str, Any]:
    if top_limit < 0:
        raise ValueError("top_limit must be zero or greater")
    rows: List[Dict[str, Any]] = list(candidates)
    levels = Counter(str(row.get("level") or "C") for row in rows)
    top = _stratify_by_project(rows)
    if top_limit:
        top = top[:min(top_limit, MAX_TOP_CANDIDATES)]
    else:
        top = top[:MAX_TOP_CANDIDATES]
    return {
        "success": True,
        "batch_id": batch_id,
        "country": country,
        "score_version": score_version,
        "scanned_workflows": scanned_workflows,
        "candidate_count": len(rows),
        "persisted_count": persisted_count,
        "level_summary": {level: levels.get(level, 0) for level in "ABCD"},
        "scanned_level_summary": scanned_level_summary or {level: levels.get(level, 0) for level in "ABCD"},
        "dependency_protected_count": sum(bool(row.get("protected_by_dependency")) for row in rows),
        "uncertain_dependency_count": sum(bool(row.get("protected_by_uncertainty")) for row in rows),
        "top_candidates": top,
        "detail_storage": "governance_db" if persisted_count else "dry_run",
    }

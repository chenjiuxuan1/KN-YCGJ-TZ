from collections import Counter
from typing import Any, Dict, Iterable, List


def build_summary(
    country: str,
    batch_id: str,
    score_version: str,
    scanned_workflows: int,
    candidates: Iterable[Dict[str, Any]],
    persisted_count: int,
    top_limit: int = 0,
) -> Dict[str, Any]:
    if top_limit < 0:
        raise ValueError("top_limit must be zero or greater")
    rows: List[Dict[str, Any]] = list(candidates)
    levels = Counter(str(row.get("level") or "C") for row in rows)
    top = sorted(rows, key=lambda row: int(row.get("score_total") or 0), reverse=True)
    if top_limit:
        top = top[:top_limit]
    return {
        "success": True,
        "batch_id": batch_id,
        "country": country,
        "score_version": score_version,
        "scanned_workflows": scanned_workflows,
        "candidate_count": len(rows),
        "persisted_count": persisted_count,
        "level_summary": {level: levels.get(level, 0) for level in "ABCD"},
        "dependency_protected_count": sum(bool(row.get("protected_by_dependency")) for row in rows),
        "uncertain_dependency_count": sum(bool(row.get("protected_by_uncertainty")) for row in rows),
        "top_candidates": top,
        "detail_storage": "governance_db" if persisted_count else "dry_run",
    }

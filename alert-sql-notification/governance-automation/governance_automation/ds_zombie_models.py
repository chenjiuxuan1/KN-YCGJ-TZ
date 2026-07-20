from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Tuple


class EvidenceState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass
class WorkflowSnapshot:
    country: str
    project_code: str
    workflow_code: str
    project_name: str = ""
    workflow_name: str = ""
    owner_name: str = ""
    last_update_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    total_runs_30d: Optional[int] = None
    failed_runs_30d: Optional[int] = None
    schedule_online: Optional[bool] = None
    schedule_active: Optional[bool] = None
    workflow_online: Optional[bool] = None
    active_instance_present: Optional[bool] = None
    instance_scan_complete: bool = False
    dependency_scan_complete: bool = False
    upstream_workflows: Tuple[str, ...] = ()
    downstream_workflows: Tuple[str, ...] = ()
    resource_reference_count: int = 0
    data_reference_count: int = 0
    access_evidence: EvidenceState = EvidenceState.UNKNOWN
    confirmed_retention: bool = False

    @property
    def key(self) -> str:
        return ":".join((self.country, self.project_code, self.workflow_code))


@dataclass
class ScoreResult:
    level: str
    action: str
    score_total: int
    reasons: Tuple[str, ...]
    score_detail: Dict[str, int] = field(default_factory=dict)
    protected_by_dependency: bool = False
    protected_by_uncertainty: bool = False

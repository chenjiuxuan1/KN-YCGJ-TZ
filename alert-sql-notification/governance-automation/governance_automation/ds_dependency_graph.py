import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, DefaultDict, Dict, Iterable, List, Set


@dataclass
class DependencyGraph:
    task_upstream: DefaultDict[str, DefaultDict[str, Set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    task_downstream: DefaultDict[str, DefaultDict[str, Set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    workflow_upstream: DefaultDict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    workflow_downstream: DefaultDict[str, Set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    scan_complete: DefaultDict[str, bool] = field(
        default_factory=lambda: defaultdict(lambda: True)
    )
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    parse_error_count: int = 0


def _walk_dependency_items(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        lowered = {str(key).lower(): item for key, item in value.items()}
        definition = (
            lowered.get("definitioncode")
            or lowered.get("processdefinitioncode")
            or lowered.get("process_definition_code")
        )
        if definition not in (None, "", 0, "0"):
            yield value
        for nested in value.values():
            yield from _walk_dependency_items(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dependency_items(nested)


def _value(item: Dict[str, Any], *names: str) -> str:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, "", 0, "0"):
            return str(value)
    return ""


def build_dependency_graph(
    relation_rows: Iterable[Dict[str, Any]], task_rows: Iterable[Dict[str, Any]]
) -> DependencyGraph:
    graph = DependencyGraph()
    for row in relation_rows:
        workflow = str(row.get("workflow_code") or "")
        pre = str(row.get("pre_task_code") or "")
        post = str(row.get("post_task_code") or "")
        if workflow and pre and post and pre != "0":
            graph.task_downstream[workflow][pre].add(post)
            graph.task_upstream[workflow][post].add(pre)

    for row in task_rows:
        if str(row.get("task_type") or "").upper() != "DEPENDENT":
            continue
        source = str(row.get("workflow_code") or "")
        graph.scan_complete[source] = True
        raw = row.get("task_params") or "{}"
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            targets = list(_walk_dependency_items(payload))
            if not targets:
                raise ValueError("no workflow code in DEPENDENT parameters")
            for item in targets:
                target = _value(
                    item,
                    "definitionCode",
                    "processDefinitionCode",
                    "process_definition_code",
                )
                if not target:
                    continue
                graph.workflow_upstream[source].add(target)
                graph.workflow_downstream[target].add(source)
                graph.evidence.append(
                    {
                        "source_workflow_code": source,
                        "target_workflow_code": target,
                        "target_project_code": _value(item, "projectCode", "project_code"),
                        "target_task_code": _value(item, "depTaskCode", "taskCode", "task_code"),
                        "dependency_type": "DEPENDENT",
                        "parse_status": "SUCCESS",
                    }
                )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            graph.scan_complete[source] = False
            graph.parse_error_count += 1
            graph.evidence.append(
                {
                    "source_workflow_code": source,
                    "dependency_type": "DEPENDENT",
                    "parse_status": "FAILED",
                    "evidence_hash": hashlib.sha256(str(raw).encode("utf-8")).hexdigest(),
                    "error": str(exc)[:160],
                }
            )
    return graph


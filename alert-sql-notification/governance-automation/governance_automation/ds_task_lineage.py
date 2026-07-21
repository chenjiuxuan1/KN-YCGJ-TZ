"""Conservative task SQL and resource evidence extraction for DS governance."""

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Iterable, Tuple

from .sql_fingerprint import strip_sql_comments


_NAME = r"(?:`?([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){0,2})`?)"
_WRITE_RE = re.compile(
    r"\b(?:insert\s+(?:(?:overwrite|into)\s+)*(?:table\s+)?|merge\s+into\s+|replace\s+into\s+)" + _NAME,
    re.IGNORECASE,
)
_CREATE_AS_RE = re.compile(
    r"\bcreate\s+(?:table\s+)?(?:if\s+not\s+exists\s+)?" + _NAME + r"\s+(?:as\s+)?select\b",
    re.IGNORECASE,
)
_READ_RE = re.compile(r"\b(?:from|join)\s+" + _NAME, re.IGNORECASE)
_CTE_RE = re.compile(r"(?:\bwith|,)\s*`?([a-zA-Z_][\w]*)`?\s+as\s*\(", re.IGNORECASE)
_DYNAMIC_RE = re.compile(r"\b(?:spark|session)\.sql\s*\(\s*[a-zA-Z_$][\w$]*\s*\)|\$\{[^}]+\}", re.IGNORECASE)
_PYTHON_IMPORT_RE = re.compile(r"(?m)^[ \t]*from[ \t]+[A-Za-z_][\w.]*[ \t]+import[^\r\n]*$")


@dataclass(frozen=True)
class TaskTableEvidence:
    status: str
    write_tables: Tuple[str, ...] = ()
    read_tables: Tuple[str, ...] = ()
    resource_refs: Tuple[str, ...] = ()


def _unique(items: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted({item.strip().lower() for item in items if item and item.strip()}))


def _resource_refs(params: Dict[str, Any]) -> Tuple[str, ...]:
    values = params.get("resourceList") or params.get("resource_list") or []
    if isinstance(values, dict):
        values = [values]
    refs = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict):
            refs.append(str(item.get("fullName") or item.get("resourceName") or item.get("name") or ""))
    return _unique(refs)


def parse_task_params(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def task_script(params: Dict[str, Any]) -> str:
    for key in ("sql", "rawScript", "script", "content", "sqlText"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def extract_task_table_evidence(sql: str, params: Dict[str, Any] = None) -> TaskTableEvidence:
    params = params or {}
    text = strip_sql_comments(sql or "")
    text = _PYTHON_IMPORT_RE.sub("", text)
    refs = _resource_refs(params)
    if not text.strip():
        return TaskTableEvidence("partial" if refs else "none", resource_refs=refs)
    if _DYNAMIC_RE.search(text):
        return TaskTableEvidence("incomplete", resource_refs=refs)
    ctes = {match.group(1).lower() for match in _CTE_RE.finditer(text)}
    writes = [match.group(1) for match in _WRITE_RE.finditer(text)]
    writes.extend(match.group(1) for match in _CREATE_AS_RE.finditer(text))
    reads = [match.group(1) for match in _READ_RE.finditer(text)]
    write_tables = _unique(writes)
    read_tables = tuple(table for table in _unique(reads) if table.split(".")[-1] not in ctes)
    return TaskTableEvidence("available" if write_tables or read_tables else "none", write_tables, read_tables, refs)


def build_table_consumers(task_rows: Iterable[Dict[str, Any]]) -> Dict[str, list]:
    """Index read tables to task locations; caller supplies active workflow state."""
    consumers: Dict[str, list] = {}
    for row in task_rows:
        evidence = extract_task_table_evidence(str(row.get("sql") or ""), row.get("params") or {})
        for table in evidence.read_tables:
            consumers.setdefault(table, []).append({
                "project_name": str(row.get("project_name") or "未知项目"),
                "workflow_code": str(row.get("workflow_code") or ""),
                "workflow_name": str(row.get("workflow_name") or "未知工作流"),
                "task_code": str(row.get("task_code") or ""),
                "task_name": str(row.get("task_name") or "未命名任务"),
                "active": bool(row.get("active")),
                "source": "内嵌任务SQL",
            })
    for table in consumers:
        consumers[table].sort(key=lambda item: (not item["active"], item["project_name"], item["workflow_name"], item["task_name"]))
    return consumers

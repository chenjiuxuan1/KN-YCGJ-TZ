"""DolphinScheduler metadata schema abstraction across DS versions.

DS 3.x renamed core tables (``t_ds_process_definition`` ->
``t_ds_workflow_definition``, ...) and their columns (``process_definition_code``
-> ``workflow_definition_code``). Different countries run different DS
versions, so scan SQL must be built against the schema that actually exists.
This module centralises the table/column names and read-only detection.
"""

from __future__ import annotations

from typing import Any, Optional

DS_SCHEMA_NEW: dict[str, str] = {
    "workflow_definition": "t_ds_workflow_definition",
    "workflow_task_relation": "t_ds_workflow_task_relation",
    "workflow_instance": "t_ds_workflow_instance",
    "schedules": "t_ds_schedules",
    "workflow_definition_code": "workflow_definition_code",
    "workflow_definition_version": "workflow_definition_version",
}

DS_SCHEMA_LEGACY: dict[str, str] = {
    "workflow_definition": "t_ds_process_definition",
    "workflow_task_relation": "t_ds_process_task_relation",
    "workflow_instance": "t_ds_process_instance",
    "schedules": "t_ds_schedules",
    "workflow_definition_code": "process_definition_code",
    "workflow_definition_version": "process_definition_version",
}

DS_SCHEMA_ALIASES: dict[str, str] = {
    "new": "new",
    "v3": "new",
    "3": "new",
    "workflow": "new",
    "legacy": "legacy",
    "old": "legacy",
    "v2": "legacy",
    "2": "legacy",
    "process": "legacy",
}

# Per-country override once verified. Leave empty to default to the new schema;
# set to "legacy" after ``--schema-check`` confirms a country runs an old DS.
DS_SCHEMA_BY_COUNTRY: dict[str, str] = {}

SCHEMA_PROBE_TABLES: dict[str, str] = {
    "new": DS_SCHEMA_NEW["workflow_definition"],
    "legacy": DS_SCHEMA_LEGACY["workflow_definition"],
}


def resolve_ds_schema(schema: Optional[str] = None, country: str = "") -> str:
    """Return "new" or "legacy". Explicit ``schema`` wins over country default."""
    if schema:
        key = str(schema).strip().lower()
        if key in DS_SCHEMA_ALIASES:
            return DS_SCHEMA_ALIASES[key]
        raise ValueError(f"未知 DS schema: {schema!r}（可选 new/legacy）")
    if country:
        return DS_SCHEMA_BY_COUNTRY.get(str(country).strip().lower(), "new")
    return "new"


def ds_schema_names(schema: Optional[str] = None, country: str = "") -> dict[str, str]:
    if resolve_ds_schema(schema, country) == "legacy":
        return DS_SCHEMA_LEGACY
    return DS_SCHEMA_NEW


def build_schema_probe_sql() -> str:
    """Read-only probe against ``information_schema.tables`` for both table names."""
    tables = sorted(set(SCHEMA_PROBE_TABLES.values()))
    in_list = ", ".join(f"'{table}'" for table in tables)
    return (
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = DATABASE() AND table_name IN ({in_list})"
    )


def detect_ds_schema(rows: list[dict[str, Any]]) -> Optional[str]:
    """Map probe rows to "new"/"legacy" or None when neither table exists."""
    found = {str(row.get("table_name") or "") for row in rows}
    if SCHEMA_PROBE_TABLES["new"] in found:
        return "new"
    if SCHEMA_PROBE_TABLES["legacy"] in found:
        return "legacy"
    return None

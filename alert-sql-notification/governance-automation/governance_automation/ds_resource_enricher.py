"""Resolve DolphinScheduler shell task resource references into searchable text."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


RESOURCE_EXTENSIONS = (".sql", ".sh", ".py", ".hql")
RESOURCE_REF_RE = re.compile(
    r"(?P<path>(?:[\w./-]+/)?[\w.-]+(?:\.sql|\.sh|\.py|\.hql))",
    re.IGNORECASE,
)


def text(value: Any) -> str:
    return str(value or "").strip()


def parse_resource_list(value: Any) -> list[str]:
    raw = text(value)
    if not raw or raw.lower() == "null":
        return []

    results: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw

    def walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            for key in ("resourceName", "resource_name", "name", "fileName", "file_name", "fullName", "full_name"):
                if text(item.get(key)):
                    results.append(text(item.get(key)))
            for child in item.values():
                if isinstance(child, (dict, list)):
                    walk(child)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        item_text = text(item)
        if item_text:
            results.append(item_text)

    walk(parsed)
    return dedupe(results)


def extract_resource_refs(row: dict[str, Any]) -> list[str]:
    values = [
        row.get("资源列表"),
        row.get("resource_list"),
        row.get("resource_refs"),
        row.get("task_params"),
        row.get("script"),
        row.get("raw_script"),
        row.get("script_content"),
        row.get("sql_content"),
    ]
    refs: list[str] = []
    for value in values:
        refs.extend(parse_resource_list(value))
        for match in RESOURCE_REF_RE.finditer(text(value)):
            refs.append(match.group("path"))
    return [ref for ref in dedupe(refs) if ref.lower().endswith(RESOURCE_EXTENSIONS)]


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        item = text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def candidate_paths(ref: str, resource_roots: list[Path]) -> list[Path]:
    normalized = text(ref).lstrip("/")
    candidates: list[Path] = []
    for root in resource_roots:
        root = root.expanduser()
        candidates.append(root / normalized)
        candidates.append(root / Path(normalized).name)
        if "resources/" in normalized:
            candidates.append(root / normalized.split("resources/", 1)[1])
    return dedupe_paths(candidates)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    output: list[Path] = []
    for path in paths:
        marker = str(path)
        if marker in seen:
            continue
        seen.add(marker)
        output.append(path)
    return output


def read_resource_text(ref: str, resource_roots: list[Path], *, max_bytes: int = 2_000_000) -> tuple[str, str]:
    for path in candidate_paths(ref, resource_roots):
        if not path.is_file():
            continue
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace"), str(path)
    return "", ""


def enrich_task_row_with_resources(
    row: dict[str, Any],
    resource_roots: list[Path],
    *,
    max_bytes_per_file: int = 2_000_000,
) -> dict[str, Any]:
    item = dict(row)
    refs = extract_resource_refs(item)
    contents: list[str] = []
    found_paths: list[str] = []
    for ref in refs:
        content, path = read_resource_text(ref, resource_roots, max_bytes=max_bytes_per_file)
        if content:
            contents.append(f"-- DS_RESOURCE_BEGIN: {ref}\n{content}\n-- DS_RESOURCE_END: {ref}")
            found_paths.append(path)

    base_script = "\n".join(
        part
        for part in (
            text(item.get("script_content")),
            text(item.get("sql_content")),
            text(item.get("raw_script")),
            text(item.get("script")),
        )
        if part
    )
    item["resource_refs"] = "\n".join(refs)
    item["resolved_resource_paths"] = "\n".join(found_paths)
    item["resource_content"] = "\n\n".join(contents)
    item["resolved_script_content"] = "\n\n".join(part for part in (base_script, item["resource_content"]) if part)
    item["resource_resolve_status"] = "resolved" if found_paths else ("no_resource_refs" if not refs else "resource_not_found")
    return item


def enrich_task_rows_with_resources(
    rows: list[dict[str, Any]],
    resource_roots: list[Path],
    *,
    max_bytes_per_file: int = 2_000_000,
) -> list[dict[str, Any]]:
    return [
        enrich_task_row_with_resources(row, resource_roots, max_bytes_per_file=max_bytes_per_file)
        for row in rows
    ]

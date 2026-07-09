"""File IO helpers for the first runnable governance pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def read_records(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(item) for item in data]
        if isinstance(data, dict):
            for key in ("rows", "data", "items", "records"):
                if isinstance(data.get(key), list):
                    return [dict(item) for item in data[key]]
        raise ValueError(f"JSON input must be a list or contain rows/data/items/records: {file_path}")
    if suffix in {".csv", ".txt"}:
        with file_path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]
    raise ValueError(f"Unsupported input file type: {file_path}")


def write_records(path: str | Path, rows: list[dict[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        file_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if suffix in {".csv", ".txt"}:
        fieldnames = collect_fieldnames(rows)
        with file_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return
    raise ValueError(f"Unsupported output file type: {file_path}")


def collect_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    return fieldnames


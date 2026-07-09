#!/usr/bin/env python3
"""Add Shell referenced resource contents to exported DS task metadata CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from governance_automation.ds_resource_enricher import enrich_task_rows_with_resources
from governance_automation.io_utils import write_csv


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve DS Shell task resource files into metadata CSV.")
    parser.add_argument("--input", required=True, help="DS task metadata CSV.")
    parser.add_argument("--output", required=True, help="Output enriched CSV.")
    parser.add_argument(
        "--resource-root",
        action="append",
        required=True,
        help="DS resource repository root. Can be provided more than once.",
    )
    parser.add_argument("--max-bytes-per-file", type=int, default=2_000_000)
    args = parser.parse_args()

    rows = read_csv(Path(args.input))
    enriched = enrich_task_rows_with_resources(
        rows,
        [Path(item) for item in args.resource_root],
        max_bytes_per_file=args.max_bytes_per_file,
    )
    write_csv(Path(args.output), enriched)

    resolved = sum(1 for row in enriched if row.get("resource_resolve_status") == "resolved")
    not_found = sum(1 for row in enriched if row.get("resource_resolve_status") == "resource_not_found")
    print(f"input rows: {len(rows)}")
    print(f"resolved resources: {resolved}")
    print(f"resource refs not found: {not_found}")
    print(f"wrote: {args.output}")


if __name__ == "__main__":
    main()

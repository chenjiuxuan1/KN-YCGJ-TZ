#!/usr/bin/env python3
"""Build n8n-ready notification payloads from notify candidates."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance_automation.io_utils import read_records, write_records
from governance_automation.notification_payloads import build_notification_payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="Build notification payloads.")
    parser.add_argument("--notify-candidates", required=True, help="CSV/JSON notify_candidates input.")
    parser.add_argument("--output", required=True, help="CSV/JSON payload output.")
    args = parser.parse_args()

    payloads = build_notification_payloads(read_records(args.notify_candidates))
    write_records(args.output, payloads)

    print(f"notification payloads: {len(payloads)}")


if __name__ == "__main__":
    main()

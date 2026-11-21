from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pushkey_migrations import build_cloud_migration_smoke_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local cloud storage migration smoke, restore checks, and emit a JSON report."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report to this path instead of stdout.",
    )
    args = parser.parse_args()

    report = build_cloud_migration_smoke_report()
    payload = json.dumps(report, indent=2, sort_keys=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

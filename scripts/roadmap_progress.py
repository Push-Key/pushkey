"""Calculate roadmap checklist progress.

The production roadmap can also contain explicitly marked post-launch agentic
items. Keep those separate so production readiness percentages stay honest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable


CHECKBOX_RE = re.compile(r"^- \[([ xX])\]", re.MULTILINE)
START_MARKER = "<!-- agentic-postlaunch:start -->"
END_MARKER = "<!-- agentic-postlaunch:end -->"
DEFAULT_ROADMAP = Path("docs/PRODUCTION_READINESS_PLAN.md")


class RoadmapProgressError(ValueError):
    """Raised when roadmap progress markers are malformed."""


def _empty_bucket() -> dict[str, float | int]:
    return {"done": 0, "total": 0, "percent": 0.0}


def _finish_bucket(bucket: dict[str, float | int]) -> dict[str, float | int]:
    total = int(bucket["total"])
    done = int(bucket["done"])
    percent = 0.0 if total == 0 else round(done / total * 100, 1)
    return {"done": done, "total": total, "percent": percent}


def _count_checkbox(line: str, bucket: dict[str, float | int]) -> None:
    match = CHECKBOX_RE.match(line)
    if not match:
        return
    bucket["total"] = int(bucket["total"]) + 1
    if match.group(1).lower() == "x":
        bucket["done"] = int(bucket["done"]) + 1


def calculate_progress(text: str) -> dict[str, dict[str, float | int]]:
    """Return production and post-launch checklist progress for markdown text."""

    production = _empty_bucket()
    agentic_postlaunch = _empty_bucket()
    in_agentic = False

    for line_number, line in enumerate(text.splitlines(), start=1):
        if START_MARKER in line:
            if in_agentic:
                raise RoadmapProgressError(
                    f"Nested agentic post-launch marker at line {line_number}"
                )
            in_agentic = True
            continue

        if END_MARKER in line:
            if not in_agentic:
                raise RoadmapProgressError(
                    f"Unexpected agentic post-launch end marker at line {line_number}"
                )
            in_agentic = False
            continue

        _count_checkbox(line, agentic_postlaunch if in_agentic else production)

    if in_agentic:
        raise RoadmapProgressError("Unclosed agentic post-launch marker")

    return {
        "production": _finish_bucket(production),
        "agentic_postlaunch": _finish_bucket(agentic_postlaunch),
    }


def _format_human(result: dict[str, dict[str, float | int]]) -> Iterable[str]:
    for name in ("production", "agentic_postlaunch"):
        bucket = result[name]
        label = name.replace("_", " ").title()
        yield (
            f"{label}: {bucket['done']}/{bucket['total']} "
            f"= {bucket['percent']:.1f}%"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roadmap",
        nargs="?",
        type=Path,
        default=DEFAULT_ROADMAP,
        help=f"Roadmap markdown file, default: {DEFAULT_ROADMAP}",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    try:
        text = args.roadmap.read_text(encoding="utf-8")
        result = calculate_progress(text)
    except (OSError, RoadmapProgressError) as exc:
        print(f"roadmap_progress: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("\n".join(_format_human(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

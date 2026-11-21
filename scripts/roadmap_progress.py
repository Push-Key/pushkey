"""Calculate roadmap checklist progress, split by what each item actually gates.

One number cannot answer both "can we invite real users?" and "are we ready to
sell this publicly?". Items that need a code-signing certificate, hosted backup
infrastructure, or a paid third-party audit cannot move until money and
external parties are involved, and counting them against alpha readiness makes
the product look further from usable than it is.

So the roadmap is bucketed by marker comments and this script reports each
bucket separately:

- `alpha_launch` (default, unmarked): everything that gates putting the product
  in front of real users.
- `public_beta_gate`: signing, hosted backup/restore/rollback evidence,
  independent security review, and penetration testing. Deferred, not dropped.
- `agentic_postlaunch`: post-launch review items.

Deferring is a scheduling decision, never a quality one. Items in the deferred
buckets stay listed, stay unchecked, and stay counted in their own totals.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable


CHECKBOX_RE = re.compile(r"^- \[([ xX])\]", re.MULTILINE)
DEFAULT_ROADMAP = Path("docs/PRODUCTION_READINESS_PLAN.md")

#: Buckets other than `alpha_launch`, keyed by the marker pair that opens and
#: closes them. Anything outside every marked region counts toward
#: `alpha_launch`, the work that gates inviting real users.
#:
#: `public_beta_gate` holds work that is real but cannot start until money,
#: hosted infrastructure, or a third party is in play: code signing
#: certificates, hosted backup/restore drills, independent security review, and
#: penetration testing. Keeping it in its own bucket stops a checklist written
#: for GA from making alpha readiness look worse than it is, and stops deferred
#: work from quietly disappearing.
BUCKET_MARKERS = {
    "agentic_postlaunch": (
        "<!-- agentic-postlaunch:start -->",
        "<!-- agentic-postlaunch:end -->",
    ),
    "public_beta_gate": (
        "<!-- public-beta-gate:start -->",
        "<!-- public-beta-gate:end -->",
    ),
}

PRIMARY_BUCKET = "alpha_launch"
BUCKET_ORDER = (PRIMARY_BUCKET, "public_beta_gate", "agentic_postlaunch")

BUCKET_LABELS = {
    "alpha_launch": "Alpha launch",
    "public_beta_gate": "Public beta / GA gates (deferred)",
    "agentic_postlaunch": "Post-launch agentic review",
}


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
    """Return per-bucket checklist progress for roadmap markdown text.

    Everything outside a marked region counts toward `alpha_launch`. Each
    marker pair in `BUCKET_MARKERS` diverts its region into its own bucket.
    Regions may not nest or overlap, so every checkbox lands in exactly one
    bucket and no work can be double counted or dropped.
    """

    buckets = {name: _empty_bucket() for name in BUCKET_ORDER}
    open_bucket: str | None = None
    open_line = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        marker_handled = False
        for name, (start, end) in BUCKET_MARKERS.items():
            if start in line:
                if open_bucket is not None:
                    raise RoadmapProgressError(
                        f"{name} marker at line {line_number} opens inside the "
                        f"{open_bucket} region opened at line {open_line}; "
                        "roadmap bucket regions may not nest"
                    )
                open_bucket = name
                open_line = line_number
                marker_handled = True
                break
            if end in line:
                if open_bucket != name:
                    raise RoadmapProgressError(
                        f"Unexpected {name} end marker at line {line_number}"
                    )
                open_bucket = None
                marker_handled = True
                break
        if marker_handled:
            continue

        _count_checkbox(line, buckets[open_bucket or PRIMARY_BUCKET])

    if open_bucket is not None:
        raise RoadmapProgressError(
            f"Unclosed {open_bucket} marker opened at line {open_line}"
        )

    return {name: _finish_bucket(bucket) for name, bucket in buckets.items()}


def _format_human(result: dict[str, dict[str, float | int]]) -> Iterable[str]:
    for name in BUCKET_ORDER:
        bucket = result[name]
        yield (
            f"{BUCKET_LABELS[name]}: {bucket['done']}/{bucket['total']} "
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

"""Validate the security review findings table for structural consistency.

Checks `docs/security-review-findings-tracker.md`:
- every row has a recognized severity;
- every critical/high finding has a non-blank status, owner, and deadline;
- every row past initial triage (status not blank/Open) has a non-blank owner.

This does not judge whether findings are actually resolved, only that the
table is well-formed enough to trust as a tracking source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DOC = Path("docs/security-review-findings-tracker.md")
SEVERITIES = {"critical", "high", "medium", "low", "informational"}
BLOCKING_SEVERITIES = {"critical", "high"}


class FindingsTableError(ValueError):
    """Raised when the findings table is malformed."""


def _table_rows(doc_text: str) -> list[list[str]]:
    start = doc_text.find("## Findings Table")
    if start == -1:
        raise FindingsTableError("missing '## Findings Table' section")
    section = doc_text[start:]
    end = section.find("\n## ", 1)
    section = section if end == -1 else section[:end]
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        raise FindingsTableError("no table rows found")
    return rows[1:]  # drop header row


def validate(doc_text: str) -> list[str]:
    errors: list[str] = []
    for row in _table_rows(doc_text):
        if len(row) < 7:
            errors.append(f"malformed row (expected >=7 columns): {row}")
            continue
        finding_id, _title, severity, _component, status, owner, deadline = row[:7]
        if not finding_id or "none yet" in finding_id.lower():
            continue
        sev = severity.lower()
        if sev not in SEVERITIES:
            errors.append(f"{finding_id}: unrecognized severity '{severity}'")
        if sev in BLOCKING_SEVERITIES:
            if not status:
                errors.append(f"{finding_id}: {severity} finding has no status")
            if not owner:
                errors.append(f"{finding_id}: {severity} finding has no owner")
            if not deadline:
                errors.append(f"{finding_id}: {severity} finding has no deadline")
        elif status and status.lower() != "open" and not owner:
            errors.append(f"{finding_id}: status '{status}' set but owner is blank")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args(argv)

    errors = validate(args.doc.read_text(encoding="utf-8"))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Findings table OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

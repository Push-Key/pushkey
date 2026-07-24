from pathlib import Path

import pytest

from scripts.security_findings_tracker import (
    FindingsTableError,
    validate,
)

HEADER = (
    "## Findings Table\n\n"
    "| ID | Title | Severity | Component/Surface | Status | Owner | Deadline | Evidence Link |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
)


def _doc(rows: str) -> str:
    return f"{HEADER}{rows}\n## Severity-To-SLA Mapping\n"


def test_empty_placeholder_table_is_valid():
    text = _doc("| _(none yet)_ | | | | | | | |\n")
    assert validate(text) == []


def test_current_shipped_template_is_valid():
    text = Path("docs/security-review-findings-tracker.md").read_text(encoding="utf-8")
    assert validate(text) == []


def test_missing_findings_table_section_raises():
    with pytest.raises(FindingsTableError):
        validate("# No table here\n")


def test_critical_finding_without_status_owner_deadline_errors():
    row = "| PEN-1 | SSRF | Critical | cloud API |  |  |  | |\n"
    errors = validate(_doc(row))
    assert any("no status" in e for e in errors)
    assert any("no owner" in e for e in errors)
    assert any("no deadline" in e for e in errors)


def test_critical_finding_fully_filled_is_valid():
    row = "| PEN-1 | SSRF | Critical | cloud API | Resolved | Alice | 2026-08-01 | PR #1 |\n"
    assert validate(_doc(row)) == []


def test_medium_finding_past_triage_without_owner_errors():
    row = "| PEN-2 | Info leak | Medium | admin portal | In Progress |  | 2026-08-15 | |\n"
    errors = validate(_doc(row))
    assert any("owner is blank" in e for e in errors)


def test_medium_finding_open_without_owner_is_allowed():
    row = "| PEN-2 | Info leak | Medium | admin portal | Open |  |  | |\n"
    assert validate(_doc(row)) == []


def test_unrecognized_severity_errors():
    row = "| PEN-3 | Odd | Severe | local API | Open | Bob | 2026-08-01 | |\n"
    errors = validate(_doc(row))
    assert any("unrecognized severity" in e for e in errors)

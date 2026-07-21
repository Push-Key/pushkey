from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_90_percent_checklist_records_capacity_and_rollback_evidence():
    checklist = (ROOT / "docs" / "90_PERCENT_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")

    assert "- [x] Add capacity-test and rollback-drill scripts or runbooks." in checklist
    assert "scripts\\alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750" in checklist
    assert "scripts\\alpha_rollback_drill.py" in checklist
    assert (ROOT / "scripts" / "alpha_capacity_smoke.py").is_file()
    assert (ROOT / "scripts" / "alpha_rollback_drill.py").is_file()
    assert (ROOT / "docs" / "alpha-capacity-results.json").is_file()
    assert (ROOT / "docs" / "alpha-rollback-drill-results.json").is_file()

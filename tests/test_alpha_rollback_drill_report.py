import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alpha_rollback_drill_report_records_successful_restore():
    report = json.loads((ROOT / "docs" / "alpha-rollback-drill-results.json").read_text(encoding="utf-8"))

    assert report["storage_mode"] == "alpha-flat-file"
    assert report["restored"] is True
    assert report["rto_seconds"] > 0
    assert report["rpo_seconds"] == 0
    for check in ("health", "vault", "activation_heartbeat", "support_ticket", "admin"):
        assert check in report["checks"]

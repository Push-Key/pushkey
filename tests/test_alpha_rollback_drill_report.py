import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alpha_rollback_drill_report_records_successful_restore():
    report = json.loads((ROOT / "docs" / "alpha-rollback-drill-results.json").read_text(encoding="utf-8"))

    datetime.fromisoformat(report["generated_at"])
    assert report["verification_scope"] == "local alpha-only"
    assert report["storage_mode"] == "alpha-encrypted-blob"
    assert report["restore_type"] == "destructive restore from local snapshot"
    assert report["scenario"].startswith("destructive restore")
    assert report["restored"] is True
    assert report["rto_seconds"] > 0
    assert report["rpo_seconds"] == 0
    assert "live alert delivery" in report["residual_risk"].lower()
    for check in ("health", "vault", "activation_heartbeat", "support_ticket", "admin"):
        assert check in report["checks"]

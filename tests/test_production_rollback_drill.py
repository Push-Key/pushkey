import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from scripts.production_rollback_drill import run_drill

ROOT = Path(__file__).resolve().parents[1]


def test_production_rollback_drill_runs_against_local_isolated_fixture_without_data_loss():
    result = run_drill()

    datetime.fromisoformat(result["generated_at"])
    assert result["verification_scope"] == "local isolated fixture"
    assert result["storage_mode"] == "production-postgresql-object-storage"
    assert result["rolled_back"] is True
    assert result["data_loss"] is False
    assert result["target_db_url_configured"] is False
    assert result["target_object_store_url_configured"] is False
    assert result["bad_deploy_release"] != result["rolled_back_to_release"]
    assert result["rto_seconds"] > 0
    assert result["rpo_seconds"] == 0
    for check in ("health", "pre_existing_session_restored", "login", "activation_heartbeat", "support_ticket", "admin_login"):
        assert check in result["checks"]
    assert "not been run against a real hosted" in result["residual_risk"]


def test_production_rollback_drill_records_configured_target_flags_without_claiming_hosted_run():
    result = run_drill(
        target_object_store_url="https://storage.example.invalid/pushkey-vault-prod",
    )

    assert result["target_object_store_url_configured"] is True
    assert result["target_db_url_configured"] is False
    assert "not wired into blob I/O yet" in result["object_storage_integration_note"]


def test_production_rollback_drill_script_writes_well_formed_evidence_json(tmp_path):
    output = tmp_path / "production-rollback-drill-results.json"

    completed = subprocess.run(
        [sys.executable, "scripts/production_rollback_drill.py", "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    datetime.fromisoformat(report["generated_at"])
    assert report["rolled_back"] is True
    assert report["data_loss"] is False
    assert report["storage_mode"] == "production-postgresql-object-storage"
    assert set(report["checks"]) == {
        "health",
        "pre_existing_session_restored",
        "login",
        "activation_heartbeat",
        "support_ticket",
        "admin_login",
    }

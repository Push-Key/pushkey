import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ops_readiness_documents_alpha_dashboard_targets_and_alert_routes():
    text = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8").lower()

    for target in (
        "auth",
        "sync",
        "activation",
        "storage",
        "email",
        "5xx",
        "rate-limit",
    ):
        assert target in text

    for route in (
        "primary operator",
        "secondary operator",
        "live accountable-operator mailbox",
        "backup accountable-operator mailbox",
    ):
        assert route in text


def test_ops_and_release_readiness_link_the_external_gate_handoff_checklist():
    release = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")
    ops = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8")

    assert "production-external-gate-handoff-checklist.md" in release
    assert "production-external-gate-handoff-checklist.md" in ops


def test_ops_readiness_forbids_plaintext_secret_telemetry():
    text = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8").lower()

    assert "must not include plaintext secrets" in text
    assert "request bodies" in text
    assert "authorization headers" in text
    assert "encrypted vault blob contents" in text


def test_backup_restore_runbook_records_alpha_and_production_storage_modes():
    text = (ROOT / "docs" / "backup-restore-runbook.md").read_text(encoding="utf-8").lower()

    for required in (
        "promoted production storage mode",
        "production-postgresql-object-storage",
        "postgresql snapshot or pitr identifier",
        "versioned object-storage blob",
        "alpha-encrypted-blob",
        "encrypted backup beta",
        "aggregate sha-256 hash",
        "application commit",
        "health",
        "license activation",
        "admin login",
        "upload/download",
        "production-rollback-drill-results.template.json",
    ):
        assert required in text


def test_production_rollback_template_records_hosted_drill_fields():
    template = json.loads(
        (ROOT / "docs" / "production-rollback-drill-results.template.json").read_text(encoding="utf-8")
    )

    assert template["verification_scope"] == "<hosted production>"
    assert "environment" in template
    assert "backup" in template
    assert "rollback" in template
    assert "restore" in template
    assert template["smoke_tests"] == [
        "health",
        "admin_login",
        "activation",
        "vault_blob_access",
    ]
    assert "residual_risk" in template

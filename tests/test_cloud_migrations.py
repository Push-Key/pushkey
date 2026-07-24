import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from pushkey_migrations import (
    MIGRATIONS,
    build_cloud_migration_smoke_report,
    import_legacy_dataset,
    migration_status,
    restore_legacy_dataset,
    rollback_plan,
    run_migrations,
)


def test_migrations_are_ordered_and_define_core_cloud_schema():
    names = [migration.name for migration in MIGRATIONS]

    assert names == sorted(names)
    combined = "\n".join(migration.sql for migration in MIGRATIONS)
    for table in (
        "users",
        "admins",
        "sessions",
        "licenses",
        "devices",
        "contacts",
        "tickets",
        "settings",
        "audits",
        "vault_revisions",
        "vault_revision_transactions",
        "outbox_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in combined
    assert "license_key_hash" in combined
    assert "reset_token_hash" in combined


def test_migrations_define_transactional_revision_and_outbox_metadata():
    combined = "\n".join(migration.sql for migration in MIGRATIONS)

    for column in (
        "revision_number INTEGER NOT NULL",
        "previous_etag TEXT",
        "object_sha256 TEXT NOT NULL",
        "idempotency_key TEXT",
        "request_id TEXT",
        "audit_id TEXT",
        "committed_at TEXT NOT NULL",
        "UNIQUE(user_id, revision_number)",
        "UNIQUE(user_id, idempotency_key)",
    ):
        assert column in combined

    for column in (
        "aggregate_type TEXT NOT NULL",
        "aggregate_id TEXT NOT NULL",
        "event_type TEXT NOT NULL",
        "payload_json TEXT NOT NULL",
        "dispatched_at TEXT",
        "idx_outbox_events_pending",
    ):
        assert column in combined


def test_migration_dry_run_and_apply_are_idempotent(tmp_path):
    db = tmp_path / "pushkey.sqlite"

    dry_run = run_migrations(db, dry_run=True)
    assert dry_run["applied"] == [migration.name for migration in MIGRATIONS]
    assert not db.exists()

    first = run_migrations(db)
    second = run_migrations(db)

    assert first["applied"] == [migration.name for migration in MIGRATIONS]
    assert second["applied"] == []
    assert migration_status(db)["current"] == MIGRATIONS[-1].name


def test_legacy_import_reconciles_counts_hashes_and_excludes_plaintext(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "users.json").write_text('{"u@example.com": {"hash": "h"}}', encoding="utf-8")
    (legacy / "licenses.json").write_text('{"PRO-1": {"tier": "pro"}}', encoding="utf-8")
    (legacy / "vaults").mkdir()
    (legacy / "vaults" / "abc.enc").write_bytes(b"encrypted-vault-blob")

    report = import_legacy_dataset(legacy, tmp_path / "export", dry_run=True)

    assert report["counts"] == {"users": 1, "licenses": 1, "vault_blobs": 1}
    assert report["hashes"]["vault_blobs"]
    assert "encrypted-vault-blob" not in str(report)


def test_legacy_import_writes_report_when_not_dry_run(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "users.json").write_text('{"u@example.com": {"hash": "h"}}', encoding="utf-8")
    (legacy / "licenses.json").write_text('{"PRO-1": {"tier": "pro"}}', encoding="utf-8")
    (legacy / "vaults").mkdir()
    (legacy / "vaults" / "abc.enc").write_bytes(b"encrypted-vault-blob")

    export = tmp_path / "export"
    report = import_legacy_dataset(legacy, export, dry_run=False)
    saved = json.loads((export / "import-report.json").read_text(encoding="utf-8"))

    assert saved == report
    assert saved["counts"] == {"users": 1, "licenses": 1, "vault_blobs": 1}


def test_legacy_restore_reconciles_metadata_and_encrypted_blobs(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "users.json").write_text('{"u@example.com": {"hash": "h"}}', encoding="utf-8")
    (legacy / "licenses.json").write_text('{"PRO-1": {"tier": "pro"}}', encoding="utf-8")
    (legacy / "vaults").mkdir()
    (legacy / "vaults" / "abc.enc").write_bytes(b"encrypted-vault-blob")

    restore_dir = tmp_path / "restore"
    dry_run = restore_legacy_dataset(legacy, restore_dir, dry_run=True)
    applied = restore_legacy_dataset(legacy, restore_dir, dry_run=False)
    saved = json.loads((restore_dir / "restore-report.json").read_text(encoding="utf-8"))

    assert dry_run["counts"] == {"users": 1, "licenses": 1, "vault_blobs": 1}
    assert dry_run["restored_files"] == ["users.json", "licenses.json", "vaults/abc.enc"]
    assert applied == saved
    assert saved["counts"] == {"users": 1, "licenses": 1, "vault_blobs": 1}
    assert saved["restored_files"] == ["users.json", "licenses.json", "vaults/abc.enc"]
    assert (restore_dir / "users.json").read_text(encoding="utf-8") == legacy.joinpath("users.json").read_text(encoding="utf-8")
    assert (restore_dir / "licenses.json").read_text(encoding="utf-8") == legacy.joinpath("licenses.json").read_text(encoding="utf-8")
    assert (restore_dir / "vaults" / "abc.enc").read_bytes() == b"encrypted-vault-blob"


def test_rollback_plan_and_smoke_report_record_local_boundary():
    plan = rollback_plan("local smoke")
    report = build_cloud_migration_smoke_report()

    assert plan[0] == "Rollback target: local smoke"
    assert any("freeze writes" in step.lower() for step in plan)
    assert report["boundary"] == "local-only"
    assert report["migrations"]["dry_run"]["dry_run"] is True
    assert report["migrations"]["applied"]["applied"] == [migration.name for migration in MIGRATIONS]
    assert report["migrations"]["status"]["current"] == MIGRATIONS[-1].name
    assert report["import"]["report_exists"] is True
    assert report["restore"]["report_exists"] is True
    assert report["restore"]["applied"]["counts"] == report["legacy_dataset"]["counts"]
    assert set(report["restore"]["applied"]["restored_files"]) == {
        "users.json",
        "licenses.json",
        "vaults/sample.enc",
    }


def test_cloud_storage_migration_smoke_script_writes_expected_report(tmp_path):
    output = tmp_path / "cloud-storage-migration-results.json"

    completed = subprocess.run(
        [sys.executable, "scripts/cloud_storage_migration_smoke.py", "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == ""
    assert completed.stderr == ""
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["boundary"] == "local-only"
    assert report["migrations"]["applied"]["applied"] == [
        migration.name for migration in MIGRATIONS
    ]
    assert report["import"]["report_exists"] is True
    assert report["restore"]["report_exists"] is True
    assert report["rollback_plan"][0] == "Rollback target: local smoke"

from pathlib import Path

from pushkey_migrations import (
    MIGRATIONS,
    import_legacy_dataset,
    migration_status,
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

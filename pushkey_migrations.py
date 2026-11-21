from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        "001_core_cloud_schema",
        """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    reset_token_hash TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    revoked_at TEXT,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    license_key_hash TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    reset_token_hash TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL,
    device_hash TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    contact_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,
    actor_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    request_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vault_revisions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    etag TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
""",
    ),
    Migration(
        "002_constraints_and_indexes",
        """
CREATE INDEX IF NOT EXISTS idx_sessions_subject ON sessions(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_devices_license ON devices(license_id);
CREATE INDEX IF NOT EXISTS idx_tickets_contact ON tickets(contact_id);
CREATE INDEX IF NOT EXISTS idx_audits_target ON audits(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_vault_revisions_user_created ON vault_revisions(user_id, created_at);
""",
    ),
    Migration(
        "003_transactional_revision_outbox",
        """
CREATE TABLE IF NOT EXISTS vault_revision_transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    object_key TEXT NOT NULL,
    etag TEXT NOT NULL,
    previous_etag TEXT,
    object_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    idempotency_key TEXT,
    request_id TEXT,
    audit_id TEXT,
    committed_at TEXT NOT NULL,
    UNIQUE(user_id, revision_number),
    UNIQUE(user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS outbox_events (
    id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    request_id TEXT,
    created_at TEXT NOT NULL,
    dispatched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_vault_revision_transactions_user_commit
    ON vault_revision_transactions(user_id, committed_at);
CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
    ON outbox_events(dispatched_at, created_at);
""",
    ),
)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def run_migrations(db_path: Path, *, dry_run: bool = False) -> dict:
    if dry_run:
        return {"applied": [migration.name for migration in MIGRATIONS], "dry_run": True}

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        _ensure_migrations_table(conn)
        applied = {
            row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
        }
        newly_applied = []
        for migration in MIGRATIONS:
            if migration.name in applied:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations(name) VALUES (?)",
                (migration.name,),
            )
            newly_applied.append(migration.name)
        conn.commit()
    finally:
        conn.close()
    return {"applied": newly_applied, "dry_run": False}


def migration_status(db_path: Path) -> dict:
    if not db_path.exists():
        return {"current": None, "applied": []}
    conn = sqlite3.connect(db_path)
    try:
        _ensure_migrations_table(conn)
        applied = [
            row[0]
            for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name").fetchall()
        ]
    finally:
        conn.close()
    return {"current": applied[-1] if applied else None, "applied": applied}


def _json_count(path: Path) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data) if isinstance(data, dict) else 0


def import_legacy_dataset(source_dir: Path, destination_dir: Path, *, dry_run: bool = False) -> dict:
    report = _dataset_report(source_dir, include_files=False, dry_run=dry_run)
    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)
        (destination_dir / "import-report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    return report


def _dataset_report(source_dir: Path, *, include_files: bool, dry_run: bool) -> dict:
    vault_hashes = []
    restored_files = []
    for name in ("users.json", "licenses.json"):
        if (source_dir / name).exists():
            restored_files.append(name)
    vault_dir = source_dir / "vaults"
    if vault_dir.exists():
        for item in sorted(vault_dir.glob("*.enc")):
            if item.is_file():
                vault_hashes.append(hashlib.sha256(item.read_bytes()).hexdigest())
                restored_files.append(f"vaults/{item.name}")

    report = {
        "dry_run": dry_run,
        "counts": {
            "users": _json_count(source_dir / "users.json"),
            "licenses": _json_count(source_dir / "licenses.json"),
            "vault_blobs": len(vault_hashes),
        },
        "hashes": {"vault_blobs": vault_hashes},
    }
    if include_files:
        report["restored_files"] = restored_files
    return report


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=dst.parent, prefix=f".{dst.name}.", suffix=".tmp") as handle:
        temp_path = Path(handle.name)
    try:
        shutil.copy2(src, temp_path)
        temp_path.replace(dst)
    finally:
        temp_path.unlink(missing_ok=True)


def restore_legacy_dataset(source_dir: Path, destination_dir: Path, *, dry_run: bool = False) -> dict:
    report = _dataset_report(source_dir, include_files=True, dry_run=dry_run)
    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)
        (destination_dir / "import-report.json").unlink(missing_ok=True)
        (destination_dir / "restore-report.json").unlink(missing_ok=True)
        (destination_dir / "users.json").unlink(missing_ok=True)
        (destination_dir / "licenses.json").unlink(missing_ok=True)
        shutil.rmtree(destination_dir / "vaults", ignore_errors=True)

        for name in ("users.json", "licenses.json"):
            src = source_dir / name
            if src.exists():
                _atomic_copy(src, destination_dir / name)

        vault_dir = source_dir / "vaults"
        if vault_dir.exists():
            for item in sorted(vault_dir.glob("*.enc")):
                if item.is_file():
                    _atomic_copy(item, destination_dir / "vaults" / item.name)

        (destination_dir / "restore-report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    return report


def rollback_plan(target: str | None = None) -> list[str]:
    plan = [
        "Freeze writes to the migrated storage path.",
        "Restore the last verified database snapshot and matching transactional metadata.",
        "Restore encrypted vault blobs from the latest versioned object-storage snapshot.",
        "Reconcile record counts, etags, and SHA-256 hashes against the smoke report.",
        "Re-enable reads and writes only after the restored state matches the report.",
    ]
    if target:
        plan.insert(0, f"Rollback target: {target}")
    return plan


def _write_sample_legacy_dataset(source_dir: Path) -> Path:
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "users.json").write_text(
        json.dumps({"u@example.com": {"hash": "h"}}, indent=2),
        encoding="utf-8",
    )
    (source_dir / "licenses.json").write_text(
        json.dumps({"PRO-1": {"tier": "pro"}}, indent=2),
        encoding="utf-8",
    )
    vault_dir = source_dir / "vaults"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "sample.enc").write_bytes(b"encrypted-vault-blob")
    return source_dir


def build_cloud_migration_smoke_report() -> dict:
    with tempfile.TemporaryDirectory(prefix="pushkey-cloud-migration-") as temp_root:
        root = Path(temp_root)
        legacy = _write_sample_legacy_dataset(root / "legacy")
        export_dir = root / "export"
        restore_dir = root / "restore"
        db_path = root / "cloud.sqlite"

        dry_run = run_migrations(db_path, dry_run=True)
        applied = run_migrations(db_path)
        status = migration_status(db_path)
        import_dry_run = import_legacy_dataset(legacy, export_dir, dry_run=True)
        import_live = import_legacy_dataset(legacy, export_dir, dry_run=False)
        restore_dry_run = restore_legacy_dataset(legacy, restore_dir, dry_run=True)
        restore_live = restore_legacy_dataset(legacy, restore_dir, dry_run=False)

        return {
            "boundary": "local-only",
            "legacy_dataset": {
                "counts": import_live["counts"],
                "hashes": import_live["hashes"],
            },
            "migrations": {
                "dry_run": dry_run,
                "applied": applied,
                "status": status,
            },
            "import": {
                "dry_run": import_dry_run,
                "applied": import_live,
                "report_exists": (export_dir / "import-report.json").exists(),
            },
            "restore": {
                "dry_run": restore_dry_run,
                "applied": restore_live,
                "report_exists": (restore_dir / "restore-report.json").exists(),
            },
            "rollback_plan": rollback_plan("local smoke"),
        }

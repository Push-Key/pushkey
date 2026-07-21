from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3


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
    with sqlite3.connect(db_path) as conn:
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
    return {"applied": newly_applied, "dry_run": False}


def migration_status(db_path: Path) -> dict:
    if not db_path.exists():
        return {"current": None, "applied": []}
    with sqlite3.connect(db_path) as conn:
        _ensure_migrations_table(conn)
        applied = [
            row[0]
            for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name").fetchall()
        ]
    return {"current": applied[-1] if applied else None, "applied": applied}


def _json_count(path: Path) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data) if isinstance(data, dict) else 0


def import_legacy_dataset(source_dir: Path, destination_dir: Path, *, dry_run: bool = False) -> dict:
    vault_hashes = []
    vault_dir = source_dir / "vaults"
    if vault_dir.exists():
        for item in sorted(vault_dir.glob("*.enc")):
            vault_hashes.append(hashlib.sha256(item.read_bytes()).hexdigest())

    report = {
        "dry_run": dry_run,
        "counts": {
            "users": _json_count(source_dir / "users.json"),
            "licenses": _json_count(source_dir / "licenses.json"),
            "vault_blobs": len(vault_hashes),
        },
        "hashes": {"vault_blobs": vault_hashes},
    }
    if not dry_run:
        destination_dir.mkdir(parents=True, exist_ok=True)
        (destination_dir / "import-report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    return report

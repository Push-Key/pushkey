#!/usr/bin/env python
"""Run a destructive restore drill against a configurable target.

This exercises the promoted production storage mode described in
docs/backup-restore-runbook.md (PostgreSQL vault metadata plus encrypted
object-storage blobs): it seeds vault/license/ticket data, deletes and
corrupts it to simulate a destructive incident, restores it from a captured
backup, and verifies the application still works end to end.

By default the drill runs against an isolated local/test fixture (an
ephemeral SQLite-backed vault store, matching the schema used against
PostgreSQL). Pass --target-db-url to point the vault metadata store at a real
staging/production PostgreSQL instance once hosted access exists; the
encrypted blob object store remains on the local application volume until
remote object-storage support lands in pushkey_cloud_api.py, so
--target-object-store-url is recorded as informational configuration only.

This script is execution-ready but has not been run against real hosted
production infrastructure. See docs/backup-restore-runbook.md and
docs/production-rollback-backup-infrastructure-checklist.md.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_app(data_dir: Path, *, target_db_url: str | None):
    os.environ.update(
        {
            "PUSHKEY_DATA_DIR": str(data_dir),
            "PUSHKEY_ADMIN_EMAIL": "admin@example.com",
            "PUSHKEY_ADMIN_PASSWORD": "admin-pass-123",
            "PUSHKEY_ADMIN_COOKIE_SECURE": "false",
            "PUSHKEY_JWT_SECRET": "production-restore-jwt-secret",
            "AUTH_RATE_MAX": "10000",
            "PORTAL_RATE_MAX": "10000",
            "HEARTBEAT_RATE_MAX": "10000",
            "SMTP_HOST": "",
            "SMTP_USER": "",
            "SMTP_PASS": "",
            "FROM_EMAIL": "",
        }
    )
    if target_db_url:
        os.environ["PUSHKEY_CLOUD_DATABASE_URL"] = target_db_url
    else:
        os.environ.pop("PUSHKEY_CLOUD_DATABASE_URL", None)
    sys.modules.pop("pushkey_cloud_api", None)
    return importlib.import_module("pushkey_cloud_api")


def _admin_login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    if response.status_code != 200:
        raise SystemExit(f"admin login failed: {response.status_code} {response.text}")
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _seed(data_dir: Path, target_db_url: str | None) -> dict:
    app_module = _fresh_app(data_dir, target_db_url=target_db_url)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)

        issued = client.post(
            "/api/admin/licenses/issue",
            headers=admin_headers,
            json={"tier": "starter", "email": "restore@example.com", "send_email": False},
        )
        if issued.status_code != 200:
            raise SystemExit(f"license issue failed: {issued.status_code} {issued.text}")
        license_key = issued.json()["key"]

        user_email = "restore-user@example.com"
        user_password = "correct horse battery staple"
        register = client.post("/api/v1/auth/register", json={"email": user_email, "password": user_password})
        if register.status_code != 200:
            raise SystemExit(f"user register failed: {register.status_code} {register.text}")
        token = register.json()["token"]
        vault_blob = b"encrypted-production-restore-blob"
        vault_put = client.put("/api/v1/vault", headers={"Authorization": f"Bearer {token}"}, content=vault_blob)
        if vault_put.status_code != 200:
            raise SystemExit(f"vault put failed: {vault_put.status_code} {vault_put.text}")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": license_key, "fingerprint": "restore-device", "platform": "drill", "version": "production"},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed: {activation.status_code} {activation.text}")

        ticket = client.post(
            "/api/v1/portal/request-renewal",
            json={"license_key": license_key, "message": "production restore drill renewal ticket"},
        )
        if ticket.status_code != 200:
            raise SystemExit(f"ticket seed failed: {ticket.status_code} {ticket.text}")

        return {
            "license_key": license_key,
            "user_email": user_email,
            "user_password": user_password,
            "vault_blob": vault_blob.decode("ascii"),
            "device_token": activation.json()["token"],
            "ticket_id": ticket.json()["ticket_id"],
        }


def _capture_vault_state(app_module, user_key: str) -> dict:
    engine = app_module._vault_store._engine
    with engine.connect() as conn:
        current_row = conn.execute(
            app_module.select(app_module._VAULT_CURRENT).where(app_module._VAULT_CURRENT.c.user_key == user_key)
        ).mappings().first()
        if current_row is None:
            raise SystemExit("no vault metadata found to back up before corruption")
        history_rows = conn.execute(
            app_module.select(app_module._VAULT_HISTORY).where(app_module._VAULT_HISTORY.c.user_key == user_key)
        ).mappings().all()
        transaction_rows = conn.execute(
            app_module.select(app_module._VAULT_REVISION_TRANSACTIONS).where(
                app_module._VAULT_REVISION_TRANSACTIONS.c.user_id == user_key
            )
        ).mappings().all()

    object_key = current_row["object_key"]
    blob_path = app_module.VAULT_OBJECTS_DIR / f"{object_key}.blob"
    return {
        "current": dict(current_row),
        "history": [dict(row) for row in history_rows],
        "transactions": [dict(row) for row in transaction_rows],
        "blob_path": blob_path,
        "blob_bytes": blob_path.read_bytes(),
    }


def _corrupt_vault_state(app_module, user_key: str, blob_path: Path) -> None:
    engine = app_module._vault_store._engine
    with engine.begin() as conn:
        conn.execute(app_module.delete(app_module._VAULT_CURRENT).where(app_module._VAULT_CURRENT.c.user_key == user_key))
        conn.execute(app_module.delete(app_module._VAULT_HISTORY).where(app_module._VAULT_HISTORY.c.user_key == user_key))
        conn.execute(
            app_module.delete(app_module._VAULT_REVISION_TRANSACTIONS).where(
                app_module._VAULT_REVISION_TRANSACTIONS.c.user_id == user_key
            )
        )
    blob_path.unlink(missing_ok=True)


def _restore_vault_state(app_module, backup: dict) -> None:
    engine = app_module._vault_store._engine
    with engine.begin() as conn:
        conn.execute(app_module._VAULT_CURRENT.insert().values(**backup["current"]))
        if backup["history"]:
            conn.execute(app_module._VAULT_HISTORY.insert(), backup["history"])
        if backup["transactions"]:
            conn.execute(app_module._VAULT_REVISION_TRANSACTIONS.insert(), backup["transactions"])
    backup["blob_path"].parent.mkdir(parents=True, exist_ok=True)
    backup["blob_path"].write_bytes(backup["blob_bytes"])


def _verify(data_dir: Path, seed: dict, target_db_url: str | None) -> list[str]:
    app_module = _fresh_app(data_dir, target_db_url=target_db_url)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)
        checks: list[str] = []

        health = client.get("/api/v1/health")
        if health.status_code != 200:
            raise SystemExit(f"health failed after restore: {health.status_code}")
        checks.append("health")

        login = client.post(
            "/api/v1/auth/login",
            json={"email": seed["user_email"], "password": seed["user_password"]},
        )
        if login.status_code != 200:
            raise SystemExit(f"user login failed after restore: {login.status_code} {login.text}")
        auth = {"Authorization": f"Bearer {login.json()['token']}"}
        vault = client.get("/api/v1/vault", headers=auth)
        if vault.status_code != 200 or vault.content.decode("ascii") != seed["vault_blob"]:
            raise SystemExit("vault blob mismatch after restore")
        checks.append("vault_blob_access")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": seed["license_key"], "fingerprint": "restore-device", "platform": "drill", "version": "production"},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed after restore: {activation.status_code} {activation.text}")
        checks.append("activation")

        tickets = client.get("/api/admin/tickets", headers=admin_headers)
        if tickets.status_code != 200 or seed["ticket_id"] not in {ticket["id"] for ticket in tickets.json()}:
            raise SystemExit("support ticket missing after restore")
        checks.append("support_ticket")

        stats = client.get("/api/admin/stats", headers=admin_headers)
        if stats.status_code != 200:
            raise SystemExit(f"admin stats failed after restore: {stats.status_code}")
        checks.append("admin_login")
        return checks


def run_drill(*, target_db_url: str | None = None, target_object_store_url: str | None = None) -> dict:
    import hashlib

    with tempfile.TemporaryDirectory(
        prefix="pushkey-production-restore-", ignore_cleanup_errors=True
    ) as tmp:
        data_dir = Path(tmp) / "data"
        seed = _seed(data_dir, target_db_url)

        app_module = _fresh_app(data_dir, target_db_url=target_db_url)
        user_key = hashlib.sha256(seed["user_email"].encode()).hexdigest()

        start = time.perf_counter()
        backup = _capture_vault_state(app_module, user_key)
        _corrupt_vault_state(app_module, user_key, backup["blob_path"])
        _restore_vault_state(app_module, backup)
        checks = _verify(data_dir, seed, target_db_url)
        duration = time.perf_counter() - start

        using_local_fixture = target_db_url is None

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verification_scope": "local isolated fixture" if using_local_fixture else "configured target-db-url",
            "storage_mode": "production-postgresql-object-storage",
            "restore_type": "destructive restore of vault metadata rows and encrypted blob from captured backup",
            "scenario": "delete vault metadata and encrypted blob for a seeded account, then restore from backup",
            "target_db_url_configured": bool(target_db_url),
            "target_object_store_url_configured": bool(target_object_store_url),
            "object_storage_integration_note": (
                "Encrypted vault blobs are still written to the local application "
                "volume (pushkey_cloud_api.VAULT_OBJECTS_DIR); pushkey_cloud_api.py "
                "does not yet support a remote/versioned object-storage backend, so "
                "--target-object-store-url is recorded for forward compatibility but "
                "is not wired into blob I/O yet."
            ),
            "duration_seconds": round(duration, 3),
            "restored": True,
            "checks": checks,
            "rpo_seconds": 0,
            "rto_seconds": round(duration, 3),
            "residual_risk": (
                "This drill has not been run against real hosted PostgreSQL or "
                "versioned object storage. It proves the restore code path and "
                "verification checks against an isolated fixture (or, if "
                "--target-db-url was supplied, against that database), not a real "
                "provider snapshot/PITR restore. See "
                "docs/production-rollback-backup-infrastructure-checklist.md for "
                "the outstanding hosted-access gate."
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-db-url",
        default=os.environ.get("PUSHKEY_PRODUCTION_TARGET_DB_URL") or None,
        help="PostgreSQL URL for the vault metadata store. Defaults to an isolated local SQLite fixture.",
    )
    parser.add_argument(
        "--target-object-store-url",
        default=os.environ.get("PUSHKEY_PRODUCTION_TARGET_OBJECT_STORE_URL") or None,
        help="Versioned object-storage URL for encrypted vault blobs. Recorded for forward compatibility only.",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "production-restore-drill-results.json")
    args = parser.parse_args()

    result = run_drill(
        target_db_url=args.target_db_url,
        target_object_store_url=args.target_object_store_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["restored"]:
        raise SystemExit("restore drill did not restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

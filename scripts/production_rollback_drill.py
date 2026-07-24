#!/usr/bin/env python
"""Run a deployment rollback drill against a configurable target.

This exercises the promoted production storage mode described in
docs/backup-restore-runbook.md: it seeds vault/license/ticket data under a
"good" release configuration, simulates a bad deploy that breaks active
sessions (a signing-key misconfiguration that a faulty release could ship
without a rotation grace period), rolls the application configuration back to
the last known good release, and verifies that no data was lost and that the
previously broken session works again.

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

GOOD_RELEASE = "good-release-v1.0.0"
BAD_RELEASE = "bad-release-v1.1.0"
GOOD_JWT_SECRET = "production-rollback-good-jwt-secret"
BAD_JWT_SECRET = "production-rollback-bad-jwt-secret-no-grace-period"


def _fresh_app(data_dir: Path, *, target_db_url: str | None, jwt_secret: str, jwt_previous_secrets: str = ""):
    os.environ.update(
        {
            "PUSHKEY_DATA_DIR": str(data_dir),
            "PUSHKEY_ADMIN_EMAIL": "admin@example.com",
            "PUSHKEY_ADMIN_PASSWORD": "admin-pass-123",
            "PUSHKEY_ADMIN_COOKIE_SECURE": "false",
            "PUSHKEY_JWT_SECRET": jwt_secret,
            "PUSHKEY_JWT_PREVIOUS_SECRETS": jwt_previous_secrets,
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
    app_module = _fresh_app(data_dir, target_db_url=target_db_url, jwt_secret=GOOD_JWT_SECRET)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)

        issued = client.post(
            "/api/admin/licenses/issue",
            headers=admin_headers,
            json={"tier": "starter", "email": "rollback-drill@example.com", "send_email": False},
        )
        if issued.status_code != 200:
            raise SystemExit(f"license issue failed: {issued.status_code} {issued.text}")
        license_key = issued.json()["key"]

        user_email = "production-rollback-user@example.com"
        user_password = "correct horse battery staple"
        register = client.post("/api/v1/auth/register", json={"email": user_email, "password": user_password})
        if register.status_code != 200:
            raise SystemExit(f"user register failed: {register.status_code} {register.text}")

        login = client.post("/api/v1/auth/login", json={"email": user_email, "password": user_password})
        if login.status_code != 200:
            raise SystemExit(f"user login failed: {login.status_code} {login.text}")
        session_token = login.json()["token"]

        vault_blob = b"encrypted-production-rollback-blob"
        vault_put = client.put(
            "/api/v1/vault", headers={"Authorization": f"Bearer {session_token}"}, content=vault_blob
        )
        if vault_put.status_code != 200:
            raise SystemExit(f"vault put failed: {vault_put.status_code} {vault_put.text}")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": license_key, "fingerprint": "rollback-drill-device", "platform": "drill", "version": GOOD_RELEASE},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed: {activation.status_code} {activation.text}")

        ticket = client.post(
            "/api/v1/portal/request-renewal",
            json={"license_key": license_key, "message": "production rollback drill renewal ticket"},
        )
        if ticket.status_code != 200:
            raise SystemExit(f"ticket seed failed: {ticket.status_code} {ticket.text}")

        return {
            "license_key": license_key,
            "user_email": user_email,
            "user_password": user_password,
            "vault_blob": vault_blob.decode("ascii"),
            "session_token": session_token,
            "device_token": activation.json()["token"],
            "ticket_id": ticket.json()["ticket_id"],
        }


def _confirm_bad_deploy_breaks_session(data_dir: Path, seed: dict, target_db_url: str | None) -> None:
    app_module = _fresh_app(data_dir, target_db_url=target_db_url, jwt_secret=BAD_JWT_SECRET)
    with TestClient(app_module.app) as client:
        broken = client.get(
            "/api/v1/vault", headers={"Authorization": f"Bearer {seed['session_token']}"}
        )
        if broken.status_code != 401:
            raise SystemExit(
                f"bad deploy did not break the pre-existing session as expected: {broken.status_code}"
            )


def _verify_after_rollback(data_dir: Path, seed: dict, target_db_url: str | None) -> list[str]:
    app_module = _fresh_app(data_dir, target_db_url=target_db_url, jwt_secret=GOOD_JWT_SECRET)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)
        checks: list[str] = []

        health = client.get("/api/v1/health")
        if health.status_code != 200:
            raise SystemExit(f"health failed after rollback: {health.status_code}")
        checks.append("health")

        restored_session = client.get(
            "/api/v1/vault", headers={"Authorization": f"Bearer {seed['session_token']}"}
        )
        if restored_session.status_code != 200 or restored_session.content.decode("ascii") != seed["vault_blob"]:
            raise SystemExit("pre-existing session/vault data did not survive rollback")
        checks.append("pre_existing_session_restored")

        login = client.post(
            "/api/v1/auth/login",
            json={"email": seed["user_email"], "password": seed["user_password"]},
        )
        if login.status_code != 200:
            raise SystemExit(f"user login failed after rollback: {login.status_code} {login.text}")
        checks.append("login")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": seed["license_key"], "fingerprint": "rollback-drill-device", "platform": "drill", "version": GOOD_RELEASE},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed after rollback: {activation.status_code} {activation.text}")
        heartbeat = client.post(
            "/api/v1/heartbeat",
            json={
                "license_key": seed["license_key"],
                "fingerprint": "rollback-drill-device",
                "token": activation.json()["token"],
                "platform": "drill",
                "version": GOOD_RELEASE,
            },
        )
        if heartbeat.status_code != 200:
            raise SystemExit(f"heartbeat failed after rollback: {heartbeat.status_code} {heartbeat.text}")
        checks.append("activation_heartbeat")

        tickets = client.get("/api/admin/tickets", headers=admin_headers)
        if tickets.status_code != 200 or seed["ticket_id"] not in {ticket["id"] for ticket in tickets.json()}:
            raise SystemExit("support ticket missing after rollback")
        checks.append("support_ticket")

        stats = client.get("/api/admin/stats", headers=admin_headers)
        if stats.status_code != 200:
            raise SystemExit(f"admin stats failed after rollback: {stats.status_code}")
        checks.append("admin_login")
        return checks


def run_drill(*, target_db_url: str | None = None, target_object_store_url: str | None = None) -> dict:
    with tempfile.TemporaryDirectory(
        prefix="pushkey-production-rollback-", ignore_cleanup_errors=True
    ) as tmp:
        data_dir = Path(tmp) / "data"
        seed = _seed(data_dir, target_db_url)

        start = time.perf_counter()
        _confirm_bad_deploy_breaks_session(data_dir, seed, target_db_url)
        checks = _verify_after_rollback(data_dir, seed, target_db_url)
        duration = time.perf_counter() - start

        using_local_fixture = target_db_url is None

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verification_scope": "local isolated fixture" if using_local_fixture else "configured target-db-url",
            "storage_mode": "production-postgresql-object-storage",
            "rollback_type": "application/config rollback from a bad release to the last known good release",
            "scenario": "bad deploy breaks active sessions via a signing-key misconfiguration; roll back "
            "to the last known good release configuration without losing account, license, vault, or ticket data",
            "bad_deploy_release": BAD_RELEASE,
            "rolled_back_to_release": GOOD_RELEASE,
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
            "rolled_back": True,
            "data_loss": False,
            "checks": checks,
            "rpo_seconds": 0,
            "rto_seconds": round(duration, 3),
            "residual_risk": (
                "This drill has not been run against a real hosted deployment "
                "pipeline, PostgreSQL instance, or versioned object storage. It "
                "proves the application-level rollback and no-data-loss "
                "verification checks against an isolated fixture (or, if "
                "--target-db-url was supplied, against that database), not a real "
                "provider deploy/rollback. See "
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
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "production-rollback-drill-results.json")
    args = parser.parse_args()

    result = run_drill(
        target_db_url=args.target_db_url,
        target_object_store_url=args.target_object_store_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["rolled_back"]:
        raise SystemExit("rollback drill did not roll back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

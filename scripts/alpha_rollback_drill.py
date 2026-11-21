#!/usr/bin/env python
"""Run an isolated alpha rollback drill for the encrypted-blob cloud mode."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_app(data_dir: Path):
    os.environ.update(
        {
            "PUSHKEY_DATA_DIR": str(data_dir),
            "PUSHKEY_ADMIN_EMAIL": "admin@example.com",
            "PUSHKEY_ADMIN_PASSWORD": "admin-pass-123",
            "PUSHKEY_ADMIN_COOKIE_SECURE": "false",
            "PUSHKEY_JWT_SECRET": "alpha-rollback-jwt-secret",
            "AUTH_RATE_MAX": "10000",
            "PORTAL_RATE_MAX": "10000",
            "HEARTBEAT_RATE_MAX": "10000",
            "SMTP_HOST": "",
            "SMTP_USER": "",
            "SMTP_PASS": "",
            "FROM_EMAIL": "",
        }
    )
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


def _remove_tree(path: Path) -> None:
    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2 * (attempt + 1))


def _restore_snapshot(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if item.name.endswith(("-wal", "-shm", "-journal")):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _seed(data_dir: Path) -> dict:
    app_module = _fresh_app(data_dir)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)

        issued = client.post(
            "/api/admin/licenses/issue",
            headers=admin_headers,
            json={"tier": "starter", "email": "rollback@example.com", "send_email": False},
        )
        if issued.status_code != 200:
            raise SystemExit(f"license issue failed: {issued.status_code} {issued.text}")
        license_key = issued.json()["key"]

        user_email = "rollback-user@example.com"
        user_password = "correct horse battery staple"
        register = client.post("/api/v1/auth/register", json={"email": user_email, "password": user_password})
        if register.status_code != 200:
            raise SystemExit(f"user register failed: {register.status_code} {register.text}")
        token = register.json()["token"]
        vault_blob = b"encrypted-rollback-blob"
        vault_put = client.put("/api/v1/vault", headers={"Authorization": f"Bearer {token}"}, content=vault_blob)
        if vault_put.status_code != 200:
            raise SystemExit(f"vault put failed: {vault_put.status_code} {vault_put.text}")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": license_key, "fingerprint": "rollback-device", "platform": "drill", "version": "alpha"},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed: {activation.status_code} {activation.text}")

        ticket = client.post(
            "/api/v1/portal/request-renewal",
            json={"license_key": license_key, "message": "rollback drill renewal ticket"},
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


def _verify(data_dir: Path, seed: dict) -> list[str]:
    app_module = _fresh_app(data_dir)
    with TestClient(app_module.app) as client:
        admin_headers = _admin_login(client)
        checks: list[str] = []

        health = client.get("/api/v1/health")
        if health.status_code != 200:
            raise SystemExit(f"health failed after rollback: {health.status_code}")
        checks.append("health")

        login = client.post(
            "/api/v1/auth/login",
            json={"email": seed["user_email"], "password": seed["user_password"]},
        )
        if login.status_code != 200:
            raise SystemExit(f"user login failed after rollback: {login.status_code} {login.text}")
        auth = {"Authorization": f"Bearer {login.json()['token']}"}
        vault = client.get("/api/v1/vault", headers=auth)
        if vault.status_code != 200 or vault.content.decode("ascii") != seed["vault_blob"]:
            raise SystemExit("vault blob mismatch after rollback")
        checks.append("vault")

        activation = client.post(
            "/api/v1/activate",
            json={"license_key": seed["license_key"], "fingerprint": "rollback-device", "platform": "drill", "version": "alpha"},
        )
        if activation.status_code != 200:
            raise SystemExit(f"activation failed after rollback: {activation.status_code} {activation.text}")
        heartbeat = client.post(
            "/api/v1/heartbeat",
            json={
                "license_key": seed["license_key"],
                "fingerprint": "rollback-device",
                "token": activation.json()["token"],
                "platform": "drill",
                "version": "alpha",
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
        checks.append("admin")
        return checks


def run_drill() -> dict:
    with tempfile.TemporaryDirectory(
        prefix="pushkey-alpha-rollback-", ignore_cleanup_errors=True
    ) as tmp:
        base = Path(tmp)
        data_dir = base / "data"
        snapshot_dir = base / "snapshot"
        seed = _seed(data_dir)
        shutil.copytree(data_dir, snapshot_dir)

        start = time.perf_counter()
        (data_dir / "licenses.json").write_text('{"bad-deploy": true}', encoding="utf-8")
        vault_dir = data_dir / "vaults"
        if vault_dir.exists():
            _remove_tree(vault_dir)

        _restore_snapshot(snapshot_dir, data_dir)
        checks = _verify(data_dir, seed)
        duration = time.perf_counter() - start

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verification_scope": "local alpha-only",
            "storage_mode": "alpha-encrypted-blob",
            "restore_type": "destructive restore from local snapshot",
            "scenario": "destructive restore from volume snapshot after bad deploy mutation",
            "duration_seconds": round(duration, 3),
            "restored": True,
            "checks": checks,
            "rpo_seconds": 0,
            "rto_seconds": round(duration, 3),
            "residual_risk": (
                "Local alpha-only drill; production backup/PITR, versioned object storage, "
                "and live alert delivery still require hosted environment evidence."
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "alpha-rollback-drill-results.json")
    args = parser.parse_args()

    result = run_drill()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["restored"]:
        raise SystemExit("rollback drill did not restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

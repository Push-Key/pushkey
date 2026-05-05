"""
Tests for the local-only Pushkey API consumed by the bundled web UI.
Phase 1: status, unlock, lock, keys read-only, token auth, autolock.
"""
import importlib
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from pushkey_crypto import encrypt_data_v3
import pushkey_shared as _s


@pytest.fixture
def fresh_app(monkeypatch):
    monkeypatch.setenv("PUSHKEY_LAUNCH_TOKEN", "test-launch-token")
    monkeypatch.setenv("PUSHKEY_LOCAL_PORT", "0")
    if "pushkey_local_api" in sys.modules:
        del sys.modules["pushkey_local_api"]
    mod = importlib.import_module("pushkey_local_api")
    return mod


@pytest.fixture
def client(fresh_app):
    return TestClient(fresh_app.app)


@pytest.fixture
def auth():
    return {"Authorization": "Bearer test-launch-token"}


def _seed_vault(password: str, recovery: str, keys: dict) -> None:
    _s.ensure_vault_dir()
    payload = {"_schema": _s.VAULT_SCHEMA_VERSION, "keys": keys}
    blob = encrypt_data_v3(json.dumps(payload), password, recovery)
    _s.VAULT_FILE.write_bytes(blob)


# ── auth gate ──────────────────────────────────────────────────────
def test_status_requires_bearer_token(client):
    r = client.get("/api/status")
    assert r.status_code == 401


def test_invalid_bearer_rejected(client):
    r = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_valid_bearer_accepted(client, auth):
    r = client.get("/api/status", headers=auth)
    assert r.status_code == 200


# ── status ─────────────────────────────────────────────────────────
def test_status_locked_when_no_vault(client, auth):
    r = client.get("/api/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["locked"] is True
    assert body["has_vault"] is False
    assert body["key_count"] == 0


def test_status_locked_when_vault_present_but_not_unlocked(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"OPENAI": {"value": "sk-x"}})
    r = client.get("/api/status", headers=auth)
    body = r.json()
    assert body["locked"] is True
    assert body["has_vault"] is True


# ── unlock / lock ─────────────────────────────────────────────────
def test_unlock_requires_credential(client, auth):
    r = client.post("/api/unlock", headers=auth, json={})
    assert r.status_code == 400


def test_unlock_wrong_password(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    r = client.post("/api/unlock", headers=auth, json={"password": "nope"})
    assert r.status_code == 401


def test_unlock_correct_password(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K1": {"value": "v1"}, "K2": {"value": "v2"}})
    r = client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    assert r.status_code == 200
    assert r.json() == {"locked": False, "key_count": 2}
    s = client.get("/api/status", headers=auth).json()
    assert s["locked"] is False
    assert s["key_count"] == 2


def test_unlock_via_recovery_code(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    r = client.post("/api/unlock", headers=auth, json={"recovery_code": "PUSH-AAAA-BBBB-CCCC-DDDD"})
    assert r.status_code == 200


def test_lock_clears_session(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    r = client.post("/api/lock", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"locked": True}
    assert client.get("/api/status", headers=auth).json()["locked"] is True


# ── keys read-only ────────────────────────────────────────────────
def test_keys_blocked_when_locked(client, auth):
    r = client.get("/api/keys", headers=auth)
    assert r.status_code == 423


def test_keys_list_masks_values(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {
        "OPENAI_API_KEY": {"value": "sk-1234567890abcdef", "env": "prod", "rotated": "2026-01-01"},
        "STRIPE_KEY": {"value": "pk_short", "env": "dev"},
    })
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    body = client.get("/api/keys", headers=auth).json()
    assert body["count"] == 2
    by = {k["name"]: k for k in body["keys"]}
    assert "OPENAI_API_KEY" in by
    assert by["OPENAI_API_KEY"]["env"] == "prod"
    assert by["OPENAI_API_KEY"]["masked"].startswith("sk-1")
    assert "•" in by["OPENAI_API_KEY"]["masked"]
    assert "sk-1234567890abcdef" not in body["keys"].__repr__()


def test_keys_list_skips_meta_underscore_keys(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {
        "REAL": {"value": "v"},
        "_policies": {"foo": "bar"},
    })
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    body = client.get("/api/keys", headers=auth).json()
    names = [k["name"] for k in body["keys"]]
    assert "REAL" in names
    assert "_policies" not in names


def test_reveal_returns_plaintext(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "the-real-secret", "env": "prod"}})
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    r = client.get("/api/keys/K", headers=auth)
    assert r.status_code == 200
    assert r.json()["value"] == "the-real-secret"


def test_reveal_unknown_key(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    r = client.get("/api/keys/NOPE", headers=auth)
    assert r.status_code == 404


def test_reveal_blocked_when_locked(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    r = client.get("/api/keys/K", headers=auth)
    assert r.status_code == 423


# ── autolock ──────────────────────────────────────────────────────
def test_autolock_relocks_after_idle(client, auth, fresh_app):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {"K": {"value": "v"}})
    client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    fresh_app.app.state.session.autolock_seconds = 1
    fresh_app.app.state.session.last_activity = time.time() - 5
    r = client.get("/api/keys", headers=auth)
    assert r.status_code == 423


# ── origin pin ────────────────────────────────────────────────────
def test_foreign_origin_rejected(client, auth):
    r = client.get("/api/status", headers={**auth, "Origin": "http://evil.example.com"})
    assert r.status_code == 403


def test_localhost_origin_allowed(client, auth):
    r = client.get("/api/status", headers={**auth, "Origin": "http://127.0.0.1:5173"})
    assert r.status_code == 200

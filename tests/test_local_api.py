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
    body = r.json()
    assert body["locked"] is False
    assert body["key_count"] == 2
    assert body["can_write"] is True
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


# ════════════════════════════════════════════════════════════════════════
# Phase 2 — write ops
# ════════════════════════════════════════════════════════════════════════

@pytest.fixture
def unlocked(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {
        "OPENAI_API_KEY": {"value": "sk-original", "env": "prod", "provider": "OpenAI",
                           "rotated": "2026-01-01", "created": "2026-01-01", "projects": []},
    })
    r = client.post("/api/unlock", headers=auth, json={"password": "master-pw"})
    assert r.status_code == 200
    return client


@pytest.fixture
def unlocked_recovery(client, auth):
    _seed_vault("master-pw", "PUSH-AAAA-BBBB-CCCC-DDDD", {
        "K": {"value": "v", "env": "dev", "provider": "Unknown",
              "rotated": "2026-01-01", "created": "2026-01-01", "projects": []},
    })
    r = client.post("/api/unlock", headers=auth, json={"recovery_code": "PUSH-AAAA-BBBB-CCCC-DDDD"})
    assert r.status_code == 200
    return client


# ── auth gate for writes ──────────────────────────────────────────
def test_recovery_unlock_blocks_writes(unlocked_recovery, auth):
    r = unlocked_recovery.post("/api/keys", headers=auth,
                               json={"name": "NEW", "value": "v"})
    assert r.status_code == 403
    assert "master-password" in r.json()["detail"]


def test_status_reports_can_write_false_on_recovery(unlocked_recovery, auth):
    body = unlocked_recovery.get("/api/status", headers=auth).json()
    assert body["can_write"] is False
    assert body["auth_method"] == "recovery"


def test_status_reports_can_write_true_on_password(unlocked, auth):
    body = unlocked.get("/api/status", headers=auth).json()
    assert body["can_write"] is True
    assert body["auth_method"] == "password"


# ── keys CRUD ─────────────────────────────────────────────────────
def test_create_key(unlocked, auth):
    r = unlocked.post("/api/keys", headers=auth,
                      json={"name": "STRIPE_KEY", "value": "sk_live_x", "env": "prod"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "STRIPE_KEY"
    assert body["env"] == "prod"
    keys = unlocked.get("/api/keys", headers=auth).json()
    names = [k["name"] for k in keys["keys"]]
    assert "STRIPE_KEY" in names


def test_create_key_auto_detects_provider(unlocked, auth):
    r = unlocked.post("/api/keys", headers=auth,
                      json={"name": "ANTHROPIC_API_KEY", "value": "sk-ant-x"})
    assert r.json()["provider"] == "Anthropic"


def test_create_duplicate_key_rejected(unlocked, auth):
    r = unlocked.post("/api/keys", headers=auth,
                      json={"name": "OPENAI_API_KEY", "value": "sk-x"})
    assert r.status_code == 409


def test_create_duplicate_key_with_overwrite(unlocked, auth):
    r = unlocked.post("/api/keys", headers=auth,
                      json={"name": "OPENAI_API_KEY", "value": "sk-replaced", "overwrite": True})
    assert r.status_code == 201
    rev = unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).json()
    assert rev["value"] == "sk-replaced"


def test_create_underscore_name_rejected(unlocked, auth):
    r = unlocked.post("/api/keys", headers=auth, json={"name": "_meta", "value": "v"})
    assert r.status_code == 400


def test_update_key_metadata(unlocked, auth):
    r = unlocked.patch("/api/keys/OPENAI_API_KEY", headers=auth,
                       json={"env": "dev", "notes": "rotated by dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["env"] == "dev"
    assert body["notes"] == "rotated by dev"


def test_update_unknown_key_404(unlocked, auth):
    r = unlocked.patch("/api/keys/NOPE", headers=auth, json={"env": "dev"})
    assert r.status_code == 404


def test_delete_key(unlocked, auth):
    r = unlocked.delete("/api/keys/OPENAI_API_KEY", headers=auth)
    assert r.status_code == 204
    assert unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).status_code == 404


def test_delete_unknown_404(unlocked, auth):
    r = unlocked.delete("/api/keys/NOPE", headers=auth)
    assert r.status_code == 404


# ── rotate / dual-rotation ────────────────────────────────────────
def test_rotate_key(unlocked, auth):
    r = unlocked.post("/api/keys/OPENAI_API_KEY/rotate", headers=auth,
                      json={"new_value": "sk-new"})
    assert r.status_code == 200
    rev = unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).json()
    assert rev["value"] == "sk-new"
    assert len(rev["history"]) == 1
    assert rev["history"][0]["value"] == "sk-original"


def test_rotate_unknown_key_404(unlocked, auth):
    r = unlocked.post("/api/keys/NOPE/rotate", headers=auth, json={"new_value": "x"})
    assert r.status_code == 404


def test_set_backup_key(unlocked, auth):
    r = unlocked.post("/api/keys/OPENAI_API_KEY/backup", headers=auth,
                      json={"backup_value": "sk-backup"})
    assert r.status_code == 200
    body = r.json()
    assert body["dual_rotation"] is True
    assert body["provider_supports_multi_key"] in (True, False)
    rev = unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).json()
    assert rev["next_value"] == "sk-backup"
    assert rev["dual_rotation"] is True


def test_promote_backup(unlocked, auth):
    unlocked.post("/api/keys/OPENAI_API_KEY/backup", headers=auth,
                  json={"backup_value": "sk-backup"})
    r = unlocked.post("/api/keys/OPENAI_API_KEY/promote", headers=auth)
    assert r.status_code == 200
    rev = unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).json()
    assert rev["value"] == "sk-backup"
    assert rev["next_value"] is None
    assert any(h["value"] == "sk-original" for h in rev["history"])


def test_promote_without_backup_400(unlocked, auth):
    r = unlocked.post("/api/keys/OPENAI_API_KEY/promote", headers=auth)
    assert r.status_code == 400


# ── projects ──────────────────────────────────────────────────────
def test_create_and_list_project(unlocked, auth, tmp_path):
    p = str(tmp_path / "myproj")
    (tmp_path / "myproj").mkdir()
    r = unlocked.post("/api/projects", headers=auth, json={"path": p, "name": "Demo"})
    assert r.status_code == 201
    body = unlocked.get("/api/projects", headers=auth).json()
    assert body["count"] == 1
    assert body["projects"][0]["name"] == "Demo"


def test_create_project_duplicate(unlocked, auth, tmp_path):
    p = str(tmp_path / "p")
    (tmp_path / "p").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    r = unlocked.post("/api/projects", headers=auth, json={"path": p})
    assert r.status_code == 409


def test_assign_keys_to_project(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    r = unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                      json={"keys": ["OPENAI_API_KEY"]})
    assert r.status_code == 200
    listing = unlocked.get("/api/projects", headers=auth).json()
    assert listing["projects"][0]["keys"] == ["OPENAI_API_KEY"]


def test_assign_unknown_key_400(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    r = unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                      json={"keys": ["GHOST"]})
    assert r.status_code == 400


def test_unassign_keys(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                  json={"keys": ["OPENAI_API_KEY"]})
    r = unlocked.post("/api/projects/unassign", headers=auth, params={"path": p},
                     json={"keys": ["OPENAI_API_KEY"]})
    assert r.status_code == 200
    listing = unlocked.get("/api/projects", headers=auth).json()
    assert listing["projects"][0]["keys"] == []


def test_delete_project_clears_assignments(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                  json={"keys": ["OPENAI_API_KEY"]})
    r = unlocked.delete("/api/projects", headers=auth, params={"path": p})
    assert r.status_code == 204
    rev = unlocked.get("/api/keys/OPENAI_API_KEY", headers=auth).json()
    assert p not in rev["projects"]


def test_inject_preview_does_not_write(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                  json={"keys": ["OPENAI_API_KEY"]})
    r = unlocked.post("/api/projects/inject", headers=auth,
                      params={"path": p, "write": False}, json={})
    body = r.json()
    assert "OPENAI_API_KEY=sk-original" in body["injected"]
    assert body["wrote"] is False
    assert not (tmp_path / "proj" / ".env").exists()


def test_inject_writes_env_and_gitignore(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                  json={"keys": ["OPENAI_API_KEY"]})
    r = unlocked.post("/api/projects/inject", headers=auth, params={"path": p}, json={})
    assert r.status_code == 200
    env_text = (tmp_path / "proj" / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-original" in env_text
    gi = (tmp_path / "proj" / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi


def test_inject_skips_existing_env_keys(unlocked, auth, tmp_path):
    p = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / ".env").write_text("OPENAI_API_KEY=preexisting\n", encoding="utf-8")
    unlocked.post("/api/projects", headers=auth, json={"path": p})
    unlocked.post("/api/projects/assign", headers=auth, params={"path": p},
                  json={"keys": ["OPENAI_API_KEY"]})
    r = unlocked.post("/api/projects/inject", headers=auth, params={"path": p}, json={})
    body = r.json()
    assert body["injected"] == []
    assert "OPENAI_API_KEY" in body["skipped_existing"]


# ── providers ─────────────────────────────────────────────────────
def test_list_providers(client, auth):
    r = client.get("/api/providers", headers=auth)
    assert r.status_code == 200
    assert "OpenAI" in r.json()["providers"]


def test_detect_provider_by_name(client, auth):
    r = client.post("/api/providers/detect", headers=auth,
                    json={"name": "OPENAI_API_KEY", "value": "sk-x"})
    body = r.json()
    assert body["provider"] == "OpenAI"


def test_detect_provider_unknown(client, auth):
    r = client.post("/api/providers/detect", headers=auth,
                    json={"name": "MY_RANDOM_THING", "value": "x"})
    assert r.json()["provider"] is None


# ── agent tokens ──────────────────────────────────────────────────
def test_list_agents_empty(unlocked, auth):
    r = unlocked.get("/api/agents", headers=auth)
    assert r.status_code == 200
    assert r.json()["tokens"] == []


def test_create_agent_token_requires_pro(unlocked, auth):
    # Free tier (default) → 403
    r = unlocked.post("/api/agents", headers=auth,
                      json={"name": "ci", "scopes": ["read"]})
    assert r.status_code == 403

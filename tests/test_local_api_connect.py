"""Local web API routes for add-and-connect: connections, one-call add, sync after a
key changes, the shared project registry and the one-time migration at unlock.

The vault is a V3 vault seeded with dummy keys (no real secret anywhere). Project
folders are always a subfolder of tmp_path (tmp_path itself is the vault directory).
Each route test also asserts a side effect (the file, the vault or the config), so
none passes on a status code alone.
"""
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pushkey_agent_tokens as _at
import pushkey_connect
import pushkey_connect_migrate
import pushkey_crypto
import pushkey_health
import pushkey_projectfs
import pushkey_shared as _s
import pushkey_tiers
import pushkey_vault
from pushkey_connect import ConnectError
from pushkey_crypto import encrypt_data_v3
from pushkey_projectfs import ProjectPathError
from pushkey_vault import (
    ConfigUnreadableError, VaultBusyError, load_config, load_vault, save_config, save_vault,
)

PASSWORD = "master-pw"
RECOVERY = "PUSH-AAAA-BBBB-CCCC-DDDD"
KEY = "OPENAI_API_KEY"
VALUE = "sk-original-value"
OTHER = "STRIPE_SECRET"
OTHER_VALUE = "sk_test_other_value"
PROD = "PROD_TOKEN"


def _entry(value=VALUE, env="all", provider="OpenAI"):
    return {
        "value": value, "env": env, "provider": provider,
        "created": "2026-01-01", "rotated": "2026-01-01", "projects": [],
    }


def _seed_vault(keys=None):
    _s.ensure_vault_dir()
    keys = keys if keys is not None else {
        KEY: _entry(),
        OTHER: _entry(OTHER_VALUE, provider="Stripe"),
        PROD: _entry("prod-token-value", env="prod", provider="Unknown"),
    }
    payload = {"_schema": _s.VAULT_SCHEMA_VERSION, "keys": keys}
    _s.VAULT_FILE.write_bytes(encrypt_data_v3(json.dumps(payload), PASSWORD, RECOVERY))


def _project(tmp_path, name="proj"):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _env(folder):
    return (folder / ".env").read_text(encoding="utf-8")


def _git(folder, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=folder, check=True, capture_output=True,
    )


def _stored(name=KEY):
    return load_vault(PASSWORD)[0][name]


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch):
    """One SHA-256 instead of Argon2id (64 MB, 3 passes); nothing here is about the KDF."""
    monkeypatch.setattr(
        pushkey_crypto, "_derive_key_argon2",
        lambda password, salt: hashlib.sha256(salt + password.encode()).digest(),
    )


@pytest.fixture(autouse=True)
def team_tier(monkeypatch):
    """Five agent tokens and unlimited projects; a test that needs another tier patches it."""
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "team")


@pytest.fixture
def fresh_app(monkeypatch):
    monkeypatch.setenv("PUSHKEY_LAUNCH_TOKEN", "test-launch-token")
    monkeypatch.setenv("PUSHKEY_LOCAL_PORT", "0")
    if "pushkey_local_api" in sys.modules:
        del sys.modules["pushkey_local_api"]
    return importlib.import_module("pushkey_local_api")


class Api:
    """A TestClient with the session header; one app session, so the last unlock wins."""

    def __init__(self, client, headers):
        self.client = client
        self.headers = headers

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path, **kw):
        return self.client.post(path, headers=self.headers, **kw)

    def delete(self, path, json=None, **kw):
        return self.client.request("DELETE", path, headers=self.headers, json=json, **kw)

    def unlock(self, password=PASSWORD):
        response = self.post("/api/unlock", json={"password": password})
        assert response.status_code == 200, response.text
        return response

    def mint(self, scopes, name="agent"):
        _, vault_key = load_vault(PASSWORD)
        ok, token, _ = _at.create_token(name, scopes, vault_key)
        assert ok, token
        return token

    def token(self, scopes):
        response = self.post("/api/unlock", json={"password": self.mint(scopes)})
        assert response.status_code == 200, response.text
        return response

    def recovery(self):
        response = self.post("/api/unlock", json={"recovery_code": RECOVERY})
        assert response.status_code == 200, response.text
        assert response.json()["auth_method"] == "recovery"

    def register(self, folder, **body):
        response = self.post("/api/projects", json={"path": str(folder), **body})
        assert response.status_code == 201, response.text
        return response.json()["path"]

    def connect(self, path, key=KEY, **body):
        response = self.post("/api/connections", json={"key": key, "project": path, **body})
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def api(fresh_app):
    _seed_vault()
    client = TestClient(fresh_app.app, raise_server_exceptions=False)
    boot = client.post("/api/bootstrap", headers={"Authorization": "Bearer test-launch-token"})
    assert boot.status_code == 200
    return Api(client, {"Authorization": f"Bearer {boot.json()['token']}"})


# -- one call: add a key and connect it ------------------------------------------------


def test_add_key_with_connect_writes_file(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)

    response = api.post("/api/keys", json={
        "name": "NEW_SECRET", "value": "sk_test_new_value", "env": "dev",
        "connect": {"project": path},
    })

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["name"], body["env"]) == ("NEW_SECRET", "dev")
    connection = body["connection"]
    assert (connection["project"], connection["file"], connection["var"]) == (path, ".env", "NEW_SECRET")
    assert connection["written"] is True
    assert connection["change"] == "add"
    assert "NEW_SECRET=sk_test_new_value" in _env(folder)
    assert ".env" in (folder / ".gitignore").read_text(encoding="utf-8")
    assert "sk_test_new_value" not in response.text
    stored = _stored("NEW_SECRET")
    assert [(c["project"], c["file"], c["var"]) for c in stored["connections"]] == [
        (path, ".env", "NEW_SECRET")
    ]
    assert path in stored["projects"]


def test_create_key_connect_needs_the_inject_scope(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.token(["write"])

    response = api.post("/api/keys", json={
        "name": "NEW_SECRET", "value": "sk_test_new_value", "connect": {"project": path},
    })

    assert response.status_code == 403
    assert "inject" in response.json()["detail"]
    assert not (folder / ".env").exists()
    assert "NEW_SECRET" not in load_vault(PASSWORD)[0]


def test_preview_returns_line(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)

    response = api.post("/api/connections/preview", json={"key": KEY, "project": path})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["line"] == f"Save to proj -> dev -> .env as {KEY}"
    assert (body["file"], body["var"], body["change"]) == (".env", KEY, "add")
    assert body["needs_confirm"] == []
    assert VALUE not in response.text
    assert not (folder / ".env").exists()

    mismatch = api.post("/api/connections/preview", json={"key": PROD, "project": path})
    assert mismatch.status_code == 200
    assert mismatch.json()["needs_confirm"] == ["env_mismatch"]

    unsaved = api.post("/api/connections/preview", json={
        "key": "BRAND_NEW", "project": path, "value": "sk-new", "env": "dev",
    })
    assert unsaved.status_code == 200, unsaved.text
    assert unsaved.json()["line"] == "Save to proj -> dev -> .env as BRAND_NEW"
    assert "BRAND_NEW" not in load_vault(PASSWORD)[0]


def test_preview_of_an_unregistered_project_is_404(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)

    response = api.post("/api/connections/preview", json={"key": KEY, "project": str(folder)})

    assert response.status_code == 404
    assert response.json() == {"detail": "project_not_registered"}


# -- who may register a project ----------------------------------------------------------


def test_token_session_cannot_register_project(api, tmp_path):
    api.unlock()
    existing = api.register(_project(tmp_path, "existing"))
    api.token(["write", "inject"])
    other = _project(tmp_path, "other")

    created = api.post("/api/projects", json={"path": str(other)})
    removed = api.delete("/api/projects", params={"path": existing})

    assert created.status_code == 403
    assert "master-password" in created.json()["detail"]
    assert removed.status_code == 403
    assert list(load_config(strict=True)["projects"]) == [existing]


def test_connections_route_needs_write_and_inject(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    body = {"key": KEY, "project": path}

    api.token(["write"])
    write_only = api.post("/api/connections", json=body)
    api.token(["inject"])
    inject_only = api.post("/api/connections", json=body)
    api.token(["read"])
    read_only = api.post("/api/connections", json=body)

    assert write_only.status_code == 403
    assert "inject" in write_only.json()["detail"]
    assert inject_only.status_code == 403
    assert "write" in inject_only.json()["detail"]
    assert read_only.status_code == 403
    assert not (folder / ".env").exists()
    assert not _stored().get("connections")

    api.token(["write", "inject"])
    allowed = api.post("/api/connections", json=body)
    assert allowed.status_code == 201, allowed.text
    assert f"{KEY}={VALUE}" in _env(folder)


def test_recovery_session_cannot_connect(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.recovery()
    vault_before = _s.VAULT_FILE.read_bytes()
    config_before = _s.CONFIG_FILE.read_bytes()

    connect = api.post("/api/connections", json={"key": KEY, "project": path})
    sync = api.post("/api/connections/sync", json={})
    preview = api.post("/api/connections/preview", json={"key": KEY, "project": path})

    assert connect.status_code == 403
    assert sync.status_code == 403
    assert preview.status_code == 200
    assert _s.VAULT_FILE.read_bytes() == vault_before
    assert _s.CONFIG_FILE.read_bytes() == config_before
    assert not (folder / ".env").exists()


# -- replacing and rotating a key keeps its files current --------------------------------


def test_overwrite_keeps_connections_and_syncs(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)
    assert f"{KEY}={VALUE}" in _env(folder)

    response = api.post("/api/keys", json={"name": KEY, "value": "sk-replacement", "overwrite": True})

    assert response.status_code == 201, response.text
    body = response.json()
    assert [(item["key"], item["written"], item["change"]) for item in body.get("synced", [])] == [
        (KEY, True, "replace")
    ]
    assert "sk-replacement" not in response.text
    assert f"{KEY}=sk-replacement" in _env(folder)
    assert VALUE not in _env(folder)
    stored = _stored()
    assert [(c["project"], c["file"], c["var"]) for c in stored["connections"]] == [(path, ".env", KEY)]
    assert stored["rotation_count"] == 1
    assert stored["history"][0]["value"] == VALUE
    states = api.get("/api/connections", params={"key": KEY}).json()["connections"]
    assert [row["state"] for row in states] == ["up_to_date"]


def test_rotate_syncs_connected_files(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)

    response = api.post(f"/api/keys/{KEY}/rotate", json={"new_value": "sk-rotated"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history_count"] == 1
    assert [(item["key"], item["written"], item["change"]) for item in body.get("synced", [])] == [
        (KEY, True, "replace")
    ]
    assert "not_synced" not in body
    assert "sk-rotated" not in response.text
    assert f"{KEY}=sk-rotated" in _env(folder)
    assert _stored()["value"] == "sk-rotated"


def test_promote_syncs_connected_files(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)
    assert api.post(f"/api/keys/{KEY}/backup", json={"backup_value": "sk-backup"}).status_code == 200

    response = api.post(f"/api/keys/{KEY}/promote")

    assert response.status_code == 200, response.text
    assert [item["written"] for item in response.json().get("synced", [])] == [True]
    assert f"{KEY}=sk-backup" in _env(folder)
    stored = _stored()
    assert (stored["value"], stored["next_value"]) == ("sk-backup", None)
    assert stored["history"][0]["value"] == VALUE


def test_token_rotate_without_inject_lists_not_synced(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)
    api.token(["write"])

    response = api.post(f"/api/keys/{KEY}/rotate", json={"new_value": "sk-rotated"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("not_synced") == [{"project": path, "file": ".env", "var": KEY}]
    assert "synced" not in body
    assert f"{KEY}={VALUE}" in _env(folder)
    assert _stored()["value"] == "sk-rotated"

    api.token(["write", "inject"])
    allowed = api.post(f"/api/keys/{KEY}/rotate", json={"new_value": "sk-again"})
    assert allowed.status_code == 200, allowed.text
    assert [item["written"] for item in allowed.json().get("synced", [])] == [True]
    assert "not_synced" not in allowed.json()
    assert f"{KEY}=sk-again" in _env(folder)


def test_rotate_still_succeeds_when_the_follow_up_sync_fails(api, tmp_path, monkeypatch):
    api.unlock()
    folder = _project(tmp_path)
    api.connect(api.register(folder))

    def busy(**kwargs):
        raise ConfigUnreadableError("config_busy")

    monkeypatch.setattr(pushkey_connect, "sync", busy)
    response = api.post(f"/api/keys/{KEY}/rotate", json={"new_value": "sk-rotated"})

    assert response.status_code == 200, response.text
    assert response.json().get("synced") == []
    assert response.json()["sync_error"] == "config_busy"
    assert _stored()["value"] == "sk-rotated"


# -- inject goes through the connections ---------------------------------------------------


def test_inject_replaces_connected_values(api, tmp_path):
    folder = _project(tmp_path)
    (folder / ".env").write_text(f"{KEY}=preexisting\nUNCONNECTED=keep-me\n", encoding="utf-8")
    api.unlock()
    path = api.register(folder)
    assigned = api.post("/api/projects/assign", params={"path": path}, json={"keys": [KEY]})
    assert assigned.status_code == 200, assigned.text

    response = api.post("/api/projects/inject", params={"path": path}, json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["injected"], body["wrote"]) == ([KEY], True)
    assert body["skipped_existing"] == []
    assert body["env_file"].endswith(".env")
    assert VALUE not in response.text
    env = _env(folder)
    assert f"{KEY}={VALUE}" in env
    assert "preexisting" not in env
    assert "UNCONNECTED=keep-me" in env


def test_inject_refuses_unconnected_explicit_keys(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)
    (folder / ".env").write_text(f"{KEY}=stale\n", encoding="utf-8")

    response = api.post(
        "/api/projects/inject", params={"path": path}, json={"keys": [KEY, OTHER]}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == f"keys not connected: ['{OTHER}']"
    assert _env(folder) == f"{KEY}=stale\n"

    limited = api.post("/api/projects/inject", params={"path": path}, json={"keys": [KEY]})
    assert limited.status_code == 200, limited.text
    assert f"{KEY}={VALUE}" in _env(folder)


# -- assign, unassign and the project list ---------------------------------------------------


def test_assign_needs_confirmation_for_an_environment_mismatch(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))

    refused = api.post("/api/projects/assign", params={"path": path}, json={"keys": [KEY, PROD]})

    assert refused.status_code == 409
    assert refused.json() == {"detail": "confirmation_required", "needs": ["env_mismatch"]}
    assert not _stored(KEY).get("connections")
    assert not _stored(PROD).get("connections")

    confirmed = api.post(
        "/api/projects/assign", params={"path": path},
        json={"keys": [KEY, PROD], "confirmed": ["env_mismatch"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["assigned"] == [KEY, PROD]
    assert [c["var"] for c in _stored(PROD)["connections"]] == [PROD]


def test_assign_unknown_key_is_400_and_applies_nothing(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))

    response = api.post("/api/projects/assign", params={"path": path}, json={"keys": [KEY, "GHOST"]})

    assert response.status_code == 400
    assert "GHOST" in response.json()["detail"]
    assert not _stored(KEY).get("connections")


def test_unassign_drops_the_keys_connections(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    assert api.post(
        "/api/projects/assign", params={"path": path}, json={"keys": [KEY, OTHER]}
    ).status_code == 200

    response = api.post("/api/projects/unassign", params={"path": path}, json={"keys": [KEY]})

    assert response.status_code == 200, response.text
    assert response.json()["unassigned"] == [KEY]
    assert _stored(KEY).get("connections") == []
    assert path not in _stored(KEY)["projects"]
    assert [c["var"] for c in _stored(OTHER)["connections"]] == [OTHER]
    listing = api.get("/api/projects").json()["projects"]
    assert [(p["keys"], p["connections"]) for p in listing] == [([OTHER], 1)]


def test_project_list_and_key_rows_count_connections(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path, KEY)
    api.connect(path, KEY, file=".env.local", var="OPENAI_ALT")
    api.connect(path, OTHER)

    listing = api.get("/api/projects").json()

    assert listing["count"] == 1
    project = listing["projects"][0]
    assert project["path"] == path
    assert sorted(project["keys"]) == sorted([KEY, OTHER])
    assert project["connections"] == 3
    rows = {row["name"]: row for row in api.get("/api/keys").json()["keys"]}
    assert (rows[KEY]["connections"], rows[OTHER]["connections"], rows[PROD]["connections"]) == (2, 1, 0)


def test_project_limit_returns_402(api, tmp_path, monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "free")
    api.unlock()
    first = _project(tmp_path, "first")
    second = _project(tmp_path, "second")
    assert api.post("/api/projects", json={"path": str(first)}).status_code == 201

    response = api.post("/api/projects", json={"path": str(second)})

    assert response.status_code == 402
    assert response.json() == {"detail": "project_limit"}
    assert len(load_config(strict=True)["projects"]) == 1


def test_registering_a_project_twice_is_409(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    api.register(folder)

    response = api.post("/api/projects", json={"path": str(folder)})

    assert response.status_code == 409
    assert response.json() == {"detail": "project_exists"}


def test_removing_a_project_drops_its_connections(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)

    response = api.delete("/api/projects", params={"path": path})

    assert response.status_code == 204
    assert load_config(strict=True)["projects"] == {}
    stored = _stored()
    assert (stored["connections"], stored["projects"]) == ([], [])
    assert api.delete("/api/projects", params={"path": path}).status_code == 404


# -- the connection routes -------------------------------------------------------------------------


def test_connection_routes_round_trip(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)

    listed = api.get("/api/connections", params={"key": KEY, "project": path})
    assert listed.status_code == 200
    assert [(row["key"], row["file"], row["var"], row["state"]) for row in listed.json()["connections"]] == [
        (KEY, ".env", KEY, "up_to_date")
    ]
    assert VALUE not in listed.text

    (folder / ".env").write_text(f"{KEY}=edited-by-hand\n", encoding="utf-8")
    stale = api.get("/api/connections", params={"key": KEY}).json()["connections"]
    assert [row["state"] for row in stale] == ["out_of_date"]

    synced = api.post("/api/connections/sync", json={"key": KEY, "project": path})
    assert synced.status_code == 200, synced.text
    assert [(r["key"], r["written"], r["change"]) for r in synced.json().get("synced", [])] == [(KEY, True, "replace")]
    assert f"{KEY}={VALUE}" in _env(folder)

    suggested = api.get("/api/connections/suggest", params={"key": OTHER, "project": path})
    assert suggested.status_code == 200, suggested.text
    assert suggested.json()["files"][-1] == [".env", "default env file"]
    assert OTHER in [name for name, _ in suggested.json()["vars"]]

    removed = api.delete("/api/connections", json={"key": KEY, "project": path, "file": ".env", "var": KEY})
    assert removed.status_code == 200, removed.text
    assert _stored()["connections"] == []
    assert f"{KEY}={VALUE}" in _env(folder)
    assert api.get("/api/connections", params={"key": KEY}).json() == {"connections": []}
    again = api.delete("/api/connections", json={"key": KEY, "project": path, "file": ".env", "var": KEY})
    assert again.status_code == 404
    assert again.json() == {"detail": "connection_not_found"}


def test_connection_routes_by_scope(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)

    api.token(["read"])
    assert api.get("/api/connections", params={"key": KEY}).status_code == 200
    assert api.get("/api/connections/suggest", params={"key": KEY}).status_code == 200
    assert api.post("/api/connections/preview", json={"key": KEY, "project": path}).status_code == 200
    assert api.get("/api/connect/notice").status_code == 200
    assert api.post("/api/connections/sync", json={}).status_code == 403
    gone = {"key": KEY, "project": path, "file": ".env", "var": KEY}
    assert api.delete("/api/connections", json=gone).status_code == 403
    assert api.delete("/api/connect/notice").status_code == 403
    assert len(_stored()["connections"]) == 1

    api.token(["inject"])
    assert api.post("/api/connections/sync", json={}).status_code == 200
    assert api.get("/api/connections", params={"key": KEY}).status_code == 403

    api.token(["write"])
    assert api.delete("/api/connections", json=gone).status_code == 200
    assert _stored()["connections"] == []


def test_connection_routes_skip_underscore_keys(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))

    for response in (
        api.post("/api/connections/preview", json={"key": "_meta", "project": path}),
        api.post("/api/connections", json={"key": "_meta", "project": path}),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "key_not_found"}


def test_conflict_maps_to_409(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))
    api.connect(path, KEY, var="SHARED")

    response = api.post("/api/connections", json={"key": OTHER, "project": path, "var": "SHARED"})

    assert response.status_code == 409
    assert response.json() == {"detail": "var_taken"}
    assert _stored(OTHER).get("connections") in (None, [])


def test_connect_route_refuses_tracked_file(api, tmp_path):
    folder = _project(tmp_path)
    _git(folder, "init")
    (folder / ".env").write_text(f"{KEY}=committed-old\n", encoding="utf-8")
    _git(folder, "add", ".env")
    _git(folder, "commit", "-m", "track env")
    api.unlock()
    path = api.register(folder)

    response = api.post("/api/connections", json={"key": KEY, "project": path})

    assert response.status_code == 400
    assert response.json() == {"detail": "file_tracked_by_git"}
    assert _env(folder) == f"{KEY}=committed-old\n"
    assert not _stored().get("connections")


def test_connect_needs_confirmation_then_writes(api, tmp_path):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    body = {"key": PROD, "project": path}

    refused = api.post("/api/connections", json=body)
    confirmed = api.post("/api/connections", json={**body, "confirmed": ["env_mismatch"]})

    assert refused.status_code == 409
    assert refused.json() == {"detail": "confirmation_required", "needs": ["env_mismatch"]}
    assert confirmed.status_code == 201, confirmed.text
    assert f"{PROD}=prod-token-value" in _env(folder)


def test_health_warning_header_on_connect(api, tmp_path, monkeypatch):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)

    def failing(vault):
        raise pushkey_health.HealthSidecarError("simulated sidecar failure")

    monkeypatch.setattr(pushkey_health, "publish_saved_vault", failing)
    response = api.post("/api/connections", json={"key": KEY, "project": path})

    assert response.status_code == 201, response.text
    assert response.headers.get("X-Pushkey-Warning") == "health_publication_failed"
    assert f"{KEY}={VALUE}" in _env(folder)


# -- unlock: migration and credentials -------------------------------------------------------------


def _desktop_config(folder):
    save_config({"projects": {
        "Desk": {"path": str(folder), "keys": [], "added": "2026-01-01", "target_env": "all"},
    }})


def test_unlock_runs_migration_and_notice_route(api, tmp_path):
    folder = _project(tmp_path, "desk")
    _desktop_config(folder)

    api.unlock()

    config = load_config(strict=True)
    assert config.get("connect_schema") == 1
    canonical = list(config["projects"])
    assert len(canonical) == 1 and canonical[0].endswith("desk")
    notice = api.get("/api/connect/notice")
    assert notice.status_code == 200
    assert notice.json()["notice"]["every_key_projects"] == canonical
    assert api.get("/api/projects").json()["count"] == 1

    assert api.delete("/api/connect/notice").status_code == 204

    assert api.get("/api/connect/notice").json() == {"notice": None}
    assert "connect_notice" not in load_config(strict=True)


def test_read_token_unlock_leaves_vault_bytes_unchanged(api, tmp_path):
    folder = _project(tmp_path, "desk")
    _desktop_config(folder)
    token = api.mint(["read", "write", "inject"])
    vault_before = _s.VAULT_FILE.read_bytes()
    config_before = _s.CONFIG_FILE.read_bytes()

    unlocked = api.post("/api/unlock", json={"password": token})

    assert unlocked.status_code == 200, unlocked.text
    assert _s.VAULT_FILE.read_bytes() == vault_before
    assert _s.CONFIG_FILE.read_bytes() == config_before
    assert api.get("/api/keys").status_code == 200
    blocked = api.post("/api/connections", json={"key": KEY, "project": str(folder)})
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "migration_pending"}
    assert _s.VAULT_FILE.read_bytes() == vault_before
    assert _s.CONFIG_FILE.read_bytes() == config_before


def test_only_a_password_unlock_runs_the_migration(api, tmp_path, monkeypatch):
    calls = []

    def spy(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", spy)
    token = api.mint(["read"])

    api.post("/api/unlock", json={"password": token})
    api.recovery()
    assert calls == []

    api.unlock()
    assert len(calls) == 1
    assert calls[0]["password"] == PASSWORD
    assert calls[0]["vault_key"] is not None


@pytest.mark.parametrize("failure", [OSError("disk"), RuntimeError("boom"), ConfigUnreadableError("config_busy")])
def test_unlock_survives_a_failing_migration(api, monkeypatch, failure):
    attempts = []

    def failing(**kwargs):
        attempts.append(kwargs)
        raise failure

    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", failing)

    response = api.unlock()

    assert len(attempts) == 1
    assert response.json()["auth_method"] == "password"
    assert api.get("/api/keys").status_code == 200


def test_unlock_works_with_unreadable_config(api):
    garbage = b"this is not a config \x00\xff"
    _s.CONFIG_FILE.write_bytes(garbage)

    api.unlock()

    assert api.get("/api/keys").status_code == 200
    response = api.get("/api/projects")
    assert response.status_code == 503
    assert response.json() == {"detail": "config_unreadable"}
    assert _s.CONFIG_FILE.read_bytes() == garbage


def test_core_credentials_never_hand_over_a_non_password_secret(fresh_app):
    vault = {}
    key = b"k" * 32
    sess = fresh_app._Session()

    sess.unlock(vault, key, "PUSH-RECOVERY-CODE", method="recovery")
    recovery = fresh_app._core_credentials(sess)
    sess.unlock(vault, key, "leaked-secret", method="agent_token", scopes=["write"])
    token = fresh_app._core_credentials(sess)
    sess.unlock(vault, key, "the-master-password", method="password")
    password = fresh_app._core_credentials(sess)

    assert recovery.get("password", "<absent>") is None
    assert token.get("password", "<absent>") is None
    assert password.get("password", "<absent>") == "the-master-password"
    for creds in (recovery, token, password):
        assert creds.get("vault_key") == key
        assert creds.get("target") is vault


# -- errors map to one set of statuses -------------------------------------------------------------


_CONNECT_STATUS = {
    "migration_pending": 409, "key_exists": 409, "key_not_found": 404,
    "project_not_registered": 404, "var_taken": 409, "file_tracked_by_git": 400,
    "vault_changed": 409, "vault_unavailable": 423, "project_exists": 409,
    "project_limit": 402, "connection_not_found": 404, "invalid_var": 400,
    "invalid_env_file": 400, "read_failed": 500, "backup_failed": 500,
}

_ERROR_CASES = [
    (ConnectError(code, {"key": "SOME_KEY", "project": "/some/where"}), status, {"detail": code})
    for code, status in _CONNECT_STATUS.items()
] + [
    (
        ConnectError("confirmation_required", {"needs": ["env_mismatch", "public_prefix"]}),
        409,
        {"detail": "confirmation_required", "needs": ["env_mismatch", "public_prefix"]},
    ),
    (ConfigUnreadableError("config_unreadable"), 503, {"detail": "config_unreadable"}),
    (ConfigUnreadableError("config_busy"), 503, {"detail": "config_busy"}),
    (ProjectPathError(400, "invalid project path"), 400, {"detail": "invalid project path"}),
    (ProjectPathError(404, "project directory not found"), 404, {"detail": "project directory not found"}),
    (ConnectError("a_code_the_api_does_not_know"), 500, {"detail": "a_code_the_api_does_not_know"}),
]


@pytest.mark.parametrize(
    "error, status, body", _ERROR_CASES, ids=[f"{type(e).__name__}-{e}" for e, _, _ in _ERROR_CASES]
)
def test_error_map_covers_every_code(fresh_app, error, status, body):
    assert fresh_app._error_status_and_body(error) == (status, body)


def test_unlock_without_a_vault_file_creates_none(fresh_app):
    client = TestClient(fresh_app.app)
    boot = client.post("/api/bootstrap", headers={"Authorization": "Bearer test-launch-token"})
    headers = {"Authorization": f"Bearer {boot.json()['token']}"}
    assert not _s.VAULT_FILE.exists()

    client.post("/api/unlock", headers=headers, json={"password": PASSWORD})

    assert not _s.VAULT_FILE.exists()


# -- fix round 1 ---------------------------------------------------------------------------------


def _canonical(folder):
    return pushkey_projectfs.canonical_project_path(str(folder))


def _edit_vault(api, change):
    """Change the vault on disk behind the session's back, then unlock again to reload it."""
    vault, vault_key = load_vault(PASSWORD)
    change(vault)
    save_vault(vault, PASSWORD, vault_key=vault_key)
    api.unlock()


def test_inject_of_named_keys_keeps_the_backup_taken_before_the_inject(api, tmp_path):
    names = [KEY, OTHER, "THIRD_KEY", "FOURTH_KEY"]
    _seed_vault({
        KEY: _entry(), OTHER: _entry(OTHER_VALUE, provider="Stripe"),
        "THIRD_KEY": _entry("third-value"), "FOURTH_KEY": _entry("fourth-value"),
    })
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    for name in names:
        api.connect(path, name)
    hand_set = "".join(f"{name}=hand-set-{index}\n" for index, name in enumerate(names)).encode()
    (folder / ".env").write_bytes(hand_set)
    shutil.rmtree(_s.ENV_BACKUPS_DIR, ignore_errors=True)

    response = api.post("/api/projects/inject", params={"path": path}, json={"keys": names})

    assert response.status_code == 200, response.text
    assert sorted(response.json()["injected"]) == sorted(names)
    env = _env(folder)
    assert f"{KEY}={VALUE}" in env and "THIRD_KEY=third-value" in env and "hand-set" not in env
    backups = sorted(Path(_s.ENV_BACKUPS_DIR).rglob("*.bak"))
    assert [backup.read_bytes() for backup in backups] == [hand_set]


@pytest.mark.parametrize("error, code", [
    (ConnectError("migration_pending"), "migration_pending"),
    (ConfigUnreadableError("config_busy"), "config_busy"),
    (VaultBusyError("sk-leaked-detail"), "VaultBusyError"),
    (OSError("sk-leaked-detail"), "OSError"),
    (ValueError("sk-leaked-detail"), "ValueError"),
])
def test_rotate_reports_any_follow_up_sync_failure_as_a_code(api, tmp_path, monkeypatch, error, code):
    api.unlock()
    api.connect(api.register(_project(tmp_path)))

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(pushkey_connect, "sync", fail)
    response = api.post(f"/api/keys/{KEY}/rotate", json={"new_value": "sk-rotated"})

    assert response.status_code == 200, response.text
    assert response.json().get("synced") == []
    assert response.json().get("sync_error") == code
    assert "sk-leaked-detail" not in response.text
    assert _stored()["value"] == "sk-rotated"


def test_unassign_drops_the_allowlist_entry_of_a_key_with_no_connection(api, tmp_path):
    api.unlock()
    folder, other = _project(tmp_path, "proj"), _project(tmp_path, "other")
    path, other_path = api.register(folder), api.register(other)
    api.connect(other_path, KEY)
    api.connect(path, OTHER)

    def allow_without_connection(vault):
        vault[KEY]["projects"] = [path, other_path]
        vault[PROD]["projects"] = [path]

    _edit_vault(api, allow_without_connection)

    response = api.post("/api/projects/unassign", params={"path": path}, json={"keys": [KEY]})

    assert response.status_code == 200, response.text
    assert _stored(KEY)["projects"] == [other_path]
    assert [c["project"] for c in _stored(KEY)["connections"]] == [other_path]
    assert _stored(OTHER)["projects"] == [path]
    assert [c["project"] for c in _stored(OTHER)["connections"]] == [path]
    assert _stored(PROD)["projects"] == [path]


def test_unassign_of_a_key_with_connections_drops_them_and_the_allowlist_entry(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))
    api.connect(path, KEY)
    api.connect(path, KEY, file=".env.local", var="OPENAI_ALT")

    response = api.post("/api/projects/unassign", params={"path": path}, json={"keys": [KEY]})

    assert response.status_code == 200, response.text
    assert _stored(KEY)["connections"] == []
    assert _stored(KEY)["projects"] == []


def test_preview_with_a_value_or_env_needs_a_session_that_can_write(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))
    plain = {"key": KEY, "project": path}
    refusal = {"detail": "agent token missing required scope: write"}

    api.token(["read"])
    without_value = api.post("/api/connections/preview", json=plain)
    with_value = api.post("/api/connections/preview", json={**plain, "value": "sk-unsaved"})
    with_env = api.post("/api/connections/preview", json={**plain, "env": "dev"})

    assert without_value.status_code == 200, without_value.text
    assert (with_value.status_code, with_value.json()) == (403, refusal)
    assert (with_env.status_code, with_env.json()) == (403, refusal)

    api.token(["read", "write"])
    assert api.post("/api/connections/preview", json={**plain, "value": "sk-unsaved"}).status_code == 200
    api.unlock()
    assert api.post("/api/connections/preview", json={**plain, "value": "sk-unsaved"}).status_code == 200


def test_preview_with_a_value_is_refused_for_a_recovery_session(api, tmp_path):
    api.unlock()
    path = api.register(_project(tmp_path))
    api.recovery()

    plain = api.post("/api/connections/preview", json={"key": KEY, "project": path})
    with_value = api.post(
        "/api/connections/preview", json={"key": KEY, "project": path, "value": "sk-unsaved"}
    )

    assert plain.status_code == 200, plain.text
    assert (with_value.status_code, with_value.json()) == (
        403, {"detail": "write requires master-password unlock"}
    )


def test_underscore_vault_entries_are_never_listed_or_injected(api, tmp_path):
    folder = _project(tmp_path)
    path = _canonical(folder)
    meta = _entry("meta-secret-value")
    meta["connections"] = [
        {"project": path, "file": ".env", "var": "META_VAR", "added": "2026-11-21T10:00:00"}
    ]
    _seed_vault({KEY: _entry(), "_meta": meta})
    api.unlock()
    assert api.register(folder) == path
    api.connect(path, KEY)

    listed = api.get("/api/connections")
    injected = api.post("/api/projects/inject", params={"path": path}, json={})

    assert listed.status_code == 200, listed.text
    assert [row["key"] for row in listed.json()["connections"]] == [KEY]
    assert injected.status_code == 200, injected.text
    assert {r["key"] for r in injected.json()["results"]} == {KEY}
    assert "meta-secret-value" not in _env(folder) and "META_VAR" not in _env(folder)


def test_canonicalising_a_legacy_project_key_keeps_its_connections(api, tmp_path, monkeypatch):
    api.unlock()
    folder = _project(tmp_path)
    path = api.register(folder)
    api.connect(path)
    # A spelling of the folder that resolves to `path` but that no path normalisation
    # can see through (a link or short name), faked at the one resolver both sides use.
    legacy = str(tmp_path / "legacy-spelling")
    real = pushkey_projectfs.canonical_project_path
    monkeypatch.setattr(
        pushkey_projectfs, "canonical_project_path",
        lambda raw, **kw: path if raw == legacy else real(raw, **kw),
    )
    config = load_config(strict=True)
    config["projects"][legacy] = config["projects"].pop(path)
    save_config(config)

    def spell_legacy(vault):
        vault[KEY]["projects"] = [legacy]
        for conn in vault[KEY]["connections"]:
            conn["project"] = legacy

    _edit_vault(api, spell_legacy)

    listing = api.get("/api/projects")

    assert listing.status_code == 200, listing.text
    assert [(p["path"], p["keys"], p["connections"]) for p in listing.json()["projects"]] == [
        (path, [KEY], 1)
    ]
    stored = _stored()
    assert [c["project"] for c in stored["connections"]] == [path]
    assert stored["projects"] == [path]
    states = api.get("/api/connections", params={"key": KEY}).json()["connections"]
    assert [(row["project"], row["state"]) for row in states] == [(path, "up_to_date")]

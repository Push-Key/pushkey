"""Add-and-connect tools of the MCP server (pushkey_mcp), routed through pushkey_connect.

The vault is a V3 password vault with one key, STRIPE_TEST_KEY (a dummy value), and one
project folder, tmp_path/"proj" (tmp_path itself is the vault directory), registered the
way a person registers it. No test passes a real secret. A test that asserts "nothing was
written" also asserts one thing the tool did do, so it cannot pass vacuously.
"""
import hashlib
import importlib
import inspect
import json
import sys

import pytest

import pushkey_agent_tokens
import pushkey_connect
import pushkey_connect_migrate
import pushkey_crypto
import pushkey_projectfs
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_connect import ConnectError
from pushkey_vault import ConfigUnreadableError, load_config, load_vault, save_config, save_vault

PASSWORD = "pw"
KEY = "STRIPE_TEST_KEY"
VALUE = "tok_dummy_abc123"
OTHER = "OTHER_TEST_KEY"
OTHER_VALUE = "tok_dummy_other999"
NOT_REGISTERED_HINT = "A person must add this folder as a project in Pushkey first."
MIGRATION_PENDING_HINT = "Open Pushkey with your master password once to finish migrating projects."
TRACKED_HINT = "this file is committed to git; Pushkey will not write secrets into it"


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch):
    """Derive vault keys with one SHA-256 instead of Argon2id (64 MB, 3 passes).

    Nothing here is about the KDF; tests/test_vault_crypto.py covers the real one.
    """
    monkeypatch.setattr(
        pushkey_crypto, "_derive_key_argon2",
        lambda password, salt: hashlib.sha256(salt + password.encode()).digest(),
    )


@pytest.fixture(autouse=True)
def pro_tier(monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")


def _fresh_mcp():
    sys.modules.pop("pushkey_mcp", None)
    return importlib.import_module("pushkey_mcp")


def _entry(value=VALUE, **extra):
    entry = {
        "value": value, "created": "2026-01-01", "rotated": None,
        "provider": "Stripe", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


def _get(reply, field):
    """`reply[field]`; an absent field is a failed assertion, not a KeyError."""
    assert field in reply, f"reply has no {field!r}: {sorted(reply)}"
    return reply[field]


def _only(items):
    items = list(items)
    assert len(items) == 1, f"expected exactly one item, got {len(items)}"
    return items[0]


class _World:
    """A seeded vault, an unlocked master-password MCP session and one registered folder."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.folder = tmp_path / "proj"
        self.folder.mkdir()
        save_vault({KEY: _entry(), OTHER: _entry(OTHER_VALUE)}, PASSWORD, recovery_code=_recovery())
        self.mod = _fresh_mcp()
        assert self.mod._unlock(PASSWORD)["success"]
        self.project, _ = pushkey_connect.register_project(str(self.folder))

    def vault(self):
        loaded, _ = load_vault(PASSWORD)
        return loaded

    def env(self):
        path = self.folder / ".env"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def connect(self, name=KEY, **kw):
        return self.mod.connect_key(name, str(self.folder), **kw)

    def folder_named(self, name):
        folder = self.root / name
        folder.mkdir()
        return folder

    def token_session(self, scopes):
        """Lock the master session and unlock one with a fresh agent token of `scopes`."""
        _, vault_key = load_vault(PASSWORD)
        ok, token, _ = pushkey_agent_tokens.create_token("t", scopes, vault_key)
        assert ok, token
        self.mod._lock()
        assert self.mod._unlock(token)["success"]


def _recovery():
    return pushkey_crypto.generate_recovery_code()


@pytest.fixture
def world(tmp_path):
    return _World(tmp_path)


# -- refusals: an unregistered folder ---------------------------------------------------


def test_mcp_connect_key_refuses_unregistered_folder(world):
    other = world.folder_named("other")

    reply = world.mod.connect_key(KEY, str(other))

    assert reply == {
        "success": False, "error": "project_not_registered", "hint": NOT_REGISTERED_HINT,
    }
    assert not (other / ".env").exists() and not (other / ".gitignore").exists()
    assert world.vault()[KEY]["connections"] == []
    # The registered folder is not affected by the refusal.
    assert world.connect()["success"] is True


def test_mcp_assign_key_refuses_unregistered_folder(world):
    other = world.folder_named("other")
    before = world.vault()[KEY]

    reply = world.mod.assign_key(KEY, str(other))

    assert reply == {
        "success": False, "error": "project_not_registered", "hint": NOT_REGISTERED_HINT,
    }
    after = world.vault()[KEY]
    assert after["projects"] == before["projects"] == []
    assert after["connections"] == before["connections"] == []
    assert world.mod.assign_key(KEY, str(world.folder))["success"] is True


def test_mcp_inject_env_refuses_unregistered_folder(world):
    other = world.folder_named("other")

    reply = world.mod.inject_env(str(other), keys=[KEY])

    assert reply == {
        "success": False, "error": "project_not_registered", "hint": NOT_REGISTERED_HINT,
    }
    assert not (other / ".env").exists() and not (other / ".gitignore").exists()
    # With no keys named the registered check still comes first.
    assert world.mod.inject_env(str(other))["error"] == "project_not_registered"


# -- connect_key ------------------------------------------------------------------------


def test_mcp_connect_reply_has_no_value(world):
    reply = world.connect()

    assert reply["success"] is True
    assert _get(reply, "connection")["written"] is True and _get(reply, "connection")["var"] == KEY
    assert VALUE not in json.dumps(reply)
    assert f"{KEY}={VALUE}" in world.env()
    conn = _only(world.vault()[KEY]["connections"])
    assert (conn["project"], conn["file"], conn["var"]) == (world.project, ".env", KEY)


def test_connect_key_takes_no_value_parameter():
    mod = _fresh_mcp()
    parameters = list(inspect.signature(mod.connect_key).parameters)

    assert "value" not in parameters
    assert parameters == ["name", "project_path", "file", "var", "confirm"]


def test_preview_connection_has_no_value_parameters():
    mod = _fresh_mcp()

    assert list(inspect.signature(mod.preview_connection).parameters) == [
        "name", "project_path", "file", "var",
    ]


@pytest.mark.parametrize(
    "scopes, missing",
    [(["read", "write"], "inject"), (["read", "inject"], "write")],
)
def test_connect_key_needs_write_and_inject(world, scopes, missing):
    world.mod._SESSION["scopes"] = scopes

    reply = world.connect()

    assert reply["error"] == "scope_denied" and reply["required_scope"] == missing
    assert world.env() is None
    assert world.vault()[KEY]["connections"] == []


def test_connect_key_unknown_key_is_key_not_found_and_never_creates_one(world):
    reply = world.connect("NO_SUCH_KEY")

    assert reply["success"] is False and reply["error"] == "key_not_found"
    assert "NO_SUCH_KEY" not in world.vault()
    assert world.env() is None


def test_connect_key_confirm_maps_to_the_cores_confirmations(world):
    refused = world.connect(var="NEXT_PUBLIC_STRIPE")

    assert refused["success"] is False and refused["error"] == "confirmation_required"
    assert refused["needs"] == ["public_prefix"]
    assert world.env() is None

    allowed = world.connect(var="NEXT_PUBLIC_STRIPE", confirm=["public_prefix"])

    assert allowed["success"] is True and allowed["connection"]["var"] == "NEXT_PUBLIC_STRIPE"
    assert "NEXT_PUBLIC_STRIPE=" in world.env()


def test_connect_key_reports_a_failed_write_as_a_result_not_an_error(world):
    (world.folder / ".env").mkdir()  # a directory where the file should be

    reply = world.connect()

    assert reply["success"] is True
    assert _get(reply, "connection")["written"] is False and _get(reply, "connection")["reason"]
    assert VALUE not in json.dumps(reply)


# -- preview_connection and key_usage ---------------------------------------------------


def test_preview_connection_names_the_line_and_carries_no_value(world):
    reply = world.mod.preview_connection(KEY, str(world.folder))

    assert reply["success"] is True
    assert _get(reply, "preview")["line"] == f"Save to proj -> dev -> .env as {KEY}"
    assert _get(reply, "preview")["change"] == "add"
    assert VALUE not in json.dumps(reply)
    assert world.env() is None and world.vault()[KEY]["connections"] == []


def test_preview_connection_refuses_an_unregistered_folder_and_a_read_only_lock(world):
    other = world.folder_named("other")

    assert world.mod.preview_connection(KEY, str(other))["error"] == "project_not_registered"
    assert world.mod.preview_connection("NO_SUCH_KEY", str(world.folder))["error"] == "key_not_found"
    world.mod._lock()
    assert world.mod.preview_connection(KEY, str(world.folder))["error"] == "vault_locked"


def test_key_usage_has_no_value(world):
    world.connect()

    reply = world.mod.key_usage(KEY)

    assert reply["success"] is True and reply["name"] == KEY
    row = _only(_get(reply, "connections"))
    assert (row["key"], row["project"], row["file"], row["var"]) == (KEY, world.project, ".env", KEY)
    assert row["state"] == "up_to_date" and row["project_name"] == "proj"
    assert VALUE not in json.dumps(reply)


def test_key_usage_unknown_and_underscore_names(world):
    assert world.mod.key_usage("NO_SUCH_KEY")["error"] == "key_not_found"
    assert world.mod.key_usage("_meta")["success"] is False
    world.mod._SESSION["vault"]["_meta"] = {"value": VALUE}
    assert world.mod.key_usage("_meta")["success"] is False
    assert all(not k["name"].startswith("_") for k in world.mod.list_keys()["keys"])


# -- assign_key and inject_env ----------------------------------------------------------


def test_assign_key_connects_without_writing_the_file(world):
    reply = world.mod.assign_key(KEY, str(world.folder))

    assert reply["success"] is True and reply["key"] == KEY
    assert _get(reply, "connection")["written"] is False and _get(reply, "connection")["reason"] == "write_skipped"
    assert VALUE not in json.dumps(reply)
    assert world.env() is None
    entry = world.vault()[KEY]
    assert entry["projects"] == [world.project]
    assert _only(entry["connections"])["var"] == KEY


def test_mcp_inject_env_writes_connected_keys_in_one_pass(world):
    world.mod.assign_key(KEY, str(world.folder))
    world.mod.assign_key(OTHER, str(world.folder))

    reply = world.mod.inject_env(str(world.folder))

    assert reply["success"] is True
    assert reply["injected_count"] == 2 and sorted(reply["injected_names"]) == [OTHER, KEY]
    assert reply["skipped_count"] == 0 and reply["skipped_existing"] == []
    assert len(_get(reply, "results")) == 2
    assert VALUE not in json.dumps(reply) and OTHER_VALUE not in json.dumps(reply)
    assert f"{KEY}={VALUE}" in world.env() and f"{OTHER}={OTHER_VALUE}" in world.env()
    assert ".env" in (world.folder / ".gitignore").read_text(encoding="utf-8")
    assert len(list(pushkey_shared.ENV_BACKUPS_DIR.rglob("*.bak"))) <= 1


def test_mcp_inject_env_explicit_unconnected_key_refused(world):
    world.mod.assign_key(KEY, str(world.folder))

    reply = world.mod.inject_env(str(world.folder), keys=[KEY, OTHER])

    assert reply["success"] is False
    assert reply["error"] == f"keys not connected: ['{OTHER}']"
    assert world.env() is None  # nothing was written for the connected key either
    # The connected key alone is fine.
    assert world.mod.inject_env(str(world.folder), keys=[KEY])["injected_names"] == [KEY]


def test_mcp_inject_env_names_keys_that_are_not_in_the_vault(world):
    reply = world.mod.inject_env(str(world.folder), keys=["NO_SUCH_KEY"])

    assert reply["success"] is False and "NO_SUCH_KEY" in reply["error"]


def test_mcp_inject_env_with_nothing_connected_says_so(world):
    reply = world.mod.inject_env(str(world.folder))

    assert reply["success"] is False and "connected" in reply["error"]
    assert world.env() is None


# -- rotation: add_key(overwrite), rotate_key, rotate_to_backup -------------------------


def _backup_ready(world, name=KEY, backup="tok_dummy_backup777"):
    assert world.mod.set_backup_key(name, backup)["success"]
    return backup


def test_rotate_to_backup_syncs_connected_file(world):
    world.connect()
    backup = _backup_ready(world)

    reply = world.mod.rotate_to_backup(KEY)

    assert reply["success"] is True and reply["backup_slot"] == "empty"
    synced = _only(_get(reply, "synced"))
    assert synced["written"] is True and synced["var"] == KEY
    assert f"{KEY}={backup}" in world.env() and VALUE not in world.env()
    assert backup not in json.dumps(reply) and VALUE not in json.dumps(reply)
    entry = world.vault()[KEY]
    assert entry["value"] == backup and entry["next_value"] is None and entry["next_added"] is None
    assert entry["history"][0]["value"] == VALUE  # replace_value kept the old value in history


def test_rotate_key_syncs_connected_file(world):
    world.connect()

    reply = world.mod.rotate_key(KEY, "tok_dummy_rotated456")

    assert reply["success"] is True and "MCP client context" in reply["warning"]
    assert _only(_get(reply, "synced"))["written"] is True
    assert f"{KEY}=tok_dummy_rotated456" in world.env()
    assert "tok_dummy_rotated456" not in json.dumps({k: v for k, v in reply.items() if k != "warning"})
    entry = world.vault()[KEY]
    assert entry["value"] == "tok_dummy_rotated456" and entry["connections"]


def test_add_key_overwrite_replaces_the_value_keeps_connections_and_syncs(world):
    world.connect()

    reply = world.mod.add_key(KEY, "tok_dummy_over789", overwrite=True)

    assert reply["success"] is True and "MCP client context" in reply["warning"]
    assert _only(_get(reply, "synced"))["written"] is True
    assert f"{KEY}=tok_dummy_over789" in world.env()
    entry = world.vault()[KEY]
    assert entry["value"] == "tok_dummy_over789"
    assert _only(entry["connections"])["var"] == KEY and entry["provider"] == "Stripe"


def test_add_key_new_key_stays_on_the_plain_path(world):
    reply = world.mod.add_key("BRAND_NEW_KEY", "tok_dummy_new000")

    assert reply["success"] is True and "synced" not in reply and "not_synced" not in reply
    assert world.vault()["BRAND_NEW_KEY"]["value"] == "tok_dummy_new000"


def test_mcp_rotate_without_inject_lists_not_synced(world):
    world.connect()
    world.mod._SESSION["scopes"] = ["read", "write"]

    reply = world.mod.rotate_key(KEY, "tok_dummy_rotated456")

    assert reply["success"] is True
    assert _get(reply, "not_synced") == [{"project": world.project, "file": ".env", "var": KEY}]
    assert "synced" not in reply
    assert f"{KEY}={VALUE}" in world.env()  # the file still holds the old value
    assert world.vault()[KEY]["value"] == "tok_dummy_rotated456"


def test_mcp_rotate_to_backup_without_inject_lists_not_synced(world):
    world.connect()
    _backup_ready(world)
    world.mod._SESSION["scopes"] = ["read", "write"]

    reply = world.mod.rotate_to_backup(KEY)

    assert reply["success"] is True
    assert _get(reply, "not_synced") == [{"project": world.project, "file": ".env", "var": KEY}]


@pytest.mark.parametrize(
    "raised, code",
    [
        (RuntimeError("leaks tok_dummy_rotated456"), "RuntimeError"),
        (ConnectError("vault_changed"), "vault_changed"),
        (ConfigUnreadableError("config_busy"), "config_busy"),
    ],
)
def test_mcp_sync_failure_after_rotate_is_a_code_only_field(world, monkeypatch, raised, code):
    world.connect()

    def boom(**kwargs):
        raise raised

    monkeypatch.setattr(pushkey_connect, "sync", boom)

    reply = world.mod.rotate_key(KEY, "tok_dummy_rotated456")

    assert reply["success"] is True and _get(reply, "sync_error") == code
    assert "tok_dummy_rotated456" not in json.dumps({k: v for k, v in reply.items() if k != "warning"})
    assert world.vault()[KEY]["value"] == "tok_dummy_rotated456"  # the change itself stands


def test_rotate_key_unknown_key_and_hostile_name_keep_their_errors(world):
    assert world.mod.rotate_key("NO_SUCH_KEY", "x")["error"] == "key 'NO_SUCH_KEY' not found"
    assert world.mod.rotate_key("BAD\nNAME", "x")["error"] == "invalid key name"


# -- warnings (AGENTS.md: plaintext tools keep their text) ------------------------------


def test_add_key_warning_text_unchanged(world):
    reply = world.mod.add_key("NEW_KEY", "tok_dummy_new000", provider="OpenAI", env="dev")

    assert reply["success"] is True
    assert "MCP client context" in reply["warning"]
    assert "pushkey add NEW_KEY" in reply["warning"]
    assert reply["warning"] == (
        "Key value entered the MCP client context and may be retained by the client, "
        "model provider, transcript, or telemetry. "
        "OK for dev/test keys. For production keys, add via local CLI: "
        "`pushkey add NEW_KEY` (hidden prompt, no LLM exposure)."
    )


def test_rotate_and_backup_warning_text_unchanged(world):
    rotated = world.mod.rotate_key(KEY, "tok_dummy_rotated456")
    backup = world.mod.set_backup_key(KEY, "tok_dummy_backup777")

    assert rotated["warning"] == (
        "New key value entered the MCP client context and may be retained by the "
        "client, model provider, transcript, or telemetry. "
        "OK for dev/test keys. For production keys, prefer `pushkey rotate` (CLI, getpass) "
        "or pre-stage a backup and use rotate_to_backup() so secrets never cross chat."
    )
    assert "MCP client context" in backup["warning"] and "local CLI" in backup["warning"]


# -- error map --------------------------------------------------------------------------

CONNECT_ERROR_CODES = [
    "migration_pending", "key_not_found", "key_exists", "var_taken", "confirmation_required",
    "file_tracked_by_git", "invalid_var", "invalid_env_file", "read_failed", "backup_failed",
    "vault_changed", "vault_unavailable", "project_not_registered", "project_exists",
    "project_limit", "connection_not_found",
]


@pytest.mark.parametrize("code", CONNECT_ERROR_CODES)
def test_mcp_error_map_covers_every_code(world, monkeypatch, code):
    detail = {"needs": ["env_mismatch"]} if code == "confirmation_required" else {"key": "x"}

    def refuse(**kwargs):
        raise ConnectError(code, detail)

    monkeypatch.setattr(pushkey_connect, "connect", refuse)

    reply = world.connect()

    assert reply["success"] is False and reply["error"] == code
    if code == "confirmation_required":
        assert reply["needs"] == ["env_mismatch"]
    elif code == "migration_pending":
        assert reply["hint"] == MIGRATION_PENDING_HINT
    elif code == "project_not_registered":
        assert reply["hint"] == NOT_REGISTERED_HINT
    elif code == "file_tracked_by_git":
        assert reply["hint"] == TRACKED_HINT
    assert set(reply) <= {"success", "error", "hint", "needs"}  # nothing from the error detail


@pytest.mark.parametrize(
    "raised, code",
    [
        (ConfigUnreadableError("config_unreadable"), "config_unreadable"),
        (ConfigUnreadableError("config_busy"), "config_busy"),
        (pushkey_projectfs.ProjectPathError(400, "project path must be absolute"), "project path must be absolute"),
    ],
)
def test_mcp_error_map_covers_the_other_error_types(world, monkeypatch, raised, code):
    def refuse(**kwargs):
        raise raised

    monkeypatch.setattr(pushkey_connect, "connect", refuse)

    reply = world.connect()

    assert reply["success"] is False and reply["error"] == code


# -- unlock and sessions ----------------------------------------------------------------


def _legacy_config(folder):
    save_config({"projects": {"legacy": {"path": str(folder), "created": "2026-01-02", "keys": [KEY]}}})


def test_mcp_unlock_runs_migration_for_master_password(tmp_path):
    folder = tmp_path / "legacy-app"
    folder.mkdir()
    save_vault({KEY: _entry()}, PASSWORD)
    _legacy_config(folder)
    assert not pushkey_connect.is_migrated(load_config(strict=True))
    mod = _fresh_mcp()

    reply = mod._unlock(PASSWORD)

    assert reply["success"] is True and reply["key_count"] == 1
    config = load_config(strict=True)
    assert pushkey_connect.is_migrated(config) and set(config["projects"]) == {str(folder.resolve())}
    entry = load_vault(PASSWORD)[0][KEY]
    assert _only(entry["connections"])["var"] == KEY
    assert mod._SESSION["vault"][KEY]["connections"] == entry["connections"]


def test_mcp_unlock_survives_a_migration_error_and_logs_names_only(tmp_path, monkeypatch):
    save_vault({KEY: _entry()}, PASSWORD)
    logged = []
    mod = _fresh_mcp()

    def boom(**kwargs):
        raise OSError(f"disk says {VALUE}")

    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", boom)
    monkeypatch.setattr(pushkey_crypto, "log_event", logged.append)

    reply = mod._unlock(PASSWORD)

    assert reply["success"] is True and "vault" in mod._SESSION
    assert logged and all(VALUE not in line for line in logged)
    assert any("OSError" in line for line in logged)


def test_mcp_unlock_without_a_vault_file_runs_no_migration(monkeypatch):
    calls = []
    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", lambda **kw: calls.append(kw))
    mod = _fresh_mcp()
    assert not pushkey_shared.VAULT_FILE.exists()

    mod._unlock(PASSWORD)

    assert calls == []
    assert not pushkey_shared.VAULT_FILE.exists()


def test_mcp_token_unlock_never_runs_migration(world, monkeypatch):
    calls = []
    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", lambda **kw: calls.append(kw))

    world.token_session(["read", "write", "inject"])

    assert world.mod._SESSION["password"] is None
    assert calls == []


def test_mcp_token_unlock_leaves_vault_and_config_bytes_unchanged(tmp_path):
    folder = tmp_path / "legacy-app"
    folder.mkdir()
    save_vault({KEY: _entry()}, PASSWORD, recovery_code=_recovery())
    _, vault_key = load_vault(PASSWORD)
    _legacy_config(folder)
    ok, token, _ = pushkey_agent_tokens.create_token("t", ["read", "write", "inject"], vault_key)
    assert ok, token
    vault_before = pushkey_shared.VAULT_FILE.read_bytes()
    config_before = pushkey_shared.CONFIG_FILE.read_bytes()
    mod = _fresh_mcp()

    assert mod._unlock(token)["success"] is True

    assert pushkey_shared.VAULT_FILE.read_bytes() == vault_before
    assert pushkey_shared.CONFIG_FILE.read_bytes() == config_before
    reply = mod.connect_key(KEY, str(folder))
    assert reply == {
        "success": False, "error": "migration_pending", "hint": MIGRATION_PENDING_HINT,
    }
    assert pushkey_shared.VAULT_FILE.read_bytes() == vault_before
    assert pushkey_shared.CONFIG_FILE.read_bytes() == config_before
    assert not (folder / ".env").exists()


def test_mcp_token_session_gives_the_core_no_password(world, monkeypatch):
    seen = {}
    real = pushkey_connect.connect

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(pushkey_connect, "connect", spy)

    assert world.connect()["success"] is True
    assert seen["password"] == PASSWORD and seen["actor"] == "mcp"
    assert seen["target"] is world.mod._SESSION["vault"]

    world.token_session(["read", "write", "inject"])
    seen.clear()
    reply = world.mod.connect_key(OTHER, str(world.folder))

    assert reply["success"] is True
    assert seen["password"] is None and seen["actor"] == "mcp agent-token"
    assert isinstance(seen["vault_key"], bytes)
    assert f"{OTHER}={OTHER_VALUE}" in world.env()


def test_mcp_token_session_rotate_syncs_through_the_core(world):
    world.connect()
    world.token_session(["read", "write", "inject"])

    reply = world.mod.rotate_key(KEY, "tok_dummy_rotated456")

    assert reply["success"] is True and _only(_get(reply, "synced"))["written"] is True
    assert f"{KEY}=tok_dummy_rotated456" in world.env()

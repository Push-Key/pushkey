"""
Pushkey MCP Server — exposes vault operations as MCP tools for Claude Code / VS Code.

Usage:
    python pushkey_mcp.py           # stdio transport (Claude Code)
    python pushkey_mcp.py --port 8765  # SSE transport (VS Code Copilot)

Authentication
    Master password : unlock_vault("my-master-password")
    Agent token     : unlock_vault("pk_agent_...")   # Pro+ only

────────────────────────────────────────────────────────────────────────────
Plaintext-over-chat policy (read this before using write tools)
────────────────────────────────────────────────────────────────────────────
Tool arguments enter the MCP client context and, depending on the client and
provider configuration, may cross the model-provider boundary or be retained
in transcripts or telemetry. The vault itself remains local and encrypted.

Safe by argument and output shape:
    ✅ Metadata/name-only  (list_keys, check_health, rotate_to_backup,
                            inject_env, preview_connection, connect_key,
                            key_usage, assign_key)
    ⚠️  Secret-bearing     (get_key) — the returned value enters the MCP
        output              client context and may be retained by the client,
                            model provider, transcript, or telemetry
    ⚠️  Plaintext-secret    (add_key, rotate_key, set_backup_key) —
        tools                value may be sent to a model provider or retained
                             in client transcripts or telemetry

Recommended use:
    • Dev / throwaway / test keys     → plaintext MCP tools are fine, fast
    • Long-lived / production keys    → use the local CLI (getpass) instead:
                                          pushkey add  <NAME>
                                          pushkey rotate <NAME>
                                          pushkey set-backup <NAME>
                                        Then drive promotion from chat with
                                          rotate_to_backup(<NAME>)
                                        — only the name crosses the wire.

Each plaintext tool returns a `warning` field so the agent can surface this
choice to the user at call time.
"""
from mcp.server.fastmcp import FastMCP

import pushkey_connect as _pc
import pushkey_connect_migrate as _pcm
import pushkey_projectfs as _pfs
import pushkey_shared as _s
import pushkey_vault as _vault
from pushkey_connect import ConnectError
from pushkey_health import HealthSidecarError
from dataclasses import asdict
from datetime import datetime, timedelta
import os
import re


def _safe_str(s, max_len: int = 500) -> str:
    """Truncate and strip user-controlled strings before returning to AI context."""
    if not s:
        return ""
    return str(s)[:max_len].strip()


def _sanitize_key_value(v: str) -> str:
    """Strip newlines from key values to prevent .env injection."""
    return v.replace("\r", "").replace("\n", "")


_KEY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,255}$")


def _valid_key_name(name: str) -> bool:
    return bool(_KEY_NAME_RE.fullmatch(name or ""))


def _key_allows_project(meta: dict, project: str) -> bool:
    return project in (meta.get("projects") or [])

mcp = FastMCP("pushkey")

# Not thread-safe — designed for single-user stdio transport.
# SSE mode with concurrent requests can race on _SESSION mutations.
SESSION_TIMEOUT_SECONDS = 30 * 60
_SESSION: dict = {}  # keys: vault, vault_key, password, scopes, last_activity


def _get_raw_vault_key() -> bytes:
    """Return the raw AES vault key for token wrapping. Derives from password for V2 vaults."""
    if _SESSION.get("vault_key"):
        return _SESSION["vault_key"]
    from pushkey_crypto import derive_key, get_or_create_salt
    return derive_key(_SESSION["password"], get_or_create_salt())


def _unlock_with_password(password: str) -> dict:
    vault, vault_key = _vault.load_vault(password)
    if vault is None:
        return {"success": False, "error": "invalid password or corrupted vault"}
    _SESSION["vault"] = vault
    _SESSION["vault_key"] = vault_key
    _SESSION["password"] = password
    _SESSION["scopes"] = ["read", "write", "inject"]  # full access
    _SESSION["last_activity"] = datetime.now()
    _migrate_project_store()
    return {"success": True, "key_count": len(_SESSION["vault"]), "auth": "master_password"}


def _migrate_project_store() -> None:
    """Run the one-time project store migration; the unlock never fails because of it.

    Only a master-password unlock gets here (a token session never writes at unlock), and
    only when a vault file exists. A damaged or busy config, a busy vault or a failed save
    leave the store as it was: the next password unlock tries again and the project tools
    answer ``migration_pending`` or a config error meanwhile. The log line names the error
    type and, for the core's own errors, its code; never a message that could hold a value.
    """
    if not _s.VAULT_FILE.exists():
        return
    try:
        _pcm.ensure_migrated(
            vault_key=_SESSION["vault_key"], password=_SESSION["password"], target=_SESSION["vault"]
        )
    except Exception as error:
        from pushkey_crypto import log_event
        code = f": {error}" if isinstance(error, (ConnectError, _vault.ConfigUnreadableError)) else ""
        log_event(f"[mcp] project store migration skipped ({type(error).__name__}{code})")


def _unlock_with_token(token_value: str) -> dict:
    import pushkey_agent_tokens as _at
    vault_key, scopes, err = _at.authenticate_token(token_value)
    if vault_key is None:
        return {"success": False, "error": err or "token authentication failed"}
    vault, vk = _vault.load_vault_with_key(vault_key)
    if vault is None:
        return {"success": False, "error": "vault decryption failed with agent token — token may be stale after a master password change"}
    _SESSION["vault"] = vault
    _SESSION["vault_key"] = vk
    _SESSION["password"] = None  # agent tokens cannot save vault (read-only path by default)
    _SESSION["scopes"] = scopes
    _SESSION["last_activity"] = datetime.now()
    return {"success": True, "key_count": len(vault), "auth": "agent_token", "scopes": scopes}


def _lock():
    _SESSION.clear()


def _save_session_vault(vault) -> None:
    if _SESSION.get("password") is not None:
        _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    else:
        _vault.save_vault_with_key(vault, _SESSION["vault_key"])
    try:
        from pushkey_health import publish_saved_vault
        publish_saved_vault(vault)
        return None
    except (HealthSidecarError, _vault.VaultBusyError):
        return "health_publication_failed"


# Backward-compat alias for tests written before the password/token split.
def _unlock(password: str) -> dict:
    if password.startswith("pk_agent_"):
        return _unlock_with_token(password)
    return _unlock_with_password(password)


def _require_unlock() -> dict | None:
    if "vault" not in _SESSION:
        return {"error": "vault_locked", "hint": "Call unlock_vault first with master password or agent token"}
    last_activity = _SESSION.get("last_activity")
    if last_activity is None:
        _lock()
        return {"error": "session_expired", "hint": "Call unlock_vault again"}
    if datetime.now() - last_activity > timedelta(seconds=SESSION_TIMEOUT_SECONDS):
        _lock()
        return {"error": "session_expired", "hint": "Call unlock_vault again"}
    _SESSION["last_activity"] = datetime.now()
    return None


def _require_scope(scope: str) -> dict | None:
    err = _require_unlock()
    if err:
        return err
    if scope not in _SESSION.get("scopes", []):
        return {
            "error": "scope_denied",
            "required_scope": scope,
            "token_scopes": _SESSION.get("scopes", []),
            "hint": f"This agent token does not have '{scope}' scope. Create a token with the required scope.",
        }
    return None


# ── connect core helpers ─────────────────────────────────────────────────────

_CORE_ERRORS = (ConnectError, _vault.ConfigUnreadableError, _pfs.ProjectPathError)

_ERROR_HINTS = {
    "project_not_registered": "A person must add this folder as a project in Pushkey first.",
    "migration_pending": "Open Pushkey with your master password once to finish migrating projects.",
    "file_tracked_by_git": "this file is committed to git; Pushkey will not write secrets into it",
    "confirmation_required": (
        "Ask the person to approve these, then call connect_key again with confirm set to them."
    ),
}


def _error_reply(error: Exception) -> dict:
    """``{"success": False, "error": <code>, "hint": ...}`` for an error the connect core raises.

    Only the stable code (and, for ``confirmation_required``, the confirmations still
    missing) is passed on: the error's names and paths are not echoed, and no key value
    ever is.
    """
    if isinstance(error, ConnectError):
        code = error.code
    elif isinstance(error, _vault.ConfigUnreadableError):
        reason = str(error)
        code = reason if reason in ("config_unreadable", "config_busy") else "config_unreadable"
    else:
        code = error.reason
    reply = {"success": False, "error": code}
    if code in _ERROR_HINTS:
        reply["hint"] = _ERROR_HINTS[code]
    if code == "confirmation_required":
        reply["needs"] = list(error.detail.get("needs", []))
    return reply


def _core_credentials() -> dict:
    """The credentials the connect core is given for this session.

    A token session holds no password (``None``), so the core saves with the vault key
    only. ``target`` is the session's vault, kept current by the core after every save.
    """
    return {
        "vault_key": _SESSION["vault_key"],
        "password": _SESSION.get("password"),
        "target": _SESSION["vault"],
    }


def _core_actor() -> str:
    """The name audit lines carry for this session."""
    return "mcp" if _SESSION.get("password") is not None else "mcp agent-token"


def _may_inject() -> bool:
    return "inject" in _SESSION.get("scopes", [])


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _connection_rows(entry) -> list[dict]:
    """``{project, file, var}`` of each well-formed connection of a vault entry."""
    connections = entry.get("connections") if isinstance(entry, dict) else None
    rows = []
    for conn in connections if isinstance(connections, list) else []:
        if isinstance(conn, dict) and all(isinstance(conn.get(part), str) for part in ("project", "file", "var")):
            rows.append({"project": conn["project"], "file": conn["file"], "var": conn["var"]})
    return rows


def _registered_project(project_path: str) -> str:
    """The registered key of the project folder ``project_path`` names.

    Raises ConnectError ``migration_pending`` for a store that is not migrated yet and
    ``project_not_registered`` for a folder a person has not added as a project.
    """
    config = _vault.load_config(strict=True)
    if not _pc.is_migrated(config):
        raise ConnectError("migration_pending")
    canonical = _pfs.canonical_project_path(project_path, must_exist=False)
    for key in _pc.registered_projects(config):
        if _path_key(key) == _path_key(canonical):
            return key
    raise ConnectError("project_not_registered", {"project": canonical})


def _replace_value_of(fresh: dict, name: str, new_value: str) -> dict:
    """Rotate-style replacement on a freshly loaded vault (the commit's mutate step)."""
    entry = fresh.get(name)
    if not isinstance(entry, dict):
        raise ConnectError("key_not_found", {"key": name})
    _pc.replace_value(entry, new_value)
    return entry


def _after_value_change(name: str) -> tuple[dict, list]:
    """Bring a key's connected files up to date after its value changed.

    Returns ``(reply fields, warnings)``. A session with the inject scope syncs and reports
    ``synced``; any other session lists the connections it could not write in
    ``not_synced``. The value is already saved when this runs, so a sync that cannot start
    (an unreadable config, a store not yet migrated) is a code-only ``sync_error`` and never
    turns the successful change into an error (a retry would change the key twice).
    """
    if not _may_inject():
        return {"not_synced": _connection_rows(_SESSION["vault"].get(name))}, []
    try:
        results = _pc.sync(key_name=name, actor=_core_actor(), **_core_credentials())
    except Exception as error:
        # A code only: the class name of anything unexpected, never its message.
        code = (
            error.code if isinstance(error, ConnectError)
            else str(error) if isinstance(error, _vault.ConfigUnreadableError)
            else type(error).__name__
        )
        return {"synced": [], "sync_error": code}, []
    warnings = [w for result in results for w in (result.health_warning, result.warning)]
    return {"synced": [asdict(result) for result in results]}, warnings


def _first(*warnings):
    """The first warning that is set, or None."""
    return next((w for w in warnings if w), None)


def _add_key_warning(name: str) -> str:
    return (
        "Key value entered the MCP client context and may be retained by the client, "
        "model provider, transcript, or telemetry. "
        "OK for dev/test keys. For production keys, add via local CLI: "
        f"`pushkey add {name}` (hidden prompt, no LLM exposure)."
    )


_ROTATE_KEY_WARNING = (
    "New key value entered the MCP client context and may be retained by the "
    "client, model provider, transcript, or telemetry. "
    "OK for dev/test keys. For production keys, prefer `pushkey rotate` (CLI, getpass) "
    "or pre-stage a backup and use rotate_to_backup() so secrets never cross chat."
)


@mcp.tool()
def unlock_vault(password: str) -> dict:
    """
    Unlock the Pushkey vault. Accepts either:
      - Master password  : "my-master-password"
      - Agent token (Pro+): "pk_agent_..."

    Must be called before any other vault tool. Session is cleared by lock_vault or process exit.
    """
    if password.startswith("pk_agent_"):
        return _unlock_with_token(password)
    return _unlock_with_password(password)


@mcp.tool()
def lock_vault() -> dict:
    """Lock the vault and clear the in-memory session."""
    _lock()
    return {"success": True}


@mcp.tool()
def list_keys(env: str = None, provider: str = None, project: str = None) -> dict:
    """List all keys in the vault (metadata only, no values). Optional filters: env, provider, project."""
    err = _require_scope("read")
    if err:
        return err
    vault = _SESSION["vault"]
    keys = []
    for name, meta in vault.items():
        if name.startswith("_") or not isinstance(meta, dict):
            continue  # vault metadata, never a key
        if env and meta.get("env") != env:
            continue
        if provider and meta.get("provider", "").lower() != provider.lower():
            continue
        if project and project not in meta.get("projects", []):
            continue
        keys.append({
            "name": name,
            "provider": _safe_str(meta.get("provider", "Unknown")),
            "env": meta.get("env", "all"),
            "projects": meta.get("projects", []),
            "created": meta.get("created", ""),
            "rotated": meta.get("rotated", ""),
            "notes": _safe_str(meta.get("notes", "")),
        })
    return {"count": len(keys), "keys": keys}


@mcp.tool()
def get_key(name: str) -> dict:
    """Return a key's plaintext value and metadata.

    The returned value enters the MCP client context and may be retained by the
    client, model provider, chat transcript, or telemetry. Use only when that
    exposure is acceptable; prefer inject_env for local file injection.
    """
    err = _require_scope("read")
    if err:
        return err
    if not _valid_key_name(name):
        return {"error": "invalid key name"}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"error": f"key '{name}' not found"}
    meta = vault[name]
    return {
        "name": name,
        "value": meta["value"],
        "provider": _safe_str(meta.get("provider", "Unknown")),
        "env": meta.get("env", "all"),
        "notes": _safe_str(meta.get("notes", "")),
        "warning": (
            "Returned value entered the MCP client context and may be retained "
            "by the client, model provider, transcript, or telemetry. Prefer "
            "inject_env for local file injection when plaintext display is not required."
        ),
    }


@mcp.tool()
def add_key(
    name: str,
    value: str,
    provider: str = None,
    env: str = "dev",
    notes: str = "",
    overwrite: bool = False,
) -> dict:
    """Add a new key to the vault. Fails if key already exists unless overwrite=True. Requires 'write' scope.

    With overwrite=True the existing key keeps its provider, env, notes and connections
    (those arguments are ignored): only its value is replaced, as a rotation does, and
    every file the key is connected to is brought up to date when the session has the
    'inject' scope (otherwise the reply lists them under `not_synced`).

    ⚠️  PLAINTEXT-OVER-CHAT WARNING
    The `value` argument enters the MCP client context and may be transmitted
    to a model provider or retained in client transcripts or telemetry.
    Acceptable for short-lived dev/test keys.
    For long-lived production keys, prefer the local CLI:  pushkey add <NAME>
    (uses getpass — secret never leaves the machine). Returned response will
    include a reminder field so the agent can relay this to the user.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    import pushkey_providers as _prov
    vault = _SESSION["vault"]
    if name in vault and not overwrite:
        return {"success": False, "error": f"key '{name}' already exists; pass overwrite=True to replace"}
    if name in vault:
        try:
            saved = _pc.commit(
                lambda fresh: _replace_value_of(fresh, name, _sanitize_key_value(value)),
                **_core_credentials(),
            )
        except _CORE_ERRORS as error:
            return _error_reply(error)
        follow_up, warnings = _after_value_change(name)
        result = {
            "success": True,
            "name": name,
            "provider": saved.value.get("provider", "Unknown"),
            "warning": _add_key_warning(name),
            **follow_up,
        }
        health_warning = _first(saved.health_warning, *warnings)
        if health_warning:
            result["health_warning"] = health_warning
        return result
    if not provider:
        provider = _prov.detect_provider(name, value) or "Unknown"
    now = datetime.now().strftime("%Y-%m-%d")
    vault[name] = {
        "value": _sanitize_key_value(value),
        "created": now,
        "rotated": now,
        "provider": provider,
        "env": env,
        "projects": [],
        "notes": notes,
    }
    health_warning = _save_session_vault(vault)
    result = {
        "success": True,
        "name": name,
        "provider": provider,
        "warning": _add_key_warning(name),
    }
    if health_warning:
        result["health_warning"] = health_warning
    return result


@mcp.tool()
def inject_env(project_path: str, keys: list[str] = None) -> dict:
    """
    Write the keys connected to a registered project into their env file (a variable's
    value is replaced) and make sure the file is in the project's .gitignore.
    If keys is None, writes every key connected to the project; explicit keys must be
    connected to it (see connect_key / assign_key), otherwise the call is refused.
    A folder that a person has not added as a project in Pushkey is refused with
    `project_not_registered`. Requires 'inject' scope. No reply carries a key value.
    """
    err = _require_scope("inject")
    if err:
        return err
    vault = _SESSION["vault"]
    try:
        project = _registered_project(project_path)
    except _CORE_ERRORS as error:
        return _error_reply(error)

    connected: dict[str, list[dict]] = {}
    for name, entry in vault.items():
        rows = [r for r in _connection_rows(entry) if _path_key(r["project"]) == _path_key(project)]
        if rows and not name.startswith("_"):
            connected[name] = rows
    if keys is None:
        keys = list(connected)
        if not keys:
            return {"success": False, "error": "no keys connected to this project; connect keys first or pass keys=[...]"}
    invalid = [k for k in keys if not _valid_key_name(k)]
    if invalid:
        return {"success": False, "error": f"invalid key names: {invalid}"}
    missing = [k for k in keys if not isinstance(vault.get(k), dict)]
    if missing:
        return {"success": False, "error": f"keys not in vault: {missing}"}
    unconnected = [k for k in keys if k not in connected]
    if unconnected:
        return {
            "success": False,
            "error": f"keys not connected: {unconnected}",
            "hint": "Connect the keys to this project with connect_key before calling inject_env.",
        }
    names = list(dict.fromkeys(keys))
    try:
        # One call for every named key: one write and one backup per file.
        results = _pc.sync(key_names=names, project=project, actor=_core_actor(), **_core_credentials())
    except _CORE_ERRORS as error:
        return _error_reply(error)
    injected = list(dict.fromkeys(r.key for r in results if r.written and r.change != "none"))
    reply = {
        "success": all(r.written for r in results),
        "injected_count": len(injected),
        "injected_names": injected,
        # A connected variable's value is always replaced; nothing is "kept" any more.
        "skipped_count": 0,
        "skipped_existing": [],
        "results": [asdict(r) for r in results],
    }
    if not reply["success"]:
        reply["error"] = "write_failed"
        reply["hint"] = "See each result's reason."
    health_warning = _first(*(w for r in results for w in (r.health_warning, r.warning)))
    if health_warning:
        reply["health_warning"] = health_warning
    return reply


@mcp.tool()
def check_health(rotation_threshold_days: int = 90) -> dict:
    """Report vault health: total keys, stale keys (not rotated within threshold), keys missing provider."""
    err = _require_scope("read")
    if err:
        return err
    vault = _SESSION["vault"]
    now = datetime.now()
    stale, healthy, unknown_provider, backup_missing = [], [], [], []
    for name, meta in vault.items():
        rotated_str = meta.get("rotated") or meta.get("created", "")
        try:
            rotated = datetime.fromisoformat(rotated_str)
            age_days = (now - rotated).days
        except (ValueError, TypeError):
            age_days = 9999
        entry = {"name": name, "provider": meta.get("provider", "Unknown"),
                 "env": meta.get("env", "all"), "age_days": age_days}
        if age_days >= rotation_threshold_days:
            stale.append(entry)
        else:
            healthy.append(entry)
        if meta.get("provider", "Unknown") in ("Unknown", "", None):
            unknown_provider.append(name)
        if meta.get("dual_rotation") and not meta.get("next_value"):
            backup_missing.append(name)
    return {
        "total": len(vault),
        "stale_count": len(stale),
        "healthy_count": len(healthy),
        "stale_keys": stale,
        "unknown_provider_keys": unknown_provider,
        "backup_missing": backup_missing,
        "rotation_threshold_days": rotation_threshold_days,
    }


@mcp.tool()
def rotate_key(name: str, new_value: str) -> dict:
    """Replace a key's value and update its rotated timestamp. Requires 'write' scope.

    Every file the key is connected to is brought up to date when the session has the
    'inject' scope (the reply's `synced` lists them); otherwise the reply lists them under
    `not_synced`. A sync that fails after the value is saved is a code-only `sync_error`.

    ⚠️  PLAINTEXT-OVER-CHAT WARNING
    `new_value` enters the MCP client context and may be transmitted to a model
    provider or retained in client transcripts or telemetry. Use this path only
    for short-lived dev/test keys
    where speed matters more than secrecy.

    For long-lived production keys, prefer one of:
      • Local CLI:        pushkey rotate <NAME>     (getpass prompt, never sees LLM)
      • Dual-rotation:    rotate_to_backup(<NAME>)  (only the name crosses the wire,
                          backup pre-staged via CLI `pushkey set-backup`)

    Returned response includes a `warning` field for the agent to relay.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    try:
        saved = _pc.commit(
            lambda fresh: _replace_value_of(fresh, name, _sanitize_key_value(new_value)),
            **_core_credentials(),
        )
    except _CORE_ERRORS as error:
        return _error_reply(error)
    follow_up, warnings = _after_value_change(name)
    result = {
        "success": True,
        "name": name,
        "rotated": saved.value["rotated"],
        "warning": _ROTATE_KEY_WARNING,
        **follow_up,
    }
    health_warning = _first(saved.health_warning, *warnings)
    if health_warning:
        result["health_warning"] = health_warning
    return result


@mcp.tool()
def set_backup_key(name: str, backup_value: str) -> dict:
    """
    Store a pre-generated backup key for dual-key rotation (Pro+).

    When rotation is due, call rotate_to_backup() to promote the backup to active.
    The old active key is discarded; the backup slot is then empty — you will be
    prompted to add a new backup key to keep the rotation cycle going.

    Requires 'write' scope and a master password session.

    ⚠️  PLAINTEXT-OVER-CHAT WARNING
    `backup_value` enters the MCP client context and may be transmitted to a
    model provider or retained in client transcripts or telemetry. For
    long-lived production keys, seed the backup via the local
    CLI instead (no LLM exposure), then use rotate_to_backup() — which only
    sends the key NAME over the wire, never the secret.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    from pushkey_tiers import can_do
    if not can_do("dual_rotation"):
        return {"success": False, "error": "Dual-key rotation requires Pro or higher. Upgrade at pushkey.dev/pricing."}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}

    import pushkey_providers as _prov
    provider_name = vault[name].get("provider", "")
    multi_key_supported = _prov.provider_supports_multi_key(provider_name)
    warning = None if multi_key_supported else (
        f"Provider '{provider_name}' may only support one active key at a time. "
        "Dual rotation works best with providers that allow multiple simultaneous keys "
        "(OpenAI, Anthropic, AWS, Stripe, GitHub, etc.)."
    )

    was_enabled = vault[name].get("dual_rotation", False)
    vault[name]["next_value"] = _sanitize_key_value(backup_value)
    vault[name]["next_added"] = datetime.now().strftime("%Y-%m-%d")
    vault[name]["dual_rotation"] = True
    _save_session_vault(vault)
    try:
        from pushkey_crypto import log_event
        log_event(f"[mcp] backup key {'added' if was_enabled else 'enabled'}: {name}")
    except Exception:
        pass
    result = {"success": True, "name": name, "backup_added": vault[name]["next_added"], "status": "backup_ready"}
    plaintext_warning = (
        "Backup value entered the MCP client context and may be retained by the client, "
        "model provider, transcript, or telemetry. "
        "OK for dev/test keys. For production, seed backups via local CLI to keep "
        "secrets off the wire, then use rotate_to_backup() (name-only) for promotion."
    )
    if warning:
        result["warning"] = f"{warning}  {plaintext_warning}"
    else:
        result["warning"] = plaintext_warning
    return result


@mcp.tool()
def rotate_to_backup(name: str) -> dict:
    """
    Atomically promote the backup key to active (dual-key rotation, Pro+).

    - Active key is discarded (revoke it at the provider after this call).
    - Backup key becomes the new active value.
    - Backup slot is cleared — add a new backup key to maintain the rotation cycle.
    - Every file the key is connected to is brought up to date when the session has the
      'inject' scope (`synced`); otherwise the reply lists them under `not_synced`.

    Requires 'write' scope and a master password session.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    meta = vault[name]
    if not meta.get("dual_rotation"):
        return {"success": False, "error": f"'{name}' does not have dual rotation enabled — call set_backup_key first"}
    if not meta.get("next_value"):
        return {"success": False, "error": f"'{name}' has no backup key stored — call set_backup_key first"}

    def promote(fresh: dict) -> dict:
        entry = fresh.get(name)
        if not isinstance(entry, dict):
            raise ConnectError("key_not_found", {"key": name})
        if not entry.get("next_value"):
            raise ConnectError("no_backup_staged", {"key": name})
        _pc.replace_value(entry, entry["next_value"])
        entry["next_value"] = None
        entry["next_added"] = None
        return entry

    try:
        saved = _pc.commit(promote, **_core_credentials())
    except _CORE_ERRORS as error:
        return _error_reply(error)
    try:
        from pushkey_crypto import log_event
        log_event(f"[mcp] backup promoted to active: {name}")
    except Exception:
        pass
    follow_up, warnings = _after_value_change(name)
    result = {
        "success": True,
        "name": name,
        "rotated": saved.value["rotated"],
        "backup_slot": "empty",
        "action_needed": f"Revoke the old key at your provider, then call set_backup_key('{name}', <new_backup>) to restore the rotation cycle.",
        **follow_up,
    }
    health_warning = _first(saved.health_warning, *warnings)
    if health_warning:
        result["health_warning"] = health_warning
    return result


@mcp.tool()
def list_projects() -> dict:
    """List all projects that have keys assigned, with key counts and key names."""
    err = _require_scope("read")
    if err:
        return err
    vault = _SESSION["vault"]
    projects: dict[str, dict] = {}
    for name, meta in vault.items():
        if name.startswith("_") or not isinstance(meta, dict):
            continue
        for proj in meta.get("projects", []):
            if proj not in projects:
                projects[proj] = {"key_count": 0, "keys": []}
            projects[proj]["key_count"] += 1
            projects[proj]["keys"].append(name)
    return {"projects": projects, "total": len(projects)}


@mcp.tool()
def assign_key(key_name: str, project_path: str) -> dict:
    """Connect a vault key to a registered project without writing its env file (use
    inject_env or connect_key to write it). Requires 'write' scope.

    The folder must be a project a person has added in Pushkey; otherwise the call is
    refused with `project_not_registered`. The key is connected to the project's default
    file as a variable of its own name. If the connection needs a person's approval
    (a variable another key holds, a browser-bundled name, a key of another environment)
    the call is refused with `confirmation_required`: use connect_key with `confirm`.
    No reply carries a key value.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _valid_key_name(key_name):
        return {"success": False, "error": "invalid key name"}
    vault = _SESSION["vault"]
    if key_name not in vault:
        return {"success": False, "error": f"key '{key_name}' not found"}
    try:
        result = _pc.connect(
            key_name=key_name, project=project_path, write=False,
            actor=_core_actor(), **_core_credentials(),
        )
    except _CORE_ERRORS as error:
        return _error_reply(error)
    reply = {"success": True, "key": key_name, "project": project_path, "connection": asdict(result)}
    health_warning = _first(result.health_warning, result.warning)
    if health_warning:
        reply["health_warning"] = health_warning
    return reply


@mcp.tool()
def preview_connection(name: str, project_path: str, file: str = None, var: str = None) -> dict:
    """Say what connecting a vault key to a project would do, without changing anything.
    Requires 'read' scope. Returns `preview` with the exact line to show a person
    (`Save to <project> -> <environment> -> <file> as <var>`), whether the file would be
    added to, replaced or left alone, whether .gitignore would change, and the
    confirmations connect_key would need (`needs_confirm`).

    `file` defaults to the project's default env file and `var` to the key name. Nothing
    returns a key value, and no value can be passed in.
    """
    err = _require_scope("read")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    vault = _SESSION["vault"]
    try:
        if not isinstance(vault.get(name), dict):
            raise ConnectError("key_not_found", {"key": name})
        config = _vault.load_config(strict=True)
        if not _pc.is_migrated(config):
            raise ConnectError("migration_pending")
        shown = _pc.preview(vault, config, key_name=name, project=project_path, file=file, var=var)
    except _CORE_ERRORS as error:
        return _error_reply(error)
    return {"success": True, "preview": asdict(shown)}


@mcp.tool()
def connect_key(
    name: str,
    project_path: str,
    file: str = None,
    var: str = None,
    confirm: list[str] = None,
) -> dict:
    """Connect an existing vault key to a variable in a registered project's env file and
    write it there. Requires BOTH 'write' and 'inject' scopes.

    The secret is never passed in: only the key's NAME, so nothing here crosses the chat
    (add the key first with add_key, or better with the local CLI `pushkey add`). Nothing
    in the reply is a key value. The folder must be a project a person has added in
    Pushkey (`project_not_registered` otherwise; this tool never registers projects).
    `file` defaults to the project's default env file and `var` to the key name. When the
    connection needs a person's approval the call is refused with `confirmation_required`
    and `needs`; once they approve, call again with `confirm` set to those codes
    (use preview_connection first to see them). A write that fails after the connection
    is saved is reported in `connection.written` / `connection.reason`, not as an error.
    """
    err = _require_scope("write")
    if err:
        return err
    err = _require_scope("inject")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    try:
        result = _pc.connect(
            key_name=name, project=project_path, file=file, var=var,
            confirmed=confirm or (), write=True, actor=_core_actor(), **_core_credentials(),
        )
    except _CORE_ERRORS as error:
        return _error_reply(error)
    reply = {"success": True, "key": name, "project": result.project, "connection": asdict(result)}
    health_warning = _first(result.health_warning, result.warning)
    if health_warning:
        reply["health_warning"] = health_warning
    return reply


@mcp.tool()
def key_usage(name: str) -> dict:
    """Where a vault key is connected and whether each file is up to date.
    Requires 'read' scope. Returns `connections`: project, file, variable and a state
    (up_to_date, out_of_date, not_in_file, file_missing, folder_missing, not_ignored or
    not_written, with a reason). Nothing returns a key value."""
    err = _require_scope("read")
    if err:
        return err
    if not _valid_key_name(name):
        return {"success": False, "error": "invalid key name"}
    vault = _SESSION["vault"]
    try:
        if not isinstance(vault.get(name), dict):
            raise ConnectError("key_not_found", {"key": name})
        statuses = _pc.status(vault, _vault.load_config(strict=True), key_name=name)
    except _CORE_ERRORS as error:
        return _error_reply(error)
    return {"success": True, "name": name, "connections": [asdict(state) for state in statuses]}


# ── Agent token management (requires master password session) ─────────────────

@mcp.tool()
def create_agent_token(name: str, scopes: list[str]) -> dict:
    """
    Create a scoped agent token for CI/CD pipelines or autonomous agents (Pro+ only).

    scopes: list of "read", "write", "inject" (any combination).
      read   — list_keys, get_key, check_health, list_projects, preview_connection, key_usage
      write  — add_key, rotate_key, assign_key (connect_key needs write AND inject)
      inject — inject_env (and the file sync after rotate_key / add_key / rotate_to_backup)

    The token value is returned once and never stored in plaintext.
    Requires master password session (cannot create tokens from another token).
    """
    err = _require_unlock()
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "creating agent tokens requires master password auth, not an agent token"}

    import pushkey_agent_tokens as _at
    ok, result, token_id = _at.create_token(name, scopes, _get_raw_vault_key())
    if not ok:
        return {"success": False, "error": result}
    return {
        "success": True,
        "token_id": token_id,
        "token_value": result,
        "name": name,
        "scopes": scopes,
        "warning": "Store this token securely — it will not be shown again.",
    }


@mcp.tool()
def list_agent_tokens() -> dict:
    """List all agent tokens (metadata only — no token values)."""
    err = _require_unlock()
    if err:
        return err
    import pushkey_agent_tokens as _at
    tokens = _at.list_tokens()
    return {"count": len(tokens), "tokens": tokens}


@mcp.tool()
def revoke_agent_token(token_id: str) -> dict:
    """Revoke an agent token by its ID (from list_agent_tokens). Requires master password session."""
    err = _require_unlock()
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "revoking tokens requires master password auth"}
    import pushkey_agent_tokens as _at
    ok = _at.revoke_token(token_id)
    if not ok:
        return {"success": False, "error": f"token '{token_id}' not found"}
    return {"success": True, "revoked": token_id}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None, help="SSE port (omit for stdio)")
    args = parser.parse_args()
    if args.port:
        mcp.run(transport="sse", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")

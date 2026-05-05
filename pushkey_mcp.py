"""
Pushkey MCP Server — exposes vault operations as MCP tools for Claude Code / VS Code.

Usage:
    python pushkey_mcp.py           # stdio transport (Claude Code)
    python pushkey_mcp.py --port 8765  # SSE transport (VS Code Copilot)

Authentication
    Master password : unlock_vault("my-master-password")
    Agent token     : unlock_vault("pk_agent_...")   # Pro+ only
"""
from mcp.server.fastmcp import FastMCP

import pushkey_vault as _vault
from datetime import datetime
from pathlib import Path


def _safe_str(s, max_len: int = 500) -> str:
    """Truncate and strip user-controlled strings before returning to AI context."""
    if not s:
        return ""
    return str(s)[:max_len].strip()


def _sanitize_key_value(v: str) -> str:
    """Strip newlines from key values to prevent .env injection."""
    return v.replace("\r", "").replace("\n", "")

mcp = FastMCP("pushkey")

# Not thread-safe — designed for single-user stdio transport.
# SSE mode with concurrent requests can race on _SESSION mutations.
_SESSION: dict = {}  # keys: vault, vault_key, password, scopes


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
    return {"success": True, "key_count": len(vault), "auth": "master_password"}


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
    return {"success": True, "key_count": len(vault), "auth": "agent_token", "scopes": scopes}


def _lock():
    _SESSION.clear()


def _require_unlock() -> dict | None:
    if "vault" not in _SESSION:
        return {"error": "vault_locked", "hint": "Call unlock_vault first with master password or agent token"}
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
    """Get the value and metadata of a specific key from the vault by name."""
    err = _require_scope("read")
    if err:
        return err
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
    """Add a new key to the vault. Fails if key already exists unless overwrite=True. Requires 'write' scope."""
    err = _require_scope("write")
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "write operations require master password auth (agent tokens with write scope need password stored in session — re-unlock with master password)"}
    import pushkey_providers as _prov
    vault = _SESSION["vault"]
    if name in vault and not overwrite:
        return {"success": False, "error": f"key '{name}' already exists; pass overwrite=True to replace"}
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
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "name": name, "provider": provider}


@mcp.tool()
def inject_env(project_path: str, keys: list[str] = None) -> dict:
    """
    Write vault keys into <project_path>/.env and ensure .env is in .gitignore.
    If keys is None, injects all keys whose projects list includes project_path.
    Requires 'inject' scope.
    """
    err = _require_scope("inject")
    if err:
        return err
    vault = _SESSION["vault"]
    project = Path(project_path).resolve()
    if not project.is_dir():
        return {"success": False, "error": f"directory not found: {project_path}"}
    resolved_project = str(project)

    if keys is None:
        keys = [n for n, m in vault.items() if resolved_project in m.get("projects", [])]
        if not keys:
            return {"success": False, "error": "no keys assigned to this project; pass keys=[...] explicitly"}

    missing = [k for k in keys if k not in vault]
    if missing:
        return {"success": False, "error": f"keys not in vault: {missing}"}

    env_path = project / ".env"
    existing_lines = []
    existing_keys = set()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            existing_lines.append(line)
            if "=" in line and not line.startswith("#"):
                existing_keys.add(line.split("=", 1)[0].strip())

    new_lines = [f"{k}={_sanitize_key_value(vault[k]['value'])}" for k in keys if k not in existing_keys]
    all_lines = existing_lines + new_lines
    env_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")

    gitignore_path = project / ".gitignore"
    gitignore_content = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    if ".env" not in gitignore_content.splitlines():
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n.env\n")

    return {"success": True, "injected": new_lines, "skipped_existing": list(existing_keys & set(keys))}


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
    """Replace a key's value and update its rotated timestamp. Requires 'write' scope."""
    err = _require_scope("write")
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "write operations require master password auth"}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    vault[name]["value"] = _sanitize_key_value(new_value)
    vault[name]["rotated"] = datetime.now().strftime("%Y-%m-%d")
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "name": name, "rotated": vault[name]["rotated"]}


@mcp.tool()
def set_backup_key(name: str, backup_value: str) -> dict:
    """
    Store a pre-generated backup key for dual-key rotation (Pro+).

    When rotation is due, call rotate_to_backup() to promote the backup to active.
    The old active key is discarded; the backup slot is then empty — you will be
    prompted to add a new backup key to keep the rotation cycle going.

    Requires 'write' scope and a master password session.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "write operations require master password auth"}
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
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    try:
        from pushkey_crypto import log_event
        log_event(f"[mcp] backup key {'added' if was_enabled else 'enabled'}: {name}")
    except Exception:
        pass
    result = {"success": True, "name": name, "backup_added": vault[name]["next_added"], "status": "backup_ready"}
    if warning:
        result["warning"] = warning
    return result


@mcp.tool()
def rotate_to_backup(name: str) -> dict:
    """
    Atomically promote the backup key to active (dual-key rotation, Pro+).

    - Active key is discarded (revoke it at the provider after this call).
    - Backup key becomes the new active value.
    - Backup slot is cleared — add a new backup key to maintain the rotation cycle.

    Requires 'write' scope and a master password session.
    """
    err = _require_scope("write")
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "write operations require master password auth"}
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    meta = vault[name]
    if not meta.get("dual_rotation"):
        return {"success": False, "error": f"'{name}' does not have dual rotation enabled — call set_backup_key first"}
    if not meta.get("next_value"):
        return {"success": False, "error": f"'{name}' has no backup key stored — call set_backup_key first"}

    old_value = meta["value"]
    meta["value"] = meta["next_value"]
    meta["rotated"] = datetime.now().strftime("%Y-%m-%d")
    meta["next_value"] = None
    meta["next_added"] = None
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    try:
        from pushkey_crypto import log_event
        log_event(f"[mcp] backup promoted to active: {name}")
    except Exception:
        pass
    return {
        "success": True,
        "name": name,
        "rotated": meta["rotated"],
        "backup_slot": "empty",
        "action_needed": f"Revoke the old key at your provider, then call set_backup_key('{name}', <new_backup>) to restore the rotation cycle.",
        "old_value_hint": old_value[:8] + "…" if len(old_value) > 8 else "…",
    }


@mcp.tool()
def list_projects() -> dict:
    """List all projects that have keys assigned, with key counts and key names."""
    err = _require_scope("read")
    if err:
        return err
    vault = _SESSION["vault"]
    projects: dict[str, dict] = {}
    for name, meta in vault.items():
        for proj in meta.get("projects", []):
            if proj not in projects:
                projects[proj] = {"key_count": 0, "keys": []}
            projects[proj]["key_count"] += 1
            projects[proj]["keys"].append(name)
    return {"projects": projects, "total": len(projects)}


@mcp.tool()
def assign_key(key_name: str, project_path: str) -> dict:
    """Assign a vault key to a project path (adds to key's projects list). Requires 'write' scope."""
    err = _require_scope("write")
    if err:
        return err
    if not _SESSION.get("password"):
        return {"success": False, "error": "write operations require master password auth"}
    vault = _SESSION["vault"]
    if key_name not in vault:
        return {"success": False, "error": f"key '{key_name}' not found"}
    resolved = str(Path(project_path).resolve())
    projects = vault[key_name].setdefault("projects", [])
    if resolved not in projects:
        projects.append(resolved)
        _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "key": key_name, "project": project_path}


# ── Agent token management (requires master password session) ─────────────────

@mcp.tool()
def create_agent_token(name: str, scopes: list[str]) -> dict:
    """
    Create a scoped agent token for CI/CD pipelines or autonomous agents (Pro+ only).

    scopes: list of "read", "write", "inject" (any combination).
      read   — list_keys, get_key, check_health, list_projects
      write  — add_key, rotate_key, assign_key
      inject — inject_env

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

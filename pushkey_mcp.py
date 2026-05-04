"""
Pushkey MCP Server — exposes vault operations as MCP tools for Claude Code / VS Code.

Usage:
    python pushkey_mcp.py           # stdio transport (Claude Code)
    python pushkey_mcp.py --port 8765  # SSE transport (VS Code Copilot)
"""
from mcp.server.fastmcp import FastMCP

import pushkey_vault as _vault

mcp = FastMCP("pushkey")

_SESSION: dict = {}  # keys: vault, vault_key, password


def _unlock(password: str) -> dict:
    vault, vault_key = _vault.load_vault(password)
    if vault is None:
        return {"success": False, "error": "invalid password or corrupted vault"}
    _SESSION["vault"] = vault
    _SESSION["vault_key"] = vault_key
    _SESSION["password"] = password
    return {"success": True, "key_count": len(vault)}


def _lock():
    _SESSION.clear()


def _require_unlock() -> dict | None:
    if "vault" not in _SESSION:
        return {"error": "vault_locked", "hint": "Call unlock_vault first"}
    return None


@mcp.tool()
def unlock_vault(password: str) -> dict:
    """Unlock the Pushkey vault with the master password. Must be called before list_keys, get_key, add_key, inject_env, rotate_key, list_projects, or assign_key. Session is cleared by lock_vault or process exit."""
    return _unlock(password)


@mcp.tool()
def lock_vault() -> dict:
    """Lock the vault and clear the in-memory session."""
    _lock()
    return {"success": True}


@mcp.tool()
def list_keys(env: str = None, provider: str = None, project: str = None) -> dict:
    """List all keys in the vault (metadata only, no values). Optional filters: env, provider, project."""
    err = _require_unlock()
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
            "provider": meta.get("provider", "Unknown"),
            "env": meta.get("env", "all"),
            "projects": meta.get("projects", []),
            "created": meta.get("created", ""),
            "rotated": meta.get("rotated", ""),
            "notes": meta.get("notes", ""),
        })
    return {"count": len(keys), "keys": keys}


@mcp.tool()
def get_key(name: str) -> dict:
    """Get the value and metadata of a specific key from the vault by name."""
    err = _require_unlock()
    if err:
        return err
    vault = _SESSION["vault"]
    if name not in vault:
        return {"error": f"key '{name}' not found"}
    meta = vault[name]
    return {
        "name": name,
        "value": meta["value"],
        "provider": meta.get("provider", "Unknown"),
        "env": meta.get("env", "all"),
        "notes": meta.get("notes", ""),
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
    """Add a new key to the vault. Fails if key already exists unless overwrite=True."""
    err = _require_unlock()
    if err:
        return err
    from datetime import datetime
    import pushkey_providers as _prov
    vault = _SESSION["vault"]
    if name in vault and not overwrite:
        return {"success": False, "error": f"key '{name}' already exists; pass overwrite=True to replace"}
    if not provider:
        provider = _prov.detect_provider(name, value) or "Unknown"
    now = datetime.now().strftime("%Y-%m-%d")
    vault[name] = {
        "value": value,
        "created": now,
        "rotated": now,
        "provider": provider,
        "env": env,
        "projects": [],
        "notes": notes,
    }
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "name": name, "provider": provider}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None, help="SSE port (omit for stdio)")
    args = parser.parse_args()
    if args.port:
        mcp.run(transport="sse", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")

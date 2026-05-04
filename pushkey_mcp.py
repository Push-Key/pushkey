"""
Pushkey MCP Server — exposes vault operations as MCP tools for Claude Code / VS Code.

Usage:
    python pushkey_mcp.py           # stdio transport (Claude Code)
    python pushkey_mcp.py --port 8765  # SSE transport (VS Code Copilot)
"""
from mcp.server.fastmcp import FastMCP

import pushkey_vault as _vault
from datetime import datetime
from pathlib import Path

mcp = FastMCP("pushkey")

# Not thread-safe — designed for single-user stdio transport.
# SSE mode with concurrent requests can race on _SESSION mutations.
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
    import pushkey_providers as _prov  # deferred: triggers network fetch on first import
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


@mcp.tool()
def inject_env(project_path: str, keys: list[str] = None) -> dict:
    """
    Write vault keys into <project_path>/.env and ensure .env is in .gitignore.
    If keys is None, injects all keys whose projects list includes project_path.
    """
    err = _require_unlock()
    if err:
        return err
    vault = _SESSION["vault"]
    project = Path(project_path).resolve()
    if not project.is_dir():
        return {"success": False, "error": f"directory not found: {project_path}"}

    if keys is None:
        keys = [n for n, m in vault.items() if project_path in m.get("projects", [])]
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

    new_lines = [f"{k}={vault[k]['value']}" for k in keys if k not in existing_keys]
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
    err = _require_unlock()
    if err:
        return err
    vault = _SESSION["vault"]
    now = datetime.now()
    stale, healthy, unknown_provider = [], [], []
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
    return {
        "total": len(vault),
        "stale_count": len(stale),
        "healthy_count": len(healthy),
        "stale_keys": stale,
        "unknown_provider_keys": unknown_provider,
        "rotation_threshold_days": rotation_threshold_days,
    }


@mcp.tool()
def rotate_key(name: str, new_value: str) -> dict:
    """Replace a key's value and update its rotated timestamp."""
    err = _require_unlock()
    if err:
        return err
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    vault[name]["value"] = new_value
    vault[name]["rotated"] = datetime.now().strftime("%Y-%m-%d")
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "name": name, "rotated": vault[name]["rotated"]}


@mcp.tool()
def list_projects() -> dict:
    """List all projects that have keys assigned, with key counts and key names."""
    err = _require_unlock()
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
    """Assign a vault key to a project path (adds to key's projects list)."""
    err = _require_unlock()
    if err:
        return err
    vault = _SESSION["vault"]
    if key_name not in vault:
        return {"success": False, "error": f"key '{key_name}' not found"}
    projects = vault[key_name].setdefault("projects", [])
    if project_path not in projects:
        projects.append(project_path)
        _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "key": key_name, "project": project_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None, help="SSE port (omit for stdio)")
    args = parser.parse_args()
    if args.port:
        mcp.run(transport="sse", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")

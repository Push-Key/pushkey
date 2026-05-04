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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None, help="SSE port (omit for stdio)")
    args = parser.parse_args()
    if args.port:
        mcp.run(transport="sse", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")

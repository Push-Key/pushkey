# Pushkey MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server (`pushkey_mcp.py`) that exposes Pushkey's vault operations as tools consumable by Claude Code and VS Code Copilot.

**Architecture:** FastMCP (official `mcp` SDK) wraps `pushkey_vault.py` + `pushkey_crypto.py` directly — no subprocess. Session auth stores the unlocked vault in a module-level `_SESSION` dict cleared on server restart. Nine tools cover the full IDE workflow: unlock, list, get, add, inject_env, health, rotate, list_projects, assign.

**Tech Stack:** Python 3.11+, `mcp[cli]` SDK, existing `pushkey_vault` / `pushkey_crypto` / `pushkey_providers` / `pushkey_shared` modules.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `pushkey_mcp.py` | Create | MCP server — all 9 tools + session state |
| `tests/test_mcp.py` | Create | Integration tests for every tool |
| `requirements.txt` | Modify | Add `mcp[cli]>=1.0.0` |
| `docs/mcp-setup.md` | Create | Claude Code + VS Code config snippets |
| `~/.claude/skills/pushkey/SKILL.md` | Create | Companion skill telling Claude when to call these tools |

---

## Task 1: Add `mcp` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add mcp to requirements.txt**

Append to `requirements.txt`:
```
mcp[cli]>=1.0.0
```

- [ ] **Step 2: Install it**

```bash
pip install "mcp[cli]>=1.0.0"
```

Expected: installs without error. Verify: `python -c "import mcp; print(mcp.__version__)"` prints a version.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat(mcp): add mcp[cli] dependency"
```

---

## Task 2: Server scaffold + unlock/lock tools

**Files:**
- Create: `pushkey_mcp.py`
- Create: `tests/test_mcp.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mcp.py`:
```python
import importlib
import sys
import pytest

# Re-import fresh each test to reset _SESSION
def _fresh_mcp():
    if "pushkey_mcp" in sys.modules:
        del sys.modules["pushkey_mcp"]
    return importlib.import_module("pushkey_mcp")


def test_vault_starts_locked():
    mcp_mod = _fresh_mcp()
    assert mcp_mod._SESSION == {}


def test_unlock_bad_password(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    save_vault({"MY_KEY": {"value": "secret", "created": "2024-01-01", "rotated": "2024-01-01",
                           "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}},
               "correct-password")

    mcp_mod = _fresh_mcp()
    result = mcp_mod._unlock("wrong-password")
    assert result["success"] is False
    assert "invalid" in result["error"].lower()


def test_unlock_correct_password(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    save_vault({"MY_KEY": {"value": "secret", "created": "2024-01-01", "rotated": "2024-01-01",
                           "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}},
               "correct-password")

    mcp_mod = _fresh_mcp()
    result = mcp_mod._unlock("correct-password")
    assert result["success"] is True
    assert result["key_count"] == 1


def test_lock_clears_session(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    save_vault({}, "pw")

    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    assert mcp_mod._SESSION != {}
    mcp_mod._lock()
    assert mcp_mod._SESSION == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mcp.py -v
```
Expected: `ModuleNotFoundError: No module named 'pushkey_mcp'`

- [ ] **Step 3: Create pushkey_mcp.py with scaffold + unlock/lock**

Create `pushkey_mcp.py`:
```python
"""
Pushkey MCP Server — exposes vault operations as MCP tools for Claude Code / VS Code.

Usage:
    python pushkey_mcp.py           # stdio transport (Claude Code)
    python pushkey_mcp.py --port 8765  # SSE transport (VS Code Copilot)
"""
import sys
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
    """Unlock the Pushkey vault with master password. Required before most other tools."""
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
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_vault_starts_locked tests/test_mcp.py::test_unlock_bad_password tests/test_mcp.py::test_unlock_correct_password tests/test_mcp.py::test_lock_clears_session -v
```
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): scaffold server + unlock/lock tools"
```

---

## Task 3: list_keys tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_list_keys_locked():
    mcp_mod = _fresh_mcp()
    result = mcp_mod.list_keys.fn()
    assert result.get("error") == "vault_locked"


def test_list_keys_returns_metadata(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    vault = {
        "OPENAI_KEY": {"value": "sk-abc", "created": "2024-01-01", "rotated": "2024-01-01",
                       "provider": "OpenAI", "env": "prod", "projects": ["/myapp"], "notes": ""},
        "STRIPE_KEY": {"value": "sk_live_xyz", "created": "2024-01-01", "rotated": "2024-01-01",
                       "provider": "Stripe", "env": "prod", "projects": [], "notes": ""},
    }
    save_vault(vault, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.list_keys.fn()
    assert result["count"] == 2
    assert any(k["name"] == "OPENAI_KEY" for k in result["keys"])
    # values must NOT be returned
    for k in result["keys"]:
        assert "value" not in k


def test_list_keys_filter_env(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    vault = {
        "PROD_KEY": {"value": "v1", "created": "2024-01-01", "rotated": "2024-01-01",
                     "provider": "Unknown", "env": "prod", "projects": [], "notes": ""},
        "DEV_KEY":  {"value": "v2", "created": "2024-01-01", "rotated": "2024-01-01",
                     "provider": "Unknown", "env": "dev", "projects": [], "notes": ""},
    }
    save_vault(vault, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.list_keys.fn(env="dev")
    assert result["count"] == 1
    assert result["keys"][0]["name"] == "DEV_KEY"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_list_keys_locked tests/test_mcp.py::test_list_keys_returns_metadata tests/test_mcp.py::test_list_keys_filter_env -v
```
Expected: `AttributeError: module 'pushkey_mcp' has no attribute 'list_keys'`

- [ ] **Step 3: Add list_keys to pushkey_mcp.py**

Insert after the `lock_vault` tool:
```python
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_list_keys_locked tests/test_mcp.py::test_list_keys_returns_metadata tests/test_mcp.py::test_list_keys_filter_env -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add list_keys tool"
```

---

## Task 4: get_key tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_get_key_returns_value(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    save_vault({"MY_KEY": {"value": "super-secret", "created": "2024-01-01", "rotated": "2024-01-01",
                           "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.get_key.fn("MY_KEY")
    assert result["value"] == "super-secret"


def test_get_key_not_found(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")

    from pushkey_vault import save_vault
    save_vault({}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.get_key.fn("MISSING_KEY")
    assert "error" in result
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_get_key_returns_value tests/test_mcp.py::test_get_key_not_found -v
```
Expected: `AttributeError: module 'pushkey_mcp' has no attribute 'get_key'`

- [ ] **Step 3: Add get_key to pushkey_mcp.py**

```python
@mcp.tool()
def get_key(name: str) -> dict:
    """Get the value of a specific key from the vault by name."""
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_get_key_returns_value tests/test_mcp.py::test_get_key_not_found -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add get_key tool"
```

---

## Task 5: add_key tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_add_key_persists(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault, load_vault
    save_vault({}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.add_key.fn("NEW_KEY", "new-value", provider="OpenAI", env="dev")
    assert result["success"] is True

    vault, _ = load_vault("pw")
    assert "NEW_KEY" in vault
    assert vault["NEW_KEY"]["value"] == "new-value"


def test_add_key_duplicate_rejected(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault
    save_vault({"EXISTING": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                              "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.add_key.fn("EXISTING", "new-value")
    assert result["success"] is False
    assert "already exists" in result["error"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_add_key_persists tests/test_mcp.py::test_add_key_duplicate_rejected -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add add_key to pushkey_mcp.py**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_add_key_persists tests/test_mcp.py::test_add_key_duplicate_rejected -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add add_key tool"
```

---

## Task 6: inject_env tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_inject_env_writes_file(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path / "vault_dir")
    (tmp_path / "vault_dir").mkdir()
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault_dir" / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / "vault_dir" / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "vault_dir" / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "vault_dir" / "pushkey.log")

    from pushkey_vault import save_vault
    vault = {
        "OPENAI_KEY": {"value": "sk-abc", "created": "2024-01-01", "rotated": "2024-01-01",
                       "provider": "OpenAI", "env": "dev", "projects": [], "notes": ""},
    }
    save_vault(vault, "pw")

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.inject_env.fn(str(project_dir), keys=["OPENAI_KEY"])
    assert result["success"] is True
    env_file = project_dir / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "OPENAI_KEY=sk-abc" in content


def test_inject_env_adds_gitignore(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path / "vault_dir")
    (tmp_path / "vault_dir").mkdir()
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault_dir" / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / "vault_dir" / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "vault_dir" / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "vault_dir" / "pushkey.log")

    from pushkey_vault import save_vault
    save_vault({"K": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                      "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    mcp_mod.inject_env.fn(str(project_dir), keys=["K"])
    gitignore = project_dir / ".gitignore"
    assert gitignore.exists()
    assert ".env" in gitignore.read_text()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_inject_env_writes_file tests/test_mcp.py::test_inject_env_adds_gitignore -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add inject_env to pushkey_mcp.py**

```python
@mcp.tool()
def inject_env(project_path: str, keys: list[str] = None) -> dict:
    """
    Write vault keys into <project_path>/.env and ensure .env is in .gitignore.
    If keys is None, injects all keys whose projects list includes project_path.
    """
    err = _require_unlock()
    if err:
        return err
    from pathlib import Path
    vault = _SESSION["vault"]
    project = Path(project_path)
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_inject_env_writes_file tests/test_mcp.py::test_inject_env_adds_gitignore -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add inject_env tool"
```

---

## Task 7: check_health tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_check_health_stale(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault
    vault = {
        "OLD_KEY": {"value": "v", "created": "2020-01-01", "rotated": "2020-01-01",
                    "provider": "Unknown", "env": "dev", "projects": [], "notes": ""},
        "NEW_KEY": {"value": "v2", "created": "2025-01-01", "rotated": "2025-01-01",
                    "provider": "Unknown", "env": "dev", "projects": [], "notes": ""},
    }
    save_vault(vault, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.check_health.fn()
    stale_names = [k["name"] for k in result["stale_keys"]]
    assert "OLD_KEY" in stale_names
    assert "NEW_KEY" not in stale_names
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_check_health_stale -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add check_health to pushkey_mcp.py**

```python
@mcp.tool()
def check_health(rotation_threshold_days: int = 90) -> dict:
    """
    Report vault health: total keys, stale keys (not rotated within threshold),
    and keys missing provider detection.
    """
    err = _require_unlock()
    if err:
        return err
    from datetime import datetime
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_check_health_stale -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add check_health tool"
```

---

## Task 8: rotate_key tool

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_mcp.py`:
```python
def test_rotate_key_updates_value(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault, load_vault
    save_vault({"MY_KEY": {"value": "old", "created": "2020-01-01", "rotated": "2020-01-01",
                           "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.rotate_key.fn("MY_KEY", "new-value")
    assert result["success"] is True

    vault, _ = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "new-value"
    assert vault["MY_KEY"]["rotated"] != "2020-01-01"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_rotate_key_updates_value -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add rotate_key to pushkey_mcp.py**

```python
@mcp.tool()
def rotate_key(name: str, new_value: str) -> dict:
    """Replace a key's value and update its rotated timestamp."""
    err = _require_unlock()
    if err:
        return err
    from datetime import datetime
    vault = _SESSION["vault"]
    if name not in vault:
        return {"success": False, "error": f"key '{name}' not found"}
    vault[name]["value"] = new_value
    vault[name]["rotated"] = datetime.now().strftime("%Y-%m-%d")
    _vault.save_vault(vault, _SESSION["password"], vault_key=_SESSION.get("vault_key"))
    return {"success": True, "name": name, "rotated": vault[name]["rotated"]}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_rotate_key_updates_value -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add rotate_key tool"
```

---

## Task 9: list_projects + assign_key tools

**Files:**
- Modify: `pushkey_mcp.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_mcp.py`:
```python
def test_list_projects(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault
    vault = {
        "KEY_A": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                  "provider": "Unknown", "env": "dev", "projects": ["/app1", "/app2"], "notes": ""},
        "KEY_B": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                  "provider": "Unknown", "env": "dev", "projects": ["/app1"], "notes": ""},
    }
    save_vault(vault, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.list_projects.fn()
    assert "/app1" in result["projects"]
    assert result["projects"]["/app1"]["key_count"] == 2


def test_assign_key_to_project(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", tmp_path / "pushkey.log")

    from pushkey_vault import save_vault, load_vault
    save_vault({"MY_KEY": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                           "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.assign_key.fn("MY_KEY", "/myapp")
    assert result["success"] is True

    vault, _ = load_vault("pw")
    assert "/myapp" in vault["MY_KEY"]["projects"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py::test_list_projects tests/test_mcp.py::test_assign_key_to_project -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add list_projects + assign_key to pushkey_mcp.py**

```python
@mcp.tool()
def list_projects() -> dict:
    """List all projects that have keys assigned, with key counts."""
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_mcp.py::test_list_projects tests/test_mcp.py::test_assign_key_to_project -v
```
Expected: both PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/test_mcp.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pushkey_mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add list_projects and assign_key tools"
```

---

## Task 10: Config docs + setup guide

**Files:**
- Create: `docs/mcp-setup.md`

- [ ] **Step 1: Create docs/mcp-setup.md**

Create `docs/mcp-setup.md`:
```markdown
# Pushkey MCP Setup

## Claude Code (stdio transport)

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pushkey": {
      "command": "python",
      "args": ["C:/Users/<YOU>/bots/pushkey/pushkey_mcp.py"],
      "env": {}
    }
  }
}
```

Replace `C:/Users/<YOU>/bots/pushkey/` with your actual path.

## VS Code Copilot (SSE transport)

Start the server in SSE mode:
```bash
python pushkey_mcp.py --port 8765
```

Add to `.vscode/mcp.json` in your workspace:
```json
{
  "servers": {
    "pushkey": {
      "type": "sse",
      "url": "http://localhost:8765/sse"
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `unlock_vault` | Unlock with master password (required first) |
| `lock_vault` | Clear session |
| `list_keys` | List all keys (no values); filter by env/provider/project |
| `get_key` | Get a key's value by name |
| `add_key` | Add a new key to the vault |
| `inject_env` | Write keys to project `.env` + add to `.gitignore` |
| `check_health` | Report stale/expiring keys |
| `rotate_key` | Update a key's value + rotation date |
| `list_projects` | Show all projects and their assigned keys |
| `assign_key` | Link a key to a project path |

## Typical workflow

1. `unlock_vault("my-master-password")`
2. `list_keys()` — see what's available
3. `get_key("OPENAI_API_KEY")` — retrieve value for use
4. `inject_env("/path/to/project", keys=["OPENAI_API_KEY", "STRIPE_KEY"])` — populate .env
5. `check_health()` — find stale keys before deploying
```

- [ ] **Step 2: Commit**

```bash
git add docs/mcp-setup.md
git commit -m "docs(mcp): add Claude Code + VS Code setup guide"
```

---

## Task 11: Companion skill

**Files:**
- Create: `~/.claude/skills/pushkey/SKILL.md`

- [ ] **Step 1: Create the skill**

Create `~/.claude/skills/pushkey/SKILL.md`:
```markdown
---
name: pushkey
description: >
  Use when the user mentions API keys, secrets, credentials, .env files, or
  needs to configure environment variables for a project. Also triggers when
  user asks "what keys do I have", "add this key", or "set up env for X".
---

# Pushkey — API Key Vault MCP

Pushkey is a local encrypted vault for API keys. An MCP server exposes it
directly to Claude Code via these tools: unlock_vault, list_keys, get_key,
add_key, inject_env, check_health, rotate_key, list_projects, assign_key.

## Workflow

**Before any key operation:**
1. Call `unlock_vault` with the user's master password if vault is locked.
   Ask the user for the password — never guess or invent one.
2. After unlocking, session stays open for the conversation.

**Finding keys for a project:**
```
list_keys(project="/path/to/project")
```
If no keys are assigned yet, try `list_keys()` and ask user which ones to link.

**Setting up a new project's .env:**
```
unlock_vault("password")
inject_env("/path/to/project", keys=["KEY_A", "KEY_B"])
```

**Adding a key the user just obtained:**
```
add_key("PROVIDER_API_KEY", "sk-...", provider="OpenAI", env="dev")
```

**Before deploying / shipping:**
```
check_health()  # flag anything stale (>90 days)
```

## Security rules

- NEVER log, display, or include raw key values in commit messages or comments.
- When showing key lists, use `list_keys` (no values) not `get_key`.
- Only call `get_key` when the user explicitly needs the value for config/code.
- Always confirm before calling `inject_env` — it writes to disk.
```

- [ ] **Step 2: Verify skill is discoverable**

```bash
python -c "
import pathlib
skill = pathlib.Path.home() / '.claude' / 'skills' / 'pushkey' / 'SKILL.md'
print('EXISTS:', skill.exists())
print(skill.read_text()[:80])
"
```
Expected: `EXISTS: True` and first 80 chars of the skill.

- [ ] **Step 3: Final full test run**

```bash
pytest tests/test_mcp.py -v
```
Expected: all tests PASS.

- [ ] **Step 4: Final commit**

```bash
git add docs/mcp-setup.md
git commit -m "feat(mcp): add pushkey companion skill for Claude Code"
```

---

## Self-Review

**Spec coverage:**
- [x] unlock/lock — Task 2
- [x] list_keys with filters — Task 3
- [x] get_key — Task 4
- [x] add_key with duplicate protection — Task 5
- [x] inject_env + .gitignore — Task 6
- [x] check_health stale detection — Task 7
- [x] rotate_key — Task 8
- [x] list_projects + assign_key — Task 9
- [x] Claude Code config — Task 10
- [x] VS Code config — Task 10
- [x] Companion skill — Task 11

**Placeholder scan:** None found — all steps contain complete code.

**Type consistency:** `_SESSION["vault"]`, `_SESSION["password"]`, `_SESSION["vault_key"]` used consistently across all tools.

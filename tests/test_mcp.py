import importlib
import sys
import pytest

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


def test_list_keys_locked():
    mcp_mod = _fresh_mcp()
    result = mcp_mod.list_keys()
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
    result = mcp_mod.list_keys()
    assert result["count"] == 2
    assert any(k["name"] == "OPENAI_KEY" for k in result["keys"])
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
    result = mcp_mod.list_keys(env="dev")
    assert result["count"] == 1
    assert result["keys"][0]["name"] == "DEV_KEY"


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
    result = mcp_mod.get_key("MY_KEY")
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
    result = mcp_mod.get_key("MISSING_KEY")
    assert "error" in result


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
    result = mcp_mod.add_key("NEW_KEY", "new-value", provider="OpenAI", env="dev")
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
    result = mcp_mod.add_key("EXISTING", "new-value")
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_inject_env_writes_file(tmp_path, monkeypatch):
    import pushkey_shared as _s
    vault_dir = tmp_path / "vault_dir"
    vault_dir.mkdir()
    monkeypatch.setattr(_s, "VAULT_DIR", vault_dir)
    monkeypatch.setattr(_s, "VAULT_FILE", vault_dir / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", vault_dir / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", vault_dir / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", vault_dir / "pushkey.log")

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
    result = mcp_mod.inject_env(str(project_dir), keys=["OPENAI_KEY"])
    assert result["success"] is True
    env_file = project_dir / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "OPENAI_KEY=sk-abc" in content


def test_inject_env_adds_gitignore(tmp_path, monkeypatch):
    import pushkey_shared as _s
    vault_dir = tmp_path / "vault_dir"
    vault_dir.mkdir()
    monkeypatch.setattr(_s, "VAULT_DIR", vault_dir)
    monkeypatch.setattr(_s, "VAULT_FILE", vault_dir / "vault.enc")
    monkeypatch.setattr(_s, "SALT_FILE", vault_dir / ".salt")
    monkeypatch.setattr(_s, "CONFIG_FILE", vault_dir / "config.json")
    monkeypatch.setattr(_s, "LOG_FILE", vault_dir / "pushkey.log")

    from pushkey_vault import save_vault
    save_vault({"K": {"value": "v", "created": "2024-01-01", "rotated": "2024-01-01",
                      "provider": "Unknown", "env": "dev", "projects": [], "notes": ""}}, "pw")

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    mcp_mod.inject_env(str(project_dir), keys=["K"])
    gitignore = project_dir / ".gitignore"
    assert gitignore.exists()
    assert ".env" in gitignore.read_text()


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
        "NEW_KEY": {"value": "v2", "created": "2026-04-01", "rotated": "2026-04-01",
                    "provider": "Unknown", "env": "dev", "projects": [], "notes": ""},
    }
    save_vault(vault, "pw")
    mcp_mod = _fresh_mcp()
    mcp_mod._unlock("pw")
    result = mcp_mod.check_health()
    stale_names = [k["name"] for k in result["stale_keys"]]
    assert "OLD_KEY" in stale_names
    assert "NEW_KEY" not in stale_names


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
    result = mcp_mod.rotate_key("MY_KEY", "new-value")
    assert result["success"] is True

    vault, _ = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "new-value"
    assert vault["MY_KEY"]["rotated"] != "2020-01-01"


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
    result = mcp_mod.list_projects()
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
    from pathlib import Path
    project_path = str(tmp_path / "myapp")
    expected = str(Path(project_path).resolve())
    result = mcp_mod.assign_key("MY_KEY", project_path)
    assert result["success"] is True

    vault, _ = load_vault("pw")
    assert expected in vault["MY_KEY"]["projects"]

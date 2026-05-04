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

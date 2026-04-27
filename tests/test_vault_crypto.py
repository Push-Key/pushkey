from pathlib import Path

import pushkey


def test_save_and_load_vault_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(pushkey, "LOG_FILE", tmp_path / "pushkey.log")

    vault = {"OPENAI_API_KEY": {"value": "sk-test", "created": "2026-01-01T00:00:00"}}
    pushkey.save_vault(vault, "password123")

    loaded = pushkey.load_vault("password123")
    assert loaded == vault

    assert pushkey.load_vault("wrong-password") is None


"""Test encryption edge cases and special characters."""
import pytest
from pathlib import Path

import pushkey


def test_encrypt_special_characters(tmp_path, monkeypatch):
    """Keys with special chars, unicode, newlines should work."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    special_keys = {
        "key-with-dashes": "key-with-dashes-value",
        "key_with_underscores": "underscore_value",
        "key.with.dots": "dot.value",
        "special!@#$": "special!@#$%value",
    }

    vault = {
        name: {
            "current": value,
            "previous": None,
            "created": "2026-04-27T00:00:00",
            "rotated_at": "2026-04-27T00:00:00",
            "provider": "Unknown",
        }
        for name, value in special_keys.items()
    }

    pushkey.save_vault(vault, password)
    loaded, _ = pushkey.load_vault(password)

    # Verify all special keys were encrypted and decrypted correctly
    for name, value in special_keys.items():
        assert name in loaded
        assert loaded[name]["current"] == value


def test_very_long_api_key(tmp_path, monkeypatch):
    """Super long API keys should be handled."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    long_key = "a" * 10000  # 10K char key

    vault = {
        "LONG_KEY": {
            "current": long_key,
            "previous": None,
            "created": "2026-04-27T00:00:00",
            "rotated_at": "2026-04-27T00:00:00",
            "provider": "Unknown",
        }
    }

    pushkey.save_vault(vault, password)
    loaded, _ = pushkey.load_vault(password)

    assert loaded["LONG_KEY"]["current"] == long_key


def test_master_password_with_special_chars(tmp_path, monkeypatch):
    """Master password with special chars, spaces, unicode."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    special_passwords = [
        "pass word",  # space
        "pass-word",  # dash
        "pass.word",  # dot
        "p@ssw0rd!",  # symbols
        "pässwörd",  # unicode
    ]

    test_vault = {
        "TEST_KEY": {
            "current": "test-value",
            "previous": None,
            "created": "2026-04-27T00:00:00",
            "rotated_at": "2026-04-27T00:00:00",
            "provider": "Unknown",
        }
    }

    for pwd in special_passwords:
        pushkey.save_vault(test_vault, pwd)
        loaded, _ = pushkey.load_vault(pwd)
        assert "TEST_KEY" in loaded
        assert loaded["TEST_KEY"]["current"] == "test-value"


def test_base64_like_value(tmp_path, monkeypatch):
    """Keys that look like base64 or binary data."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    import base64

    password = "test123"
    binary_like = base64.b64encode(b"\x00\x01\x02\x03\x04").decode()

    vault = {
        "BINARY_LIKE": {
            "current": binary_like,
            "previous": None,
            "created": "2026-04-27T00:00:00",
            "rotated_at": "2026-04-27T00:00:00",
            "provider": "Unknown",
        }
    }

    pushkey.save_vault(vault, password)
    loaded, _ = pushkey.load_vault(password)

    assert loaded["BINARY_LIKE"]["current"] == binary_like


def test_sql_injection_like_value(tmp_path, monkeypatch):
    """Keys with SQL-injection-like patterns should be safely encrypted."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    sql_like_keys = {
        "sql_injection_1": "' OR '1'='1",
        "sql_injection_2": "'; DROP TABLE keys; --",
        "shell_injection": "${IFS}cat${IFS}/etc/passwd",
    }

    vault = {
        name: {
            "current": value,
            "previous": None,
            "created": "2026-04-27T00:00:00",
            "rotated_at": "2026-04-27T00:00:00",
            "provider": "Unknown",
        }
        for name, value in sql_like_keys.items()
    }

    pushkey.save_vault(vault, password)
    loaded, _ = pushkey.load_vault(password)

    # Verify dangerous strings are preserved exactly (not interpreted)
    for name, value in sql_like_keys.items():
        assert loaded[name]["current"] == value

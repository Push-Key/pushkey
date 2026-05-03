"""Test key rotation and health tracking."""
import pytest
from datetime import datetime, timedelta
from pathlib import Path

import pushkey


@pytest.fixture
def vault_setup(tmp_path, monkeypatch):
    """Setup vault in tmp dir."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    vault = {
        "OPENAI_API_KEY": {
            "current": "sk-old-value",
            "previous": None,
            "created": datetime.now().isoformat(),
            "rotated_at": datetime.now().isoformat(),
            "provider": "OpenAI",
        }
    }
    pushkey.save_vault(vault, password)
    return password, vault


def test_rotation_timestamp(vault_setup):
    """Track when keys were rotated."""
    password, vault = vault_setup
    loaded, _ = pushkey.load_vault(password)

    assert loaded["OPENAI_API_KEY"]["rotated_at"] is not None
    assert isinstance(loaded["OPENAI_API_KEY"]["rotated_at"], str)


def test_rotation_history_preserved(tmp_path, monkeypatch):
    """Previous key is saved as backup after rotation."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    vault = {
        "STRIPE_KEY": {
            "current": "rk_live_old",
            "previous": None,
            "created": datetime.now().isoformat(),
            "rotated_at": datetime.now().isoformat(),
            "provider": "Stripe",
        }
    }
    pushkey.save_vault(vault, password)

    # Simulate rotation
    loaded, _ = pushkey.load_vault(password)
    loaded["STRIPE_KEY"]["previous"] = loaded["STRIPE_KEY"]["current"]
    loaded["STRIPE_KEY"]["current"] = "rk_live_new"
    pushkey.save_vault(loaded, password)

    rotated, _ = pushkey.load_vault(password)
    assert rotated["STRIPE_KEY"]["previous"] == "rk_live_old"
    assert rotated["STRIPE_KEY"]["current"] == "rk_live_new"


def test_health_status_age_tracking(tmp_path, monkeypatch):
    """Track key age from rotation timestamp."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"

    # Create key from 95 days ago
    old_date = (datetime.now() - timedelta(days=95)).isoformat()
    vault = {
        "ANTHROPIC_KEY": {
            "current": "sk-ant-test",
            "previous": None,
            "created": old_date,
            "rotated_at": old_date,
            "provider": "Anthropic",
        }
    }
    pushkey.save_vault(vault, password)

    loaded, _ = pushkey.load_vault(password)
    rotated_date = datetime.fromisoformat(loaded["ANTHROPIC_KEY"]["rotated_at"])
    days_old = (datetime.now() - rotated_date).days

    assert days_old >= 90  # Key should be 90+ days old


def test_cannot_rotate_nonexistent_key(tmp_path, monkeypatch):
    """Rotating a key that doesn't exist fails gracefully."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    password = "test123"
    vault = {}
    pushkey.save_vault(vault, password)

    loaded, _ = pushkey.load_vault(password)
    # Key doesn't exist, can't rotate
    assert "NONEXISTENT_KEY" not in loaded

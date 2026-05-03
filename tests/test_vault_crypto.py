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


import pytest
from pushkey_crypto import (
    generate_recovery_code,
    encrypt_data_v3,
    decrypt_data_v3,
    rekey_vault,
    add_recovery_key,
    _V3_MAGIC,
    encrypt_data,
    decrypt_data,
)

# ── generate_recovery_code ─────────────────────────────────────────────────────

def test_recovery_code_format():
    code = generate_recovery_code()
    assert code.startswith("PUSH-")
    parts = code.split("-")
    assert len(parts) == 5
    assert all(len(p) == 4 for p in parts[1:])

def test_recovery_code_unique():
    assert generate_recovery_code() != generate_recovery_code()

# ── V3 round-trip ──────────────────────────────────────────────────────────────

def test_v3_round_trip(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("hello vault", "mypassword", code)
    assert token.startswith(_V3_MAGIC)

    plaintext, vault_key = decrypt_data_v3(token, password="mypassword")
    assert plaintext == "hello vault"
    assert len(vault_key) == 32

def test_v3_decrypt_with_recovery_code(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("secret data", "hunter2", code)

    plaintext, vault_key = decrypt_data_v3(token, recovery_code=code)
    assert plaintext == "secret data"
    assert len(vault_key) == 32

def test_v3_wrong_password_raises(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("data", "correct", code)
    with pytest.raises(ValueError, match="wrong_password"):
        decrypt_data_v3(token, password="wrong")

def test_v3_wrong_recovery_code_raises(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("data", "pw", code)
    with pytest.raises(ValueError, match="wrong_recovery_code"):
        decrypt_data_v3(token, recovery_code="PUSH-AAAA-BBBB-CCCC-DDDD")

# ── rekey_vault ────────────────────────────────────────────────────────────────

def test_rekey_vault_changes_password(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)

    new_token = rekey_vault(token, code, "newpass")

    plaintext, _ = decrypt_data_v3(new_token, password="newpass")
    assert plaintext == "my keys"

def test_rekey_vault_old_password_fails(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)
    new_token = rekey_vault(token, code, "newpass")

    with pytest.raises(ValueError):
        decrypt_data_v3(new_token, password="oldpass")

def test_rekey_recovery_code_still_works(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)
    new_token = rekey_vault(token, code, "newpass")

    plaintext, _ = decrypt_data_v3(new_token, recovery_code=code)
    assert plaintext == "my keys"

# ── add_recovery_key (V2 → V3 migration) ─────────────────────────────────────

def test_add_recovery_key_migrates_v2(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    v2_token = encrypt_data("original data", "mypass")
    code = generate_recovery_code()
    v3_token = add_recovery_key(v2_token, "mypass", code)

    assert v3_token.startswith(_V3_MAGIC)
    plaintext, _ = decrypt_data_v3(v3_token, password="mypass")
    assert plaintext == "original data"

    plaintext2, _ = decrypt_data_v3(v3_token, recovery_code=code)
    assert plaintext2 == "original data"

# ── recovery code normalization ────────────────────────────────────────────────

def test_recovery_code_normalization(tmp_path, monkeypatch):
    """Spaces and lowercase in recovery code should be accepted."""
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()  # e.g. PUSH-ABCD-EFGH-IJKL-MNOP
    token = encrypt_data_v3("data", "pw", code)

    messy = code.lower().replace("-", " ")
    plaintext, _ = decrypt_data_v3(token, recovery_code=messy)
    assert plaintext == "data"


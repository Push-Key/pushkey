from pathlib import Path
import base64
import hashlib
import json

import pushkey


def test_save_and_load_vault_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(pushkey, "LOG_FILE", tmp_path / "pushkey.log")

    vault = {"OPENAI_API_KEY": {"value": "sk-test", "created": "2026-01-01T00:00:00"}}
    pushkey.save_vault(vault, "password123")

    loaded, _ = pushkey.load_vault("password123")
    assert loaded == vault

    bad, _ = pushkey.load_vault("wrong-password")
    assert bad is None


import pytest
import pushkey_shared
from pushkey_crypto import (
    generate_recovery_code,
    encrypt_data_v3,
    decrypt_data_v3,
    rekey_vault,
    add_recovery_key,
    _V3_MAGIC,
    encrypt_data,
    decrypt_data,
    VaultFormatError,
    VaultIntegrityError,
    VaultAuthenticationError,
    Fernet,
    get_or_create_salt,
)

# ── generate_recovery_code ─────────────────────────────────────────────────────

def test_recovery_code_format():
    code = generate_recovery_code()
    assert code.startswith("PUSH-")
    parts = code.split("-")
    assert len(parts) == 5
    assert all(len(p) == 4 for p in parts[1:])
    assert all(set(p) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for p in parts[1:])

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


# ── load_vault / save_vault tuple contract ────────────────────────────────────

from pushkey_vault import (
    load_vault,
    save_vault,
    migrate_vault_to_v3,
    replace_v3_recovery_code,
)
from pushkey_vault import VaultConflictError


def test_load_vault_v2_returns_none_key(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    save_vault({"MY_KEY": {"value": "abc"}}, "pw")
    vault, vault_key = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "abc"
    assert vault_key is None  # V2 vault → no key


def test_load_vault_v3_returns_vault_key(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    code = generate_recovery_code()
    save_vault({"MY_KEY": {"value": "abc"}}, "pw", recovery_code=code)
    vault, vault_key = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "abc"
    assert len(vault_key) == 32


def test_save_vault_v3_preserves_vault_key(tmp_path, monkeypatch):
    """Re-saving a V3 vault must use the same vault_key so recovery code still works."""
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    code = generate_recovery_code()
    save_vault({"A": {"value": "1"}}, "pw", recovery_code=code)

    vault, vault_key = load_vault("pw")
    vault["B"] = {"value": "2"}
    save_vault(vault, "pw", vault_key=vault_key)

    # Recovery code must still unlock the updated vault
    raw = (_s.VAULT_FILE).read_bytes()
    plaintext, _ = decrypt_data_v3(raw, recovery_code=code)
    import json
    data = json.loads(plaintext)
    assert data["keys"]["B"]["value"] == "2"


def test_load_vault_rejects_truncated_v3_as_corrupt(tmp_path):
    import pushkey_shared as _s
    _s.VAULT_FILE.write_bytes(_V3_MAGIC + b"x" * 10)
    with pytest.raises(VaultFormatError):
        load_vault("pw")


def test_load_vault_rejects_tampered_body_as_corrupt(tmp_path):
    import pushkey_shared as _s
    code = generate_recovery_code()
    save_vault({"A": {"value": "1"}}, "pw", recovery_code=code)
    token = bytearray(_s.VAULT_FILE.read_bytes())
    token[-1] ^= 1
    _s.VAULT_FILE.write_bytes(token)
    with pytest.raises(VaultIntegrityError):
        load_vault("pw")


def test_load_vault_rejects_oversized_file_before_read(tmp_path, monkeypatch):
    import pushkey_shared as _s
    import pushkey_vault
    _s.VAULT_FILE.write_bytes(b"x" * 32)
    monkeypatch.setattr(pushkey_vault, "MAX_VAULT_BYTES", 16)
    with pytest.raises(VaultFormatError, match="too_large"):
        load_vault("pw")


def test_interrupted_replace_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    import pushkey_shared as _s
    import pushkey_vault
    code = generate_recovery_code()
    save_vault({"A": {"value": "original"}}, "pw", recovery_code=code)
    original = _s.VAULT_FILE.read_bytes()
    vault, _ = load_vault("pw")
    vault["A"]["value"] = "changed"

    def fail_replace(src, dst):
        raise OSError("simulated interruption")

    monkeypatch.setattr(pushkey_vault.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        save_vault(vault, "pw", recovery_code=code)

    assert _s.VAULT_FILE.read_bytes() == original
    assert not list(_s.VAULT_DIR.glob(".vault.*.tmp"))


def test_save_vault_validates_ciphertext_before_replace(tmp_path, monkeypatch):
    import pushkey_shared as _s
    import pushkey_vault
    code = generate_recovery_code()
    save_vault({"A": {"value": "original"}}, "pw", recovery_code=code)
    original = _s.VAULT_FILE.read_bytes()
    vault, _ = load_vault("pw")
    vault["A"]["value"] = "changed"
    monkeypatch.setattr(pushkey_vault, "encrypt_data_v3", lambda *a: _V3_MAGIC + b"broken")

    with pytest.raises(VaultFormatError):
        save_vault(vault, "pw", recovery_code=code)

    assert _s.VAULT_FILE.read_bytes() == original


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_generated_format_fixtures_round_trip(version):
    """Generated fixtures pin the supported binary format markers and loaders."""
    import pushkey_shared as _s
    code = generate_recovery_code()
    fixture_json = '{"_schema": 3, "keys": {"K": {"value": "v"}}}'
    if version == "v1":
        legacy_key = hashlib.pbkdf2_hmac(
            "sha256", b"pw", get_or_create_salt(), iterations=600_000
        )
        token = Fernet(base64.urlsafe_b64encode(legacy_key)).encrypt(fixture_json.encode())
        assert not token.startswith((b"PK2\x00", b"PK3\x00"))
        assert json.loads(decrypt_data(token, "pw"))["keys"]["K"]["value"] == "v"
    elif version == "v2":
        token = encrypt_data(fixture_json, "pw")
        assert token.startswith(b"PK2\x00")
        assert json.loads(decrypt_data(token, "pw"))["keys"]["K"]["value"] == "v"
    else:
        token = encrypt_data_v3(fixture_json, "pw", code)
        assert token.startswith(b"PK3\x00")
        plaintext, _ = decrypt_data_v3(token, password="pw")
        assert json.loads(plaintext)["keys"]["K"]["value"] == "v"


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_checked_in_format_fixture_remains_readable(version):
    import pushkey_shared as _s
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "vault_formats.json").read_text()
    )
    _s.SALT_FILE.write_bytes(base64.b64decode(fixture["salt_b64"]))
    token = base64.b64decode(fixture[f"{version}_b64"])
    if version == "v3":
        plaintext, _ = decrypt_data_v3(token, password=fixture["password"])
        recovered, _ = decrypt_data_v3(token, recovery_code=fixture["recovery"])
        assert recovered == plaintext
    else:
        plaintext = decrypt_data(token, fixture["password"])
    assert json.loads(plaintext)["keys"]["FIXTURE_KEY"]["value"] == "nonsecret-test-value"


def test_v2_to_v3_migration_retains_exact_source_backup():
    import pushkey_shared as _s
    save_vault({"K": {"value": "v"}}, "pw")
    original = _s.VAULT_FILE.read_bytes()
    backup = migrate_vault_to_v3("pw", generate_recovery_code())

    assert backup.read_bytes() == original
    assert _s.VAULT_FILE.read_bytes().startswith(_V3_MAGIC)


def test_v3_decrypts_vault_created_with_legacy_pbkdf2(monkeypatch):
    import pushkey_crypto
    code = generate_recovery_code()
    monkeypatch.setattr(
        pushkey_crypto,
        "_derive_key_argon2",
        pushkey_crypto._derive_key_pbkdf2,
    )
    token = encrypt_data_v3("legacy pbkdf body", "pw", code)
    plaintext, _ = decrypt_data_v3(token, password="pw")
    assert plaintext == "legacy pbkdf body"


def test_v3_creation_requires_argon2(monkeypatch):
    import pushkey_crypto
    monkeypatch.setattr(pushkey_crypto, "_ARGON2_AVAILABLE", False)
    with pytest.raises(pushkey_crypto.VaultUnsupportedKDFError):
        encrypt_data_v3("data", "pw", "PUSH-ABCD-EFGH-IJKL-MNOP")


def test_load_vault_preserves_unsupported_kdf_error(monkeypatch):
    import pushkey_crypto
    import pushkey_shared as _s
    code = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=code)
    monkeypatch.setattr(pushkey_crypto, "_ARGON2_AVAILABLE", False)
    with pytest.raises(pushkey_crypto.VaultUnsupportedKDFError):
        load_vault("pw")


def test_existing_v3_save_requires_authenticated_key():
    code = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=code)
    vault, _ = load_vault("pw")
    vault["K"]["value"] = "changed"
    with pytest.raises(VaultFormatError, match="requires_vault_key"):
        save_vault(vault, "pw")


def test_existing_v3_rejects_unrelated_vault_key():
    code = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=code)
    vault, _ = load_vault("pw")
    vault["K"]["value"] = "changed"
    with pytest.raises(VaultAuthenticationError, match="vault_key_mismatch"):
        save_vault(vault, "pw", vault_key=b"x" * 32)


def test_stale_loaded_vault_cannot_overwrite_newer_revision():
    code = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=code)
    first, first_key = load_vault("pw")
    stale, stale_key = load_vault("pw")
    first["K"]["value"] = "new"
    save_vault(first, "pw", vault_key=first_key)
    stale["K"]["value"] = "stale"
    with pytest.raises(VaultConflictError):
        save_vault(stale, "pw", vault_key=stale_key)


def test_replace_v3_recovery_preserves_data_and_invalidates_old_code():
    old = generate_recovery_code()
    new = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=old)
    replace_v3_recovery_code("pw", new)
    raw = pushkey_shared.VAULT_FILE.read_bytes()
    plaintext, _ = decrypt_data_v3(raw, recovery_code=new)
    assert json.loads(plaintext)["keys"]["K"]["value"] == "v"
    with pytest.raises(VaultAuthenticationError):
        decrypt_data_v3(raw, recovery_code=old)


def test_replace_v3_recovery_wrong_password_leaves_bytes_unchanged():
    old = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=old)
    before = pushkey_shared.VAULT_FILE.read_bytes()
    with pytest.raises(VaultAuthenticationError):
        replace_v3_recovery_code("wrong", generate_recovery_code())
    assert pushkey_shared.VAULT_FILE.read_bytes() == before


def test_replace_v3_recovery_rejects_stale_revision():
    import hashlib
    old = generate_recovery_code()
    save_vault({"K": {"value": "v"}}, "pw", recovery_code=old)
    stale_revision = hashlib.sha256(pushkey_shared.VAULT_FILE.read_bytes()).digest()
    vault, key = load_vault("pw")
    vault["K"]["value"] = "new"
    save_vault(vault, "pw", vault_key=key)
    with pytest.raises(VaultConflictError):
        replace_v3_recovery_code(
            "pw", generate_recovery_code(), expected_revision=stale_revision
        )


def test_normal_saves_retain_exactly_three_rolling_backups():
    import pushkey_shared as _s
    code = generate_recovery_code()
    save_vault({"K": {"value": "0"}}, "pw", recovery_code=code)
    vault, vault_key = load_vault("pw")
    for index in range(1, 6):
        vault["K"]["value"] = str(index)
        save_vault(vault, "pw", vault_key=vault_key)
    assert len(list(_s.VAULT_DIR.glob("vault_backup_*.enc"))) == 3


def test_failed_normal_replace_does_not_prune_existing_history(monkeypatch):
    import pushkey_shared as _s
    import pushkey_vault
    code = generate_recovery_code()
    save_vault({"K": {"value": "0"}}, "pw", recovery_code=code)
    vault, vault_key = load_vault("pw")
    for index in range(1, 4):
        vault["K"]["value"] = str(index)
        save_vault(vault, "pw", vault_key=vault_key)
    existing_backups = set(_s.VAULT_DIR.glob("vault_backup_*.enc"))
    assert len(existing_backups) == 3

    vault["K"]["value"] = "failed"
    monkeypatch.setattr(
        pushkey_vault.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("simulated replace failure")),
    )
    with pytest.raises(OSError, match="simulated"):
        save_vault(vault, "pw", vault_key=vault_key)

    backups_after_failure = set(_s.VAULT_DIR.glob("vault_backup_*.enc"))
    assert existing_backups <= backups_after_failure
    assert len(backups_after_failure) == 4


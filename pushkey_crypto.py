"""
Pushkey — crypto primitives, key derivation, vault serialization, and audit logging.
"""
import base64
import hashlib
import json
import os
import re
import secrets
from datetime import datetime

import pushkey_shared as _s

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    Fernet = InvalidToken = AESGCM = None  # type: ignore

hash_secret_raw = None
Argon2Type = None
_ARGON2_AVAILABLE = False


def _try_load_argon2():
    global hash_secret_raw, Argon2Type, _ARGON2_AVAILABLE
    try:
        from argon2.low_level import hash_secret_raw as _h, Type as _T
        hash_secret_raw = _h
        Argon2Type = _T
        _ARGON2_AVAILABLE = True
    except ImportError:
        pass


_V2_MAGIC = b'PK2\x00'
_V2T_MAGIC = b'PKT2'
_V3_MAGIC = b'PK3\x00'
_V3_HEADER_SIZE = 200  # 4+32+32+12+48+12+48+12 = 200


def generate_recovery_code() -> str:
    """Returns PUSH-XXXX-XXXX-XXXX-XXXX (80 bits entropy, base32)."""
    import base64 as _b64
    raw = secrets.token_bytes(13)
    b32 = _b64.b32encode(raw).decode().rstrip("=")[:20].upper()
    return f"PUSH-{b32[0:4]}-{b32[4:8]}-{b32[8:12]}-{b32[12:16]}"


def _normalize_recovery_code(code: str) -> str:
    return code.upper().replace("-", "").replace(" ", "")


def encrypt_data_v3(data: str, password: str, recovery_code: str) -> bytes:
    salt = get_or_create_salt()
    rec_salt = secrets.token_bytes(32)
    vault_key = secrets.token_bytes(32)

    pw_key = derive_key(password, salt)
    pw_nonce = secrets.token_bytes(12)
    pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

    norm = _normalize_recovery_code(recovery_code)
    rec_key = derive_key(norm, rec_salt)
    rec_nonce = secrets.token_bytes(12)
    rec_ct = AESGCM(rec_key).encrypt(rec_nonce, vault_key, None)

    body_nonce = secrets.token_bytes(12)
    body_ct = AESGCM(vault_key).encrypt(body_nonce, data.encode(), None)

    return (
        _V3_MAGIC
        + salt
        + rec_salt
        + pw_nonce + pw_ct
        + rec_nonce + rec_ct
        + body_nonce + body_ct
    )


def decrypt_data_v3(
    token: bytes,
    *,
    password: str = None,
    recovery_code: str = None,
) -> tuple:
    """Returns (plaintext, vault_key). Pass exactly one of password or recovery_code."""
    if not token.startswith(_V3_MAGIC):
        raise ValueError("not_v3")
    if len(token) < _V3_HEADER_SIZE:
        raise ValueError("not_v3")

    payload = token[len(_V3_MAGIC):]
    salt       = payload[0:32]
    rec_salt   = payload[32:64]
    pw_nonce   = payload[64:76]
    pw_ct      = payload[76:124]
    rec_nonce  = payload[124:136]
    rec_ct     = payload[136:184]
    body_nonce = payload[184:196]
    body_ct    = payload[196:]

    if password is not None:
        pw_key = derive_key(password, salt)
        try:
            vault_key = AESGCM(pw_key).decrypt(pw_nonce, pw_ct, None)
        except Exception:
            raise ValueError("wrong_password")
    elif recovery_code is not None:
        norm = _normalize_recovery_code(recovery_code)
        rec_key = derive_key(norm, rec_salt)
        try:
            vault_key = AESGCM(rec_key).decrypt(rec_nonce, rec_ct, None)
        except Exception:
            raise ValueError("wrong_recovery_code")
    else:
        raise ValueError("must pass password or recovery_code")

    try:
        plaintext = AESGCM(vault_key).decrypt(body_nonce, body_ct, None).decode()
    except Exception:
        raise ValueError("body_corrupt")

    return plaintext, vault_key


def rekey_vault(token: bytes, recovery_code: str, new_password: str) -> bytes:
    """Reset master password using recovery code. Returns new V3 token."""
    plaintext, vault_key = decrypt_data_v3(token, recovery_code=recovery_code)

    payload = token[len(_V3_MAGIC):]
    salt      = payload[0:32]
    rec_salt  = payload[32:64]
    rec_nonce = payload[124:136]
    rec_ct    = payload[136:184]

    pw_key = derive_key(new_password, salt)
    pw_nonce = secrets.token_bytes(12)
    pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

    body_nonce = secrets.token_bytes(12)
    body_ct = AESGCM(vault_key).encrypt(body_nonce, plaintext.encode(), None)

    return (
        _V3_MAGIC
        + salt
        + rec_salt
        + pw_nonce + pw_ct
        + rec_nonce + rec_ct
        + body_nonce + body_ct
    )


def add_recovery_key(token: bytes, password: str, recovery_code: str) -> bytes:
    """Migrate V2 vault to V3 by adding a recovery slot."""
    if token.startswith(_V3_MAGIC):
        plaintext, _ = decrypt_data_v3(token, password=password)
    else:
        plaintext = decrypt_data(token, password)
    return encrypt_data_v3(plaintext, password, recovery_code)


def get_or_create_salt() -> bytes:
    if _s.SALT_FILE.exists():
        return _s.SALT_FILE.read_bytes()
    salt = secrets.token_bytes(32)
    _s.SALT_FILE.write_bytes(salt)
    try:
        os.chmod(_s.SALT_FILE, 0o600)
    except Exception:
        pass
    return salt


def derive_key(password: str, salt: bytes) -> bytes:
    """32-byte key via Argon2id (memory-hard). Falls back to PBKDF2 if argon2-cffi missing."""
    if _ARGON2_AVAILABLE:
        return hash_secret_raw(
            secret=password.encode(),
            salt=salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            type=Argon2Type.ID,
        )
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)


def _aes_encrypt(data: str, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data.encode(), None)
    return _V2_MAGIC + nonce + ct


def _aes_decrypt(token: bytes, key: bytes) -> str:
    payload = token[len(_V2_MAGIC):]
    nonce, ct = payload[:12], payload[12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception:
        raise ValueError("wrong_password")


def _legacy_fernet_decrypt(token: bytes, password: str) -> str:
    salt = get_or_create_salt()
    legacy_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)
    try:
        return Fernet(base64.urlsafe_b64encode(legacy_key)).decrypt(token).decode()
    except InvalidToken:
        raise ValueError("wrong_password")


def encrypt_data(data: str, password: str) -> bytes:
    salt = get_or_create_salt()
    key = derive_key(password, salt)
    return _aes_encrypt(data, key)


def decrypt_data(token: bytes, password: str) -> str:
    """Decrypt vault. Auto-detects v2 (AES-256-GCM) vs legacy (Fernet/AES-128-CBC)."""
    if token.startswith(_V2_MAGIC):
        salt = get_or_create_salt()
        key = derive_key(password, salt)
        return _aes_decrypt(token, key)
    return _legacy_fernet_decrypt(token, password)


def team_encrypt(data: str, passphrase: str) -> bytes:
    salt = secrets.token_bytes(32)
    key = derive_key(passphrase, salt)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data.encode(), None)
    return _V2T_MAGIC + salt + nonce + ct


def team_decrypt(token: bytes, passphrase: str) -> str:
    if not token.startswith(_V2T_MAGIC):
        raise ValueError("Not a valid Pushkey team vault file")
    payload = token[len(_V2T_MAGIC):]
    salt, nonce, ct = payload[:32], payload[32:44], payload[44:]
    key = derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception:
        raise ValueError("wrong_password")


def _migrate_vault(data):
    schema = data.get("_schema", 0)
    if schema < 2:
        for key_data in data.get("keys", {}).values():
            if isinstance(key_data, dict):
                key_data.setdefault("env", "all")
        data["_schema"] = _s.VAULT_SCHEMA_VERSION
    return data


def _serialize_vault(vault):
    return {"_schema": _s.VAULT_SCHEMA_VERSION, "keys": vault}


def _deserialize_vault(data):
    if isinstance(data, dict) and isinstance(data.get("keys"), dict):
        return data["keys"]
    if isinstance(data, dict):
        return data
    return None


# ── Audit log ──────────────────────────────────────────────────────────────────

_LOG_KEY_CACHE = None


def _log_key() -> bytes:
    global _LOG_KEY_CACHE
    if _LOG_KEY_CACHE is None:
        salt = get_or_create_salt()
        _LOG_KEY_CACHE = hashlib.pbkdf2_hmac("sha256", b"pushkey-log-key", salt, iterations=100_000)
    return _LOG_KEY_CACHE


def _log_encrypt(text: str) -> bytes:
    key = _log_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, text.encode(), None)
    payload = nonce + ct
    return len(payload).to_bytes(4, "big") + payload


def _log_decrypt_all() -> list[str]:
    lines = []
    if not _s.LOG_FILE.exists():
        return lines
    raw = _s.LOG_FILE.read_bytes()
    if raw and raw[0:1] == b"[":
        return raw.decode("utf-8", errors="replace").splitlines()
    key = _log_key()
    pos = 0
    while pos + 4 <= len(raw):
        length = int.from_bytes(raw[pos:pos+4], "big")
        pos += 4
        if pos + length > len(raw):
            break
        payload = raw[pos:pos+length]
        pos += length
        try:
            nonce, ct = payload[:12], payload[12:]
            lines.append(AESGCM(key).decrypt(nonce, ct, None).decode())
        except Exception:
            lines.append("[corrupted entry]")
    return lines


def _log_line_age_days(line: str) -> float:
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
    if not m:
        return float("inf")
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 86400
    except ValueError:
        return float("inf")


def _migrate_plaintext_log() -> None:
    """Convert legacy plaintext log to encrypted binary format."""
    if not _s.LOG_FILE.exists():
        return
    raw = _s.LOG_FILE.read_bytes()
    if not raw or raw[0:1] != b"[":
        return
    lines = raw.decode("utf-8", errors="replace").splitlines()
    encrypted_chunks = b"".join(_log_encrypt(ln) for ln in lines if ln.strip())
    _s.LOG_FILE.write_bytes(encrypted_chunks)


def log_event(message: str) -> None:
    try:
        _s.ensure_vault_dir()
        _migrate_plaintext_log()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {message}"
        with _s.LOG_FILE.open("ab") as f:
            f.write(_log_encrypt(entry))
    except Exception:
        pass


# ── Config / MFA / FIDO2 derived key (shared across pushkey.py and pushkey_vault) ──

_CONFIG_KEY_CACHE = None


def _config_key() -> bytes:
    global _CONFIG_KEY_CACHE
    if _CONFIG_KEY_CACHE is None:
        salt = get_or_create_salt()
        _CONFIG_KEY_CACHE = hashlib.pbkdf2_hmac("sha256", b"pushkey-config-key", salt, iterations=100_000)
    return _CONFIG_KEY_CACHE

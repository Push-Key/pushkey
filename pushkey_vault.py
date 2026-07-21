"""
Pushkey — vault I/O and encrypted config.
"""
import json
import os
import secrets
import shutil
import threading
import tempfile
from contextlib import contextmanager
from datetime import datetime

import pushkey_shared as _s
from pushkey_crypto import (
    AESGCM,
    _V2_MAGIC,
    _V3_MAGIC,
    _config_key,
    _deserialize_vault,
    _migrate_vault,
    _serialize_vault,
    decrypt_data,
    decrypt_data_v3,
    encrypt_data,
    encrypt_data_v3,
    derive_key,
    log_event,
    rekey_vault,
    VaultAuthenticationError,
    VaultFormatError,
    VaultIntegrityError,
    VaultUnsupportedKDFError,
)

MAX_VAULT_BYTES = 16 * 1024 * 1024
MAX_VAULT_RECORDS = 10_000
MAX_VAULT_STRING_BYTES = 1 * 1024 * 1024
_VAULT_WRITE_LOCK = threading.RLock()


class VaultData(dict):
    """Dictionary-compatible vault carrying an optimistic file revision."""

    _pushkey_revision = None


class VaultConflictError(RuntimeError):
    """The vault changed after this in-memory object was loaded."""


class VaultBusyError(RuntimeError):
    """The operating-system vault lock could not be acquired."""


@contextmanager
def _cross_process_lock():
    _s.ensure_vault_dir()
    lock_path = _s.VAULT_DIR / ".vault.lock"
    handle = lock_path.open("a+b")
    try:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise VaultBusyError("vault_lock_failed") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read_vault_bytes() -> bytes:
    try:
        size = _s.VAULT_FILE.stat().st_size
    except FileNotFoundError:
        return b""
    if size > MAX_VAULT_BYTES:
        raise VaultFormatError("vault_too_large")
    if size == 0:
        raise VaultFormatError("empty_vault")
    with _s.VAULT_FILE.open("rb") as handle:
        raw = handle.read(MAX_VAULT_BYTES + 1)
    if len(raw) > MAX_VAULT_BYTES:
        raise VaultFormatError("vault_too_large")
    return raw


def _validate_vault_schema(decoded) -> dict:
    if isinstance(decoded, dict):
        schema = decoded.get("_schema")
        if isinstance(schema, int) and schema > _s.VAULT_SCHEMA_VERSION:
            raise VaultFormatError("future_vault_schema")
    vault = _deserialize_vault(decoded)
    if not isinstance(vault, dict):
        raise VaultIntegrityError("invalid_vault_schema")
    if len(vault) > MAX_VAULT_RECORDS:
        raise VaultIntegrityError("too_many_vault_records")
    for name, metadata in vault.items():
        if not isinstance(name, str) or not isinstance(metadata, dict):
            raise VaultIntegrityError("invalid_vault_record")
        if len(name.encode("utf-8")) > MAX_VAULT_STRING_BYTES:
            raise VaultIntegrityError("vault_string_too_large")
        if (
            not name.startswith("_")
            and not isinstance(metadata.get("value", metadata.get("current")), str)
        ):
            raise VaultIntegrityError("vault_value_required")
        projects = metadata.get("projects", [])
        if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
            raise VaultIntegrityError("invalid_projects")
        if len(projects) > 10_000:
            raise VaultIntegrityError("too_many_projects")

        def validate_value(value, depth=0):
            if depth > 8:
                raise VaultIntegrityError("metadata_too_deep")
            if isinstance(value, str):
                if len(value.encode("utf-8")) > MAX_VAULT_STRING_BYTES:
                    raise VaultIntegrityError("vault_string_too_large")
            elif isinstance(value, list):
                if len(value) > 10_000:
                    raise VaultIntegrityError("metadata_list_too_large")
                for item in value:
                    validate_value(item, depth + 1)
            elif isinstance(value, dict):
                if len(value) > 1_000:
                    raise VaultIntegrityError("metadata_object_too_large")
                for nested_key, nested_value in value.items():
                    if not isinstance(nested_key, str):
                        raise VaultIntegrityError("invalid_metadata_key")
                    validate_value(nested_value, depth + 1)
            elif not isinstance(value, (int, float, bool, type(None))):
                raise VaultIntegrityError("invalid_metadata_value")

        for key, value in metadata.items():
            if not isinstance(key, str):
                raise VaultIntegrityError("invalid_metadata_key")
            validate_value(value)
    return vault


def _validate_encrypted_vault(raw: bytes, password: str) -> None:
    if len(raw) > MAX_VAULT_BYTES:
        raise VaultFormatError("vault_too_large")
    if raw.startswith(_V3_MAGIC):
        plaintext, _ = decrypt_data_v3(raw, password=password)
    elif raw.startswith(_V2_MAGIC):
        plaintext = decrypt_data(raw, password)
    else:
        raise VaultFormatError("unsupported_vault_format")
    try:
        decoded = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VaultIntegrityError("invalid_vault_json") from exc
    _validate_vault_schema(decoded)


def _fsync_parent(path) -> None:
    """Persist a directory entry where the platform supports directory fsync."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(str(path), flags)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _create_rolling_backup(raw: bytes) -> None:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = _s.VAULT_DIR / f"vault_backup_{ts}.enc"
    with backup.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
    _fsync_parent(_s.VAULT_DIR)


def _prune_rolling_backups() -> None:
    backups = sorted(
        _s.VAULT_DIR.glob("vault_backup_*.enc"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[3:]:
        old.unlink(missing_ok=True)


def _create_migration_backup(raw: bytes):
    """Persist the exact pre-migration vault bytes and return the backup path."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = _s.VAULT_DIR / f"vault_migration_backup_{ts}.enc"
    with backup.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
    _fsync_parent(_s.VAULT_DIR)
    return backup


def migrate_vault_to_v3(password: str, recovery_code: str):
    """Migrate a legacy/V2 vault to V3 while retaining its exact source bytes."""
    with _VAULT_WRITE_LOCK:
        raw = _read_vault_bytes()
        if not raw:
            raise VaultFormatError("vault_missing")
        if raw.startswith(_V3_MAGIC):
            raise VaultFormatError("already_v3")
        vault, _ = load_vault(password)
        if vault is None:
            raise VaultAuthenticationError("wrong_password")
        backup = _create_migration_backup(raw)
        try:
            save_vault(vault, password, recovery_code=recovery_code)
        except Exception:
            # The migration backup remains intentionally: it is the recovery
            # artifact for any failure during the migration attempt.
            raise
        return backup


def replace_v3_recovery_code(password: str, recovery_code: str, *, expected_revision=None) -> None:
    """Replace a V3 recovery slot after authenticating the current password."""
    raw = _read_vault_bytes()
    if not raw.startswith(_V3_MAGIC):
        raise VaultFormatError("not_v3")
    if expected_revision is not None:
        import hashlib
        if not secrets.compare_digest(hashlib.sha256(raw).digest(), expected_revision):
            raise VaultConflictError("stale_vault_revision")
    vault, _ = load_vault(password)
    if vault is None:
        raise VaultAuthenticationError("wrong_password")
    save_vault(vault, password, recovery_code=recovery_code)


def rekey_v3_password(recovery_code: str, new_password: str) -> None:
    """Atomically replace only the password slot, validating both unlock paths."""
    with _VAULT_WRITE_LOCK, _cross_process_lock():
        existing = _read_vault_bytes()
        if not existing.startswith(_V3_MAGIC):
            raise VaultFormatError("not_v3")
        _, expected_key = decrypt_data_v3(existing, recovery_code=recovery_code)
        replacement = rekey_vault(existing, recovery_code, new_password)
        _, password_key = decrypt_data_v3(replacement, password=new_password)
        _, recovery_key = decrypt_data_v3(replacement, recovery_code=recovery_code)
        if not (
            secrets.compare_digest(expected_key, password_key)
            and secrets.compare_digest(expected_key, recovery_key)
        ):
            raise VaultIntegrityError("rekey_validation_failed")
        fd, tmp_name = tempfile.mkstemp(prefix=".vault.", suffix=".tmp", dir=str(_s.VAULT_DIR))
        tmp = type(_s.VAULT_FILE)(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(replacement)
                handle.flush()
                os.fsync(handle.fileno())
            _create_rolling_backup(existing)
            os.replace(str(tmp), str(_s.VAULT_FILE))
            _fsync_parent(_s.VAULT_DIR)
            _prune_rolling_backups()
        finally:
            tmp.unlink(missing_ok=True)


def load_vault(password) -> tuple:
    """Returns (vault_dict, vault_key). vault_key is None for V2/legacy vaults."""
    if not _s.VAULT_FILE.exists():
        return {}, None
    try:
        raw = _read_vault_bytes()
        if raw.startswith(_V3_MAGIC):
            plaintext, vault_key = decrypt_data_v3(raw, password=password)
            try:
                data = json.loads(plaintext)
            except json.JSONDecodeError as exc:
                raise VaultIntegrityError("invalid_vault_json") from exc
        else:
            is_legacy = not raw.startswith(_V2_MAGIC)
            plaintext = decrypt_data(raw, password)
            try:
                data = json.loads(plaintext)
            except json.JSONDecodeError as exc:
                raise VaultIntegrityError("invalid_vault_json") from exc
            vault_key = None
            if is_legacy:
                log_event("vault upgraded to AES-256-GCM + Argon2id")
        _validate_vault_schema(data)
        data = _migrate_vault(data)
        vault = _validate_vault_schema(data)
        import hashlib
        vault = VaultData(vault)
        vault._pushkey_revision = hashlib.sha256(raw).digest()
        return vault, vault_key
    except VaultAuthenticationError:
        return None, None
    except (VaultFormatError, VaultIntegrityError, VaultUnsupportedKDFError):
        raise
    except Exception as e:
        raise VaultIntegrityError(f"corrupted:{e}") from e


def load_vault_with_key(vault_key: bytes) -> tuple:
    """
    Load vault using a raw vault key (agent token auth path — no master password needed).

    V2 format: _V2_MAGIC(4) + nonce(12) + ct
    V3 format: _V3_MAGIC(4) + header(184) + body_nonce(12) + body_ct(...)
    """
    if not _s.VAULT_FILE.exists():
        return {}, vault_key
    try:
        raw = _read_vault_bytes()
        if raw.startswith(_V3_MAGIC):
            # body starts after: magic(4)+salt(32)+rec_salt(32)+pw_nonce(12)+pw_ct(48)+rec_nonce(12)+rec_ct(48) = 188
            payload = raw[4:]
            body_nonce = payload[184:196]
            body_ct = payload[196:]
            plaintext = AESGCM(vault_key).decrypt(body_nonce, body_ct, None)
        elif raw.startswith(_V2_MAGIC):
            nonce = raw[4:16]
            ct = raw[16:]
            plaintext = AESGCM(vault_key).decrypt(nonce, ct, None)
        else:
            return None, None
        data = _migrate_vault(json.loads(plaintext))
        vault = VaultData(_validate_vault_schema(data))
        import hashlib
        vault._pushkey_revision = hashlib.sha256(raw).digest()
        return vault, vault_key
    except Exception:
        return None, None


def save_vault(vault, password, *, vault_key=None, recovery_code=None, expected_revision=None):
    """Save vault. For V3: pass vault_key (preserve existing key) or recovery_code (create new V3)."""
    with _VAULT_WRITE_LOCK, _cross_process_lock():
        _s.ensure_vault_dir()
        existing_raw = _read_vault_bytes() if _s.VAULT_FILE.exists() else b""
        import hashlib
        expected = expected_revision or getattr(vault, "_pushkey_revision", None)
        if existing_raw and expected is None:
            raise VaultConflictError("expected_revision_required")
        if expected is not None and hashlib.sha256(existing_raw).digest() != expected:
            raise VaultConflictError("stale_vault_revision")
        if existing_raw.startswith(_V3_MAGIC) and vault_key is None and recovery_code is None:
            raise VaultFormatError("v3_save_requires_vault_key")
        payload = _serialize_vault(vault)
        _validate_vault_schema(payload)
        json_str = json.dumps(payload, indent=2)

        if recovery_code is not None:
            encrypted = encrypt_data_v3(json_str, password, recovery_code)
        elif vault_key is not None:
        # Re-encrypt V3 body preserving the existing recovery slot
            existing = existing_raw or None
            if existing and existing.startswith(_V3_MAGIC):
                _, authenticated_key = decrypt_data_v3(existing, password=password)
                if not secrets.compare_digest(authenticated_key, vault_key):
                    raise VaultAuthenticationError("vault_key_mismatch")
                import secrets as _sec
                p = existing[4:]
                salt      = p[0:32]
                rec_salt  = p[32:64]
                rec_nonce = p[124:136]
                rec_ct    = p[136:184]

                pw_key = derive_key(password, salt)
                pw_nonce = _sec.token_bytes(12)
                pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

                body_nonce = _sec.token_bytes(12)
                body_ct = AESGCM(vault_key).encrypt(body_nonce, json_str.encode(), None)

                encrypted = (
                    _V3_MAGIC + salt + rec_salt
                    + pw_nonce + pw_ct
                    + rec_nonce + rec_ct
                    + body_nonce + body_ct
                )
            else:
                encrypted = encrypt_data(json_str, password)
        else:
            encrypted = encrypt_data(json_str, password)

        if len(encrypted) > MAX_VAULT_BYTES:
            raise VaultFormatError("vault_too_large")
        fd, tmp_name = tempfile.mkstemp(
            prefix=".vault.", suffix=".tmp", dir=str(_s.VAULT_DIR)
        )
        os.close(fd)
        tmp = type(_s.VAULT_FILE)(tmp_name)
        try:
            with tmp.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            written = tmp.read_bytes()
            _validate_encrypted_vault(written, password)
            if vault_key is not None and written.startswith(_V3_MAGIC):
                _, verified_key = decrypt_data_v3(written, password=password)
                if not secrets.compare_digest(verified_key, vault_key):
                    raise VaultIntegrityError("post_write_key_mismatch")
            if existing_raw:
                _create_rolling_backup(existing_raw)
            os.replace(str(tmp), str(_s.VAULT_FILE))
            _fsync_parent(_s.VAULT_DIR)
            _prune_rolling_backups()
            if isinstance(vault, VaultData):
                vault._pushkey_revision = hashlib.sha256(written).digest()
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def save_vault_with_key(vault, vault_key: bytes, *, expected_revision=None):
    """Update only a V3 body using an authenticated raw vault key."""
    with _VAULT_WRITE_LOCK, _cross_process_lock():
        existing = _read_vault_bytes()
        if not existing.startswith(_V3_MAGIC):
            raise VaultFormatError("raw_key_requires_v3")
        import hashlib
        current_revision = hashlib.sha256(existing).digest()
        expected = expected_revision or getattr(vault, "_pushkey_revision", None)
        if expected is None:
            raise VaultConflictError("expected_revision_required")
        if not secrets.compare_digest(expected, current_revision):
            raise VaultConflictError("stale_vault_revision")
        loaded, _ = load_vault_with_key(vault_key)
        if loaded is None:
            raise VaultAuthenticationError("vault_key_mismatch")
        payload = _serialize_vault(vault)
        _validate_vault_schema(payload)
        body_nonce = secrets.token_bytes(12)
        body_ct = AESGCM(vault_key).encrypt(
            body_nonce, json.dumps(payload, indent=2).encode(), None
        )
        replacement = existing[:188] + body_nonce + body_ct
        # Credential slots are immutable in this path.
        if replacement[:188] != existing[:188]:
            raise VaultIntegrityError("credential_slots_changed")
        plaintext = AESGCM(vault_key).decrypt(body_nonce, body_ct, None)
        _validate_vault_schema(json.loads(plaintext))
        fd, tmp_name = tempfile.mkstemp(prefix=".vault.", suffix=".tmp", dir=str(_s.VAULT_DIR))
        tmp = type(_s.VAULT_FILE)(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(replacement)
                handle.flush()
                os.fsync(handle.fileno())
            _create_rolling_backup(existing)
            os.replace(str(tmp), str(_s.VAULT_FILE))
            _fsync_parent(_s.VAULT_DIR)
            _prune_rolling_backups()
            if isinstance(vault, VaultData):
                vault._pushkey_revision = hashlib.sha256(replacement).digest()
        finally:
            tmp.unlink(missing_ok=True)


def load_config():
    if not _s.CONFIG_FILE.exists():
        return {"projects": {}}
    raw = _s.CONFIG_FILE.read_bytes()
    if raw.lstrip()[:1] == b"{":
        try:
            data = json.loads(raw)
            save_config(data)
            return data
        except Exception:
            pass
        return {"projects": {}}
    try:
        key = _config_key()
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(plaintext)
    except Exception:
        return {"projects": {}}


def save_config(config):
    _s.ensure_vault_dir()
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(config, indent=2).encode(), None)
    tmp = _s.CONFIG_FILE.with_suffix(".tmp")
    tmp.write_bytes(nonce + ct)
    os.replace(str(tmp), str(_s.CONFIG_FILE))

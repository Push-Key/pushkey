"""Strict public health-sidecar schema and deterministic health projection."""
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pushkey_shared as _s
from pushkey_locking import FileLockTimeout, bounded_file_lock
from pushkey_vault import _current_encrypted_vault_revision, _vault_write_guard
from pushkey_providers import health_status_at


_MAX_BYTES = 1_048_576
MAX_HEALTH_BYTES = _MAX_BYTES
_MAX_AGE = timedelta(hours=26)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_MAX_KEYS = 10_000
_MAX_DAYS = 365_000
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ROOT_KEYS = {"schema_version", "generated_at", "keys"}
_RECORD_KEYS = {"status", "days_old", "provider"}
_STATUSES = {"healthy", "warning", "critical", "unknown"}


class HealthSidecarError(RuntimeError):
    pass


class HealthSchemaError(HealthSidecarError):
    pass


class HealthUnavailableError(HealthSidecarError):
    pass


class HealthPathError(HealthUnavailableError):
    """The sidecar, parent, lock, or temporary path is unsafe."""

    def __init__(self, reason="health_path_unsafe"):
        super().__init__(reason)


class HealthBusyError(HealthUnavailableError):
    """The bounded health lock could not be acquired."""

    def __init__(self, reason="health_lock_timeout"):
        super().__init__(reason)


def _is_link_or_reparse(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise HealthPathError() from exc
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_health_paths(path, *, create_parent):
    path = Path(_s.HEALTH_FILE if path is None else path)
    parent = path.parent
    if create_parent:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HealthPathError() from exc
    # This detects accidental/hostile path substitution of the paths Pushkey
    # owns: the sidecar's directory (~/.pushkey), the sidecar, and its lock.
    # Links above that directory are the operating system's or the user's
    # layout (macOS /var -> /private/var, Fedora Silverblue /home -> /var/home)
    # and are deliberately not checked; rejecting them made `pushkey init` fail
    # on those systems. A same-account attacker can still race path operations
    # on platforms without dir_fd support; that cannot be eliminated portably,
    # so checks are repeated.
    try:
        parent_is_dir = parent.is_dir()
    except OSError as exc:
        raise HealthPathError() from exc
    if not parent_is_dir or _is_link_or_reparse(parent):
        raise HealthPathError()
    lock_path = parent / ".health.lock"
    if _is_link_or_reparse(path) or _is_link_or_reparse(lock_path):
        raise HealthPathError()
    return path, lock_path


@contextmanager
def _health_lock(path):
    _, lock_path = _safe_health_paths(path, create_parent=True)
    try:
        with bounded_file_lock(lock_path):
            _safe_health_paths(path, create_parent=False)
            yield
    except FileLockTimeout as exc:
        raise HealthBusyError() from exc


def _require_current_revision(expected_vault_revision):
    if not isinstance(expected_vault_revision, bytes):
        raise HealthUnavailableError("health_vault_changed")
    current = _current_encrypted_vault_revision()
    if not secrets.compare_digest(current, expected_vault_revision):
        raise HealthUnavailableError("health_vault_changed")


def _fsync_parent(path):
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except AttributeError:
        return
    except OSError as exc:
        if exc.errno in (getattr(os, "ENOTSUP", 95), getattr(os, "EOPNOTSUPP", 95), getattr(os, "EINVAL", 22)):
            return
        raise
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _enforce_private_mode(path):
    if os.name == "nt":
        return
    os.chmod(path, 0o600)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OSError("health file mode is not 0600")


def _verify_temporary_identity(path, identity):
    try:
        info = path.lstat()
    except OSError as exc:
        raise HealthPathError() from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or (info.st_dev, info.st_ino) != (identity.st_dev, identity.st_ino)
    ):
        raise HealthPathError()


def _replace_sidecar(tmp, path):
    deadline = time.monotonic() + 1.0
    while True:
        try:
            os.replace(str(tmp), str(path))
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _canonical_timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise HealthSchemaError("timestamp must include UTC timezone")
        value = value.astimezone(timezone.utc)
        if value.microsecond:
            raise HealthSchemaError("timestamp must be whole seconds")
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise HealthSchemaError("timestamp must be UTC RFC3339 at whole seconds")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise HealthSchemaError("invalid timestamp") from exc
    return value


def _valid_name(name):
    return isinstance(name, str) and name.isascii() and bool(_NAME_RE.fullmatch(name))


def _valid_provider(value):
    return (isinstance(value, str) and value.isascii() and 1 <= len(value.encode("ascii")) <= 64
            and all(32 <= ord(char) <= 126 for char in value))


def _parse_source_date(value, now):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        if parsed > now:
            return None
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None


def build_health_document(vault, *, generated_at=None):
    now = (datetime.now(timezone.utc).replace(microsecond=0)
           if generated_at is None else _timestamp_datetime(generated_at))
    generated = _canonical_timestamp(now)
    keys = {}
    if not isinstance(vault, Mapping):
        return {"schema_version": 1, "generated_at": generated, "keys": keys}
    for name, record in vault.items():
        if len(keys) >= _MAX_KEYS:
            break
        if not _valid_name(name) or not isinstance(record, Mapping):
            continue
        primary = record.get("rotated") or record.get("created")
        primary_date = _parse_source_date(primary, now)
        first_used = record.get("first_used")
        first_used_date = _parse_source_date(first_used, now) if first_used else None
        if primary_date is None or (first_used and first_used_date is None):
            status, days_old = "unknown", None
        else:
            dates = [primary_date] + ([first_used_date] if first_used_date else [])
            days_old = min((now - date).days for date in dates)
            status = health_status_at(record, now)
        provider = record.get("provider")
        keys[name] = {"status": status, "days_old": days_old,
                      "provider": provider if _valid_provider(provider) else None}
    return {"schema_version": 1, "generated_at": generated, "keys": keys}


def _timestamp_datetime(value):
    canonical = _canonical_timestamp(value)
    return datetime.strptime(canonical, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def validate_health_document(document):
    if not isinstance(document, dict) or set(document) != _ROOT_KEYS:
        raise HealthSchemaError("document must contain exactly the v1 root fields")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise HealthSchemaError("unsupported schema version")
    if not isinstance(document["generated_at"], str):
        raise HealthSchemaError("generated_at must be a string")
    generated = _canonical_timestamp(document["generated_at"])
    keys = document["keys"]
    if not isinstance(keys, dict) or len(keys) > _MAX_KEYS:
        raise HealthSchemaError("invalid keys collection")
    normalized = {}
    for name, record in keys.items():
        if not _valid_name(name) or not isinstance(record, dict) or set(record) != _RECORD_KEYS:
            raise HealthSchemaError("invalid key record")
        status, days_old, provider = record["status"], record["days_old"], record["provider"]
        if not isinstance(status, str) or status not in _STATUSES:
            raise HealthSchemaError("invalid health status")
        if days_old is not None and (type(days_old) is not int or not 0 <= days_old <= _MAX_DAYS):
            raise HealthSchemaError("invalid days_old")
        if provider is not None and not _valid_provider(provider):
            raise HealthSchemaError("invalid provider")
        normalized[name] = {"status": status, "days_old": days_old, "provider": provider}
    return {"schema_version": 1, "generated_at": generated, "keys": normalized}


def encode_health_document(document):
    normalized = validate_health_document(document)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("utf-8") + b"\n"
    if len(raw) > _MAX_BYTES:
        raise HealthSchemaError("encoded health document exceeds maximum size")
    return raw


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HealthSchemaError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise HealthSchemaError("non-finite JSON value")


def _normalize_legacy(document, legacy_generated_at):
    if not isinstance(document, dict) or any(name in _ROOT_KEYS for name in document):
        raise HealthSchemaError("legacy document contains reserved root field")
    if len(document) > _MAX_KEYS:
        raise HealthSchemaError("legacy document has too many records")
    generated = _canonical_timestamp(legacy_generated_at)
    keys = {}
    for name, record in document.items():
        if not _valid_name(name):
            continue
        if not isinstance(record, dict):
            raise HealthSchemaError("legacy record is not an object")
        status = record.get("status")
        status = status if isinstance(status, str) and status in _STATUSES - {"unknown"} else "unknown"
        days_old = record.get("days_old")
        if type(days_old) is not int or not 0 <= days_old <= _MAX_DAYS:
            days_old = None
        provider = record.get("provider")
        keys[name] = {"status": status, "days_old": days_old,
                      "provider": provider if _valid_provider(provider) else None}
    return {"schema_version": 1, "generated_at": generated, "keys": keys}


def decode_health_document(raw, *, allow_legacy=True, legacy_generated_at=None):
    if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES:
        raise HealthSchemaError("invalid raw health document")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates,
                              parse_constant=_reject_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, HealthSchemaError) as exc:
        raise HealthSchemaError("invalid health JSON") from exc
    if not isinstance(document, dict):
        raise HealthSchemaError("health JSON root must be an object")
    if any(name in _ROOT_KEYS for name in document):
        return validate_health_document(document)
    if not allow_legacy:
        raise HealthSchemaError("legacy health documents are disabled")
    return _normalize_legacy(document, legacy_generated_at)


def _fresh_document(document, now):
    generated = _timestamp_datetime(document["generated_at"])
    if generated < now - _MAX_AGE:
        raise HealthUnavailableError("health_stale")
    if generated > now + _MAX_FUTURE_SKEW:
        raise HealthUnavailableError("health_clock_invalid")
    return document


def read_health_sidecar(path=None, *, allow_legacy=True, now=None):
    """Read one bounded public sidecar and return a normalized, fresh v1 document."""
    path, _ = _safe_health_paths(path, create_parent=False)
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_HEALTH_BYTES + 1)
            modified = datetime.fromtimestamp(
                os.fstat(handle.fileno()).st_mtime, timezone.utc
            ).replace(microsecond=0)
        if len(raw) > MAX_HEALTH_BYTES:
            raise HealthUnavailableError("health_too_large")
        document = decode_health_document(
            raw, allow_legacy=allow_legacy, legacy_generated_at=modified.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except FileNotFoundError as exc:
        raise HealthUnavailableError("health_missing") from exc
    except HealthUnavailableError:
        raise
    except (OSError, HealthSchemaError) as exc:
        raise HealthUnavailableError("health_invalid") from exc
    current = datetime.now(timezone.utc).replace(microsecond=0) if now is None else _timestamp_datetime(now)
    return _fresh_document(document, current)


def _write_all(fd, raw):
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        if written <= 0:
            raise OSError("health_write_failed")
        offset += written


def write_health_sidecar(vault, path=None, *, generated_at=None, expected_vault_revision: bytes):
    """Atomically publish a fresh strict health snapshot for one vault revision."""
    path, _ = _safe_health_paths(path, create_parent=True)
    document = build_health_document(vault, generated_at=generated_at)
    raw = encode_health_document(document)
    tmp = None
    try:
        with _vault_write_guard():
            _require_current_revision(expected_vault_revision)
            with _health_lock(path):
                _require_current_revision(expected_vault_revision)
                fd, name = tempfile.mkstemp(prefix=".health.", suffix=".tmp", dir=str(path.parent))
                tmp = Path(name)
                try:
                    _write_all(fd, raw)
                    os.fsync(fd)
                    identity = os.fstat(fd)
                finally:
                    os.close(fd)
                _enforce_private_mode(tmp)
                try:
                    _require_current_revision(expected_vault_revision)
                    _safe_health_paths(path, create_parent=False)
                    _verify_temporary_identity(tmp, identity)
                    _replace_sidecar(tmp, path)
                except OSError as exc:
                    raise HealthUnavailableError("health_replace_failed") from exc
                tmp = None
                _enforce_private_mode(path)
                try:
                    verified = read_health_sidecar(path, allow_legacy=False, now=generated_at)
                    if verified != document:
                        raise HealthUnavailableError("health_verification_failed")
                except Exception as exc:
                    if isinstance(exc, HealthUnavailableError) and str(exc) == "health_verification_failed":
                        raise
                    raise HealthUnavailableError("health_verification_failed") from exc
                _fsync_parent(path.parent)
                return verified
    except HealthUnavailableError:
        raise
    except OSError as exc:
        raise HealthUnavailableError("health_write_failed") from exc
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def publish_saved_vault(vault, *, generated_at=None):
    """Publish the public snapshot after a successful plaintext-aware save.

    Encrypted vault writes intentionally invalidate the sidecar. Callers that
    still hold the plaintext vault use this narrow hook to republish it.
    """
    revision = getattr(vault, "_pushkey_revision", None)
    if not isinstance(revision, bytes):
        raise HealthUnavailableError("health_vault_revision_missing")
    return write_health_sidecar(
        vault, generated_at=generated_at, expected_vault_revision=revision
    )


def invalidate_health_sidecar(path=None, *, expected_vault_revision: bytes):
    """Remove exactly the health sidecar for the specified current vault revision."""
    path, _ = _safe_health_paths(path, create_parent=True)
    try:
        with _vault_write_guard():
            _require_current_revision(expected_vault_revision)
            with _health_lock(path):
                _require_current_revision(expected_vault_revision)
                if path.exists():
                    if _is_link_or_reparse(path):
                        raise HealthUnavailableError("health_path_unsafe")
                    path.unlink()
                if path.exists():
                    raise HealthUnavailableError("health_verification_failed")
                _fsync_parent(path.parent)
    except HealthUnavailableError:
        raise
    except OSError as exc:
        raise HealthUnavailableError("health_write_failed") from exc


def invalidate_health_sidecar_under_vault_lock(path=None, *, expected_vault_revision: bytes):
    """Invalidate under an already-held process vault lock and `.vault.lock`."""
    path, _ = _safe_health_paths(path, create_parent=True)
    try:
        _require_current_revision(expected_vault_revision)
        with _health_lock(path):
            _require_current_revision(expected_vault_revision)
            if path.exists():
                if _is_link_or_reparse(path):
                    raise HealthPathError()
                path.unlink()
            if path.exists():
                raise HealthUnavailableError("health_verification_failed")
            _fsync_parent(path.parent)
    except HealthUnavailableError:
        raise
    except OSError as exc:
        raise HealthUnavailableError("health_write_failed") from exc

"""Strict public health-sidecar schema and deterministic health projection."""
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone

from pushkey_providers import health_status_at


_MAX_BYTES = 1_048_576
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

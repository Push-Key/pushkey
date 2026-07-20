import json
from datetime import datetime, timedelta, timezone

import pytest

from pushkey_health import (
    HealthSchemaError,
    build_health_document,
    decode_health_document,
    encode_health_document,
    validate_health_document,
)


NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


def valid_document():
    return {
        "schema_version": 1,
        "generated_at": "2026-01-10T12:00:00Z",
        "keys": {"OPENAI_API_KEY": {"status": "healthy", "days_old": 0, "provider": "OpenAI"}},
    }


def test_build_is_deterministic_and_excludes_secret_metadata():
    vault = {
        "OPENAI_API_KEY": {
            "value": "super-secret-value",
            "created": "2026-01-10T12:00:00+00:00",
            "provider": "OpenAI",
            "paths": ["C:/private"], "projects": ["hidden"], "notes": "do not publish",
            "rotated": "2026-01-10T12:00:00+00:00", "rotation_count": 4,
        },
        "1BAD": {"created": "2026-01-01T00:00:00+00:00"},
        "GOOD": "not a mapping",
    }
    document = build_health_document(vault, generated_at=NOW)
    assert document == {
        "schema_version": 1, "generated_at": "2026-01-10T12:00:00Z",
        "keys": {"OPENAI_API_KEY": {"status": "healthy", "days_old": 0, "provider": "OpenAI"}},
    }
    assert "super-secret-value" not in json.dumps(document)


@pytest.mark.parametrize(("age", "provider", "expected"), [
    (60, None, "healthy"), (61, None, "warning"), (91, None, "critical"),
    (21, "HashiCorp Vault", "warning"), (31, "HashiCorp Vault", "critical"),
])
def test_build_uses_provider_thresholds_at_injected_time(age, provider, expected):
    generated = NOW
    vault = {"KEY": {"created": (generated - timedelta(days=age)).isoformat(), "provider": provider}}
    assert build_health_document(vault, generated_at=generated)["keys"]["KEY"]["status"] == expected


def test_valid_empty_document_round_trips_to_canonical_json():
    document = {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {}}
    assert decode_health_document(encode_health_document(document)) == document
    assert encode_health_document(document) == b'{"generated_at":"2026-01-10T12:00:00Z","keys":{},"schema_version":1}\n'


@pytest.mark.parametrize("generated_at", [NOW, None, 0])
def test_v1_generated_at_must_be_a_string(generated_at):
    document = valid_document()
    document["generated_at"] = generated_at
    with pytest.raises(HealthSchemaError):
        validate_health_document(document)


@pytest.mark.parametrize("status", [[], {}])
def test_v1_unhashable_status_raises_schema_error(status):
    document = valid_document()
    document["keys"]["OPENAI_API_KEY"]["status"] = status
    with pytest.raises(HealthSchemaError):
        validate_health_document(document)


@pytest.mark.parametrize("source", [None, "bad-date", float("nan"), "2026-01-10T12:00:01+00:00"])
def test_build_marks_invalid_or_future_source_dates_unknown(source):
    document = build_health_document({"KEY": {"created": source, "provider": "OpenAI"}}, generated_at=NOW)
    assert document["keys"]["KEY"] == {"status": "unknown", "days_old": None, "provider": "OpenAI"}


@pytest.mark.parametrize("document", [
    {},
    {"schema_version": 2, "generated_at": "2026-01-10T12:00:00Z", "keys": {}},
    {"schema_version": True, "generated_at": "2026-01-10T12:00:00Z", "keys": {}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00.001Z", "keys": {}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00+00:00", "keys": {}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {}, "extra": None},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": []},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"bad-name": {"status": "healthy", "days_old": 1, "provider": None}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": []}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": "bad", "days_old": 1, "provider": None}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": True, "days_old": 1, "provider": None}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": "healthy", "days_old": True, "provider": None}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": "healthy", "days_old": 365001, "provider": None}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": "healthy", "days_old": None, "provider": "bad\n"}}},
    {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": {"KEY": {"status": "healthy", "days_old": None, "provider": "x" * 65}}},
])
def test_schema_rejects_invalid_types_bounds_and_fields(document):
    with pytest.raises(HealthSchemaError):
        validate_health_document(document)


def test_schema_rejects_too_many_records():
    document = valid_document(); document["keys"] = {f"K{i}": {"status": "healthy", "days_old": 0, "provider": None} for i in range(10001)}
    with pytest.raises(HealthSchemaError): validate_health_document(document)


@pytest.mark.parametrize("raw", [
    b'{"schema_version":1,"schema_version":1,"generated_at":"2026-01-10T12:00:00Z","keys":{}}',
    b'{"schema_version":1,"generated_at":"2026-01-10T12:00:00Z","keys":{"KEY":{"status":"healthy","status":"critical","days_old":0,"provider":null}}}',
    b'[]', b'{"schema_version":1,"generated_at":"2026-01-10T12:00:00Z","keys":{},"n":NaN}',
])
def test_decode_rejects_duplicate_keys_nonobject_and_nonfinite(raw):
    with pytest.raises(HealthSchemaError): decode_health_document(raw)


def test_decode_rejects_oversize_raw_input():
    with pytest.raises(HealthSchemaError): decode_health_document(b" " * 1_048_577)


@pytest.mark.parametrize(("legacy", "expected"), [
    ({"KEY": {"status": "warning", "days_old": 12, "provider": "OpenAI", "value": "secret"}}, {"KEY": {"status": "warning", "days_old": 12, "provider": "OpenAI"}}),
    ({"KEY": {"status": "nope", "days_old": True, "provider": "bad\n"}}, {"KEY": {"status": "unknown", "days_old": None, "provider": None}}),
    ({"1BAD": {"status": "healthy", "days_old": 1, "provider": None}}, {}),
])
def test_legacy_normalizes_rows(legacy, expected):
    assert decode_health_document(json.dumps(legacy).encode(), legacy_generated_at="2026-01-10T12:00:00Z") == {"schema_version": 1, "generated_at": "2026-01-10T12:00:00Z", "keys": expected}


@pytest.mark.parametrize("raw", [b'{"schema_version": 1}', b'{"KEY": []}', b'{"generated_at": "x", "KEY": {}}'])
def test_legacy_rejects_reserved_or_nonmapping_records(raw):
    with pytest.raises(HealthSchemaError): decode_health_document(raw, legacy_generated_at="2026-01-10T12:00:00Z")


@pytest.mark.parametrize("timestamp", [None, "bad", "2026-01-10T12:00:00+00:00"])
def test_legacy_requires_canonical_generated_at(timestamp):
    with pytest.raises(HealthSchemaError): decode_health_document(b'{"KEY": {}}', legacy_generated_at=timestamp)


def test_legacy_can_be_disabled():
    with pytest.raises(HealthSchemaError):
        decode_health_document(b'{"KEY": {}}', allow_legacy=False)

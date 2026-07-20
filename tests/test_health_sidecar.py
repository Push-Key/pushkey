import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from pushkey_health import (
    HealthSchemaError,
    HealthPathError,
    HealthBusyError,
    HealthUnavailableError,
    build_health_document,
    decode_health_document,
    encode_health_document,
    validate_health_document,
    read_health_sidecar,
    write_health_sidecar,
    invalidate_health_sidecar,
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


def test_read_health_sidecar_reads_v1_and_normalizes_legacy(tmp_path):
    path = tmp_path / "health.json"
    path.write_bytes(encode_health_document(valid_document()))
    assert read_health_sidecar(path, now=NOW) == valid_document()
    path.write_text('{"KEY":{"status":"warning","days_old":2,"provider":"OpenAI"}}')
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0)
    assert read_health_sidecar(path, now=stamp + timedelta(hours=1))["generated_at"] == stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize("contents, reason", [
    pytest.param(b"x" * (1_048_577), "health_too_large", id="oversize"),
    pytest.param(b"not json", "health_invalid", id="invalid-json"),
])
def test_read_health_sidecar_bounds_and_normalizes_failures(tmp_path, contents, reason):
    path = tmp_path / "health.json"
    path.write_bytes(contents)
    with pytest.raises(HealthUnavailableError, match=reason):
        read_health_sidecar(path, now=NOW)


@pytest.mark.parametrize("timestamp, reason", [
    (NOW - timedelta(hours=27), "health_stale"),
    (NOW + timedelta(minutes=6), "health_clock_invalid"),
])
def test_read_health_sidecar_enforces_freshness(tmp_path, timestamp, reason):
    path = tmp_path / "health.json"
    document = valid_document(); document["generated_at"] = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_bytes(encode_health_document(document))
    with pytest.raises(HealthUnavailableError, match=reason):
        read_health_sidecar(path, now=NOW)


def test_write_health_sidecar_is_atomic_and_strict(tmp_path):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    document = write_health_sidecar({"KEY": {"created": NOW.isoformat()}}, path, generated_at=NOW, expected_vault_revision=revision)
    assert document == read_health_sidecar(path, now=NOW)
    assert not list(tmp_path.glob(".health.*.tmp"))
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["write", "fsync", "replace", "verify"])
def test_write_failures_preserve_prior_snapshot(tmp_path, monkeypatch, failure):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    original = encode_health_document(valid_document()); path.write_bytes(original)
    if failure == "write":
        monkeypatch.setattr(pushkey_health.os, "write", lambda *args: (_ for _ in ()).throw(OSError("write")))
    elif failure == "fsync":
        monkeypatch.setattr(pushkey_health.os, "fsync", lambda *args: (_ for _ in ()).throw(OSError("fsync")))
    elif failure == "replace":
        monkeypatch.setattr(pushkey_health.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replace")))
    else:
        monkeypatch.setattr(pushkey_health, "read_health_sidecar", lambda *args, **kwargs: (_ for _ in ()).throw(HealthUnavailableError("bad")))
    with pytest.raises(HealthUnavailableError):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    if failure != "verify":
        assert path.read_bytes() == original
    assert not list(tmp_path.glob(".health.*.tmp"))


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
@pytest.mark.parametrize("kind", ["destination", "parent", "lock"])
def test_health_paths_reject_symlinks(tmp_path, kind):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    external = tmp_path / "external"; external.write_text("unchanged")
    path = tmp_path / "health.json"
    try:
        if kind == "destination":
            path.symlink_to(external)
        elif kind == "parent":
            parent = tmp_path / "linked"; parent.symlink_to(tmp_path, target_is_directory=True); path = parent / "health.json"
        else:
            (tmp_path / ".health.lock").symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc.winerror if hasattr(exc, 'winerror') else exc}")
    with pytest.raises(HealthUnavailableError, match="health_path_unsafe"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    assert external.read_text() == "unchanged"


def test_revision_mismatch_prevents_write_and_invalidation(tmp_path):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"new encrypted vault")
    stale = hashlib.sha256(b"old encrypted vault").digest()
    path = tmp_path / "health.json"; path.write_bytes(encode_health_document(valid_document()))
    with pytest.raises(HealthUnavailableError, match="health_vault_changed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=stale)
    with pytest.raises(HealthUnavailableError, match="health_vault_changed"):
        invalidate_health_sidecar(path, expected_vault_revision=stale)
    assert path.exists()


def test_revision_change_after_health_lock_aborts_publication(tmp_path, monkeypatch):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"old encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"

    @contextmanager
    def replace_vault_after_lock(_path):
        shared.VAULT_FILE.write_bytes(b"new encrypted vault")
        yield

    monkeypatch.setattr(pushkey_health, "_health_lock", replace_vault_after_lock)
    with pytest.raises(HealthUnavailableError, match="health_vault_changed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    assert not path.exists()


def test_two_process_publishers_leave_a_complete_document(tmp_path):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).hexdigest()
    path = tmp_path / "health.json"
    ready = tmp_path / "ready"
    ready.mkdir()
    start = tmp_path / "start"
    source = "\n".join([
        "import sys, time",
        "import pushkey_shared as s",
        "from pathlib import Path",
        "from pushkey_health import write_health_sidecar",
        "s.VAULT_DIR = Path(sys.argv[1])",
        "s.VAULT_FILE = s.VAULT_DIR / 'vault.enc'",
        "Path(sys.argv[4]).touch()",
        "while not Path(sys.argv[5]).exists():",
        "    time.sleep(0.005)",
        "write_health_sidecar({'KEY': {'created': '2026-01-10T12:00:00+00:00'}}, Path(sys.argv[2]),",
        "    generated_at='2026-01-10T12:00:00Z', expected_vault_revision=bytes.fromhex(sys.argv[3]))",
    ])
    commands = [[sys.executable, "-c", source, str(tmp_path), str(path), revision, str(ready / str(index)), str(start)] for index in range(2)]
    processes = [subprocess.Popen(command, cwd=os.getcwd()) for command in commands]
    deadline = time.monotonic() + 10
    while len(list(ready.glob("*"))) != 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(list(ready.glob("*"))) == 2
    start.touch()
    while any(process.poll() is None for process in processes):
        if path.exists():
            assert read_health_sidecar(path, now=NOW)["schema_version"] == 1
        time.sleep(0.005)
    assert [process.wait(timeout=20) for process in processes] == [0, 0]
    assert read_health_sidecar(path, now=NOW)["keys"]["KEY"]["status"] == "healthy"


def test_invalidate_removes_only_sidecar(tmp_path):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"; path.write_bytes(encode_health_document(valid_document()))
    other = tmp_path / "other"; other.write_text("keep")
    invalidate_health_sidecar(path, expected_vault_revision=revision)
    assert not path.exists()
    assert other.read_text() == "keep"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_final_sidecar_permissions_and_parent_fsync_are_required(tmp_path, monkeypatch):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    monkeypatch.setattr(pushkey_health, "_fsync_parent", lambda _path: (_ for _ in ()).throw(OSError("dir fsync")))
    with pytest.raises(HealthUnavailableError, match="health_write_failed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_final_sidecar_mode_failure_aborts_publication(tmp_path, monkeypatch):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    real_chmod = pushkey_health.os.chmod

    def fail_final_chmod(target, mode):
        if os.fspath(target) == os.fspath(path):
            raise OSError("final chmod")
        real_chmod(target, mode)

    monkeypatch.setattr(pushkey_health.os, "chmod", fail_final_chmod)
    with pytest.raises(HealthUnavailableError, match="health_write_failed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)


def test_path_inspection_failure_uses_typed_path_error(tmp_path, monkeypatch):
    import pushkey_health
    monkeypatch.setattr(pushkey_health.Path, "lstat", lambda _self: (_ for _ in ()).throw(OSError("no stat")))
    with pytest.raises(HealthPathError, match="health_path_unsafe"):
        read_health_sidecar(tmp_path / "health.json", now=NOW)


def test_health_lock_timeout_uses_typed_busy_error(tmp_path, monkeypatch):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    from pushkey_locking import FileLockTimeout
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    monkeypatch.setattr(pushkey_health, "bounded_file_lock", lambda _path: (_ for _ in ()).throw(FileLockTimeout()))
    with pytest.raises(HealthBusyError, match="health_lock_timeout"):
        write_health_sidecar({}, tmp_path / "health.json", generated_at=NOW, expected_vault_revision=revision)

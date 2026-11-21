import json
import os
import subprocess
import sys
import http.client
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import pushkey_providers
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
    publish_saved_vault,
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


def test_publish_saved_vault_requires_current_revision_and_writes_v1(tmp_path, monkeypatch):
    import pushkey_shared as shared
    from pushkey_vault import load_vault, save_vault
    monkeypatch.setattr(shared, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(shared, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(shared, "HEALTH_FILE", tmp_path / "health.json")
    shared.ensure_vault_dir()
    save_vault({"KEY": {"value": "secret", "created": NOW.isoformat()}}, "password")
    vault, _ = load_vault("password")
    document = publish_saved_vault(vault, generated_at=NOW)
    assert document["schema_version"] == 1
    assert document["keys"]["KEY"] == {"status": "healthy", "days_old": 0, "provider": None}


def test_loopback_health_server_serves_canonical_v1_or_sanitized_503(tmp_path, monkeypatch):
    import pushkey
    path = tmp_path / "health.json"
    monkeypatch.setattr(pushkey, "HEALTH_FILE", path)
    server = pushkey._start_health_server(0)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 503
        assert response.read() == b'{"error":"health_unavailable"}\n'
        assert response.getheader("Content-Type") == "application/json; charset=utf-8"
        assert response.getheader("Cache-Control") == "no-store"
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("Content-Length") == str(len(b'{"error":"health_unavailable"}\n'))
        assert response.getheader("Access-Control-Allow-Origin") is None
        conn.close()
        fresh = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "keys": {},
        }
        path.write_bytes(encode_health_document(fresh))
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 200
        body = response.read()
        assert body == encode_health_document(fresh)
        assert response.getheader("Content-Length") == str(len(body))
        conn.close()

        invalid_documents = [
            b"not-json",
            encode_health_document({**fresh, "generated_at": (datetime.now(timezone.utc) - timedelta(hours=27)).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")}),
            encode_health_document({**fresh, "generated_at": (datetime.now(timezone.utc) + timedelta(minutes=6)).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")}),
            b"x" * (1024 * 1024 + 1),
        ]
        for invalid in invalid_documents:
            path.write_bytes(invalid)
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request("GET", "/health")
            response = conn.getresponse()
            assert response.status == 503
            assert response.read() == b'{"error":"health_unavailable"}\n'
            conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request("POST", "/health")
        response = conn.getresponse()
        assert response.status == 405
        assert response.getheader("Allow") == "GET"
        assert response.read() == b""
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


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


def test_build_reads_a_naive_stamp_as_local_time_east_of_utc(monkeypatch):
    zone = timezone(timedelta(hours=10))
    monkeypatch.setattr(pushkey_providers, "LOCAL_TZ", zone)
    rotated = NOW.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S")  # what every writer stamps
    assert rotated == "2026-01-10T22:00:00"
    record = build_health_document({"KEY": {"rotated": rotated}}, generated_at=NOW)["keys"]["KEY"]
    assert record["status"] != "unknown"
    assert record["days_old"] == 0


def test_build_reads_a_date_only_stamp_as_local_date_east_of_utc(monkeypatch):
    monkeypatch.setattr(pushkey_providers, "LOCAL_TZ", timezone(timedelta(hours=10)))
    generated = datetime(2026, 1, 9, 22, 0, 0, tzinfo=timezone.utc)  # 08:00 on 2026-01-10 locally
    record = build_health_document({"KEY": {"created": "2026-01-10"}}, generated_at=generated)["keys"]["KEY"]
    assert record["status"] != "unknown"
    assert record["days_old"] == 0


def test_build_reads_a_naive_stamp_as_local_time_west_of_utc(monkeypatch):
    zone = timezone(timedelta(hours=-8))
    monkeypatch.setattr(pushkey_providers, "LOCAL_TZ", zone)
    true_age = timedelta(days=60, hours=20)  # under the 60.3 day warning line; 61 days when misread as UTC
    created = (NOW - true_age).astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S")
    assert created == "2025-11-10T08:00:00"
    record = build_health_document({"KEY": {"created": created, "provider": None}}, generated_at=NOW)["keys"]["KEY"]
    assert record["status"] == "healthy"
    assert record["days_old"] == 60


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


def _link_directory(link, target):
    """Directory link: a junction on Windows (needs no privilege), a symlink elsewhere."""
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, check=False,
        )
        if created.returncode:
            pytest.skip("Windows junction creation is unavailable in this environment")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")


def test_health_paths_allow_a_linked_ancestor_above_the_pushkey_directory(tmp_path):
    # OS-level links above ~/.pushkey (macOS /var -> /private/var, Fedora Silverblue
    # /home -> /var/home) must not block publication or invalidation. Links at the
    # Pushkey directory, the sidecar, or its lock are still rejected (tests above).
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    real_home = tmp_path / "real-home"
    (real_home / ".pushkey").mkdir(parents=True)
    linked_home = tmp_path / "linked-home"
    _link_directory(linked_home, real_home)
    path = linked_home / ".pushkey" / "health.json"

    written, rejected = None, None
    try:
        written = write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    except HealthPathError as exc:
        rejected = exc
    assert rejected is None, f"a link above the Pushkey directory was rejected: {rejected}"

    assert written["schema_version"] == 1
    assert (real_home / ".pushkey" / "health.json").exists()
    invalidate_health_sidecar(path, expected_vault_revision=revision)
    assert not path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are reparse points")
@pytest.mark.parametrize("kind", ["destination", "lock"])
def test_health_paths_reject_windows_junction_destination_and_lock(tmp_path, kind):
    # Symlinks need a privilege on Windows (so the symlink cases above skip there,
    # including on the Windows CI runner); junctions do not, and are reparse points.
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    target = tmp_path / "elsewhere"; target.mkdir()
    path = tmp_path / "health.json"
    _link_directory(path if kind == "destination" else tmp_path / ".health.lock", target)

    error = None
    try:
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    except HealthUnavailableError as exc:
        error = exc
    # The path guard must refuse it up front, not a later step failing on the link.
    assert str(error) == "health_path_unsafe", f"a junction at the {kind} path was not refused by the guard: {error!r}"
    assert list(target.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are reparse points")
def test_health_paths_reject_windows_junction_parent(tmp_path):
    import hashlib
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    target = tmp_path / "target"; target.mkdir()
    junction = tmp_path / "junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True, text=True, check=False,
    )
    if created.returncode:
        pytest.skip("Windows junction creation is unavailable in this environment")
    with pytest.raises(HealthPathError, match="health_path_unsafe"):
        write_health_sidecar({}, junction / "health.json", generated_at=NOW, expected_vault_revision=revision)
    assert not (target / "health.json").exists()


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
        # ensure_vault_dir() also creates IMPORT_DIR; leaving it at the default
        # would write into the real ~/.pushkey (and fail where it does not exist).
        "s.IMPORT_DIR = s.VAULT_DIR / 'import'",
        "Path(sys.argv[4]).touch()",
        "while not Path(sys.argv[5]).exists():",
        "    time.sleep(0.005)",
        "write_health_sidecar({'KEY': {'created': '2026-01-10T12:00:00+00:00'}}, Path(sys.argv[2]),",
        "    generated_at='2026-01-10T12:00:00Z', expected_vault_revision=bytes.fromhex(sys.argv[3]))",
    ])
    commands = [[sys.executable, "-c", source, str(tmp_path), str(path), revision, str(ready / str(index)), str(start)] for index in range(2)]
    processes = [subprocess.Popen(command, cwd=os.getcwd(), stderr=subprocess.PIPE, text=True) for command in commands]
    try:
        deadline = time.monotonic() + 10
        while len(list(ready.glob("*"))) != 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(ready.glob("*"))) == 2
        start.touch()
        while any(process.poll() is None for process in processes):
            if path.exists():
                assert read_health_sidecar(path, now=NOW)["schema_version"] == 1
            time.sleep(0.005)
        diagnostics = [process.stderr.read() if process.stderr else "" for process in processes]
        assert [process.wait(timeout=20) for process in processes] == [0, 0], diagnostics
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_temporary_mode_enforcement_failure_preserves_snapshot(tmp_path, monkeypatch):
    import hashlib
    import pushkey_health
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    original = encode_health_document(valid_document()); path.write_bytes(original)
    monkeypatch.setattr(pushkey_health, "_enforce_private_mode", lambda _path: (_ for _ in ()).throw(OSError("temp chmod")))
    with pytest.raises(HealthUnavailableError, match="health_write_failed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".health.*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_health_lock_mode_enforcement_failure_preserves_snapshot(tmp_path, monkeypatch):
    import hashlib
    import pushkey_locking
    import pushkey_shared as shared
    shared.VAULT_FILE.write_bytes(b"encrypted vault")
    revision = hashlib.sha256(shared.VAULT_FILE.read_bytes()).digest()
    path = tmp_path / "health.json"
    original = encode_health_document(valid_document()); path.write_bytes(original)
    monkeypatch.setattr(pushkey_locking, "_enforce_private_mode", lambda _path: (_ for _ in ()).throw(OSError("lock chmod")))
    with pytest.raises(HealthUnavailableError, match="health_write_failed"):
        write_health_sidecar({}, path, generated_at=NOW, expected_vault_revision=revision)
    assert path.read_bytes() == original


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

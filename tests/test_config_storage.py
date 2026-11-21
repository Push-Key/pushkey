"""Encrypted config storage must round-trip whatever the random nonce looks like.

It must also refuse to write over a config file it could not read, and serialise
its writers, so a damaged file or two racing saves can never wipe projects.
"""
import errno
import inspect
import json
import os
import random
import threading
import time
from pathlib import Path

import pytest

import pushkey_shared
import pushkey_vault
from pushkey_locking import FileLockTimeout


CONFIG = {"projects": {"C:/work/proj": {"name": "proj", "created": "2026-11-21"}}}


@pytest.mark.parametrize("prefix", [b"{", b" {", b"\n{"])
def test_encrypted_config_survives_a_nonce_that_looks_like_json(monkeypatch, prefix):
    # The 12-byte AES-GCM nonce is random, so roughly 1 save in 250 starts with
    # "{" (optionally after whitespace). load_config must still decrypt it rather
    # than mistake it for a legacy plaintext file and report no projects.
    real_token_bytes = pushkey_vault.secrets.token_bytes
    # A scoped context: monkeypatch.undo() would also undo conftest's path
    # isolation and point CONFIG_FILE back at the real ~/.pushkey.
    with monkeypatch.context() as patch:
        patch.setattr(
            pushkey_vault.secrets, "token_bytes", lambda n: (prefix + real_token_bytes(n))[:n]
        )
        pushkey_vault.save_config(CONFIG)
    assert pushkey_shared.CONFIG_FILE.read_bytes().lstrip()[:1] == b"{"  # the trap is armed

    assert pushkey_vault.load_config() == CONFIG


def test_legacy_plaintext_config_still_loads_and_is_re_encrypted():
    pushkey_shared.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(CONFIG).encode()
    pushkey_shared.CONFIG_FILE.write_bytes(original)

    assert pushkey_vault.load_config() == CONFIG

    migrated = pushkey_shared.CONFIG_FILE.read_bytes()
    assert migrated != original
    with pytest.raises(ValueError):
        json.loads(migrated)
    assert pushkey_vault.load_config() == CONFIG


# 40 seeded pseudo-random bytes: neither a valid ciphertext nor JSON.
GARBAGE = bytes(random.Random(20261121).getrandbits(8) for _ in range(40))
assert GARBAGE.lstrip()[:1] != b"{"


def _api(name):
    """Resolve a new pushkey_vault name; fail on a plain assert while it is missing."""
    obj = getattr(pushkey_vault, name, None)
    assert obj is not None, f"pushkey_vault.{name} does not exist yet"
    return obj


def _strict_loading_exists():
    parameters = inspect.signature(pushkey_vault.load_config).parameters
    assert "strict" in parameters, "load_config has no strict parameter yet"


def _write_raw(data):
    pushkey_shared.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    pushkey_shared.CONFIG_FILE.write_bytes(data)


def _leftover_temp_files():
    return sorted(p.name for p in pushkey_shared.CONFIG_FILE.parent.glob("config*.tmp"))


def _catch(fn, *args, **kwargs):
    """Return what fn raised (or None). Lets a missing raise fail on a plain assert."""
    try:
        fn(*args, **kwargs)
    except BaseException as exc:
        return exc
    return None


def _run_in_thread(fn):
    outcome = {}

    def target():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # reported to the asserting thread
            outcome["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=15)
    assert not thread.is_alive(), "worker thread hung"
    return outcome


# -- strict loading ----------------------------------------------------------


def test_strict_load_raises_on_garbage():
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    _write_raw(GARBAGE)

    caught = _catch(pushkey_vault.load_config, strict=True)
    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    # Every existing caller keeps the old, lenient behaviour.
    assert pushkey_vault.load_config() == {"projects": {}}
    assert pushkey_shared.CONFIG_FILE.read_bytes() == GARBAGE


def test_strict_load_of_a_missing_file_is_an_empty_registry():
    _strict_loading_exists()
    assert not pushkey_shared.CONFIG_FILE.exists()

    assert pushkey_vault.load_config(strict=True) == {"projects": {}}
    assert not pushkey_shared.CONFIG_FILE.exists()


@pytest.mark.parametrize(
    "raw",
    [b"", b"   ", b"{oops", b"[1, 2]", b'"text"'],
    ids=["empty", "blank", "broken-json-object", "plain-list", "plain-string"],
)
def test_strict_load_refuses_a_file_that_is_not_a_config_dict(raw):
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    _write_raw(raw)

    caught = _catch(pushkey_vault.load_config, strict=True)
    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == raw


def test_strict_load_refuses_an_encrypted_payload_that_is_not_a_dict():
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    pushkey_vault.save_config(["not", "a", "dict"])
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    caught = _catch(pushkey_vault.load_config, strict=True)
    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    # Lenient loading is unchanged for existing callers.
    assert pushkey_vault.load_config() == ["not", "a", "dict"]
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_strict_load_reads_a_legacy_plaintext_config_without_writing():
    _strict_loading_exists()
    original = json.dumps(CONFIG).encode()
    _write_raw(original)

    assert pushkey_vault.load_config(strict=True) == CONFIG

    # A strict read may run outside config_lock, so it never saves.
    assert pushkey_shared.CONFIG_FILE.read_bytes() == original
    assert _leftover_temp_files() == []


def test_update_config_re_encrypts_a_legacy_plaintext_config():
    update_config = _api("update_config")
    original = json.dumps(CONFIG).encode()
    _write_raw(original)

    update_config(lambda cfg: cfg["projects"].__setitem__("/p", {"name": "p"}))

    migrated = pushkey_shared.CONFIG_FILE.read_bytes()
    assert migrated != original
    with pytest.raises(ValueError):
        json.loads(migrated)
    reloaded = pushkey_vault.load_config(strict=True)
    assert reloaded["projects"]["/p"] == {"name": "p"}
    assert reloaded["projects"]["C:/work/proj"] == CONFIG["projects"]["C:/work/proj"]


def test_lenient_load_still_re_encrypts_a_legacy_plaintext_config():
    original = json.dumps(CONFIG).encode()
    _write_raw(original)

    assert pushkey_vault.load_config() == CONFIG

    assert pushkey_shared.CONFIG_FILE.read_bytes() != original


# -- strict loading: what counts as "missing" and what counts as a registry ---


def test_strict_load_treats_an_unreadable_path_as_unreadable_not_missing(monkeypatch):
    # Path.exists() is False for ENOTDIR, ELOOP, WinError 123 and 1921 as well as
    # for a really missing file. Only FileNotFoundError may mean "no config yet":
    # anything else must refuse, or the next save wipes a registry we could not see.
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    config_file = pushkey_shared.CONFIG_FILE
    real_exists = Path.exists
    real_read_bytes = Path.read_bytes

    def exists(self, *args, **kwargs):
        return False if self == config_file else real_exists(self, *args, **kwargs)

    def read_bytes(self):
        if self == config_file:
            raise OSError(errno.ENOTDIR, "Not a directory")
        return real_read_bytes(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", exists)
        patch.setattr(Path, "read_bytes", read_bytes)
        caught = _catch(pushkey_vault.load_config, strict=True)

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"


def test_strict_load_refuses_when_the_read_itself_fails(monkeypatch):
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()
    config_file = pushkey_shared.CONFIG_FILE
    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if self == config_file:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_read_bytes(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_bytes)
        caught = _catch(pushkey_vault.load_config, strict=True)

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_update_config_refuses_when_the_read_fails_and_writes_nothing(monkeypatch):
    error = _api("ConfigUnreadableError")
    update_config = _api("update_config")
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()
    config_file = pushkey_shared.CONFIG_FILE
    real_read_bytes = Path.read_bytes
    calls = []

    def read_bytes(self):
        if self == config_file:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_read_bytes(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_bytes)
        caught = _catch(update_config, lambda cfg: calls.append(cfg))

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert calls == []
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before
    assert _leftover_temp_files() == []


@pytest.mark.parametrize("projects", [[], None, "x", 3, ["/p"]], ids=repr)
def test_strict_load_refuses_a_projects_value_that_is_not_a_dict(projects):
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    pushkey_vault.save_config({"projects": projects, "theme": "light"})
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    caught = _catch(pushkey_vault.load_config, strict=True)

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_strict_load_refuses_a_legacy_plaintext_config_with_a_bad_projects_value():
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    original = json.dumps({"projects": [1, 2]}).encode()
    _write_raw(original)

    caught = _catch(pushkey_vault.load_config, strict=True)

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == original


def test_update_config_refuses_a_bad_projects_value_and_never_calls_mutate():
    error = _api("ConfigUnreadableError")
    update_config = _api("update_config")
    pushkey_vault.save_config({"projects": ["/p"]})
    before = pushkey_shared.CONFIG_FILE.read_bytes()
    calls = []

    caught = _catch(update_config, lambda cfg: calls.append(cfg))

    assert isinstance(caught, error), caught
    assert calls == []
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_strict_load_adds_an_empty_projects_dict_when_the_key_is_absent():
    _strict_loading_exists()
    pushkey_vault.save_config({"theme": "light"})

    assert pushkey_vault.load_config(strict=True) == {"theme": "light", "projects": {}}


def test_update_config_can_add_a_project_to_a_config_without_a_projects_key():
    update_config = _api("update_config")
    pushkey_vault.save_config({"theme": "light"})

    caught = _catch(
        update_config, lambda cfg: cfg["projects"].__setitem__("/p", {"name": "p"})
    )

    assert caught is None, caught
    reloaded = pushkey_vault.load_config(strict=True)
    assert reloaded == {"theme": "light", "projects": {"/p": {"name": "p"}}}


# -- update_config -----------------------------------------------------------


def test_update_config_keeps_other_settings():
    update_config = _api("update_config")
    pushkey_vault.save_config({"projects": {}, "theme": "light"})

    update_config(lambda c: c["projects"].__setitem__("/p", {"name": "p"}))

    reloaded = pushkey_vault.load_config()
    assert reloaded["theme"] == "light"
    assert reloaded["projects"]["/p"] == {"name": "p"}


def test_update_config_creates_the_file_and_returns_what_mutate_returns():
    update_config = _api("update_config")
    assert not pushkey_shared.CONFIG_FILE.exists()

    def mutate(cfg):
        cfg["projects"]["/p"] = {"name": "p"}
        return "added"

    assert update_config(mutate) == "added"
    assert pushkey_vault.load_config(strict=True) == {"projects": {"/p": {"name": "p"}}}


def test_registry_refuses_unreadable_config():
    error = _api("ConfigUnreadableError")
    update_config = _api("update_config")
    _write_raw(GARBAGE)
    calls = []

    def mutate(cfg):
        calls.append(cfg)
        cfg["projects"]["/p"] = {"name": "p"}

    caught = _catch(update_config, mutate)

    assert isinstance(caught, error), caught
    assert str(caught) == "config_unreadable"
    assert calls == []
    assert pushkey_shared.CONFIG_FILE.read_bytes() == GARBAGE
    assert _leftover_temp_files() == []


def test_update_config_writes_nothing_when_mutate_raises():
    update_config = _api("update_config")
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    def mutate(cfg):
        cfg["projects"].clear()
        raise RuntimeError("boom")

    caught = _catch(update_config, mutate)

    assert isinstance(caught, RuntimeError) and str(caught) == "boom", caught
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before
    assert pushkey_vault.load_config() == CONFIG
    assert update_config(lambda cfg: "lock was released") == "lock was released"


# -- config_lock -------------------------------------------------------------


def test_a_held_config_lock_makes_update_config_in_another_thread_busy(monkeypatch):
    config_lock = _api("config_lock")
    update_config = _api("update_config")
    error = _api("ConfigUnreadableError")
    monkeypatch.setattr(pushkey_vault, "_CONFIG_LOCK_TIMEOUT_SECONDS", 0.2)
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    with config_lock():
        started = time.monotonic()
        outcome = _run_in_thread(lambda: update_config(lambda cfg: cfg["projects"].clear()))
        waited = time.monotonic() - started

    assert isinstance(outcome.get("error"), error), outcome
    assert str(outcome["error"]) == "config_busy"
    # The patched 0.2 s timeout is the one honoured, not the 5 s default.
    assert waited < 2.5, waited
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before
    assert update_config(lambda cfg: "free again") == "free again"


def test_config_lock_only_relabels_its_own_acquisition_timeout():
    config_lock = _api("config_lock")

    # A FileLockTimeout raised by the body (say, a nested vault lock) is not a
    # busy config: it must reach the caller unchanged.
    def body():
        with config_lock():
            raise FileLockTimeout()

    caught = _catch(body)
    assert type(caught) is FileLockTimeout, caught


def test_update_config_inside_mutate_fails_busy_instead_of_hanging(monkeypatch):
    update_config = _api("update_config")
    error = _api("ConfigUnreadableError")
    monkeypatch.setattr(pushkey_vault, "_CONFIG_LOCK_TIMEOUT_SECONDS", 0.2)
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    def mutate(cfg):
        # The lock is not reentrant: mutate must never call update_config.
        update_config(lambda inner: None)

    started = time.monotonic()
    caught = _catch(update_config, mutate)
    waited = time.monotonic() - started

    assert isinstance(caught, error), caught
    assert str(caught) == "config_busy"
    assert waited < 2.5, waited
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_two_threads_do_not_lose_each_others_updates():
    update_config = _api("update_config")
    pushkey_vault.save_config({"projects": {}})
    errors = []

    def worker(tag):
        try:
            for i in range(20):

                def mutate(cfg, i=i):
                    time.sleep(0.001)  # widen the read-modify-write window
                    cfg["projects"][f"/{tag}/{i}"] = {"name": f"{tag}{i}"}

                update_config(mutate)
        except BaseException as exc:  # reported to the asserting thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not any(thread.is_alive() for thread in threads), "worker thread hung"
    assert errors == []
    projects = pushkey_vault.load_config(strict=True)["projects"]
    assert len(projects) == 40
    assert set(projects) == {f"/{tag}/{i}" for tag in "ab" for i in range(20)}


# -- save_config temp file ---------------------------------------------------


def _record_config_replaces(monkeypatch_context, calls):
    """Run calls() while recording every os.replace that targets config.json."""
    real_replace = os.replace
    moves = []

    def spy(src, dst):
        moves.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    with monkeypatch_context() as patch:
        patch.setattr(pushkey_vault.os, "replace", spy)
        calls()
    return [src for src, dst in moves if dst == pushkey_shared.CONFIG_FILE]


def test_save_config_writes_through_a_temp_file_next_to_config_json(monkeypatch):
    sources = _record_config_replaces(
        monkeypatch.context, lambda: pushkey_vault.save_config(CONFIG)
    )

    assert len(sources) == 1
    src = sources[0]
    assert src.parent == pushkey_shared.CONFIG_FILE.parent
    assert src.name.startswith(f"config.{os.getpid()}.")
    assert src.name.endswith(".tmp")
    assert src != pushkey_shared.CONFIG_FILE
    assert _leftover_temp_files() == []
    assert pushkey_vault.load_config() == CONFIG


def test_every_save_config_call_gets_its_own_temp_file(monkeypatch):
    # One shared name per process lets two threads of the GUI and its sync
    # daemon write, replace and unlink each other's file.
    def two_saves():
        pushkey_vault.save_config(CONFIG)
        pushkey_vault.save_config(CONFIG)

    sources = _record_config_replaces(monkeypatch.context, two_saves)

    assert len(sources) == 2
    assert sources[0].name != sources[1].name
    assert _leftover_temp_files() == []


def test_save_config_syncs_the_temp_file_before_the_replace_and_the_folder_after(monkeypatch):
    events = []
    real_fsync = os.fsync
    real_replace = os.replace
    config_dir = pushkey_shared.CONFIG_FILE.parent

    def fsync(fd):
        events.append(("fsync", os.fstat(fd).st_size))
        return real_fsync(fd)

    def replace(src, dst):
        events.append(("replace", Path(src).stat().st_size))
        return real_replace(src, dst)

    def fsync_parent(path):
        events.append(("parent", Path(path)))

    with monkeypatch.context() as patch:
        patch.setattr(pushkey_vault.os, "fsync", fsync)
        patch.setattr(pushkey_vault.os, "replace", replace)
        patch.setattr(pushkey_vault, "_fsync_parent", fsync_parent)
        pushkey_vault.save_config(CONFIG)

    # The temp file holds all its bytes when it is synced, then it replaces
    # config.json, then the folder entry is synced.
    kinds = [kind for kind, _detail in events]
    assert kinds == ["fsync", "replace", "parent"], events
    assert events[0][1] > 0
    assert events[0][1] == events[1][1]
    assert events[2][1] == config_dir
    assert pushkey_vault.load_config() == CONFIG


def test_unlocked_concurrent_saves_never_leave_config_json_missing_or_unreadable():
    # The desktop GUI thread and its cloud-sync daemon thread both call
    # save_config without update_config. A missing file is the one damage state
    # strict loading accepts as an empty registry, so it must never happen.
    # PermissionError from os.replace racing another replace is a Windows fact of
    # life (a separate item), so exceptions are not asserted on.
    small = {"projects": {"/a": {"name": "a"}}}
    big = {"projects": {f"/p{i}": {"name": "x" * 60} for i in range(40)}}
    pushkey_vault.save_config(small)
    threads_per_round = 4
    unexpected = []
    damage = []

    for round_number in range(250):
        barrier = threading.Barrier(threads_per_round)

        def worker(payload):
            barrier.wait()
            try:
                pushkey_vault.save_config(payload)
            except OSError:
                pass
            except BaseException as exc:  # a real bug, not a Windows replace race
                unexpected.append(exc)

        threads = [
            threading.Thread(target=worker, args=(big if i % 2 else small,))
            for i in range(threads_per_round)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads), "worker thread hung"

        if not pushkey_shared.CONFIG_FILE.exists():
            damage.append((round_number, "missing"))
            pushkey_vault.save_config(small)
            continue
        caught = _catch(pushkey_vault.load_config, strict=True)
        if caught is not None:
            damage.append((round_number, f"unreadable: {caught!r}"))
            pushkey_vault.save_config(small)
        elif pushkey_vault.load_config(strict=True) not in (small, big):
            damage.append((round_number, "unexpected content"))

    assert unexpected == []
    assert damage == []
    assert _leftover_temp_files() == []


def test_save_config_removes_its_temp_file_when_the_write_fails(monkeypatch):
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    def refuse(src, dst):
        raise OSError("disk says no")

    with monkeypatch.context() as patch:
        patch.setattr(pushkey_vault.os, "replace", refuse)
        with pytest.raises(OSError, match="disk says no"):
            pushkey_vault.save_config({"projects": {"/other": {"name": "other"}}})

    assert _leftover_temp_files() == []
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before

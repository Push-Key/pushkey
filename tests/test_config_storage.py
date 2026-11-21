"""Encrypted config storage must round-trip whatever the random nonce looks like.

It must also refuse to write over a config file it could not read, and serialise
its writers, so a damaged file or two racing saves can never wipe projects.
"""
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

    with pytest.raises(error) as excinfo:
        pushkey_vault.load_config(strict=True)
    assert str(excinfo.value) == "config_unreadable"
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

    with pytest.raises(error) as excinfo:
        pushkey_vault.load_config(strict=True)
    assert str(excinfo.value) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == raw


def test_strict_load_refuses_an_encrypted_payload_that_is_not_a_dict():
    error = _api("ConfigUnreadableError")
    _strict_loading_exists()
    pushkey_vault.save_config(["not", "a", "dict"])
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    with pytest.raises(error) as excinfo:
        pushkey_vault.load_config(strict=True)
    assert str(excinfo.value) == "config_unreadable"
    # Lenient loading is unchanged for existing callers.
    assert pushkey_vault.load_config() == ["not", "a", "dict"]
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before


def test_strict_load_still_migrates_a_legacy_plaintext_config():
    _strict_loading_exists()
    original = json.dumps(CONFIG).encode()
    _write_raw(original)

    assert pushkey_vault.load_config(strict=True) == CONFIG

    migrated = pushkey_shared.CONFIG_FILE.read_bytes()
    assert migrated != original
    with pytest.raises(ValueError):
        json.loads(migrated)
    assert pushkey_vault.load_config(strict=True) == CONFIG


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

    with pytest.raises(error) as excinfo:
        update_config(mutate)

    assert str(excinfo.value) == "config_unreadable"
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

    with pytest.raises(RuntimeError, match="boom"):
        update_config(mutate)

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
        outcome = _run_in_thread(lambda: update_config(lambda cfg: cfg["projects"].clear()))

    assert isinstance(outcome.get("error"), error), outcome
    assert str(outcome["error"]) == "config_busy"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == before
    assert update_config(lambda cfg: "free again") == "free again"


def test_config_lock_only_relabels_its_own_acquisition_timeout():
    config_lock = _api("config_lock")

    # A FileLockTimeout raised by the body (say, a nested vault lock) is not a
    # busy config: it must reach the caller unchanged.
    with pytest.raises(FileLockTimeout):
        with config_lock():
            raise FileLockTimeout()


def test_update_config_inside_mutate_fails_busy_instead_of_hanging(monkeypatch):
    update_config = _api("update_config")
    error = _api("ConfigUnreadableError")
    monkeypatch.setattr(pushkey_vault, "_CONFIG_LOCK_TIMEOUT_SECONDS", 0.2)
    pushkey_vault.save_config(CONFIG)
    before = pushkey_shared.CONFIG_FILE.read_bytes()

    def mutate(cfg):
        # The lock is not reentrant: mutate must never call update_config.
        update_config(lambda inner: None)

    with pytest.raises(error) as excinfo:
        update_config(mutate)

    assert str(excinfo.value) == "config_busy"
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


def test_save_config_writes_through_a_per_process_temp_file(monkeypatch):
    real_replace = os.replace
    moves = []

    def spy(src, dst):
        moves.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(pushkey_vault.os, "replace", spy)
        pushkey_vault.save_config(CONFIG)

    config_moves = [(src, dst) for src, dst in moves if dst == pushkey_shared.CONFIG_FILE]
    assert len(config_moves) == 1
    src, _dst = config_moves[0]
    assert src.name == f"config.{os.getpid()}.tmp"
    assert src.parent == pushkey_shared.CONFIG_FILE.parent
    assert _leftover_temp_files() == []
    assert pushkey_vault.load_config() == CONFIG


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

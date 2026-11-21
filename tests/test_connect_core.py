"""pushkey_connect core: the vault commit cycle, key replacement and the project registry.

Vaults are seeded the way the app does it: a V2 vault is `save_vault(vault, "pw")`,
a V3 vault adds a recovery code and gives back the raw vault key. Project folders
are subfolders of tmp_path (tmp_path itself is the vault directory). No test
passes a real secret: values are dummy strings, and the module must never put one
in a ConnectError.
"""
import copy
import os
import re
from datetime import datetime

import pytest

import pushkey_connect
import pushkey_health
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_crypto import generate_recovery_code
from pushkey_projectfs import ProjectPathError
from pushkey_vault import (
    ConfigUnreadableError,
    VaultBusyError,
    VaultConflictError,
    VaultData,
    load_config,
    load_vault,
    save_config,
    save_vault,
)

PASSWORD = "pw"
MODES = ["v2_password", "v3_key_only", "v3_key_and_password"]
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _entry(**extra):
    entry = {
        "value": "sk-old", "created": "2026-01-01", "rotated": None,
        "provider": "Unknown", "env": "dev", "projects": [], "notes": "",
    }
    entry.update(extra)
    return entry


def _conn(project, file=".env", var="A"):
    return {"project": project, "file": file, "var": var, "added": "2026-11-21T10:00:00"}


def _raised(call, exc_type):
    """The exception `call` raises, or None. Any other exception type propagates."""
    try:
        call()
    except exc_type as exc:
        return exc
    return None


def _folder(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _canon(folder):
    return str(folder.resolve())


def _registered():
    return pushkey_connect.registered_projects(load_config(strict=True))


@pytest.fixture
def pro_tier(monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")


class _Open:
    """A seeded vault plus the credentials one entry point holds for it."""

    def __init__(self, mode, vault):
        self.mode = mode
        if mode == "v2_password":
            save_vault(vault, PASSWORD)
            self.vault_key = None
        else:
            save_vault(vault, PASSWORD, recovery_code=generate_recovery_code())
            _, self.vault_key = load_vault(PASSWORD)
            assert self.vault_key is not None
        self.password = None if mode == "v3_key_only" else PASSWORD

    def kwargs(self):
        return {"vault_key": self.vault_key, "password": self.password}

    def current(self):
        loaded, _ = load_vault(PASSWORD)
        assert loaded is not None
        return loaded

    def external_save(self, change):
        """Another process loads the vault, changes it and saves it."""
        if self.mode == "v3_key_only":
            other, _ = pushkey_vault.load_vault_with_key(self.vault_key)
            change(other)
            pushkey_vault.save_vault_with_key(other, self.vault_key)
        else:
            other, _ = load_vault(PASSWORD)
            change(other)
            save_vault(other, PASSWORD, vault_key=self.vault_key)


# -- ConnectError --------------------------------------------------------------


def test_connect_error_carries_a_code_and_detail():
    error = pushkey_connect.ConnectError("var_taken", {"key": "OTHER"})

    assert error.code == "var_taken"
    assert error.detail == {"key": "OTHER"}
    assert str(error) == "var_taken"
    assert pushkey_connect.ConnectError("vault_changed").detail == {}


# -- commit ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_commit_saves_and_adopts(mode):
    s = _Open(mode, {"A": _entry()})
    target, _ = load_vault(PASSWORD)
    seen = []

    def mutate(vault):
        seen.append(vault)
        vault["A"]["notes"] = "x"
        return "done"

    result = pushkey_connect.commit(mutate, target=target, **s.kwargs())

    assert isinstance(result, pushkey_connect.CommitResult)
    assert result.value == "done"
    assert result.health_warning is None
    assert s.current()["A"]["notes"] == "x"
    assert target["A"]["notes"] == "x"
    assert target._pushkey_revision == load_vault(PASSWORD)[0]._pushkey_revision
    assert len(seen) == 1 and seen[0] is not target and result.vault is seen[0]


def test_commit_replaces_the_callers_stale_copy_with_what_it_saved():
    s = _Open("v2_password", {"A": _entry()})
    target, _ = load_vault(PASSWORD)
    s.external_save(lambda vault: vault.update({"B": _entry(value="sk-b")}))

    pushkey_connect.commit(
        lambda vault: vault["A"].update(notes="x"), target=target, **s.kwargs()
    )

    assert sorted(target) == ["A", "B"]
    assert target["A"]["notes"] == "x"
    assert s.current()["B"]["value"] == "sk-b"


@pytest.mark.parametrize("mode", MODES)
def test_commit_retries_once_after_conflict(mode):
    s = _Open(mode, {"A": _entry(), "B": _entry(value="sk-b")})
    calls = []

    def mutate(vault):
        calls.append(sorted(vault))
        vault["A"]["notes"] = "mine"
        if len(calls) == 1:
            s.external_save(lambda other: other["B"].update(notes="theirs"))

    result = pushkey_connect.commit(mutate, **s.kwargs())

    assert len(calls) == 2
    assert result.vault["A"]["notes"] == "mine"
    assert result.vault["B"]["notes"] == "theirs"
    saved = s.current()
    assert saved["A"]["notes"] == "mine" and saved["B"]["notes"] == "theirs"


@pytest.mark.parametrize("mode", MODES)
def test_commit_gives_up_after_second_conflict(mode):
    s = _Open(mode, {"A": _entry(), "B": _entry(value="sk-b")})
    calls = []

    def mutate(vault):
        calls.append(1)
        vault["A"]["notes"] = "mine"
        s.external_save(lambda other: other["B"].update(notes=f"theirs-{len(calls)}"))

    error = _raised(lambda: pushkey_connect.commit(mutate, **s.kwargs()), pushkey_connect.ConnectError)

    assert error is not None, "a second conflict must raise ConnectError"
    assert error.code == "vault_changed"
    assert len(calls) == 2
    assert "sk-" not in str(error) + repr(error.detail)
    saved = s.current()
    assert saved["A"]["notes"] == ""
    assert saved["B"]["notes"] == "theirs-2"


def test_commit_does_not_retry_a_conflict_that_is_not_a_stale_revision():
    s = _Open("v2_password", {"A": _entry()})
    calls = []

    def mutate(vault):
        calls.append(1)
        vault._pushkey_revision = None  # save_vault: "expected_revision_required"

    error = _raised(lambda: pushkey_connect.commit(mutate, **s.kwargs()), VaultConflictError)

    assert error is not None, "expected_revision_required is a bug, not a retry"
    assert str(error) == "expected_revision_required"
    assert len(calls) == 1


def test_commit_saves_nothing_when_mutate_raises():
    s = _Open("v2_password", {"A": _entry()})
    before = pushkey_shared.VAULT_FILE.read_bytes()

    def mutate(vault):
        vault["A"]["notes"] = "half done"
        raise pushkey_connect.ConnectError("key_not_found", {"key": "A"})

    error = _raised(lambda: pushkey_connect.commit(mutate, **s.kwargs()), pushkey_connect.ConnectError)

    assert error is not None and error.code == "key_not_found"
    assert pushkey_shared.VAULT_FILE.read_bytes() == before


@pytest.mark.parametrize(
    "error", [pushkey_health.HealthSidecarError("health_write_failed"), VaultBusyError("vault_lock_failed")]
)
def test_commit_reports_a_health_publication_failure(monkeypatch, error):
    s = _Open("v2_password", {"A": _entry()})
    target, _ = load_vault(PASSWORD)

    def failing(vault, **kwargs):
        raise error

    monkeypatch.setattr(pushkey_health, "publish_saved_vault", failing)

    result = pushkey_connect.commit(
        lambda vault: vault["A"].update(notes="x"), target=target, **s.kwargs()
    )

    assert result.health_warning == "health_publication_failed"
    assert s.current()["A"]["notes"] == "x"
    assert target["A"]["notes"] == "x"


def test_commit_publishes_the_vault_it_just_saved(monkeypatch):
    s = _Open("v2_password", {"A": _entry()})
    published = []

    def recording(vault, **kwargs):
        published.append(
            (vault["A"]["notes"], vault._pushkey_revision == load_vault(PASSWORD)[0]._pushkey_revision)
        )

    monkeypatch.setattr(pushkey_health, "publish_saved_vault", recording)

    result = pushkey_connect.commit(lambda vault: vault["A"].update(notes="x"), **s.kwargs())

    assert published == [("x", True)]
    assert result.health_warning is None


def test_commit_writes_the_health_sidecar():
    s = _Open("v2_password", {"A": _entry()})
    assert not pushkey_shared.HEALTH_FILE.exists()

    result = pushkey_connect.commit(lambda vault: vault["A"].update(notes="x"), **s.kwargs())

    assert result.health_warning is None
    assert pushkey_shared.HEALTH_FILE.exists()


def test_commit_creates_a_vault_that_does_not_exist_yet():
    assert not pushkey_shared.VAULT_FILE.exists()

    result = pushkey_connect.commit(
        lambda vault: vault.update({"A": _entry()}), vault_key=None, password=PASSWORD
    )

    assert pushkey_shared.VAULT_FILE.exists()
    assert result.health_warning is None
    assert isinstance(result.vault, VaultData)
    assert load_vault(PASSWORD)[0]["A"]["value"] == "sk-old"


def test_commit_without_usable_credentials_is_vault_unavailable():
    s = _Open("v3_key_and_password", {"A": _entry()})
    calls = []

    def mutate(vault):
        calls.append(1)

    attempts = {
        "wrong password": {"vault_key": None, "password": "not-the-password"},
        "wrong vault key": {"vault_key": bytes(32), "password": None},
        "no credentials": {"vault_key": None, "password": None},
    }
    for label, kwargs in attempts.items():
        error = _raised(lambda: pushkey_connect.commit(mutate, **kwargs), pushkey_connect.ConnectError)
        assert error is not None, label
        assert error.code == "vault_unavailable", label
    assert calls == []
    assert s.current()["A"]["notes"] == ""


# -- adopt_vault -----------------------------------------------------------------


def test_adopt_vault_replaces_contents_and_copies_the_revision():
    target = VaultData({"OLD": _entry()})
    target._pushkey_revision = b"old-revision"
    fresh = VaultData({"NEW": _entry(value="sk-new")})
    fresh._pushkey_revision = b"new-revision"

    pushkey_connect.adopt_vault(target, fresh)

    assert dict(target) == dict(fresh)
    assert "OLD" not in target
    assert target._pushkey_revision == b"new-revision"


def test_adopt_vault_accepts_a_plain_dict_and_the_same_object():
    plain = {"OLD": _entry()}
    fresh = VaultData({"NEW": _entry()})
    fresh._pushkey_revision = b"new-revision"
    pushkey_connect.adopt_vault(plain, fresh)
    assert sorted(plain) == ["NEW"]

    same = VaultData({"KEEP": _entry()})
    same._pushkey_revision = b"r"
    pushkey_connect.adopt_vault(same, same)
    assert sorted(same) == ["KEEP"] and same._pushkey_revision == b"r"


# -- replace_value ---------------------------------------------------------------


def test_replace_value_keeps_connections():
    entry = _entry(
        projects=["/p1"], connections=[_conn("/p1")], next_value="sk-next",
        next_added="2026-11-01", dual_rotation=True,
    )
    snapshot = copy.deepcopy(entry)

    pushkey_connect.replace_value(entry, "new", now="2026-11-21T10:30:00")

    assert entry.get("history") == [{"value": "sk-old", "retired": "2026-11-21T10:30:00"}]
    assert entry.get("previous") == "sk-old"
    assert entry["value"] == "new"
    assert entry["rotated"] == "2026-11-21T10:30:00"
    assert entry.get("rotation_count") == 1
    for kept in ("projects", "connections", "next_value", "next_added", "dual_rotation",
                 "env", "provider", "notes", "created"):
        assert entry[kept] == snapshot[kept], kept
    assert set(entry) - set(snapshot) == {"history", "previous", "rotation_count"}


def test_replace_value_stamps_the_current_time_when_none_is_given():
    entry = _entry()

    pushkey_connect.replace_value(entry, "new")

    rotated = entry["rotated"]
    assert isinstance(rotated, str) and TIMESTAMP.match(rotated), rotated
    datetime.strptime(rotated, "%Y-%m-%dT%H:%M:%S")
    assert entry["history"][0]["retired"] == rotated


def test_replace_value_keeps_only_the_ten_newest_history_entries():
    old = [{"value": f"sk-{n}", "retired": f"2026-01-{n + 1:02d}"} for n in range(10)]
    entry = _entry(history=copy.deepcopy(old), rotation_count=10)

    pushkey_connect.replace_value(entry, "new", now="2026-11-21T10:30:00")

    assert len(entry["history"]) == 10
    assert entry["history"][0] == {"value": "sk-old", "retired": "2026-11-21T10:30:00"}
    assert entry["history"][1:] == old[:9]
    assert entry["rotation_count"] == 11


def test_replace_value_counts_on_from_the_stored_count_and_repairs_a_null_history():
    entry = _entry(history=None, rotation_count=3)

    pushkey_connect.replace_value(entry, "new", now="2026-11-21T10:30:00")

    assert entry["rotation_count"] == 4
    assert entry["history"] == [{"value": "sk-old", "retired": "2026-11-21T10:30:00"}]


# -- registry: registered_projects, register_project ---------------------------------


def test_registered_projects_keeps_only_absolute_path_keys(tmp_path):
    absolute = str(tmp_path / "proj")
    record = {"name": "proj"}
    config = {"projects": {absolute: record, "legacy-name": {"name": "legacy"}}}

    assert pushkey_connect.registered_projects(config) == {absolute: record}
    assert pushkey_connect.registered_projects({"projects": {}}) == {}
    assert pushkey_connect.registered_projects({}) == {}


def test_register_project_and_limit(monkeypatch, tmp_path):
    p1, p2 = _folder(tmp_path, "p1"), _folder(tmp_path, "p2")
    day_before = datetime.now().strftime("%Y-%m-%d")

    path, record = pushkey_connect.register_project(str(p1))

    day_after = datetime.now().strftime("%Y-%m-%d")
    assert path == _canon(p1)
    assert record["created"] in {day_before, day_after}
    assert record == {"name": "p1", "created": record["created"], "default_file": ".env", "environment": "dev"}
    assert _registered() == {path: record}

    full = _raised(lambda: pushkey_connect.register_project(str(p2)), pushkey_connect.ConnectError)
    assert full is not None, "the free tier allows one project"
    assert full.code == "project_limit"
    assert list(_registered()) == [path]

    again = _raised(lambda: pushkey_connect.register_project(str(p1)), pushkey_connect.ConnectError)
    assert again is not None and again.code == "project_exists"  # exists wins over the limit

    with monkeypatch.context() as patch:
        patch.setattr(pushkey_tiers, "current_tier", lambda: "pro")
        second, _ = pushkey_connect.register_project(str(p2))
        dup = _raised(lambda: pushkey_connect.register_project(str(p2)), pushkey_connect.ConnectError)
    assert second == _canon(p2)
    assert dup is not None and dup.code == "project_exists"
    assert sorted(_registered()) == sorted([path, second])


def test_register_project_stores_the_canonical_path(pro_tier, tmp_path):
    p1 = _folder(tmp_path, "p1")
    roundabout = str(p1) + os.sep + ".." + os.sep + "p1"

    path, _ = pushkey_connect.register_project(roundabout)

    assert path == _canon(p1)
    assert list(_registered()) == [_canon(p1)]
    again = _raised(lambda: pushkey_connect.register_project(str(p1)), pushkey_connect.ConnectError)
    assert again is not None and again.code == "project_exists"


def test_register_project_takes_a_display_name(pro_tier, tmp_path):
    named_path, named = pushkey_connect.register_project(str(_folder(tmp_path, "p1")), name="Acme Web")
    _, unnamed = pushkey_connect.register_project(str(_folder(tmp_path, "p2")), name="  ")

    assert named.get("name") == "Acme Web"
    assert _registered()[named_path]["name"] == "Acme Web"
    assert unnamed.get("name") == "p2"


def test_register_project_counts_only_absolute_path_projects(tmp_path):
    save_config({"projects": {"desktop-name": {"name": "legacy"}}, "sso_settings": {"on": True}})
    p1 = _folder(tmp_path, "p1")

    path, _ = pushkey_connect.register_project(str(p1))

    config = load_config(strict=True)
    assert path in config["projects"]
    assert config["projects"]["desktop-name"] == {"name": "legacy"}
    assert config["sso_settings"] == {"on": True}


def test_register_project_path_errors_pass_through(tmp_path):
    for bad in ("relative/folder", str(tmp_path / "missing"), ""):
        error = _raised(lambda: pushkey_connect.register_project(bad), ProjectPathError)
        assert error is not None, repr(bad)
    assert not pushkey_shared.CONFIG_FILE.exists()


def test_register_project_leaves_an_unreadable_config_alone(tmp_path):
    p1 = _folder(tmp_path, "p1")
    damaged = bytes(range(40))
    pushkey_shared.CONFIG_FILE.write_bytes(damaged)

    error = _raised(lambda: pushkey_connect.register_project(str(p1)), ConfigUnreadableError)

    assert error is not None and str(error) == "config_unreadable"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == damaged


# -- registry: unregister_project -------------------------------------------------


def _seed_two_projects(mode, tmp_path):
    p1, p2 = _folder(tmp_path, "p1"), _folder(tmp_path, "p2")
    c1, _ = pushkey_connect.register_project(str(p1))
    c2, _ = pushkey_connect.register_project(str(p2))
    vault = {
        "A": _entry(projects=[c1, c2], connections=[_conn(c1, ".env", "A"), _conn(c2, ".env.local", "A_LOCAL")]),
        "B": _entry(projects=[c1], connections=[_conn(c1, ".env", "B")]),
        "C": _entry(projects=[c2], connections=[_conn(c2, ".env", "C")]),
        "D": _entry(projects=[c1], connections=[]),
        "E": {"value": "sk-legacy"},
    }
    return p1, c1, c2, _Open(mode, vault)


@pytest.mark.parametrize("mode", MODES)
def test_unregister_removes_connections(mode, pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects(mode, tmp_path)
    target, _ = load_vault(PASSWORD)
    before_c = copy.deepcopy(s.current()["C"])

    result = pushkey_connect.unregister_project(str(p1), target=target, **s.kwargs())

    vault = s.current()
    assert isinstance(result, pushkey_connect.CommitResult)
    assert vault["A"]["projects"] == [c2]
    assert vault["A"]["connections"] == [_conn(c2, ".env.local", "A_LOCAL")]
    assert vault["B"]["projects"] == [] and vault["B"]["connections"] == []
    assert vault["D"]["projects"] == [] and vault["D"]["connections"] == []
    assert vault["C"] == before_c
    assert vault["E"] == {"value": "sk-legacy"}
    assert sorted(result.value) == ["A", "B", "D"]
    assert list(_registered()) == [c2]
    assert dict(target) == dict(vault)
    assert target._pushkey_revision == load_vault(PASSWORD)[0]._pushkey_revision


def test_unregister_commits_the_vault_before_it_touches_the_config(monkeypatch, pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects("v2_password", tmp_path)

    def broken(mutate):
        raise ConfigUnreadableError("config_busy")

    monkeypatch.setattr(pushkey_vault, "update_config", broken)

    error = _raised(lambda: pushkey_connect.unregister_project(str(p1), **s.kwargs()), ConfigUnreadableError)

    assert error is not None and str(error) == "config_busy"
    vault = s.current()
    assert all(c1 not in vault[name].get("projects", []) for name in vault)
    assert all(c["project"] != c1 for name in vault for c in vault[name].get("connections", []))
    assert c1 in _registered()  # a registered project without connections, never the reverse


def test_unregister_an_unregistered_folder_changes_nothing(pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects("v2_password", tmp_path)
    stranger = _folder(tmp_path, "stranger")
    before = pushkey_shared.VAULT_FILE.read_bytes()

    for folder in (stranger, tmp_path / "never-existed"):
        error = _raised(
            lambda: pushkey_connect.unregister_project(str(folder), **s.kwargs()), pushkey_connect.ConnectError
        )
        assert error is not None, str(folder)
        assert error.code == "project_not_registered"

    assert pushkey_shared.VAULT_FILE.read_bytes() == before
    assert sorted(_registered()) == sorted([c1, c2])


def test_unregister_works_after_the_folder_was_deleted(pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects("v2_password", tmp_path)
    p1.rmdir()

    pushkey_connect.unregister_project(str(p1), **s.kwargs())

    assert list(_registered()) == [c2]
    assert s.current()["B"]["connections"] == []


def test_unregister_rejects_an_invalid_path(pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects("v2_password", tmp_path)

    error = _raised(lambda: pushkey_connect.unregister_project("relative/p1", **s.kwargs()), ProjectPathError)

    assert error is not None, "a relative path is not a project path"
    assert sorted(_registered()) == sorted([c1, c2])


def test_unregister_with_an_unreadable_config_changes_nothing(pro_tier, tmp_path):
    p1, c1, c2, s = _seed_two_projects("v2_password", tmp_path)
    pushkey_shared.CONFIG_FILE.write_bytes(bytes(range(40)))
    before = pushkey_shared.VAULT_FILE.read_bytes()

    error = _raised(lambda: pushkey_connect.unregister_project(str(p1), **s.kwargs()), ConfigUnreadableError)

    assert error is not None and str(error) == "config_unreadable"
    assert pushkey_shared.VAULT_FILE.read_bytes() == before

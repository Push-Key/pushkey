"""pushkey_connect_migrate: the one-time move of the desktop's name-keyed projects to the
shared, path-keyed project store.

`plan_migration` is tested on plain dicts (it is pure apart from mutating them);
`ensure_migrated` and the `migration_pending` refusals run against a real V2 vault and
config.json under tmp_path (the vault directory). Project folders are subfolders of
tmp_path, never tmp_path itself. Keys carry dummy values, and one test checks that no
value reaches a report or the config. Paths in assertions go through
`canonical_project_path(..., must_exist=False)`, never `str(folder)`: on Windows the
two can differ in case or long-path form.
"""
import copy
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import date

import pytest

import pushkey_connect
import pushkey_crypto
import pushkey_projectfs
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_connect import ConnectError
from pushkey_connect_migrate import (
    MigrationReport,
    dismiss_notice,
    ensure_migrated,
    is_migrated,
    plan_migration,
)
from pushkey_vault import (
    ConfigUnreadableError,
    VaultConflictError,
    load_config,
    load_vault,
    save_config,
    save_vault,
)

PASSWORD = "pw"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
ADDED = "2026-01-02T03:04:05"


def _entry(name, **extra):
    entry = {
        "value": f"dummy-{name}", "created": "2026-01-01", "rotated": None,
        "provider": "Unknown", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


def _desktop(folder, keys, **extra):
    """A desktop entry the way pushkey.py:7868 writes it."""
    entry = {"path": str(folder), "keys": keys, "added": ADDED, "target_env": "all"}
    entry.update(extra)
    return entry


def _canon(folder):
    return pushkey_projectfs.canonical_project_path(str(folder), must_exist=False)


def _folder(tmp_path, name, *, create=True):
    folder = tmp_path / name
    if create:
        folder.mkdir()
    return folder


def _raised(call, exc_type):
    """The exception `call` raises, or None. An exception of another type fails the test."""
    try:
        call()
    except Exception as exc:
        assert isinstance(exc, exc_type), f"expected {exc_type.__name__}, got {exc!r}"
        return exc
    return None


def _only(items):
    items = list(items)
    assert len(items) == 1, f"expected exactly one item, got {len(items)}"
    return items[0]


def _bare(conn):
    """A connection without its timestamp."""
    return {key: value for key, value in conn.items() if key != "added"}


def _vault_bytes():
    return pushkey_shared.VAULT_FILE.read_bytes()


def _config_bytes():
    return pushkey_shared.CONFIG_FILE.read_bytes()


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch):
    """Derive vault keys with one SHA-256 instead of Argon2id (64 MB, 3 passes).

    Nothing here is about the KDF; tests/test_vault_crypto.py covers the real one.
    """
    monkeypatch.setattr(
        pushkey_crypto, "_derive_key_argon2",
        lambda password, salt: hashlib.sha256(salt + password.encode()).digest(),
    )


@pytest.fixture(autouse=True)
def pro_tier(monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")


def _seed_desktop(tmp_path):
    """A saved V2 vault and a desktop-shaped config: one entry, acme, with two keys and a stale name."""
    folder = _folder(tmp_path, "acme-web")
    save_vault({"A": _entry("A", env="dev"), "B": _entry("B", env="prod")}, PASSWORD)
    save_config({"projects": {"acme": _desktop(folder, ["A", "B", "GONE"], target_env="dev")}})
    return folder


def _migrate():
    return ensure_migrated(vault_key=None, password=PASSWORD)


# -- plan_migration: desktop entries ----------------------------------------------------


def test_migrates_desktop_entry(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    desktop = _desktop(folder, ["A", "GONE"], ci_platform="github")
    config = {"projects": {"acme": copy.deepcopy(desktop)}}
    vault = {"A": _entry("A", env="prod")}

    report = plan_migration(vault, config)

    assert report == MigrationReport(moved=["acme"], connections_added=1, missing_keys=[("acme", "GONE")])
    assert config["projects"] == {
        canon: {
            "name": "acme", "created": "2026-01-02", "default_file": ".env",
            "environment": "all", "ci_platform": "github",
        }
    }
    assert config["projects_legacy"] == {"acme": desktop}
    assert config["connect_schema"] == 1
    assert "connect_notice" not in config
    assert vault["A"]["projects"] == [canon]
    conn = _only(vault["A"]["connections"])
    assert _bare(conn) == {"project": canon, "file": ".env", "var": "A"}
    assert TIMESTAMP.fullmatch(conn["added"])
    assert is_migrated(config)


def test_empty_list_gets_no_keys_and_notice(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {"acme": _desktop(folder, [])}}
    vault = {"A": _entry("A")}

    report = plan_migration(vault, config)

    assert report == MigrationReport(moved=["acme"], every_key_projects=[canon])
    assert vault["A"]["projects"] == [] and vault["A"]["connections"] == []
    assert canon in config["projects"]
    assert config["connect_notice"] == {"every_key_projects": [canon], "env_skipped": []}


def test_env_filter_respected(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {"acme": _desktop(folder, ["PROD", "DEV", "ANY"], target_env="dev")}}
    vault = {
        "PROD": _entry("PROD", env="prod"),
        "DEV": _entry("DEV", env="dev"),
        "ANY": _entry("ANY", env="all"),
    }

    report = plan_migration(vault, config)

    assert report.env_skipped == [("acme", "PROD")]
    assert report.connections_added == 2 and report.missing_keys == []
    assert vault["PROD"]["projects"] == [] and vault["PROD"]["connections"] == []
    for name in ("DEV", "ANY"):
        assert vault[name]["projects"] == [canon]
        assert _bare(_only(vault[name]["connections"])) == {"project": canon, "file": ".env", "var": name}
    assert config["projects"][canon]["environment"] == "dev"
    assert config["connect_notice"] == {"every_key_projects": [], "env_skipped": [["acme", "PROD"]]}


def test_key_without_env_counts_as_all(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {"acme": _desktop(folder, ["NOENV"], target_env="staging")}}
    entry = _entry("NOENV")
    del entry["env"]
    vault = {"NOENV": entry}

    report = plan_migration(vault, config)

    assert report.env_skipped == [] and report.connections_added == 1
    assert vault["NOENV"]["projects"] == [canon]


def test_missing_target_env_means_all_and_an_unknown_one_becomes_dev(tmp_path):
    plain, odd = _folder(tmp_path, "plain"), _folder(tmp_path, "odd")
    no_level = _desktop(plain, ["P"])
    del no_level["target_env"]
    config = {"projects": {"nolevel": no_level, "odd": _desktop(odd, ["Q"], target_env="qa")}}
    vault = {"P": _entry("P", env="prod"), "Q": _entry("Q", env="all")}

    report = plan_migration(vault, config)

    # The desktop reads a missing target_env as "all" (proj_info.get("target_env", "all")),
    # so a prod key was written there; an unknown level has no meaning for the store: "dev".
    assert report.env_skipped == [] and report.connections_added == 2
    assert config["projects"][_canon(plain)]["environment"] == "all"
    assert config["projects"][_canon(odd)]["environment"] == "dev"


def test_created_comes_from_added_or_today(tmp_path):
    folders = {name: _folder(tmp_path, name) for name in ("dated", "undated", "junk")}
    undated = _desktop(folders["undated"], [])
    del undated["added"]
    config = {"projects": {
        "dated": _desktop(folders["dated"], []),
        "undated": undated,
        "junk": _desktop(folders["junk"], [], added="yesterday"),
    }}
    before = date.today().isoformat()

    plan_migration({}, config)

    after = date.today().isoformat()
    assert all(_canon(folder) in config["projects"] for folder in folders.values())
    created = {name: config["projects"][_canon(folder)]["created"] for name, folder in folders.items()}
    assert created["dated"] == "2026-01-02"
    assert created["undated"] in {before, after} and created["junk"] in {before, after}


def test_missing_folder_is_still_migrated(tmp_path):
    gone = _folder(tmp_path, "gone", create=False)
    config = {"projects": {"old": _desktop(gone, ["A"])}}
    vault = {"A": _entry("A")}

    report = plan_migration(vault, config)

    assert report.moved == ["old"] and report.unusable == [] and report.connections_added == 1
    assert _canon(gone) in config["projects"] and "old" not in config["projects"]
    assert not gone.exists()


def test_entry_without_usable_path_goes_to_legacy_and_notice(tmp_path):
    config = {"projects": {
        "nopath": {"keys": ["A"], "added": ADDED, "target_env": "all"},
        "relative": _desktop("relative/dir", []),
        "blank": _desktop("", ["A"]),
        "junk": "not a record",
    }}
    vault = {"A": _entry("A")}
    legacy = copy.deepcopy(config["projects"])

    report = plan_migration(vault, config)

    assert report == MigrationReport(unusable=["nopath", "relative", "blank", "junk"])
    assert config["projects"] == {}
    assert config["projects_legacy"] == legacy
    assert config["connect_notice"] == {
        "every_key_projects": [], "env_skipped": [], "unusable": ["nopath", "relative", "blank", "junk"],
    }
    assert vault["A"]["projects"] == [] and vault["A"]["connections"] == []


def test_merges_into_existing_registered_record(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {
        canon: {"name": "cli-name", "created": "2025-05-05", "environment": "prod"},
        "first": _desktop(folder, ["A"], target_env="dev", ci_platform="github", github_owner="me"),
        "second": _desktop(folder, ["B"], target_env="staging", ci_platform="vercel", vercel_project_id="p1"),
    }}
    vault = {"A": _entry("A", env="dev"), "B": _entry("B", env="all")}

    report = plan_migration(vault, config)

    # Existing fields win, only missing ones are filled, and the first desktop entry
    # supplies the extras; both entries' keys are connected.
    assert report.moved == ["first", "second"] and report.connections_added == 2
    assert config["projects"] == {
        canon: {
            "name": "cli-name", "created": "2025-05-05", "environment": "prod", "default_file": ".env",
            "ci_platform": "github", "github_owner": "me", "vercel_project_id": "p1",
        }
    }
    assert set(config["projects_legacy"]) == {"first", "second"}
    assert vault["A"]["projects"] == [canon] and vault["B"]["projects"] == [canon]


def test_merge_matches_the_same_folder_spelled_differently(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    spelled = _canon(folder).replace("\\", "/") + "/"
    config = {"projects": {spelled: {"name": "cli-name", "created": "2025-05-05"}, "acme": _desktop(folder, ["A"])}}
    vault = {"A": _entry("A")}

    plan_migration(vault, config)

    assert list(config["projects"]) == [spelled]
    assert config["projects"][spelled]["name"] == "cli-name"
    assert config["projects"][spelled]["default_file"] == ".env"
    assert _only(vault["A"]["connections"])["project"] == spelled


# -- plan_migration: assignments from every other origin --------------------------------


def test_existing_assignment_becomes_connection(tmp_path):
    folder = _folder(tmp_path, "cli-web")
    canon = _canon(folder)
    record = {"name": "cli-web", "created": "2026-02-03"}
    config = {"projects": {canon: copy.deepcopy(record)}}
    no_field = _entry("D", projects=[canon])
    del no_field["connections"]  # an entry the CLI wrote before connections existed
    vault = {"B": _entry("B", projects=[canon]), "C": _entry("C"), "D": no_field}

    report = plan_migration(vault, config)

    assert report == MigrationReport(connections_added=2)
    assert _bare(_only(vault["B"]["connections"])) == {"project": canon, "file": ".env", "var": "B"}
    assert _bare(_only(vault["D"]["connections"])) == {"project": canon, "file": ".env", "var": "D"}
    assert vault["C"]["connections"] == []
    assert config["projects"] == {canon: record}
    assert config["connect_schema"] == 1 and "projects_legacy" not in config


def test_an_assignment_that_has_a_connection_gets_no_second_one(tmp_path):
    folder = _folder(tmp_path, "cli-web")
    canon = _canon(folder)
    config = {"projects": {canon: {"name": "cli-web", "created": "2026-02-03"}}}
    existing = {"project": canon, "file": ".env.local", "var": "RENAMED", "added": "2026-03-04T05:06:07"}
    vault = {"K": _entry("K", projects=[canon], connections=[copy.deepcopy(existing)])}

    report = plan_migration(vault, config)

    assert config.get("connect_schema") == 1  # it ran ...
    assert report.connections_added == 0  # ... and added nothing
    assert vault["K"]["connections"] == [existing]


def test_a_lost_marker_does_not_bring_back_unassigned_keys(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {"acme": _desktop(folder, ["A", "B"])}}
    vault = {"A": _entry("A"), "B": _entry("B")}
    assert plan_migration(vault, config).connections_added == 2
    # The user unassigns A afterwards, then the marker is lost.
    vault["A"]["projects"], vault["A"]["connections"] = [], []
    del config["connect_schema"]
    before = copy.deepcopy((vault, config["projects"], config["projects_legacy"]))

    report = plan_migration(vault, config)

    assert report == MigrationReport()
    assert (vault, config["projects"], config["projects_legacy"]) == before
    assert vault["A"]["connections"] == [] and _only(vault["B"]["connections"])["project"] == canon
    assert config["connect_schema"] == 1


def test_unregistered_allowlist_path_is_reported_not_connected(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    elsewhere = str(tmp_path / "elsewhere")
    projects = [elsewhere, "relative/dir", 5, canon]
    config = {"projects": {canon: {"name": "acme-web", "created": "2026-02-03"}}}
    vault = {"K": _entry("K", projects=list(projects))}

    report = plan_migration(vault, config)

    # Only the registered folder is connected; the rest of the allowlist is left as it was,
    # and only the absolute path that no project covers is reported.
    assert report == MigrationReport(connections_added=1, unregistered=[("K", elsewhere)])
    assert _only(vault["K"]["connections"])["project"] == canon
    assert vault["K"]["projects"] == projects
    assert config["connect_notice"] == {
        "every_key_projects": [], "env_skipped": [], "unregistered": [["K", elsewhere]],
    }


def test_allowlist_spelling_difference_matches_registered_project(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    spelled = canon.replace("\\", "/") + "/"
    config = {"projects": {canon: {"name": "acme-web", "created": "2026-02-03"}}}
    vault = {"K": _entry("K", projects=[spelled])}

    report = plan_migration(vault, config)

    assert report == MigrationReport(connections_added=1)
    assert _only(vault["K"]["connections"])["project"] == canon  # the registered spelling
    assert vault["K"]["projects"] == [spelled]


def test_desktop_key_failing_the_env_filter_but_already_assigned_is_connected_not_skipped(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    canon = _canon(folder)
    config = {"projects": {
        canon: {"name": "acme-web", "created": "2026-02-03"},
        "acme": _desktop(folder, ["PROD"], target_env="dev"),
    }}
    vault = {"PROD": _entry("PROD", env="prod", projects=[canon])}

    report = plan_migration(vault, config)

    assert report.env_skipped == [] and report.connections_added == 1
    assert "connect_notice" not in config


def test_a_new_notice_keeps_the_one_not_yet_dismissed(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    config = {
        "projects": {"acme": _desktop(folder, [])},
        "connect_notice": {"every_key_projects": ["older"], "env_skipped": [["x", "K"]]},
    }

    plan_migration({}, config)

    assert config["connect_notice"] == {"every_key_projects": ["older", _canon(folder)], "env_skipped": [["x", "K"]]}


def test_migration_is_idempotent(tmp_path):
    a, b, c = (_folder(tmp_path, name) for name in ("a", "b", "c"))
    config = {"projects": {
        "acme": _desktop(a, ["A", "PROD", "GONE"], target_env="dev"),
        "empty": _desktop(b, []),
        "nopath": {"keys": ["A"]},
        _canon(c): {"name": "c", "created": "2026-03-03"},
    }}
    vault = {
        "A": _entry("A", env="dev"),
        "PROD": _entry("PROD", env="prod"),
        "CLI": _entry("CLI", projects=[_canon(c), str(tmp_path / "elsewhere")]),
    }

    first = plan_migration(vault, config)

    assert first.moved == ["acme", "empty"] and first.connections_added == 2
    assert first.unregistered == [("CLI", str(tmp_path / "elsewhere"))]
    snapshot = copy.deepcopy((vault, config))
    second = plan_migration(vault, config)
    assert second == MigrationReport()
    assert (vault, config) == snapshot


def test_no_key_value_reaches_the_report_or_the_config(tmp_path):
    folder = _folder(tmp_path, "acme-web")
    other = _folder(tmp_path, "other")
    config = {"projects": {"acme": _desktop(folder, ["A", "PROD", "GONE"], target_env="dev"), "all": _desktop(other, [])}}
    vault = {
        "A": _entry("A", env="dev", value="SECRET-VALUE-A"),
        "PROD": _entry("PROD", env="prod", value="SECRET-VALUE-PROD"),
        "CLI": _entry("CLI", value="SECRET-VALUE-CLI", projects=[str(tmp_path / "elsewhere")]),
    }

    report = plan_migration(vault, config)

    assert report.connections_added == 1 and report.env_skipped and report.every_key_projects
    assert "SECRET-VALUE" not in repr(report) + json.dumps(config)


# -- ensure_migrated ----------------------------------------------------------------------


def test_ensure_migrated_moves_the_store_and_returns_the_report(tmp_path):
    folder = _seed_desktop(tmp_path)
    canon = _canon(folder)
    target = {}

    report = ensure_migrated(vault_key=None, password=PASSWORD, target=target)

    assert report is not None
    assert report.moved == ["acme"] and report.connections_added == 1
    assert report.env_skipped == [("acme", "B")] and report.missing_keys == [("acme", "GONE")]
    config = load_config(strict=True)
    assert list(config["projects"]) == [canon] and set(config["projects_legacy"]) == {"acme"}
    assert config["projects"][canon]["environment"] == "dev" and config["connect_schema"] == 1
    assert config["connect_notice"] == {"every_key_projects": [], "env_skipped": [["acme", "B"]]}
    vault, _ = load_vault(PASSWORD)
    assert _bare(_only(vault["A"]["connections"])) == {"project": canon, "file": ".env", "var": "A"}
    assert vault["A"]["projects"] == [canon] and vault["B"]["connections"] == []
    assert target["A"]["connections"] == vault["A"]["connections"]  # the session's copy was brought up to date
    assert is_migrated(config)


def test_ensure_migrated_returns_none_when_done(tmp_path):
    _seed_desktop(tmp_path)
    first = _migrate()
    assert first is not None
    vault_before, config_before = _vault_bytes(), _config_bytes()

    second = _migrate()

    assert second is None
    assert _vault_bytes() == vault_before and _config_bytes() == config_before


def test_a_store_without_desktop_entries_still_gets_connections_and_the_marker(tmp_path):
    # is_migrated() is already True for a config with only path-keyed projects, but the
    # allowlist of a CLI-only store still has to become connections (spec 5.2 step 1).
    folder = _folder(tmp_path, "cli-web")
    canon = _canon(folder)
    save_vault({"K": _entry("K", projects=[canon])}, PASSWORD)
    save_config({"projects": {canon: {"name": "cli-web", "created": "2026-02-03"}}})
    assert is_migrated(load_config(strict=True))

    first = _migrate()
    second = _migrate()

    assert first is not None and first.connections_added == 1
    assert second is None
    assert load_config(strict=True)["connect_schema"] == 1
    vault, _ = load_vault(PASSWORD)
    assert _only(vault["K"]["connections"])["project"] == canon


@pytest.mark.parametrize("password", [None, ""])
def test_ensure_migrated_without_password_is_pending(tmp_path, password):
    _seed_desktop(tmp_path)
    vault_before, config_before = _vault_bytes(), _config_bytes()

    error = _raised(lambda: ensure_migrated(vault_key=bytes(32), password=password), ConnectError)

    assert error is not None and error.code == "migration_pending"
    assert _vault_bytes() == vault_before and _config_bytes() == config_before


def test_migration_refuses_unreadable_config(tmp_path):
    save_vault({"A": _entry("A")}, PASSWORD)
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config \x00\xff garbage")
    vault_before, config_before = _vault_bytes(), _config_bytes()

    error = _raised(_migrate, ConfigUnreadableError)

    assert error is not None and str(error) == "config_unreadable"
    assert _vault_bytes() == vault_before and _config_bytes() == config_before


def test_vault_is_saved_before_the_config(tmp_path, monkeypatch):
    _seed_desktop(tmp_path)
    calls = []
    real_vault, real_config = pushkey_vault.save_vault, pushkey_vault.save_config

    def save_vault_spy(*args, **kwargs):
        calls.append("vault")
        return real_vault(*args, **kwargs)

    def save_config_spy(*args, **kwargs):
        calls.append("config")
        return real_config(*args, **kwargs)

    monkeypatch.setattr(pushkey_vault, "save_vault", save_vault_spy)
    monkeypatch.setattr(pushkey_vault, "save_config", save_config_spy)

    report = _migrate()

    assert report is not None
    assert calls == ["vault", "config"]


def test_a_vault_save_failure_leaves_the_config_untouched(tmp_path, monkeypatch):
    _seed_desktop(tmp_path)
    vault_before, config_before = _vault_bytes(), _config_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pushkey_vault, "save_vault", boom)

    error = _raised(_migrate, OSError)

    assert error is not None
    assert _vault_bytes() == vault_before and _config_bytes() == config_before
    assert not pushkey_connect.is_migrated(load_config(strict=True))


def test_config_save_failure_after_vault_save_converges_on_rerun(tmp_path, monkeypatch):
    folder = _seed_desktop(tmp_path)
    canon = _canon(folder)
    config_before = _config_bytes()
    real_save_config = pushkey_vault.save_config
    state = {"fail": True}

    def flaky_save_config(config):
        if state["fail"]:
            state["fail"] = False
            raise OSError("disk full")
        return real_save_config(config)

    monkeypatch.setattr(pushkey_vault, "save_config", flaky_save_config)

    error = _raised(_migrate, OSError)

    # The vault side landed, the config did not move.
    assert error is not None
    assert _config_bytes() == config_before
    vault, _ = load_vault(PASSWORD)
    assert len(vault["A"]["connections"]) == 1

    report = _migrate()

    assert report is not None and report.moved == ["acme"]
    assert report.env_skipped == [("acme", "B")] and report.missing_keys == [("acme", "GONE")]
    vault, _ = load_vault(PASSWORD)
    assert len(vault["A"]["connections"]) == 1 and vault["B"]["connections"] == []  # nothing doubled
    config = load_config(strict=True)
    assert list(config["projects"]) == [canon] and config["connect_schema"] == 1
    assert config["connect_notice"]["env_skipped"] == [["acme", "B"]]
    assert _migrate() is None


def test_a_stale_vault_revision_retry_still_adds_the_connections(tmp_path, monkeypatch):
    folder = _seed_desktop(tmp_path)
    canon = _canon(folder)
    real_save = pushkey_vault.save_vault
    attempts = []

    def save_once_stale(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise VaultConflictError("stale_vault_revision")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(pushkey_vault, "save_vault", save_once_stale)

    report = _migrate()

    # The retry runs the migration again on a fresh copy of the config: a copy the first
    # pass had already migrated would save a vault without a single connection.
    assert len(attempts) == 2
    assert report is not None and report.connections_added == 1 and report.moved == ["acme"]
    vault, _ = load_vault(PASSWORD)
    assert _bare(_only(vault["A"]["connections"])) == {"project": canon, "file": ".env", "var": "A"}
    assert list(load_config(strict=True)["projects"]) == [canon]


def test_ensure_migrated_takes_the_config_lock_before_the_vault_lock(tmp_path, monkeypatch):
    _seed_desktop(tmp_path)
    events = []
    real_config_lock, real_vault_lock = pushkey_vault.config_lock, pushkey_vault._cross_process_lock

    def recording(label, real):
        @contextmanager
        def lock(*args, **kwargs):
            events.append(f"{label}+")
            try:
                with real(*args, **kwargs):
                    yield
            finally:
                events.append(f"{label}-")
        return lock

    monkeypatch.setattr(pushkey_vault, "config_lock", recording("config", real_config_lock))
    monkeypatch.setattr(pushkey_vault, "_cross_process_lock", recording("vault", real_vault_lock))

    report = _migrate()

    assert report is not None
    held, inside_config, inverted = [], 0, []
    for event in events:
        label, sign = event[:-1], event[-1]
        if sign == "+":
            if label == "config" and "vault" in held:
                inverted.append(event)  # a config lock taken while the vault lock was held
            if label == "vault" and "config" in held:
                inside_config += 1
            held.append(label)
        else:
            held.remove(label)
    assert inverted == []
    assert inside_config >= 2  # the vault was reloaded and saved while the config lock was held


# -- migration_pending ----------------------------------------------------------------------


def _writers():
    auth = {"vault_key": None, "password": PASSWORD}
    return {
        "connect": lambda folder: pushkey_connect.connect(key_name="A", project=str(folder), actor="test", **auth),
        "sync": lambda folder: pushkey_connect.sync(actor="test", **auth),
        "disconnect": lambda folder: pushkey_connect.disconnect(
            key_name="A", project=str(folder), file=".env", var="A", actor="test", **auth
        ),
        "register_project": lambda folder: pushkey_connect.register_project(str(folder)),
        "unregister_project": lambda folder: pushkey_connect.unregister_project(str(folder), **auth),
    }


def test_connect_before_migration_is_pending(tmp_path):
    folder = _seed_desktop(tmp_path)
    vault_before = _vault_bytes()

    error = _raised(lambda: _writers()["connect"](folder), ConnectError)

    assert error is not None and error.code == "migration_pending"
    assert _vault_bytes() == vault_before


@pytest.mark.parametrize("name", ["connect", "sync", "disconnect", "register_project", "unregister_project"])
def test_write_functions_refuse_until_migrated(tmp_path, name):
    folder = _seed_desktop(tmp_path)
    call = _writers()[name]
    vault_before, config_before = _vault_bytes(), _config_bytes()

    error = _raised(lambda: call(folder), ConnectError)

    assert error is not None and error.code == "migration_pending"
    assert _vault_bytes() == vault_before and _config_bytes() == config_before

    # The refusal is the migration's doing: once it ran, the same call is not refused for that.
    assert _migrate() is not None
    after = _raised(lambda: call(folder), ConnectError)
    assert after is None or after.code != "migration_pending"


# -- dismiss_notice -------------------------------------------------------------------------


def test_dismiss_notice():
    save_config({
        "projects": {}, "connect_schema": 1, "keep": {"a": 1},
        "connect_notice": {"every_key_projects": ["x"], "env_skipped": []},
    })

    dismiss_notice()

    config = load_config(strict=True)
    assert "connect_notice" not in config
    assert config["connect_schema"] == 1 and config["keep"] == {"a": 1}
    dismiss_notice()  # nothing to dismiss: no error
    assert "connect_notice" not in load_config(strict=True)

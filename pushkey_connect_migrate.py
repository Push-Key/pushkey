"""One-time migration of the desktop's name-keyed projects to the shared project store.

Before this feature the desktop kept its projects in ``config["projects"]`` keyed by a
bare name (``{path, keys, added, target_env, ...}``) and the CLI, web app and MCP kept
absolute-path keys (``{name, created}``) plus an allowlist in the vault
(``vault[KEY]["projects"]``). The store is now path-keyed, and every assignment is an
explicit connection ``{project, file, var, added}``. ``plan_migration`` makes that move
on two in-memory dicts; ``ensure_migrated`` runs it once, at unlock, for a
master-password session.

Safe to run again: the old desktop entries move to ``projects_legacy`` (a second run
finds nothing to move), a key that already has a connection to a project gets no new
one (so a key unassigned later stays unassigned even if the ``connect_schema`` marker is
lost), and a store already marked and without name-keyed entries is left alone.

Nothing here reads or reports a key value: reports and notices hold key names, project
names and paths only.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pushkey_connect
import pushkey_projectfs
import pushkey_shared
import pushkey_vault
from pushkey_connect import ConnectError, is_migrated  # noqa: F401  (is_migrated is re-exported)

#: Fields of a desktop entry that become the record's own fields; the rest are extras.
_DESKTOP_FIELDS = ("path", "keys", "added", "target_env")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NOTICE_LISTS = ("every_key_projects", "env_skipped", "unusable", "unregistered")


@dataclass
class MigrationReport:
    """What one migration run did; names and paths only, never a value.

    ``moved``: desktop names whose entry became a path-keyed record. ``unusable``:
    desktop names with no usable path (moved to ``projects_legacy``, nothing else).
    ``env_skipped`` / ``missing_keys``: ``(desktop name, key)`` pairs. ``every_key_projects``:
    projects whose desktop entry had an empty ``keys`` list. ``unregistered``:
    ``(key, path)`` allowlist entries that no registered project covers.
    """

    moved: list[str] = field(default_factory=list)
    connections_added: int = 0
    every_key_projects: list[str] = field(default_factory=list)
    env_skipped: list[tuple[str, str]] = field(default_factory=list)
    missing_keys: list[tuple[str, str]] = field(default_factory=list)
    unusable: list[str] = field(default_factory=list)
    unregistered: list[tuple[str, str]] = field(default_factory=list)


def _is_path_key(key: Any) -> bool:
    return isinstance(key, str) and Path(key).is_absolute()


def _bare_names(projects: Any) -> list:
    """The ``projects`` keys that are not absolute paths (desktop names)."""
    if not isinstance(projects, dict):
        return []
    return [key for key in projects if not _is_path_key(key)]


def _is_done(config: dict) -> bool:
    return config.get("connect_schema") == 1 and not _bare_names(config.get("projects"))


def _usable_path(entry: Any) -> Optional[str]:
    """The canonical folder of a desktop entry, or None when it has no usable path.

    A folder that does not exist (any more) is still usable: it shows up later as
    ``folder_missing`` and is never removed.
    """
    raw = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        return pushkey_projectfs.canonical_project_path(raw, must_exist=False)
    except (pushkey_projectfs.ProjectPathError, RuntimeError, OSError, ValueError):
        return None


def _created(added: Any, today: str) -> str:
    head = added[:10] if isinstance(added, str) else ""
    return head if _DATE.fullmatch(head) else today


def _same_folder(path: Any, project: str) -> bool:
    return isinstance(path, str) and pushkey_connect._path_key(path) == pushkey_connect._path_key(project)


def _allowlisted(entry: dict, project: str) -> bool:
    projects = entry.get("projects")
    return isinstance(projects, list) and any(_same_folder(p, project) for p in projects)


def _has_connection(entry: dict, project: str) -> bool:
    return any(_same_folder(conn.get("project"), project) for conn in pushkey_connect._connections(entry))


def _allow(entry: dict, project: str) -> None:
    if not isinstance(entry.get("projects"), list):
        entry["projects"] = []
    if not _allowlisted(entry, project):
        entry["projects"].append(project)


def _record_for(projects: dict, desktop_name: str, entry: dict, canonical: str, today: str) -> str:
    """Create or complete the path-keyed record for a desktop entry; return its key.

    An existing record (CLI or web) keeps every field it has; only missing ones are filled.
    """
    target_env = entry.get("target_env", "all")
    fields = {
        "name": desktop_name,
        "created": _created(entry.get("added"), today),
        "default_file": ".env",
        "environment": target_env if target_env in pushkey_shared.ENV_LEVELS else "dev",
    }
    for key, value in entry.items():
        if key not in _DESKTOP_FIELDS and key not in fields:
            fields[key] = copy.deepcopy(value)
    key = pushkey_connect._find_registered(pushkey_connect.registered_projects({"projects": projects}), canonical)
    if key is None:
        key = canonical
        projects[key] = {}
    for name, value in fields.items():
        projects[key].setdefault(name, value)
    return key


def _env_allows(target_env: Any, key_env: Any) -> bool:
    """The desktop's own rule (pushkey.py ``inject_env_file``): which keys it ever wrote."""
    return target_env == "all" or key_env == "all" or key_env == target_env


def _merge_notice(config: dict, report: MigrationReport) -> None:
    fresh = {
        "every_key_projects": list(report.every_key_projects),
        "env_skipped": [list(pair) for pair in report.env_skipped],
        "unusable": list(report.unusable),
        "unregistered": [list(pair) for pair in report.unregistered],
    }
    if not any(fresh.values()):
        return
    notice = config.get("connect_notice")
    notice = notice if isinstance(notice, dict) else {}
    for name in _NOTICE_LISTS:
        current = notice.get(name)
        merged = list(current) if isinstance(current, list) else []
        merged.extend(item for item in fresh[name] if item not in merged)
        if merged or name in ("every_key_projects", "env_skipped"):
            notice[name] = merged
    config["connect_notice"] = notice


def plan_migration(vault: dict, config: dict) -> MigrationReport:
    """Move desktop entries into the path-keyed store and connect every assignment.

    Mutates ``vault`` and ``config`` in memory and nothing else. In order: each
    name-keyed entry with a usable path becomes (or completes) a path-keyed record, and
    each of its keys that exists and passes the desktop's environment rule goes on that
    key's allowlist; the old entry moves to ``projects_legacy``. Then every allowlist
    entry that names a registered project and has no connection to it gets
    ``{file ".env", var KEY}``. The project limit is never applied (nothing is removed).
    """
    report = MigrationReport()
    if _is_done(config):
        return report
    projects = config.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    now = datetime.now()
    today, stamp = now.strftime("%Y-%m-%d"), now.strftime(pushkey_connect._TIMESTAMP_FORMAT)

    for name in _bare_names(projects):
        entry = projects.pop(name)
        legacy = config.get("projects_legacy")
        if not isinstance(legacy, dict):
            legacy = config["projects_legacy"] = {}
        legacy[name] = entry
        canonical = _usable_path(entry)
        if canonical is None:
            report.unusable.append(name)
            continue
        report.moved.append(name)
        project = _record_for(projects, name, entry, canonical, today)
        keys = entry.get("keys")
        keys = keys if isinstance(keys, list) else []
        if not keys:
            if project not in report.every_key_projects:
                report.every_key_projects.append(project)
            continue
        target_env = entry.get("target_env", "all")
        for key_name in dict.fromkeys(k for k in keys if isinstance(k, str)):
            key_entry = vault.get(key_name)
            if not isinstance(key_entry, dict):
                report.missing_keys.append((name, key_name))
            elif _env_allows(target_env, key_entry.get("env", "all")):
                _allow(key_entry, project)
            elif not _allowlisted(key_entry, project):
                report.env_skipped.append((name, key_name))

    registered = pushkey_connect.registered_projects({"projects": projects})
    for key_name, key_entry in vault.items():
        allowed = key_entry.get("projects") if isinstance(key_entry, dict) else None
        if not isinstance(allowed, list):
            continue
        for path in allowed:
            if not isinstance(path, str) or not Path(path).is_absolute():
                continue
            project = pushkey_connect._find_registered(registered, path)
            if project is None:
                if not any(k == key_name and _same_folder(p, path) for k, p in report.unregistered):
                    report.unregistered.append((key_name, path))
            elif not _has_connection(key_entry, project):
                connections = key_entry.get("connections")
                if not isinstance(connections, list):
                    connections = key_entry["connections"] = []
                connections.append({"project": project, "file": ".env", "var": key_name, "added": stamp})
                report.connections_added += 1

    config["connect_schema"] = 1
    _merge_notice(config, report)
    return report


def ensure_migrated(
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
) -> Optional[MigrationReport]:
    """Run the migration once, for a master-password session; None when it is already done.

    ``password`` is required: agent-token and recovery sessions never write at unlock
    (``ConnectError("migration_pending")``, nothing touched). Under ``config_lock`` the
    config is read strictly (``ConfigUnreadableError`` propagates: callers log it and
    skip the migration), the vault side is committed first, then the config is saved. A
    failure between the two leaves a vault with connections and a config still in the old
    shape, and a rerun converges. Lock order is config, then vault (nothing takes the
    vault lock and then the config lock).
    """
    if not password:
        raise ConnectError("migration_pending")
    with pushkey_vault.config_lock():
        config = pushkey_vault.load_config(strict=True)
        if _is_done(config):
            return None

        def migrate(fresh: pushkey_vault.VaultData) -> tuple[MigrationReport, dict]:
            # A fresh copy per run: commit may run this twice, and the second run must
            # start from the config as it is on disk, not from one already migrated.
            work = copy.deepcopy(config)
            return plan_migration(fresh, work), work

        saved = pushkey_connect.commit(migrate, vault_key=vault_key, password=password, target=target)
        report, work = saved.value
        pushkey_vault.save_config(work)
        return report


def dismiss_notice() -> None:
    """Remove ``connect_notice`` from the config (no error when there is none)."""

    def drop(config: dict) -> None:
        config.pop("connect_notice", None)

    pushkey_vault.update_config(drop)

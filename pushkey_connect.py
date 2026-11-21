"""Connect keys to project folders: vault commit cycle, key replacement, project registry.

Three foundations every entry point (CLI, MCP, local web API, desktop) shares:

* ``commit`` reloads the vault, applies one change and saves it, retrying once
  when another process saved in between. It never saves a caller's stale copy.
* ``replace_value`` swaps a key's value with rotate behaviour and keeps its
  project links.
* The project registry lives in config.json; removing a project also removes
  every key's link to it.

Nothing here puts a key value in a ConnectError, a message or a log line: error
details hold names, paths and codes only. Collaborators are called as module
attributes (``pushkey_vault.save_vault``) so tests can patch them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import pushkey_health
import pushkey_projectfs
import pushkey_tiers
import pushkey_vault
from pushkey_vault import VaultData

T = TypeVar("T")

#: Timestamp written to ``rotated`` and ``retired`` by replace_value.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
#: Retired values kept per key, newest first (same cap as every rotate path).
_HISTORY_LIMIT = 10
#: One reload-mutate-save pass plus one retry after a concurrent change.
_MAX_COMMIT_ATTEMPTS = 2
#: The only VaultConflictError message that means "someone else saved first".
_STALE_REVISION = "stale_vault_revision"
_HEALTH_WARNING = "health_publication_failed"


class ConnectError(RuntimeError):
    """A refused or failed connect operation.

    ``code`` is the stable machine-readable reason; ``detail`` carries names,
    paths and codes only, never a key value. ``str(error)`` is the code.
    """

    def __init__(self, code: str, detail: Optional[dict] = None):
        super().__init__(code)
        self.code = code
        self.detail = dict(detail) if detail else {}


@dataclass
class CommitResult:
    value: Any
    vault: VaultData
    health_warning: Optional[str]


# -- vault commit cycle ---------------------------------------------------------


def _reload(vault_key: Optional[bytes], password: Optional[str]) -> VaultData:
    if vault_key is not None:
        loaded, _ = pushkey_vault.load_vault_with_key(vault_key)
    elif password is not None:
        loaded, _ = pushkey_vault.load_vault(password)
    else:
        raise ConnectError("vault_unavailable")
    if loaded is None:
        raise ConnectError("vault_unavailable")
    if not isinstance(loaded, VaultData):
        # A vault file that does not exist yet loads as a plain {}. A VaultData
        # lets save_vault record the new revision, which the health publication
        # and the caller's copy both need.
        loaded = VaultData(loaded)
    return loaded


def _save(fresh: VaultData, vault_key: Optional[bytes], password: Optional[str]) -> None:
    if password is not None:
        pushkey_vault.save_vault(fresh, password, vault_key=vault_key)
    else:
        pushkey_vault.save_vault_with_key(fresh, vault_key)


def commit(
    mutate: Callable[[VaultData], T],
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
) -> CommitResult:
    """Reload the vault, apply ``mutate`` to the fresh copy and save it.

    ``mutate`` may run twice: when the vault file changed between the reload and
    the save (``VaultConflictError("stale_vault_revision")``) the cycle starts
    over once, and a second conflict raises ``ConnectError("vault_changed")``.
    It must therefore be safe to run twice and must not call ``commit``: no lock
    is held while it runs (the vault write guard is not reentrant), the save's
    own revision check is what detects a concurrent change. Any other
    VaultConflictError ("expected_revision_required") is a bug and propagates.

    The health sidecar is republished after the save, outside any guard; a
    failure there is reported in ``health_warning``, not raised. ``target``, when
    given, takes over the saved contents and revision.
    """
    attempts = 0
    while True:
        attempts += 1
        fresh = _reload(vault_key, password)
        value = mutate(fresh)
        try:
            _save(fresh, vault_key, password)
            break
        except pushkey_vault.VaultConflictError as error:
            if str(error) != _STALE_REVISION:
                raise
            if attempts >= _MAX_COMMIT_ATTEMPTS:
                raise ConnectError("vault_changed") from error
    # The vault is saved: bring the caller's copy up to date before anything
    # that can still fail.
    if target is not None:
        adopt_vault(target, fresh)
    warning = None
    try:
        pushkey_health.publish_saved_vault(fresh)
    except (pushkey_health.HealthSidecarError, pushkey_vault.VaultBusyError):
        warning = _HEALTH_WARNING
    return CommitResult(value, fresh, warning)


def adopt_vault(target: dict, fresh: VaultData) -> None:
    """Make ``target`` hold ``fresh``'s contents and revision (a session's copy)."""
    if target is fresh:
        return
    revision = getattr(fresh, "_pushkey_revision", None)
    target.clear()
    target.update(fresh)
    try:
        target._pushkey_revision = revision
    except AttributeError:
        pass  # a plain dict cannot carry a revision


# -- key replacement ------------------------------------------------------------


def replace_value(entry: dict, new_value: str, *, now: Optional[str] = None) -> None:
    """Replace a key's value the way a rotation does, keeping everything else.

    The old value goes to the front of ``history`` (newest ten kept) and to
    ``previous``; ``value``, ``rotated`` and ``rotation_count`` are updated.
    ``projects``, ``connections``, ``next_value``, ``env``, ``provider`` and
    ``notes`` are never touched.
    """
    stamp = now if now is not None else datetime.now().strftime(_TIMESTAMP_FORMAT)
    old_value = entry.get("value", "")
    history = entry.get("history")
    if not isinstance(history, list):
        history = []
    entry["history"] = [{"value": old_value, "retired": stamp}, *history][:_HISTORY_LIMIT]
    entry["previous"] = old_value
    entry["value"] = new_value
    entry["rotated"] = stamp
    count = entry.get("rotation_count")
    entry["rotation_count"] = (count if isinstance(count, int) else 0) + 1


# -- project registry -----------------------------------------------------------


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _find_registered(registered: dict[str, dict], canonical: str) -> Optional[str]:
    """The registered key for the folder ``canonical`` names, or None.

    Exact match first; then the same folder spelled differently (separators,
    case on Windows), so one folder is never registered or left registered twice.
    """
    if canonical in registered:
        return canonical
    wanted = _path_key(canonical)
    for key in registered:
        if _path_key(key) == wanted:
            return key
    return None


def registered_projects(config: dict) -> dict[str, dict]:
    """The registered projects of a config: absolute-path keys with a record.

    Desktop entries keyed by a bare project name are not registered projects.
    """
    projects = config.get("projects") if isinstance(config, dict) else None
    if not isinstance(projects, dict):
        return {}
    return {
        key: record
        for key, record in projects.items()
        if isinstance(key, str) and isinstance(record, dict) and Path(key).is_absolute()
    }


def register_project(path: str, *, name: Optional[str] = None) -> tuple[str, dict]:
    """Register a project folder and return ``(canonical path, record)``.

    Raises ConnectError ``project_exists`` or ``project_limit`` (free tier: one
    project), ProjectPathError for a path that is not an existing absolute
    folder and ConfigUnreadableError for a config that cannot be read; in every
    case nothing is written.
    """
    canonical = pushkey_projectfs.canonical_project_path(path)
    label = name.strip() if isinstance(name, str) else ""
    label = label or Path(canonical).name or canonical

    def add(config: dict) -> dict:
        registered = registered_projects(config)
        if _find_registered(registered, canonical) is not None:
            raise ConnectError("project_exists", {"project": canonical})
        if not pushkey_tiers.within_limit("max_projects", len(registered)):
            raise ConnectError(
                "project_limit",
                {"limit": pushkey_tiers.tier_limits().get("max_projects")},
            )
        record = {
            "name": label,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "default_file": ".env",
            "environment": "dev",
        }
        config["projects"][canonical] = record
        return record

    return canonical, pushkey_vault.update_config(add)


def _drop_project_links(vault: VaultData, canonical: str) -> list[str]:
    """Remove ``canonical`` from every key's allowlist and connections; names changed."""
    wanted = _path_key(canonical)
    changed = []
    for name, entry in vault.items():
        if not isinstance(entry, dict):
            continue
        touched = False
        projects = entry.get("projects")
        if isinstance(projects, list):
            kept = [p for p in projects if not (isinstance(p, str) and _path_key(p) == wanted)]
            if len(kept) != len(projects):
                entry["projects"] = kept
                touched = True
        connections = entry.get("connections")
        if isinstance(connections, list):
            kept = [
                c for c in connections
                if not (
                    isinstance(c, dict)
                    and isinstance(c.get("project"), str)
                    and _path_key(c["project"]) == wanted
                )
            ]
            if len(kept) != len(connections):
                entry["connections"] = kept
                touched = True
        if touched:
            changed.append(name)
    return sorted(changed)


def unregister_project(
    path: str,
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
) -> CommitResult:
    """Unregister a project and drop every key's link to it.

    The vault is committed first, then the config record is removed: a failure
    in between leaves a registered project without connections, never
    connections to an unregistered path. The folder need not exist any more.
    An unregistered path raises ConnectError ``project_not_registered`` before
    anything is written; ``CommitResult.value`` lists the key names changed.
    """
    canonical = pushkey_projectfs.canonical_project_path(path, must_exist=False)
    registered = registered_projects(pushkey_vault.load_config(strict=True))
    if _find_registered(registered, canonical) is None:
        raise ConnectError("project_not_registered", {"project": canonical})

    result = commit(
        lambda vault: _drop_project_links(vault, canonical),
        vault_key=vault_key,
        password=password,
        target=target,
    )

    def remove(config: dict) -> None:
        key = _find_registered(registered_projects(config), canonical)
        if key is not None:
            del config["projects"][key]

    pushkey_vault.update_config(remove)
    return result

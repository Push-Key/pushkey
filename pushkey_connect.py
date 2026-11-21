"""Connect keys to project folders: vault commit cycle, key replacement, project
registry, and the operations every entry point (CLI, MCP, local web API, desktop)
shares on top of them.

Foundations:

* ``commit`` reloads the vault, applies one change and saves it, retrying once
  when another process saved in between. It never saves a caller's stale copy.
* ``replace_value`` swaps a key's value with rotate behaviour and keeps its
  project links.
* The project registry lives in config.json; removing a project also removes
  every key's link to it.

Operations: ``preview`` (the confirmation line and what needs confirming),
``connect`` (save, allowlist, connection, then write the env file with a backup
and a .gitignore line), ``sync`` (rewrite every connected file after a key
changed), ``status`` (up to date, out of date, missing, ... per connection),
``disconnect`` and ``suggest`` (project, file and variable candidates).

Nothing here puts a key value in a ConnectError, a message, a result or a log
line: details hold names, paths and codes only. Collaborators are called as
module attributes (``pushkey_vault.save_vault``, ``pushkey_projectfs.atomic_project_write``)
so tests can patch them.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional, TypeVar

import pushkey_env
import pushkey_health
import pushkey_projectfs
import pushkey_providers
import pushkey_tiers
import pushkey_vault
from pushkey_crypto import log_event
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

    A connect that races an unregister can still leave links to a path that is
    no longer registered; this is the cleanup. When the path is not registered
    but some key still lists it, those links are swept in the same vault commit
    and the config is left alone. ``project_not_registered`` is raised, with
    nothing saved, only when there is nothing to remove at all.
    ``CommitResult.value`` lists the key names changed.
    """
    canonical = pushkey_projectfs.canonical_project_path(path, must_exist=False)
    registered = registered_projects(pushkey_vault.load_config(strict=True))
    was_registered = _find_registered(registered, canonical) is not None

    def drop(vault: VaultData) -> list[str]:
        changed = _drop_project_links(vault, canonical)
        if not changed and not was_registered:
            raise ConnectError("project_not_registered", {"project": canonical})
        return changed

    result = commit(drop, vault_key=vault_key, password=password, target=target)
    if was_registered:

        def remove(config: dict) -> None:
            key = _find_registered(registered_projects(config), canonical)
            if key is not None:
                del config["projects"][key]

        pushkey_vault.update_config(remove)
    return result


# -- connections: shapes and shared helpers -----------------------------------------

_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BARE_CR = re.compile(r"\r(?!\n)")
#: Variable-name prefixes that frameworks bundle into browser code (spec 5.5).
_BROWSER_PREFIXES = (
    "NEXT_PUBLIC_", "VITE_", "PUBLIC_", "REACT_APP_", "EXPO_PUBLIC_", "NUXT_PUBLIC_",
)
#: A key or variable name carrying one of these is meant to be public.
_PUBLIC_NAME_MARKERS = ("ANON", "PUBLISHABLE", "PUBLIC_KEY", "_URL", "CLIENT_ID")
#: A value starting with one of these is a publishable key.
_PUBLIC_VALUE_PREFIXES = ("pk_", "sb_publishable_")
#: Read-only env files that list variable names for suggestions.
_TEMPLATE_FILES = (".env.example", ".env.sample")
#: Most bytes read from one env file when collecting variable names.
_NAMES_READ_LIMIT = 1_000_000
#: Files whose names suggest a framework that reads ``.env.local``.
_FRAMEWORK_CONFIG_PREFIXES = ("next.config.", "vite.config.")


@dataclass
class Preview:
    """What a connect would do, with the exact line to show the user.

    ``needs_confirm`` lists the extra confirmations ``connect`` will ask for
    (``env_mismatch``, ``public_prefix``); ``conflict_key`` is the key that holds
    the variable now, set only when the caller asked to take it over.
    """

    key: str
    project: str
    project_name: str
    file: str
    var: str
    environment: str
    line: str
    change: Literal["add", "replace", "none"]
    gitignore_change: bool
    needs_confirm: list[str]
    conflict_key: Optional[str]


@dataclass
class ConnectResult:
    """The outcome of one connection write; never carries a value.

    ``written`` is True when the file holds the key's value afterwards (also
    when it did already, ``change == "none"``). When False, ``reason`` says why
    and the connection stays in the vault.
    """

    key: str
    project: str
    file: str
    var: str
    written: bool
    reason: Optional[str]
    change: str
    gitignore_changed: bool
    health_warning: Optional[str]


@dataclass
class ConnectionStatus:
    """Where one connection stands; never carries a value."""

    key: str
    project: str
    project_name: str
    file: str
    var: str
    state: Literal[
        "up_to_date", "out_of_date", "not_in_file", "file_missing",
        "folder_missing", "not_ignored", "not_written",
    ]
    reason: Optional[str]


@dataclass
class Suggestion:
    """Candidates for a connect, each ``(value, reason)``; names only, never values."""

    projects: list[tuple[str, str]]
    files: list[tuple[str, str]]
    vars: list[tuple[str, str]]


@dataclass
class _Plan:
    """A connect resolved against a vault and a config (holds no key value)."""

    project: str
    project_name: str
    environment: str
    file: str
    var: str
    needs_confirm: list[str]
    conflicts: list[str]


@dataclass
class _WriteOutcome:
    """What writing one file did: ``reason`` None means the file is up to date."""

    reason: Optional[str]
    changes: dict[str, str]
    gitignore_changed: bool


def is_migrated(config: dict) -> bool:
    """True when the project registry is in the path-keyed shape.

    That is the case when ``connect_schema`` is 1, or when no entry of
    ``projects`` is keyed by a bare name (a key that is not an absolute path).
    """
    if config.get("connect_schema") == 1:
        return True
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return True
    return all(isinstance(key, str) and Path(key).is_absolute() for key in projects)


def _text(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _norm_file(file: Any) -> str:
    """``file`` as a normalised relative path, or as given when it is not a valid one."""
    if not isinstance(file, str):
        return ""
    try:
        return pushkey_projectfs.validate_env_relpath(file)
    except pushkey_projectfs.ProjectPathError:
        return file


def _is_env_path(file: str) -> bool:
    """Whether ``file`` is already a normalised, allowed env file path."""
    try:
        return pushkey_projectfs.validate_env_relpath(file) == file
    except pushkey_projectfs.ProjectPathError:
        return False


def _connections(entry: Any) -> list[dict]:
    """The connection dicts of a vault entry (the live dicts, so callers may edit them)."""
    connections = entry.get("connections") if isinstance(entry, dict) else None
    if not isinstance(connections, list):
        return []
    return [conn for conn in connections if isinstance(conn, dict)]


def _matches(conn: dict, project: str, file: str, var: str) -> bool:
    """Whether ``conn`` is the connection ``(project, file, var)``.

    The folder compares as ``_find_registered`` does; the file compares
    case-insensitively because NTFS and macOS open one file under any case.
    """
    conn_project = conn.get("project")
    return (
        isinstance(conn_project, str)
        and _path_key(conn_project) == _path_key(project)
        and _norm_file(conn.get("file")).casefold() == _norm_file(file).casefold()
        and conn.get("var") == var
    )


def _project_label(registered: dict[str, dict], project: str) -> str:
    key = _find_registered(registered, project)
    record = registered[key] if key is not None else {}
    return _text(record.get("name"), Path(project).name or project)


def _bundled_in_browser(key_name: str, var: str, value: Any) -> bool:
    """Whether ``var`` is bundled into browser code and the key is not meant to be public."""
    if not var.startswith(_BROWSER_PREFIXES):
        return False
    names = f"{key_name} {var}".upper()
    if any(marker in names for marker in _PUBLIC_NAME_MARKERS):
        return False
    return not ("" if value is None else str(value)).startswith(_PUBLIC_VALUE_PREFIXES)


def _resolve(
    vault: dict,
    config: dict,
    *,
    key_name: str,
    project: str,
    file: Optional[str],
    var: Optional[str],
    value: Optional[str],
    env: Optional[str],
    replace_source: bool,
) -> _Plan:
    """Resolve defaults and run every check that needs only the vault and the config.

    ``value`` and ``env`` describe a key that is not in the vault yet (or a
    replacement value); the confirmation checks use them in place of the stored
    ones. Raises ConnectError (``key_not_found``, ``project_not_registered``,
    ``invalid_var``, ``var_taken``) or ProjectPathError for a refused file path.
    """
    entry = vault.get(key_name)
    entry = entry if isinstance(entry, dict) else None
    if entry is None and value is None:
        raise ConnectError("key_not_found", {"key": key_name})

    registered = registered_projects(config)
    canonical = pushkey_projectfs.canonical_project_path(project, must_exist=False)
    project_key = _find_registered(registered, canonical)
    if project_key is None:
        raise ConnectError("project_not_registered", {"project": canonical})
    record = registered[project_key]
    environment = _text(record.get("environment"), "dev")

    relpath = pushkey_projectfs.validate_env_relpath(file or _text(record.get("default_file"), ".env"))
    name = var or key_name
    if not isinstance(name, str) or not _VAR_NAME.fullmatch(name):
        raise ConnectError("invalid_var", {"var": name if isinstance(name, str) else None})

    conflicts = sorted(
        other
        for other, other_entry in vault.items()
        if other != key_name
        and any(_matches(conn, project_key, relpath, name) for conn in _connections(other_entry))
    )
    if conflicts and not replace_source:
        raise ConnectError("var_taken", {"key": conflicts[0]})

    key_env = entry.get("env") if entry is not None else (env or "dev")
    candidate = value if value is not None else (entry or {}).get("value")
    needs = []
    if key_env not in (environment, "all"):
        needs.append("env_mismatch")
    if _bundled_in_browser(key_name, name, candidate):
        needs.append("public_prefix")
    return _Plan(
        project=project_key,
        project_name=_text(record.get("name"), Path(project_key).name or project_key),
        environment=environment,
        file=relpath,
        var=name,
        needs_confirm=needs,
        conflicts=conflicts,
    )


# -- connections: reading and writing the env file ------------------------------------


def _check_target(project: str, relpath: str) -> tuple[Path, tuple[int, int]]:
    """Resolve ``relpath`` below the registered ``project`` and refuse a file git tracks.

    Returns the file's absolute path and the project folder's identity (for the
    write). Raises ProjectPathError for a folder or path that is not usable and
    ConnectError ``file_tracked_by_git``. Nothing is written.
    """
    try:
        identity = pushkey_projectfs.project_identity(Path(project))
    except OSError:
        raise pushkey_projectfs.ProjectPathError(400, "project directory not found") from None
    target = pushkey_projectfs.resolve_project_target(project, relpath, identity)
    if pushkey_projectfs.is_git_tracked(project, relpath):
        raise ConnectError("file_tracked_by_git", {"file": relpath})
    return target, identity


def _read_env(target: Path) -> Optional[bytes]:
    """The bytes of an env file, or None when it does not exist.

    Bytes, never ``read_text``: that would turn CRLF into LF and a BOM into text.
    """
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise ConnectError("read_failed") from None


def _decode_env(raw: Optional[bytes]) -> str:
    if raw is None:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConnectError("invalid_env_file") from None


def _change_for(text: str, var: str, value: Any) -> str:
    """What writing ``value`` to ``var`` would do to env ``text``: add, replace or none."""
    lines = [line for line in pushkey_env.parse_env_lines(text) if line.name == var]
    if not lines:
        return "add"
    wanted = pushkey_env.normalize_env_value(value)
    if all(pushkey_env.decode_env_value(line.value_text) == wanted for line in lines):
        return "none"
    return "replace"


def _gitignore_covers_file(project: str, relpath: str, identity: tuple[int, int]) -> bool:
    """Whether the project's own .gitignore already lists ``relpath`` (read only).

    Decodes the way ``ensure_project_gitignore`` does, so a status read and the
    writer cannot disagree.
    """
    path = pushkey_projectfs.resolve_project_target(project, ".gitignore", identity)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raw = b""
    return pushkey_projectfs._gitignore_covers(raw.decode("utf-8-sig", errors="replace"), relpath)


def _backup_then_write(project: str, relpath: str, identity: tuple[int, int], old: Optional[bytes], new: bytes) -> None:
    """Back up ``old`` (when the file exists) outside the project, then replace it atomically."""
    if old is not None:
        try:
            pushkey_env.backup_env_file(Path(project), relpath, old)
        except OSError:
            raise ConnectError("backup_failed") from None
    pushkey_projectfs.atomic_project_write(project, relpath, new, identity)


def _write_assignments(project: str, file: str, values: dict[str, Any]) -> _WriteOutcome:
    """Set each variable of ``values`` in the env file ``file`` of the registered ``project``.

    Everything that can refuse runs first and has no side effect: the path
    shape, the git-tracked check, reading and decoding the file, and rendering
    the new text. Then, in the spec's order, the file is backed up and
    replaced, and the project's .gitignore is made to list it. A file that
    already holds every value is not rewritten, but its .gitignore is still
    checked. Nothing raises: a refusal or failure is the outcome's ``reason``.
    """
    changes: dict[str, str] = {}
    wrote = False
    try:
        relpath = pushkey_projectfs.validate_env_relpath(file)
        target, identity = _check_target(project, relpath)
        raw = _read_env(target)
        text = _decode_env(raw)
        changes = {var: _change_for(text, var, value) for var, value in values.items()}
        if any(change != "none" for change in changes.values()):
            rendered = {var: pushkey_env.render_connected_value(value) for var, value in values.items()}
            try:
                new_text, _added, _updated = pushkey_env.apply_env_assignments(text, rendered)
                new_bytes = new_text.encode("utf-8")
            except ValueError:
                raise ConnectError("invalid_env_file") from None
            _backup_then_write(project, relpath, identity, raw, new_bytes)
            wrote = True
        gitignore_changed = pushkey_projectfs.ensure_project_gitignore(project, relpath, identity)
    except pushkey_projectfs.ProjectPathError as error:
        return _WriteOutcome(error.reason, changes if wrote else {}, False)
    except ConnectError as error:
        return _WriteOutcome(error.code, changes if wrote else {}, False)
    except OSError:
        return _WriteOutcome("write_failed", changes if wrote else {}, False)
    return _WriteOutcome(None, changes, gitignore_changed)


def _without_variable(text: str, var: str) -> str:
    """``text`` without the assignment lines of ``var`` (a multi-line value goes whole)."""
    bom, lines = pushkey_env._split_env_text(text)
    dropped: set[int] = set()
    for first, last, match in pushkey_env._assignment_spans(lines):
        if match["name"] == var:
            dropped.update(range(first, last + 1))
    if not dropped:
        return text
    return bom + "".join(
        content + ending for index, (content, ending) in enumerate(lines) if index not in dropped
    )


def _remove_variable(project: str, file: str, var: str) -> tuple[bool, Optional[str]]:
    """Remove ``var``'s line from the env file; ``(removed, reason)``, never raises.

    A line removal is a write: it takes the same guards as ``_write_assignments``
    and keeps a backup of the old file. A file or variable that is not there is
    not a failure, just nothing removed.
    """
    try:
        relpath = pushkey_projectfs.validate_env_relpath(file)
        target, identity = _check_target(project, relpath)
        raw = _read_env(target)
        if raw is None:
            return False, None
        text = _decode_env(raw)
        shortened = _without_variable(text, var)
        if shortened == text:
            return False, None
        if _BARE_CR.search(text):
            raise ConnectError("invalid_env_file")
        _backup_then_write(project, relpath, identity, raw, shortened.encode("utf-8"))
    except pushkey_projectfs.ProjectPathError as error:
        return False, error.reason
    except ConnectError as error:
        return False, error.code
    except OSError:
        return False, "write_failed"
    return True, None


def _record_last_errors(
    known: dict,
    updates: list[tuple[str, str, str, str, Optional[str]]],
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict],
) -> Optional[str]:
    """Set (reason) or clear (None) ``last_error`` on connections, in one save.

    ``updates`` holds ``(key, project, file, var, reason)``. Nothing is saved
    when ``known`` already agrees. The file outcome is the truth the caller
    reports, so a save that cannot complete (``vault_changed``, a busy vault)
    only leaves the old ``last_error`` in place. Returns the health warning.
    """

    def connections(vault: dict, key: str, project: str, file: str, var: str):
        return [conn for conn in _connections(vault.get(key)) if _matches(conn, project, file, var)]

    if not any(
        conn.get("last_error") != reason
        for key, project, file, var, reason in updates
        for conn in connections(known, key, project, file, var)
    ):
        return None

    def mutate(fresh: VaultData) -> None:
        for key, project, file, var, reason in updates:
            for conn in connections(fresh, key, project, file, var):
                if reason is None:
                    conn.pop("last_error", None)
                else:
                    conn["last_error"] = reason

    try:
        return commit(mutate, vault_key=vault_key, password=password, target=target).health_warning
    except (ConnectError, pushkey_vault.VaultBusyError):
        return None


# -- preview and connect ----------------------------------------------------------------


def preview(
    vault: dict,
    config: dict,
    *,
    key_name: str,
    project: str,
    file: Optional[str] = None,
    var: Optional[str] = None,
    replace_source: bool = False,
) -> Preview:
    """Resolve a connect and say what it would do; reads the env file, writes nothing.

    ``file`` defaults to the project's ``default_file`` and ``var`` to the key
    name. Raises ConnectError (``key_not_found``, ``project_not_registered``,
    ``invalid_var``, ``var_taken`` with ``detail["key"]``, ``file_tracked_by_git``)
    and ProjectPathError for a refused path. With ``replace_source=True`` a
    variable another key holds is not an error: ``conflict_key`` names that key.
    """
    plan = _resolve(
        vault, config, key_name=key_name, project=project, file=file, var=var,
        value=None, env=None, replace_source=replace_source,
    )
    target, identity = _check_target(plan.project, plan.file)
    text = _decode_env(_read_env(target))
    return Preview(
        key=key_name,
        project=plan.project,
        project_name=plan.project_name,
        file=plan.file,
        var=plan.var,
        environment=plan.environment,
        line=f"Save to {plan.project_name} -> {plan.environment} -> {plan.file} as {plan.var}",
        change=_change_for(text, plan.var, vault[key_name].get("value")),
        gitignore_change=not _gitignore_covers_file(plan.project, plan.file, identity),
        needs_confirm=plan.needs_confirm,
        conflict_key=plan.conflicts[0] if plan.conflicts else None,
    )


def _drop_connection(entry: dict, project: str, file: str, var: str) -> bool:
    """Remove ``(project, file, var)`` from ``entry``; True when it was there.

    The project leaves the key's allowlist when that was its last connection to it.
    """
    connections = entry.get("connections")
    if not isinstance(connections, list):
        return False
    kept = [
        conn for conn in connections
        if not (isinstance(conn, dict) and _matches(conn, project, file, var))
    ]
    if len(kept) == len(connections):
        return False
    entry["connections"] = kept
    if not any(
        isinstance(conn.get("project"), str) and _path_key(conn["project"]) == _path_key(project)
        for conn in _connections(entry)
    ):
        projects = entry.get("projects")
        if isinstance(projects, list):
            entry["projects"] = [
                p for p in projects if not (isinstance(p, str) and _path_key(p) == _path_key(project))
            ]
    return True


def _add_connection(entry: dict, plan: _Plan, stamp: str) -> None:
    """Allowlist the project and record the connection (once) on ``entry``."""
    projects = entry.get("projects")
    if not isinstance(projects, list):
        projects = entry["projects"] = []
    if not any(isinstance(p, str) and _path_key(p) == _path_key(plan.project) for p in projects):
        projects.append(plan.project)
    connections = entry.get("connections")
    if not isinstance(connections, list):
        connections = entry["connections"] = []
    if not any(_matches(conn, plan.project, plan.file, plan.var) for conn in _connections(entry)):
        connections.append(
            {"project": plan.project, "file": plan.file, "var": plan.var, "added": stamp}
        )


def connect(
    *,
    key_name: str,
    project: str,
    file: Optional[str] = None,
    var: Optional[str] = None,
    value: Optional[str] = None,
    replace: bool = False,
    provider: Optional[str] = None,
    env: Optional[str] = None,
    notes: str = "",
    write: bool = True,
    confirmed: Iterable[str] = (),
    replace_source: bool = False,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
    actor: str,
) -> ConnectResult:
    """Connect a key to a variable in a project's env file and write it.

    With ``value`` the key is added (a new name) or replaced (an existing name,
    only with ``replace=True``; otherwise ``key_exists``). In order: every check
    (nothing is saved or written when one fails, including
    ``confirmation_required`` with ``detail["needs"]`` listing the extra
    confirmations ``confirmed`` lacks), then one vault save (key, allowlist,
    connection), then the file (backup, write, .gitignore) unless ``write`` is
    False, then the audit line. A file failure never undoes the connection: the
    result has ``written=False`` and a ``reason``, and the connection records it
    as ``last_error`` until a ``sync`` succeeds.
    """
    approved = frozenset(confirmed)
    stamp = datetime.now().strftime(_TIMESTAMP_FORMAT)

    def apply(fresh: VaultData) -> _Plan:
        entry = fresh.get(key_name)
        exists = isinstance(entry, dict)
        if exists and value is not None and not replace:
            raise ConnectError("key_exists", {"key": key_name})
        # Read inside the save, so a project unregistered since the caller looked
        # cannot be linked to (an unregister racing this connect).
        config = pushkey_vault.load_config(strict=True)
        plan = _resolve(
            fresh, config, key_name=key_name, project=project, file=file, var=var,
            value=value, env=env, replace_source=replace_source,
        )
        _check_target(plan.project, plan.file)
        missing = [code for code in plan.needs_confirm if code not in approved]
        if missing:
            raise ConnectError("confirmation_required", {"needs": missing})
        if not exists:
            entry = fresh[key_name] = {
                "value": value,
                "created": stamp,
                "rotated": None,
                "provider": provider or pushkey_providers.detect_provider(key_name, value) or "Unknown",
                "env": env or "dev",
                "projects": [],
                "connections": [],
                "notes": notes,
                "rotation_count": 0,
            }
        elif value is not None:
            replace_value(entry, value)
        _add_connection(entry, plan, stamp)
        for other in plan.conflicts:
            _drop_connection(fresh[other], plan.project, plan.file, plan.var)
        return plan

    saved = commit(apply, vault_key=vault_key, password=password, target=target)
    plan = saved.value
    warning = saved.health_warning
    if write:
        outcome = _write_assignments(plan.project, plan.file, {plan.var: saved.vault[key_name].get("value")})
        recorded = _record_last_errors(
            saved.vault,
            [(key_name, plan.project, plan.file, plan.var, outcome.reason)],
            vault_key=vault_key, password=password, target=target,
        )
        warning = warning or recorded
    else:
        outcome = _WriteOutcome("write_skipped", {}, False)
    log_event(f"{actor}: connected {key_name} -> {plan.project_name} {plan.file} as {plan.var}")
    return ConnectResult(
        key=key_name,
        project=plan.project,
        file=plan.file,
        var=plan.var,
        written=outcome.reason is None,
        reason=outcome.reason,
        change=outcome.changes.get(plan.var, "none"),
        gitignore_changed=outcome.gitignore_changed,
        health_warning=warning,
    )


# -- sync, status, disconnect -----------------------------------------------------------


def sync(
    *,
    key_name: Optional[str] = None,
    project: Optional[str] = None,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
    actor: str,
) -> list[ConnectResult]:
    """Rewrite every matching connection's variable with the key's current value.

    One result per connection, in vault order; nothing raises for a single
    connection: a refusal or failure is that result's ``reason`` (and its
    ``last_error``). Connections to the same file are written together, so one
    sync makes one backup per file. A folder that is not on this computer gives
    ``folder_missing`` and records nothing: it is a state, not an error.
    """
    vault = _reload(vault_key, password)
    registered = registered_projects(pushkey_vault.load_config(strict=True))
    if key_name is not None and not isinstance(vault.get(key_name), dict):
        raise ConnectError("key_not_found", {"key": key_name})
    wanted = None
    if project is not None:
        wanted = _path_key(pushkey_projectfs.canonical_project_path(project, must_exist=False))

    rows = []  # (key, project, file, var)
    for name, entry in vault.items():
        if key_name is not None and name != key_name:
            continue
        for conn in _connections(entry):
            conn_project, conn_file, conn_var = conn.get("project"), conn.get("file"), conn.get("var")
            if not all(isinstance(part, str) for part in (conn_project, conn_file, conn_var)):
                continue
            if wanted is not None and _path_key(conn_project) != wanted:
                continue
            rows.append((name, conn_project, conn_file, conn_var))

    groups: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for row in rows:
        groups.setdefault((_path_key(row[1]), _norm_file(row[2]).casefold()), []).append(row)

    outcomes: dict[tuple[str, str], _WriteOutcome] = {}
    for group_key, group in groups.items():
        _, group_project, group_file, _ = group[0]
        registered_key = _find_registered(registered, group_project)
        if registered_key is None:
            outcomes[group_key] = _WriteOutcome("project_not_registered", {}, False)
        elif not Path(registered_key).is_dir():
            outcomes[group_key] = _WriteOutcome("folder_missing", {}, False)
        else:
            values = {
                var: vault[name].get("value")
                for name, _, _, var in group
                if _VAR_NAME.fullmatch(var)
            }
            outcomes[group_key] = (
                _write_assignments(registered_key, group_file, values)
                if values
                else _WriteOutcome(None, {}, False)
            )

    results = []
    updates = []
    for name, row_project, row_file, row_var in rows:
        outcome = outcomes[(_path_key(row_project), _norm_file(row_file).casefold())]
        reason = outcome.reason
        if reason is None and not _VAR_NAME.fullmatch(row_var):
            reason = "invalid_var"
        change = outcome.changes.get(row_var, "none") if reason is None else "none"
        if reason != "folder_missing":
            updates.append((name, row_project, row_file, row_var, reason))
        if reason is None and change != "none":
            log_event(
                f"{actor}: synced {name} -> {_project_label(registered, row_project)} {row_file} as {row_var}"
            )
        results.append(
            ConnectResult(
                key=name, project=row_project, file=row_file, var=row_var,
                written=reason is None, reason=reason, change=change,
                gitignore_changed=outcome.gitignore_changed, health_warning=None,
            )
        )
    warning = _record_last_errors(
        vault, updates, vault_key=vault_key, password=password, target=target
    )
    if warning:
        for result in results:
            result.health_warning = warning
    return results


def _connection_state(project: str, file: str, var: str, value: Any, last_error: Any):
    """``(state, reason)`` of one connection, read from the file without changing anything."""
    folder = Path(project)
    if not folder.is_dir():
        return "folder_missing", None
    state, reason = _file_state(folder, project, file, var, value)
    if state not in ("up_to_date", "not_written") and last_error:
        return "not_written", str(last_error)
    return state, reason


def _file_state(folder: Path, project: str, file: str, var: str, value: Any):
    try:
        relpath = pushkey_projectfs.validate_env_relpath(file)
    except pushkey_projectfs.ProjectPathError as error:
        return "not_written", error.reason
    try:
        identity = pushkey_projectfs.project_identity(folder)
        target = pushkey_projectfs.resolve_project_target(project, relpath, identity)
    except pushkey_projectfs.ProjectPathError as error:
        if not (folder / relpath).parent.is_dir():
            return "file_missing", None
        return "not_written", error.reason
    except OSError:
        return "folder_missing", None
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return "file_missing", None
    except OSError:
        return "not_written", "read_failed"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "not_written", "invalid_env_file"
    lines = [line for line in pushkey_env.parse_env_lines(text) if line.name == var]
    if not lines:
        return "not_in_file", None
    wanted = pushkey_env.normalize_env_value(value)
    if any(pushkey_env.decode_env_value(line.value_text) != wanted for line in lines):
        return "out_of_date", None
    try:
        if not _gitignore_covers_file(project, relpath, identity):
            return "not_ignored", None
    except pushkey_projectfs.ProjectPathError as error:
        return "not_written", error.reason
    except OSError:
        return "not_written", "read_failed"
    return "up_to_date", None


def status(
    vault: dict,
    config: dict,
    *,
    key_name: Optional[str] = None,
    project: Optional[str] = None,
) -> list[ConnectionStatus]:
    """Where each connection stands, read from the files; values never appear.

    A connection that has a ``last_error`` and is not up to date reads
    ``not_written`` with that reason; a folder that is gone is ``folder_missing``
    either way. A refused path (a template name, a link) is ``not_written`` too.
    """
    registered = registered_projects(config)
    wanted = None
    if project is not None:
        wanted = _path_key(pushkey_projectfs.canonical_project_path(project, must_exist=False))
    statuses = []
    for name, entry in vault.items():
        if key_name is not None and name != key_name:
            continue
        for conn in _connections(entry):
            conn_project, conn_file, conn_var = conn.get("project"), conn.get("file"), conn.get("var")
            if not all(isinstance(part, str) for part in (conn_project, conn_file, conn_var)):
                continue
            if wanted is not None and _path_key(conn_project) != wanted:
                continue
            state, reason = _connection_state(
                conn_project, conn_file, conn_var, entry.get("value"), conn.get("last_error")
            )
            statuses.append(
                ConnectionStatus(
                    key=name, project=conn_project,
                    project_name=_project_label(registered, conn_project),
                    file=conn_file, var=conn_var, state=state, reason=reason,
                )
            )
    return statuses


def disconnect(
    *,
    key_name: str,
    project: str,
    file: str,
    var: str,
    remove_line: bool = False,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
    actor: str,
) -> CommitResult:
    """Remove one connection (and the project from the allowlist when it was the last).

    ``key_not_found`` / ``connection_not_found`` refuse before anything is saved.
    With ``remove_line=True`` the variable's line is then taken out of the env file
    (a write, so it keeps the same guards and a backup). The vault is committed
    first and never rolled back for a file problem: ``CommitResult.value`` is
    ``{"line_removed": bool, "reason": Optional[str]}``.
    """
    canonical = pushkey_projectfs.canonical_project_path(project, must_exist=False)

    def apply(fresh: VaultData) -> None:
        entry = fresh.get(key_name)
        if not isinstance(entry, dict):
            raise ConnectError("key_not_found", {"key": key_name})
        if not _drop_connection(entry, canonical, file, var):
            raise ConnectError(
                "connection_not_found",
                {"key": key_name, "project": canonical, "file": file, "var": var},
            )

    saved = commit(apply, vault_key=vault_key, password=password, target=target)
    registered = registered_projects(pushkey_vault.load_config())
    removed, reason = False, None
    if remove_line:
        registered_key = _find_registered(registered, canonical)
        if registered_key is None:
            reason = "project_not_registered"
        elif not Path(registered_key).is_dir():
            reason = "folder_missing"
        else:
            removed, reason = _remove_variable(registered_key, file, var)
    log_event(
        f"{actor}: disconnected {key_name} -> {_project_label(registered, canonical)} "
        f"{_norm_file(file)} as {var}"
    )
    return CommitResult(
        {"line_removed": removed, "reason": reason}, saved.vault, saved.health_warning
    )


# -- suggestions ------------------------------------------------------------------------


def _has_framework_config(project: str) -> bool:
    try:
        return any(name.startswith(_FRAMEWORK_CONFIG_PREFIXES) for name in os.listdir(project))
    except OSError:
        return False


def _env_names(project: str, relpath: str) -> list[str]:
    """The variable names of an env file (never its values); nothing for a link or a missing file."""
    folder = Path(project)
    try:
        if relpath in _TEMPLATE_FILES:
            path = folder / relpath
            if pushkey_projectfs.is_link_or_reparse(folder) or pushkey_projectfs.is_link_or_reparse(path):
                return []
        else:
            path = pushkey_projectfs.resolve_project_target(
                project, relpath, pushkey_projectfs.project_identity(folder)
            )
        with path.open("rb") as handle:
            raw = handle.read(_NAMES_READ_LIMIT)
    except (OSError, pushkey_projectfs.ProjectPathError):
        return []
    text = raw.decode("utf-8", errors="replace")
    return [line.name for line in pushkey_env.parse_env_lines(text)]


def suggest(
    vault: dict,
    config: dict,
    *,
    key_name: str,
    value: Optional[str] = None,
    cwd: Optional[str] = None,
    project: Optional[str] = None,
) -> Suggestion:
    """Candidate projects, files and variable names for connecting ``key_name``.

    Each is ``(value, reason)``. Projects: the current folder, the last used one,
    projects other keys of the same provider are connected to; only registered
    projects. Files and variables are for ``project``, or for the first suggested
    project when none is given. Variable names come from ``.env.example``,
    ``.env.sample`` and the suggested files, kept when they match the provider's
    patterns and no key uses them in that project yet. Names only: no value is
    read into the result.
    """
    registered = registered_projects(config)
    entry = vault.get(key_name)
    provider = entry.get("provider") if isinstance(entry, dict) else None
    if not provider:
        provider = pushkey_providers.detect_provider(key_name, value or "")

    projects: list[tuple[str, str]] = []

    def offer(path: Any, reason: str) -> None:
        key = _find_registered(registered, path) if isinstance(path, str) else None
        if key is not None and all(_path_key(key) != _path_key(known) for known, _ in projects):
            projects.append((key, reason))

    if cwd:
        try:
            offer(pushkey_projectfs.canonical_project_path(cwd, must_exist=False), "current folder")
        except pushkey_projectfs.ProjectPathError:
            pass
    offer(config.get("last_project"), "last used")
    if provider and provider != "Unknown":
        for other, other_entry in sorted(vault.items(), key=lambda item: item[0]):
            if other != key_name and isinstance(other_entry, dict) and other_entry.get("provider") == provider:
                for conn in _connections(other_entry):
                    offer(conn.get("project"), f"used with other {provider} keys")

    chosen = None
    if project is not None:
        try:
            chosen = _find_registered(
                registered, pushkey_projectfs.canonical_project_path(project, must_exist=False)
            )
        except pushkey_projectfs.ProjectPathError:
            chosen = None
    elif projects:
        chosen = projects[0][0]

    files: list[tuple[str, str]] = []
    if chosen is not None:
        default = _text(registered[chosen].get("default_file"), ".env")
        if default != ".env" and _is_env_path(default):
            files.append((default, "project default"))
        if _has_framework_config(chosen) and all(name != ".env.local" for name, _ in files):
            files.append((".env.local", "Next.js or Vite project"))
        files.append((".env", "default env file"))

    found: list[tuple[str, str]] = []
    patterns = (pushkey_providers.PROVIDERS.get(provider) or {}).get("patterns", []) if provider else []
    if chosen is not None and patterns:
        in_use = {
            conn.get("var")
            for other_entry in vault.values()
            for conn in _connections(other_entry)
            if isinstance(conn.get("project"), str) and _path_key(conn["project"]) == _path_key(chosen)
        }
        for relpath in (*_TEMPLATE_FILES, *(name for name, _ in files)):
            for name in _env_names(chosen, relpath):
                if name in in_use or any(name == known for known, _ in found):
                    continue
                if any(pattern in name.lower() for pattern in patterns):
                    found.append((name, f"found in {relpath}"))
    if _VAR_NAME.fullmatch(key_name) and all(name != key_name for name, _ in found):
        found.append((key_name, "same as the key name"))
    return Suggestion(projects=projects, files=files, vars=found)

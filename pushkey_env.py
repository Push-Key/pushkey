"""Shared .env mutation helpers for CLI, MCP, and the local API."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional

import pushkey_shared as _s


_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

#: Backups older Pushkey versions wrote into the project folder.
LEGACY_BACKUP_GLOB = ".env.pushkey_backup_*"

_BACKUP_KEEP = 3
_BACKUP_STAMP_FORMAT = "%Y%m%d_%H%M%S_%f"


@dataclass(frozen=True)
class EnvMutationResult:
    env_file: str
    injected_names: list[str]
    updated_names: list[str]
    skipped_existing: list[str]
    wrote: bool

    @property
    def changed_count(self) -> int:
        return len(self.injected_names) + len(self.updated_names)


def format_env_value(value: object) -> str:
    value = str(value) if value is not None else ""
    needs_quotes = (
        not value
        or value[0].isspace()
        or value[-1].isspace()
        or any(ch in value for ch in ("\n", "\r", "\t", " ", "#", '"'))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def sanitize_env_value(value: object) -> str:
    return str(value).replace("\r", "").replace("\n", "")


def project_id(project: Path) -> str:
    """Stable 16-hex-char id of a project folder, used to group its backups."""
    resolved = str(Path(project).resolve())
    return hashlib.sha256(resolved.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _private_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # best effort, as for the vault files; some filesystems ignore modes


def _backup_stamps(directory: Path, safe_name: str) -> list[tuple[str, Path]]:
    """Backups of one file in `directory`, oldest first.

    The match is exact so that backing up `.env` never touches the backups of
    `.env.local` (`.env.local.<stamp>.bak` would also fit a `.env.*.bak` glob).
    """
    pattern = re.compile(r"^" + re.escape(safe_name) + r"\.(\d{8}_\d{6}_\d{6})\.bak$")
    found: list[tuple[str, Path]] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return found
    for entry in entries:
        match = pattern.match(entry.name)
        if match:
            found.append((match.group(1), entry))
    found.sort(key=lambda item: item[0])
    return found


def backup_env_file(project: Path, relpath: str, data: bytes) -> Path:
    """Save `data` (the old contents of `<project>/<relpath>`) under ~/.pushkey.

    Backups never go into the project folder: they hold secrets and a project
    folder is usually under version control. Only the newest three backups of
    each file are kept. Raises on failure so the caller does not overwrite the
    original without a backup.
    """
    safe_name = relpath.replace("\\", "/").replace("/", "__")
    if not safe_name:
        raise ValueError("relpath must not be empty")

    root = Path(_s.ENV_BACKUPS_DIR)
    target_dir = root / project_id(project)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_dir.mkdir(mode=0o700, exist_ok=True)
    _private_chmod(root, 0o700)
    _private_chmod(target_dir, 0o700)

    existing = _backup_stamps(target_dir, safe_name)
    moment = datetime.now()
    if existing:
        # The clock is coarse on Windows (about 15 ms): keep names strictly
        # increasing so quick successive backups neither collide nor misorder.
        try:
            newest = datetime.strptime(existing[-1][0], _BACKUP_STAMP_FORMAT)
        except ValueError:
            newest = None
        if newest is not None and moment <= newest:
            moment = newest + timedelta(microseconds=1)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for _ in range(1000):
        path = target_dir / f"{safe_name}.{moment.strftime(_BACKUP_STAMP_FORMAT)}.bak"
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            moment += timedelta(microseconds=1)  # another process won this name
            continue
        break
    else:
        raise OSError(f"could not pick a free backup name in {target_dir}")

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    _private_chmod(path, 0o600)

    for _stamp, old in _backup_stamps(target_dir, safe_name)[:-_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def ensure_gitignore_env(
    project_dir: Path,
    *,
    write: bool = True,
    atomic_write: Optional[Callable[[str, bytes], None]] = None,
) -> bool:
    gitignore = project_dir / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = content.splitlines()
    missing: list[str] = []
    if ".env" not in lines:
        missing.append(".env")
    # Backups from older versions sit in the project and hold secrets.
    if LEGACY_BACKUP_GLOB not in lines and any(project_dir.glob(LEGACY_BACKUP_GLOB)):
        missing.append(LEGACY_BACKUP_GLOB)
    if not missing:
        return False
    new_content = (content.rstrip("\n") + "\n" + "\n".join(missing) + "\n").lstrip("\n")
    if write:
        if atomic_write:
            atomic_write(".gitignore", new_content.encode("utf-8"))
        else:
            gitignore.write_text(new_content, encoding="utf-8")
    return True


def mutate_env_file(
    project_dir: str | Path,
    vault_entries: Mapping[str, Mapping[str, object]],
    *,
    key_names: Optional[list[str]] = None,
    update_existing: bool,
    write: bool = True,
    backup_existing: bool = False,
    atomic_write: Optional[Callable[[str, bytes], None]] = None,
) -> EnvMutationResult:
    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise NotADirectoryError(str(project))

    selected_names = key_names or list(vault_entries.keys())
    selected = {name: vault_entries[name] for name in selected_names if name in vault_entries}
    env_path = project / ".env"
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    existing_keys: set[str] = set()
    updated: list[str] = []
    new_lines: list[str] = []
    for line in existing_lines:
        match = _ENV_LINE.match(line)
        if match:
            key = match.group(1)
            existing_keys.add(key)
            if update_existing and key in selected:
                new_lines.append(f"{key}={format_env_value(selected[key].get('value', ''))}")
                updated.append(key)
                continue
        new_lines.append(line)

    injected = [name for name in selected_names if name in selected and name not in existing_keys]
    if injected:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Managed by Pushkey")
        for name in injected:
            new_lines.append(f"{name}={format_env_value(selected[name].get('value', ''))}")

    skipped = [name for name in selected_names if name in selected and name in existing_keys and not update_existing]
    if write:
        ensure_gitignore_env(project, write=True, atomic_write=atomic_write)
        data = ("\n".join(new_lines) + "\n").encode("utf-8")
        if backup_existing and env_path.exists():
            previous = env_path.read_bytes()
            # Only a change needs a backup: an idempotent re-run must not push
            # the user's real earlier file out of the few kept backups.
            if previous != data:
                backup_env_file(project, ".env", previous)
        if atomic_write:
            atomic_write(".env", data)
        else:
            tmp = env_path.with_name(f".env.pushkey-{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, env_path)

    return EnvMutationResult(
        env_file=str(env_path),
        injected_names=injected,
        updated_names=updated,
        skipped_existing=skipped,
        wrote=write,
    )

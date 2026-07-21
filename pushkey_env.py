"""Shared .env mutation helpers for CLI, MCP, and the local API."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional


_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


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


def ensure_gitignore_env(
    project_dir: Path,
    *,
    write: bool = True,
    atomic_write: Optional[Callable[[str, bytes], None]] = None,
) -> bool:
    gitignore = project_dir / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".env" in content.splitlines():
        return False
    new_content = (content.rstrip("\n") + "\n.env\n").lstrip("\n")
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
        if backup_existing and env_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(str(env_path), str(env_path.with_name(f".env.pushkey_backup_{ts}")))
        data = ("\n".join(new_lines) + "\n").encode("utf-8")
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

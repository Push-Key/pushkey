"""Backups of a project's .env live under ~/.pushkey, never inside the project."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

import pushkey_env
import pushkey_shared


def _project(tmp_path: Path, env_bytes: bytes = b"A=1\n") -> Path:
    # tmp_path itself is the vault dir, so the project is always a subfolder.
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_bytes(env_bytes)
    return project


def _legacy_backups(project: Path) -> list[Path]:
    return sorted(project.glob(".env.pushkey_backup_*"))


def _expected_project_id(project: Path) -> str:
    return hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()[:16]


def _write(project: Path, value: str) -> None:
    pushkey_env.mutate_env_file(
        project,
        {"A": {"value": value}},
        update_existing=True,
        backup_existing=True,
    )


def test_backup_goes_to_vault_dir_not_project(tmp_path: Path):
    project = _project(tmp_path)

    _write(project, "2")

    # Nothing secret is left in the project folder.
    assert _legacy_backups(project) == []
    assert (project / ".env").read_bytes() == b"A=2\n"

    backup_dir = pushkey_shared.ENV_BACKUPS_DIR / _expected_project_id(project)
    assert pushkey_env.project_id(project) == _expected_project_id(project)
    backups = sorted(backup_dir.glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"A=1\n"


def test_backup_keeps_newest_three(tmp_path: Path):
    project = _project(tmp_path)

    for value in ("2", "3", "4", "5"):
        _write(project, value)

    assert _legacy_backups(project) == []
    backup_dir = pushkey_shared.ENV_BACKUPS_DIR / _expected_project_id(project)
    backups = sorted(backup_dir.glob("*.bak"), key=lambda p: p.name)
    # Backups were taken of A=1, A=2, A=3, A=4; the oldest (A=1) is pruned.
    assert [p.read_bytes() for p in backups] == [b"A=2\n", b"A=3\n", b"A=4\n"]


def test_existing_backup_files_get_ignored(tmp_path: Path):
    project = _project(tmp_path)
    stray = project / ".env.pushkey_backup_20250101_000000"
    stray.write_bytes(b"OLD=secret\n")
    (project / ".gitignore").write_bytes(b".env\n")

    pushkey_env.mutate_env_file(
        project,
        {"A": {"value": "2"}},
        update_existing=True,
        write=True,
    )

    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert ".env.pushkey_backup_*" in lines
    # Never delete what we did not create this run.
    assert stray.read_bytes() == b"OLD=secret\n"


def _backup_dir(project: Path) -> Path:
    return pushkey_shared.ENV_BACKUPS_DIR / _expected_project_id(project)


def _contents(project: Path, name_pattern: str) -> list[bytes]:
    names = sorted(p.name for p in _backup_dir(project).glob("*.bak"))
    return [
        (_backup_dir(project) / name).read_bytes()
        for name in names
        if re.fullmatch(name_pattern, name)
    ]


def test_backup_pruning_is_per_file(tmp_path: Path):
    project = _project(tmp_path)
    stamp = r"\d{8}_\d{6}_\d{6}"

    # `.env.local` first, so a prune of `.env` that also matched it would hit
    # the older `.env.local` backups.
    for n in range(3):
        pushkey_env.backup_env_file(project, ".env.local", f"L{n}".encode())
    for n in range(4):
        pushkey_env.backup_env_file(project, ".env", f"E{n}".encode())
    pushkey_env.backup_env_file(project, "apps/web/.env", b"W0")

    assert _contents(project, rf"\.env\.local\.{stamp}\.bak") == [b"L0", b"L1", b"L2"]
    assert _contents(project, rf"\.env\.{stamp}\.bak") == [b"E1", b"E2", b"E3"]
    assert _contents(project, rf"apps__web__\.env\.{stamp}\.bak") == [b"W0"]


def test_backup_names_stay_ordered_when_the_clock_stalls(tmp_path: Path, monkeypatch):
    class _Stalled(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 12, 0, 0)

    monkeypatch.setattr(pushkey_env, "datetime", _Stalled)
    project = _project(tmp_path)

    for n in range(1, 6):
        pushkey_env.backup_env_file(project, ".env", f"V{n}".encode())

    # The newest three survive even though every call saw the same clock reading.
    assert _contents(project, r".*\.bak") == [b"V3", b"V4", b"V5"]

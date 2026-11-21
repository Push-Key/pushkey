"""Safe project paths and writes (stub: implementation follows the tests).

The stubs are inert, not NotImplementedError: a test that raises before its
own assertion proves nothing (mutate.py red refuses it), so each stub returns a
neutral wrong value and the tests fail on their assertions.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class ProjectPathError(ValueError):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def canonical_project_path(raw: str, *, must_exist: bool = True) -> str:
    return raw


def is_link_or_reparse(path: Path) -> bool:
    return False


def project_identity(project: Path) -> tuple[int, int]:
    return (0, 0)


def validate_env_relpath(relpath: str) -> str:
    return relpath


def resolve_project_target(
    registered: str, relpath: str, expected_identity: tuple[int, int]
) -> Path:
    return Path(registered) / relpath


def atomic_project_write(
    registered: str,
    relpath: str,
    data: bytes,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    return None


def ensure_project_gitignore(
    registered: str, relpath: str, expected_identity: tuple[int, int]
) -> bool:
    return False


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, 1, b"", b"")


def is_git_tracked(project: str, relpath: str) -> bool:
    return False

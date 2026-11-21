"""Connect keys to project folders: vault commit cycle, key replacement, project registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from pushkey_vault import VaultData

T = TypeVar("T")


class ConnectError(RuntimeError):
    code: str = ""
    detail: dict = {}


@dataclass
class CommitResult:
    value: Any
    vault: VaultData
    health_warning: Optional[str]


def commit(
    mutate: Callable[[VaultData], T],
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
) -> CommitResult:
    return CommitResult(None, VaultData(), None)


def adopt_vault(target: dict, fresh: VaultData) -> None:
    return None


def replace_value(entry: dict, new_value: str, *, now: Optional[str] = None) -> None:
    return None


def registered_projects(config: dict) -> dict[str, dict]:
    return {}


def register_project(path: str, *, name: Optional[str] = None) -> tuple[str, dict]:
    return "", {}


def unregister_project(
    path: str,
    *,
    vault_key: Optional[bytes],
    password: Optional[str],
    target: Optional[dict] = None,
) -> CommitResult:
    return CommitResult(None, VaultData(), None)

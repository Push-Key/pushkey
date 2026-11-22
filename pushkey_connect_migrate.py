"""One-time migration of the desktop's name-keyed projects to the shared project store."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pushkey_connect import is_migrated  # noqa: F401  (re-exported)


@dataclass
class MigrationReport:
    moved: list[str] = field(default_factory=list)
    connections_added: int = 0
    every_key_projects: list[str] = field(default_factory=list)
    env_skipped: list[tuple[str, str]] = field(default_factory=list)
    missing_keys: list[tuple[str, str]] = field(default_factory=list)
    unusable: list[str] = field(default_factory=list)
    unregistered: list[tuple[str, str]] = field(default_factory=list)


def plan_migration(vault: dict, config: dict) -> MigrationReport:
    return MigrationReport()


def ensure_migrated(*, vault_key, password, target=None) -> Optional[MigrationReport]:
    return None


def dismiss_notice() -> None:
    return None

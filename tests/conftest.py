import os
import re
import shutil
import time
from pathlib import Path

import pytest
import pushkey_shared


#: Sibling session directories older than this are pruned at session start.
_SESSION_DIR_MAX_AGE_SECONDS = 6 * 60 * 60

#: Session directory names this module owns: "s" followed by a PID.
_SESSION_DIR_RE = re.compile(r"^s\d+$")


def pytest_configure(config):
    """Give each pytest session its own subdirectory under the shared basetemp.

    pytest deletes the entire `--basetemp` tree when a session starts. Because
    `pytest.ini` pins that to the repo-local `.pytest_tmp`, starting a second
    pytest run -- a focused file while the full suite is going, or two jobs on
    one workspace -- destroys the live `tmp_path` directories of the run already
    in progress. That surfaces as unrelated failures and teardown
    `PermissionError`s in whichever test happened to be running, and it never
    reproduces in isolation.

    Nesting each session under its own PID-named directory keeps the short
    repo-local path that `--basetemp` exists for, while making the start-up
    wipe affect only this session.
    """
    basetemp = config.option.basetemp
    if not basetemp:
        return
    basetemp = Path(basetemp)
    session_name = f"s{os.getpid()}"
    if basetemp.name == session_name:  # already narrowed; do not nest again
        return
    # pytest creates the basetemp itself but does not create its parents.
    basetemp.mkdir(parents=True, exist_ok=True)
    _prune_stale_session_dirs(basetemp)
    config.option.basetemp = str(basetemp / session_name)


def _prune_stale_session_dirs(basetemp: Path) -> None:
    """Remove session directories left behind by runs that are long gone."""
    cutoff = time.time() - _SESSION_DIR_MAX_AGE_SECONDS
    try:
        entries = list(basetemp.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir() or not _SESSION_DIR_RE.match(entry.name):
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)


#: The real vault directory, captured once at import before any redirection.
REAL_VAULT_DIR = pushkey_shared.VAULT_DIR


def vault_path_attributes(module=pushkey_shared) -> dict[str, Path]:
    """Return every module attribute that points inside the real vault directory.

    Derived rather than hand-listed. The previous fixture enumerated nine paths
    by name while pushkey_shared defines sixteen, so PROVIDERS_CACHE, MFA_FILE,
    FIDO2_FILE, SSO_FILE, LEASES_FILE, and AGENT_TOKENS_FILE still pointed at the
    developer's real ~/.pushkey during tests. That passed on any machine that had
    a vault directory and failed on a fresh one, and meant the suite could read
    and write a real user's vault. Deriving the list keeps it correct as
    pushkey_shared grows.
    """

    found: dict[str, Path] = {}
    for name in dir(module):
        if name.startswith("__"):
            continue
        value = getattr(module, name)
        if not isinstance(value, Path):
            continue
        if value == REAL_VAULT_DIR or REAL_VAULT_DIR in value.parents:
            found[name] = value
    return found


@pytest.fixture(autouse=True)
def isolate_vault_paths(tmp_path, monkeypatch):
    """Redirect all vault I/O to tmp_path so tests never touch ~/.pushkey."""
    for name, original in vault_path_attributes().items():
        if original == REAL_VAULT_DIR:
            monkeypatch.setattr(pushkey_shared, name, tmp_path)
        else:
            monkeypatch.setattr(
                pushkey_shared, name, tmp_path / original.relative_to(REAL_VAULT_DIR)
            )
    try:
        import pushkey_tiers
        pushkey_tiers._LICENSE_CACHE = None
    except ImportError:
        pass
    yield
    try:
        import pushkey_tiers
        pushkey_tiers._LICENSE_CACHE = None
    except ImportError:
        pass

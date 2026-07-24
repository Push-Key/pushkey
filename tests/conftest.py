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


@pytest.fixture(autouse=True)
def isolate_vault_paths(tmp_path, monkeypatch):
    """Redirect all vault I/O to tmp_path so tests never touch ~/.pushkey."""
    monkeypatch.setattr(pushkey_shared, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey_shared, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey_shared, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey_shared, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(pushkey_shared, "LOG_FILE", tmp_path / "pushkey.log")
    monkeypatch.setattr(pushkey_shared, "HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(pushkey_shared, "IMPORT_DIR", tmp_path / "import")
    monkeypatch.setattr(pushkey_shared, "LICENSE_FILE", tmp_path / ".license")
    monkeypatch.setattr(pushkey_shared, "TOKEN_FILE", tmp_path / ".token")
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

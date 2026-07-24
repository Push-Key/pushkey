"""Guard the test-session isolation that `tests/conftest.py` sets up.

pytest deletes the whole `--basetemp` tree at session start. `pytest.ini` pins
that to the repo-local `.pytest_tmp`, so without the per-session subdirectory
one pytest run wipes the live `tmp_path` directories of any run already in
progress. The resulting failures land on whichever unrelated test happened to
be executing and never reproduce in isolation, which is expensive to diagnose.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import conftest


def test_tmp_path_is_scoped_to_this_session(tmp_path):
    session_dir = tmp_path.parent

    assert session_dir.name == f"s{os.getpid()}", (
        "tmp_path must live under a per-session basetemp subdirectory, "
        f"got {session_dir.name!r}. A shared basetemp lets a second pytest "
        "session delete this session's temp files mid-run."
    )


def test_basetemp_parent_is_the_repo_local_directory(tmp_path):
    basetemp_root = tmp_path.parent.parent

    assert basetemp_root.name == ".pytest_tmp"
    assert basetemp_root.parent == Path(__file__).resolve().parents[1]


def test_configure_narrows_a_shared_basetemp(tmp_path):
    class _Option:
        basetemp = str(tmp_path / "shared")

    class _Config:
        option = _Option()

    config = _Config()
    conftest.pytest_configure(config)

    assert Path(config.option.basetemp) == tmp_path / "shared" / f"s{os.getpid()}"
    assert (tmp_path / "shared").is_dir(), "the shared parent must be created for pytest"


def test_configure_narrows_a_basetemp_whose_name_merely_starts_with_s(tmp_path):
    # Guards against matching the already-narrowed marker by prefix: a basetemp
    # named "shared" or "scratch" must still be narrowed, not mistaken for a
    # session directory and left shared between concurrent runs.
    class _Option:
        basetemp = str(tmp_path / "scratch")

    class _Config:
        option = _Option()

    config = _Config()
    conftest.pytest_configure(config)

    assert Path(config.option.basetemp).name == f"s{os.getpid()}"


def test_configure_is_idempotent_for_an_already_narrowed_basetemp(tmp_path):
    narrowed = str(tmp_path / "shared" / f"s{os.getpid()}")

    class _Option:
        basetemp = narrowed

    class _Config:
        option = _Option()

    config = _Config()
    conftest.pytest_configure(config)

    assert config.option.basetemp == narrowed


def test_stale_session_directories_are_pruned_but_recent_ones_are_kept(tmp_path):
    stale = tmp_path / "s111"
    recent = tmp_path / "s222"
    unrelated = tmp_path / "scratch"
    for directory in (stale, recent, unrelated):
        directory.mkdir()
        (directory / "marker").write_text("x", encoding="utf-8")

    old = time.time() - conftest._SESSION_DIR_MAX_AGE_SECONDS - 60
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))

    conftest._prune_stale_session_dirs(tmp_path)

    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists(), (
        "only s<pid> session directories are pruned; an old directory whose "
        "name merely starts with 's' must survive"
    )

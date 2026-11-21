"""Safe project paths and writes (pushkey_projectfs)."""
import importlib
import os
import subprocess

import pytest

import pushkey_projectfs
from pushkey_projectfs import (
    ProjectPathError,
    atomic_project_write,
    canonical_project_path,
    ensure_project_gitignore,
    is_git_tracked,
    project_identity,
    resolve_project_target,
    validate_env_relpath,
)

LINK_REASON = "refusing link or reparse-point project target"


def _link_directory(link, target):
    """Directory link: a junction on Windows (needs no privilege), a symlink elsewhere."""
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, check=False,
        )
        if created.returncode:
            pytest.skip("Windows junction creation is unavailable in this environment")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    return folder.resolve()


def _error(call, *args, **kwargs):
    """The ProjectPathError a call raises; anything else is an assertion failure."""
    try:
        call(*args, **kwargs)
    except ProjectPathError as err:
        return err
    except Exception as exc:
        raise AssertionError(f"{call.__name__} raised {exc!r}, not ProjectPathError") from exc
    raise AssertionError(f"{call.__name__} did not raise ProjectPathError")


def _reason(call, *args, **kwargs):
    return _error(call, *args, **kwargs).reason


def _normalised(relpath):
    try:
        return validate_env_relpath(relpath)
    except ProjectPathError as err:
        return f"refused: {err.reason}"


def _tracked(project, relpath):
    try:
        return is_git_tracked(str(project), relpath)
    except Exception as exc:
        return f"raised {exc!r}"


def _read(path):
    return path.read_bytes() if path.exists() else None


def _temp_files(folder):
    return [p.name for p in folder.iterdir() if p.name.startswith(".pushkey-")]


# ── error type ───────────────────────────────────────────────────────────────


def test_error_carries_status_and_reason():
    err = ProjectPathError(409, "project path changed during write")
    assert isinstance(err, ValueError)
    assert (err.status, err.reason) == (409, "project path changed during write")
    assert str(err) == "project path changed during write"


# ── canonical project path ───────────────────────────────────────────────────


def test_canonical_project_path_rules(tmp_path, project):
    assert canonical_project_path(str(project)) == str(project)
    assert _reason(canonical_project_path, "") == "invalid project path"
    assert _reason(canonical_project_path, str(project) + "\x01") == "invalid project path"
    assert _reason(canonical_project_path, "relative/dir") == "project path must be absolute"
    # A path that does not exist cannot be resolved strictly ("invalid project
    # path"); "not found" is for an existing path that is not a directory.
    assert _reason(canonical_project_path, str(tmp_path / "missing")) == "invalid project path"
    (tmp_path / "a-file").write_text("x")
    assert _reason(canonical_project_path, str(tmp_path / "a-file")) == "project directory not found"
    assert canonical_project_path(str(tmp_path / "missing"), must_exist=False).endswith("missing")


# ── env file path rules ──────────────────────────────────────────────────────


def test_relpath_normalises_backslashes():
    assert _normalised("apps\\web\\.env.local") == "apps/web/.env.local"
    assert _normalised("./apps/./web/.env") == "apps/web/.env"


def test_relpath_rejects_parent_segments():
    for bad in ("../x/.env", "apps/../../.env", "apps\\..\\.env"):
        assert _reason(validate_env_relpath, bad) == "env file path may not contain '..'"
    for bad in ("/abs/.env", "C:/x/.env", "\\\\server\\share\\.env"):
        assert _reason(validate_env_relpath, bad) == "env file path must be relative"


def test_relpath_rejects_other_names_and_templates():
    assert _reason(validate_env_relpath, "config.js") == "env file name must be .env or start with .env."
    assert _reason(validate_env_relpath, "apps/web/envfile") == "env file name must be .env or start with .env."
    for template in (".env.example", ".env.sample", ".env.template", "apps/.env.EXAMPLE", ".env.local.example"):
        assert _reason(validate_env_relpath, template) == "env template files are read-only"
    for fine in (".env", ".env.local", "apps/web/.env.development.local"):
        assert _normalised(fine) == fine


def test_relpath_rejects_invalid_paths():
    invalid = "invalid env file path"
    for bad in ("", "apps//web/.env", "apps/web/", "apps/.env\x07", "apps/.env\x00", ".env:stream", "apps/web./.env", ".env.local ", "ap?ps/.env"):
        assert _reason(validate_env_relpath, bad) == invalid, repr(bad)


# ── strict writes ────────────────────────────────────────────────────────────


def test_write_into_subfolder(project):
    (project / "apps" / "web").mkdir(parents=True)
    atomic_project_write(str(project), "apps/web/.env.local", b"A=1\n")
    assert _read(project / "apps" / "web" / ".env.local") == b"A=1\n"
    assert _temp_files(project / "apps" / "web") == []
    assert _temp_files(project) == []


def test_write_keeps_root_file_behaviour(project):
    atomic_project_write(str(project), ".env", b"A=1\n")
    atomic_project_write(str(project), ".env", b"A=2\n")
    atomic_project_write(str(project), ".gitignore", b".env\n")
    assert _read(project / ".env") == b"A=2\n"
    assert _read(project / ".gitignore") == b".env\n"
    assert _temp_files(project) == []


def test_temp_file_sits_in_the_target_folder_with_the_pushkey_prefix(project, monkeypatch):
    (project / "apps").mkdir()
    seen = []
    real_replace = os.replace

    def spy(source, target):
        seen.append((os.fspath(source), os.fspath(target)))
        return real_replace(source, target)

    monkeypatch.setattr(pushkey_projectfs.os, "replace", spy)
    atomic_project_write(str(project), "apps/.env.local", b"A=1\n")
    assert len(seen) == 1
    source, target = seen[0]
    assert os.path.dirname(source) == os.path.dirname(target) == str(project / "apps")
    assert os.path.basename(source).startswith(".pushkey-")


def test_failed_replace_leaves_no_temp_and_keeps_the_old_file(project, monkeypatch):
    (project / ".env").write_bytes(b"OLD=1\n")

    def boom(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(pushkey_projectfs.os, "replace", boom)
    try:
        atomic_project_write(str(project), ".env", b"NEW=1\n")
        outcome = "no error"
    except OSError as exc:
        outcome = str(exc)
    assert outcome == "disk full"
    assert (project / ".env").read_bytes() == b"OLD=1\n"
    assert _temp_files(project) == []


def test_write_refuses_junction_subfolder(project, tmp_path):
    outside = tmp_path / "outside"
    (outside / "web").mkdir(parents=True)
    _link_directory(project / "apps", outside)
    for relpath in ("apps/.env.local", "apps/web/.env.local"):
        assert _reason(atomic_project_write, str(project), relpath, b"A=1\n") == LINK_REASON
    assert not (outside / ".env.local").exists()
    assert not (outside / "web" / ".env.local").exists()
    assert list(outside.glob(".pushkey-*")) == []


def test_write_refuses_linked_leaf(project, tmp_path):
    # A directory link needs no privilege on Windows; the leaf check is the same
    # for any link or reparse point.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    _link_directory(project / ".env.local", outside)
    assert _reason(atomic_project_write, str(project), ".env.local", b"A=1\n") == LINK_REASON
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_write_refuses_missing_subfolder(project):
    reason = _reason(atomic_project_write, str(project), "apps/web/.env.local", b"A=1\n")
    assert reason == "env file folder does not exist"
    assert not (project / "apps").exists()


def test_write_refuses_a_file_where_a_folder_is_expected(project):
    (project / "apps").write_text("not a folder")
    assert _reason(atomic_project_write, str(project), "apps/.env.local", b"A=1\n") == "env file folder does not exist"


def test_write_refuses_paths_that_climb_out_of_the_project(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    reason = _reason(atomic_project_write, str(project), "../outside/.env", b"A=1\n")
    assert reason == "env file path may not contain '..'"
    assert not (outside / ".env").exists()
    assert _reason(atomic_project_write, str(project), str(outside / ".env"), b"A=1\n") == "env file path must be relative"


def test_write_refuses_changed_folder_identity(project):
    stale = (project_identity(project)[0], project_identity(project)[1] + 1)
    err = _error(atomic_project_write, str(project), ".env", b"A=1\n", stale)
    assert (err.status, err.reason) == (409, "project directory identity changed during write")
    assert not (project / ".env").exists()


def test_write_refuses_a_project_path_that_is_not_canonical(project):
    err = _error(atomic_project_write, str(project) + os.sep + ".", ".env", b"A=1\n")
    assert (err.status, err.reason) == (409, "project path changed during write")


def test_link_refusal_has_status_400(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_directory(project / "apps", outside)
    identity = project_identity(project)
    err = _error(resolve_project_target, str(project), "apps/.env.local", identity)
    assert (err.status, err.reason) == (400, LINK_REASON)


def test_identity_change_after_the_temp_write_is_caught_before_the_replace(project, monkeypatch):
    (project / ".env").write_bytes(b"OLD=1\n")
    identity = project_identity(project)
    real_identity, real_fsync = pushkey_projectfs.project_identity, os.fsync
    moved = []

    def fsync_then_move(fd):
        real_fsync(fd)
        moved.append(True)

    monkeypatch.setattr(pushkey_projectfs.os, "fsync", fsync_then_move)
    monkeypatch.setattr(
        pushkey_projectfs, "project_identity",
        lambda path: (0, 0) if moved else real_identity(path),
    )
    err = _error(atomic_project_write, str(project), ".env", b"NEW=1\n", identity)
    assert (err.status, err.reason) == (409, "project directory identity changed during write")
    assert (project / ".env").read_bytes() == b"OLD=1\n"
    assert _temp_files(project) == []


def test_identity_change_after_the_replace_is_still_reported(project, monkeypatch):
    identity = project_identity(project)
    real_identity, real_replace = pushkey_projectfs.project_identity, os.replace
    replaced = []

    def replace_then_move(source, target):
        real_replace(source, target)
        replaced.append(True)

    monkeypatch.setattr(pushkey_projectfs.os, "replace", replace_then_move)
    monkeypatch.setattr(
        pushkey_projectfs, "project_identity",
        lambda path: (0, 0) if replaced else real_identity(path),
    )
    err = _error(atomic_project_write, str(project), ".env", b"A=1\n", identity)
    assert (err.status, err.reason) == (409, "project directory identity changed during write")
    assert _temp_files(project) == []


def test_temp_file_that_turns_into_a_link_is_refused(project, monkeypatch):
    (project / ".env").write_bytes(b"OLD=1\n")
    real_check = pushkey_projectfs.is_link_or_reparse
    monkeypatch.setattr(
        pushkey_projectfs, "is_link_or_reparse",
        lambda path: path.name.startswith(".pushkey-") or real_check(path),
    )
    err = _error(atomic_project_write, str(project), ".env", b"NEW=1\n")
    assert (err.status, err.reason) == (409, "temporary project target changed")
    assert (project / ".env").read_bytes() == b"OLD=1\n"
    assert _temp_files(project) == []


def test_escape_guard_catches_a_link_the_link_check_missed(project, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_directory(project / "apps", outside)
    monkeypatch.setattr(pushkey_projectfs, "is_link_or_reparse", lambda path: False)
    reason = _reason(atomic_project_write, str(project), "apps/.env.local", b"A=1\n")
    assert reason == "project target escapes registered directory"
    assert not (outside / ".env.local").exists()


def test_resolve_project_target_returns_the_path_without_creating_anything(project):
    (project / "apps" / "web").mkdir(parents=True)
    target = resolve_project_target(str(project), "apps\\web\\.env.local", project_identity(project))
    assert target == project / "apps" / "web" / ".env.local"
    assert not target.exists()


# ── project .gitignore ───────────────────────────────────────────────────────


def test_write_adds_exact_path_to_project_gitignore(project):
    identity = project_identity(project)
    assert ensure_project_gitignore(str(project), "apps/web/.env.local", identity) is True
    assert (project / ".gitignore").read_text() == "apps/web/.env.local\n"
    assert ensure_project_gitignore(str(project), "apps/web/.env.local", identity) is False
    assert (project / ".gitignore").read_text() == "apps/web/.env.local\n"


def test_gitignore_pattern_that_covers_the_file_is_left_alone(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"node_modules\n.env*\n")
    assert ensure_project_gitignore(str(project), "apps/web/.env.local", identity) is False
    assert ensure_project_gitignore(str(project), ".env", identity) is False
    assert (project / ".gitignore").read_bytes() == b"node_modules\n.env*\n"


def test_gitignore_anchored_line_covers_the_file(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"/apps/web/.env.local\n/.env\n")
    assert ensure_project_gitignore(str(project), "apps/web/.env.local", identity) is False
    assert ensure_project_gitignore(str(project), ".env", identity) is False
    assert (project / ".gitignore").read_bytes() == b"/apps/web/.env.local\n/.env\n"


def test_gitignore_root_anchored_name_does_not_cover_a_nested_file(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"/.env.local\n")
    assert ensure_project_gitignore(str(project), "apps/.env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b"/.env.local\napps/.env.local\n"


def test_gitignore_pattern_that_does_not_match_the_name_is_not_a_cover(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b".env.*\n")
    assert ensure_project_gitignore(str(project), ".env", identity) is True
    assert (project / ".gitignore").read_bytes() == b".env.*\n.env\n"


def test_gitignore_pattern_with_a_slash_does_not_cover_a_deeper_file(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"apps/.env*\n")
    assert ensure_project_gitignore(str(project), "apps/web/.env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b"apps/.env*\napps/web/.env.local\n"


def test_gitignore_keeps_crlf_line_endings(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"dist\r\nnode_modules\r\n")
    assert ensure_project_gitignore(str(project), ".env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b"dist\r\nnode_modules\r\n.env.local\r\n"


def test_gitignore_without_a_final_newline_gets_one_before_the_new_line(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"dist")
    assert ensure_project_gitignore(str(project), ".env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b"dist\n.env.local\n"


def test_gitignore_negation_after_a_pattern_means_the_file_is_not_covered(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b".env*\n!.env.local\n")
    assert ensure_project_gitignore(str(project), ".env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b".env*\n!.env.local\n.env.local\n"
    assert ensure_project_gitignore(str(project), ".env.local", identity) is False


def test_gitignore_refuses_a_linked_gitignore(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_directory(project / ".gitignore", outside)
    assert _reason(ensure_project_gitignore, str(project), ".env.local", project_identity(project)) == LINK_REASON
    assert list(outside.iterdir()) == []


def test_gitignore_goes_through_the_module_writer(project, monkeypatch):
    calls = []
    monkeypatch.setattr(
        pushkey_projectfs, "atomic_project_write",
        lambda registered, relpath, data, expected_identity=None: calls.append((registered, relpath, data)),
    )
    assert ensure_project_gitignore(str(project), ".env.local", project_identity(project)) is True
    assert calls == [(str(project), ".gitignore", b".env.local\n")]


def _git_ignore_status(project, relpath):
    """Exit code of `git check-ignore -q`: 0 ignored, 1 not ignored."""
    return subprocess.run(
        ["git", "-C", str(project), "check-ignore", "-q", "--", relpath],
        capture_output=True, text=True, check=False,
    ).returncode


def test_gitignore_line_for_glob_named_folder_is_matched_by_git(project):
    _git(project, "init")
    (project / "app" / "[id]").mkdir(parents=True)
    (project / "app" / "[id]" / ".env.local").write_text("A=1\n")
    identity = project_identity(project)
    assert ensure_project_gitignore(str(project), "app/[id]/.env.local", identity) is True
    assert _git_ignore_status(project, "app/[id]/.env.local") == 0
    assert ensure_project_gitignore(str(project), "app/[id]/.env.local", identity) is False


@pytest.mark.parametrize("folder", ["#notes", "!bang", "x[1]", "a]b"])
def test_gitignore_line_for_awkward_folder_names_is_matched_by_git(project, folder):
    _git(project, "init")
    (project / folder).mkdir()
    (project / folder / ".env.local").write_text("A=1\n")
    identity = project_identity(project)
    relpath = f"{folder}/.env.local"
    assert ensure_project_gitignore(str(project), relpath, identity) is True
    assert _git_ignore_status(project, relpath) == 0
    assert ensure_project_gitignore(str(project), relpath, identity) is False


def test_gitignore_line_that_names_a_glob_folder_without_escapes_is_not_a_cover(project):
    identity = project_identity(project)
    (project / ".gitignore").write_bytes(b"app/[id]/.env.local\n")
    assert ensure_project_gitignore(str(project), "app/[id]/.env.local", identity) is True
    assert (project / ".gitignore").read_bytes() == b"app/[id]/.env.local\napp/\\[id\\]/.env.local\n"


# ── git tracking ─────────────────────────────────────────────────────────────


def _git(project, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project, capture_output=True, text=True, check=True,
    )


def test_tracked_file_is_refused(project, monkeypatch):
    _git(project, "init")
    (project / ".env.local").write_text("A=1\n")
    (project / ".env").write_text("B=2\n")
    _git(project, "add", ".env.local")
    _git(project, "commit", "-m", "x")
    assert _tracked(project, ".env.local") is True
    assert _tracked(project, ".env") is False
    assert _tracked(project, "apps/web/.env.local") is False

    def missing_git(args, cwd):
        raise FileNotFoundError("git")

    with monkeypatch.context() as m:
        m.setattr(pushkey_projectfs, "_run_git", missing_git)
        assert _tracked(project, ".env.local") is False


def test_a_folder_that_is_not_a_repository_has_nothing_tracked(project, monkeypatch):
    def not_a_repo(args, cwd):
        return subprocess.CompletedProcess(args, 128, b"", b"fatal: not a git repository")

    monkeypatch.setattr(pushkey_projectfs, "_run_git", not_a_repo)
    assert _tracked(project, ".env") is False


def test_git_is_run_with_list_argv_a_timeout_and_no_shell(project, monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(pushkey_projectfs.subprocess, "run", fake_run)
    assert _tracked(project, "apps/web/.env.local") is True
    argv = seen["argv"]
    assert isinstance(argv, list) and argv[0] == "git"
    assert "-C" in argv and "ls-files" in argv
    assert argv[argv.index("ls-files"):] == ["ls-files", "--error-unmatch", "--", "apps/web/.env.local"]
    assert argv[argv.index("-C") + 1] == str(project)
    assert seen["kwargs"]["timeout"] == 5
    assert not seen["kwargs"].get("shell")


def test_git_timeout_means_not_tracked(project, monkeypatch):
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(pushkey_projectfs.subprocess, "run", slow)
    assert _tracked(project, ".env") is False


# ── the web API keeps its names as thin shims ────────────────────────────────


@pytest.fixture
def local_api(monkeypatch):
    monkeypatch.setenv("PUSHKEY_LAUNCH_TOKEN", "test-launch-token")
    monkeypatch.setenv("PUSHKEY_LOCAL_PORT", "0")
    return importlib.import_module("pushkey_local_api")


def test_local_api_shim_writes_into_a_subfolder(local_api, project):
    (project / "apps").mkdir()
    try:
        local_api._atomic_project_write(str(project), "apps/.env.local", b"A=1\n")
        refused = None
    except Exception as exc:  # an HTTPException while the single-folder rule still applies
        refused = repr(exc)
    assert refused is None
    assert _read(project / "apps" / ".env.local") == b"A=1\n"


def test_local_api_shims_raise_http_errors_with_the_same_reasons(local_api, project, tmp_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        local_api._canonical_project_path("relative/dir")
    assert (caught.value.status_code, caught.value.detail) == (400, "project path must be absolute")

    outside = tmp_path / "outside"
    outside.mkdir()
    _link_directory(project / "apps", outside)
    with pytest.raises(HTTPException) as caught:
        local_api._atomic_project_write(str(project), "apps/.env.local", b"A=1\n")
    assert (caught.value.status_code, caught.value.detail) == (400, LINK_REASON)

    stale = (project_identity(project)[0], project_identity(project)[1] + 1)
    with pytest.raises(HTTPException) as caught:
        local_api._assert_project_target(project, str(project), project / ".env", stale)
    assert (caught.value.status_code, caught.value.detail) == (409, "project directory identity changed during write")

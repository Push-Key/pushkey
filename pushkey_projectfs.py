"""Safe project paths and writes, free of any web framework.

The strict writer behind the web API's ``.env`` injection, generalised from a
bare file name in the project root to a relative path with subfolders
(``apps/web/.env.local``). Nothing below the registered project folder may be a
symlink, junction or other reparse point; a path that fails is refused, never
followed. Failures raise :class:`ProjectPathError` (an HTTP-style status plus a
reason string); the web API maps it to ``HTTPException`` in thin shims.

Callers outside this module reach everything through module attributes
(``pushkey_projectfs.atomic_project_write(...)``) so tests can patch it.
"""
from __future__ import annotations

import fnmatch
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

_LINK_REASON = "refusing link or reparse-point project target"
_INVALID_ENV_PATH = "invalid env file path"
# Characters no segment of an env file path may carry (":" also stops drive
# letters and NTFS alternate data streams; the rest are invalid on Windows and
# wildcards to git).
_FORBIDDEN_SEGMENT_CHARS = frozenset(':*?"<>|')
_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")
_GITIGNORE_PATTERN_CHARS = re.compile(r"([\[\]*?])")
_GIT_TIMEOUT_SECONDS = 5


class ProjectPathError(ValueError):
    """A refused project path: ``status`` is the HTTP-style code, ``reason`` the text."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def canonical_project_path(raw: str, *, must_exist: bool = True) -> str:
    """Return a canonical absolute project directory, rejecting ambiguous paths."""
    if not raw or "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        raise ProjectPathError(400, "invalid project path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ProjectPathError(400, "project path must be absolute")
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError):
        raise ProjectPathError(400, "invalid project path") from None
    if must_exist and not resolved.is_dir():
        raise ProjectPathError(400, "project directory not found")
    return str(resolved)


def is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


def project_identity(project: Path) -> tuple[int, int]:
    info = project.stat()
    return (info.st_dev, info.st_ino)


def _relative_segments(relpath: str) -> list[str]:
    """Split a project-relative path into safe segments (shape rules only)."""
    if not isinstance(relpath, str) or not relpath or any(ord(ch) < 32 for ch in relpath):
        raise ProjectPathError(400, _INVALID_ENV_PATH)
    normal = relpath.replace("\\", "/")
    if normal.startswith("/") or re.match(r"[A-Za-z]:", normal):
        raise ProjectPathError(400, "env file path must be relative")
    parts = normal.split("/")
    if ".." in parts:
        raise ProjectPathError(400, "env file path may not contain '..'")
    segments = [part for part in parts if part != "."]
    if not segments:
        raise ProjectPathError(400, _INVALID_ENV_PATH)
    for segment in segments:
        # Windows drops a trailing dot or space, so the name on disk would differ.
        if (
            not segment
            or segment[-1] in " ."
            or any(ch in _FORBIDDEN_SEGMENT_CHARS for ch in segment)
        ):
            raise ProjectPathError(400, _INVALID_ENV_PATH)
    return segments


def validate_env_relpath(relpath: str) -> str:
    """Return the normalised POSIX relative path of an env file, or raise."""
    segments = _relative_segments(relpath)
    name = segments[-1]
    if name != ".env" and not name.startswith(".env."):
        raise ProjectPathError(400, "env file name must be .env or start with .env.")
    if name.lower().endswith(_TEMPLATE_SUFFIXES):
        raise ProjectPathError(400, "env template files are read-only")
    return "/".join(segments)


def resolve_project_target(
    registered: str, relpath: str, expected_identity: tuple[int, int]
) -> Path:
    """Check ``relpath`` below the registered project and return its absolute path.

    Every existing segment below the project must be a real directory, the
    leaf may not be a link or reparse point, and the project folder must still
    be the one that was registered. Missing subfolders are an error: nothing is
    created here.
    """
    segments = _relative_segments(relpath)
    project = Path(registered)
    if canonical_project_path(str(project)) != registered:
        raise ProjectPathError(409, "project path changed during write")
    if is_link_or_reparse(project):
        raise ProjectPathError(400, _LINK_REASON)
    folder = project
    for segment in segments[:-1]:
        folder = folder / segment
        # lstat first: is_dir() would follow a junction or symlink.
        if is_link_or_reparse(folder):
            raise ProjectPathError(400, _LINK_REASON)
        if not folder.is_dir():
            raise ProjectPathError(400, "env file folder does not exist")
    target = folder / segments[-1]
    if is_link_or_reparse(target):
        raise ProjectPathError(400, _LINK_REASON)
    if folder.resolve(strict=True) != folder:
        raise ProjectPathError(400, "project target escapes registered directory")
    if project_identity(project) != expected_identity:
        raise ProjectPathError(409, "project directory identity changed during write")
    return target


def atomic_project_write(
    registered: str,
    relpath: str,
    data: bytes,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Write a project file without following links or exposing partial data."""
    project = Path(registered)
    if expected_identity is None:
        try:
            expected_identity = project_identity(project)
        except OSError:
            raise ProjectPathError(400, "project directory not found") from None
    target = resolve_project_target(registered, relpath, expected_identity)
    fd, temporary = tempfile.mkstemp(prefix=".pushkey-", dir=target.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        resolve_project_target(registered, relpath, expected_identity)
        if is_link_or_reparse(temp_path):
            raise ProjectPathError(409, "temporary project target changed")
        os.replace(temp_path, target)
        resolve_project_target(registered, relpath, expected_identity)
        try:
            directory_fd = os.open(
                str(target.parent),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp_path.unlink(missing_ok=True)


def _gitignore_escape(path: str) -> str:
    """Escape ``path`` so a .gitignore line matches exactly that file.

    ``[ ] * ?`` are pattern characters anywhere, a leading ``!`` or ``#`` would
    negate or comment the line, and trailing spaces are dropped unless escaped.
    """
    escaped = _GITIGNORE_PATTERN_CHARS.sub(r"\\\1", path)
    if escaped[:1] in ("!", "#"):
        escaped = "\\" + escaped
    unspaced = escaped.rstrip(" ")
    return unspaced + "\\ " * (len(escaped) - len(unspaced))


def _gitignore_covers(text: str, relpath: str) -> bool:
    """True when the last matching line of a .gitignore ignores ``relpath``.

    A line matches when, without a leading ``/``, it equals the escaped path
    (the only spelling git reads as that literal file), or it has no ``/`` at
    all and matches the file name as a pattern. ``!`` lines undo an earlier
    match, as in git (the last matching line wins).
    """
    name = relpath.rsplit("/", 1)[-1]
    literal = _gitignore_escape(relpath).strip()
    covered = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
        bare = line[1:] if line.startswith("/") else line
        if bare == literal or ("/" not in line and fnmatch.fnmatch(name, line)):
            covered = not negated
    return covered


def ensure_project_gitignore(
    registered: str, relpath: str, expected_identity: tuple[int, int]
) -> bool:
    """List ``relpath`` in the project's own .gitignore; True when a line was added."""
    relpath = validate_env_relpath(relpath)
    target = resolve_project_target(registered, ".gitignore", expected_identity)
    try:
        existing = target.read_bytes()
    except FileNotFoundError:
        existing = b""
    if _gitignore_covers(existing.decode("utf-8-sig", errors="replace"), relpath):
        return False
    eol = b"\r\n" if b"\r\n" in existing else b"\n"
    separator = b"" if not existing or existing.endswith(b"\n") else eol
    atomic_project_write(
        registered,
        ".gitignore",
        existing + separator + _gitignore_escape(relpath).encode("utf-8") + eol,
        expected_identity,
    )
    return True


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    # List argv, no shell, bounded. Literal pathspecs: a "[id]" folder is a name, not a glob.
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
    )


def is_git_tracked(project: str, relpath: str) -> bool:
    """True when git already tracks ``relpath``; no git, a timeout or any error is False."""
    relpath = "/".join(_relative_segments(relpath))
    try:
        result = _run_git(
            ["-C", project, "ls-files", "--error-unmatch", "--", relpath], project
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0

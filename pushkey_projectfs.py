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
import unicodedata
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
# Repository-selecting variables of the caller's environment, never passed to git.
_GIT_ENV_DROPPED = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS"}
)


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


def _trim_trailing_spaces(line: str) -> str:
    """Drop trailing unescaped spaces, as git does (tabs and other spaces stay)."""
    last_space = None
    index = 0
    while index < len(line):
        char = line[index]
        if char == " ":
            if last_space is None:
                last_space = index
        elif char == "\\":
            index += 1
            if index >= len(line):
                break
            last_space = None
        else:
            last_space = None
        index += 1
    return line if last_space is None else line[:last_space]


def _gitignore_covers(text: str, relpath: str) -> bool:
    """True only when git certainly ignores ``relpath`` because of this .gitignore.

    When unsure the answer is False: the caller then appends the exact line,
    which comes last and wins. Lines are read the way git reads them (only a CR
    before the LF and unescaped trailing spaces are dropped; leading spaces,
    tabs and other Unicode spaces are part of the pattern). A line is a cover
    when, without a leading ``/``, it equals the escaped path, or it is a plain
    name pattern (no ``/``, ``[`` or backslash) that matches the file name. A
    ``!`` line resets the answer when its last part could match the file name,
    which includes any pattern git and fnmatch might read differently (``[``,
    a backslash, ``**``) and a case-insensitive match.
    """
    name = relpath.rsplit("/", 1)[-1]
    literal = _gitignore_escape(relpath)
    covered = False
    for raw in text.split("\n"):
        line = _trim_trailing_spaces(raw[:-1] if raw.endswith("\r") else raw)
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            pattern = line[1:]
            last = pattern.rsplit("/", 1)[-1]
            if (
                "**" in pattern
                or "[" in last
                or "\\" in last
                or fnmatch.fnmatchcase(name.casefold(), last.casefold())
            ):
                covered = False
            continue
        bare = line[1:] if line.startswith("/") else line
        is_name_pattern = not any(ch in line for ch in "/[\\")
        if bare == literal or (is_name_pattern and fnmatch.fnmatchcase(name, line)):
            covered = True
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
    # List argv, no shell, bounded. Literal pathspecs: a "[id]" folder is a name,
    # not a glob. fsmonitor off: the project's own .git/config may name a command
    # to run, and the repository-selecting variables of the caller's environment
    # must not point git at another repository.
    env = {k: v for k, v in os.environ.items() if k.upper() not in _GIT_ENV_DROPPED}
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=cwd,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
        env=env,
    )


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _on_disk_segments(project: str, segments: list[str]) -> tuple[list[str], int]:
    """Spell ``segments`` the way they are on disk; also count the existing folders.

    NTFS and macOS open one file under any letter case, while git matches
    paths case-sensitively. Each segment that exists is replaced by the real
    name of the same file (the entry whose identity equals the given spelling's),
    until the first segment that does not exist; the rest is kept as given.
    The count is the number of leading folders (not the leaf) that exist.
    """
    folder = Path(project)
    spelled: list[str] = []
    existing = 0
    for index, segment in enumerate(segments):
        try:
            wanted = (folder / segment).lstat()
        except OSError:
            spelled.extend(segments[index:])
            break
        real = segment
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        if segment not in names:
            for name in names:
                if _fold(name) != _fold(segment):
                    continue
                try:
                    if os.path.samestat(os.lstat(folder / name), wanted):
                        real = name
                        break
                except OSError:
                    continue
        spelled.append(real)
        folder = folder / real
        existing = index + 1
    return spelled, min(existing, len(segments) - 1)


def _git_ignores_case(project: str) -> bool:
    result = _run_git(["-C", project, "config", "--bool", "core.ignorecase"], project)
    return result.returncode == 0 and result.stdout.strip().lower() == b"true"


def _tracked_ignoring_case(project: str, folders: list[str], path: str) -> bool:
    """Compare ``path`` case-folded with what git tracks below ``folders``.

    Covers a tracked file that is missing from disk, which no on-disk spelling
    can find.
    """
    args = ["-C", project, "ls-files", "-z"]
    if folders:
        args += ["--", "/".join(folders)]
    result = _run_git(args, project)
    if result.returncode != 0:
        return False
    wanted = _fold(path)
    for raw in result.stdout.split(b"\0"):
        if raw and _fold(raw.decode("utf-8", errors="surrogateescape")) == wanted:
            return True
    return False


def is_git_tracked(project: str, relpath: str) -> bool:
    """True when git already tracks ``relpath``; no git, a timeout or any error is False.

    The path is first spelled the way it is on disk, so a different letter case
    cannot slip past git's case-sensitive match; when git itself ignores case
    (``core.ignorecase``) the path is also compared case-folded with the tracked
    files, which finds a tracked file that was deleted from disk.
    """
    segments = _relative_segments(relpath)
    spelled, existing = _on_disk_segments(project, segments)
    path = "/".join(spelled)
    try:
        listed = _run_git(
            ["-C", project, "ls-files", "--error-unmatch", "--", path], project
        )
        if listed.returncode == 0:
            return True
        if not _git_ignores_case(project):
            return False
        return _tracked_ignoring_case(project, spelled[:existing], path)
    except (OSError, subprocess.SubprocessError):
        return False

"""Shared .env mutation helpers for CLI, MCP, and the local API."""
from __future__ import annotations

import hashlib
import os
import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional

import pushkey_shared as _s


_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

#: Backups older Pushkey versions wrote into the project folder.
LEGACY_BACKUP_GLOB = ".env.pushkey_backup_*"

_BACKUP_KEEP = 3
_BACKUP_STAMP_FORMAT = "%Y%m%d_%H%M%S_%f"


@dataclass(frozen=True)
class EnvMutationResult:
    env_file: str
    injected_names: list[str]
    updated_names: list[str]
    skipped_existing: list[str]
    wrote: bool

    @property
    def changed_count(self) -> int:
        return len(self.injected_names) + len(self.updated_names)


def format_env_value(value: object, *, force_quote: bool = False) -> str:
    value = str(value) if value is not None else ""
    needs_quotes = (
        force_quote
        or not value
        or value[0].isspace()
        or value[-1].isspace()
        or any(ch in value for ch in ("\n", "\r", "\t", " ", "#", '"'))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def sanitize_env_value(value: object) -> str:
    return str(value).replace("\r", "").replace("\n", "")


def normalize_env_value(value: object) -> str:
    """`value` as it is kept in an env file: None is the empty string, line breaks are dropped.

    Writing a connected variable (`render_connected_value`) and comparing it with what
    the file holds (`decode_env_value(line.value_text)`) must both start from this.
    """
    return "" if value is None else sanitize_env_value(value)


#: Line Pushkey puts above the variables it appends to an env file.
MANAGED_HEADER = "# Managed by Pushkey"

# One assignment line, already split from its line ending: optional indent and
# `export`, the name in its original case, and the value text without the
# whitespace around it. `prefix` is everything before the name.
_ASSIGNMENT_LINE = re.compile(
    r"^(?P<prefix>\s*(?P<export>export\s+)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$"
)
_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOUBLE_QUOTE_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_DOUBLE_QUOTE_DECODED = {"\\": "\\", '"': '"', "n": "\n", "r": "\r"}
_INLINE_COMMENT = re.compile(r"\s#")  # a hash after whitespace starts a comment in an unquoted value
_BARE_CR = re.compile(r"\r(?!\n)")  # a CR that is not the first half of CRLF
# A value that starts or ends with one of these is read as (part of) a quoted string by
# some loaders (python-dotenv, Node) when written bare, so it is always double-quoted.
_QUOTE_CHARS = "'\"`"


@dataclass(frozen=True)
class EnvLine:
    """One `NAME=value` line of an env file.

    `index` is the 0-based line number (lines end at `\\n` or `\\r\\n`), `value_text`
    the text after the `=` as written (still quoted, whitespace around it removed). For
    a double-quoted value that runs over several lines it is the text on the first
    line only; the other lines belong to that value and are not reported.
    """

    index: int
    name: str
    value_text: str
    export: bool


def _split_env_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split env text into (bom, [(line without its ending, its ending)]).

    Only `\\n` ends a line, and a `\\r` just before it belongs to the ending, so a
    separator such as `\\x0c` or `\\u2028` inside a value never splits a line (that is
    what `str.splitlines` would do). The last line has an empty ending when the text
    does not end with a newline.
    """
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    pieces = text[len(bom):].split("\n")
    last = pieces.pop()  # what follows the final "\n"; "" when the text ends with one
    lines = [
        (piece[:-1], "\r\n") if piece.endswith("\r") else (piece, "\n")
        for piece in pieces
    ]
    if last:
        lines.append((last, ""))
    return bom, lines


def _closing_quote_index(text: str, start: int = 0) -> int:
    """Index of the first double quote in `text[start:]` that a backslash does not escape, or -1.

    A backslash escapes the character after it, so `\\"` is not a closing quote but the
    `"` after an escaped backslash (`\\\\"`) is.
    """
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i
        else:
            i += 1
    return -1


def _assignment_spans(lines: list[tuple[str, str]]):
    """Yield `(first, last, match)` for each assignment of the split `lines`.

    `lines[first:last + 1]` hold its value: more than one line when a double-quoted
    value is still open at the end of its line and a later line closes it. Lines inside
    such a value are never matched as assignments. When no later line holds a closing
    quote the value is not treated as multi-line (python-dotenv and Node also keep the
    following lines live then).
    """
    closers = [i for i, (content, _ending) in enumerate(lines) if _closing_quote_index(content) >= 0]
    i = 0
    while i < len(lines):
        match = _ASSIGNMENT_LINE.match(lines[i][0])
        if not match:
            i += 1
            continue
        last = i
        value = match["value"]
        if value.startswith('"') and _closing_quote_index(value, 1) < 0:
            later = bisect_right(closers, i)
            if later < len(closers):
                last = closers[later]
        yield i, last, match
        i = last + 1


def parse_env_lines(text: str) -> list[EnvLine]:
    """Every assignment line of `text`, names in their original case.

    Understands `export NAME=...` and indented lines; a leading BOM is ignored.
    Comments and lines that are not assignments are skipped, and a name that
    appears on several lines gives several entries. The lines inside a multi-line
    double-quoted value are not assignments and are not reported.
    """
    _bom, lines = _split_env_text(text)
    return [
        EnvLine(
            index=first,
            name=match["name"],
            value_text=match["value"],
            export=match["export"] is not None,
        )
        for first, _last, match in _assignment_spans(lines)
    ]


def decode_env_value(value_text: str) -> str:
    """The value a `value_text` stands for (the inverse of `format_env_value`).

    A double-quoted value ends at its first unescaped closing quote (what follows is
    ignored); inside, `\\\\`, `\\"`, `\\n` and `\\r` are decoded in one left-to-right pass and
    any other backslash is kept. A single-quoted value is literal up to the next `'`. An
    unquoted value is cut at the first `#` that follows whitespace and loses its trailing
    whitespace. A value that opens a quote it never closes is read as unquoted text.
    """
    if value_text.startswith('"'):
        end = _closing_quote_index(value_text, 1)
        if end >= 0:
            return _DOUBLE_QUOTE_ESCAPE.sub(
                lambda m: _DOUBLE_QUOTE_DECODED.get(m.group(1), m.group(0)), value_text[1:end]
            )
    elif value_text.startswith("'"):
        end = value_text.find("'", 1)
        if end >= 0:
            return value_text[1:end]
    comment = _INLINE_COMMENT.search(value_text)
    if comment:
        value_text = value_text[: comment.start()]
    return value_text.rstrip()


def render_connected_value(value: object) -> str:
    """The text written after `NAME=` for `value`: the one transform used to write and to compare.

    The value goes through `normalize_env_value` (None is empty, line breaks dropped) and
    `format_env_value`, except that a value starting or ending with `'`, `"` or a
    backtick is always double-quoted so no loader reads it as an open string.
    """
    text = normalize_env_value(value)
    edge_quote = bool(text) and (text[0] in _QUOTE_CHARS or text[-1] in _QUOTE_CHARS)
    return format_env_value(text, force_quote=edge_quote)


def apply_env_assignments(
    text: str, assignments: Mapping[str, str]
) -> tuple[str, list[str], list[str]]:
    """Set variables in env `text`; returns `(new_text, added_vars, updated_vars)`.

    `assignments` maps a variable name to its value text, already rendered with
    `render_connected_value`. Every line of an assigned variable is rewritten as
    `<indent>[export ]NAME=value` (its own line ending is kept); a value that runs over
    several lines is replaced as a whole. The variable is listed once in `updated_vars`
    even when it sits on several lines or already holds that value. Variables not in the
    text are appended under a single `# Managed by Pushkey` header, which is only added
    when it is not there yet. Every other line is kept exactly, including the lines of a
    multi-line quoted value, which are never taken for assignments. A BOM is kept, new
    lines use `\\r\\n` when the text contains it and `\\n` otherwise, and the result ends
    with a newline. With no assignments the text comes back untouched. Both lists follow
    the order of `assignments`.

    Raises ValueError for a name that is not `[A-Za-z_][A-Za-z0-9_]*`, a value with a
    line break (the message names the variable, never the value), or text with a bare
    CR line ending (a CR not followed by LF), which this function cannot rewrite safely.
    """
    for name, value in assignments.items():
        if not _VAR_NAME.fullmatch(name):
            raise ValueError(f"invalid environment variable name: {name!r}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"value for {name} contains a line break; render it first")
    if not assignments:
        return text, [], []
    if _BARE_CR.search(text):
        raise ValueError("env file has bare CR line endings")

    bom, lines = _split_env_text(text)
    eol = "\r\n" if "\r\n" in text else "\n"

    found: set[str] = set()
    out: list[tuple[str, str]] = []
    cursor = 0
    for first, last, match in _assignment_spans(lines):
        name = match["name"]
        if name not in assignments:
            continue
        found.add(name)
        out.extend(lines[cursor:first])
        out.append((f"{match['prefix']}{name}={assignments[name]}", lines[last][1]))
        cursor = last + 1
    out.extend(lines[cursor:])
    if out and not out[-1][1]:
        out[-1] = (out[-1][0], eol)

    added = [name for name in assignments if name not in found]
    updated = [name for name in assignments if name in found]
    if added:
        if not any(content.strip() == MANAGED_HEADER for content, _ending in out):
            if out and out[-1][0].strip():
                out.append(("", eol))
            out.append((MANAGED_HEADER, eol))
        out.extend((f"{name}={assignments[name]}", eol) for name in added)

    return bom + "".join(content + ending for content, ending in out), added, updated


def project_id(project: Path) -> str:
    """Stable 16-hex-char id of a project folder, used to group its backups."""
    resolved = str(Path(project).resolve())
    return hashlib.sha256(resolved.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _private_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # best effort, as for the vault files; some filesystems ignore modes


def _backup_stamps(directory: Path, safe_name: str) -> list[tuple[str, Path]]:
    """Backups of one file in `directory`, oldest first.

    The match is exact so that backing up `.env` never touches the backups of
    `.env.local` (`.env.local.<stamp>.bak` would also fit a `.env.*.bak` glob).
    """
    pattern = re.compile(r"^" + re.escape(safe_name) + r"\.(\d{8}_\d{6}_\d{6})\.bak$")
    found: list[tuple[str, Path]] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return found
    for entry in entries:
        match = pattern.match(entry.name)
        if match:
            found.append((match.group(1), entry))
    found.sort(key=lambda item: item[0])
    return found


def backup_env_file(project: Path, relpath: str, data: bytes) -> Path:
    """Save `data` (the old contents of `<project>/<relpath>`) under ~/.pushkey.

    Backups never go into the project folder: they hold secrets and a project
    folder is usually under version control. Only the newest three backups of
    each file are kept. Raises on failure so the caller does not overwrite the
    original without a backup.
    """
    safe_name = relpath.replace("\\", "/").replace("/", "__")
    if not safe_name:
        raise ValueError("relpath must not be empty")

    root = Path(_s.ENV_BACKUPS_DIR)
    target_dir = root / project_id(project)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_dir.mkdir(mode=0o700, exist_ok=True)
    _private_chmod(root, 0o700)
    _private_chmod(target_dir, 0o700)

    existing = _backup_stamps(target_dir, safe_name)
    moment = datetime.now()
    if existing:
        # The clock is coarse on Windows (about 15 ms): keep names strictly
        # increasing so quick successive backups neither collide nor misorder.
        try:
            newest = datetime.strptime(existing[-1][0], _BACKUP_STAMP_FORMAT)
        except ValueError:
            newest = None
        if newest is not None and moment <= newest:
            moment = newest + timedelta(microseconds=1)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for _ in range(1000):
        path = target_dir / f"{safe_name}.{moment.strftime(_BACKUP_STAMP_FORMAT)}.bak"
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            moment += timedelta(microseconds=1)  # another process won this name
            continue
        break
    else:
        raise OSError(f"could not pick a free backup name in {target_dir}")

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    _private_chmod(path, 0o600)

    for _stamp, old in _backup_stamps(target_dir, safe_name)[:-_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def ensure_gitignore_env(
    project_dir: Path,
    *,
    write: bool = True,
    atomic_write: Optional[Callable[[str, bytes], None]] = None,
) -> bool:
    gitignore = project_dir / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = content.splitlines()
    missing: list[str] = []
    if ".env" not in lines:
        missing.append(".env")
    # Backups from older versions sit in the project and hold secrets.
    if LEGACY_BACKUP_GLOB not in lines and any(project_dir.glob(LEGACY_BACKUP_GLOB)):
        missing.append(LEGACY_BACKUP_GLOB)
    if not missing:
        return False
    new_content = (content.rstrip("\n") + "\n" + "\n".join(missing) + "\n").lstrip("\n")
    if write:
        if atomic_write:
            atomic_write(".gitignore", new_content.encode("utf-8"))
        else:
            gitignore.write_text(new_content, encoding="utf-8")
    return True


def mutate_env_file(
    project_dir: str | Path,
    vault_entries: Mapping[str, Mapping[str, object]],
    *,
    key_names: Optional[list[str]] = None,
    update_existing: bool,
    write: bool = True,
    backup_existing: bool = False,
    atomic_write: Optional[Callable[[str, bytes], None]] = None,
) -> EnvMutationResult:
    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise NotADirectoryError(str(project))

    selected_names = key_names or list(vault_entries.keys())
    selected = {name: vault_entries[name] for name in selected_names if name in vault_entries}
    env_path = project / ".env"
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    existing_keys: set[str] = set()
    updated: list[str] = []
    new_lines: list[str] = []
    for line in existing_lines:
        match = _ENV_LINE.match(line)
        if match:
            key = match.group(1)
            existing_keys.add(key)
            if update_existing and key in selected:
                new_lines.append(f"{key}={format_env_value(selected[key].get('value', ''))}")
                updated.append(key)
                continue
        new_lines.append(line)

    injected = [name for name in selected_names if name in selected and name not in existing_keys]
    if injected:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Managed by Pushkey")
        for name in injected:
            new_lines.append(f"{name}={format_env_value(selected[name].get('value', ''))}")

    skipped = [name for name in selected_names if name in selected and name in existing_keys and not update_existing]
    if write:
        ensure_gitignore_env(project, write=True, atomic_write=atomic_write)
        data = ("\n".join(new_lines) + "\n").encode("utf-8")
        if backup_existing and env_path.exists():
            previous = env_path.read_bytes()
            # Only a change needs a backup: an idempotent re-run must not push
            # the user's real earlier file out of the few kept backups.
            if previous != data:
                backup_env_file(project, ".env", previous)
        if atomic_write:
            atomic_write(".env", data)
        else:
            tmp = env_path.with_name(f".env.pushkey-{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, env_path)

    return EnvMutationResult(
        env_file=str(env_path),
        injected_names=injected,
        updated_names=updated,
        skipped_existing=skipped,
        wrote=write,
    )

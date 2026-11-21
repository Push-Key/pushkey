"""Public bounded cross-process file locking."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
import sys
import time


class FileLockTimeout(RuntimeError):
    """Raised when a bounded file lock cannot be acquired in time."""

    reason = "file_lock_timeout"

    def __init__(self):
        super().__init__(self.reason)


def _is_lock_contention(error):
    return error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)


def _enforce_private_mode(path):
    if os.name == "nt":
        return
    os.chmod(path, 0o600)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OSError("lock file mode is not 0600")


@contextmanager
def bounded_file_lock(path: Path, *, timeout_seconds: float = 5.0, poll_seconds: float = 0.05):
    """Acquire a one-byte cross-process lock, waiting no longer than the timeout."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unbuffered, so a refused write of the initial byte leaves nothing pending in
    # a buffer that a later seek or close would try (and fail) to flush again.
    handle = path.open("a+b", buffering=0)
    acquired = False

    try:
        _enforce_private_mode(path)
        handle.seek(0, 2)
        if handle.tell() == 0:
            try:
                handle.write(b"\0")
            except OSError as error:
                # Another holder created the file, wrote the byte and locked it
                # between our size check and this write; the byte exists, so wait
                # for the lock below instead of failing. Anything else is real.
                if not _is_lock_contention(error):
                    raise
        handle.seek(0)

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as error:
                if not _is_lock_contention(error):
                    raise
                if time.monotonic() >= deadline:
                    raise FileLockTimeout() from None
                time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))

        yield
    finally:
        try:
            if acquired:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

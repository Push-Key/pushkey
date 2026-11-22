"""Cross-process tests for the public bounded file lock."""

import errno
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from pushkey_locking import FileLockTimeout, bounded_file_lock


ROOT = Path(__file__).resolve().parents[1]


def _run_lock_process(lock_path, body, timeout=5.0):
    """Run a fresh interpreter with the repository import path available."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    script = "\n".join(
        [
            "from pathlib import Path",
            "from pushkey_locking import FileLockTimeout, bounded_file_lock",
            "lock_path = Path(r'''%s''')" % lock_path,
            body,
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=timeout,
    )


def test_second_process_times_out_then_acquires_after_release(tmp_path):
    lock_path = tmp_path / "nested" / "shared.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    "from pushkey_locking import bounded_file_lock",
                    "import time",
                    "lock_path = Path(r'''%s''')" % lock_path,
                    "with bounded_file_lock(lock_path):",
                    "    print('locked', flush=True)",
                    "    time.sleep(0.5)",
                ]
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")},
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"

    timed_out = _run_lock_process(
        lock_path,
        "try:\n    with bounded_file_lock(lock_path, timeout_seconds=0.1, poll_seconds=0.01):\n        pass\nexcept FileLockTimeout as exc:\n    print(str(exc))",
    )
    assert timed_out.returncode == 0
    assert "file_lock_timeout" in timed_out.stdout

    assert holder.wait(timeout=5.0) == 0
    acquired = _run_lock_process(lock_path, "with bounded_file_lock(lock_path):\n    print('acquired')")
    assert acquired.returncode == 0, acquired.stderr
    assert acquired.stdout.strip() == "acquired"
    assert lock_path.read_bytes() == b"\0"


def test_exception_in_first_holder_releases_lock_before_process_exit(tmp_path):
    lock_path = tmp_path / "shared.lock"
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    "from pushkey_locking import bounded_file_lock",
                    "import sys",
                    "lock_path = Path(r'''%s''')" % lock_path,
                    "try:",
                    "    with bounded_file_lock(lock_path):",
                    "        raise RuntimeError('holder failed')",
                    "except RuntimeError:",
                    "    print('released', flush=True)",
                    "sys.stdin.readline()",
                ]
            ),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")},
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "released"
    assert child.poll() is None
    try:
        acquired = _run_lock_process(lock_path, "with bounded_file_lock(lock_path):\n    print('acquired')")
        assert acquired.returncode == 0, acquired.stderr
        assert acquired.stdout.strip() == "acquired"
    finally:
        assert child.stdin is not None
        child.stdin.close()
        assert child.wait(timeout=5.0) == 0


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": 0},
    {"timeout_seconds": -1},
    {"poll_seconds": 0},
    {"poll_seconds": -1},
])
def test_bounded_file_lock_rejects_non_positive_timings(tmp_path, kwargs):
    with pytest.raises(ValueError):
        with bounded_file_lock(tmp_path / "shared.lock", **kwargs):
            pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_bounded_file_lock_enforces_private_mode_for_existing_file(tmp_path):
    lock_path = tmp_path / "shared.lock"
    lock_path.write_bytes(b"\0")
    os.chmod(lock_path, 0o644)
    with bounded_file_lock(lock_path):
        assert lock_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_bounded_file_lock_raises_when_vault_lock_mode_cannot_be_enforced(tmp_path, monkeypatch):
    import pushkey_locking
    lock_path = tmp_path / ".vault.lock"
    monkeypatch.setattr(pushkey_locking, "_enforce_private_mode", lambda _path: (_ for _ in ()).throw(OSError("chmod")))
    with pytest.raises(OSError, match="chmod"):
        with bounded_file_lock(lock_path):
            pass


# -- first creation of the lock file ------------------------------------------


class _EmptyFileHolder:
    """Hold the one-byte lock on a lock file that is still empty.

    Another holder that has just created the file and locked byte 0 looks exactly
    like this to a latecomer: from its point of view the file is still empty, and
    on Windows a write into the locked byte is refused.
    """

    def __init__(self, lock_path):
        self._lock_path = lock_path
        self._handle = None

    def acquire(self):
        self._handle = self._lock_path.open("a+b")
        self._handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class _FileThatFailsItsFirstWrite:
    """Delegates to a real file handle, but its first write raises the given error."""

    def __init__(self, real, error):
        self._real = real
        self._error = error
        self.failed = False

    def write(self, data):
        if not self.failed:
            self.failed = True
            raise self._error
        return self._real.write(data)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _make_lock_file_fail_its_first_write(patch, lock_path, error):
    """Make Path.open hand bounded_file_lock a handle whose first write fails."""
    real_open = Path.open
    handles = []

    def open_with_failing_write(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if self != lock_path:
            return handle
        wrapped = _FileThatFailsItsFirstWrite(handle, error)
        handles.append(wrapped)
        return wrapped

    patch.setattr(Path, "open", open_with_failing_write)
    return handles


def _outcome_of(action):
    """Run action(); return the exception it raised, or None."""
    try:
        action()
    except BaseException as exc:
        return exc
    return None


def test_concurrent_first_creation_never_raises(tmp_path):
    lock_path = tmp_path / "first-creation.lock"
    thread_count = 4
    rounds = 1000
    errors = []
    entered = []
    occupancy = {"now": 0, "max": 0}

    def delete_lock_file():
        # Runs once per round, after every worker has arrived and before any is
        # released, so each round starts with a lock file that does not exist yet.
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    round_start = threading.Barrier(thread_count, action=delete_lock_file, timeout=30)
    round_end = threading.Barrier(thread_count, timeout=30)

    def worker(worker_id):
        try:
            for round_number in range(rounds):
                round_start.wait()
                try:
                    with bounded_file_lock(lock_path, timeout_seconds=5, poll_seconds=0.001):
                        occupancy["now"] += 1
                        occupancy["max"] = max(occupancy["max"], occupancy["now"])
                        entered.append((round_number, worker_id))
                        occupancy["now"] -= 1
                except Exception as exc:
                    errors.append((round_number, worker_id, repr(exc)))
                round_end.wait()
        except BaseException as exc:  # a broken barrier ends the whole run
            errors.append((-1, worker_id, repr(exc)))

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not any(thread.is_alive() for thread in threads), "worker thread hung"
    assert not errors, errors[:5]
    expected = {(r, w) for r in range(rounds) for w in range(thread_count)}
    assert not expected - set(entered), sorted(expected - set(entered))[:5]
    assert len(entered) == len(expected)
    assert occupancy["max"] == 1, "two holders were inside the lock at the same time"


@pytest.mark.parametrize("contention_errno", [errno.EACCES, errno.EAGAIN])
def test_initial_byte_write_contention_is_not_an_error(tmp_path, monkeypatch, contention_errno):
    lock_path = tmp_path / "contended-init.lock"
    entered = []

    def acquire():
        with bounded_file_lock(lock_path, timeout_seconds=2, poll_seconds=0.01):
            entered.append(True)

    with monkeypatch.context() as patch:
        handles = _make_lock_file_fail_its_first_write(
            patch, lock_path, OSError(contention_errno, "another holder owns the lock byte")
        )
        outcome = _outcome_of(acquire)

    assert outcome is None, repr(outcome)
    assert [handle.failed for handle in handles] == [True]
    assert entered == [True]
    # The lock was released: an ordinary second acquisition goes straight through.
    assert _outcome_of(acquire) is None
    assert entered == [True, True]


@pytest.mark.parametrize("other_errno", [errno.ENOSPC, errno.EIO])
def test_initial_byte_write_failure_other_than_contention_still_raises(tmp_path, monkeypatch, other_errno):
    lock_path = tmp_path / "failing-init.lock"
    entered = []

    def acquire():
        with bounded_file_lock(lock_path, timeout_seconds=2, poll_seconds=0.01):
            entered.append(True)

    with monkeypatch.context() as patch:
        handles = _make_lock_file_fail_its_first_write(patch, lock_path, OSError(other_errno, "disk trouble"))
        outcome = _outcome_of(acquire)

    assert isinstance(outcome, OSError), repr(outcome)
    assert outcome.errno == other_errno
    assert [handle.failed for handle in handles] == [True]
    assert entered == []
    # The failed attempt left no open handle behind (Windows refuses to delete one).
    lock_path.unlink()


def test_initial_byte_write_denied_by_a_holder_waits_for_its_release(tmp_path):
    lock_path = tmp_path / "held-while-empty.lock"
    holder = _EmptyFileHolder(lock_path)
    holder.acquire()
    released_at = []
    acquired_at = []

    def release_soon():
        time.sleep(0.3)
        released_at.append(time.monotonic())
        holder.release()

    def acquire():
        with bounded_file_lock(lock_path, timeout_seconds=10, poll_seconds=0.01):
            acquired_at.append(time.monotonic())

    releaser = threading.Thread(target=release_soon)
    releaser.start()
    try:
        outcome = _outcome_of(acquire)
    finally:
        releaser.join(timeout=10)
        holder.release()

    assert outcome is None, repr(outcome)
    assert released_at, "the holder never released"
    assert acquired_at and acquired_at[0] >= released_at[0]


def test_initial_byte_write_denied_by_a_holder_still_times_out(tmp_path):
    lock_path = tmp_path / "held-while-empty-timeout.lock"
    holder = _EmptyFileHolder(lock_path)
    holder.acquire()

    def acquire():
        with bounded_file_lock(lock_path, timeout_seconds=0.2, poll_seconds=0.01):
            raise AssertionError("acquired a lock that another holder still owns")

    try:
        started = time.monotonic()
        outcome = _outcome_of(acquire)
        waited = time.monotonic() - started
    finally:
        holder.release()

    assert isinstance(outcome, FileLockTimeout), repr(outcome)
    assert 0.15 <= waited < 5, waited

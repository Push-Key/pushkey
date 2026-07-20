"""Cross-process tests for the public bounded file lock."""

import os
from pathlib import Path
import subprocess
import sys

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

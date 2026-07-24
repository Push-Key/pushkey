#!/usr/bin/env python
"""Smoke-test package reinstall without losing an existing local vault."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(command: list[str], *, env: dict[str, str], cwd: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, help="Wheel path to force-reinstall.")
    args = parser.parse_args()

    wheel = Path(args.wheel).resolve()
    if not wheel.exists():
        raise SystemExit(f"wheel not found: {wheel}")

    with tempfile.TemporaryDirectory(prefix="pushkey-upgrade-smoke-") as home:
        env = os.environ.copy()
        env["HOME"] = home
        env["USERPROFILE"] = home
        env["PUSHKEY_MASTER"] = "upgrade-smoke-password"
        recovery_file = str(Path(home) / "recovery.txt")
        venv_dir = Path(home) / ".venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        child_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = [str(child_python), "-m", "pushkey_cli"]

        install_command = [
            str(child_python),
            "-m",
            "pip",
            "install",
            str(wheel),
        ]
        reinstall_command = [
            str(child_python),
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(wheel),
        ]

        _run(install_command, env=env, cwd=home)
        _run([*cli, "--password", env["PUSHKEY_MASTER"], "init", "--recovery-file", recovery_file], env=env, cwd=home)
        _run([*cli, "--password", env["PUSHKEY_MASTER"], "add", "UPGRADE_SMOKE_KEY", "sk-upgrade-smoke"], env=env, cwd=home)

        before = _run([*cli, "--password", env["PUSHKEY_MASTER"], "get", "UPGRADE_SMOKE_KEY"], env=env, cwd=home)

        _run(reinstall_command, env=env, cwd=home)

        after = _run([*cli, "--password", env["PUSHKEY_MASTER"], "get", "UPGRADE_SMOKE_KEY"], env=env, cwd=home)
        if before.stdout != after.stdout or "sk-upgrade-smoke" not in after.stdout:
            raise SystemExit("vault value changed or disappeared after package reinstall")

        if not (Path(home) / ".pushkey" / "vault.enc").exists():
            raise SystemExit("vault file missing after package reinstall")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

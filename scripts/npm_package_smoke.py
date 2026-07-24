#!/usr/bin/env python
"""Smoke-test the npm wrapper in an isolated prefix."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NPM_PACKAGE = ROOT / "npm"


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _write_fake_python(bin_dir: Path) -> None:
    if os.name == "nt":
        shim = bin_dir / "python.cmd"
        shim.write_text(
            "@echo off\r\n"
            "if \"%1\"==\"-m\" if \"%2\"==\"pushkey_cli\" exit /b 0\r\n"
            "exit /b 1\r\n",
            encoding="ascii",
        )
        return

    shim = bin_dir / "python"
    shim.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"pushkey_cli\" ]; then exit 0; fi\n"
        "exit 1\n",
        encoding="ascii",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)


def _global_bin(prefix: Path) -> Path:
    if os.name == "nt":
        return prefix / "pushkey.cmd"
    return prefix / "bin" / "pushkey"


def main() -> int:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found")

    with tempfile.TemporaryDirectory(prefix="pushkey-npm-smoke-") as tmp:
        tmp_path = Path(tmp)
        prefix = tmp_path / "prefix"
        fake_bin = tmp_path / "fake-bin"
        pack_dir = tmp_path / "pack"
        fake_bin.mkdir()
        pack_dir.mkdir()
        _write_fake_python(fake_bin)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

        packed = _run([npm, "pack", str(NPM_PACKAGE), "--pack-destination", str(pack_dir)], cwd=ROOT, env=env)
        tarball_name = packed.stdout.strip().splitlines()[-1]
        tarball = pack_dir / tarball_name
        if not tarball.exists():
            raise SystemExit(f"npm pack did not create tarball: {tarball}")

        install = [npm, "install", "-g", "--ignore-scripts", "--prefix", str(prefix), str(tarball)]
        _run(install, cwd=ROOT, env=env)
        _run([str(_global_bin(prefix)), "--help"], cwd=ROOT, env=env)
        _run(install, cwd=ROOT, env=env)
        _run([str(_global_bin(prefix)), "--help"], cwd=ROOT, env=env)
        _run(
            [
                npm,
                "exec",
                "--yes",
                "--ignore-scripts",
                "--package",
                str(tarball),
                "--",
                "pushkey",
                "--help",
            ],
            cwd=ROOT,
            env=env,
        )
        _run([npm, "uninstall", "-g", "--prefix", str(prefix), "@pushkey/cli"], cwd=ROOT, env=env)

        if _global_bin(prefix).exists():
            raise SystemExit("npm uninstall left the pushkey shim behind")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

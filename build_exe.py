#!/usr/bin/env python
"""Build Pushkey as a standalone Windows executable using PyInstaller."""

import subprocess
import sys
from pathlib import Path

SUBMODULES = [
    "pushkey_shared",
    "pushkey_crypto",
    "pushkey_vault",
    "pushkey_tiers",
    "pushkey_providers",
    "pushkey_icons",
]


def _common_flags(root):
    """Flags shared by both GUI and CLI builds."""
    flags = ["--noconfirm", "--collect-all", "cryptography", "--collect-all", "customtkinter"]
    for mod in SUBMODULES:
        flags += ["--hidden-import", mod]
    providers_path = root / "providers.json"
    if providers_path.exists():
        flags += ["--add-data", f"{providers_path};."]
    return flags


def build_gui(root):
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--name", "Pushkey"]
    cmd += _common_flags(root)

    icon_path = root / "pushkey.ico"
    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]

    logo_path = root / "pushkey_logo.png"
    if logo_path.exists():
        cmd += ["--add-data", f"{logo_path};."]

    cmd.append(str(root / "pushkey.py"))
    print(f"Building GUI: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=root).returncode


def build_cli(root):
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--name", "pushkey-cli"]
    cmd += _common_flags(root)
    cmd.append(str(root / "pushkey_cli.py"))
    print(f"Building CLI: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=root).returncode


def build():
    root = Path(__file__).parent
    rc = build_gui(root)
    if rc != 0:
        return rc
    return build_cli(root)


if __name__ == "__main__":
    sys.exit(build())

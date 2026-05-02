#!/usr/bin/env python
"""Build Pushkey as a standalone Windows executable using PyInstaller."""

import subprocess
import sys
from pathlib import Path

def build():
    """Build executable."""
    root = Path(__file__).parent

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "Pushkey",
        "--collect-all", "cryptography",
        "--collect-all", "customtkinter",
        "--hidden-import", "pushkey_icons",
        str(root / "pushkey.py"),
    ]

    # Add icon if present
    icon_path = root / "pushkey.ico"
    if icon_path.exists():
        cmd.insert(4, str(icon_path))
        cmd.insert(4, "--icon")

    # Bundle logo PNG so it's available inside the exe
    logo_path = root / "pushkey_logo.png"
    if logo_path.exists():
        cmd.insert(4, f"{logo_path};.")
        cmd.insert(4, "--add-data")

    # Bundle providers.json
    providers_path = root / "providers.json"
    if providers_path.exists():
        cmd.insert(4, f"{providers_path};.")
        cmd.insert(4, "--add-data")

    print(f"Building: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root)
    return result.returncode

if __name__ == "__main__":
    sys.exit(build())

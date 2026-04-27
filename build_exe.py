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
        str(root / "pushkey.py"),
    ]

    # Add icon if present
    icon_path = root / "pushkey.ico"
    if icon_path.exists():
        cmd.insert(4, str(icon_path))
        cmd.insert(4, "--icon")

    print(f"Building: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root)
    return result.returncode

if __name__ == "__main__":
    sys.exit(build())

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
        "--icon", "pushkey.ico" if (root / "pushkey.ico").exists() else None,
        "--add-data", ".pushkey:.",  # Include default vault dir
        "--collect-all", "cryptography",
        str(root / "pushkey.py"),
    ]

    # Filter out None values
    cmd = [c for c in cmd if c is not None]

    print(f"Building: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root)
    return result.returncode

if __name__ == "__main__":
    sys.exit(build())

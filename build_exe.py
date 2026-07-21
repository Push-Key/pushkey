#!/usr/bin/env python
"""Build Pushkey as a standalone Windows executable using PyInstaller."""

import subprocess
import sys
from pathlib import Path
import tomllib

SUBMODULES = [
    "pushkey_shared",
    "pushkey_crypto",
    "pushkey_vault",
    "pushkey_tiers",
    "pushkey_providers",
    "pushkey_icons",
    "pushkey_env",
    "pushkey_local_api",
    "pushkey_mcp",
    "pushkey_agent_tokens",
]


def _project_metadata(root):
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    version = project["version"]
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return {
        "version": version,
        "version_tuple": tuple(parts[:4]),
        "name": project["name"],
        "author": project["authors"][0]["name"],
    }


def _write_version_file(root, exe_name, description):
    metadata = _project_metadata(root)
    version_path = root / "build" / f"{exe_name}-version.txt"
    version_path.parent.mkdir(exist_ok=True)
    file_version = metadata["version"]
    tuple_text = repr(metadata["version_tuple"])
    version_path.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple_text},
    prodvers={tuple_text},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '{metadata["author"]}'),
          StringStruct('FileDescription', '{description}'),
          StringStruct('FileVersion', '{file_version}'),
          StringStruct('InternalName', '{exe_name}'),
          StringStruct('OriginalFilename', '{exe_name}.exe'),
          StringStruct('ProductName', 'Pushkey'),
          StringStruct('ProductVersion', '{file_version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return version_path


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
    cmd += ["--version-file", str(_write_version_file(root, "Pushkey", "Pushkey desktop vault"))]

    icon_path = root / "pushkey.ico"
    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]
        cmd += ["--add-data", f"{icon_path};."]

    logo_path = root / "pushkey_logo.png"
    if logo_path.exists():
        cmd += ["--add-data", f"{logo_path};."]

    cmd.append(str(root / "pushkey.py"))
    print(f"Building GUI: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=root).returncode


def build_cli(root):
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--name", "pushkey-cli"]
    cmd += _common_flags(root)
    cmd += ["--version-file", str(_write_version_file(root, "pushkey-cli", "Pushkey command-line vault"))]
    web_out = root / "web-app" / "out"
    if not (web_out / "pushkey-integrity.json").exists():
        raise RuntimeError("web app integrity manifest missing")
    cmd += ["--add-data", f"{web_out};web-app/out"]
    cmd.append(str(root / "pushkey_cli.py"))
    print(f"Building CLI: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=root).returncode


def build():
    root = Path(__file__).parent
    web_build = subprocess.run(
        ["npm", "run", "build"],
        cwd=root / "web-app",
        shell=sys.platform == "win32",
    )
    if web_build.returncode != 0:
        return web_build.returncode
    rc = build_gui(root)
    if rc != 0:
        return rc
    return build_cli(root)


if __name__ == "__main__":
    sys.exit(build())

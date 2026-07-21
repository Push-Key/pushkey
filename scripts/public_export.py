from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_ALLOWLIST = (
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "browser-pushkey",
    "build_exe.py",
    "docs",
    "package.json",
    "pushkey.py",
    "pushkey_agent_tokens.py",
    "pushkey_cli.py",
    "pushkey_cloud_api.py",
    "pushkey_crypto.py",
    "pushkey_env.py",
    "pushkey_icons.py",
    "pushkey_local_api.py",
    "pushkey_mcp.py",
    "pushkey_providers.py",
    "pushkey_shared.py",
    "pushkey_tiers.py",
    "pushkey_vault.py",
    "pyproject.toml",
    "requirements-api.txt",
    "requirements-dev.txt",
    "requirements.txt",
    "scripts",
    "server",
    "tests",
    "vercel.json",
    "vscode-pushkey",
    "web",
    "web-app",
)

DENY_NAMES = {
    ".env",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def _is_denied(path: Path) -> bool:
    return any(part in DENY_NAMES for part in path.parts)


def export_public_repo(source: Path, destination: Path) -> list[Path]:
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("destination must be outside the source checkout")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    copied: list[Path] = []
    for item in DEFAULT_ALLOWLIST:
        src = source / item
        if not src.exists():
            continue
        if src.is_dir():
            for child in src.rglob("*"):
                relative = child.relative_to(source)
                if _is_denied(relative) or not child.is_file():
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
                copied.append(relative)
        elif not _is_denied(src.relative_to(source)):
            target = destination / item
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(Path(item))
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the public Pushkey repository allowlist.")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    args = parser.parse_args()

    copied = export_public_repo(args.source, args.destination)
    print(f"Exported {len(copied)} files to {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

#: Directory and file names never copied into the public export, matched against
#: any path component.
#:
#: `.next` matters as much as `.env` here. A built `web/` tree contains
#: `.next/prerender-manifest.json` and `.next/cache/.previewinfo`, which hold
#: real `previewModeSigningKey` and `previewModeEncryptionKey` values for that
#: deployment. Because `web` and `web-app` are on the allowlist, running this
#: export on any machine that had built the frontends would have copied those
#: keys straight into the public boundary.
DENY_NAMES = {
    ".env",
    ".git",
    ".mypy_cache",
    ".next",
    ".playwright-mcp",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    ".vercel",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "test-results",
}


#: Dotenv files safe to publish. Everything else matching `.env*` is denied.
ENV_ALLOWED_NAMES = {".env.example", ".env.sample", ".env.template"}


def _is_denied_name(name: str) -> bool:
    if name in DENY_NAMES:
        return True
    # Exact-name matching on ".env" missed every real-world variant:
    # .env.local, .env.production, .env.vercel.local, .env.production.fetched.
    # Those hold live credentials and sit right next to the tracked
    # .env.example, so the export happily copied them into the public
    # boundary. Deny the whole family and allow back only the templates.
    if name.startswith(".env") and name not in ENV_ALLOWED_NAMES:
        return True
    return False


def _is_denied(path: Path) -> bool:
    return any(_is_denied_name(part) for part in path.parts)


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

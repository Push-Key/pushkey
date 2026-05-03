"""
Pushkey CLI - standalone command-line interface.
No tkinter dependency. Password via PUSHKEY_MASTER env var, --password arg, or prompt.
"""
import argparse
import getpass
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pushkey_shared as _s
from pushkey_crypto import log_event
from pushkey_providers import PROVIDERS, detect_provider, days_since, health_status
from pushkey_vault import load_vault, save_vault


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_password(args):
    pw = os.environ.get("PUSHKEY_MASTER") or getattr(args, "password", None)
    if pw:
        return pw
    try:
        return getpass.getpass("Master password: ")
    except (EOFError, KeyboardInterrupt):
        print("Aborted.", file=sys.stderr)
        sys.exit(1)


def _open_vault(args):
    password = _get_password(args)
    _s.ensure_vault_dir()
    vault = load_vault(password)
    if vault is None:
        print("Error: wrong master password", file=sys.stderr)
        sys.exit(1)
    return vault, password


_ENV_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


def _format_env_value(value):
    value = str(value) if value is not None else ""
    needs_quotes = (
        not value
        or value[0].isspace()
        or value[-1].isspace()
        or any(ch in value for ch in ("\n", "\r", "\t", " ", "#", '"'))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def _ensure_gitignore(project_dir):
    gi = Path(project_dir) / ".gitignore"
    if gi.exists():
        lines = gi.read_text(encoding="utf-8").splitlines()
        if ".env" not in lines:
            gi.write_text(gi.read_text(encoding="utf-8").rstrip() + "\n.env\n", encoding="utf-8")
    else:
        gi.write_text(".env\n", encoding="utf-8")


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_add(args, vault, password):
    name = args.name.upper()
    if name in vault:
        print(f"Error: '{name}' already exists. Use 'rotate' to update.", file=sys.stderr)
        sys.exit(1)
    provider = detect_provider(name, args.value)
    now = datetime.now().isoformat()
    vault[name] = {
        "value": args.value,
        "created": now,
        "rotated": None,
        "provider": provider,
        "env": "all",
        "projects": [],
        "notes": args.notes or "",
        "rotation_count": 0,
    }
    save_vault(vault, password)
    log_event(f"cli: added {name}")
    suffix = f" [{provider}]" if provider else ""
    print(f"Added {name}{suffix}")


def cmd_get(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        print(f"Error: '{name}' not found", file=sys.stderr)
        sys.exit(1)
    value = vault[name]["value"]
    if args.clip:
        try:
            import pyperclip
            pyperclip.copy(value)
            print(f"{name} copied to clipboard")
        except ImportError:
            print("Error: install pyperclip for --clip support:  pip install pyperclip", file=sys.stderr)
            sys.exit(1)
    else:
        print(value)


def cmd_list(args, vault, password):
    rows = []
    for name, info in sorted(vault.items()):
        status = health_status(info)
        if args.status and status != args.status:
            continue
        age = days_since(info.get("rotated") or info.get("created"))
        age_str = f"{int(age)}d" if age != float("inf") else "?"
        rows.append({
            "name": name,
            "provider": info.get("provider") or "—",
            "age": age_str,
            "status": status,
            "env": info.get("env", "all"),
        })

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    if not rows:
        print("No keys found.")
        return

    w_name = max(len(r["name"]) for r in rows)
    w_prov = max(len(r["provider"]) for r in rows)
    icon = {"healthy": "✓", "warning": "!", "critical": "✗"}
    header = f"{'NAME':<{w_name}}  {'PROVIDER':<{w_prov}}  {'AGE':>6}  STATUS"
    print(header)
    print("─" * len(header))
    for r in rows:
        print(f"{r['name']:<{w_name}}  {r['provider']:<{w_prov}}  {r['age']:>6}  {icon.get(r['status'], '?')} {r['status']}")


def cmd_rotate(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        print(f"Error: '{name}' not found", file=sys.stderr)
        sys.exit(1)
    new_val = args.new_value
    if not new_val:
        try:
            new_val = getpass.getpass(f"New value for {name}: ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.", file=sys.stderr)
            sys.exit(1)
    now = datetime.now().isoformat()
    info = vault[name]
    info.setdefault("history", []).insert(0, {"value": info["value"], "retired": now})
    info["history"] = info["history"][:10]
    info["value"] = new_val
    info["rotated"] = now
    info["rotation_count"] = info.get("rotation_count", 0) + 1
    save_vault(vault, password)
    log_event(f"cli: rotated {name}")
    print(f"Rotated {name}")


def cmd_delete(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        print(f"Error: '{name}' not found", file=sys.stderr)
        sys.exit(1)
    if not args.yes:
        try:
            confirm = input(f"Delete '{name}'? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            return
        if confirm.strip().lower() != "y":
            print("Cancelled.")
            return
    del vault[name]
    save_vault(vault, password)
    log_event(f"cli: deleted {name}")
    print(f"Deleted {name}")


def cmd_status(args, vault, password):
    counts = {"healthy": 0, "warning": 0, "critical": 0}
    for info in vault.values():
        counts[health_status(info)] += 1
    total = sum(counts.values())
    print(f"Vault: {total} key(s)")
    print(f"  ✓ healthy:   {counts['healthy']}")
    print(f"  ! warning:   {counts['warning']}")
    print(f"  ✗ critical:  {counts['critical']}")


def cmd_inject(args, vault, password):
    project = Path(getattr(args, "project", None) or Path.cwd()).resolve()
    if not project.is_dir():
        print(f"Error: '{project}' is not a directory", file=sys.stderr)
        sys.exit(1)

    inject_all = getattr(args, "all", False)
    keys_to_write = {
        n: v for n, v in vault.items()
        if str(project) in (v.get("projects") or [])
    }
    if not keys_to_write:
        if inject_all:
            keys_to_write = dict(vault)
        else:
            print(f"No keys assigned to {project}.")
            print("Assign keys via the GUI, or use --all to inject all keys.")
            sys.exit(0)

    env_path = project / ".env"
    if env_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(str(env_path), str(env_path.with_name(f".env.pushkey_backup_{ts}")))

    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated = set()
    new_lines = []
    for line in existing_lines:
        m = _ENV_LINE.match(line)
        if m and m.group(1) in keys_to_write:
            key = m.group(1)
            new_lines.append(f"{key}={_format_env_value(keys_to_write[key]['value'])}")
            updated.add(key)
        else:
            new_lines.append(line)

    new_keys = {k: v for k, v in keys_to_write.items() if k not in updated}
    if new_keys:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Managed by Pushkey")
        for k in sorted(new_keys):
            new_lines.append(f"{k}={_format_env_value(new_keys[k]['value'])}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    _ensure_gitignore(project)
    log_event(f"cli: injected {len(keys_to_write)} keys into {project}")
    print(f"Wrote {len(keys_to_write)} key(s) to {env_path}")


def cmd_import(args, vault, password):
    path = Path(args.file)
    if not path.exists():
        print(f"Error: '{path}' not found", file=sys.stderr)
        sys.exit(1)
    content = path.read_text(encoding="utf-8")
    now = datetime.now().isoformat()
    added = skipped = 0
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        name = m.group(1).upper()
        value = m.group(2).strip().strip('"').strip("'")
        if name in vault:
            skipped += 1
            continue
        provider = detect_provider(name, value)
        vault[name] = {
            "value": value,
            "created": now,
            "rotated": None,
            "provider": provider,
            "env": "all",
            "projects": [],
            "notes": f"imported from {path.name}",
            "rotation_count": 0,
        }
        added += 1

    if added:
        save_vault(vault, password)
        log_event(f"cli: imported {added} keys from {path.name}")
    print(f"Imported {added} key(s), skipped {skipped} existing")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="pushkey",
        description="Pushkey - encrypted API key manager",
    )
    parser.add_argument("--password", "-p", help="Master password (or set PUSHKEY_MASTER)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add a new key")
    p_add.add_argument("name", help="Key name, e.g. OPENAI_API_KEY")
    p_add.add_argument("value", help="Key value")
    p_add.add_argument("--notes", help="Optional notes")

    p_get = sub.add_parser("get", help="Print a key value")
    p_get.add_argument("name")
    p_get.add_argument("--clip", "-c", action="store_true", help="Copy to clipboard")

    p_list = sub.add_parser("list", help="List all keys")
    p_list.add_argument("--status", choices=["healthy", "warning", "critical"], help="Filter by health status")
    p_list.add_argument("--json", action="store_true", help="JSON output")

    p_rotate = sub.add_parser("rotate", help="Rotate key to a new value")
    p_rotate.add_argument("name")
    p_rotate.add_argument("new_value", nargs="?", default=None, help="New value (prompted if omitted)")

    p_delete = sub.add_parser("delete", help="Delete a key")
    p_delete.add_argument("name")
    p_delete.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    sub.add_parser("status", help="Health summary")

    p_inject = sub.add_parser("inject", help="Write keys to project .env")
    p_inject.add_argument("--project", help="Project path (default: current directory)")
    p_inject.add_argument("--all", action="store_true", dest="all", help="Inject all keys regardless of project assignment")

    p_import = sub.add_parser("import", help="Bulk import keys from a .env file")
    p_import.add_argument("file", help="Path to .env file")

    args = parser.parse_args()
    vault, password = _open_vault(args)

    {
        "add":    cmd_add,
        "get":    cmd_get,
        "list":   cmd_list,
        "rotate": cmd_rotate,
        "delete": cmd_delete,
        "status": cmd_status,
        "inject": cmd_inject,
        "import": cmd_import,
    }[args.command](args, vault, password)


if __name__ == "__main__":
    main()

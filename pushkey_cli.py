"""
Pushkey CLI - standalone command-line interface.
No tkinter dependency. Password via PUSHKEY_MASTER env var, --password arg, or prompt.
"""
import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pushkey_shared as _s
from pushkey_crypto import log_event
from pushkey_providers import PROVIDERS, detect_provider, days_since, health_status
from pushkey_vault import load_vault, save_vault


# ── ANSI colors ───────────────────────────────────────────────────────────────

def _supports_color():
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()

_COLOR = _supports_color()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def cyan(t):    return _c("96", t)
def green(t):   return _c("92", t)
def yellow(t):  return _c("93", t)
def red(t):     return _c("91", t)
def bold(t):    return _c("1",  t)
def dim(t):     return _c("2",  t)
def magenta(t): return _c("95", t)

def ok(msg):   print(green("✓ ") + msg)
def warn(msg): print(yellow("! ") + msg)
def err(msg):  print(red("✗ ") + msg, file=sys.stderr)


# ── banner + help ─────────────────────────────────────────────────────────────

_LOGO = [
    " ██████╗ ██╗   ██╗███████╗██╗  ██╗██╗  ██╗███████╗██╗   ██╗",
    " ██╔══██╗██║   ██║██╔════╝██║  ██║██║ ██╔╝██╔════╝╚██╗ ██╔╝",
    " ██████╔╝██║   ██║███████╗███████║█████╔╝ █████╗   ╚████╔╝ ",
    " ██╔═══╝ ██║   ██║╚════██║██╔══██║██╔═██╗ ██╔══╝    ╚██╔╝  ",
    " ██║     ╚██████╔╝███████║██║  ██║██║  ██╗███████╗   ██║   ",
    " ╚═╝      ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝  ",
]

_SPLIT = 34  # PUSH = first 34 chars, KEY = remainder


def _print_banner():
    try:
        from pushkey_shared import VERSION
    except ImportError:
        VERSION = "2.1.0"
    print()
    for logo_line in _LOGO:
        print("  " + cyan(logo_line[:_SPLIT]) + red(logo_line[_SPLIT:]))
    print()
    print(f"  {bold('Encrypted API key manager')}  {dim('v' + VERSION)}")
    print(f"  {dim('─' * 54)}")
    print(f"  Store, rotate, and inject API keys — encrypted at rest.")
    print(f"  Vault shared with the GUI · zero plaintext on disk.")
    print(f"  {dim('─' * 54)}\n")


def _print_help():
    _print_banner()
    print(f"  {bold('Usage:')}  pushkey {cyan('<command>')} [options]\n")
    cmds = [
        ("add",        "<NAME> [VALUE]",    "Store a new key  (--generate for random value)"),
        ("get",        "<NAME>",            "Print or copy a key  (--clip)"),
        ("list",       "",                  "List all keys + health status"),
        ("rotate",     "<NAME> [VALUE]",    "Rotate to a new value  (--generate)"),
        ("delete",     "<NAME>",            "Remove a key"),
        ("status",     "",                  "Vault health summary"),
        ("inject",     "",                  "Write keys to .env  (--env prod|dev|staging)"),
        ("import",     "<FILE>",            "Bulk import from a .env file"),
        ("assign",     "<NAME> <PATH>",     "Assign key to a project  (--remove to unassign)"),
        ("info",       "<NAME>",            "Show full key metadata"),
        ("history",    "<NAME>",            "Show rotation history  (--reveal to unmask)"),
        ("note",       "<NAME> [TEXT]",     "Add or update a note on a key"),
        ("log",        "",                  "Show audit log  (--limit N  --key NAME)"),
        ("passwd",     "",                  "Change master password"),
        ("init",       "",                  "Create a new vault (first-time setup)"),
        ("completion", "<bash|zsh|ps>",     "Print shell completion script"),
    ]
    print(f"  {bold('Commands:')}")
    for name, args_, desc in cmds:
        args_str = dim(f" {args_}") if args_ else ""
        print(f"    {cyan(f'{name:<8}')}{args_str:<30}  {desc}")
    print()
    print(f"  {bold('Options:')}")
    print(f"    {cyan('-p')}, {cyan('--password')}  Master password  {dim('(or set PUSHKEY_MASTER)')}")
    print(f"    {cyan('-h')}, {cyan('--help')}      Show help for any command\n")
    print(f"  {dim('Examples:')}")
    print(f"    {dim('pushkey add OPENAI_API_KEY sk-abc123')}")
    print(f"    {dim('pushkey list --status critical')}")
    print(f"    {dim('pushkey inject --all')}\n")


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_password(args):
    pw = os.environ.get("PUSHKEY_MASTER") or getattr(args, "password", None)
    if pw:
        return pw
    try:
        return getpass.getpass(bold("Master password: "))
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)


def _open_vault(args):
    password = _get_password(args)
    _s.ensure_vault_dir()
    result = load_vault(password)
    if result is None:
        err("Wrong master password")
        sys.exit(1)
    vault = result[0] if isinstance(result, tuple) else result
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
        err(f"'{name}' already exists — use {cyan('rotate')} to update")
        sys.exit(1)
    provider = detect_provider(name, args.value)
    now = datetime.now().isoformat()
    vault[name] = {
        "value":          args.value,
        "created":        now,
        "rotated":        None,
        "provider":       provider,
        "env":            "all",
        "projects":       [],
        "notes":          args.notes or "",
        "rotation_count": 0,
    }
    save_vault(vault, password)
    log_event(f"cli: added {name}")
    suffix = f"  {dim('[' + provider + ']')}" if provider else ""
    ok(f"Added {bold(name)}{suffix}")


def cmd_get(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    value = vault[name]["value"]
    if args.clip:
        try:
            import pyperclip
            pyperclip.copy(value)
            ok(f"{bold(name)} copied to clipboard")
        except ImportError:
            err("install pyperclip for --clip:  pip install pyperclip")
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
            "name":     name,
            "provider": info.get("provider") or "—",
            "age":      age_str,
            "status":   status,
            "env":      info.get("env", "all"),
        })

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    if not rows:
        print(dim("  No keys found."))
        return

    w_name = max(len(r["name"]) for r in rows)
    w_prov = max(len(r["provider"]) for r in rows)

    header = (
        f"  {bold(f'{'NAME':<{w_name}}')}  "
        f"{bold(f'{'PROVIDER':<{w_prov}}')}  "
        f"{bold(f'{'AGE':>6}')}  "
        f"{bold('STATUS')}"
    )
    print(header)
    print(dim("  " + "─" * (w_name + w_prov + 22)))

    status_fmt = {
        "healthy":  lambda s: green("✓ " + s),
        "warning":  lambda s: yellow("! " + s),
        "critical": lambda s: red("✗ " + s),
    }
    for r in rows:
        status_str = status_fmt.get(r["status"], lambda s: "? " + s)(r["status"])
        prov_col = dim(f"{r['provider']:<{w_prov}}")
        print(
            f"  {r['name']:<{w_name}}  "
            f"{prov_col}  "
            f"{r['age']:>6}  "
            f"{status_str}"
        )
    print()
    total = len(rows)
    h = sum(1 for r in rows if r["status"] == "healthy")
    w = sum(1 for r in rows if r["status"] == "warning")
    c = sum(1 for r in rows if r["status"] == "critical")
    parts = [dim(f"{total} total")]
    if h: parts.append(green(f"{h} healthy"))
    if w: parts.append(yellow(f"{w} warning"))
    if c: parts.append(red(f"{c} critical"))
    print("  " + "  ·  ".join(parts))


def cmd_rotate(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    new_val = args.new_value
    if not new_val:
        try:
            new_val = getpass.getpass(bold(f"New value for {name}: "))
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
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
    ok(f"Rotated {bold(name)}")


def cmd_delete(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    if not args.yes:
        try:
            confirm = input(yellow(f"  Delete '{name}'? [y/N] "))
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
        if confirm.strip().lower() != "y":
            print(dim("  Cancelled."))
            return
    del vault[name]
    save_vault(vault, password)
    log_event(f"cli: deleted {name}")
    ok(f"Deleted {bold(name)}")


def cmd_status(args, vault, password):
    counts = {"healthy": 0, "warning": 0, "critical": 0}
    for info in vault.values():
        counts[health_status(info)] += 1
    total = sum(counts.values())
    print(f"\n  {bold('Vault')}  {dim(str(total) + ' key(s)')}\n")
    print(f"  {green('✓')}  healthy   {bold(str(counts['healthy']))}")
    print(f"  {yellow('!')}  warning   {bold(str(counts['warning']))}")
    print(f"  {red('✗')}  critical  {bold(str(counts['critical']))}\n")


def cmd_inject(args, vault, password):
    project = Path(getattr(args, "project", None) or Path.cwd()).resolve()
    if not project.is_dir():
        err(f"'{project}' is not a directory")
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
            warn(f"No keys assigned to {dim(str(project))}")
            print(f"  Assign keys via the GUI, or use {cyan('--all')} to inject all keys.")
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
    ok(f"Wrote {bold(str(len(keys_to_write)))} key(s) to {dim(str(env_path))}")


def cmd_import(args, vault, password):
    path = Path(args.file)
    if not path.exists():
        err(f"'{path}' not found")
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
            "value":          value,
            "created":        now,
            "rotated":        None,
            "provider":       provider,
            "env":            "all",
            "projects":       [],
            "notes":          f"imported from {path.name}",
            "rotation_count": 0,
        }
        added += 1

    if added:
        save_vault(vault, password)
        log_event(f"cli: imported {added} keys from {path.name}")
    ok(f"Imported {bold(str(added))} key(s)" + (f"  {dim(str(skipped) + ' skipped')}" if skipped else ""))


# ── new commands ─────────────────────────────────────────────────────────────

def cmd_init(args):
    _s.ensure_vault_dir()
    if _s.VAULT_FILE.exists():
        warn(f"Vault already exists at {dim(str(_s.VAULT_FILE))}")
        try:
            confirm = input(yellow("  Overwrite? This deletes all stored keys. [y/N] "))
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if confirm.strip().lower() != "y":
            print(dim("  Cancelled."))
            return
    try:
        pw1 = getpass.getpass(bold("New master password: "))
        pw2 = getpass.getpass(bold("Confirm password:    "))
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    if pw1 != pw2:
        err("Passwords do not match")
        sys.exit(1)
    if len(pw1) < 8:
        err("Password must be at least 8 characters")
        sys.exit(1)
    save_vault({}, pw1)
    log_event("cli: vault initialized")
    ok(f"Vault created at {dim(str(_s.VAULT_FILE))}")
    print(f"  Set {cyan('PUSHKEY_MASTER')} in your shell to skip the password prompt.")


def cmd_assign(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    project = str(Path(args.project).resolve())
    projects = vault[name].setdefault("projects", [])
    if args.remove:
        if project in projects:
            projects.remove(project)
            save_vault(vault, password)
            log_event(f"cli: unassigned {name} from {project}")
            ok(f"Unassigned {bold(name)} from {dim(project)}")
        else:
            warn(f"{bold(name)} was not assigned to {dim(project)}")
    else:
        if project in projects:
            warn(f"{bold(name)} already assigned to {dim(project)}")
        else:
            projects.append(project)
            save_vault(vault, password)
            log_event(f"cli: assigned {name} to {project}")
            ok(f"Assigned {bold(name)} → {dim(project)}")


def cmd_info(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    info = vault[name]
    status = health_status(info)
    status_col = {"healthy": green, "warning": yellow, "critical": red}.get(status, str)
    age = days_since(info.get("rotated") or info.get("created"))
    age_str = f"{int(age)} days" if age != float("inf") else "unknown"

    print()
    print(f"  {bold(name)}  {status_col('● ' + status)}")
    print(f"  {dim('─' * 40)}")
    print(f"  {'Provider':<14} {info.get('provider') or dim('—')}")
    print(f"  {'Environment':<14} {info.get('env', 'all')}")
    print(f"  {'Created':<14} {info.get('created', '—')[:19]}")
    print(f"  {'Last rotated':<14} {(info.get('rotated') or dim('never'))[:19]}")
    print(f"  {'Rotations':<14} {info.get('rotation_count', 0)}")
    print(f"  {'Age':<14} {age_str}")
    projects = info.get("projects") or []
    print(f"  {'Projects':<14} {len(projects)} assigned")
    for p in projects:
        print(f"  {'':14} {dim(p)}")
    notes = info.get("notes", "").strip()
    if notes:
        print(f"  {'Notes':<14} {notes}")
    print()


def cmd_history(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    history = vault[name].get("history") or []
    if not history:
        print(dim(f"  No rotation history for {name}."))
        return
    print(f"\n  {bold('Rotation history')} — {bold(name)}\n")
    for i, entry in enumerate(history):
        ts = entry.get("retired", "—")[:19]
        val = entry.get("value", "")
        masked = val[:4] + "••••••••" + val[-2:] if len(val) > 6 else "••••••••"
        display = val if args.reveal else masked
        print(f"  {dim(str(i + 1) + '.')}  {ts}  {dim(display)}")
    print()


def cmd_passwd(args):
    _s.ensure_vault_dir()
    try:
        old_pw = getpass.getpass(bold("Current password: "))
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    result = load_vault(old_pw)
    if result is None:
        err("Wrong password")
        sys.exit(1)
    vault = result[0] if isinstance(result, tuple) else result
    try:
        new_pw1 = getpass.getpass(bold("New password:     "))
        new_pw2 = getpass.getpass(bold("Confirm new:      "))
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    if new_pw1 != new_pw2:
        err("Passwords do not match")
        sys.exit(1)
    if len(new_pw1) < 8:
        err("Password must be at least 8 characters")
        sys.exit(1)
    save_vault(vault, new_pw1)
    log_event("cli: master password changed")
    ok("Master password updated")


def cmd_note(args, vault, password):
    name = args.name.upper()
    if name not in vault:
        err(f"'{name}' not found")
        sys.exit(1)
    if args.text:
        vault[name]["notes"] = args.text
    else:
        current = vault[name].get("notes", "")
        print(f"  Current note: {dim(current or '(none)')}")
        try:
            text = input(bold("  New note (blank to clear): ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        vault[name]["notes"] = text
    save_vault(vault, password)
    log_event(f"cli: updated note for {name}")
    ok(f"Note saved for {bold(name)}")


def cmd_log(args, vault, password):
    from pushkey_crypto import _log_decrypt_all
    entries = _log_decrypt_all()
    if not entries:
        print(dim("  No log entries found."))
        return
    key_filter = args.key.upper() if args.key else None
    if key_filter:
        entries = [e for e in entries if key_filter.lower() in e.lower()]
    entries = entries[-args.limit:]
    print()
    for entry in entries:
        if "] cli:" in entry or "] gui:" in entry:
            print(f"  {dim(entry)}")
        else:
            print(f"  {entry}")
    print()


def cmd_completion(args):
    shell = args.shell
    cmds = "init add get list rotate delete status inject import assign info history passwd note log completion"
    if shell == "bash":
        print(f"""# Pushkey bash completion — add to ~/.bashrc
_pushkey_complete() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local cmds="{cmds}"
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
}}
complete -F _pushkey_complete pushkey""")
    elif shell == "zsh":
        print(f"""# Pushkey zsh completion — add to ~/.zshrc
_pushkey() {{
    local cmds=({cmds})
    _describe 'commands' cmds
}}
compdef _pushkey pushkey""")
    elif shell == "powershell":
        print(f"""# Pushkey PowerShell completion — add to $PROFILE
Register-ArgumentCompleter -Native -CommandName pushkey -ScriptBlock {{
    param($word, $ast, $cursor)
    '{cmds}'.Split() | Where-Object {{ $_ -like "$word*" }} |
        ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }}
}}""")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) == 1:
        _print_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(prog="pushkey", add_help=False)
    parser.add_argument("--password", "-p")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", "-V", action="store_true")
    sub = parser.add_subparsers(dest="command")

    # ── existing commands ──
    p_add = sub.add_parser("add")
    p_add.add_argument("name")
    p_add.add_argument("value", nargs="?", default=None)
    p_add.add_argument("--notes")
    p_add.add_argument("--generate", "-g", action="store_true", help="Auto-generate a secure random value")

    p_get = sub.add_parser("get")
    p_get.add_argument("name")
    p_get.add_argument("--clip", "-c", action="store_true")

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", choices=["healthy", "warning", "critical"])
    p_list.add_argument("--json", action="store_true")

    p_rotate = sub.add_parser("rotate")
    p_rotate.add_argument("name")
    p_rotate.add_argument("new_value", nargs="?", default=None)
    p_rotate.add_argument("--generate", "-g", action="store_true", help="Auto-generate a secure random value")

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("name")
    p_delete.add_argument("--yes", "-y", action="store_true")

    sub.add_parser("status")

    p_inject = sub.add_parser("inject")
    p_inject.add_argument("--project")
    p_inject.add_argument("--all", action="store_true", dest="all")
    p_inject.add_argument("--env", default=None, help="Only inject keys with this env tag")

    p_import = sub.add_parser("import")
    p_import.add_argument("file")

    # ── new commands ──
    sub.add_parser("init")

    p_assign = sub.add_parser("assign")
    p_assign.add_argument("name")
    p_assign.add_argument("project")
    p_assign.add_argument("--remove", "-r", action="store_true", help="Unassign instead of assign")

    p_info = sub.add_parser("info")
    p_info.add_argument("name")

    p_history = sub.add_parser("history")
    p_history.add_argument("name")
    p_history.add_argument("--reveal", action="store_true", help="Show actual values")

    sub.add_parser("passwd")

    p_note = sub.add_parser("note")
    p_note.add_argument("name")
    p_note.add_argument("text", nargs="?", default=None)

    p_log = sub.add_parser("log")
    p_log.add_argument("--limit", type=int, default=20)
    p_log.add_argument("--key", default=None, help="Filter by key name")

    p_completion = sub.add_parser("completion")
    p_completion.add_argument("shell", choices=["bash", "zsh", "powershell"])

    args = parser.parse_args()

    if args.version:
        try:
            from pushkey_shared import VERSION
        except ImportError:
            VERSION = "2.1.0"
        print(f"pushkey {VERSION}")
        sys.exit(0)

    if args.help or not args.command:
        _print_help()
        sys.exit(0)

    # commands that don't need an open vault
    if args.command == "init":
        cmd_init(args)
        return
    if args.command == "passwd":
        cmd_passwd(args)
        return
    if args.command == "completion":
        cmd_completion(args)
        return

    vault, password = _open_vault(args)

    # apply --generate to add/rotate before dispatching
    if args.command in ("add", "rotate") and getattr(args, "generate", False):
        generated = secrets.token_urlsafe(32)
        if args.command == "add":
            args.value = generated
        else:
            args.new_value = generated
        ok(f"Generated value: {bold(generated)}")

    # apply --env filter to inject
    if args.command == "inject" and args.env:
        env_filter = args.env
        original_inject = cmd_inject
        def cmd_inject_filtered(a, v, pw):
            filtered = {k: val for k, val in v.items() if val.get("env", "all") in (env_filter, "all")}
            original_inject(a, filtered, pw)
        globals()["_inject_fn"] = cmd_inject_filtered
    else:
        globals()["_inject_fn"] = cmd_inject

    {
        "add":     cmd_add,
        "get":     cmd_get,
        "list":    cmd_list,
        "rotate":  cmd_rotate,
        "delete":  cmd_delete,
        "status":  cmd_status,
        "inject":  globals()["_inject_fn"],
        "import":  cmd_import,
        "assign":  cmd_assign,
        "info":    cmd_info,
        "history": cmd_history,
        "note":    cmd_note,
        "log":     cmd_log,
    }[args.command](args, vault, password)


if __name__ == "__main__":
    main()

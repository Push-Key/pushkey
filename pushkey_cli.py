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
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

import pushkey_shared as _s
from pushkey_crypto import generate_recovery_code, log_event
from pushkey_env import mutate_env_file
from pushkey_providers import PROVIDERS, detect_provider, days_since, health_status
from pushkey_vault import load_config, load_vault, load_vault_with_key, save_config, save_vault, save_vault_with_key


# ── ANSI colors ───────────────────────────────────────────────────────────────

C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_ORANGE = "\033[33m"
C_RED = "\033[91m"
C_WHITE = "\033[97m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 10
EXIT_IO = 20
EXIT_CORRUPTION = 30
EXIT_NETWORK = 40
EXIT_INTERRUPTED = 130
CLI_COMMANDS = [
    "add", "get", "list", "rotate", "set-backup", "delete", "status",
    "inject", "import", "init", "app", "completion",
]

CLI_ONBOARDING_MARKER = ".cli_onboarding_seen"
PUSHKEY_ASCII_ART = [
    "██████  ██    ██ ███████ ██   ██ ██   ██ ███████ ██    ██",
    "██   ██ ██    ██ ██      ██   ██ ██  ██  ██       ██  ██ ",
    "██████  ██    ██ ███████ ███████ █████   █████     ████  ",
    "██      ██    ██      ██ ██   ██ ██  ██  ██         ██   ",
    "██       ██████  ███████ ██   ██ ██   ██ ███████    ██   ",
]


# ── helpers ──────────────────────────────────────────────────────────────────


def _cli_onboarding_marker_path() -> Path:
    return _s.VAULT_DIR / CLI_ONBOARDING_MARKER


def _has_seen_cli_onboarding() -> bool:
    return _cli_onboarding_marker_path().exists()


def _mark_cli_onboarding_seen() -> Path:
    marker = _cli_onboarding_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("seen\n", encoding="utf-8")
    return marker


def _print_pushkey_ascii_art() -> None:
    for line in PUSHKEY_ASCII_ART:
        print(f"{C_CYAN}{line}{C_RESET}")



def _render_cli_header(first_run: bool, has_vault: bool) -> None:
    _print_pushkey_ascii_art()
    print()
    if first_run:
        print("Pushkey is an encrypted vault for API keys, secrets, and project environment injection.")
        print("Unlock your vault to use the CLI, launch the secure web app, or open the desktop interface.")
        print()
    else:
        print(f"{C_CYAN}=== PUSHKEY CLI ==={C_RESET}")
        print()
    primary = "UNLOCK" if has_vault else "CREATE A VAULT"
    print(f"{C_WHITE}{primary}{C_RESET}  ·  menu numbers or command names both work")
    print()


def _print_pre_unlock_menu(has_vault: bool) -> None:
    rows = [
        ("1", "unlock" if has_vault else "init", "Unlock vault" if has_vault else "Create vault"),
        ("2", "init" if has_vault else "app", "Create vault" if has_vault else "Open web app"),
        ("3", "app" if has_vault else "desktop", "Open web app" if has_vault else "Open desktop app"),
        ("4", "desktop" if has_vault else "help", "Open desktop app" if has_vault else "Help"),
        ("5", "help" if has_vault else "exit", "Help" if has_vault else "Exit"),
    ]
    if not has_vault:
        rows.append(("6", "exit", "Exit"))
    for num, cmd, desc in rows:
        print(f"  {C_CYAN}[{num}] {cmd.ljust(8)}{C_RESET} {desc}")
    print()


def _print_pre_unlock_help(has_vault: bool = True) -> None:
    print(f"{C_WHITE}Basic actions{C_RESET}")
    basics = [
        ("unlock", "enter your master password and open the CLI"),
        ("init", "create a new vault"),
        ("app", "launch the secure local web app"),
        ("desktop", "open the desktop application"),
        ("exit", "leave Pushkey"),
    ]
    if not has_vault:
        basics[0] = ("init", "create your first vault to get started")
    for cmd, desc in basics:
        print(f"  {C_CYAN}{cmd.ljust(8)}{C_RESET} {desc}")
    print()
    print(f"{C_WHITE}After unlock{C_RESET}")
    advanced = [
        ("list", "show vault keys"),
        ("get NAME", "print a key value"),
        ("add", "add a key interactively or via subcommand"),
        ("rotate NAME", "rotate a key value"),
        ("inject [PATH]", "write assigned keys to a project .env"),
        ("pushkey app", "launch the web app directly from a subcommand"),
    ]
    for cmd, desc in advanced:
        print(f"  {C_CYAN}{cmd.ljust(14)}{C_RESET} {desc}")
    print()


def _desktop_app_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / "OneDrive" / "Desktop" / "Pushkey" / "Pushkey.exe",
        home / "Desktop" / "Pushkey" / "Pushkey.exe",
        home / "OneDrive" / "Desktop" / "Pushkey.exe",
        home / "Desktop" / "Pushkey.exe",
    ]


def _launch_desktop_app() -> None:
    gui = shutil.which("pushkey-gui")
    if gui:
        subprocess.Popen([gui])
        return
    for candidate in _desktop_app_candidates():
        if candidate.exists():
            subprocess.Popen([str(candidate)])
            return
    print("Desktop app not found. Try pushkey-gui or rebuild the desktop app.", file=sys.stderr)
    sys.exit(EXIT_USAGE)


def _run_repl_session(vault, password, vault_key=None):
    history_file = _s.VAULT_DIR / ".cli_history"
    rl = _setup_readline(vault, history_file)

    print()
    _render_dashboard(vault)
    _render_stale_warnings(vault, password)
    print()

    app_proc = None
    prompt = f"{C_CYAN}pushkey{C_RESET}> "

    try:
        while True:
            try:
                line = input(prompt)
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue

            line = line.strip()
            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()
            rest = parts[1:]
            app_proc = _handle_repl_command(cmd, rest, vault, password, vault_key, app_proc)
            if app_proc is False:
                break
    finally:
        _save_history(rl, history_file)
        if app_proc and app_proc is not False and app_proc.poll() is None:
            try:
                app_proc.terminate()
            except Exception:
                pass


def _unlock_into_repl(args) -> None:
    vault, password, vault_key, _scopes = _open_vault(args)
    _mark_cli_onboarding_seen()
    _run_repl_session(vault, password, vault_key)


def _dispatch_pre_unlock_command(command: str, args, has_vault: bool) -> bool:
    normalized = (command or "").strip().lower()
    aliases = {
        "1": "unlock" if has_vault else "init",
        "2": "init" if has_vault else "app",
        "3": "app" if has_vault else "desktop",
        "4": "desktop" if has_vault else "help",
        "5": "help" if has_vault else "exit",
        "6": "exit",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"exit", "quit"}:
        return False
    if normalized in {"unlock", "login"}:
        _unlock_into_repl(args)
        return True
    if normalized in {"init", "create", "new"}:
        init_password = os.environ.get("PUSHKEY_MASTER") or getattr(args, "password", None)
        _cmd_init(None, password=init_password)
        return True
    if normalized in {"app", "web"}:
        _cmd_app(blocking=False)
        return True
    if normalized in {"desktop", "gui"}:
        _launch_desktop_app()
        return True
    if normalized in {"help", "?"}:
        _print_pre_unlock_help(has_vault)
        return True
    print(f"{C_RED}Unknown option. Type help.{C_RESET}")
    return True


def _pre_unlock_shell(args) -> None:
    _s.ensure_vault_dir()
    first_run = not _has_seen_cli_onboarding()
    has_vault = _s.VAULT_FILE.exists()
    if first_run:
        _mark_cli_onboarding_seen()
    while True:
        _render_cli_header(first_run, has_vault)
        _print_pre_unlock_menu(has_vault)
        try:
            command = input(f"{C_CYAN}pushkey setup{C_RESET}> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue
        if not _dispatch_pre_unlock_command(command, args, has_vault):
            break
        first_run = False
        has_vault = _s.VAULT_FILE.exists()
        print()

def _get_password(args):
    pw = os.environ.get("PUSHKEY_MASTER") or getattr(args, "password", None)
    if pw:
        return pw
    try:
        return getpass.getpass("Master password: ")
    except (EOFError, KeyboardInterrupt):
        print("Aborted.", file=sys.stderr)
        sys.exit(1)


def _get_agent_token(args):
    return getattr(args, "token", None) or os.environ.get("PUSHKEY_AGENT_TOKEN")


def _open_vault_with_token(token_value):
    """Unlock via a scoped agent token instead of the master password.

    Mirrors pushkey_mcp.py's _unlock_with_token: the vault key is unwrapped
    from the token (never the master password), so writes go through
    save_vault_with_key rather than save_vault -- see _save_vault_for_session.
    Returns (vault, password, vault_key, scopes) with password=None, the
    session-less signal that this credential cannot re-derive the password slot.
    """
    import pushkey_agent_tokens as _at
    vault_key, scopes, err = _at.authenticate_token(token_value)
    if vault_key is None:
        print(f"Error: {err or 'invalid or expired agent token'}", file=sys.stderr)
        sys.exit(EXIT_AUTH)
    vault, vk = load_vault_with_key(vault_key)
    if vault is None:
        print(
            "Error: agent token could not decrypt vault (stale after a master password change?)",
            file=sys.stderr,
        )
        sys.exit(EXIT_AUTH)
    return vault, None, vk, scopes


def _open_vault(args):
    token = _get_agent_token(args)
    if token:
        return _open_vault_with_token(token)
    password = _get_password(args)
    if password.startswith("pk_agent_"):
        return _open_vault_with_token(password)
    _s.ensure_vault_dir()
    vault, vault_key = load_vault(password)
    if vault is None:
        print("Error: wrong master password", file=sys.stderr)
        sys.exit(EXIT_AUTH)
    return vault, password, vault_key, None


def _save_vault_for_session(vault, password, vault_key):
    """Persist vault changes for either auth path.

    Agent-token sessions never hold the master password (password is None),
    so they write through the raw-key path -- save_vault would otherwise
    require re-deriving the password slot with a password we were never given.
    """
    if password is not None:
        save_vault(vault, password, vault_key=vault_key)
    else:
        save_vault_with_key(vault, vault_key)


_COMMAND_SCOPES = {
    "add": "write",
    "get": "read",
    "list": "read",
    "rotate": "write",
    "set-backup": "write",
    "delete": "write",
    "status": "read",
    "inject": "inject",
    "import": "write",
}


def _require_command_scope(command, scopes):
    """Exit with EXIT_AUTH if an agent token lacks the scope a command needs.

    scopes is None for master-password sessions (full access, unchanged
    behavior); a list for agent-token sessions, checked against
    _COMMAND_SCOPES the same way pushkey_mcp.py's _require_scope gates tools.
    """
    if scopes is None:
        return
    required = _COMMAND_SCOPES.get(command)
    if required and required not in scopes:
        have = ", ".join(scopes) or "none"
        print(
            f"Error: agent token missing required scope '{required}' for '{command}' (token has: {have})",
            file=sys.stderr,
        )
        sys.exit(EXIT_AUTH)


_ENV_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_add(args, vault, password, vault_key=None):
    name = args.name.upper()
    if name in vault:
        print(f"Error: '{name}' already exists. Use 'rotate' to update.", file=sys.stderr)
        sys.exit(EXIT_USAGE)
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
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: added {name}")
    suffix = f" [{provider}]" if provider else ""
    print(f"Added {name}{suffix}")


def cmd_get(args, vault, password, vault_key=None):
    name = args.name.upper()
    if name not in vault:
        print(f"Error: '{name}' not found", file=sys.stderr)
        sys.exit(EXIT_USAGE)
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


def cmd_list(args, vault, password, vault_key=None):
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


def cmd_rotate(args, vault, password, vault_key=None):
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
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: rotated {name}")
    print(f"Rotated {name}")


def cmd_set_backup(args, vault, password, vault_key=None):
    name = args.name.upper()
    if name not in vault:
        print(f"Error: '{name}' not found", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)
    try:
        backup_value = getpass.getpass(f"Backup value for {name}: ")
    except (EOFError, KeyboardInterrupt):
        print("Aborted.", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)
    if not backup_value:
        print("Error: backup value cannot be empty", file=sys.stderr)
        sys.exit(1)

    info = vault[name]
    info["next_value"] = backup_value
    info["next_added"] = datetime.now().isoformat()
    info["dual_rotation"] = True
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: set backup for {name}")
    print(f"Backup staged for {name}")


def cmd_delete(args, vault, password, vault_key=None):
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
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: deleted {name}")
    print(f"Deleted {name}")


def cmd_status(args, vault, password, vault_key=None):
    counts = {"healthy": 0, "warning": 0, "critical": 0}
    for info in vault.values():
        counts[health_status(info)] += 1
    total = sum(counts.values())
    print(f"Vault: {total} key(s)")
    print(f"  ✓ healthy:   {counts['healthy']}")
    print(f"  ! warning:   {counts['warning']}")
    print(f"  ✗ critical:  {counts['critical']}")


def cmd_inject(args, vault, password, vault_key=None):
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

    result = mutate_env_file(
        project,
        keys_to_write,
        update_existing=True,
        backup_existing=True,
    )
    log_event(f"cli: injected {len(keys_to_write)} keys into {project}")
    print(f"Wrote {result.changed_count} key(s) to {result.env_file}")


def cmd_import(args, vault, password, vault_key=None):
    path = Path(args.file)
    if not path.exists():
        print(f"Error: '{path}' not found", file=sys.stderr)
        sys.exit(EXIT_IO)
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
        _save_vault_for_session(vault, password, vault_key)
        log_event(f"cli: imported {added} keys from {path.name}")
    print(f"Imported {added} key(s), skipped {skipped} existing")


def cmd_completion(args):
    commands = " ".join(CLI_COMMANDS)
    if args.shell == "bash":
        print(
            "_pushkey_complete() {\n"
            "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
            f"  COMPREPLY=( $(compgen -W \"{commands}\" -- \"$cur\") )\n"
            "}\n"
            "complete -F _pushkey_complete pushkey"
        )
        return
    if args.shell == "powershell":
        quoted = ", ".join(f"'{command}'" for command in CLI_COMMANDS)
        print(
            "Register-ArgumentCompleter -Native -CommandName pushkey -ScriptBlock {\n"
            "  param($wordToComplete)\n"
            f"  $commands = @({quoted})\n"
            "  $commands | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
            "    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
            "  }\n"
            "}"
        )
        return
    print(f"Error: unsupported shell '{args.shell}'", file=sys.stderr)
    sys.exit(EXIT_USAGE)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--local-api-server":
        from pushkey_local_api import run_server
        return run_server()
    parser = argparse.ArgumentParser(
        prog="pushkey",
        description="Pushkey - encrypted API key manager",
    )
    parser.add_argument("--password", "-p", help="Master password (or set PUSHKEY_MASTER)")
    parser.add_argument(
        "--token",
        help="Scoped agent token, pk_agent_... (or set PUSHKEY_AGENT_TOKEN). "
             "Grants only the read/write/inject scopes the token was created with.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

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

    p_set_backup = sub.add_parser("set-backup", help="Stage a backup key value")
    p_set_backup.add_argument("name")

    p_delete = sub.add_parser("delete", help="Delete a key")
    p_delete.add_argument("name")
    p_delete.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    sub.add_parser("status", help="Health summary")

    p_inject = sub.add_parser("inject", help="Write keys to project .env")
    p_inject.add_argument("--project", help="Project path (default: current directory)")
    p_inject.add_argument("--all", action="store_true", dest="all", help="Inject all keys regardless of project assignment")

    p_import = sub.add_parser("import", help="Bulk import keys from a .env file")
    p_import.add_argument("file", help="Path to .env file")

    p_init = sub.add_parser("init", help="Initialize a new vault")
    p_init.add_argument(
        "--recovery-file",
        help="Required for non-interactive init; recovery code is written atomically",
    )
    sub.add_parser("app", help="Launch web UI in browser")
    p_completion = sub.add_parser("completion", help="Print shell completion script")
    p_completion.add_argument("shell", choices=["bash", "powershell"])

    args = parser.parse_args()

    if args.command is None:
        return _pre_unlock_shell(args)

    if args.command == "init":
        init_password = os.environ.get("PUSHKEY_MASTER") or args.password
        return _cmd_init(args.recovery_file, password=init_password)

    if args.command == "app":
        return _cmd_app(blocking=True)

    if args.command == "completion":
        return cmd_completion(args)

    vault, password, vault_key, scopes = _open_vault(args)
    _require_command_scope(args.command, scopes)

    {
        "add":    cmd_add,
        "get":    cmd_get,
        "list":   cmd_list,
        "rotate": cmd_rotate,
        "set-backup": cmd_set_backup,
        "delete": cmd_delete,
        "status": cmd_status,
        "inject": cmd_inject,
        "import": cmd_import,
    }[args.command](args, vault, password, vault_key)


# ── init ──────────────────────────────────────────────────────────────────────

def _stdin_is_interactive():
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def _write_recovery_file(path, recovery_code):
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(str(destination), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as handle:
            handle.write(recovery_code + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _cmd_init(recovery_file=None, password=None):
    _s.ensure_vault_dir()
    if _s.VAULT_FILE.exists():
        print(f"{C_RED}Vault already exists at {_s.VAULT_FILE}{C_RESET}", file=sys.stderr)
        sys.exit(1)
    if password is not None:
        pw1 = password
    else:
        try:
            pw1 = getpass.getpass("Choose master password (>=8 chars): ")
            pw2 = getpass.getpass("Confirm password: ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.", file=sys.stderr)
            sys.exit(1)
        if pw1 != pw2:
            print(f"{C_RED}Passwords do not match.{C_RESET}", file=sys.stderr)
            sys.exit(1)
    if len(pw1) < 8:
        print(f"{C_RED}Password too short.{C_RESET}", file=sys.stderr)
        sys.exit(1)
    recovery_code = generate_recovery_code()
    recovery_destination = None
    if _stdin_is_interactive() and not recovery_file:
        print(
            "\nRecovery code (store this offline; it is the only way to reset "
            "a forgotten password):"
        )
        print(recovery_code)
        try:
            confirmation = input("Type I SAVED IT to create the vault: ").strip()
        except (EOFError, KeyboardInterrupt):
            confirmation = ""
        if confirmation != "I SAVED IT":
            print("Aborted: recovery code was not confirmed.", file=sys.stderr)
            sys.exit(1)
    else:
        if not recovery_file:
            print(
                "Non-interactive initialization requires --recovery-file; "
                "the recovery code will not be printed.",
                file=sys.stderr,
            )
            sys.exit(2)
        recovery_destination = _write_recovery_file(recovery_file, recovery_code)
        print(f"Recovery code written to {recovery_destination}")
    try:
        save_vault({}, pw1, recovery_code=recovery_code)
    except Exception:
        if recovery_destination is not None:
            recovery_destination.unlink(missing_ok=True)
            try:
                parent_fd = os.open(
                    str(recovery_destination.parent),
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except OSError:
                pass
        raise
    log_event("cli: vault initialized")
    print(f"{C_GREEN}Vault created at {_s.VAULT_FILE}{C_RESET}")


# ── app launcher ──────────────────────────────────────────────────────────────

def _port_in_use(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _cmd_app(blocking=False):
    frozen = bool(getattr(sys, "frozen", False))
    api_path = Path(__file__).parent / "pushkey_local_api.py"
    if not frozen and not api_path.exists():
        print(f"{C_RED}pushkey_local_api.py not found alongside CLI{C_RESET}", file=sys.stderr)
        if blocking:
            sys.exit(1)
        return None

    port = None
    for p in range(7654, 7660):
        if not _port_in_use(p):
            port = p
            break
    if port is None:
        print(f"{C_RED}No free port in 7654-7659{C_RESET}", file=sys.stderr)
        if blocking:
            sys.exit(1)
        return None

    token = secrets.token_urlsafe(24)
    env = {
        **os.environ,
        "PUSHKEY_LOCAL_PORT": str(port),
        "PUSHKEY_LAUNCH_TOKEN": token,
    }
    command = (
        [sys.executable, "--local-api-server"]
        if frozen
        else [sys.executable, str(api_path)]
    )
    proc = subprocess.Popen(command, env=env)

    ready = False
    for _ in range(20):
        try:
            _s.urlopen_checked(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
            ready = True
            break
        except Exception:
            time.sleep(0.5)

    if not ready:
        print(f"{C_RED}API failed to start{C_RESET}", file=sys.stderr)
        try:
            proc.kill()
        except Exception:
            pass
        if blocking:
            sys.exit(1)
        return None

    # URL fragments are never sent in HTTP requests or access logs. The web app
    # exchanges this one-time bootstrap credential for an in-memory session.
    url = f"http://127.0.0.1:{port}/#t={token}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"  {C_GREEN}✓ Opened secure web app in your browser.{C_RESET}")
    print(f"  {C_DIM}If nothing opened, rerun 'pushkey app' instead of opening the local URL manually.{C_RESET}")

    if blocking:
        try:
            proc.wait()
        except KeyboardInterrupt:
            try:
                proc.terminate()
            except Exception:
                pass
        return None
    return proc


# ── REPL ──────────────────────────────────────────────────────────────────────

_REPL_COMMANDS = ["list", "get", "copy", "add", "rotate", "delete",
                  "inject", "project", "projects", "security", "app", "desktop",
                  "status", "help", "about", "agents", "exit", "quit"]


def _setup_readline(vault, history_file):
    try:
        import readline as _rl
    except Exception:
        try:
            import pyreadline3 as _rl  # type: ignore
        except Exception:
            return None
    try:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        if history_file.exists():
            try:
                _rl.read_history_file(str(history_file))
            except Exception:
                pass
        _rl.set_history_length(500)
    except Exception:
        pass

    def _completer(text, state):
        try:
            line = _rl.get_line_buffer()
            tokens = line.split()
            if len(tokens) <= 1 and not line.endswith(" "):
                opts = [c for c in _REPL_COMMANDS if c.startswith(text)]
            else:
                cmd = tokens[0] if tokens else ""
                if cmd in ("get", "copy", "rotate", "delete"):
                    opts = [n for n in vault.keys() if n.startswith(text.upper())]
                else:
                    opts = []
            return opts[state] if state < len(opts) else None
        except Exception:
            return None

    try:
        _rl.set_completer(_completer)
        _rl.parse_and_bind("tab: complete")
    except Exception:
        pass
    return _rl


def _save_history(rl, history_file):
    if rl is None:
        return
    try:
        rl.write_history_file(str(history_file))
    except Exception:
        pass


def _project_summary(vault):
    config = load_config()
    projects = []
    registered = config.get("projects", {}) if isinstance(config, dict) else {}
    for path, meta in sorted(registered.items()):
        assigned = [name for name, entry in sorted(vault.items()) if path in (entry.get("projects") or [])]
        projects.append({
            "path": path,
            "name": meta.get("name", Path(path).name) if isinstance(meta, dict) else Path(path).name,
            "keys": assigned,
        })
    for name, entry in sorted(vault.items()):
        for path in entry.get("projects") or []:
            if not any(project["path"] == path for project in projects):
                projects.append({"path": path, "name": Path(path).name, "keys": [name]})
            else:
                for project in projects:
                    if project["path"] == path and name not in project["keys"]:
                        project["keys"].append(name)
    return projects


def _agent_token_count() -> int:
    try:
        import pushkey_agent_tokens as _at
        return len(_at.list_tokens())
    except Exception:
        return 0


def _render_brand_header() -> None:
    _print_pushkey_ascii_art()
    print(f"{C_DIM}Local encrypted API key vault for developers, apps, and autonomous agents.{C_RESET}")
    print()


def _color_for_age(age):
    if age == float("inf"):
        return C_DIM
    if age < 60:
        return C_GREEN
    if age <= 90:
        return C_ORANGE
    return C_RED


def _minimap(age):
    if age == float("inf"):
        return "░" * 10
    blocks = int(min(10, max(0, age / 90.0 * 10)))
    return "█" * blocks + "░" * (10 - blocks)


def _render_dashboard(vault):
    counts = {"healthy": 0, "warning": 0, "critical": 0}
    backup_staged = 0
    for info in vault.values():
        counts[health_status(info)] += 1
        if info.get("next_value"):
            backup_staged += 1
    total = sum(counts.values())
    need_rot = counts["warning"] + counts["critical"]
    projects = _project_summary(vault)
    token_count = _agent_token_count()

    _render_brand_header()
    line1 = f"  {total} keys total   {need_rot} need rotation   {backup_staged} backup staged  "
    line2 = f"  {len(projects)} Projects   {token_count} Agent tokens   {counts['critical']} critical  "
    width = max(len(line1), len(line2)) + 2
    top = "╔" + "═" * (width - 2) + "╗"
    mid = "╚" + "═" * (width - 2) + "╝"
    print(f"{C_CYAN}{top}{C_RESET}")
    print(f"{C_CYAN}║{C_RESET}{C_WHITE}{line1.ljust(width - 2)}{C_RESET}{C_CYAN}║{C_RESET}")
    print(f"{C_CYAN}║{C_RESET}{line2.ljust(width - 2)}{C_CYAN}║{C_RESET}")
    print(f"{C_CYAN}{mid}{C_RESET}")
    print(f"  {C_GREEN}✓ healthy ({counts['healthy']}){C_RESET}   "
          f"{C_ORANGE}⚠ warning ({counts['warning']}){C_RESET}   "
          f"{C_RED}✗ critical ({counts['critical']}){C_RESET}")
    print()
    print(f"{C_WHITE}Quick actions{C_RESET}")
    actions = [
        "[1] Add key", "[2] Get key", "[3] Inject project", "[4] Rotate key",
        "[5] Projects", "[6] Agents", "[7] Security", "[8] Launch app",
    ]
    print("  " + "   ".join(f"{C_CYAN}{item}{C_RESET}" for item in actions[:4]))
    print("  " + "   ".join(f"{C_CYAN}{item}{C_RESET}" for item in actions[4:]))
    print()
    print(f"{C_WHITE}Projects{C_RESET}")
    if projects:
        for project in projects[:3]:
            keys = ", ".join(project["keys"][:3]) if project["keys"] else "no assigned keys"
            display_name = project.get("name") or Path(project["path"]).name or project["path"]
            print(f"  {C_CYAN}{display_name}{C_RESET}  {C_DIM}{project['path']}{C_RESET}  {len(project['keys'])} key(s): {keys}")
    else:
        print(f"  {C_DIM}No linked projects yet. Use: project add <path>{C_RESET}")
    print()
    print(f"{C_WHITE}Agent tokens{C_RESET}")
    print(f"  {token_count} token(s). Use {C_CYAN}agents list{C_RESET}, {C_CYAN}agents create <name> read,write,inject{C_RESET}, {C_CYAN}agents revoke <token_id>{C_RESET}")


def _render_stale_warnings(vault, password):
    stale = []
    for name, info in vault.items():
        age = days_since(info.get("rotated") or info.get("created"))
        if age != float("inf") and age > 90:
            stale.append((name, int(age)))
    if not stale:
        return
    stale.sort(key=lambda x: -x[1])
    print()
    print(f"{C_ORANGE}⚠  {len(stale)} key(s) need rotation:{C_RESET}")
    w = max(len(n) for n, _ in stale)
    for name, age in stale:
        print(f"   {C_CYAN}{name.ljust(w)}{C_RESET}  {C_RED}{age}d{C_RESET}")
    try:
        choice = input("   Press Enter to skip, or type a name to rotate: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not choice:
        return
    target = choice.upper()
    if target in vault:
        _repl_rotate(vault, password, target)
    else:
        print(f"   {C_DIM}Unknown key. Continuing.{C_RESET}")


def _repl_list(vault, status_filter=None):
    rows = []
    for name, info in sorted(vault.items()):
        st = health_status(info)
        if status_filter and st != status_filter:
            continue
        age = days_since(info.get("rotated") or info.get("created"))
        rows.append((name, info, st, age))
    if not rows:
        print("  No keys.")
        return
    w_name = max(len(r[0]) for r in rows)
    w_prov = max(len(r[1].get("provider") or "—") for r in rows)
    w_env = max(len(r[1].get("env") or "all") for r in rows)
    icon = {"healthy": f"{C_GREEN}✓{C_RESET}",
            "warning": f"{C_ORANGE}⚠{C_RESET}",
            "critical": f"{C_RED}✗{C_RESET}"}
    for name, info, st, age in rows:
        prov = info.get("provider") or "—"
        envv = info.get("env") or "all"
        age_str = f"{int(age)}d" if age != float("inf") else "?"
        bar = _minimap(age)
        col = _color_for_age(age)
        print(f"  {C_CYAN}{name.ljust(w_name)}{C_RESET}  "
              f"{C_DIM}{prov.ljust(w_prov)}{C_RESET}  "
              f"{envv.ljust(w_env)}  "
              f"{col}{bar}{C_RESET}  {age_str:>4}  {icon.get(st, '?')}")


def _copy_to_clipboard(text):
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            # No shell=True: the command is a fixed list, so the shell added
            # nothing but an injection surface if this ever became dynamic.
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-16le"))
            return True
        except Exception:
            return False
    if sys.platform == "darwin":
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return True
        except Exception:
            return False
    for tool, args in (("xclip", ["xclip", "-selection", "clipboard"]),
                       ("xsel", ["xsel", "--clipboard", "--input"])):
        if shutil.which(tool):
            try:
                p = subprocess.Popen(args, stdin=subprocess.PIPE)
                p.communicate(input=text.encode("utf-8"))
                return True
            except Exception:
                continue
    return False


def _repl_copy(vault, name):
    if name not in vault:
        print(f"{C_RED}Unknown key. Try: list{C_RESET}")
        return
    if not _copy_to_clipboard(vault[name]["value"]):
        print(f"{C_RED}Clipboard unavailable. Install pyperclip.{C_RESET}")
        return
    print(f"  {C_GREEN}✓{C_RESET} {C_CYAN}{name}{C_RESET} copied. {C_DIM}Clears in 30s.{C_RESET}")
    threading.Timer(30, lambda: _copy_to_clipboard("")).start()


def _repl_add(vault, password, vault_key=None):
    try:
        name = input("  Key name: ").strip().upper()
        if not name:
            print("  Aborted.")
            return
        if name in vault:
            print(f"{C_RED}'{name}' already exists. Use rotate.{C_RESET}")
            return
        value = getpass.getpass("  Value (hidden): ")
        if not value.strip():
            print("  Aborted.")
            return
        notes = input("  Notes (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        return
    provider = detect_provider(name, value)
    now = datetime.now().isoformat()
    vault[name] = {
        "value": value, "created": now, "rotated": None,
        "provider": provider, "env": "all", "projects": [],
        "notes": notes, "rotation_count": 0,
    }
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: added {name}")
    print(f"  {C_GREEN}✓ Added {name}{C_RESET}")


def _repl_rotate(vault, password, name, vault_key=None):
    if name not in vault:
        print(f"{C_RED}Unknown key. Try: list{C_RESET}")
        return
    try:
        new_val = getpass.getpass(f"  New value for {name} (hidden): ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        return
    if not new_val.strip():
        print("  Aborted.")
        return
    info = vault[name]
    old_age = days_since(info.get("rotated") or info.get("created"))
    now = datetime.now().isoformat()
    info.setdefault("history", []).insert(0, {"value": info["value"], "retired": now})
    info["history"] = info["history"][:10]
    info["value"] = new_val.strip()
    info["rotated"] = now
    info["rotation_count"] = info.get("rotation_count", 0) + 1
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: rotated {name}")
    age_str = f"{int(old_age)}d" if old_age != float("inf") else "?"
    print(f"  {C_GREEN}✓ Rotated. Was {age_str} old.{C_RESET}")


def _repl_delete(vault, password, name, vault_key=None):
    if name not in vault:
        print(f"{C_RED}Unknown key. Try: list{C_RESET}")
        return
    try:
        confirm = input(f"  Delete {C_CYAN}{name}{C_RESET}? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if confirm != "y":
        print("  Cancelled.")
        return
    del vault[name]
    _save_vault_for_session(vault, password, vault_key)
    log_event(f"cli: deleted {name}")
    print(f"  {C_GREEN}✓ Deleted {name}{C_RESET}")


def _repl_get(vault, name):
    if name not in vault:
        print(f"{C_RED}Unknown key. Try: list{C_RESET}")
        return
    print(vault[name]["value"])


def _repl_inject(vault, password, project_arg=None):
    project = Path(project_arg or Path.cwd()).resolve()
    keys_to_write = {n: v for n, v in vault.items()
                     if str(project) in (v.get("projects") or [])}
    if not keys_to_write:
        print(f"  {C_DIM}No keys assigned to {project}.{C_RESET}")
        return
    print(f"  {C_DIM}Inject writes the keys assigned to this project into its local .env file.{C_RESET}")
    print(f"  {C_DIM}Only keys linked to this project path are written here.{C_RESET}")
    print(f"  Project: {C_CYAN}{project}{C_RESET}")
    print(f"  Will write: {', '.join(sorted(keys_to_write))}")
    try:
        confirm = input("  Confirm? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if confirm != "y":
        print("  Cancelled.")
        return

    class _A: pass
    a = _A()
    a.project = str(project)
    a.all = False
    cmd_inject(a, vault, password)


def _repl_project_add(project_arg: str) -> str:
    project = Path(project_arg).resolve()
    config = load_config()
    config.setdefault("projects", {})
    project_key = str(project)
    if project_key not in config["projects"]:
        config["projects"][project_key] = {
            "name": project.name,
            "created": datetime.now().isoformat(),
        }
        save_config(config)
    print(f"  {C_GREEN}✓ Linked project{C_RESET} {C_CYAN}{project_key}{C_RESET}")
    return project_key


def _repl_project_assign(vault, password, project_arg: str, key_names: list[str], vault_key=None) -> None:
    project_key = _repl_project_add(project_arg)
    missing = [name.upper() for name in key_names if name.upper() not in vault]
    if missing:
        print(f"{C_RED}Unknown keys: {', '.join(missing)}{C_RESET}")
        return
    for raw_name in key_names:
        name = raw_name.upper()
        projects = vault[name].setdefault("projects", [])
        if project_key not in projects:
            projects.append(project_key)
    _save_vault_for_session(vault, password, vault_key)
    print(f"  {C_GREEN}✓ Assigned{C_RESET} {', '.join(name.upper() for name in key_names)} to {C_CYAN}{project_key}{C_RESET}")


def _repl_projects(vault) -> None:
    print(f"{C_WHITE}Projects{C_RESET}")
    print(f"  {C_DIM}A project is a local repo or app folder that should receive selected secrets in its .env file.{C_RESET}")
    print(f"  {C_DIM}Typical flow: project add <path>  ->  project assign <path> OPENAI_API_KEY  ->  inject <path>{C_RESET}")
    print()
    projects = _project_summary(vault)
    if not projects:
        print(f"  {C_DIM}No projects linked yet. Use: project add <path>{C_RESET}")
        return
    for project in projects:
        keys = ", ".join(project["keys"]) if project["keys"] else "no assigned keys"
        print(f"  {C_CYAN}{project['path']}{C_RESET}\n    {len(project['keys'])} key(s): {keys}")


def _render_security_panel(vault) -> None:
    stale = []
    missing_backups = []
    for name, info in sorted(vault.items()):
        age = days_since(info.get("rotated") or info.get("created"))
        if age != float("inf") and age > 90:
            stale.append((name, int(age)))
        if not info.get("next_value"):
            missing_backups.append(name)
    print(f"{C_WHITE}Security / Health{C_RESET}")
    print(f"  {C_DIM}Healthy keys are fresh. Warning keys are aging toward rotation. Critical keys are overdue or risky.{C_RESET}")
    print(f"  {C_DIM}Backup staged means you already saved the next secret value and can promote it during rotation.{C_RESET}")
    print()
    print(f"  Stale keys: {len(stale)}")
    print(f"  Missing backup slots: {len(missing_backups)}")
    if stale:
        print("  Needs rotation: " + ", ".join(f"{name} ({age}d)" for name, age in stale[:5]))
    if missing_backups:
        print("  No backup staged: " + ", ".join(missing_backups[:5]))


def _repl_agents(vault, password, vault_key, rest=None) -> None:
    rest = rest or []
    import pushkey_agent_tokens as _at
    action = rest[0].lower() if rest else "help"
    if action in {"help", "about"}:
        _print_agent_help()
        print()
        print(f"  {C_CYAN}agents list{C_RESET}                 show existing tokens")
        print(f"  {C_CYAN}agents create NAME scopes{C_RESET} create a token, e.g. agents create builder read,inject")
        print(f"  {C_CYAN}agents revoke TOKEN_ID{C_RESET}     revoke a token by id")
        return
    if action == "list":
        tokens = _at.list_tokens()
        if not tokens:
            print(f"  {C_DIM}No agent tokens yet.{C_RESET}")
            return
        for token in tokens:
            scopes = ",".join(token.get("scopes", []))
            print(f"  {C_CYAN}{token['id']}{C_RESET}  {token['name']}  [{scopes}]")
        return
    if action == "create":
        if password is None:
            print(f"{C_RED}Master password session required to create tokens.{C_RESET}")
            return
        if len(rest) < 3:
            print(f"{C_RED}Usage: agents create <name> read,write,inject{C_RESET}")
            return
        name = rest[1]
        scopes = [scope.strip() for scope in rest[2].split(",") if scope.strip()]
        ok, result, token_id = _at.create_token(name, scopes, vault_key)
        if not ok:
            print(f"{C_RED}{result}{C_RESET}")
            return
        print(f"  {C_GREEN}✓ Created token{C_RESET} {C_CYAN}{token_id}{C_RESET}")
        print(f"  {result}")
        return
    if action == "revoke":
        if password is None:
            print(f"{C_RED}Master password session required to revoke tokens.{C_RESET}")
            return
        if len(rest) < 2:
            print(f"{C_RED}Usage: agents revoke <token_id>{C_RESET}")
            return
        if not _at.revoke_token(rest[1]):
            print(f"{C_RED}Token not found.{C_RESET}")
            return
        print(f"  {C_GREEN}✓ Revoked token{C_RESET} {C_CYAN}{rest[1]}{C_RESET}")
        return
    print(f"{C_RED}Usage: agents [list|create|revoke]{C_RESET}")


def _handle_repl_command(cmd, rest, vault, password, vault_key, app_proc):
    aliases = {"1": "add", "2": "get", "3": "inject", "4": "rotate", "5": "projects", "6": "agents", "7": "security", "8": "app"}
    cmd = aliases.get(cmd, cmd)
    if cmd in ("exit", "quit"):
        return False
    if cmd in ("help", "about"):
        _print_help()
        return app_proc
    if cmd == "agents":
        _repl_agents(vault, password, vault_key, rest)
        return app_proc
    if cmd == "projects":
        _repl_projects(vault)
        return app_proc
    if cmd == "project":
        if not rest:
            print(f"{C_RED}Usage: project [add|assign|inject] ...{C_RESET}")
        elif rest[0] == "add" and len(rest) >= 2:
            _repl_project_add(rest[1])
        elif rest[0] == "assign" and len(rest) >= 3:
            _repl_project_assign(vault, password, rest[1], rest[2:], vault_key)
        elif rest[0] == "inject" and len(rest) >= 2:
            _repl_inject(vault, password, rest[1])
        else:
            print(f"{C_RED}Usage: project [add|assign|inject] ...{C_RESET}")
        return app_proc
    if cmd == "security":
        _render_security_panel(vault)
        return app_proc
    if cmd == "desktop":
        _launch_desktop_app()
        return app_proc
    if cmd == "status":
        _render_dashboard(vault)
        return app_proc
    if cmd == "list":
        f = None
        if rest and rest[0] in ("healthy", "warning", "critical"):
            f = rest[0]
        elif rest and rest[0] == "--status" and len(rest) > 1:
            f = rest[1]
        _repl_list(vault, f)
        return app_proc
    if cmd == "get":
        if not rest:
            print(f"{C_RED}Usage: get NAME{C_RESET}")
        else:
            _repl_get(vault, rest[0].upper())
        return app_proc
    if cmd == "copy":
        if not rest:
            print(f"{C_RED}Usage: copy NAME{C_RESET}")
        else:
            _repl_copy(vault, rest[0].upper())
        return app_proc
    if cmd == "add":
        _repl_add(vault, password, vault_key)
        return app_proc
    if cmd == "rotate":
        if not rest:
            print(f"{C_RED}Usage: rotate NAME{C_RESET}")
        else:
            _repl_rotate(vault, password, rest[0].upper(), vault_key)
        return app_proc
    if cmd == "delete":
        if not rest:
            print(f"{C_RED}Usage: delete NAME{C_RESET}")
        else:
            _repl_delete(vault, password, rest[0].upper(), vault_key)
        return app_proc
    if cmd == "inject":
        _repl_inject(vault, password, rest[0] if rest else None)
        return app_proc
    if cmd == "app":
        if app_proc and app_proc.poll() is None:
            print(f"  {C_DIM}App already running.{C_RESET}")
            return app_proc
        return _cmd_app(blocking=False)
    print(f"{C_RED}Unknown command. Type help.{C_RESET}")
    return app_proc


def _print_agent_help():
    print(f"{C_WHITE}Agent tokens{C_RESET}")
    print("An agent token is a scoped credential for an AI agent, CI job, or local automation flow.")
    print("Use a scoped pk_agent_... token when something should access the vault without the master password.")
    print("If a token is no longer needed, revoke it and that automation path immediately loses access.")
    print("")
    scopes = [
        ("read", "list keys, get a value, check status/health"),
        ("write", "add, rotate, delete, import, or stage backup values"),
        ("inject", "write assigned secrets into a local project .env file"),
    ]
    w = max(len(name) for name, _desc in scopes)
    for name, desc in scopes:
        print(f"  {C_CYAN}{name.ljust(w)}{C_RESET}  {C_DIM}{desc}{C_RESET}")
    print()
    print(f"{C_WHITE}Where agentic access works{C_RESET}")
    surfaces = [
        ("CLI", "pushkey --token pk_agent_... list --json"),
        ("MCP", 'unlock_vault("pk_agent_...") then call list_keys / inject_env / rotate_to_backup'),
        ("Local API", 'POST /api/unlock with {"password": "pk_agent_..."}'),
    ]
    w = max(len(name) for name, _desc in surfaces)
    for name, example in surfaces:
        print(f"  {C_CYAN}{name.ljust(w)}{C_RESET}  {C_DIM}{example}{C_RESET}")
    print()
    print(f"{C_DIM}Tip: use plaintext write tools only for short-lived dev/test keys. For long-lived production keys, prefer the local CLI so the secret never enters chat context.{C_RESET}")


def _print_help():
    print(f"{C_WHITE}What Pushkey does{C_RESET}")
    print("Pushkey helps developers keep API keys local, encrypted, organized by project, and ready to inject into .env files.")
    print()

    print(f"{C_WHITE}Vault commands{C_RESET}")
    rows = [
        ("list [filter]",     "show all keys (filter: healthy|warning|critical)"),
        ("get NAME",          "print key value"),
        ("copy NAME",         "copy to clipboard (clears in 30s)"),
        ("add",               "add a new key (prompts for value)"),
        ("rotate NAME",       "rotate key value"),
        ("delete NAME",       "delete a key"),
        ("inject [PATH]",     "write assigned keys to project .env"),
        ("projects",          "list linked projects and assigned keys"),
        ("project add PATH",  "link a project folder"),
        ("project assign PATH KEYS...", "assign one or more keys to a project"),
        ("agents",            "list/create/revoke agent tokens"),
        ("security",          "show stale keys and missing backup coverage"),
        ("app / desktop",     "launch the web app or desktop app"),
        ("status",            "re-render the branded command center"),
        ("about",             "show this guide again"),
        ("exit / quit",       "exit REPL"),
    ]
    w = max(len(r[0]) for r in rows)
    for cmd, desc in rows:
        print(f"  {C_CYAN}{cmd.ljust(w)}{C_RESET}  {C_DIM}{desc}{C_RESET}")
    print()

    print(f"{C_WHITE}Common workflows{C_RESET}")
    workflows = [
        "Add a secret: add  → save OPENAI_API_KEY once, encrypted locally",
        "Use a secret: get OPENAI_API_KEY  or  copy OPENAI_API_KEY",
        "Inject project env: inject .  → write assigned keys into the current repo .env",
        "Rotate a key: rotate OPENAI_API_KEY  → replace the live value and keep metadata updated",
    ]
    for line in workflows:
        print(f"  {C_DIM}{line}{C_RESET}")
    print()

    _print_agent_help()


def _repl(args):
    _s.ensure_vault_dir()
    if not _s.VAULT_FILE.exists():
        print(f"{C_RED}No vault found. Run: pushkey init{C_RESET}", file=sys.stderr)
        sys.exit(1)
    password = _get_password(args)
    vault, _vk = load_vault(password)
    if vault is None:
        print(f"{C_RED}Error: wrong master password{C_RESET}", file=sys.stderr)
        sys.exit(1)
    _run_repl_session(vault, password, _vk)


if __name__ == "__main__":
    main()

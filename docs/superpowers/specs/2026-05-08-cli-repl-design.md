# Pushkey CLI v2 — Interactive REPL + `pushkey app`

**Date:** 2026-05-08  
**Status:** Approved  
**File:** `pushkey_cli.py` (single-file change, no new deps)

---

## Goal

`pushkey` typed bare in any terminal → interactive Cyber Cyan REPL with dashboard, health warnings, and full vault management. `pushkey app` (standalone or REPL command) → starts local API and opens web UI in browser.

---

## Architecture

Single file modification: `pushkey_cli.py`. No new dependencies — pure stdlib only (`readline`, `subprocess`, `webbrowser`, `shutil`, ANSI escapes). 

`main()` modified: if no subcommand → call `_repl()`. All existing subcommand handler functions (`cmd_add`, `cmd_list`, etc.) are **reused** by the REPL dispatch table — zero duplicated logic.

---

## Color System (Cyber Cyan / ANSI)

| Token | ANSI | Use |
|-------|------|-----|
| Cyan | `\033[96m` | Key names, borders, prompt, accents |
| White | `\033[97m` | Brand name, primary text |
| Green | `\033[92m` | Healthy status, success messages |
| Orange | `\033[33m` | Warning status, stale keys |
| Red | `\033[91m` | Critical status, errors |
| Dim gray | `\033[2m` | Provider labels, secondary text |
| Reset | `\033[0m` | Reset after every colored token |

---

## Launch Sequence

```
pushkey
  1. prompt: Master password (hidden, getpass)
  2. load_vault(password) — exit with error if wrong
  3. render_dashboard(vault)
  4. render_stale_warnings(vault)  ← only if keys > 90d exist
  5. readline setup (tab complete + history)
  6. enter prompt loop: pushkey> _
```

---

## Dashboard Block

Rendered by `_render_dashboard(vault)`. Re-rendered by `status` command.

```
╔══════════════════════════════════════════╗
║  PUSHKEY  v2.1.0          12 keys total  ║
║  2 need rotation          1 backup staged║
╚══════════════════════════════════════════╝
  ✓ healthy (10)   ⚠ warning (2)   ✗ critical (0)
```

- Box drawn with `═╔╗╚╝║` Unicode box chars, colored cyan
- Counts derived from `health_status()` per key (already in `pushkey_providers.py`)
- Backup staged count from `vault[k].get("next_value")` non-null check

---

## Stale Key Warning Block

Rendered by `_render_stale_warnings(vault)` immediately after dashboard. Only shown if any key > 90 days old.

```
⚠  2 keys need rotation:
   ANTHROPIC_KEY    95 days
   STRIPE_SECRET   112 days
   Press Enter to skip, or type a name to rotate →
```

- Reads one line of input; if matches a key name → calls inline rotate wizard for that key
- Enter/blank → continues to prompt loop
- Unrecognized input → prints `Unknown key. Continuing.` in dim gray, continues to prompt loop

---

## REPL Prompt Loop

Prompt string: `\033[96mpushkey\033[0m> `

Input parsed as: `COMMAND [ARG1] [ARG2...]`

### Command Dispatch Table

| Command | Args | Handler |
|---------|------|---------|
| `list` | `[--status healthy\|warning\|critical]` | `_repl_list(vault)` — table + minimap |
| `get` | `NAME` | `cmd_get` reused |
| `copy` | `NAME` | `_repl_copy(vault, name)` — clipboard, no print |
| `add` | `NAME` | `_repl_add(vault, password)` — hidden value prompt |
| `rotate` | `NAME` | `_repl_rotate(vault, password, name)` — hidden input |
| `delete` | `NAME` | `cmd_delete` reused with confirm |
| `inject` | `[PATH]` | `_repl_inject(vault, password)` — preview + confirm |
| `app` | — | `_cmd_app(token=None)` |
| `status` | — | re-renders dashboard |
| `help` | — | prints command table |
| `exit` / `quit` | — | clean exit, stop app server if running |
| Ctrl+C / Ctrl+D | — | clean exit |

Unknown command → `Unknown command '<x>'. Type help.` in red.

---

## Health Minimap (on `list`)

Each key row gets a 10-block age bar:

```
OPENAI_API_KEY   openai   prod  ██░░░░░░░░  14d  ✓
ANTHROPIC_KEY    anthropic dev  ████████░░  95d  ⚠
STRIPE_SECRET    stripe   prod  ██████████ 112d  ✗
```

- Bar = `days / 90 * 10` filled blocks, capped at 10
- Filled block: `█`, empty: `░`
- Color: green (< 60d), orange (60–90d), red (> 90d)

---

## Tab Completion

Registered via `readline.set_completer` + `readline.parse_and_bind("tab: complete")`.

- Empty line or first token → complete from command list
- Second token after `get`, `copy`, `rotate`, `delete` → complete from vault key names
- Vault key names loaded once at REPL start, refreshed after `add`/`delete`

---

## Command History

- `readline.read_history_file(~/.pushkey/.cli_history)` on start
- `readline.write_history_file(~/.pushkey/.cli_history)` on exit
- `readline.set_history_length(500)`
- Before writing, strip lines matching `^(add|rotate)\s+\S+\s+\S+` (would contain raw values if user passed value as arg — belt-and-suspenders since REPL always prompts, but guards against edge cases)

---

## Inline Rotate Wizard

```python
def _repl_rotate(vault, password, name):
    new_val = getpass.getpass(f"  New value for {name} (hidden): ")
    if not new_val.strip():
        print("  Aborted.")
        return
    old_age = days_since(vault[name].get("rotated") or vault[name].get("added"))
    vault[name]["value"] = new_val.strip()
    vault[name]["rotated"] = datetime.now().strftime("%Y-%m-%d")
    save_vault(vault, password)
    print(f"  ✓ Rotated. Was {old_age}d old.")
```

---

## Quick Copy

```python
def _repl_copy(vault, name):
    # uses pyperclip if available, falls back to xclip/pbcopy/clip.exe detection
    value = vault[name]["value"]
    _copy_to_clipboard(value)
    print(f"  ✓ {name} copied to clipboard. Clears in 30s.")
    threading.Timer(30, lambda: _copy_to_clipboard("")).start()
```

Clipboard helper priority: `pyperclip` (if installed) → `clip.exe` (Windows) → `pbcopy` (mac) → `xclip`/`xsel` (linux). Falls back gracefully with an error if none found.

---

## inject Wizard

```python
def _repl_inject(vault, password):
    cwd = Path.cwd()
    config = load_config()
    assigned = config.get("projects", {}).get(str(cwd), {}).get("keys", [])
    if not assigned:
        print(f"  No keys assigned to {cwd}. Use: assign KEY to link keys.")
        return
    print(f"  Project: {cwd}")
    print(f"  Will write: {', '.join(assigned)}")
    confirm = input("  Confirm? [y/N] ").strip().lower()
    if confirm == "y":
        # calls existing inject logic
```

---

## `pushkey app` — Web UI Launcher

Works both as:
- **Standalone subcommand:** `pushkey app` from any shell
- **REPL command:** `app` inside the interactive session

```python
def _cmd_app(existing_proc=None):
    token = secrets.token_urlsafe(24)
    port = 7654
    env = {**os.environ, "PUSHKEY_LOCAL_PORT": str(port), "PUSHKEY_LAUNCH_TOKEN": token}
    proc = subprocess.Popen([sys.executable, str(Path(__file__).parent / "pushkey_local_api.py")], env=env)
    # poll until ready, max 10s
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.5)
            break
        except Exception:
            time.sleep(0.5)
    url = f"http://127.0.0.1:{port}/?token={token}"
    webbrowser.open(url)
    print(f"  \033[96m→\033[0m {url}")
    return proc  # caller holds reference; killed on REPL exit
```

Standalone mode: `proc.wait()` (blocks). REPL mode: proc stored, killed on `exit`.

---

## Error Handling

- Wrong password → `Error: wrong master password` → exit 1
- No vault → `No vault found. Run: pushkey init` → exit 1
- Key not found in REPL → `Unknown key 'X'. Try: list` in red, continue loop
- Clipboard unavailable → print warning, don't crash
- `pushkey app` port already in use → try 7655, 7656, up to 7659

---

## Testing

Existing 107 tests unaffected — REPL is a new code path. New manual smoke test checklist:
1. `pushkey` → dashboard renders, prompt appears
2. `list` → minimap bars colored correctly
3. `rotate NAME` → hidden input, vault updated
4. `copy NAME` → clipboard set, not printed
5. `app` → browser opens, local API responds
6. Tab complete key names
7. History persists across sessions

---

## Out of Scope

- No `rich` or `textual` dependency
- No arrow-key navigation (ncurses-style panels)
- No network calls from REPL (all local)

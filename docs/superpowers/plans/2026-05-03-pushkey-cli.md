# Pushkey CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract provider/health logic into `pushkey_providers.py`, then build `pushkey_cli.py` — a fully standalone CLI with 8 commands that imports zero tkinter.

**Architecture:** Three new/modified files. `pushkey_providers.py` holds the provider database, `days_since`, and `health_status` (moved from `pushkey.py`). `pushkey_cli.py` is a pure argparse CLI importing only from `pushkey_*` sub-modules. `pyproject.toml` gains a `pushkey` entry point pointing at the CLI.

**Tech Stack:** Python stdlib (argparse, getpass, json, re, shutil), existing pushkey_* modules.

---

### Task 1: Create `pushkey_providers.py`

**Files:**
- Create: `pushkey_providers.py`
- Modify: `pushkey.py` (replace inline defs with imports)

- [ ] **Step 1: Create `pushkey_providers.py`**

```python
"""
Pushkey — provider database, detection, and key health utilities.
No tkinter dependency — safe to import from CLI and tests.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pushkey_shared as _s
from pushkey_crypto import log_event


_BUNDLED_PROVIDERS = {
    "OpenAI":         {"url": "https://platform.openai.com/api-keys",                          "prefix": "sk-",           "category": "AI",                 "patterns": ["openai", "gpt"],             "rotation_days": 90},
    "Anthropic":      {"url": "https://console.anthropic.com/settings/keys",                   "prefix": "sk-ant-",       "category": "AI",                 "patterns": ["anthropic", "claude"],       "rotation_days": 90},
    "Alpaca":         {"url": "https://app.alpaca.markets/paper/dashboard/overview",            "prefix": "",              "category": "Trading",            "patterns": ["alpaca"],                    "rotation_days": 90},
    "OANDA":          {"url": "https://www.oanda.com/account/tpa/personal_token",               "prefix": "",              "category": "Trading",            "patterns": ["oanda"],                     "rotation_days": 90},
    "Coinbase":       {"url": "https://www.coinbase.com/settings/api",                          "prefix": "",              "category": "Trading",            "patterns": ["coinbase"],                  "rotation_days": 90},
    "Supabase":       {"url": "https://supabase.com/dashboard",                                 "prefix": "eyJ",           "category": "Database",           "patterns": ["supabase"],                  "rotation_days": 180},
    "Stripe":         {"url": "https://dashboard.stripe.com/apikeys",                           "prefix": "sk_",           "category": "Payment",            "patterns": ["stripe"],                    "rotation_days": 90},
    "AWS":            {"url": "https://console.aws.amazon.com/iam/home#/security_credentials", "prefix": "AKIA",          "category": "Cloud",              "patterns": ["aws", "amazon"],             "rotation_days": 90},
    "Vercel":         {"url": "https://vercel.com/account/tokens",                              "prefix": "",              "category": "Cloud",              "patterns": ["vercel"],                    "rotation_days": 90},
    "GitHub":         {"url": "https://github.com/settings/tokens",                            "prefix": "ghp_",          "category": "VCS",                "patterns": ["github", "gh_", "ghp_"],    "rotation_days": 90},
    "GitLab":         {"url": "https://gitlab.com/-/profile/personal_access_tokens",           "prefix": "glpat-",        "category": "VCS",                "patterns": ["gitlab", "glpat"],           "rotation_days": 90},
    "Twilio":         {"url": "https://console.twilio.com/?frameUrl=/console/account/keys",    "prefix": "",              "category": "Communication",      "patterns": ["twilio"],                    "rotation_days": 90},
    "SendGrid":       {"url": "https://app.sendgrid.com/settings/api_keys",                    "prefix": "SG.",           "category": "Communication",      "patterns": ["sendgrid"],                  "rotation_days": 90},
    "Slack":          {"url": "https://api.slack.com/apps",                                    "prefix": "xoxb-",         "category": "Communication",      "patterns": ["slack", "xoxb", "xoxp"],    "rotation_days": 180},
    "Discord":        {"url": "https://discord.com/developers/applications",                   "prefix": "",              "category": "Communication",      "patterns": ["discord"],                   "rotation_days": 90},
    "Google Cloud":   {"url": "https://console.cloud.google.com/apis/credentials",             "prefix": "",              "category": "Cloud",              "patterns": ["google", "gcp"],             "rotation_days": 90},
    "Azure":          {"url": "https://portal.azure.com/#view/Microsoft_AAD_IAM/AppIntegrationsMenuBlade", "prefix": "", "category": "Cloud",              "patterns": ["azure"],                     "rotation_days": 90},
    "DigitalOcean":   {"url": "https://cloud.digitalocean.com/account/api/tokens",             "prefix": "dop_v1_",       "category": "Cloud",              "patterns": ["digitalocean", "dop_"],      "rotation_days": 90},
    "Heroku":         {"url": "https://dashboard.heroku.com/account",                          "prefix": "",              "category": "Cloud",              "patterns": ["heroku"],                    "rotation_days": 90},
    "MongoDB Atlas":  {"url": "https://cloud.mongodb.com/v2",                                  "prefix": "mongodb+srv://","category": "Database",           "patterns": ["mongodb", "mongo"],          "rotation_days": 180},
    "PostgreSQL":     {"url": "https://console.cloud.google.com/sql",                          "prefix": "postgresql://", "category": "Database",           "patterns": ["postgres", "psql"],          "rotation_days": 180},
    "Elastic":        {"url": "https://www.elastic.co/cloud/console/",                         "prefix": "",              "category": "Database",           "patterns": ["elastic"],                   "rotation_days": 90},
    "HashiCorp Vault":{"url": "https://www.vaultproject.io/",                                  "prefix": "s.",            "category": "Security",           "patterns": ["hashicorp"],                 "rotation_days": 30},
    "PagerDuty":      {"url": "https://subdomain.pagerduty.com/api_keys",                      "prefix": "",              "category": "Incident",           "patterns": ["pagerduty"],                 "rotation_days": 90},
    "Datadog":        {"url": "https://app.datadoghq.com/organization-settings/api-keys",      "prefix": "",              "category": "Monitoring",         "patterns": ["datadog"],                   "rotation_days": 90},
    "New Relic":      {"url": "https://one.newrelic.com/launcher/api-keys-ui.launcher",        "prefix": "",              "category": "Monitoring",         "patterns": ["newrelic"],                  "rotation_days": 90},
    "HubSpot":        {"url": "https://app.hubspot.com/login",                                 "prefix": "pat-",          "category": "CRM",                "patterns": ["hubspot"],                   "rotation_days": 90},
    "Jira":           {"url": "https://id.atlassian.com/manage/api-tokens",                    "prefix": "",              "category": "Project Management", "patterns": ["jira", "atlassian"],         "rotation_days": 90},
}


def _load_providers():
    merged = dict(_BUNDLED_PROVIDERS)
    if _s.PROVIDERS_CACHE.exists():
        try:
            cached = json.loads(_s.PROVIDERS_CACHE.read_text(encoding="utf-8"))
            merged.update(cached.get("providers", {}))
        except Exception:
            pass
    return merged


def update_providers_from_web():
    """Fetch latest providers.json from GitHub. Returns (new_count, updated_count, error_str)."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(_s.PROVIDERS_REGISTRY_URL, timeout=10) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
        remote = data.get("providers", {})
        if not remote:
            return 0, 0, "Registry returned empty providers list"
        existing = _load_providers()
        new_count     = sum(1 for k in remote if k not in existing)
        updated_count = sum(1 for k in remote if k in existing and remote[k] != existing.get(k))
        tmp = _s.PROVIDERS_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_s.PROVIDERS_CACHE))
        global PROVIDERS
        PROVIDERS = _load_providers()
        log_event(f"providers updated: {new_count} new, {updated_count} changed")
        return new_count, updated_count, None
    except urllib.error.URLError as e:
        return 0, 0, f"Network error: {e.reason}"
    except Exception as e:
        return 0, 0, str(e)


def detect_provider(key_name, key_value=""):
    name_lower = key_name.lower()
    for prov_name, prov in PROVIDERS.items():
        for pattern in prov["patterns"]:
            if pattern in name_lower:
                return prov_name
    prefixed = [(prov["prefix"], name) for name, prov in PROVIDERS.items() if prov["prefix"]]
    for prefix, prov_name in sorted(prefixed, key=lambda x: len(x[0]), reverse=True):
        if key_value.startswith(prefix):
            return prov_name
    return None


def days_since(date_str):
    if not date_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(date_str)
        return (datetime.now() - dt).days
    except Exception:
        return float("inf")


def health_status(key_info):
    age = days_since(key_info.get("rotated") or key_info.get("created"))
    provider = key_info.get("provider")
    threshold = 90
    if provider and provider in PROVIDERS:
        threshold = PROVIDERS[provider].get("rotation_days", 90)
    use_age = days_since(key_info.get("first_used"))
    effective_age = min(age, use_age) if use_age != float("inf") else age
    if effective_age > threshold:
        return "critical"
    if effective_age > threshold * 0.67:
        return "warning"
    return "healthy"


PROVIDERS = _load_providers()
```

- [ ] **Step 2: Update `pushkey.py` — replace inline defs with imports**

At the top of `pushkey.py`, after the existing `from pushkey_tiers import (...)` block (~line 85), add:

```python
from pushkey_providers import (
    _BUNDLED_PROVIDERS, _load_providers, update_providers_from_web,
    detect_provider, days_since, health_status, PROVIDERS,
)
```

Then delete the following blocks from `pushkey.py` (they now live in `pushkey_providers.py`):
- `_BUNDLED_PROVIDERS = { ... }` (lines ~545–574)
- `def _load_providers(): ...` (lines ~577–585)
- `def update_providers_from_web(): ...` (lines ~588–611)
- `PROVIDERS = _load_providers()` (line ~614)
- `def detect_provider(...): ...` (lines ~896–906)
- `def days_since(...): ...` (lines ~1471–1478)
- `def health_status(...): ...` (lines ~1481–1494)

- [ ] **Step 3: Verify import works without tkinter**

```bash
python -c "from pushkey_providers import detect_provider, health_status, PROVIDERS; print('OK', len(PROVIDERS))"
```

Expected output: `OK 27` (or however many providers)

- [ ] **Step 4: Commit**

```bash
git add pushkey_providers.py pushkey.py
git commit -m "refactor: extract provider/health logic into pushkey_providers.py"
```

---

### Task 2: Tests for `pushkey_providers.py`

**Files:**
- Create: `tests/test_providers.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_providers.py
import pytest
from pushkey_providers import detect_provider, days_since, health_status, PROVIDERS


def test_detect_by_name_pattern():
    assert detect_provider("OPENAI_API_KEY") == "OpenAI"


def test_detect_anthropic_by_name():
    assert detect_provider("ANTHROPIC_API_KEY") == "Anthropic"


def test_detect_by_value_prefix_openai():
    assert detect_provider("MY_KEY", "sk-abc123") == "OpenAI"


def test_detect_anthropic_prefix_wins_over_openai():
    # sk-ant- is longer than sk- so Anthropic should win
    assert detect_provider("MY_KEY", "sk-ant-abc123") == "Anthropic"


def test_detect_aws_by_value():
    assert detect_provider("MY_KEY", "AKIAabc123") == "AWS"


def test_detect_unknown_returns_none():
    assert detect_provider("RANDOM_KEY", "xyz123") is None


def test_detect_github_by_name():
    assert detect_provider("GH_TOKEN") == "GitHub"


def test_detect_stripe_by_prefix():
    assert detect_provider("PAYMENT_KEY", "sk_live_abc") == "Stripe"


def test_days_since_none():
    assert days_since(None) == float("inf")


def test_days_since_today():
    from datetime import datetime
    now = datetime.now().isoformat()
    assert days_since(now) == 0


def test_days_since_old():
    assert days_since("2020-01-01T00:00:00") > 1000


def test_health_status_healthy():
    from datetime import datetime
    info = {"created": datetime.now().isoformat(), "provider": None}
    assert health_status(info) == "healthy"


def test_health_status_critical():
    info = {"created": "2020-01-01T00:00:00", "provider": None}
    assert health_status(info) == "critical"


def test_health_status_uses_provider_threshold():
    # HashiCorp Vault has 30-day threshold
    from datetime import datetime, timedelta
    dt = (datetime.now() - timedelta(days=35)).isoformat()
    info = {"created": dt, "provider": "HashiCorp Vault"}
    assert health_status(info) == "critical"


def test_providers_contains_openai():
    assert "OpenAI" in PROVIDERS
    assert PROVIDERS["OpenAI"]["url"] == "https://platform.openai.com/api-keys"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_providers.py -v
```

Expected: all 14 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_providers.py
git commit -m "test: add pushkey_providers test suite"
```

---

### Task 3: Create `pushkey_cli.py`

**Files:**
- Create: `pushkey_cli.py`

- [ ] **Step 1: Write `pushkey_cli.py`**

```python
"""
Pushkey CLI — standalone command-line interface.
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
    project = Path(args.project or Path.cwd()).resolve()
    if not project.is_dir():
        print(f"Error: '{project}' is not a directory", file=sys.stderr)
        sys.exit(1)

    keys_to_write = {
        n: v for n, v in vault.items()
        if str(project) in (v.get("projects") or [])
    }
    if not keys_to_write:
        # fall back: write all keys if --all flag set
        if getattr(args, "all", False):
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
        description="Pushkey — encrypted API key manager",
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
    p_inject.add_argument("--all", action="store_true", help="Inject all keys regardless of project assignment")

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
```

- [ ] **Step 2: Smoke test — no tkinter import**

```bash
python -c "import pushkey_cli; print('OK — no tkinter')"
```

Expected: `OK — no tkinter`

- [ ] **Step 3: Commit**

```bash
git add pushkey_cli.py
git commit -m "feat: add pushkey_cli.py — standalone CLI with 8 commands"
```

---

### Task 4: Tests for `pushkey_cli.py`

**Files:**
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_cli.py
"""
CLI tests — call command functions directly, no subprocess.
Password is always injected via monkeypatch on PUSHKEY_MASTER.
"""
import json
import sys
import pytest
from argparse import Namespace
from pathlib import Path

import pushkey_shared
import pushkey_cli as cli
from pushkey_vault import save_vault, load_vault


PASSWORD = "cli-test-password"


@pytest.fixture(autouse=True)
def patch_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PUSHKEY_MASTER", PASSWORD)
    monkeypatch.setattr(pushkey_shared, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey_shared, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey_shared, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey_shared, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(pushkey_shared, "LOG_FILE", tmp_path / "pushkey.log")
    monkeypatch.setattr(pushkey_shared, "HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(pushkey_shared, "IMPORT_DIR", tmp_path / "import")
    monkeypatch.setattr(pushkey_shared, "LICENSE_FILE", tmp_path / ".license")
    monkeypatch.setattr(pushkey_shared, "TOKEN_FILE", tmp_path / ".token")
    pushkey_shared.ensure_vault_dir()


def _empty_vault():
    return {}


def _vault_with_key():
    from datetime import datetime
    return {
        "OPENAI_API_KEY": {
            "value": "sk-test123",
            "created": datetime.now().isoformat(),
            "rotated": None,
            "provider": "OpenAI",
            "env": "all",
            "projects": [],
            "notes": "",
            "rotation_count": 0,
        }
    }


# ── add ──────────────────────────────────────────────────────────────────────

def test_cmd_add_new_key(capsys):
    vault = _empty_vault()
    args = Namespace(name="OPENAI_API_KEY", value="sk-abc", notes=None)
    cli.cmd_add(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "Added OPENAI_API_KEY" in out
    assert "OpenAI" in out
    assert "OPENAI_API_KEY" in vault
    assert vault["OPENAI_API_KEY"]["provider"] == "OpenAI"


def test_cmd_add_duplicate_exits():
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", value="sk-new", notes=None)
    with pytest.raises(SystemExit):
        cli.cmd_add(args, vault, PASSWORD)


def test_cmd_add_normalises_name_to_upper(capsys):
    vault = _empty_vault()
    args = Namespace(name="my_key", value="val123", notes=None)
    cli.cmd_add(args, vault, PASSWORD)
    assert "MY_KEY" in vault


# ── get ──────────────────────────────────────────────────────────────────────

def test_cmd_get_prints_value(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", clip=False)
    cli.cmd_get(args, vault, PASSWORD)
    assert capsys.readouterr().out.strip() == "sk-test123"


def test_cmd_get_missing_exits():
    vault = _empty_vault()
    args = Namespace(name="MISSING_KEY", clip=False)
    with pytest.raises(SystemExit):
        cli.cmd_get(args, vault, PASSWORD)


# ── list ─────────────────────────────────────────────────────────────────────

def test_cmd_list_table(capsys):
    vault = _vault_with_key()
    args = Namespace(status=None, json=False)
    cli.cmd_list(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out
    assert "OpenAI" in out


def test_cmd_list_json_output(capsys):
    vault = _vault_with_key()
    args = Namespace(status=None, json=True)
    cli.cmd_list(args, vault, PASSWORD)
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["name"] == "OPENAI_API_KEY"


def test_cmd_list_status_filter(capsys):
    vault = _vault_with_key()
    args = Namespace(status="critical", json=False)
    cli.cmd_list(args, vault, PASSWORD)
    out = capsys.readouterr().out
    # fresh key is healthy — filtered out
    assert "OPENAI_API_KEY" not in out


# ── rotate ───────────────────────────────────────────────────────────────────

def test_cmd_rotate_updates_value(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", new_value="sk-new-value")
    cli.cmd_rotate(args, vault, PASSWORD)
    assert vault["OPENAI_API_KEY"]["value"] == "sk-new-value"
    assert vault["OPENAI_API_KEY"]["rotated"] is not None
    assert vault["OPENAI_API_KEY"]["rotation_count"] == 1
    assert capsys.readouterr().out.strip() == "Rotated OPENAI_API_KEY"


def test_cmd_rotate_missing_exits():
    vault = _empty_vault()
    args = Namespace(name="MISSING", new_value="x")
    with pytest.raises(SystemExit):
        cli.cmd_rotate(args, vault, PASSWORD)


# ── delete ───────────────────────────────────────────────────────────────────

def test_cmd_delete_with_yes(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", yes=True)
    cli.cmd_delete(args, vault, PASSWORD)
    assert "OPENAI_API_KEY" not in vault
    assert "Deleted" in capsys.readouterr().out


def test_cmd_delete_missing_exits():
    vault = _empty_vault()
    args = Namespace(name="GHOST", yes=True)
    with pytest.raises(SystemExit):
        cli.cmd_delete(args, vault, PASSWORD)


# ── status ───────────────────────────────────────────────────────────────────

def test_cmd_status(capsys):
    vault = _vault_with_key()
    cli.cmd_status(Namespace(), vault, PASSWORD)
    out = capsys.readouterr().out
    assert "1 key" in out
    assert "healthy" in out


# ── import ───────────────────────────────────────────────────────────────────

def test_cmd_import_env_file(tmp_path, capsys):
    env_file = tmp_path / "secrets.env"
    env_file.write_text("GITHUB_TOKEN=ghp_abc123\nSTRIPE_KEY=sk_live_xyz\n", encoding="utf-8")
    vault = _empty_vault()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    assert "GITHUB_TOKEN" in vault
    assert "STRIPE_KEY" in vault
    assert vault["GITHUB_TOKEN"]["provider"] == "GitHub"
    assert "Imported 2" in capsys.readouterr().out


def test_cmd_import_skips_existing(tmp_path, capsys):
    env_file = tmp_path / "more.env"
    env_file.write_text("OPENAI_API_KEY=sk-new\n", encoding="utf-8")
    vault = _vault_with_key()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "Imported 0" in out
    assert "skipped 1" in out


def test_cmd_import_ignores_comments(tmp_path, capsys):
    env_file = tmp_path / "commented.env"
    env_file.write_text("# this is a comment\nREAL_KEY=realval\n", encoding="utf-8")
    vault = _empty_vault()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    assert "REAL_KEY" in vault
    assert "# THIS IS A COMMENT" not in vault


# ── inject ───────────────────────────────────────────────────────────────────

def test_cmd_inject_all_flag(tmp_path, capsys):
    project = tmp_path / "myproject"
    project.mkdir()
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=True)
    cli.cmd_inject(args, vault, PASSWORD)
    env_file = project / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "OPENAI_API_KEY=sk-test123" in content
    gi = project / ".gitignore"
    assert gi.exists()
    assert ".env" in gi.read_text()


def test_cmd_inject_no_project_no_all(tmp_path, capsys):
    project = tmp_path / "empty_project"
    project.mkdir()
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=False)
    with pytest.raises(SystemExit):
        cli.cmd_inject(args, vault, PASSWORD)
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: add CLI test suite"
```

---

### Task 5: Update `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update entry points and py-modules**

Replace the `[project.scripts]` and `[tool.setuptools]` sections:

```toml
[project.scripts]
pushkey = "pushkey_cli:main"
pushkey-gui = "pushkey:main"

[tool.setuptools]
py-modules = ["pushkey", "pushkey_cli", "pushkey_providers", "pushkey_shared", "pushkey_crypto", "pushkey_vault", "pushkey_tiers"]
```

- [ ] **Step 2: Run full test suite**

```bash
pytest -v
```

Expected: all existing tests + new tests pass.

- [ ] **Step 3: Final commit**

```bash
git add pyproject.toml
git commit -m "build: wire pushkey_cli as pip entry point, add pushkey-gui alias"
```

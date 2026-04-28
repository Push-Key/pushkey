"""
Pushkey v2 — Encrypted Key Manager with Direct .env Injection
=========================================================================

This is a desktop app (not a browser tool). It runs on your machine and can:

1. Store keys encrypted with AES-256 via your master password
2. Track when each key was created, last rotated, and from which provider
3. Link directly to each provider's key generation page
4. Register project folders — know which projects use which keys
5. DIRECTLY WRITE .env files into your project folders when keys change
6. Auto-add .env to .gitignore if it's not there already

Usage:
    pip install -r requirements.txt
    python pushkey.py

That's it. Double-click or run from terminal.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import sys
import base64
import hashlib
import secrets
import tempfile
import time
import webbrowser
import re
from pathlib import Path
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════
# CRYPTO
# ═══════════════════════════════════════════════

VAULT_DIR = Path.home() / ".pushkey"
VAULT_FILE = VAULT_DIR / "vault.enc"
SALT_FILE = VAULT_DIR / ".salt"
CONFIG_FILE = VAULT_DIR / "config.json"
LOG_FILE = VAULT_DIR / "pushkey.log"

VAULT_SCHEMA_VERSION = 1

def _migrate_vault(data):
    """Apply schema migrations as needed. Migrations are idempotent."""
    schema = data.get("_schema", 0)

    # Future migrations: if schema < 2: apply migration...
    # Migration functions should modify data in-place and return updated data

    if schema < VAULT_SCHEMA_VERSION:
        data["_schema"] = VAULT_SCHEMA_VERSION
    return data

def log_event(message: str) -> None:
    # Best-effort local logging. Never include secret values here.
    try:
        ensure_vault_dir()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass

def ensure_vault_dir():
    VAULT_DIR.mkdir(mode=0o700, exist_ok=True)

def get_or_create_salt():
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    salt = secrets.token_bytes(32)
    SALT_FILE.write_bytes(salt)
    os.chmod(SALT_FILE, 0o600)
    return salt

def derive_key(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations=200_000)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Missing dependency",
        "Pushkey requires the 'cryptography' package.\n\n"
        "Install it with:\n"
        "  pip install -r requirements.txt\n\n"
        "Then re-run:\n"
        "  python pushkey.py"
    )
    _root.destroy()
    raise SystemExit(1)

HAS_CRYPTO = True

def make_fernet(password):
    salt = get_or_create_salt()
    key = derive_key(password, salt)
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt_data(data, password):
    return make_fernet(password).encrypt(data.encode())

def decrypt_data(token, password):
    return make_fernet(password).decrypt(token).decode()

def _serialize_vault(vault):
    return {"_schema": VAULT_SCHEMA_VERSION, "keys": vault}

def _deserialize_vault(data):
    # Accept both the new on-disk format and the legacy "raw dict of keys" format.
    if isinstance(data, dict) and isinstance(data.get("keys"), dict):
        return data["keys"]
    if isinstance(data, dict):
        return data
    return None

def load_vault(password):
    if not VAULT_FILE.exists(): return {}
    try:
        data = json.loads(decrypt_data(VAULT_FILE.read_bytes(), password))
        data = _migrate_vault(data)
        vault = _deserialize_vault(data)
        return vault
    except InvalidToken:
        return None
    except Exception:
        return None

def save_vault(vault, password):
    ensure_vault_dir()
    payload = _serialize_vault(vault)
    VAULT_FILE.write_bytes(encrypt_data(json.dumps(payload, indent=2), password))
    os.chmod(VAULT_FILE, 0o600)

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"projects": {}}

def save_config(config):
    ensure_vault_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))

# ═══════════════════════════════════════════════
# PROVIDER DATABASE
# ═══════════════════════════════════════════════

PROVIDERS = {
    "OpenAI": {
        "url": "https://platform.openai.com/api-keys",
        "prefix": "sk-",
        "category": "AI",
        "patterns": ["openai", "gpt"],
        "rotation_days": 90,
    },
    "Anthropic": {
        "url": "https://console.anthropic.com/settings/keys",
        "prefix": "sk-ant-",
        "category": "AI",
        "patterns": ["anthropic", "claude"],
        "rotation_days": 90,
    },
    "Alpaca": {
        "url": "https://app.alpaca.markets/paper/dashboard/overview",
        "prefix": "",
        "category": "Trading",
        "patterns": ["alpaca"],
        "rotation_days": 90,
    },
    "OANDA": {
        "url": "https://www.oanda.com/account/tpa/personal_token",
        "prefix": "",
        "category": "Trading",
        "patterns": ["oanda"],
        "rotation_days": 90,
    },
    "Coinbase": {
        "url": "https://www.coinbase.com/settings/api",
        "prefix": "",
        "category": "Trading",
        "patterns": ["coinbase"],
        "rotation_days": 90,
    },
    "Supabase": {
        "url": "https://supabase.com/dashboard",
        "prefix": "eyJ",
        "category": "Database",
        "patterns": ["supabase"],
        "rotation_days": 180,
    },
    "Stripe": {
        "url": "https://dashboard.stripe.com/apikeys",
        "prefix": "sk_",
        "category": "Payment",
        "patterns": ["stripe"],
        "rotation_days": 90,
    },
    "AWS": {
        "url": "https://console.aws.amazon.com/iam/home#/security_credentials",
        "prefix": "AKIA",
        "category": "Cloud",
        "patterns": ["aws", "amazon"],
        "rotation_days": 90,
    },
    "Vercel": {
        "url": "https://vercel.com/account/tokens",
        "prefix": "",
        "category": "Cloud",
        "patterns": ["vercel"],
        "rotation_days": 90,
    },
    "GitHub": {
        "url": "https://github.com/settings/tokens",
        "prefix": "ghp_",
        "category": "VCS",
        "patterns": ["github", "gh_", "ghp_"],
        "rotation_days": 90,
    },
    "GitLab": {
        "url": "https://gitlab.com/-/profile/personal_access_tokens",
        "prefix": "glpat-",
        "category": "VCS",
        "patterns": ["gitlab", "glpat"],
        "rotation_days": 90,
    },
    "Twilio": {
        "url": "https://console.twilio.com/?frameUrl=/console/account/keys",
        "prefix": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "category": "Communication",
        "patterns": ["twilio", "twilio_account"],
        "rotation_days": 90,
    },
    "SendGrid": {
        "url": "https://app.sendgrid.com/settings/api_keys",
        "prefix": "SG.",
        "category": "Communication",
        "patterns": ["sendgrid", "sendgrid_api"],
        "rotation_days": 90,
    },
    "Slack": {
        "url": "https://api.slack.com/apps",
        "prefix": "xoxb-",
        "category": "Communication",
        "patterns": ["slack", "slack_bot", "xoxb", "xoxp"],
        "rotation_days": 180,
    },
    "Discord": {
        "url": "https://discord.com/developers/applications",
        "prefix": "",
        "category": "Communication",
        "patterns": ["discord", "discord_token"],
        "rotation_days": 90,
    },
    "Google Cloud": {
        "url": "https://console.cloud.google.com/apis/credentials",
        "prefix": "",
        "category": "Cloud",
        "patterns": ["google", "gcp", "google_cloud"],
        "rotation_days": 90,
    },
    "Azure": {
        "url": "https://portal.azure.com/#view/Microsoft_AAD_IAM/AppIntegrationsMenuBlade",
        "prefix": "",
        "category": "Cloud",
        "patterns": ["azure", "azure_"],
        "rotation_days": 90,
    },
    "DigitalOcean": {
        "url": "https://cloud.digitalocean.com/account/api/tokens",
        "prefix": "dop_v1_",
        "category": "Cloud",
        "patterns": ["digitalocean", "do_", "dop_"],
        "rotation_days": 90,
    },
    "Heroku": {
        "url": "https://dashboard.heroku.com/account",
        "prefix": "",
        "category": "Cloud",
        "patterns": ["heroku"],
        "rotation_days": 90,
    },
    "MongoDB Atlas": {
        "url": "https://cloud.mongodb.com/v2",
        "prefix": "mongodb+srv://",
        "category": "Database",
        "patterns": ["mongodb", "mongo_atlas"],
        "rotation_days": 180,
    },
    "PostgreSQL": {
        "url": "https://console.cloud.google.com/sql",
        "prefix": "postgresql://",
        "category": "Database",
        "patterns": ["postgres", "postgresql", "psql"],
        "rotation_days": 180,
    },
    "Elastic": {
        "url": "https://www.elastic.co/cloud/console/",
        "prefix": "",
        "category": "Database",
        "patterns": ["elastic", "elasticsearch"],
        "rotation_days": 90,
    },
    "HashiCorp Vault": {
        "url": "https://www.vaultproject.io/",
        "prefix": "s.",
        "category": "Security",
        "patterns": ["vault", "hashicorp"],
        "rotation_days": 30,
    },
    "PagerDuty": {
        "url": "https://subdomain.pagerduty.com/api_keys",
        "prefix": "",
        "category": "Incident",
        "patterns": ["pagerduty", "pagerduty_api"],
        "rotation_days": 90,
    },
    "Datadog": {
        "url": "https://app.datadoghq.com/organization-settings/api-keys",
        "prefix": "",
        "category": "Monitoring",
        "patterns": ["datadog", "dd_api"],
        "rotation_days": 90,
    },
    "New Relic": {
        "url": "https://one.newrelic.com/launcher/api-keys-ui.launcher",
        "prefix": "",
        "category": "Monitoring",
        "patterns": ["newrelic", "nrapi"],
        "rotation_days": 90,
    },
    "HubSpot": {
        "url": "https://app.hubspot.com/login",
        "prefix": "pat-",
        "category": "CRM",
        "patterns": ["hubspot", "hubspot_api"],
        "rotation_days": 90,
    },
    "Jira": {
        "url": "https://id.atlassian.com/manage/api-tokens",
        "prefix": "",
        "category": "Project Management",
        "patterns": ["jira", "atlassian"],
        "rotation_days": 90,
    },
}

def detect_provider(key_name, key_value=""):
    name_lower = key_name.lower()
    for prov_name, prov in PROVIDERS.items():
        for pattern in prov["patterns"]:
            if pattern in name_lower:
                return prov_name

    # Check prefixes by length (longest first) to avoid partial matches
    prefixed = [(prov["prefix"], name) for name, prov in PROVIDERS.items() if prov["prefix"]]
    for prefix, prov_name in sorted(prefixed, key=lambda x: len(x[0]), reverse=True):
        if key_value.startswith(prefix):
            return prov_name
    return None

# ═══════════════════════════════════════════════
# .ENV INJECTION ENGINE
# ═══════════════════════════════════════════════

def _format_env_value(value):
    # Minimal .env quoting so common parsers (python-dotenv, dotenv-cli, etc.) behave.
    if value is None:
        return ""
    value = str(value)
    needs_quotes = (
        value == ""
        or value[0].isspace()
        or value[-1].isspace()
        or any(ch in value for ch in ("\n", "\r", "\t", " ", "#", "\""))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\"", "\\\"")
    return f"\"{escaped}\""

# ═══════════════════════════════════════════════
# ENV LINE PARSER (handles .env, .env.example, .pushkey, bulk upload)
# ═══════════════════════════════════════════════

_ENV_LINE_RE = re.compile(
    r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^#\r\n]*?)(?:\s*#.*)?\s*$'
)
_COLON_LINE_RE = re.compile(r'^([A-Za-z][A-Za-z0-9 _-]{1,40})\s*:\s*(?!//)(.+)$')
_LABEL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9 _\-/()\[\]]{0,79}$')
_SECRET_META_RE = re.compile(r'^#\s*secret\s*:\s*(true|false|yes|no|1|0)\s*$', re.IGNORECASE)

def _parse_env_line(raw_line: str):
    """Parse a single .env line. Returns (key, value) or None.

    Handles:
      - export KEY=val        -> ('KEY', 'val')
      - KEY="val"             -> ('KEY', 'val')  [quotes stripped]
      - KEY=val # comment     -> ('KEY', 'val')  [comment discarded]
      - KEY=                  -> ('KEY', '')     [empty values allowed]
      - Label: value          -> ('LABEL', 'value')  [colon format from dashboards]
      - Blank/comment lines   -> None
    """
    line = raw_line.strip()
    if not line or line.startswith('#'):
        return None

    # Try equals format first (standard .env)
    m = _ENV_LINE_RE.match(line)
    if m:
        key = m.group(1).upper()
        raw_val = m.group(2).strip()
        # Strip outer quotes if present
        if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
            quote_char = raw_val[0]
            raw_val = raw_val[1:-1]
            # Unescape common escape sequences
            raw_val = raw_val.replace(f"\\{quote_char}", quote_char)
            raw_val = raw_val.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
        return key, raw_val

    # Try colon format (copied from dashboard / provider pages)
    m = _COLON_LINE_RE.match(line)
    if m:
        label = m.group(1).strip()
        value = m.group(2).strip()
        # Normalize label to KEY_NAME: uppercase, spaces/hyphens to underscore
        key = label.upper().replace(" ", "_").replace("-", "_")
        return key, value

    return None

# Type-word labels: when the label IS one of these words, the key name is built
# from the file prefix + this suffix, and secret flag is set automatically.
_TYPE_WORDS = {
    'key':           ('KEY',          False),
    'api key':       ('API_KEY',      False),
    'token':         ('TOKEN',        False),
    'access token':  ('ACCESS_TOKEN', False),
    'bot token':     ('BOT_TOKEN',    False),
    'secret':        ('SECRET',       True),
    'secret key':    ('SECRET_KEY',   True),
    'private':       ('PRIVATE_KEY',  True),
    'private key':   ('PRIVATE_KEY',  True),
    'password':      ('PASSWORD',     True),
    'passphrase':    ('PASSPHRASE',   True),
    'endpoint':      ('ENDPOINT',     False),
    'url':           ('URL',          False),
    'base url':      ('BASE_URL',     False),
    'api url':       ('API_URL',      False),
    'https':         ('ENDPOINT',     False),
    'http':          ('ENDPOINT',     False),
    'webhook':       ('WEBHOOK_URL',  False),
    'webhook url':   ('WEBHOOK_URL',  False),
    'rpc':           ('RPC_URL',      False),
    'rpc url':       ('RPC_URL',      False),
    'account id':    ('ACCOUNT_ID',   False),
    'account':       ('ACCOUNT_ID',   False),
    'client id':     ('CLIENT_ID',    False),
    'client secret': ('CLIENT_SECRET',True),
    'username':      ('USERNAME',     False),
    'user':          ('USERNAME',     False),
}

def _file_prefix(path):
    """'alpaca telegram.txt' -> 'ALPACA_TELEGRAM'"""
    stem = Path(path).stem
    prefix = re.sub(r'[^A-Z0-9]', '_', stem.upper())
    return re.sub(r'_+', '_', prefix).strip('_')

def _parse_env_file(path):
    """Stateful file parser. Returns (entries, errors).

    Handles four formats:
      1. Standard .env:  KEY=value / export KEY=value / Label: value
      2. Type-word block (filename = project prefix):
             key                    <- type word
             8750660786:AAG...      <- value  ->  ALPACA_TELEGRAM_KEY
      3. Plain label block (label is the full name):
             alpaca telegram
             8750660786:AAG...      ->  ALPACA_TELEGRAM
      4. Secret metadata:
             KEY=value
             # secret: true
    """
    entries = []
    errors = []
    pending_label = None
    pending_label_line = None
    next_secret = None
    prefix = _file_prefix(path)

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # Secret metadata directive
        m = _SECRET_META_RE.match(line)
        if m:
            flag = m.group(1).lower() in ('true', 'yes', '1')
            if pending_label is not None:
                next_secret = flag
            elif entries:
                entries[-1]['secret'] = flag
            continue

        if not line:
            continue

        if line.startswith('#'):
            continue

        # Try standard .env parse
        result = _parse_env_line(raw_line)
        if result:
            name, value = result
            if pending_label:
                errors.append(f"line {pending_label_line}: label '{pending_label}' had no value (skipped)")
                pending_label = None
            if name and value:
                entries.append({
                    'name': name, 'value': value,
                    'line': line_num, 'raw_line': raw_line,
                    'secret': next_secret or False,
                })
                next_secret = None
            elif not value:
                errors.append(f"line {line_num}: {name} skipped (no value)")
            continue

        # Non-matching line: label or bare value?
        if pending_label is not None:
            type_info = _TYPE_WORDS.get(pending_label.lower())
            if type_info:
                # e.g. label="key", file="alpaca telegram.txt" -> ALPACA_TELEGRAM_KEY
                suffix, auto_secret = type_info
                key = f"{prefix}_{suffix}" if prefix else suffix
                is_secret = next_secret if next_secret is not None else auto_secret
            else:
                # label is the full name — always prepend file prefix so it's traceable
                key = re.sub(r'[^A-Z0-9]', '_', pending_label.upper())
                key = re.sub(r'_+', '_', key).strip('_')
                if prefix and not key.startswith(prefix + '_') and key != prefix:
                    key = f"{prefix}_{key}"
                is_secret = next_secret or False
            entries.append({
                'name': key, 'value': line,
                'line': line_num, 'raw_line': raw_line,
                'secret': is_secret,
            })
            next_secret = None
            pending_label = None
        elif _LABEL_RE.match(line):
            pending_label = line
            pending_label_line = line_num
        else:
            errors.append(f"line {line_num}: could not parse '{line[:40]}'")

    if pending_label:
        errors.append(f"line {pending_label_line}: label '{pending_label}' had no value (skipped)")

    return entries, errors

def _atomic_write_text(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.pushkey.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

def _ensure_gitignore_env(project_dir: Path) -> None:
    gitignore_path = project_dir / ".gitignore"
    try:
        if gitignore_path.exists():
            lines = gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if any(line.strip() == ".env" for line in lines):
                return
            with gitignore_path.open("a", encoding="utf-8", newline="\n") as f:
                if lines and lines[-1].strip() != "":
                    f.write("\n")
                f.write("# Pushkey — never commit secrets\n.env\n")
        else:
            gitignore_path.write_text("# Pushkey — never commit secrets\n.env\n", encoding="utf-8", newline="\n")
    except Exception as e:
        log_event(f"gitignore update failed for {project_dir}: {e}")

def inject_env_file(project_path, vault, key_names=None):
    """Write/update a .env file in the given project directory.

    If key_names is None, writes ALL keys. Otherwise only the specified ones.
    Preserves any existing keys in the .env that aren't in our vault.
    """
    project_dir = Path(project_path)
    env_path = project_dir / ".env"

    # Read existing .env if it exists (best-effort).
    existing = {}
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            result = _parse_env_line(raw_line)
            if result:
                k, v = result
                existing[k] = v

    # Determine which keys to write
    if key_names:
        keys_to_write = {k: vault[k]["value"] for k in key_names if k in vault}
    else:
        keys_to_write = {k: v["value"] for k, v in vault.items()}

    # Merge: our vault keys override, but keep any extras from existing .env
    merged = {**existing, **keys_to_write}

    lines = [
        "# Managed by Pushkey",
        f"# Last synced: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# Do NOT commit this file to git!\n",
    ]
    for k in sorted(merged.keys()):
        lines.append(f"{k}={_format_env_value(merged[k])}")

    _atomic_write_text(env_path, "\n".join(lines) + "\n")
    _ensure_gitignore_env(project_dir)

    return True

# ═══════════════════════════════════════════════
# COLORS & STYLES
# ═══════════════════════════════════════════════

C = {
    # Backgrounds — OLED deep, layered depth
    "bg":      "#04070D",   # deepest — main canvas
    "bg2":     "#080D17",   # top bar, tab bar
    "bg3":     "#0C1420",   # input fields
    "bg4":     "#11202F",   # hover states
    "surface": "#09111D",   # cards, rows
    # Accent — security green (vault DNA: green = encrypted/safe/good)
    "accent":  "#059669",   # primary CTA, active state
    "accent2": "#047857",   # pressed / darker variant
    # Semantic
    "green":    "#10B981",  # success, healthy
    "green_bg": "#022C22",  # success backgrounds
    "amber":    "#F59E0B",  # warning, rotation due
    "amber_bg": "#451A03",  # warning backgrounds
    "red":      "#F87171",  # error, critical
    "red_bg":   "#3B0D0D",  # error backgrounds
    # Button base (distinct from surface)
    "btn":      "#0F1E30",
    "btn_hover":"#162840",
    # Text hierarchy — 4-stop scale
    "text":  "#DDE4EE",     # primary — high contrast
    "text2": "#7C8FA6",     # secondary / meta
    "text3": "#3D5166",     # tertiary / disabled
    # Borders — subtle blue-tinted for depth
    "border":  "#152238",
    "border2": "#1E3350",
}

FONT       = ("Segoe UI", 11)
FONT_SM    = ("Segoe UI", 10)
FONT_XS    = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 11)
FONT_MONO_SM = ("Consolas", 10)
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_H2    = ("Segoe UI", 14, "bold")
FONT_H3    = ("Segoe UI", 11, "bold")
FONT_BTN   = ("Segoe UI", 9, "bold")

CAT_COLORS = {
    "AI":       "#A78BFA",  # violet
    "Trading":  "#F59E0B",  # amber — money
    "Database": "#22D3EE",  # cyan
    "Cloud":    "#60A5FA",  # sky blue
    "Payment":  "#F472B6",  # pink
    "Comms":    "#34D399",  # mint
    "Security": "#059669",  # security green
    "Crypto":   "#FB923C",  # orange
    "General":  "#64748B",  # slate
}

# ═══════════════════════════════════════════════
# HELPER WIDGETS
# ═══════════════════════════════════════════════

def make_btn(parent, text, command, bg=None, fg=None, width=None):
    bg = bg or C["btn"]
    fg = fg or C["text2"]
    btn = tk.Button(parent, text=text, font=FONT_BTN, bg=bg, fg=fg,
                   relief="flat", cursor="hand2", command=command,
                   padx=10, pady=5,
                   activebackground=C["btn_hover"], activeforeground=C["text"],
                   borderwidth=0)
    if width:
        btn.config(width=width)
    btn.bind("<Enter>", lambda e, b=btn, ob=bg: b.config(bg=C["btn_hover"] if ob == C["btn"] else ob))
    btn.bind("<Leave>", lambda e, b=btn, ob=bg: b.config(bg=ob))
    return btn

def days_since(date_str):
    if not date_str: return float('inf')
    try:
        dt = datetime.fromisoformat(date_str)
        return (datetime.now() - dt).days
    except: return float('inf')

def health_status(key_info):
    age = days_since(key_info.get("rotated") or key_info.get("created"))
    provider = key_info.get("provider")
    threshold = 90
    if provider and provider in PROVIDERS:
        threshold = PROVIDERS[provider].get("rotation_days", 90)
    if age > threshold: return "critical"
    if age > threshold * 0.67: return "warning"
    return "healthy"

def health_color(status):
    return {"healthy": C["green"], "warning": C["amber"], "critical": C["red"]}.get(status, C["text3"])

# ═══════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════

class LoginFrame(tk.Frame):
    def __init__(self, master, on_login):
        super().__init__(master, bg=C["bg"])
        self.on_login = on_login
        self.is_new = not VAULT_FILE.exists()

        tk.Frame(self, bg=C["bg"], height=60).pack()

        # Brand lockup
        tk.Label(self, text="●", font=("Consolas", 36), bg=C["bg"], fg=C["accent"]).pack(pady=(0, 4))
        tk.Label(self, text="PUSHKEY", font=("Consolas", 26, "bold"), bg=C["bg"], fg=C["text"]).pack()
        tk.Label(self, text="encrypted key vault", font=("Segoe UI", 9),
                bg=C["bg"], fg=C["text3"]).pack(pady=(2, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=100, pady=24)

        sub = "create a master password to get started" if self.is_new else "enter master password to unlock"
        tk.Label(self, text=sub, font=("Segoe UI", 9), bg=C["bg"], fg=C["text3"]).pack(pady=(0, 12))
        
        frame = tk.Frame(self, bg=C["bg"])
        frame.pack()
        
        self.pw = tk.Entry(frame, show="●", font=("Consolas", 14), bg=C["bg3"], fg=C["text"],
                          insertbackground=C["text"], relief="flat", width=26, justify="center")
        self.pw.pack(ipady=10, pady=(0, 8))
        self.pw.focus_set()
        self.pw.bind("<Return>", lambda e: self.unlock())
        
        if self.is_new:
            self.pw2 = tk.Entry(frame, show="●", font=("Consolas", 14), bg=C["bg3"], fg=C["text"],
                               insertbackground=C["text"], relief="flat", width=26, justify="center")
            self.pw2.pack(ipady=10, pady=(0, 8))
            self.pw2.bind("<Return>", lambda e: self.unlock())
            tk.Label(frame, text="Re-enter to confirm", font=FONT_XS, bg=C["bg"], fg=C["text3"]).pack(pady=(0, 8))
        
        make_btn(frame, "Unlock" if not self.is_new else "Create Vault", self.unlock,
                bg=C["accent"], fg="white", width=22).pack(ipady=6)
        
        self.err = tk.Label(self, text="", font=FONT_SM, bg=C["bg"], fg=C["red"])
        self.err.pack(pady=(10, 0))
    
    def unlock(self):
        pw = self.pw.get().strip()
        if len(pw) < 6:
            self.err.config(text="Password must be at least 6 characters")
            return
        if self.is_new:
            if pw != self.pw2.get().strip():
                self.err.config(text="Passwords don't match")
                return
            ensure_vault_dir()
            save_vault({}, pw)
            self.on_login(pw, {})
        else:
            vault = load_vault(pw)
            if vault is None:
                self.err.config(text="Wrong password")
                self.pw.delete(0, tk.END)
                return
            self.on_login(pw, vault)

# ═══════════════════════════════════════════════
# MAIN APP SCREEN
# ═══════════════════════════════════════════════

class AppFrame(tk.Frame):
    def __init__(self, master, password, vault, on_lock):
        super().__init__(master, bg=C["bg"])
        self.password = password
        self.vault = vault
        self.on_lock = on_lock
        self.config = load_config()
        self.revealed = set()
        self._group_by = "file"
        self._collapsed_groups = set()
        self._bulk_select_vars = {}
        
        # ── Top bar ──
        top = tk.Frame(self, bg=C["bg2"], pady=2)
        top.pack(fill="x")
        # Brand mark with security-green accent dot
        brand = tk.Frame(top, bg=C["bg2"])
        brand.pack(side="left", padx=(12, 0), pady=6)
        tk.Label(brand, text="●", font=("Segoe UI", 10), bg=C["bg2"], fg=C["accent"]).pack(side="left", padx=(0, 6))
        tk.Label(brand, text="PUSHKEY", font=("Consolas", 13, "bold"), bg=C["bg2"], fg=C["text"]).pack(side="left")
        tk.Label(brand, text=" vault", font=("Segoe UI", 9), bg=C["bg2"], fg=C["text3"]).pack(side="left", pady=(2, 0))

        make_btn(top, "⚠ Lock", self.lock, bg=C["red_bg"], fg=C["red"]).pack(side="right", padx=(4, 12), pady=8)
        make_btn(top, "Password", self.change_master_password).pack(side="right", padx=2, pady=8)
        make_btn(top, "Export", self.export_vault).pack(side="right", padx=2, pady=8)
        make_btn(top, "Import", self.import_vault).pack(side="right", padx=2, pady=8)
        make_btn(top, "Template", self.show_template).pack(side="right", padx=2, pady=8)

        # Auto-lock timer (5 min inactivity)
        self._lock_timeout = 5 * 60 * 1000  # 5 minutes in ms
        self._lock_timer_id = None
        self._reset_lock_timer()
        self.bind_all("<Key>", lambda e: self._reset_lock_timer())
        self.bind_all("<Button>", lambda e: self._reset_lock_timer())
        
        # ── Notebook tabs ──
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)
        
        style = ttk.Style()
        style.theme_use('default')
        style.configure("TNotebook", background=C["bg2"], borderwidth=0, tabmargins=[0, 0, 0, 0])
        style.configure("TNotebook.Tab", background=C["bg2"], foreground=C["text3"],
                        padding=[18, 8], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", C["bg"])],
                  foreground=[("selected", C["accent"])])
        
        # Tab 1: Dashboard
        self.dash_frame = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(self.dash_frame, text=" Dashboard ")
        
        # Tab 2: Keys
        self.keys_frame = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(self.keys_frame, text=" All Keys ")
        
        # Tab 3: Projects
        self.proj_frame = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(self.proj_frame, text=" Projects ")
        
        self.render_all()
    
    def save(self):
        save_vault(self.vault, self.password)
        save_config(self.config)
    
    def lock(self):
        self.revealed.clear()
        if self._lock_timer_id:
            self.after_cancel(self._lock_timer_id)
        self.on_lock()

    def _reset_lock_timer(self):
        if self._lock_timer_id:
            self.after_cancel(self._lock_timer_id)
        self._lock_timer_id = self.after(self._lock_timeout, self.lock)

    def export_vault(self):
        path = filedialog.asksaveasfilename(
            title="Export encrypted vault",
            defaultextension=".pushkey-backup",
            filetypes=[("Pushkey Backup", "*.pushkey-backup"), ("All files", "*.*")])
        if not path:
            return
        data = json.dumps({"vault": self.vault, "config": self.config}, indent=2)
        encrypted = encrypt_data(data, self.password)
        Path(path).write_bytes(encrypted)
        messagebox.showinfo("Exported", f"Vault exported to:\n{path}\n\nYou'll need your master password to import.")

    def import_vault(self):
        path = filedialog.askopenfilename(
            title="Import encrypted vault backup",
            filetypes=[("Pushkey Backup", "*.pushkey-backup"), ("All files", "*.*")])
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            decrypted = decrypt_data(raw, self.password)
            data = json.loads(decrypted)
        except Exception:
            messagebox.showerror("Failed", "Could not decrypt. Wrong password or corrupted file.")
            return
        imported_vault = data.get("vault", {})
        imported_config = data.get("config", {})
        new_keys = [k for k in imported_vault if k not in self.vault]
        updated = [k for k in imported_vault if k in self.vault and imported_vault[k]["value"] != self.vault[k]["value"]]
        msg = f"Found {len(imported_vault)} keys.\n{len(new_keys)} new, {len(updated)} different values.\n\nMerge into current vault?"
        if not messagebox.askyesno("Import", msg):
            return
        self.vault.update(imported_vault)
        for proj, info in imported_config.get("projects", {}).items():
            if proj not in self.config.get("projects", {}):
                self.config.setdefault("projects", {})[proj] = info
        self.save()
        self.render_all()
        messagebox.showinfo("Imported", f"Merged {len(new_keys)} new + {len(updated)} updated keys.")

    def render_all(self):
        self.render_dashboard()
        self.render_keys()
        self.render_projects()
    
    # ═══════════════════════════════════════════
    # DASHBOARD TAB
    # ═══════════════════════════════════════════
    
    def render_dashboard(self):
        for w in self.dash_frame.winfo_children(): w.destroy()
        
        canvas = tk.Canvas(self.dash_frame, bg=C["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self.dash_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _dash_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_dash_win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        
        pad = tk.Frame(inner, bg=C["bg"])
        pad.pack(fill="x", padx=20, pady=(16, 0))
        
        keys = list(self.vault.items())
        total = len(keys)
        healthy = sum(1 for _, v in keys if health_status(v) == "healthy")
        warning = sum(1 for _, v in keys if health_status(v) == "warning")
        critical = sum(1 for _, v in keys if health_status(v) == "critical")
        projects = len(self.config.get("projects", {}))
        
        # Stats row
        stats_frame = tk.Frame(pad, bg=C["bg"])
        stats_frame.pack(fill="x", pady=(0, 16))
        
        for label, val, color in [
            ("Total keys", str(total), C["text"]),
            ("Healthy", str(healthy), C["green"]),
            ("Needs rotation", str(warning + critical), C["amber"] if warning + critical > 0 else C["green"]),
            ("Projects linked", str(projects), C["accent"]),
        ]:
            card = tk.Frame(stats_frame, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=label, font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(8, 0))
            tk.Label(card, text=val, font=("Segoe UI", 22, "bold"), bg=C["surface"], fg=color).pack(anchor="w", padx=10, pady=(0, 8))
        
        # Action needed section
        if critical + warning > 0:
            tk.Label(pad, text="ACTION NEEDED", font=FONT_XS, bg=C["bg"], fg=C["red"]).pack(anchor="w", pady=(8, 4))
            
            for name, info in sorted(keys, key=lambda x: days_since(x[1].get("rotated") or x[1].get("created")), reverse=True):
                status = health_status(info)
                if status in ("critical", "warning"):
                    age = days_since(info.get("rotated") or info.get("created"))
                    provider = info.get("provider")
                    prov_data = PROVIDERS.get(provider, {})
                    
                    row = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
                    row.pack(fill="x", pady=2)
                    
                    # Health dot
                    dot = tk.Canvas(row, width=12, height=12, bg=C["surface"], highlightthickness=0)
                    dot.pack(side="left", padx=(10, 6), pady=10)
                    dot.create_oval(2, 2, 10, 10, fill=health_color(status), outline="")
                    
                    info_frame = tk.Frame(row, bg=C["surface"])
                    info_frame.pack(side="left", fill="x", expand=True, pady=8)
                    tk.Label(info_frame, text=name, font=FONT_MONO, bg=C["surface"], fg=C["text"]).pack(anchor="w")
                    
                    msg = f"{age} days old"
                    if status == "critical": msg += " — rotate immediately"
                    else: msg += " — rotate soon"
                    tk.Label(info_frame, text=msg, font=FONT_XS, bg=C["surface"], fg=health_color(status)).pack(anchor="w")
                    
                    if prov_data.get("url"):
                        make_btn(row, "Open " + (provider or "provider"),
                                lambda u=prov_data["url"]: webbrowser.open(u),
                                bg=C["bg3"]).pack(side="right", padx=8, pady=8)
        
        # All keys health
        tk.Label(pad, text="ALL KEYS", font=FONT_XS, bg=C["bg"], fg=C["text3"]).pack(anchor="w", pady=(16, 4))
        
        if not keys:
            tk.Label(pad, text="No keys yet. Go to 'All Keys' tab to add your first one.",
                    font=FONT, bg=C["bg"], fg=C["text3"]).pack(anchor="w", pady=20)
            return
        
        for name, info in sorted(keys, key=lambda x: x[0]):
            status = health_status(info)
            age = days_since(info.get("rotated") or info.get("created"))
            provider = info.get("provider", "")

            row = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1,
                           cursor="hand2")
            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            dot = tk.Canvas(row, width=10, height=10, bg=C["surface"], highlightthickness=0, cursor="hand2")
            dot.pack(side="left", padx=(10, 6), pady=8)
            dot.create_oval(1, 1, 9, 9, fill=health_color(status), outline="")
            dot.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            cat = info.get("category", "General")
            cat_color = CAT_COLORS.get(cat, C["text3"])
            age_text = f"{age}d" if age != float('inf') else "?"

            lbl_name = tk.Label(row, text=name, font=FONT_MONO_SM, bg=C["surface"], fg=C["text"], width=24, anchor="w", cursor="hand2")
            lbl_name.pack(side="left")
            lbl_name.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            lbl_cat = tk.Label(row, text=cat, font=FONT_XS, bg=C["surface"], fg=cat_color, cursor="hand2")
            lbl_cat.pack(side="left", padx=8)
            lbl_cat.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            lbl_age = tk.Label(row, text=age_text, font=FONT_XS, bg=C["surface"], fg=health_color(status), width=6, cursor="hand2")
            lbl_age.pack(side="right", padx=10)
            lbl_age.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
    
    # ═══════════════════════════════════════════
    # ALL KEYS TAB
    # ═══════════════════════════════════════════
    
    def render_keys(self):
        for w in self.keys_frame.winfo_children(): w.destroy()
        
        # Add key form at top
        form = tk.Frame(self.keys_frame, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        form.pack(fill="x", padx=16, pady=(12, 0))
        
        tk.Label(form, text="Add or rotate a key", font=FONT_H3, bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=12, pady=(10, 8))
        
        input_row = tk.Frame(form, bg=C["surface"])
        input_row.pack(fill="x", padx=12, pady=(0, 10))
        
        # Name
        nf = tk.Frame(input_row, bg=C["surface"])
        nf.pack(side="left", padx=(0, 6))
        tk.Label(nf, text="NAME", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w")
        self.add_name = tk.Entry(nf, font=FONT_MONO_SM, bg=C["bg3"], fg=C["text"],
                                 insertbackground=C["text"], relief="flat", width=20)
        self.add_name.pack(ipady=5)
        
        # Value
        vf = tk.Frame(input_row, bg=C["surface"])
        vf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(vf, text="VALUE", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w")
        self.add_value = tk.Entry(vf, font=FONT_MONO_SM, bg=C["bg3"], fg=C["text"], show="●",
                                  insertbackground=C["text"], relief="flat")
        self.add_value.pack(fill="x", ipady=5)
        
        # Category
        cf = tk.Frame(input_row, bg=C["surface"])
        cf.pack(side="left", padx=(0, 6))
        tk.Label(cf, text="CATEGORY", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w")
        self.add_cat = ttk.Combobox(cf, values=["General", "Trading", "AI", "Database", "Cloud", "Payment"],
                                     state="readonly", width=10, font=FONT_XS)
        self.add_cat.set("General")
        self.add_cat.pack(ipady=3)
        
        make_btn(input_row, "+ Add", self.add_key, bg=C["green_bg"], fg=C["green"]).pack(side="left", pady=(14, 0), ipady=3)
        make_btn(input_row, "📤 Bulk Upload", self.bulk_upload_keys, bg=C["accent"], fg="white").pack(side="left", padx=(4, 0), pady=(14, 0), ipady=3)
        
        # Key list
        canvas = tk.Canvas(self.keys_frame, bg=C["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self.keys_frame, orient="vertical", command=canvas.yview)
        self.keys_inner = tk.Frame(canvas, bg=C["bg"])
        self.keys_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _keys_win = canvas.create_window((0, 0), window=self.keys_inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_keys_win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self._render_key_rows()
    
    def _render_key_rows(self):
        for w in self.keys_inner.winfo_children(): w.destroy()
        self._bulk_select_vars = {}

        if not self.vault:
            tk.Label(self.keys_inner, text="No keys yet. Add your first key above.",
                    font=FONT, bg=C["bg"], fg=C["text3"]).pack(pady=40)
            return

        # Toolbar: bulk actions + group toggle
        toolbar = tk.Frame(self.keys_inner, bg=C["bg"])
        toolbar.pack(fill="x", padx=16, pady=(8, 2))
        make_btn(toolbar, "☑ All", self._select_all_keys, width=6).pack(side="left", padx=(0, 2))
        make_btn(toolbar, "☐ None", self._deselect_all_keys, width=6).pack(side="left", padx=(0, 8))
        make_btn(toolbar, "🗑 Delete Selected", self.bulk_delete_keys,
                bg=C["red_bg"], fg="#FCA5A5").pack(side="left")

        # Group toggle
        by_file = self._group_by == "file"
        make_btn(toolbar, "📁 By File" if not by_file else "By Category",
                self._toggle_group_by).pack(side="right")

        # Build groups
        groups = {}
        for name, info in sorted(self.vault.items()):
            if self._group_by == "file":
                key = info.get("source_file") or "✏ Manual"
            else:
                key = info.get("category", "General")
            groups.setdefault(key, []).append((name, info))

        for group_key in sorted(groups.keys()):
            items = groups[group_key]
            collapsed = group_key in self._collapsed_groups

            # Group header
            hdr = tk.Frame(self.keys_inner, bg=C["bg"])
            hdr.pack(fill="x", padx=16, pady=(10, 2))

            if self._group_by == "file":
                icon = "📁 " if group_key != "✏ Manual" else ""
                label_text = f"{'▶' if collapsed else '▼'}  {icon}{group_key}  ({len(items)})"
                color = C["accent"]
            else:
                label_text = f"{'▶' if collapsed else '▼'}  {group_key.upper()}  ({len(items)})"
                color = CAT_COLORS.get(group_key, C["text3"])

            lbl = tk.Label(hdr, text=label_text, font=FONT_XS, bg=C["bg"], fg=color, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, gk=group_key: self._toggle_group(gk))

            if not collapsed:
                for name, info in items:
                    self._render_single_key(name, info)

    def _toggle_group_by(self):
        self._group_by = "category" if self._group_by == "file" else "file"
        self._collapsed_groups.clear()
        self._render_key_rows()

    def _toggle_group(self, group_key):
        if group_key in self._collapsed_groups:
            self._collapsed_groups.discard(group_key)
        else:
            self._collapsed_groups.add(group_key)
        self._render_key_rows()
    
    def _render_single_key(self, name, info):
        status = health_status(info)
        revealed = name in self.revealed
        provider = info.get("provider")
        prov_data = PROVIDERS.get(provider, {})
        
        row = tk.Frame(self.keys_inner, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", padx=16, pady=1)

        # Bulk select checkbox
        sel_var = tk.BooleanVar(value=False)
        self._bulk_select_vars[name] = sel_var
        tk.Checkbutton(row, variable=sel_var, bg=C["surface"], relief="flat",
                       selectcolor=C["bg3"], activebackground=C["surface"],
                       borderwidth=0, highlightthickness=0).pack(side="left", padx=(6, 0))

        # Health dot
        dot = tk.Canvas(row, width=10, height=10, bg=C["surface"], highlightthickness=0)
        dot.pack(side="left", padx=(4, 6), pady=10)
        dot.create_oval(1, 1, 9, 9, fill=health_color(status), outline="")
        
        # Info (click anywhere on info area to open detail popup)
        info_frame = tk.Frame(row, bg=C["surface"], cursor="hand2")
        info_frame.pack(side="left", fill="x", expand=True, pady=6)
        info_frame.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        name_row = tk.Frame(info_frame, bg=C["surface"], cursor="hand2")
        name_row.pack(anchor="w")
        name_row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        lbl_n = tk.Label(name_row, text=name, font=("Consolas", 10, "bold"), bg=C["surface"], fg=C["text"], cursor="hand2")
        lbl_n.pack(side="left")
        lbl_n.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        if provider:
            lbl_p = tk.Label(name_row, text=f" ({provider})", font=FONT_XS, bg=C["surface"],
                    fg=CAT_COLORS.get(info.get("category", "General"), C["text3"]), cursor="hand2")
            lbl_p.pack(side="left")
            lbl_p.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        meta_parts = []
        if info.get("source_file"): meta_parts.append(f"📁 {info['source_file']}")
        if info.get("created"): meta_parts.append(f"Added {info['created'][:10]}")
        if info.get("rotated"): meta_parts.append(f"Rotated {info['rotated'][:10]}")
        if info.get("rotation_count", 0) > 0: meta_parts.append(f"{info['rotation_count']}x rotated")

        lbl_meta = tk.Label(info_frame, text="  ·  ".join(meta_parts) if meta_parts else "",
                font=FONT_XS, bg=C["surface"], fg=C["text3"], cursor="hand2")
        lbl_meta.pack(anchor="w")
        lbl_meta.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
        
        # Value display
        val = info["value"]
        display = val if revealed else val[:4] + "●" * min(16, len(val) - 8) + val[-4:] if len(val) > 8 else "●" * len(val)
        tk.Label(row, text=display, font=FONT_MONO_SM, bg=C["surface"],
                fg=C["green"] if revealed else C["text3"], width=26, anchor="w").pack(side="left", padx=4)
        
        # Buttons
        btns = tk.Frame(row, bg=C["surface"])
        btns.pack(side="right", padx=6, pady=4)
        
        # Provider link button
        if prov_data.get("url"):
            make_btn(btns, "↗", lambda u=prov_data["url"]: webbrowser.open(u), width=3).pack(side="left", padx=1)
        
        # Show/hide
        make_btn(btns, "Eye" if not revealed else "Hide",
                lambda n=name: self.toggle_reveal(n), width=5).pack(side="left", padx=1)
        
        # Copy
        make_btn(btns, "Copy", lambda v=val: self.copy_key(v), width=5).pack(side="left", padx=1)
        
        # Rotate
        make_btn(btns, "Rotate", lambda n=name: self.rotate_key(n),
                bg=C["amber_bg"], fg=C["amber"], width=6).pack(side="left", padx=1)

        # History
        if info.get("history"):
            make_btn(btns, "History", lambda n=name: self.show_history(n),
                    width=7).pack(side="left", padx=1)

        # View source (if uploaded from file)
        if info.get("source_file"):
            make_btn(btns, "Source", lambda n=name: self.show_source(n),
                    width=6).pack(side="left", padx=1)

        # Delete
        make_btn(btns, "Del", lambda n=name: self.delete_key(n),
                bg=C["red_bg"], fg="#FCA5A5", width=4).pack(side="left", padx=1)
    
    def _select_all_keys(self):
        for var in self._bulk_select_vars.values():
            var.set(True)

    def _deselect_all_keys(self):
        for var in self._bulk_select_vars.values():
            var.set(False)

    def bulk_delete_keys(self):
        selected = [n for n, var in self._bulk_select_vars.items() if var.get()]
        if not selected:
            messagebox.showinfo("Nothing selected", "Check the boxes next to the keys you want to delete first.")
            return
        names_preview = "\n".join(selected[:10])
        if len(selected) > 10:
            names_preview += f"\n... and {len(selected) - 10} more"
        if not messagebox.askyesno("Delete keys",
                f"Permanently delete {len(selected)} key(s)?\n\n{names_preview}"):
            return
        for name in selected:
            del self.vault[name]
            self.revealed.discard(name)
            log_event(f"bulk delete: removed {name}")
        self.save()
        self.render_all()
        messagebox.showinfo("Deleted", f"Deleted {len(selected)} key(s).")

    def add_key(self):
        name = self.add_name.get().strip().upper().replace(" ", "_")
        value = self.add_value.get().strip()
        category = self.add_cat.get()
        
        if not name or not value:
            messagebox.showwarning("Missing info", "Enter both a key name and value")
            return
        
        provider = detect_provider(name, value)
        now = datetime.now().isoformat()
        
        if name in self.vault:
            if not messagebox.askyesno("Rotate key?",
                f"'{name}' already exists.\n\nReplace with new value?\n(Old value will be saved as backup)"):
                return
            old_val = self.vault[name]["value"]
            self.vault[name].setdefault("history", [])
            self.vault[name]["history"].insert(0, {"value": old_val, "retired": now})
            self.vault[name]["history"] = self.vault[name]["history"][:10]  # keep last 10
            self.vault[name]["previous"] = old_val
            self.vault[name]["value"] = value
            self.vault[name]["rotated"] = now
            self.vault[name]["rotation_count"] = self.vault[name].get("rotation_count", 0) + 1
            msg = f"{name} rotated successfully"
        else:
            self.vault[name] = {
                "value": value, "category": category, "provider": provider,
                "created": now, "rotated": None, "rotation_count": 0, "previous": None,
            }
            msg = f"{name} added"
        
        self.save()

        # Auto-inject into all linked projects that use this key
        injected, errors = self._auto_inject_key(name)
        if injected:
            msg += f" and synced to {injected} project(s)"
        if errors:
            msg += f"\n\n⚠ Sync failed for {len(errors)} project(s):\n" + "\n".join(errors)

        self.add_name.delete(0, tk.END)
        self.add_value.delete(0, tk.END)
        self.render_all()
        messagebox.showinfo("Done", msg)
    
    def bulk_upload_keys(self):
        paths = filedialog.askopenfilenames(
            title="Select text files with keys",
            filetypes=[("Env / text files", "*.env *.txt *.pushkey"), ("All files", "*.*")])
        if not paths:
            return

        parsed_entries = []
        errors = []

        for path in paths:
            basename = os.path.basename(path)
            try:
                file_entries, file_errors = _parse_env_file(path)
                for err in file_errors:
                    errors.append(f"{basename}: {err}")
                for fe in file_entries:
                    name = fe['name']
                    value = fe['value']
                    provider = detect_provider(name, value)
                    is_new = name not in self.vault
                    parsed_entries.append({
                        "name": name,
                        "value": value,
                        "provider": provider,
                        "is_new": is_new,
                        "file": basename,
                        "line": fe['line'],
                        "raw_line": fe.get('raw_line', ''),
                        "secret": fe.get('secret', False),
                    })
            except Exception as e:
                errors.append(f"{basename}: {str(e)}")

        if not parsed_entries:
            msg = "No valid keys found in the selected files."
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    msg += f"\n... and {len(errors) - 5} more"
            messagebox.showwarning("No keys parsed", msg)
            return

        # Show preview dialog
        confirmed = self._show_bulk_preview_dialog(parsed_entries, errors)
        if not confirmed:
            return

        # Commit to vault
        added = []
        now = datetime.now().isoformat()
        for entry in confirmed:
            name = entry["name"]
            value = entry["value"]
            provider = entry["provider"]

            # Use source metadata from the entry itself (from preview dialog)
            source_file = entry.get("file")
            source_line = entry.get("line")
            source_raw = entry.get("raw_line", "")

            if name in self.vault:
                old_val = self.vault[name]["value"]
                self.vault[name].setdefault("history", [])
                self.vault[name]["history"].insert(0, {"value": old_val, "retired": now})
                self.vault[name]["history"] = self.vault[name]["history"][:10]
                self.vault[name]["previous"] = old_val
                self.vault[name]["value"] = value
                self.vault[name]["rotated"] = now
                self.vault[name]["rotation_count"] = self.vault[name].get("rotation_count", 0) + 1
                # Also track source for rotations from bulk import
                if source_file:
                    self.vault[name]["source_file"] = source_file
                    self.vault[name]["source_line"] = source_line
                    self.vault[name]["source_raw"] = source_raw
                    self.vault[name]["imported_at"] = now
                if entry.get("secret"):
                    self.vault[name]["secret"] = True
                added.append(f"{name} (rotated)")
            else:
                category = self.add_cat.get() if hasattr(self, 'add_cat') else "General"
                self.vault[name] = {
                    "value": value, "category": category, "provider": provider,
                    "created": now, "rotated": None, "rotation_count": 0, "previous": None,
                    "source_file": source_file,
                    "source_line": source_line,
                    "source_raw": source_raw,
                    "imported_at": now,
                    "secret": entry.get("secret", False),
                }
                log_event(f"bulk: imported {name} from {source_file}:{source_line}")
                added.append(name)

        self.save()
        self._refresh_all_projects()
        injected, _ = self._auto_inject_keys_bulk([e["name"] for e in confirmed])

        msg = f"✓ Imported {len(added)} key(s)"
        if injected:
            msg += f" and synced to {injected} project(s)"

        self.render_all()
        messagebox.showinfo("Bulk Upload Complete", msg)

    def _show_bulk_preview_dialog(self, parsed_entries, errors):
        """Show a table of parsed keys. User can uncheck, edit names, confirm import.
        Returns list of entries to import, or None if cancelled.
        """
        win = tk.Toplevel(self)
        win.title("Review Keys Before Import")
        win.geometry("700x500")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"Preview: {len(parsed_entries)} key(s) parsed",
                font=FONT_H2, bg=C["bg2"], fg=C["text"]).pack(pady=(12, 4), padx=12, anchor="w")
        if errors:
            tk.Label(win, text=f"⚠ {len(errors)} parsing error(s) (some keys skipped)",
                    font=FONT_XS, bg=C["bg2"], fg=C["amber"]).pack(padx=12, anchor="w", pady=(0, 8))

        # Scrollable table
        canvas = tk.Canvas(win, bg=C["bg"], highlightthickness=0, height=300)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        checks = {}
        for entry in parsed_entries:
            row = tk.Frame(inner, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            row.pack(fill="x", padx=2, pady=1)

            var = tk.BooleanVar(value=True)
            checks[entry["name"]] = var
            cb = tk.Checkbutton(row, variable=var, font=FONT_XS, bg=C["surface"], fg=C["text"],
                               selectcolor=C["bg3"], activebackground=C["surface"], activeforeground=C["text"])
            cb.pack(side="left", padx=(4, 2), pady=4)

            # Key name (editable)
            name_frame = tk.Frame(row, bg=C["surface"])
            name_frame.pack(side="left", fill="x", expand=True, padx=2, pady=4)
            tk.Label(name_frame, text=entry["name"], font=FONT_MONO_SM, bg=C["surface"], fg=C["text"], width=24).pack(side="left")

            # Provider badge
            prov = entry["provider"] or "?"
            prov_color = CAT_COLORS.get(PROVIDERS.get(prov, {}).get("category", "General"), C["text3"])
            tk.Label(name_frame, text=prov, font=FONT_XS, bg=C["surface"], fg=prov_color, width=12).pack(side="left", padx=4)

            # Status (new/rotate)
            status = "new" if entry["is_new"] else "rotate"
            status_color = C["green"] if entry["is_new"] else C["amber"]
            tk.Label(name_frame, text=status, font=FONT_XS, bg=C["surface"], fg=status_color).pack(side="left")

            # Secret badge
            if entry.get("secret"):
                tk.Label(name_frame, text="🔒", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(side="left", padx=(4, 0))

        canvas.pack(side="left", fill="both", expand=True, padx=12, pady=8)
        scrollbar.pack(side="right", fill="y")

        # Buttons
        btn_frame = tk.Frame(win, bg=C["bg2"])
        btn_frame.pack(fill="x", padx=12, pady=8)

        def import_selected():
            selected = [e for e in parsed_entries if checks[e["name"]].get()]
            win.selected = selected
            win.destroy()

        make_btn(btn_frame, f"✓ Import {len(parsed_entries)} selected",
                import_selected, bg=C["green_bg"], fg=C["green"]).pack(side="left", padx=(0, 4), ipady=4)
        make_btn(btn_frame, "Cancel", lambda: (setattr(win, 'selected', None), win.destroy())).pack(side="left", ipady=4)

        win.selected = None
        self.wait_window(win)
        return win.selected

    def _auto_inject_keys_bulk(self, key_names):
        """Push updated keys to all projects. Returns (count, errors)."""
        count = 0
        errors = []
        for proj_name, proj_info in self.config.get("projects", {}).items():
            proj_keys = proj_info.get("keys", [])
            relevant_keys = [k for k in key_names if k in proj_keys or not proj_keys]
            if relevant_keys:
                path = proj_info.get("path")
                if path and os.path.isdir(path):
                    try:
                        inject_env_file(path, self.vault, proj_keys if proj_keys else None)
                        count += 1
                    except Exception as e:
                        errors.append(f"{proj_name}: {e}")
        return count, errors

    def _auto_inject_key(self, key_name):
        """Push updated key to all projects that use it. Returns (count, errors)."""
        count = 0
        errors = []
        for proj_name, proj_info in self.config.get("projects", {}).items():
            proj_keys = proj_info.get("keys", [])
            if key_name in proj_keys or not proj_keys:  # empty = all keys
                path = proj_info.get("path")
                if path and os.path.isdir(path):
                    keys_to_write = proj_keys if proj_keys else None
                    try:
                        inject_env_file(path, self.vault, keys_to_write)
                        count += 1
                    except Exception as e:
                        msg = f"{proj_name}: {e}"
                        log_event(f"env inject failed for {path}: {e}")
                        errors.append(msg)
        return count, errors
    
    def toggle_reveal(self, name):
        if name in self.revealed:
            self.revealed.discard(name)
        else:
            self.revealed.add(name)
            self.after(10000, lambda: (self.revealed.discard(name), self._render_key_rows()))
        self._render_key_rows()
    
    def copy_key(self, value):
        self.clipboard_clear()
        self.clipboard_append(value)
        self.after(30000, lambda: self.clipboard_clear())
    
    def delete_key(self, name):
        if messagebox.askyesno("Delete?", f"Delete '{name}'?\nThis cannot be undone."):
            del self.vault[name]
            self.revealed.discard(name)
            self.save()
            self.render_all()

    def rotate_key(self, name):
        """Guided rotation: open provider page, prompt for new value, archive old, sync."""
        info = self.vault.get(name)
        if not info:
            return
        provider = info.get("provider")
        prov_data = PROVIDERS.get(provider, {})

        # Open provider dashboard
        if prov_data.get("url"):
            webbrowser.open(prov_data["url"])

        # Prompt for new value
        win = tk.Toplevel(self)
        win.title(f"Rotate {name}")
        win.geometry("480x220")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"Rotate {name}", font=FONT_H2, bg=C["bg2"], fg=C["text"]).pack(pady=(16, 4))
        if provider:
            tk.Label(win, text=f"{provider} dashboard opened in browser — copy your new key",
                    font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack()

        tk.Label(win, text="PASTE NEW KEY VALUE", font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w", padx=20, pady=(16, 2))
        new_val = tk.Entry(win, font=FONT_MONO, bg=C["bg3"], fg=C["text"],
                          insertbackground=C["text"], relief="flat", width=50)
        new_val.pack(padx=20, ipady=6)
        new_val.focus_set()

        def do_rotate():
            val = new_val.get().strip()
            if not val:
                messagebox.showwarning("Empty", "Paste the new key value")
                return
            now = datetime.now().isoformat()
            old_val = info["value"]
            info.setdefault("history", [])
            info["history"].insert(0, {"value": old_val, "retired": now})
            info["history"] = info["history"][:10]
            info["previous"] = old_val
            info["value"] = val
            info["rotated"] = now
            info["rotation_count"] = info.get("rotation_count", 0) + 1
            self.save()
            injected, errors = self._auto_inject_key(name)
            win.destroy()
            self.render_all()
            msg = f"{name} rotated"
            if injected:
                msg += f" and synced to {injected} project(s)"
            if errors:
                msg += f"\n\n⚠ Sync failed for {len(errors)} project(s):\n" + "\n".join(errors)
            messagebox.showinfo("Rotated", msg)

        new_val.bind("<Return>", lambda e: do_rotate())
        make_btn(win, "Save & Sync", do_rotate, bg=C["green_bg"], fg=C["green"], width=18).pack(pady=16)

    def show_source(self, name):
        """Show the source file and raw line for an uploaded key."""
        info = self.vault.get(name, {})
        source_file = info.get("source_file")
        source_line = info.get("source_line")
        source_raw = info.get("source_raw", "")
        imported_at = info.get("imported_at", "?")

        # Debug: log what we found
        log_event(f"show_source({name}): file={source_file}, line={source_line}, raw={source_raw[:30] if source_raw else 'None'}")

        if not source_file:
            messagebox.showinfo("No source", f"Key '{name}' was added manually, not from bulk upload.")
            return

        win = tk.Toplevel(self)
        win.title(f"Source: {name}")
        win.geometry("550x280")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"Source Information — {name}", font=FONT_H2,
                bg=C["bg2"], fg=C["text"]).pack(pady=(12, 8), padx=12, anchor="w")

        # File info
        info_frame = tk.Frame(win, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        info_frame.pack(fill="x", padx=12, pady=(0, 8))

        tk.Label(info_frame, text="FILE", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        tk.Label(info_frame, text=f"{source_file}:{source_line}", font=FONT_MONO_SM,
                bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=10, pady=(0, 6))

        tk.Label(info_frame, text="IMPORTED", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        tk.Label(info_frame, text=imported_at[:16].replace("T", " "), font=FONT_MONO_SM,
                bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=10, pady=(0, 6))

        # Raw line
        tk.Label(win, text="ORIGINAL LINE (before parsing)", font=FONT_XS,
                bg=C["bg2"], fg=C["text3"]).pack(anchor="w", padx=12, pady=(8, 2))

        raw_frame = tk.Frame(win, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        raw_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        raw_text = tk.Text(raw_frame, font=FONT_MONO, bg=C["bg3"], fg=C["text"],
                          height=6, width=60, wrap="word", relief="flat", state="normal")
        raw_text.pack(fill="both", expand=True, padx=8, pady=8)
        raw_text.insert("1.0", source_raw or "(no data)")
        raw_text.config(state="disabled")

        make_btn(win, "Close", win.destroy, width=12).pack(pady=8)

    def show_history(self, name):
        """Show previous values for a key."""
        info = self.vault.get(name, {})
        history = info.get("history", [])
        if not history:
            messagebox.showinfo("No history", f"No rotation history for {name}")
            return

        win = tk.Toplevel(self)
        win.title(f"History: {name}")
        win.geometry("520x400")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"Rotation History — {name}", font=FONT_H2,
                bg=C["bg2"], fg=C["text"]).pack(pady=(12, 4))
        tk.Label(win, text=f"{len(history)} previous value(s) stored", font=FONT_XS,
                bg=C["bg2"], fg=C["text3"]).pack(pady=(0, 12))

        frame = tk.Frame(win, bg=C["bg2"])
        frame.pack(fill="both", expand=True, padx=16)

        for i, entry in enumerate(history):
            row = tk.Frame(frame, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            row.pack(fill="x", pady=2)

            retired = entry.get("retired", "?")[:16].replace("T", " ")
            tk.Label(row, text=f"#{i+1}  retired {retired}", font=FONT_XS,
                    bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))

            val = entry["value"]
            masked = val[:4] + "●" * min(12, len(val) - 8) + val[-4:] if len(val) > 8 else "●" * len(val)
            lbl = tk.Label(row, text=masked, font=FONT_MONO_SM, bg=C["surface"], fg=C["text2"])
            lbl.pack(anchor="w", padx=10, pady=(0, 6))

            make_btn(row, "Copy", lambda v=val: (self.clipboard_clear(), self.clipboard_append(v),
                    self.after(30000, self.clipboard_clear)),
                    width=5).pack(side="right", padx=8, pady=6)

        make_btn(win, "Close", win.destroy, width=12).pack(pady=12)

    def change_master_password(self):
        """Change master password by re-encrypting the vault."""
        win = tk.Toplevel(self)
        win.title("Change Master Password")
        win.geometry("400x280")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="Change Master Password", font=FONT_H2,
                bg=C["bg2"], fg=C["text"]).pack(pady=(16, 12))

        fields = {}
        for label_text, key in [("CURRENT PASSWORD", "current"), ("NEW PASSWORD", "new"), ("CONFIRM NEW", "confirm")]:
            tk.Label(win, text=label_text, font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w", padx=24)
            e = tk.Entry(win, show="●", font=FONT_MONO_SM, bg=C["bg3"], fg=C["text"],
                        insertbackground=C["text"], relief="flat", width=36)
            e.pack(padx=24, ipady=5, pady=(0, 6))
            fields[key] = e

        err = tk.Label(win, text="", font=FONT_XS, bg=C["bg2"], fg=C["red"])
        err.pack()

        def do_change():
            current = fields["current"].get()
            new_pw = fields["new"].get().strip()
            confirm = fields["confirm"].get().strip()

            if current != self.password:
                err.config(text="Current password is wrong")
                return
            if len(new_pw) < 6:
                err.config(text="New password must be at least 6 characters")
                return
            if new_pw != confirm:
                err.config(text="New passwords don't match")
                return

            self.password = new_pw
            save_vault(self.vault, self.password)
            win.destroy()
            messagebox.showinfo("Done", "Master password changed. Vault re-encrypted.")

        make_btn(win, "Change Password", do_change, bg=C["accent"], fg="white", width=20).pack(pady=12)

    # ═══════════════════════════════════════════
    # KEY DETAIL POPUP
    # ═══════════════════════════════════════════

    def show_key_detail(self, name):
        info = self.vault.get(name, {})
        if not info:
            return

        win = tk.Toplevel(self)
        win.title(f"Key Details — {name}")
        win.geometry("600x580")
        win.minsize(480, 400)
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        # Header
        header = tk.Frame(win, bg=C["bg3"])
        header.pack(fill="x")

        status = health_status(info)
        dot = tk.Canvas(header, width=12, height=12, bg=C["bg3"], highlightthickness=0)
        dot.pack(side="left", padx=(16, 6), pady=16)
        dot.create_oval(2, 2, 10, 10, fill=health_color(status), outline="")

        tk.Label(header, text=name, font=FONT_H2, bg=C["bg3"], fg=C["text"]).pack(side="left", pady=16)

        provider = info.get("provider")
        if provider:
            cat = info.get("category", "General")
            tk.Label(header, text=f"  {provider}", font=FONT_SM,
                    bg=C["bg3"], fg=CAT_COLORS.get(cat, C["text3"])).pack(side="left")

        # Scrollable body
        canvas = tk.Canvas(win, bg=C["bg2"], highlightthickness=0)
        sb = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg2"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_wid, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        pad = tk.Frame(inner, bg=C["bg2"])
        pad.pack(fill="x", padx=16, pady=12)

        def info_field(label, value, mono=False, fg=None):
            f = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=label, font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(f, text=value or "—", font=FONT_MONO_SM if mono else FONT_SM,
                    bg=C["surface"], fg=fg or C["text"], wraplength=520, justify="left").pack(anchor="w", padx=10, pady=(0, 6))

        # Value row with copy
        val = info["value"]
        revealed = name in self.revealed
        masked = val[:4] + "●" * min(20, max(0, len(val) - 8)) + val[-4:] if len(val) > 8 else "●" * len(val)
        vf = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        vf.pack(fill="x", pady=2)
        tk.Label(vf, text="VALUE", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        vrow = tk.Frame(vf, bg=C["surface"])
        vrow.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(vrow, text=val if revealed else masked, font=FONT_MONO_SM, bg=C["surface"],
                fg=C["green"] if revealed else C["text3"]).pack(side="left")
        make_btn(vrow, "Copy", lambda v=val: self.copy_key(v), width=5).pack(side="right", padx=(4, 0))
        make_btn(vrow, "Hide" if revealed else "Reveal",
                lambda n=name: (self.toggle_reveal(n), win.destroy(), self.show_key_detail(n)),
                width=6).pack(side="right", padx=4)

        # Metadata fields
        info_field("CATEGORY", info.get("category", "General"))
        info_field("PROVIDER", provider or "Unknown")
        info_field("CREATED", (info.get("created") or "")[:16].replace("T", " ") or "—", mono=True)
        info_field("LAST ROTATED", (info.get("rotated") or "")[:16].replace("T", " ") or "Never", mono=True)
        info_field("ROTATION COUNT", str(info.get("rotation_count", 0)))

        age = days_since(info.get("rotated") or info.get("created"))
        age_str = f"{age} days" if age != float('inf') else "Unknown"
        info_field("AGE / HEALTH", f"{age_str} — {health_status(info).upper()}", fg=health_color(status))

        # Import source (bulk upload metadata)
        if info.get("source_file"):
            tk.Label(pad, text="IMPORT SOURCE", font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w", pady=(14, 4))
            sf = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            sf.pack(fill="x", pady=2)

            tk.Label(sf, text="FILE", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(sf, text=f"{info['source_file']} : line {info.get('source_line', '?')}",
                    font=FONT_MONO_SM, bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=10, pady=(0, 4))

            imp = (info.get("imported_at") or "")[:16].replace("T", " ")
            if imp:
                tk.Label(sf, text="IMPORTED", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                tk.Label(sf, text=imp, font=FONT_MONO_SM, bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=10, pady=(0, 4))

            raw = info.get("source_raw", "")
            if raw:
                tk.Label(sf, text="ORIGINAL LINE", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                rt = tk.Text(sf, font=FONT_MONO, bg=C["bg3"], fg=C["text"],
                            height=3, wrap="word", relief="flat", state="normal")
                rt.pack(fill="x", padx=10, pady=(0, 8))
                rt.insert("1.0", raw)
                rt.config(state="disabled")

        # History summary
        history = info.get("history", [])
        if history:
            tk.Label(pad, text=f"HISTORY ({len(history)} previous values)",
                    font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w", pady=(14, 4))
            for i, entry in enumerate(history[:3]):
                hf = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
                hf.pack(fill="x", pady=1)
                retired = (entry.get("retired") or "")[:16].replace("T", " ")
                tk.Label(hf, text=f"#{i+1}  retired {retired}", font=FONT_XS,
                        bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                v = entry["value"]
                mv = v[:4] + "●" * min(12, len(v) - 8) + v[-4:] if len(v) > 8 else "●" * len(v)
                tk.Label(hf, text=mv, font=FONT_MONO_SM, bg=C["surface"], fg=C["text2"]).pack(anchor="w", padx=10, pady=(0, 4))
            if len(history) > 3:
                tk.Label(pad, text=f"  … and {len(history) - 3} more",
                        font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w")

        # Action bar
        bar = tk.Frame(win, bg=C["bg3"])
        bar.pack(fill="x", pady=8, padx=16)

        make_btn(bar, "Rotate Key", lambda: (win.destroy(), self.rotate_key(name)),
                bg=C["amber_bg"], fg=C["amber"]).pack(side="left", padx=4, ipady=4)
        if history:
            make_btn(bar, "Full History", lambda: self.show_history(name), width=12).pack(side="left", padx=4, ipady=4)
        if info.get("source_file"):
            make_btn(bar, "Source Detail", lambda: self.show_source(name), width=12).pack(side="left", padx=4, ipady=4)
        if provider and PROVIDERS.get(provider, {}).get("url"):
            make_btn(bar, f"Open {provider}",
                    lambda u=PROVIDERS[provider]["url"]: webbrowser.open(u),
                    bg=C["accent"], fg="white").pack(side="left", padx=4, ipady=4)
        make_btn(bar, "Delete", lambda: (win.destroy(), self.delete_key(name)),
                bg=C["red_bg"], fg="#FCA5A5", width=8).pack(side="right", padx=4, ipady=4)
        make_btn(bar, "Close", win.destroy, width=8).pack(side="right", padx=4, ipady=4)

    # ═══════════════════════════════════════════
    # TEMPLATE VIEWER
    # ═══════════════════════════════════════════

    def show_template(self):
        template_path = Path(__file__).parent / "KEY_IMPORT_TEMPLATE.md"

        win = tk.Toplevel(self)
        win.title("Key Import Template")
        win.geometry("660x580")
        win.minsize(500, 400)
        win.configure(bg=C["bg2"])
        win.transient(self)

        tk.Label(win, text="Key Import Template", font=FONT_H2,
                bg=C["bg2"], fg=C["text"]).pack(pady=(12, 4), padx=16, anchor="w")
        tk.Label(win, text="Reference format for bulk upload files (txt / .env)",
                font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(padx=16, anchor="w", pady=(0, 8))

        text_frame = tk.Frame(win, bg=C["bg2"])
        text_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        vsb = tk.Scrollbar(text_frame, orient="vertical")
        txt = tk.Text(text_frame, font=FONT_MONO_SM, bg=C["bg3"], fg=C["text"],
                     relief="flat", wrap="none", padx=12, pady=8,
                     yscrollcommand=vsb.set, state="normal")
        vsb.config(command=txt.yview)
        vsb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        content = template_path.read_text(encoding="utf-8") if template_path.exists() else "(Template file not found)"
        txt.insert("1.0", content)
        txt.config(state="disabled")

        btn_bar = tk.Frame(win, bg=C["bg2"])
        btn_bar.pack(fill="x", padx=16, pady=8)
        if template_path.exists():
            make_btn(btn_bar, "Open in Editor", lambda: os.startfile(str(template_path))).pack(side="left", ipady=4)
        make_btn(btn_bar, "Close", win.destroy, width=10).pack(side="right", ipady=4)

    # ═══════════════════════════════════════════
    # PROJECTS TAB
    # ═══════════════════════════════════════════
    
    def render_projects(self):
        for w in self.proj_frame.winfo_children(): w.destroy()
        
        canvas = tk.Canvas(self.proj_frame, bg=C["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self.proj_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _proj_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_proj_win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        pad = tk.Frame(inner, bg=C["bg"])
        pad.pack(fill="x", padx=16, pady=12)
        
        # Add project form
        form = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        form.pack(fill="x", pady=(0, 16))

        tk.Label(form, text="Link a project folder", font=FONT_H3, bg=C["surface"], fg=C["text"]).pack(anchor="w", padx=12, pady=(10, 4))
        tk.Label(form, text="Click Browse, pick your project folder — name and path fill in automatically.",
                font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=12, pady=(0, 10))

        # Row 1: FOLDER PATH + Browse button inline
        r1 = tk.Frame(form, bg=C["surface"])
        r1.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(r1, text="FOLDER PATH", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w")
        path_row = tk.Frame(r1, bg=C["surface"])
        path_row.pack(fill="x")
        self.proj_path_var = tk.StringVar()
        path_entry = tk.Entry(path_row, font=FONT_MONO_SM, bg=C["bg3"], fg=C["text"],
                              insertbackground=C["text"], relief="flat", textvariable=self.proj_path_var)
        path_entry.pack(side="left", fill="x", expand=True, ipady=5)
        make_btn(path_row, "📁 Browse", self.browse_folder, bg=C["accent"], fg="white").pack(side="left", padx=(6, 0), ipady=5)

        # Row 2: PROJECT NAME + Link button inline
        r2 = tk.Frame(form, bg=C["surface"])
        r2.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(r2, text="PROJECT NAME", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w")
        name_row = tk.Frame(r2, bg=C["surface"])
        name_row.pack(fill="x")
        self.proj_name = tk.Entry(name_row, font=FONT_SM, bg=C["bg3"], fg=C["text"],
                                  insertbackground=C["text"], relief="flat")
        self.proj_name.pack(side="left", fill="x", expand=True, ipady=5)
        make_btn(name_row, "+ Link Project", self.add_project, bg=C["green_bg"], fg=C["green"]).pack(side="left", padx=(6, 0), ipady=5)
        
        # Project list
        projects = self.config.get("projects", {})
        if not projects:
            tk.Label(pad, text="No projects linked yet.\nAdd a project folder above, and Pushkey will auto-write\n.env files when you add or rotate keys.",
                    font=FONT, bg=C["bg"], fg=C["text3"], justify="center").pack(pady=30)
            return
        
        tk.Label(pad, text="LINKED PROJECTS", font=FONT_XS, bg=C["bg"], fg=C["text3"]).pack(anchor="w", pady=(0, 6))
        
        for proj_name, proj_info in sorted(projects.items()):
            proj_keys = proj_info.get("keys", [])
            matched = self._auto_match_keys(proj_name)
            has_keys = len(proj_keys) > 0 or len(matched) > 0
            dot_color = C["green"] if has_keys else "#FCA5A5"

            card = tk.Frame(pad, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            card.pack(fill="x", pady=3)

            # Status dot
            dot = tk.Canvas(card, width=10, height=10, bg=C["surface"], highlightthickness=0)
            dot.pack(side="left", padx=(12, 0), pady=12)
            dot.create_oval(1, 1, 9, 9, fill=dot_color, outline="")

            info_f = tk.Frame(card, bg=C["surface"])
            info_f.pack(side="left", fill="x", expand=True, padx=10, pady=8)

            tk.Label(info_f, text=proj_name, font=FONT_H3, bg=C["surface"], fg=C["text"]).pack(anchor="w")
            tk.Label(info_f, text=proj_info.get("path", ""), font=FONT_MONO_SM, bg=C["surface"], fg=C["text3"]).pack(anchor="w")

            if proj_keys:
                key_text = f"{len(proj_keys)} keys assigned"
                key_color = C["green"]
            elif matched:
                key_text = f"No keys assigned — {len(matched)} auto-matched available (click Assign Keys)"
                key_color = C["amber"]
            else:
                key_text = "No keys assigned — no matching keys found in vault"
                key_color = "#FCA5A5"
            tk.Label(info_f, text=key_text, font=FONT_XS, bg=C["surface"], fg=key_color).pack(anchor="w")

            btn_f = tk.Frame(card, bg=C["surface"])
            btn_f.pack(side="right", padx=8, pady=8)

            make_btn(btn_f, "Sync now",
                    lambda p=proj_name: self.sync_project(p),
                    bg=C["accent"], fg="white").pack(pady=1)
            make_btn(btn_f, "Assign Keys",
                    lambda p=proj_name: self.assign_keys_to_project(p)).pack(pady=1)
            make_btn(btn_f, "Remove",
                    lambda p=proj_name: self.remove_project(p),
                    bg=C["red_bg"], fg="#FCA5A5").pack(pady=1)
    
    def browse_folder(self):
        desktop = Path.home() / "Desktop"
        onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
        if onedrive_desktop.exists():
            start = onedrive_desktop
        elif desktop.exists():
            start = desktop
        else:
            start = Path.home()
        path = filedialog.askdirectory(title="Select project folder", initialdir=str(start))
        if path:
            self.proj_path_var.set(path)
            self.proj_name.delete(0, tk.END)
            self.proj_name.insert(0, os.path.basename(path))
    
    def add_project(self):
        name = self.proj_name.get().strip()
        path = self.proj_path_var.get().strip()
        
        if not name or not path:
            messagebox.showwarning("Missing info", "Enter a project name and select a folder")
            return
        if not os.path.isdir(path):
            messagebox.showwarning("Invalid path", f"Folder not found:\n{path}")
            return
        
        if "projects" not in self.config:
            self.config["projects"] = {}

        matched = self._auto_match_keys(name)
        self.config["projects"][name] = {
            "path": path,
            "keys": matched,
            "added": datetime.now().isoformat(),
        }
        
        # Immediately inject
        inject_env_file(path, self.vault)
        
        self.save()
        self.proj_name.delete(0, tk.END)
        self.proj_path_var.set("")
        self.render_projects()
        messagebox.showinfo("Linked", f"'{name}' linked and .env written to:\n{path}")
    
    def _refresh_project_keys(self, proj_name):
        """Merge any newly auto-matched keys into the project's assigned list. Returns new keys added."""
        proj = self.config["projects"].get(proj_name)
        if not proj:
            return []
        matched = set(self._auto_match_keys(proj_name))
        current = set(proj.get("keys", []))
        new_keys = matched - current
        if new_keys:
            proj["keys"] = sorted(current | matched)
            self.save()
        return sorted(new_keys)

    def _refresh_all_projects(self):
        """Called after bulk import — update every project with any newly matching keys."""
        for proj_name in list(self.config.get("projects", {}).keys()):
            self._refresh_project_keys(proj_name)

    def sync_project(self, proj_name):
        proj = self.config["projects"].get(proj_name)
        if not proj:
            return

        path = proj["path"]

        if not os.path.isdir(path):
            messagebox.showerror("Folder not found", f"The project folder no longer exists:\n{path}\n\nUpdate the path in Projects.")
            return

        # Always refresh auto-match first so newly imported keys are included
        new_keys = self._refresh_project_keys(proj_name)
        assigned = set(proj.get("keys", []))
        matched = set(self._auto_match_keys(proj_name))

        # Final write list: assigned keys that exist in vault
        keys_to_write = sorted(k for k in assigned if k in self.vault)

        # Verification dialog
        win = tk.Toplevel(self)
        win.title("Confirm Sync")
        win.geometry("500x460")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="Confirm .env Sync", font=FONT_H2, bg=C["bg2"], fg=C["text"]).pack(pady=(14, 4), padx=16, anchor="w")

        # Folder path
        folder_f = tk.Frame(win, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        folder_f.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(folder_f, text="WRITING TO", font=FONT_XS, bg=C["surface"], fg=C["text3"]).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(folder_f, text=os.path.join(path, ".env"), font=FONT_MONO_SM,
                bg=C["surface"], fg=C["green"], wraplength=440, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        if new_keys:
            tk.Label(win, text=f"+ {len(new_keys)} newly matched key(s) added since last sync",
                    font=FONT_XS, bg=C["bg2"], fg=C["amber"]).pack(anchor="w", padx=16, pady=(0, 4))

        tk.Label(win, text=f"KEYS TO WRITE  ({len(keys_to_write)})", font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(anchor="w", padx=16, pady=(0, 4))

        list_canvas = tk.Canvas(win, bg=C["bg"], highlightthickness=0, height=180)
        list_sb = tk.Scrollbar(win, orient="vertical", command=list_canvas.yview)
        list_frame = tk.Frame(list_canvas, bg=C["bg"])
        list_frame.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_sb.set)
        list_canvas.pack(side="left", fill="x", expand=True, padx=16)
        list_sb.pack(side="right", fill="y")

        for k in keys_to_write:
            is_new = k in new_keys
            color = C["amber"] if is_new else C["text"]
            tag = "  + new" if is_new else ""
            tk.Label(list_frame, text=f"  {k}{tag}", font=FONT_MONO_SM, bg=C["bg"], fg=color, anchor="w").pack(fill="x")

        btn_f = tk.Frame(win, bg=C["bg2"])
        btn_f.pack(fill="x", padx=16, pady=12)

        def confirm():
            win.destroy()
            try:
                inject_env_file(path, self.vault, keys_to_write if keys_to_write else None)
                log_event(f"sync: wrote {len(keys_to_write)} keys to {path}/.env")
                messagebox.showinfo("Synced", f"✓ .env written to:\n{path}\n\n{len(keys_to_write)} key(s) synced.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to write .env:\n{e}")

        make_btn(btn_f, "✓ Confirm & Write .env", confirm, bg=C["green_bg"], fg=C["green"]).pack(side="left", ipady=4)
        make_btn(btn_f, "Cancel", win.destroy).pack(side="left", padx=(8, 0), ipady=4)
    
    def _auto_match_keys(self, proj_name):
        """Return vault keys whose name starts with the project name prefix."""
        prefix = re.sub(r'[^A-Z0-9]', '_', proj_name.upper())
        prefix = re.sub(r'_+', '_', prefix).strip('_')
        return [k for k in self.vault if k == prefix or k.startswith(prefix + '_')]

    def assign_keys_to_project(self, proj_name):
        """Pop up a window to pick which keys this project uses."""
        if not self.vault:
            messagebox.showinfo("No keys", "Add some keys first, then assign them to projects.")
            return
        
        win = tk.Toplevel(self)
        win.title(f"Assign keys to {proj_name}")
        win.geometry("400x450")
        win.configure(bg=C["bg2"])
        win.transient(self)
        win.grab_set()
        
        tk.Label(win, text=f"Select keys for {proj_name}", font=FONT_H3,
                bg=C["bg2"], fg=C["text"]).pack(pady=(12, 4), padx=12, anchor="w")
        tk.Label(win, text="Unchecked keys won't be written to this project's .env",
                font=FONT_XS, bg=C["bg2"], fg=C["text3"]).pack(padx=12, anchor="w", pady=(0, 8))
        
        current_keys = set(self.config["projects"][proj_name].get("keys", []))
        matched = set(self._auto_match_keys(proj_name))

        checks = {}
        canvas = tk.Canvas(win, bg=C["bg2"], highlightthickness=0)
        sb = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=C["bg2"])
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=12)
        sb.pack(side="right", fill="y")

        for section_keys, label, color in [
            (sorted(matched), "AUTO-MATCHED", C["green"]),
            (sorted(k for k in self.vault if k not in matched), "OTHER KEYS", C["text3"]),
        ]:
            if not section_keys:
                continue
            tk.Label(frame, text=label, font=FONT_XS, bg=C["bg2"], fg=color).pack(anchor="w", pady=(8, 2), padx=4)
            for key_name in section_keys:
                checked = key_name in current_keys or (not current_keys and key_name in matched)
                var = tk.BooleanVar(value=checked)
                checks[key_name] = var
                row = tk.Frame(frame, bg=C["bg2"])
                row.pack(fill="x")
                cb = tk.Checkbutton(row, text=key_name, variable=var, font=FONT_MONO_SM,
                                   bg=C["bg2"], fg=C["green"] if key_name in matched else C["text"],
                                   selectcolor=C["bg3"], activebackground=C["bg2"], activeforeground=C["text"])
                cb.pack(side="left", anchor="w", pady=1)
        
        def save_assignment():
            selected = [n for n, v in checks.items() if v.get()]
            self.config["projects"][proj_name]["keys"] = selected
            self.save()
            win.destroy()
            self.render_projects()
        
        make_btn(win, "Save", save_assignment, bg=C["accent"], fg="white", width=15).pack(pady=12)
    
    def remove_project(self, proj_name):
        if messagebox.askyesno("Remove?", f"Unlink '{proj_name}'?\n\nThis won't delete the .env file, just stops syncing."):
            del self.config["projects"][proj_name]
            self.save()
            self.render_projects()

# ═══════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════

class PushkeyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Pushkey")
        self.root.geometry("760x620")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)
        self.root.minsize(700, 500)
        
        self.frame = None
        self.show_login()
        self.root.mainloop()
    
    def switch(self, cls, **kw):
        if self.frame: self.frame.destroy()
        self.frame = cls(self.root, **kw)
        self.frame.pack(fill="both", expand=True)
    
    def show_login(self):
        self.switch(LoginFrame, on_login=self.on_login)
    
    def on_login(self, pw, vault):
        self.switch(AppFrame, password=pw, vault=vault, on_lock=self.show_login)

def main():
    ensure_vault_dir()
    PushkeyApp()

if __name__ == "__main__":
    main()

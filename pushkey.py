"""
Pushkey v3 — Encrypted Key Manager with Direct .env Injection
=========================================================================

CustomTkinter edition — native-looking UI on all platforms.

1. Store keys encrypted with AES-256 via your master password
2. Track when each key was created, last rotated, and from which provider
3. Link directly to each provider's key generation page
4. Register project folders — know which projects use which keys
5. DIRECTLY WRITE .env files into your project folders when keys change
6. Auto-add .env to .gitignore if it's not there already

Usage:
    pip install -r requirements.txt
    python pushkey.py
"""

import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
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
import atexit

# ═══════════════════════════════════════════════
# CTK APPEARANCE
# ═══════════════════════════════════════════════

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ═══════════════════════════════════════════════
# CRYPTO
# ═══════════════════════════════════════════════

VAULT_DIR = Path.home() / ".pushkey"
VAULT_FILE = VAULT_DIR / "vault.enc"
SALT_FILE = VAULT_DIR / ".salt"
CONFIG_FILE = VAULT_DIR / "config.json"
LOG_FILE = VAULT_DIR / "pushkey.log"
IMPORT_DIR = VAULT_DIR / "import"

VAULT_SCHEMA_VERSION = 1


def _migrate_vault(data):
    schema = data.get("_schema", 0)
    if schema < VAULT_SCHEMA_VERSION:
        data["_schema"] = VAULT_SCHEMA_VERSION
    return data


def log_event(message: str) -> None:
    try:
        ensure_vault_dir()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def ensure_vault_dir():
    VAULT_DIR.mkdir(mode=0o700, exist_ok=True)
    IMPORT_DIR.mkdir(exist_ok=True)
    # Drop a README in the import folder so users know what to do
    readme = IMPORT_DIR / "README.txt"
    if not readme.exists():
        readme.write_text(
            "PUSHKEY IMPORT FOLDER\n"
            "═══════════════════════════════════════\n\n"
            "Drop your key files here (.txt, .env)\n"
            "then click 'Scan Import Folder' in Pushkey\n"
            "to import them all at once.\n\n"
            "Supported formats:\n"
            "  KEY=value\n"
            "  key\n"
            "  value\n"
            "  client id = value\n"
            "  Label: value\n\n"
            "The file name becomes the key prefix.\n"
            "Example: alpaca.txt → ALPACA_KEY, ALPACA_SECRET\n"
        )


def get_or_create_salt():
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    salt = secrets.token_bytes(32)
    SALT_FILE.write_bytes(salt)
    try:
        os.chmod(SALT_FILE, 0o600)
    except Exception:
        pass
    return salt


def derive_key(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)


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
        "  python pushkey.py",
    )
    _root.destroy()
    raise SystemExit(1)


def make_fernet(password):
    salt = get_or_create_salt()
    key = derive_key(password, salt)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_data(data, password):
    return make_fernet(password).encrypt(data.encode())


def decrypt_data(token, password):
    try:
        return make_fernet(password).decrypt(token).decode()
    except InvalidToken:
        raise ValueError("wrong_password")
    except Exception as e:
        raise ValueError(f"corrupted:{e}")


def _serialize_vault(vault):
    return {"_schema": VAULT_SCHEMA_VERSION, "keys": vault}


def _deserialize_vault(data):
    if isinstance(data, dict) and isinstance(data.get("keys"), dict):
        return data["keys"]
    if isinstance(data, dict):
        return data
    return None


def load_vault(password):
    if not VAULT_FILE.exists():
        return {}
    try:
        raw = VAULT_FILE.read_bytes()
        decrypted = decrypt_data(raw, password)
        data = json.loads(decrypted)
        data = _migrate_vault(data)
        return _deserialize_vault(data)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"corrupted:{e}")


def save_vault(vault, password):
    import shutil
    ensure_vault_dir()
    payload = _serialize_vault(vault)
    encrypted = encrypt_data(json.dumps(payload, indent=2), password)
    # Atomic write — never corrupt on crash
    tmp = VAULT_FILE.with_suffix('.tmp')
    tmp.write_bytes(encrypted)
    os.replace(str(tmp), str(VAULT_FILE))
    try:
        os.chmod(VAULT_FILE, 0o600)
    except Exception:
        pass
    # Auto-backup (keep 3 most recent)
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = VAULT_DIR / f"vault_backup_{ts}.enc"
        shutil.copy2(str(VAULT_FILE), str(backup))
        backups = sorted(VAULT_DIR.glob("vault_backup_*.enc"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"projects": {}}


def save_config(config):
    ensure_vault_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


# ═══════════════════════════════════════════════
# PROVIDER DATABASE
# ═══════════════════════════════════════════════

PROVIDERS = {
    "OpenAI": {"url": "https://platform.openai.com/api-keys", "prefix": "sk-", "category": "AI", "patterns": ["openai", "gpt"], "rotation_days": 90},
    "Anthropic": {"url": "https://console.anthropic.com/settings/keys", "prefix": "sk-ant-", "category": "AI", "patterns": ["anthropic", "claude"], "rotation_days": 90},
    "Alpaca": {"url": "https://app.alpaca.markets/paper/dashboard/overview", "prefix": "", "category": "Trading", "patterns": ["alpaca"], "rotation_days": 90},
    "OANDA": {"url": "https://www.oanda.com/account/tpa/personal_token", "prefix": "", "category": "Trading", "patterns": ["oanda"], "rotation_days": 90},
    "Coinbase": {"url": "https://www.coinbase.com/settings/api", "prefix": "", "category": "Trading", "patterns": ["coinbase"], "rotation_days": 90},
    "Supabase": {"url": "https://supabase.com/dashboard", "prefix": "eyJ", "category": "Database", "patterns": ["supabase"], "rotation_days": 180},
    "Stripe": {"url": "https://dashboard.stripe.com/apikeys", "prefix": "sk_", "category": "Payment", "patterns": ["stripe"], "rotation_days": 90},
    "AWS": {"url": "https://console.aws.amazon.com/iam/home#/security_credentials", "prefix": "AKIA", "category": "Cloud", "patterns": ["aws", "amazon"], "rotation_days": 90},
    "Vercel": {"url": "https://vercel.com/account/tokens", "prefix": "", "category": "Cloud", "patterns": ["vercel"], "rotation_days": 90},
    "GitHub": {"url": "https://github.com/settings/tokens", "prefix": "ghp_", "category": "VCS", "patterns": ["github", "gh_", "ghp_"], "rotation_days": 90},
    "GitLab": {"url": "https://gitlab.com/-/profile/personal_access_tokens", "prefix": "glpat-", "category": "VCS", "patterns": ["gitlab", "glpat"], "rotation_days": 90},
    "Twilio": {"url": "https://console.twilio.com/?frameUrl=/console/account/keys", "prefix": "", "category": "Communication", "patterns": ["twilio"], "rotation_days": 90},
    "SendGrid": {"url": "https://app.sendgrid.com/settings/api_keys", "prefix": "SG.", "category": "Communication", "patterns": ["sendgrid"], "rotation_days": 90},
    "Slack": {"url": "https://api.slack.com/apps", "prefix": "xoxb-", "category": "Communication", "patterns": ["slack", "xoxb", "xoxp"], "rotation_days": 180},
    "Discord": {"url": "https://discord.com/developers/applications", "prefix": "", "category": "Communication", "patterns": ["discord"], "rotation_days": 90},
    "Google Cloud": {"url": "https://console.cloud.google.com/apis/credentials", "prefix": "", "category": "Cloud", "patterns": ["google", "gcp"], "rotation_days": 90},
    "Azure": {"url": "https://portal.azure.com/#view/Microsoft_AAD_IAM/AppIntegrationsMenuBlade", "prefix": "", "category": "Cloud", "patterns": ["azure"], "rotation_days": 90},
    "DigitalOcean": {"url": "https://cloud.digitalocean.com/account/api/tokens", "prefix": "dop_v1_", "category": "Cloud", "patterns": ["digitalocean", "dop_"], "rotation_days": 90},
    "Heroku": {"url": "https://dashboard.heroku.com/account", "prefix": "", "category": "Cloud", "patterns": ["heroku"], "rotation_days": 90},
    "MongoDB Atlas": {"url": "https://cloud.mongodb.com/v2", "prefix": "mongodb+srv://", "category": "Database", "patterns": ["mongodb", "mongo"], "rotation_days": 180},
    "PostgreSQL": {"url": "https://console.cloud.google.com/sql", "prefix": "postgresql://", "category": "Database", "patterns": ["postgres", "psql"], "rotation_days": 180},
    "Elastic": {"url": "https://www.elastic.co/cloud/console/", "prefix": "", "category": "Database", "patterns": ["elastic"], "rotation_days": 90},
    "HashiCorp Vault": {"url": "https://www.vaultproject.io/", "prefix": "s.", "category": "Security", "patterns": ["hashicorp"], "rotation_days": 30},
    "PagerDuty": {"url": "https://subdomain.pagerduty.com/api_keys", "prefix": "", "category": "Incident", "patterns": ["pagerduty"], "rotation_days": 90},
    "Datadog": {"url": "https://app.datadoghq.com/organization-settings/api-keys", "prefix": "", "category": "Monitoring", "patterns": ["datadog"], "rotation_days": 90},
    "New Relic": {"url": "https://one.newrelic.com/launcher/api-keys-ui.launcher", "prefix": "", "category": "Monitoring", "patterns": ["newrelic"], "rotation_days": 90},
    "HubSpot": {"url": "https://app.hubspot.com/login", "prefix": "pat-", "category": "CRM", "patterns": ["hubspot"], "rotation_days": 90},
    "Jira": {"url": "https://id.atlassian.com/manage/api-tokens", "prefix": "", "category": "Project Management", "patterns": ["jira", "atlassian"], "rotation_days": 90},
}


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


# ═══════════════════════════════════════════════
# .ENV INJECTION ENGINE
# ═══════════════════════════════════════════════

def _format_env_value(value):
    if value is None:
        return ""
    value = str(value)
    needs_quotes = (
        value == ""
        or value[0].isspace()
        or value[-1].isspace()
        or any(ch in value for ch in ("\n", "\r", "\t", " ", "#", '"'))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


_ENV_LINE_RE = re.compile(
    r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^#\r\n]*?)(?:\s*#.*)?\s*$'
)
_COLON_LINE_RE = re.compile(r'^([A-Za-z][A-Za-z0-9 _-]{1,40})\s*:\s*(?!//)(.+)$')
_LABEL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9 _\-/()\[\]]{0,79}$')
_SECRET_META_RE = re.compile(r'^#\s*secret\s*:\s*(true|false|yes|no|1|0)\s*$', re.IGNORECASE)
# Handles "client id = value", "sandbox secret = value" (spaces allowed in key)
_SPACED_KEY_RE = re.compile(r'^([A-Za-z][A-Za-z0-9 _-]{1,50}?)\s*=\s*(.+)$')

_TYPE_WORDS = {
    "key": ("KEY", False),
    "api key": ("API_KEY", False),
    "token": ("TOKEN", False),
    "access token": ("ACCESS_TOKEN", False),
    "bot token": ("BOT_TOKEN", False),
    "secret": ("SECRET", True),
    "secret key": ("SECRET_KEY", True),
    "private": ("PRIVATE_KEY", True),
    "private key": ("PRIVATE_KEY", True),
    "password": ("PASSWORD", True),
    "passphrase": ("PASSPHRASE", True),
    "endpoint": ("ENDPOINT", False),
    "url": ("URL", False),
    "base url": ("BASE_URL", False),
    "api url": ("API_URL", False),
    "webhook": ("WEBHOOK_URL", False),
    "webhook url": ("WEBHOOK_URL", False),
    "rpc": ("RPC_URL", False),
    "rpc url": ("RPC_URL", False),
    "account id": ("ACCOUNT_ID", False),
    "account": ("ACCOUNT_ID", False),
    "client id": ("CLIENT_ID", False),
    "client secret": ("CLIENT_SECRET", True),
    "username": ("USERNAME", False),
    "user": ("USERNAME", False),
}


def _parse_env_line(raw_line: str):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    m = _ENV_LINE_RE.match(line)
    if m:
        key = m.group(1).upper()
        raw_val = m.group(2).strip()
        if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
            quote_char = raw_val[0]
            raw_val = raw_val[1:-1]
            raw_val = raw_val.replace(f"\\{quote_char}", quote_char)
            raw_val = raw_val.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
        return key, raw_val
    m = _COLON_LINE_RE.match(line)
    if m:
        label = m.group(1).strip()
        value = m.group(2).strip()
        key = label.upper().replace(" ", "_").replace("-", "_")
        return key, value
    return None


def _file_prefix(path):
    stem = Path(path).stem
    prefix = re.sub(r"[^A-Z0-9]", "_", stem.upper())
    return re.sub(r"_+", "_", prefix).strip("_")


def _parse_env_file(path):
    entries = []
    errors = []
    pending_label = None
    pending_label_line = None
    next_secret = None
    prefix = _file_prefix(path)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        m = _SECRET_META_RE.match(line)
        if m:
            flag = m.group(1).lower() in ("true", "yes", "1")
            if pending_label is not None:
                next_secret = flag
            elif entries:
                entries[-1]["secret"] = flag
            continue

        if not line or line.startswith("#"):
            continue

        result = _parse_env_line(raw_line)
        if result:
            name, value = result
            if pending_label:
                errors.append(f"line {pending_label_line}: label '{pending_label}' had no value (skipped)")
                pending_label = None
            if name and value:
                entries.append({"name": name, "value": value, "line": line_num, "raw_line": raw_line, "secret": next_secret or False})
                next_secret = None
            elif not value:
                errors.append(f"line {line_num}: {name} skipped (no value)")
            continue

        # Try spaced-key format: "client id = value", "sandbox secret = value"
        m = _SPACED_KEY_RE.match(line)
        if m:
            spaced_key = m.group(1).strip()
            value = m.group(2).strip()
            suffix = re.sub(r'[^A-Z0-9]', '_', spaced_key.upper())
            suffix = re.sub(r'_+', '_', suffix).strip('_')
            # Check if the suffix itself is a type word
            type_info = _TYPE_WORDS.get(spaced_key.lower())
            auto_secret = type_info[1] if type_info else any(
                w in spaced_key.lower() for w in ('secret', 'password', 'private', 'passphrase')
            )
            if type_info:
                suffix = type_info[0]
            if pending_label is not None:
                # "plaid" label becomes the prefix for all spaced-key lines that follow
                lbl = re.sub(r'[^A-Z0-9]', '_', pending_label.upper())
                lbl = re.sub(r'_+', '_', lbl).strip('_')
                key = f"{lbl}_{suffix}"
                # Keep pending_label so subsequent spaced-key lines also use it
            else:
                key = f"{prefix}_{suffix}" if prefix else suffix
            is_secret = next_secret if next_secret is not None else auto_secret
            entries.append({"name": key, "value": value, "line": line_num, "raw_line": raw_line, "secret": is_secret})
            next_secret = None
            continue

        if pending_label is not None:
            type_info = _TYPE_WORDS.get(pending_label.lower())
            if type_info:
                suffix, auto_secret = type_info
                key = f"{prefix}_{suffix}" if prefix else suffix
                is_secret = next_secret if next_secret is not None else auto_secret
            else:
                key = re.sub(r"[^A-Z0-9]", "_", pending_label.upper())
                key = re.sub(r"_+", "_", key).strip("_")
                if prefix and not key.startswith(prefix + "_") and key != prefix:
                    key = f"{prefix}_{key}"
                is_secret = next_secret or False
            entries.append({"name": key, "value": line, "line": line_num, "raw_line": raw_line, "secret": is_secret})
            next_secret = None
            pending_label = None
        elif _LABEL_RE.match(line):
            pending_label = line
            pending_label_line = line_num
        else:
            errors.append(f"line {line_num}: could not parse '{line[:40]}'")

    if pending_label and not any(e.get("name", "").startswith(
            re.sub(r'[^A-Z0-9]', '_', pending_label.upper()).strip('_')) for e in entries):
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
    """Update .env surgically — only touch keys being written, preserve everything else."""
    project_dir = Path(project_path)
    env_path = project_dir / ".env"

    if key_names:
        keys_to_write = {k: vault[k]["value"] for k in key_names if k in vault}
    else:
        keys_to_write = {k: v["value"] for k, v in vault.items()}

    if not keys_to_write:
        return True

    # Backup existing .env before any changes
    import shutil
    if env_path.exists():
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = env_path.with_name(f".env.pushkey_backup_{ts}")
        shutil.copy2(str(env_path), str(backup))
        # Keep only the 5 most recent backups
        backups = sorted(env_path.parent.glob(".env.pushkey_backup_*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[5:]:
            old.unlink(missing_ok=True)

    # Read existing file preserving ALL lines (comments, blanks, structure)
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    # Pass 1: update keys that already exist in the file in-place
    updated = set()
    new_lines = []
    for line in existing_lines:
        result = _parse_env_line(line)
        if result and result[0] in keys_to_write:
            key = result[0]
            new_lines.append(f"{key}={_format_env_value(keys_to_write[key])}")
            updated.add(key)
        else:
            new_lines.append(line)

    # Pass 2: append new keys that didn't exist yet
    new_keys = {k: v for k, v in keys_to_write.items() if k not in updated}
    if new_keys:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"# Added by Pushkey {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        for k in sorted(new_keys.keys()):
            new_lines.append(f"{k}={_format_env_value(new_keys[k])}")

    _atomic_write_text(env_path, "\n".join(new_lines) + "\n")
    _ensure_gitignore_env(project_dir)
    return True


# ═══════════════════════════════════════════════
# COLORS & FONTS
# ═══════════════════════════════════════════════

C = {
    "bg":       "#04070D",
    "bg2":      "#080D17",
    "bg3":      "#0C1420",
    "bg4":      "#11202F",
    "surface":  "#09111D",
    "accent":   "#059669",
    "accent2":  "#047857",
    "green":    "#10B981",
    "green_bg": "#022C22",
    "amber":    "#F59E0B",
    "amber_bg": "#451A03",
    "red":      "#F87171",
    "red_bg":   "#3B0D0D",
    "btn":      "#0F1E30",
    "btn_hover":"#162840",
    "text":     "#DDE4EE",
    "text2":    "#7C8FA6",
    "text3":    "#3D5166",
    "border":   "#152238",
    "border2":  "#1E3350",
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
    "AI":       "#A78BFA",
    "Trading":  "#F59E0B",
    "Database": "#22D3EE",
    "Cloud":    "#60A5FA",
    "Payment":  "#F472B6",
    "Communication": "#34D399",
    "Comms":    "#34D399",
    "Security": "#059669",
    "Crypto":   "#FB923C",
    "General":  "#64748B",
    "VCS":      "#94A3B8",
    "Monitoring": "#818CF8",
    "CRM":      "#FB7185",
    "Project Management": "#A3E635",
    "Incident": "#FCD34D",
}


# ═══════════════════════════════════════════════
# HELPER WIDGETS (CTK-native)
# ═══════════════════════════════════════════════

def make_btn(parent, text, command, fg_color=None, text_color=None, width=None, height=28):
    fg = fg_color or C["btn"]
    tc = text_color or C["text2"]
    kw = dict(
        text=text,
        command=command,
        fg_color=fg,
        text_color=tc,
        hover_color=C["btn_hover"],
        font=FONT_BTN,
        corner_radius=4,
        height=height,
    )
    if width:
        kw["width"] = width
    return ctk.CTkButton(parent, **kw)


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
    if age > threshold:
        return "critical"
    if age > threshold * 0.67:
        return "warning"
    return "healthy"


def health_color(status):
    return {"healthy": C["green"], "warning": C["amber"], "critical": C["red"]}.get(status, C["text3"])


# ═══════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════

class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, on_login):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.on_login = on_login
        self.is_new = not VAULT_FILE.exists()

        ctk.CTkFrame(self, fg_color="transparent", height=60).pack()

        # Brand
        ctk.CTkLabel(self, text="●", font=("Consolas", 36), text_color=C["accent"]).pack(pady=(0, 4))
        ctk.CTkLabel(self, text="PUSHKEY", font=("Consolas", 26, "bold"), text_color=C["text"]).pack()
        ctk.CTkLabel(self, text="encrypted key vault", font=FONT_XS, text_color=C["text3"]).pack(pady=(2, 0))

        ctk.CTkFrame(self, fg_color=C["border"], height=1).pack(fill="x", padx=100, pady=24)

        sub = "create a master password to get started" if self.is_new else "enter master password to unlock"
        ctk.CTkLabel(self, text=sub, font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 12))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack()

        self.pw = ctk.CTkEntry(
            form, show="●", font=("Consolas", 14), fg_color=C["bg3"],
            text_color=C["text"], border_color=C["border2"], width=300, justify="center",
        )
        self.pw.pack(pady=(0, 8), ipady=4)
        self.pw.focus_set()
        self.pw.bind("<Return>", lambda e: self.unlock())

        if self.is_new:
            self.pw2 = ctk.CTkEntry(
                form, show="●", font=("Consolas", 14), fg_color=C["bg3"],
                text_color=C["text"], border_color=C["border2"], width=300, justify="center",
            )
            self.pw2.pack(pady=(0, 4), ipady=4)
            self.pw2.bind("<Return>", lambda e: self.unlock())
            ctk.CTkLabel(form, text="Re-enter to confirm", font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 8))

        make_btn(
            form,
            "Unlock" if not self.is_new else "Create Vault",
            self.unlock,
            fg_color=C["accent"],
            text_color="white",
            width=200,
            height=36,
        ).pack(pady=(4, 0))

        self.err = ctk.CTkLabel(self, text="", font=FONT_SM, text_color=C["red"])
        self.err.pack(pady=(10, 0))

    def _check_password_strength(self, pw):
        if len(pw) < 12:
            return "Must be at least 12 characters"
        if not any(c.isupper() for c in pw):
            return "Must contain an uppercase letter"
        if not any(c.isdigit() for c in pw):
            return "Must contain a number"
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in pw):
            return "Must contain a special character (!@#$...)"
        return None

    def unlock(self):
        # Rate limiting
        if hasattr(self, '_locked_until') and self._locked_until:
            remaining = (self._locked_until - datetime.now()).seconds
            if datetime.now() < self._locked_until:
                self.err.configure(text=f"Too many attempts — wait {remaining}s")
                return

        pw = self.pw.get().strip()
        if self.is_new:
            err = self._check_password_strength(pw)
            if err:
                self.err.configure(text=err)
                return
            if pw != self.pw2.get().strip():
                self.err.configure(text="Passwords don't match")
                return
            ensure_vault_dir()
            save_vault({}, pw)
            self.on_login(pw, {})
        else:
            try:
                vault = load_vault(pw)
                if vault is None:
                    raise ValueError("wrong_password")
                self._failed_attempts = 0
                self._locked_until = None
                self.on_login(pw, vault)
            except ValueError as e:
                self._failed_attempts = getattr(self, '_failed_attempts', 0) + 1
                if self._failed_attempts >= 5:
                    delay = min(300, 10 * (2 ** (self._failed_attempts - 5)))
                    self._locked_until = datetime.now() + timedelta(seconds=delay)
                    self.err.configure(text=f"Too many attempts — locked for {delay}s")
                else:
                    if "corrupted" in str(e):
                        self.err.configure(text="Vault may be corrupted — check backup files")
                    else:
                        self.err.configure(text=f"Wrong password ({5 - self._failed_attempts} attempts left)")
                self.pw.delete(0, "end")


# ═══════════════════════════════════════════════
# MAIN APP SCREEN
# ═══════════════════════════════════════════════

class AppFrame(ctk.CTkFrame):
    def __init__(self, master, password, vault, on_lock):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.password = password
        self.vault = vault
        self.on_lock = on_lock
        self.config = load_config()
        self.revealed = set()
        self._group_by = "file"
        self._collapsed_groups = set()
        self._bulk_select_vars = {}
        self._clipboard_jobs = []
        self._search_var = tk.StringVar()

        # ── Top bar ──
        top = ctk.CTkFrame(self, fg_color=C["bg2"], corner_radius=0, height=48)
        top.pack(fill="x")
        top.pack_propagate(False)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(brand, text="●", font=("Segoe UI", 10), text_color=C["accent"]).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(brand, text="PUSHKEY", font=("Consolas", 13, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(brand, text=" vault", font=FONT_XS, text_color=C["text3"]).pack(side="left")

        make_btn(top, "Lock", self.lock, fg_color=C["red_bg"], text_color=C["red"]).pack(side="right", padx=(4, 12), pady=10)
        make_btn(top, "Password", self.change_master_password).pack(side="right", padx=2, pady=10)
        make_btn(top, "Export", self.export_vault).pack(side="right", padx=2, pady=10)
        make_btn(top, "Import", self.import_vault).pack(side="right", padx=2, pady=10)
        make_btn(top, "Template", self.show_template).pack(side="right", padx=2, pady=10)

        # Auto-lock
        self._lock_timeout = 5 * 60 * 1000
        self._lock_timer_id = None
        self._reset_lock_timer()
        self.master.bind("<Key>", lambda e: self._reset_lock_timer(), add="+")
        self.master.bind("<Button>", lambda e: self._reset_lock_timer(), add="+")

        # ── Tab view ──
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=C["bg"],
            segmented_button_fg_color=C["bg2"],
            segmented_button_selected_color=C["accent"],
            segmented_button_selected_hover_color=C["accent2"],
            segmented_button_unselected_color=C["bg2"],
            segmented_button_unselected_hover_color=C["bg4"],
            text_color=C["text"],
            corner_radius=0,
        )
        self.tabview.pack(fill="both", expand=True)

        self.tabview.add("Dashboard")
        self.tabview.add("All Keys")
        self.tabview.add("Projects")

        self.dash_frame = self.tabview.tab("Dashboard")
        self.keys_frame = self.tabview.tab("All Keys")
        self.proj_frame = self.tabview.tab("Projects")

        # Configure tab frames
        for f in (self.dash_frame, self.keys_frame, self.proj_frame):
            f.configure(fg_color=C["bg"])

        self.render_all()

    def save(self):
        save_vault(self.vault, self.password)
        save_config(self.config)

    def lock(self):
        self.revealed.clear()
        if self._lock_timer_id:
            self.after_cancel(self._lock_timer_id)
        # Cancel all pending clipboard clears and wipe clipboard now
        for job_id in self._clipboard_jobs:
            try: self.after_cancel(job_id)
            except: pass
        self._clipboard_jobs.clear()
        try: self.clipboard_clear()
        except: pass
        self.on_lock()

    def _reset_lock_timer(self):
        if self._lock_timer_id:
            self.after_cancel(self._lock_timer_id)
        self._lock_timer_id = self.after(self._lock_timeout, self.lock)

    def export_vault(self):
        path = filedialog.asksaveasfilename(
            title="Export encrypted vault",
            defaultextension=".pushkey-backup",
            filetypes=[("Pushkey Backup", "*.pushkey-backup"), ("All files", "*.*")],
        )
        if not path:
            return
        data = json.dumps({"vault": self.vault, "config": self.config}, indent=2)
        Path(path).write_bytes(encrypt_data(data, self.password))
        messagebox.showinfo("Exported", f"Vault exported to:\n{path}\n\nYou'll need your master password to import.")

    def import_vault(self):
        path = filedialog.askopenfilename(
            title="Import encrypted vault backup",
            filetypes=[("Pushkey Backup", "*.pushkey-backup"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            data = json.loads(decrypt_data(raw, self.password))
        except Exception:
            messagebox.showerror("Failed", "Could not decrypt. Wrong password or corrupted file.")
            return
        imported_vault = data.get("vault", {})
        imported_config = data.get("config", {})
        new_keys = [k for k in imported_vault if k not in self.vault]
        updated = [k for k in imported_vault if k in self.vault and imported_vault[k]["value"] != self.vault[k]["value"]]
        if not messagebox.askyesno("Import", f"Found {len(imported_vault)} keys.\n{len(new_keys)} new, {len(updated)} different.\n\nMerge into current vault?"):
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
        for w in self.dash_frame.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self.dash_frame, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=20, pady=(16, 0))

        keys = list(self.vault.items())
        total = len(keys)
        healthy = sum(1 for _, v in keys if health_status(v) == "healthy")
        warning = sum(1 for _, v in keys if health_status(v) == "warning")
        critical = sum(1 for _, v in keys if health_status(v) == "critical")
        projects = len(self.config.get("projects", {}))

        # Stats row
        stats_frame = ctk.CTkFrame(pad, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 16))

        for label, val, color in [
            ("Total keys", str(total), C["text"]),
            ("Healthy", str(healthy), C["green"]),
            ("Needs rotation", str(warning + critical), C["amber"] if warning + critical > 0 else C["green"]),
            ("Projects linked", str(projects), C["accent"]),
        ]:
            card = ctk.CTkFrame(stats_frame, fg_color=C["surface"], corner_radius=6)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkLabel(card, text=label, font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(card, text=val, font=("Segoe UI", 22, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(0, 8))

        # Action needed
        if critical + warning > 0:
            ctk.CTkLabel(pad, text="ACTION NEEDED", font=FONT_XS, text_color=C["red"]).pack(anchor="w", pady=(8, 4))
            for name, info in sorted(keys, key=lambda x: days_since(x[1].get("rotated") or x[1].get("created")), reverse=True):
                status = health_status(info)
                if status in ("critical", "warning"):
                    age = days_since(info.get("rotated") or info.get("created"))
                    provider = info.get("provider")
                    prov_data = PROVIDERS.get(provider, {})

                    row = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
                    row.pack(fill="x", pady=2)

                    left = ctk.CTkFrame(row, fg_color="transparent")
                    left.pack(side="left", fill="x", expand=True, padx=10, pady=8)
                    ctk.CTkLabel(left, text=name, font=FONT_MONO, text_color=C["text"]).pack(anchor="w")
                    msg = f"{age} days old"
                    msg += " — rotate immediately" if status == "critical" else " — rotate soon"
                    ctk.CTkLabel(left, text=msg, font=FONT_XS, text_color=health_color(status)).pack(anchor="w")

                    if prov_data.get("url"):
                        make_btn(row, f"Open {provider or 'provider'}",
                                 lambda u=prov_data["url"]: webbrowser.open(u),
                                 fg_color=C["bg3"]).pack(side="right", padx=8, pady=8)

        # All keys health list
        ctk.CTkLabel(pad, text="ALL KEYS", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(16, 4))

        if not keys:
            ctk.CTkLabel(pad, text="No keys yet. Go to 'All Keys' tab to add your first one.",
                         font=FONT, text_color=C["text3"]).pack(anchor="w", pady=20)
            return

        for name, info in sorted(keys, key=lambda x: x[0]):
            status = health_status(info)
            age = days_since(info.get("rotated") or info.get("created"))
            provider = info.get("provider", "")

            row = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4, cursor="hand2")
            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            cat = info.get("category", "General")
            cat_color = CAT_COLORS.get(cat, C["text3"])
            age_text = f"{age}d" if age != float("inf") else "?"

            left = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
            left.pack(side="left", fill="x", expand=True, pady=4, padx=8)
            left.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            lbl_name = ctk.CTkLabel(left, text=name, font=FONT_MONO_SM, text_color=C["text"], anchor="w", cursor="hand2")
            lbl_name.pack(anchor="w")
            lbl_name.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            meta_row = ctk.CTkFrame(left, fg_color="transparent")
            meta_row.pack(anchor="w")
            ctk.CTkLabel(meta_row, text=cat, font=FONT_XS, text_color=cat_color).pack(side="left")

            ctk.CTkLabel(row, text=age_text, font=FONT_XS, text_color=health_color(status), width=50).pack(side="right", padx=10)

    # ═══════════════════════════════════════════
    # ALL KEYS TAB
    # ═══════════════════════════════════════════

    def render_keys(self):
        for w in self.keys_frame.winfo_children():
            w.destroy()

        # Add key form
        form = ctk.CTkFrame(self.keys_frame, fg_color=C["surface"], corner_radius=6)
        form.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(form, text="Add or rotate a key", font=FONT_H3, text_color=C["text"]).pack(anchor="w", padx=12, pady=(10, 6))

        # Row 1: Name + Value + Category
        input_row = ctk.CTkFrame(form, fg_color="transparent")
        input_row.pack(fill="x", padx=12, pady=(0, 6))

        nf = ctk.CTkFrame(input_row, fg_color="transparent")
        nf.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(nf, text="NAME", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        self.add_name = ctk.CTkEntry(nf, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                                     border_color=C["border2"], width=180)
        self.add_name.pack(ipady=2)

        vf = ctk.CTkFrame(input_row, fg_color="transparent")
        vf.pack(side="left", padx=(0, 6), fill="x", expand=True)
        ctk.CTkLabel(vf, text="VALUE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        self.add_value = ctk.CTkEntry(vf, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                                      show="●", border_color=C["border2"])
        self.add_value.pack(fill="x", ipady=2)

        cf = ctk.CTkFrame(input_row, fg_color="transparent")
        cf.pack(side="left", padx=(0, 0))
        ctk.CTkLabel(cf, text="CATEGORY", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        self.add_cat = ctk.CTkOptionMenu(
            cf, values=["General", "Trading", "AI", "Database", "Cloud", "Payment", "Comms", "Security", "Crypto"],
            fg_color=C["bg3"], button_color=C["bg4"], button_hover_color=C["btn_hover"],
            text_color=C["text"], font=FONT_XS, width=110,
        )
        self.add_cat.set("General")
        self.add_cat.pack(ipady=2)

        # Row 2: Action buttons on their own line
        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        make_btn(btn_row, "+ Add Key", self.add_key, fg_color=C["green_bg"], text_color=C["green"]).pack(side="left", padx=(0, 6))
        make_btn(btn_row, "+ Add Group", self.add_group_manual, fg_color=C["accent2"], text_color="white").pack(side="left", padx=(0, 6))
        make_btn(btn_row, "📤 Upload File", self.bulk_upload_keys, fg_color=C["accent"], text_color="white").pack(side="left", padx=(0, 6))
        make_btn(btn_row, "📁 Scan Import Folder", self.scan_import_folder, fg_color=C["btn"], text_color=C["text2"]).pack(side="left", padx=(0, 6))
        make_btn(btn_row, "Open Folder", self.open_import_folder, fg_color=C["btn"], text_color=C["text3"]).pack(side="left")

        # Search bar
        search_bar = ctk.CTkFrame(self.keys_frame, fg_color=C["bg2"], corner_radius=0)
        search_bar.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkEntry(search_bar, textvariable=self._search_var,
                     placeholder_text="Search keys by name or provider...",
                     fg_color=C["bg3"], text_color=C["text"], corner_radius=6,
                     font=FONT_SM).pack(fill="x", ipady=2)
        self._search_var.trace_add("write", lambda *_: self._render_key_rows())

        # Scrollable key list
        self.keys_scroll = ctk.CTkScrollableFrame(self.keys_frame, fg_color=C["bg"], corner_radius=0)
        self.keys_scroll.pack(fill="both", expand=True, pady=(4, 0))

        self._render_key_rows()

    def _render_key_rows(self):
        for w in self.keys_scroll.winfo_children():
            w.destroy()
        self._bulk_select_vars = {}

        if not self.vault:
            ctk.CTkLabel(self.keys_scroll, text="No keys yet. Add your first key above.",
                         font=FONT, text_color=C["text3"]).pack(pady=40)
            return

        # Toolbar
        toolbar = ctk.CTkFrame(self.keys_scroll, fg_color="transparent")
        toolbar.pack(fill="x", padx=16, pady=(0, 2))
        make_btn(toolbar, "All", self._select_all_keys, width=50).pack(side="left", padx=(0, 2))
        make_btn(toolbar, "None", self._deselect_all_keys, width=50).pack(side="left", padx=(0, 8))
        make_btn(toolbar, "Delete Selected", self.bulk_delete_keys, fg_color=C["red_bg"], text_color="#FCA5A5").pack(side="left")
        by_file = self._group_by == "file"
        make_btn(toolbar, "By File" if not by_file else "By Category", self._toggle_group_by).pack(side="right")

        # Apply search filter
        query = self._search_var.get().lower().strip()
        filtered_vault = {
            n: i for n, i in self.vault.items()
            if not query or query in n.lower()
            or query in (i.get("provider") or "").lower()
            or query in (i.get("source_file") or "").lower()
            or query in (i.get("category") or "").lower()
        }
        if not filtered_vault:
            ctk.CTkLabel(self.keys_scroll, text=f'No keys match "{query}"',
                         font=FONT, text_color=C["text3"]).pack(pady=40)
            return

        # Build groups
        groups = {}
        for name, info in sorted(filtered_vault.items()):
            key = info.get("source_file") or "Manual" if self._group_by == "file" else info.get("category", "General")
            groups.setdefault(key, []).append((name, info))

        for group_key in sorted(groups.keys()):
            items = groups[group_key]
            collapsed = group_key in self._collapsed_groups

            hdr = ctk.CTkFrame(self.keys_scroll, fg_color="transparent")
            hdr.pack(fill="x", padx=16, pady=(10, 2))

            color = C["accent"] if self._group_by == "file" else CAT_COLORS.get(group_key, C["text3"])
            prefix_icon = "" if group_key == "Manual" else ""
            arrow = ">" if collapsed else "v"
            label_text = f"{arrow}  {group_key}  ({len(items)})"

            lbl = ctk.CTkLabel(hdr, text=label_text, font=FONT_XS, text_color=color, cursor="hand2", anchor="w")
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

        row = ctk.CTkFrame(self.keys_scroll, fg_color=C["surface"], corner_radius=4)
        row.pack(fill="x", padx=16, pady=1)

        # Checkbox
        sel_var = ctk.BooleanVar(value=False)
        self._bulk_select_vars[name] = sel_var
        ctk.CTkCheckBox(
            row, variable=sel_var, text="",
            fg_color=C["accent"], hover_color=C["accent2"],
            border_color=C["border2"], checkmark_color="white",
            width=20, height=20,
        ).pack(side="left", padx=(8, 2), pady=10)

        # Health dot via label
        dot_char = "●"
        ctk.CTkLabel(row, text=dot_char, font=("Consolas", 8), text_color=health_color(status), width=14).pack(side="left", padx=(2, 4))

        # Info area (clickable)
        info_frame = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
        info_frame.pack(side="left", fill="x", expand=True, pady=6)
        info_frame.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        name_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        name_row.pack(anchor="w")

        lbl_n = ctk.CTkLabel(name_row, text=name, font=("Consolas", 10, "bold"), text_color=C["text"], cursor="hand2", anchor="w")
        lbl_n.pack(side="left")
        lbl_n.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        if provider:
            cat = info.get("category", "General")
            lbl_p = ctk.CTkLabel(name_row, text=f" ({provider})", font=FONT_XS,
                                  text_color=CAT_COLORS.get(cat, C["text3"]), cursor="hand2")
            lbl_p.pack(side="left")
            lbl_p.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        meta_parts = []
        if info.get("source_file"):
            meta_parts.append(info["source_file"])
        if info.get("created"):
            meta_parts.append(f"Added {info['created'][:10]}")
        if info.get("rotated"):
            meta_parts.append(f"Rotated {info['rotated'][:10]}")
        if info.get("rotation_count", 0) > 0:
            meta_parts.append(f"{info['rotation_count']}x rotated")

        lbl_meta = ctk.CTkLabel(info_frame, text="  ·  ".join(meta_parts) if meta_parts else "",
                                 font=FONT_XS, text_color=C["text3"], cursor="hand2", anchor="w")
        lbl_meta.pack(anchor="w")
        lbl_meta.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        # Value display
        val = info["value"]
        if revealed:
            display = val
        elif len(val) > 8:
            display = val[:4] + "●" * min(16, len(val) - 8) + val[-4:]
        else:
            display = "●" * len(val)
        ctk.CTkLabel(row, text=display, font=FONT_MONO_SM,
                     text_color=C["green"] if revealed else C["text3"], width=200, anchor="w").pack(side="left", padx=4)

        # Buttons
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right", padx=6, pady=4)

        if prov_data.get("url"):
            make_btn(btns, "->", lambda u=prov_data["url"]: webbrowser.open(u), width=32).pack(side="left", padx=1)

        make_btn(btns, "Show" if not revealed else "Hide",
                 lambda n=name: self.toggle_reveal(n), width=48).pack(side="left", padx=1)
        make_btn(btns, "Copy", lambda v=val: self.copy_key(v), width=48).pack(side="left", padx=1)
        make_btn(btns, "Rotate", lambda n=name: self.rotate_key(n),
                 fg_color=C["amber_bg"], text_color=C["amber"], width=56).pack(side="left", padx=1)

        if info.get("history"):
            make_btn(btns, "History", lambda n=name: self.show_history(n), width=60).pack(side="left", padx=1)

        if info.get("source_file"):
            make_btn(btns, "Source", lambda n=name: self.show_source(n), width=56).pack(side="left", padx=1)

        make_btn(btns, "Del", lambda n=name: self.delete_key(n),
                 fg_color=C["red_bg"], text_color="#FCA5A5", width=40).pack(side="left", padx=1)

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
        if not messagebox.askyesno("Delete keys", f"Permanently delete {len(selected)} key(s)?\n\n{names_preview}"):
            return
        for name in selected:
            del self.vault[name]
            self.revealed.discard(name)
            log_event(f"bulk delete: removed {name}")
        self.save()
        self.render_all()

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
            if not messagebox.askyesno("Rotate key?", f"'{name}' already exists.\n\nReplace with new value?\n(Old value saved as backup)"):
                return
            old_val = self.vault[name]["value"]
            self.vault[name].setdefault("history", [])
            self.vault[name]["history"].insert(0, {"value": old_val, "retired": now})
            self.vault[name]["history"] = self.vault[name]["history"][:10]
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
        injected, errors = self._auto_inject_key(name)
        if injected:
            msg += f" and synced to {injected} project(s)"
        if errors:
            msg += f"\n\nSync failed for {len(errors)} project(s):\n" + "\n".join(errors)

        self.add_name.delete(0, "end")
        self.add_value.delete(0, "end")
        self.render_all()
        messagebox.showinfo("Done", msg)

    def add_group_manual(self):
        """Dialog to manually add multiple keys under one named group."""
        win = ctk.CTkToplevel(self)
        win.title("Add Key Group")
        win.geometry("560x540")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Add Key Group", font=FONT_H2, text_color=C["text"]).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(win, text="All keys in this group will appear together in the vault.",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=16, pady=(0, 10))

        # Group name row
        gf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        gf.pack(fill="x", padx=16, pady=(0, 10))
        top_row = ctk.CTkFrame(gf, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(top_row, text="GROUP NAME", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(0, 8))
        group_var = tk.StringVar()
        ctk.CTkEntry(top_row, textvariable=group_var, placeholder_text="e.g. plaid, stripe, alpaca",
                     fg_color=C["bg3"], text_color=C["text"], width=260).pack(side="left")

        # Scrollable key rows
        ctk.CTkLabel(win, text="KEYS", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=16, pady=(0, 4))
        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0, height=280)
        scroll.pack(fill="x", padx=16)

        key_rows = []  # list of (name_var, value_var, secret_var)

        def add_row(name_hint="", secret=False):
            row = ctk.CTkFrame(scroll, fg_color=C["surface"], corner_radius=4)
            row.pack(fill="x", pady=2)

            nv = tk.StringVar(value=name_hint)
            vv = tk.StringVar()
            sv = tk.BooleanVar(value=secret)

            nf = ctk.CTkFrame(row, fg_color="transparent")
            nf.pack(side="left", padx=(8, 4), pady=6, fill="x", expand=True)
            ctk.CTkLabel(nf, text="KEY NAME", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
            ctk.CTkEntry(nf, textvariable=nv, fg_color=C["bg3"], text_color=C["text"],
                         placeholder_text="e.g. CLIENT_ID").pack(fill="x", ipady=2)

            vf = ctk.CTkFrame(row, fg_color="transparent")
            vf.pack(side="left", padx=(0, 4), pady=6, fill="x", expand=True)
            ctk.CTkLabel(vf, text="VALUE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
            ctk.CTkEntry(vf, textvariable=vv, fg_color=C["bg3"], text_color=C["text"],
                         show="●", placeholder_text="paste value").pack(fill="x", ipady=2)

            ctk.CTkCheckBox(row, text="🔒", variable=sv, fg_color=C["accent"],
                            hover_color=C["accent2"], width=40).pack(side="left", padx=(0, 6), pady=6)

            def remove(r=row, entry=(nv, vv, sv)):
                key_rows.remove(entry)
                r.destroy()

            make_btn(row, "✕", remove, fg_color=C["red_bg"], text_color=C["red"], width=30).pack(side="left", padx=(0, 8), pady=6)
            key_rows.append((nv, vv, sv))

        # Start with two rows (common case: id + secret)
        add_row("CLIENT_ID", False)
        add_row("SECRET", True)

        # Add row button
        btn_bar = ctk.CTkFrame(win, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(6, 0))
        make_btn(btn_bar, "+ Add Another Key", add_row).pack(side="left")

        # Save button
        def save_group():
            group = group_var.get().strip()
            if not group:
                messagebox.showwarning("Missing", "Enter a group name.", parent=win)
                return

            prefix = re.sub(r'[^A-Z0-9]', '_', group.upper())
            prefix = re.sub(r'_+', '_', prefix).strip('_')
            source_label = f"{group}.manual"
            now = datetime.now().isoformat()
            added = []

            for nv, vv, sv in key_rows:
                raw_name = nv.get().strip().upper().replace(" ", "_")
                value = vv.get().strip()
                if not raw_name or not value:
                    continue
                # Prepend prefix if not already there
                name = raw_name if raw_name.startswith(prefix + "_") or raw_name == prefix else f"{prefix}_{raw_name}"
                provider = detect_provider(name, value)
                if name in self.vault:
                    old_val = self.vault[name]["value"]
                    self.vault[name].setdefault("history", [])
                    self.vault[name]["history"].insert(0, {"value": old_val, "retired": now})
                    self.vault[name]["history"] = self.vault[name]["history"][:10]
                    self.vault[name]["value"] = value
                    self.vault[name]["rotated"] = now
                    self.vault[name]["rotation_count"] = self.vault[name].get("rotation_count", 0) + 1
                    self.vault[name]["secret"] = sv.get()
                    self.vault[name]["source_file"] = source_label
                    self.vault[name]["imported_at"] = now
                else:
                    self.vault[name] = {
                        "value": value, "category": "General",
                        "provider": provider, "created": now,
                        "rotated": None, "rotation_count": 0, "previous": None,
                        "secret": sv.get(), "source_file": source_label, "imported_at": now,
                    }
                added.append(name)

            if not added:
                messagebox.showwarning("Nothing added", "Fill in at least one key name and value.", parent=win)
                return

            self._refresh_all_projects()
            self.save()
            win.destroy()
            self.render_all()
            messagebox.showinfo("Saved", f"✓ Added {len(added)} key(s) to group '{group}':\n" + "\n".join(added))

        make_btn(btn_bar, "✓ Save Group", save_group, fg_color=C["green_bg"], text_color=C["green"]).pack(side="right")

    def open_import_folder(self):
        ensure_vault_dir()
        import subprocess
        subprocess.Popen(f'explorer "{IMPORT_DIR}"')

    def scan_import_folder(self):
        ensure_vault_dir()
        files = [f for f in IMPORT_DIR.iterdir()
                 if f.is_file() and f.suffix.lower() in ('.txt', '.env', '.pushkey')
                 and f.name != "README.txt"]
        if not files:
            messagebox.showinfo(
                "Import Folder Empty",
                f"No key files found in:\n{IMPORT_DIR}\n\n"
                "Drop .txt or .env files into that folder,\nthen scan again."
            )
            return

        parsed_entries = []
        errors = []
        for path in files:
            basename = path.name
            try:
                file_entries, file_errors = _parse_env_file(str(path))
                for err in file_errors:
                    errors.append(f"{basename}: {err}")
                for fe in file_entries:
                    name, value = fe['name'], fe['value']
                    provider = detect_provider(name, value)
                    is_new = name not in self.vault
                    parsed_entries.append({
                        "name": name, "value": value, "provider": provider,
                        "is_new": is_new, "file": basename,
                        "line": fe['line'], "raw_line": fe.get('raw_line', ''),
                        "secret": fe.get('secret', False),
                    })
            except Exception as e:
                errors.append(f"{basename}: {str(e)}")

        if not parsed_entries:
            msg = f"No valid keys found in {len(files)} file(s)."
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(errors[:5])
            messagebox.showwarning("Nothing parsed", msg)
            return

        confirmed = self._show_bulk_preview_dialog(parsed_entries, errors)
        if not confirmed:
            return

        added = []
        now = datetime.now().isoformat()
        for entry in confirmed:
            name, value = entry["name"], entry["value"]
            provider = entry["provider"]
            source_file = entry.get("file")
            source_line = entry.get("line")
            source_raw = entry.get("raw_line", "")
            if name in self.vault:
                old_val = self.vault[name]["value"]
                self.vault[name].setdefault("history", [])
                self.vault[name]["history"].insert(0, {"value": old_val, "retired": now})
                self.vault[name]["history"] = self.vault[name]["history"][:10]
                self.vault[name]["value"] = value
                self.vault[name]["rotated"] = now
                self.vault[name]["rotation_count"] = self.vault[name].get("rotation_count", 0) + 1
                self.vault[name]["source_file"] = source_file
                self.vault[name]["imported_at"] = now
                self.vault[name]["secret"] = entry.get("secret", False)
                added.append(f"{name} (rotated)")
            else:
                self.vault[name] = {
                    "value": value, "category": "General", "provider": provider,
                    "created": now, "rotated": None, "rotation_count": 0, "previous": None,
                    "source_file": source_file, "source_line": source_line,
                    "source_raw": source_raw, "imported_at": now,
                    "secret": entry.get("secret", False),
                }
                added.append(name)

        self.save()
        self._refresh_all_projects()
        self.render_all()
        messagebox.showinfo("Scan Complete",
            f"✓ Imported {len(added)} key(s) from {len(files)} file(s)\n\n"
            f"Folder: {IMPORT_DIR}")

    def bulk_upload_keys(self):
        paths = filedialog.askopenfilenames(
            title="Select text files with keys",
            filetypes=[("Env / text files", "*.env *.txt *.pushkey"), ("All files", "*.*")],
        )
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
                    name = fe["name"]
                    value = fe["value"]
                    provider = detect_provider(name, value)
                    is_new = name not in self.vault
                    parsed_entries.append({
                        "name": name, "value": value, "provider": provider,
                        "is_new": is_new, "file": basename, "line": fe["line"],
                        "raw_line": fe.get("raw_line", ""), "secret": fe.get("secret", False),
                    })
            except Exception as e:
                errors.append(f"{basename}: {e}")

        if not parsed_entries:
            msg = "No valid keys found in the selected files."
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    msg += f"\n... and {len(errors) - 5} more"
            messagebox.showwarning("No keys parsed", msg)
            return

        confirmed = self._show_bulk_preview_dialog(parsed_entries, errors)
        if not confirmed:
            return

        now = datetime.now().isoformat()
        added = []
        for entry in confirmed:
            name = entry["name"]
            value = entry["value"]
            provider = entry["provider"]
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
                if source_file:
                    self.vault[name].update({"source_file": source_file, "source_line": source_line, "source_raw": source_raw, "imported_at": now})
                if entry.get("secret"):
                    self.vault[name]["secret"] = True
                added.append(f"{name} (rotated)")
            else:
                category = self.add_cat.get() if hasattr(self, "add_cat") else "General"
                self.vault[name] = {
                    "value": value, "category": category, "provider": provider,
                    "created": now, "rotated": None, "rotation_count": 0, "previous": None,
                    "source_file": source_file, "source_line": source_line,
                    "source_raw": source_raw, "imported_at": now,
                    "secret": entry.get("secret", False),
                }
                log_event(f"bulk: imported {name} from {source_file}:{source_line}")
                added.append(name)

        self.save()
        self._refresh_all_projects()
        injected, _ = self._auto_inject_keys_bulk([e["name"] for e in confirmed])

        msg = f"Imported {len(added)} key(s)"
        if injected:
            msg += f" and synced to {injected} project(s)"

        self.render_all()
        messagebox.showinfo("Bulk Upload Complete", msg)

    def _show_bulk_preview_dialog(self, parsed_entries, errors):
        win = ctk.CTkToplevel(self)
        win.title("Review Keys Before Import")
        win.geometry("720x520")
        win.transient(self)
        win.grab_set()
        win.configure(fg_color=C["bg2"])

        ctk.CTkLabel(win, text=f"Preview: {len(parsed_entries)} key(s) parsed",
                     font=FONT_H2, text_color=C["text"]).pack(pady=(12, 4), padx=12, anchor="w")
        if errors:
            ctk.CTkLabel(win, text=f"{len(errors)} parsing error(s) — some keys skipped",
                         font=FONT_XS, text_color=C["amber"]).pack(padx=12, anchor="w", pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=4, height=300)
        scroll.pack(fill="both", expand=True, padx=12, pady=8)

        checks = {}
        for entry in parsed_entries:
            row = ctk.CTkFrame(scroll, fg_color=C["surface"], corner_radius=4)
            row.pack(fill="x", pady=1)

            var = ctk.BooleanVar(value=True)
            checks[entry["name"]] = var
            ctk.CTkCheckBox(row, variable=var, text="",
                            fg_color=C["accent"], hover_color=C["accent2"],
                            border_color=C["border2"], checkmark_color="white",
                            width=20, height=20).pack(side="left", padx=(6, 2), pady=6)

            ctk.CTkLabel(row, text=entry["name"], font=FONT_MONO_SM, text_color=C["text"],
                         width=220, anchor="w").pack(side="left", padx=4)

            prov = entry["provider"] or "?"
            prov_color = CAT_COLORS.get(PROVIDERS.get(prov, {}).get("category", "General"), C["text3"])
            ctk.CTkLabel(row, text=prov, font=FONT_XS, text_color=prov_color, width=100).pack(side="left", padx=4)

            status = "new" if entry["is_new"] else "rotate"
            status_color = C["green"] if entry["is_new"] else C["amber"]
            ctk.CTkLabel(row, text=status, font=FONT_XS, text_color=status_color).pack(side="left")

            if entry.get("secret"):
                ctk.CTkLabel(row, text="[secret]", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(4, 0))

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=8)

        def import_selected():
            selected = [e for e in parsed_entries if checks[e["name"]].get()]
            win.selected = selected
            win.destroy()

        make_btn(btn_frame, f"Import {len(parsed_entries)} keys", import_selected,
                 fg_color=C["green_bg"], text_color=C["green"], height=32).pack(side="left", padx=(0, 4))
        make_btn(btn_frame, "Cancel", lambda: (setattr(win, "selected", None), win.destroy())).pack(side="left")

        win.selected = None
        self.wait_window(win)
        return win.selected

    def _auto_inject_keys_bulk(self, key_names):
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
        count = 0
        errors = []
        for proj_name, proj_info in self.config.get("projects", {}).items():
            proj_keys = proj_info.get("keys", [])
            if key_name in proj_keys or not proj_keys:
                path = proj_info.get("path")
                if path and os.path.isdir(path):
                    keys_to_write = proj_keys if proj_keys else None
                    try:
                        inject_env_file(path, self.vault, keys_to_write)
                        count += 1
                    except Exception as e:
                        log_event(f"env inject failed for {path}: {e}")
                        errors.append(f"{proj_name}: {e}")
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
        job_id = self.after(30000, self.clipboard_clear)
        self._clipboard_jobs.append(job_id)

    def delete_key(self, name):
        if messagebox.askyesno("Delete?", f"Delete '{name}'?\nThis cannot be undone."):
            del self.vault[name]
            self.revealed.discard(name)
            self.save()
            self.render_all()

    def rotate_key(self, name):
        info = self.vault.get(name)
        if not info:
            return
        provider = info.get("provider")
        prov_data = PROVIDERS.get(provider, {})

        if prov_data.get("url"):
            webbrowser.open(prov_data["url"])

        win = ctk.CTkToplevel(self)
        win.title(f"Rotate {name}")
        win.geometry("500x240")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Rotate {name}", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        if provider:
            ctk.CTkLabel(win, text=f"{provider} dashboard opened in browser — copy your new key",
                         font=FONT_XS, text_color=C["text3"]).pack()

        ctk.CTkLabel(win, text="PASTE NEW KEY VALUE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=20, pady=(16, 2))
        new_val = ctk.CTkEntry(win, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                               border_color=C["border2"], width=440)
        new_val.pack(padx=20, ipady=4)
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
                msg += f"\n\nSync failed for {len(errors)} project(s):\n" + "\n".join(errors)
            messagebox.showinfo("Rotated", msg)

        new_val.bind("<Return>", lambda e: do_rotate())
        make_btn(win, "Save & Sync", do_rotate, fg_color=C["green_bg"], text_color=C["green"], width=160, height=34).pack(pady=16)

    def show_source(self, name):
        info = self.vault.get(name, {})
        source_file = info.get("source_file")
        source_line = info.get("source_line")
        source_raw = info.get("source_raw", "")
        imported_at = info.get("imported_at", "?")

        if not source_file:
            messagebox.showinfo("No source", f"Key '{name}' was added manually, not from bulk upload.")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Source: {name}")
        win.geometry("560x300")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Source Information — {name}", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(12, 8), padx=12, anchor="w")

        info_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=4)
        info_frame.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(info_frame, text="FILE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(info_frame, text=f"{source_file}:{source_line}", font=FONT_MONO_SM,
                     text_color=C["text"]).pack(anchor="w", padx=10, pady=(0, 6))
        ctk.CTkLabel(info_frame, text="IMPORTED", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
        ctk.CTkLabel(info_frame, text=imported_at[:16].replace("T", " "), font=FONT_MONO_SM,
                     text_color=C["text"]).pack(anchor="w", padx=10, pady=(0, 6))

        ctk.CTkLabel(win, text="ORIGINAL LINE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=12, pady=(4, 2))
        raw_box = ctk.CTkTextbox(win, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                                  height=80, corner_radius=4)
        raw_box.pack(fill="x", padx=12, pady=(0, 8))
        raw_box.insert("1.0", source_raw or "(no data)")
        raw_box.configure(state="disabled")

        make_btn(win, "Close", win.destroy, width=100).pack(pady=8)

    def show_history(self, name):
        info = self.vault.get(name, {})
        history = info.get("history", [])
        if not history:
            messagebox.showinfo("No history", f"No rotation history for {name}")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"History: {name}")
        win.geometry("540x420")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Rotation History — {name}", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(12, 4))
        ctk.CTkLabel(win, text=f"{len(history)} previous value(s) stored", font=FONT_XS,
                     text_color=C["text3"]).pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=16)

        for i, entry in enumerate(history):
            row = ctk.CTkFrame(scroll, fg_color=C["surface"], corner_radius=4)
            row.pack(fill="x", pady=2)

            retired = entry.get("retired", "?")[:16].replace("T", " ")
            ctk.CTkLabel(row, text=f"#{i+1}  retired {retired}", font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))

            val = entry["value"]
            masked = val[:4] + "●" * min(12, len(val) - 8) + val[-4:] if len(val) > 8 else "●" * len(val)

            rv = ctk.CTkFrame(row, fg_color="transparent")
            rv.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkLabel(rv, text=masked, font=FONT_MONO_SM, text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)
            make_btn(rv, "Copy", lambda v=val: (self.clipboard_clear(), self.clipboard_append(v),
                     self.after(30000, self.clipboard_clear)), width=50).pack(side="right")

        make_btn(win, "Close", win.destroy, width=100).pack(pady=12)

    def change_master_password(self):
        win = ctk.CTkToplevel(self)
        win.title("Change Master Password")
        win.geometry("420x300")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Change Master Password", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(16, 12))

        fields = {}
        for label_text, key in [("CURRENT PASSWORD", "current"), ("NEW PASSWORD", "new"), ("CONFIRM NEW", "confirm")]:
            ctk.CTkLabel(win, text=label_text, font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=24)
            e = ctk.CTkEntry(win, show="●", font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                             border_color=C["border2"], width=340)
            e.pack(padx=24, ipady=4, pady=(0, 6))
            fields[key] = e

        err = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["red"])
        err.pack()

        def do_change():
            current = fields["current"].get()
            new_pw = fields["new"].get().strip()
            confirm = fields["confirm"].get().strip()
            if current != self.password:
                err.configure(text="Current password is wrong")
                return
            if len(new_pw) < 6:
                err.configure(text="New password must be at least 6 characters")
                return
            if new_pw != confirm:
                err.configure(text="New passwords don't match")
                return
            self.password = new_pw
            save_vault(self.vault, self.password)
            win.destroy()
            messagebox.showinfo("Done", "Master password changed. Vault re-encrypted.")

        make_btn(win, "Change Password", do_change, fg_color=C["accent"], text_color="white", width=200).pack(pady=12)

    # ═══════════════════════════════════════════
    # KEY DETAIL POPUP
    # ═══════════════════════════════════════════

    def show_key_detail(self, name):
        info = self.vault.get(name, {})
        if not info:
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Key Details — {name}")
        win.geometry("620x600")
        win.minsize(480, 400)
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        # Header
        header = ctk.CTkFrame(win, fg_color=C["bg3"], corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        status = health_status(info)
        ctk.CTkLabel(header, text="●", font=("Consolas", 12), text_color=health_color(status)).pack(side="left", padx=(16, 4), pady=16)
        ctk.CTkLabel(header, text=name, font=FONT_H2, text_color=C["text"]).pack(side="left", pady=16)

        provider = info.get("provider")
        if provider:
            cat = info.get("category", "General")
            ctk.CTkLabel(header, text=f"  {provider}", font=FONT_SM,
                         text_color=CAT_COLORS.get(cat, C["text3"])).pack(side="left")

        # Scrollable body
        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg2"], corner_radius=0)
        scroll.pack(fill="both", expand=True)

        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=16, pady=12)

        def info_field(label, value, mono=False, fg=None):
            f = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
            f.pack(fill="x", pady=2)
            ctk.CTkLabel(f, text=label, font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(f, text=value or "—", font=FONT_MONO_SM if mono else FONT_SM,
                         text_color=fg or C["text"], wraplength=520, justify="left",
                         anchor="w").pack(anchor="w", padx=10, pady=(0, 6))

        # Value row
        val = info["value"]
        revealed = name in self.revealed
        masked = val[:4] + "●" * min(20, max(0, len(val) - 8)) + val[-4:] if len(val) > 8 else "●" * len(val)
        vf = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
        vf.pack(fill="x", pady=2)
        ctk.CTkLabel(vf, text="VALUE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        vrow = ctk.CTkFrame(vf, fg_color="transparent")
        vrow.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(vrow, text=val if revealed else masked, font=FONT_MONO_SM,
                     text_color=C["green"] if revealed else C["text3"], anchor="w").pack(side="left", fill="x", expand=True)
        make_btn(vrow, "Copy", lambda v=val: self.copy_key(v), width=50).pack(side="right", padx=(4, 0))
        make_btn(vrow, "Hide" if revealed else "Reveal",
                 lambda n=name: (self.toggle_reveal(n), win.destroy(), self.show_key_detail(n)),
                 width=60).pack(side="right", padx=4)

        info_field("CATEGORY", info.get("category", "General"))
        info_field("PROVIDER", provider or "Unknown")
        info_field("CREATED", (info.get("created") or "")[:16].replace("T", " ") or "—", mono=True)
        info_field("LAST ROTATED", (info.get("rotated") or "")[:16].replace("T", " ") or "Never", mono=True)
        info_field("ROTATION COUNT", str(info.get("rotation_count", 0)))

        age = days_since(info.get("rotated") or info.get("created"))
        age_str = f"{age} days" if age != float("inf") else "Unknown"
        info_field("AGE / HEALTH", f"{age_str} — {health_status(info).upper()}", fg=health_color(status))

        # Import source
        if info.get("source_file"):
            ctk.CTkLabel(pad, text="IMPORT SOURCE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(14, 4))
            sf = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
            sf.pack(fill="x", pady=2)
            ctk.CTkLabel(sf, text="FILE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(sf, text=f"{info['source_file']} : line {info.get('source_line', '?')}",
                         font=FONT_MONO_SM, text_color=C["text"]).pack(anchor="w", padx=10, pady=(0, 4))
            imp = (info.get("imported_at") or "")[:16].replace("T", " ")
            if imp:
                ctk.CTkLabel(sf, text="IMPORTED", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                ctk.CTkLabel(sf, text=imp, font=FONT_MONO_SM, text_color=C["text"]).pack(anchor="w", padx=10, pady=(0, 4))
            raw = info.get("source_raw", "")
            if raw:
                ctk.CTkLabel(sf, text="ORIGINAL LINE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                rt = ctk.CTkTextbox(sf, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                                    height=70, corner_radius=4)
                rt.pack(fill="x", padx=10, pady=(0, 8))
                rt.insert("1.0", raw)
                rt.configure(state="disabled")

        # History summary
        history = info.get("history", [])
        if history:
            ctk.CTkLabel(pad, text=f"HISTORY ({len(history)} previous values)",
                         font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(14, 4))
            for i, entry in enumerate(history[:3]):
                hf = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
                hf.pack(fill="x", pady=1)
                retired = (entry.get("retired") or "")[:16].replace("T", " ")
                ctk.CTkLabel(hf, text=f"#{i+1}  retired {retired}", font=FONT_XS,
                             text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                v = entry["value"]
                mv = v[:4] + "●" * min(12, len(v) - 8) + v[-4:] if len(v) > 8 else "●" * len(v)
                ctk.CTkLabel(hf, text=mv, font=FONT_MONO_SM, text_color=C["text2"]).pack(anchor="w", padx=10, pady=(0, 4))
            if len(history) > 3:
                ctk.CTkLabel(pad, text=f"  ... and {len(history) - 3} more",
                             font=FONT_XS, text_color=C["text3"]).pack(anchor="w")

        # Action bar
        bar = ctk.CTkFrame(win, fg_color=C["bg3"], corner_radius=0, height=56)
        bar.pack(fill="x", pady=0)
        bar.pack_propagate(False)

        inner_bar = ctk.CTkFrame(bar, fg_color="transparent")
        inner_bar.pack(side="left", padx=12, pady=10)

        make_btn(inner_bar, "Rotate Key", lambda: (win.destroy(), self.rotate_key(name)),
                 fg_color=C["amber_bg"], text_color=C["amber"]).pack(side="left", padx=4)
        if history:
            make_btn(inner_bar, "Full History", lambda: self.show_history(name), width=100).pack(side="left", padx=4)
        if info.get("source_file"):
            make_btn(inner_bar, "Source Detail", lambda: self.show_source(name), width=100).pack(side="left", padx=4)
        if provider and PROVIDERS.get(provider, {}).get("url"):
            make_btn(inner_bar, f"Open {provider}",
                     lambda u=PROVIDERS[provider]["url"]: webbrowser.open(u),
                     fg_color=C["accent"], text_color="white").pack(side="left", padx=4)

        right_bar = ctk.CTkFrame(bar, fg_color="transparent")
        right_bar.pack(side="right", padx=12, pady=10)
        make_btn(right_bar, "Delete", lambda: (win.destroy(), self.delete_key(name)),
                 fg_color=C["red_bg"], text_color="#FCA5A5", width=70).pack(side="right", padx=4)
        make_btn(right_bar, "Close", win.destroy, width=70).pack(side="right", padx=4)

    # ═══════════════════════════════════════════
    # TEMPLATE VIEWER
    # ═══════════════════════════════════════════

    def show_template(self):
        template_path = Path(__file__).parent / "KEY_IMPORT_TEMPLATE.md"

        win = ctk.CTkToplevel(self)
        win.title("Key Import Template")
        win.geometry("680x580")
        win.minsize(500, 400)
        win.configure(fg_color=C["bg2"])
        win.transient(self)

        ctk.CTkLabel(win, text="Key Import Template", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(12, 4), padx=16, anchor="w")
        ctk.CTkLabel(win, text="Reference format for bulk upload files (txt / .env)",
                     font=FONT_XS, text_color=C["text3"]).pack(padx=16, anchor="w", pady=(0, 8))

        txt = ctk.CTkTextbox(win, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                              corner_radius=4, wrap="none")
        txt.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        content = template_path.read_text(encoding="utf-8") if template_path.exists() else "(Template file not found)"
        txt.insert("1.0", content)
        txt.configure(state="disabled")

        btn_bar = ctk.CTkFrame(win, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=8)
        if template_path.exists():
            make_btn(btn_bar, "Open in Editor", lambda: os.startfile(str(template_path))).pack(side="left")
        make_btn(btn_bar, "Close", win.destroy, width=80).pack(side="right")

    # ═══════════════════════════════════════════
    # PROJECTS TAB
    # ═══════════════════════════════════════════

    def render_projects(self):
        for w in self.proj_frame.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self.proj_frame, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True)

        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=16, pady=12)

        # Add project form
        form = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6)
        form.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(form, text="Link a project folder", font=FONT_H3, text_color=C["text"]).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(form, text="Click Browse, pick your project folder — name and path fill in automatically.",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=12, pady=(0, 10))

        # Path row
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(r1, text="FOLDER PATH", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        path_row = ctk.CTkFrame(r1, fg_color="transparent")
        path_row.pack(fill="x")
        self.proj_path_var = ctk.StringVar()
        path_entry = ctk.CTkEntry(path_row, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                                   border_color=C["border2"], textvariable=self.proj_path_var)
        path_entry.pack(side="left", fill="x", expand=True, ipady=4)
        make_btn(path_row, "Browse", self.browse_folder, fg_color=C["accent"], text_color="white", width=80).pack(side="left", padx=(6, 0))

        # Name row
        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(r2, text="PROJECT NAME", font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        name_row = ctk.CTkFrame(r2, fg_color="transparent")
        name_row.pack(fill="x")
        self.proj_name = ctk.CTkEntry(name_row, font=FONT_SM, fg_color=C["bg3"], text_color=C["text"],
                                       border_color=C["border2"])
        self.proj_name.pack(side="left", fill="x", expand=True, ipady=4)
        make_btn(name_row, "+ Link Project", self.add_project, fg_color=C["green_bg"], text_color=C["green"], width=110).pack(side="left", padx=(6, 0))

        # Project list
        projects = self.config.get("projects", {})
        if not projects:
            ctk.CTkLabel(pad, text="No projects linked yet.\nAdd a project folder above, and Pushkey will\nauto-write .env files when you add or rotate keys.",
                         font=FONT, text_color=C["text3"], justify="center").pack(pady=30)
            return

        ctk.CTkLabel(pad, text="LINKED PROJECTS", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(0, 6))

        for proj_name, proj_info in sorted(projects.items()):
            proj_keys = proj_info.get("keys", [])
            matched = self._auto_match_keys(proj_name)
            has_keys = len(proj_keys) > 0 or len(matched) > 0
            dot_color = C["green"] if has_keys else C["red"]

            card = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6)
            card.pack(fill="x", pady=3)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=12, pady=8)

            name_row2 = ctk.CTkFrame(left, fg_color="transparent")
            name_row2.pack(anchor="w")
            ctk.CTkLabel(name_row2, text="●", font=("Consolas", 10), text_color=dot_color).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(name_row2, text=proj_name, font=FONT_H3, text_color=C["text"]).pack(side="left")

            ctk.CTkLabel(left, text=proj_info.get("path", ""), font=FONT_MONO_SM, text_color=C["text3"], anchor="w").pack(anchor="w")

            if proj_keys:
                key_text = f"{len(proj_keys)} keys assigned"
                key_color = C["green"]
            elif matched:
                key_text = f"No keys assigned — {len(matched)} auto-matched available (click Assign Keys)"
                key_color = C["amber"]
            else:
                key_text = "No keys assigned — no matching keys found in vault"
                key_color = C["red"]
            ctk.CTkLabel(left, text=key_text, font=FONT_XS, text_color=key_color, anchor="w").pack(anchor="w")

            btn_f = ctk.CTkFrame(card, fg_color="transparent")
            btn_f.pack(side="right", padx=8, pady=8)
            make_btn(btn_f, "Sync now", lambda p=proj_name: self.sync_project(p),
                     fg_color=C["accent"], text_color="white", width=80).pack(pady=2)
            make_btn(btn_f, "Assign Keys", lambda p=proj_name: self.assign_keys_to_project(p), width=80).pack(pady=2)
            make_btn(btn_f, "Remove", lambda p=proj_name: self.remove_project(p),
                     fg_color=C["red_bg"], text_color="#FCA5A5", width=80).pack(pady=2)

    def browse_folder(self):
        onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
        desktop = Path.home() / "Desktop"
        start = onedrive_desktop if onedrive_desktop.exists() else (desktop if desktop.exists() else Path.home())
        path = filedialog.askdirectory(title="Select project folder", initialdir=str(start))
        if path:
            self.proj_path_var.set(path)
            self.proj_name.delete(0, "end")
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

        try:
            inject_env_file(path, self.vault)
        except Exception as e:
            messagebox.showwarning("Sync warning", f"Could not write .env:\n{e}")

        self.save()
        self.proj_name.delete(0, "end")
        self.proj_path_var.set("")
        self.render_projects()
        messagebox.showinfo("Linked", f"'{name}' linked and .env written to:\n{path}")

    def _refresh_project_keys(self, proj_name):
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

        new_keys = self._refresh_project_keys(proj_name)
        assigned = set(proj.get("keys", []))
        keys_to_write = sorted(k for k in assigned if k in self.vault)

        win = ctk.CTkToplevel(self)
        win.title("Confirm Sync")
        win.geometry("520x480")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Confirm .env Sync", font=FONT_H2, text_color=C["text"]).pack(pady=(14, 4), padx=16, anchor="w")

        folder_f = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=4)
        folder_f.pack(fill="x", padx=16, pady=(4, 8))
        ctk.CTkLabel(folder_f, text="WRITING TO", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(folder_f, text=os.path.join(path, ".env"), font=FONT_MONO_SM,
                     text_color=C["green"], wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        if new_keys:
            ctk.CTkLabel(win, text=f"+ {len(new_keys)} newly matched key(s) added since last sync",
                         font=FONT_XS, text_color=C["amber"]).pack(anchor="w", padx=16, pady=(0, 4))

        # Read existing .env to detect rotations
        env_path = os.path.join(path, ".env")
        existing_env = {}
        try:
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        result = _parse_env_line(line)
                        if result:
                            existing_env[result[0]] = result[1]
        except Exception:
            pass

        def mask(val):
            if not val: return "●●●●"
            return "●" * min(8, max(4, len(val) - 4)) + val[-4:]

        rotating = [k for k in keys_to_write if k in existing_env and existing_env[k] != self.vault[k]["value"]]
        adding   = [k for k in keys_to_write if k not in existing_env]
        unchanged= [k for k in keys_to_write if k in existing_env and existing_env[k] == self.vault[k]["value"]]

        ctk.CTkLabel(win, text=f"KEYS TO WRITE  ({len(keys_to_write)})", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=16, pady=(0, 4))

        keys_scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=4, height=200)
        keys_scroll.pack(fill="x", padx=16, pady=(0, 8))

        for k in keys_to_write:
            new_val = self.vault[k]["value"]
            row = ctk.CTkFrame(keys_scroll, fg_color=C["surface"], corner_radius=4)
            row.pack(fill="x", pady=1)

            if k in rotating:
                # Before → After
                old_val = existing_env[k]
                ctk.CTkLabel(row, text=k, font=FONT_MONO_SM, text_color=C["amber"], anchor="w", width=200).pack(side="left", padx=(8, 4), pady=5)
                ctk.CTkLabel(row, text=mask(old_val), font=FONT_MONO_SM, text_color=C["text3"], anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=" → ", font=FONT_XS, text_color=C["text3"]).pack(side="left")
                ctk.CTkLabel(row, text=mask(new_val), font=FONT_MONO_SM, text_color=C["amber"], anchor="w").pack(side="left")
                ctk.CTkLabel(row, text="rotate", font=FONT_XS, text_color=C["amber"]).pack(side="right", padx=8)
            elif k in adding:
                ctk.CTkLabel(row, text=k, font=FONT_MONO_SM, text_color=C["green"], anchor="w", width=200).pack(side="left", padx=(8, 4), pady=5)
                ctk.CTkLabel(row, text=mask(new_val), font=FONT_MONO_SM, text_color=C["green"], anchor="w").pack(side="left")
                ctk.CTkLabel(row, text="new", font=FONT_XS, text_color=C["green"]).pack(side="right", padx=8)
            else:
                ctk.CTkLabel(row, text=k, font=FONT_MONO_SM, text_color=C["text2"], anchor="w", width=200).pack(side="left", padx=(8, 4), pady=5)
                ctk.CTkLabel(row, text=mask(new_val), font=FONT_MONO_SM, text_color=C["text3"], anchor="w").pack(side="left")
                ctk.CTkLabel(row, text="unchanged", font=FONT_XS, text_color=C["text3"]).pack(side="right", padx=8)

        btn_f = ctk.CTkFrame(win, fg_color="transparent")
        btn_f.pack(fill="x", padx=16, pady=12)

        def confirm():
            win.destroy()
            try:
                inject_env_file(path, self.vault, keys_to_write if keys_to_write else None)
                log_event(f"sync: wrote {len(keys_to_write)} keys to {path}/.env")
                messagebox.showinfo("Synced", f".env written to:\n{path}\n\n{len(keys_to_write)} key(s) synced.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to write .env:\n{e}")

        make_btn(btn_f, "Confirm & Write .env", confirm, fg_color=C["green_bg"], text_color=C["green"], width=160).pack(side="left")
        make_btn(btn_f, "Cancel", win.destroy, width=80).pack(side="left", padx=(8, 0))

    def _auto_match_keys(self, proj_name):
        prefix = re.sub(r"[^A-Z0-9]", "_", proj_name.upper())
        prefix = re.sub(r"_+", "_", prefix).strip("_")
        return [k for k in self.vault if k == prefix or k.startswith(prefix + "_")]

    def assign_keys_to_project(self, proj_name):
        if not self.vault:
            messagebox.showinfo("No keys", "Add some keys first, then assign them to projects.")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Assign keys to {proj_name}")
        win.geometry("420x480")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Select keys for {proj_name}", font=FONT_H3,
                     text_color=C["text"]).pack(pady=(12, 4), padx=12, anchor="w")
        ctk.CTkLabel(win, text="Unchecked keys won't be written to this project's .env",
                     font=FONT_XS, text_color=C["text3"]).pack(padx=12, anchor="w", pady=(0, 8))

        current_keys = set(self.config["projects"][proj_name].get("keys", []))
        matched = set(self._auto_match_keys(proj_name))
        checks = {}

        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=12)

        for section_keys, label, color in [
            (sorted(matched), "AUTO-MATCHED", C["green"]),
            (sorted(k for k in self.vault if k not in matched), "OTHER KEYS", C["text3"]),
        ]:
            if not section_keys:
                continue
            ctk.CTkLabel(scroll, text=label, font=FONT_XS, text_color=color).pack(anchor="w", pady=(8, 2), padx=4)
            for key_name in section_keys:
                checked = key_name in current_keys or (not current_keys and key_name in matched)
                var = ctk.BooleanVar(value=checked)
                checks[key_name] = var
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x")
                ctk.CTkCheckBox(
                    row, text=key_name, variable=var, font=FONT_MONO_SM,
                    text_color=C["green"] if key_name in matched else C["text"],
                    fg_color=C["accent"], hover_color=C["accent2"],
                    border_color=C["border2"], checkmark_color="white",
                ).pack(side="left", anchor="w", pady=1, padx=4)

        def save_assignment():
            selected = [n for n, v in checks.items() if v.get()]
            self.config["projects"][proj_name]["keys"] = selected
            self.save()
            win.destroy()
            self.render_projects()

        make_btn(win, "Save", save_assignment, fg_color=C["accent"], text_color="white", width=140).pack(pady=12)

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
        self.root = ctk.CTk()
        self.root.title("Pushkey")
        self.root.geometry("780x640")
        self.root.configure(fg_color=C["bg"])
        self.root.resizable(True, True)
        self.root.minsize(700, 500)

        self.frame = None
        atexit.register(self._on_exit)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_login()
        self.root.mainloop()

    def _on_exit(self):
        try: self.root.clipboard_clear()
        except: pass

    def _on_close(self):
        self._on_exit()
        self.root.destroy()

    def switch(self, cls, **kw):
        if self.frame:
            self.frame.destroy()
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

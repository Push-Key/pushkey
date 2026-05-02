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
from pathlib import Path

# Resolve asset base dir — works both in dev and PyInstaller --onefile
def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent
import tempfile
import time
import webbrowser
import re
from datetime import datetime, timedelta
import atexit

# ═══════════════════════════════════════════════
# CTK APPEARANCE
# ═══════════════════════════════════════════════

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
# Theme loaded from config after VAULT_DIR is known — see PushkeyApp.__init__

# ═══════════════════════════════════════════════
# CRYPTO
# ═══════════════════════════════════════════════

VAULT_DIR = Path.home() / ".pushkey"
VAULT_FILE = VAULT_DIR / "vault.enc"
SALT_FILE = VAULT_DIR / ".salt"
CONFIG_FILE = VAULT_DIR / "config.json"
LOG_FILE = VAULT_DIR / "pushkey.log"
HEALTH_FILE = VAULT_DIR / "health.json"
PROVIDERS_CACHE = VAULT_DIR / "providers.json"
PROVIDERS_REGISTRY_URL = "https://raw.githubusercontent.com/ebothegreat/pushkey/main/providers.json"
IMPORT_DIR = VAULT_DIR / "import"
MFA_FILE = VAULT_DIR / ".mfa"          # encrypted TOTP secret + backup codes
LICENSE_FILE = VAULT_DIR / ".license"  # encrypted license record
TOKEN_FILE   = VAULT_DIR / ".token"    # activation token from server
FIDO2_FILE   = VAULT_DIR / ".fido2"   # encrypted FIDO2 credential
SSO_FILE     = VAULT_DIR / ".sso"     # encrypted OIDC session
LEASES_FILE  = VAULT_DIR / "leases.json"  # dynamic secret leases
HEALTH_PORT  = 7654                   # local HTTP for browser extension

ACTIVATION_SERVER  = os.environ.get("PUSHKEY_SERVER", "https://api.pushkey.dev")
_TOKEN_GRACE_DAYS  = 10   # days offline before paid tier downgrades to free

# ── Tier definitions ──────────────────────────────────────────
TIERS = {
    "free": {
        "label": "Free",
        "max_keys": 15,
        "max_projects": 1,
        "max_devices": 1,
        "cloud_sync": False,
        "ci_sync": False,
        "team_rbac": False,
        "hardware_mfa": False,
        "sso": False,
        "dynamic_secrets": False,
        "git_scan": False,
        "color": "#64748B",
        "emoji": "🆓",
    },
    "starter": {
        "label": "Starter",
        "max_keys": 50,
        "max_projects": 3,
        "max_devices": 1,
        "cloud_sync": True,
        "ci_sync": False,
        "team_rbac": False,
        "hardware_mfa": False,
        "sso": False,
        "dynamic_secrets": False,
        "git_scan": True,
        "color": "#60A5FA",
        "emoji": "🚀",
    },
    "pro": {
        "label": "Pro",
        "max_keys": None,
        "max_projects": None,
        "max_devices": 3,
        "cloud_sync": True,
        "ci_sync": True,
        "team_rbac": False,
        "hardware_mfa": False,
        "sso": False,
        "dynamic_secrets": False,
        "git_scan": True,
        "color": "#A78BFA",
        "emoji": "⚡",
    },
    "team": {
        "label": "Team",
        "max_keys": None,
        "max_projects": None,
        "max_devices": 5,
        "cloud_sync": True,
        "ci_sync": True,
        "team_rbac": True,
        "hardware_mfa": False,
        "sso": False,
        "dynamic_secrets": False,
        "git_scan": True,
        "color": "#34D399",
        "emoji": "👥",
    },
    "enterprise": {
        "label": "Enterprise",
        "max_keys": None,
        "max_projects": None,
        "max_devices": None,
        "cloud_sync": True,
        "ci_sync": True,
        "team_rbac": True,
        "hardware_mfa": True,
        "sso": True,
        "dynamic_secrets": True,
        "git_scan": True,
        "color": "#F59E0B",
        "emoji": "🏛️",
    },
}

UPGRADE_MESSAGES = {
    "max_keys":        ("🔑 Key limit reached",         "Upgrade to add more keys.",             "starter"),
    "max_projects":    ("📁 Project limit reached",     "Upgrade to link more projects.",        "starter"),
    "cloud_sync":      ("☁️ Cloud sync is Pro+",        "Upgrade for encrypted cloud backup.",   "starter"),
    "ci_sync":         ("⚡ CI sync is Pro+",            "Upgrade to push to GitHub/Vercel.",     "pro"),
    "team_rbac":       ("👥 Team RBAC is Team+",         "Upgrade to share with your team.",      "team"),
    "hardware_mfa":    ("🔐 YubiKey is Enterprise",     "Upgrade for hardware MFA.",             "enterprise"),
    "sso":             ("🏛️ SSO is Enterprise",          "Upgrade for SAML/Okta/Azure AD.",       "enterprise"),
    "dynamic_secrets": ("⚙️ Dynamic secrets is Enterprise", "Upgrade for lease-based secrets.", "enterprise"),
    "git_scan":        ("🕵️ Git scan is Starter+",       "Upgrade to scan commit history.",       "starter"),
}

VAULT_SCHEMA_VERSION = 2
ENV_LEVELS = ["all", "dev", "staging", "prod"]
ENV_COLORS = {"all": "#3D5166", "dev": "#059669", "staging": "#F59E0B", "prod": "#F87171"}


def _migrate_vault(data):
    schema = data.get("_schema", 0)
    if schema < 2:
        # v1→v2: stamp env="all" on every key that lacks it
        for key_data in data.get("keys", {}).values():
            if isinstance(key_data, dict):
                key_data.setdefault("env", "all")
        data["_schema"] = VAULT_SCHEMA_VERSION
    return data


_LOG_KEY_CACHE = None  # derived once per session


def _log_key() -> bytes:
    global _LOG_KEY_CACHE
    if _LOG_KEY_CACHE is None:
        salt = get_or_create_salt()
        # Derive log key from salt + fixed domain — no password needed
        _LOG_KEY_CACHE = hashlib.pbkdf2_hmac("sha256", b"pushkey-log-key", salt, iterations=100_000)
    return _LOG_KEY_CACHE


def _log_encrypt(text: str) -> bytes:
    key = _log_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, text.encode(), None)
    payload = nonce + ct
    return len(payload).to_bytes(4, "big") + payload


def _log_decrypt_all() -> list[str]:
    lines = []
    if not LOG_FILE.exists():
        return lines
    raw = LOG_FILE.read_bytes()
    # Legacy plaintext log (starts with '[')
    if raw and raw[0:1] == b"[":
        return raw.decode("utf-8", errors="replace").splitlines()
    key = _log_key()
    pos = 0
    while pos + 4 <= len(raw):
        length = int.from_bytes(raw[pos:pos+4], "big")
        pos += 4
        if pos + length > len(raw):
            break
        payload = raw[pos:pos+length]
        pos += length
        try:
            nonce, ct = payload[:12], payload[12:]
            lines.append(AESGCM(key).decrypt(nonce, ct, None).decode())
        except Exception:
            lines.append("[corrupted entry]")
    return lines


def _log_line_age_days(line: str) -> float:
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
    if not m:
        return float("inf")
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 86400
    except ValueError:
        return float("inf")


def _migrate_plaintext_log() -> None:
    """Convert legacy plaintext log to encrypted binary format."""
    if not LOG_FILE.exists():
        return
    raw = LOG_FILE.read_bytes()
    if not raw or raw[0:1] != b"[":
        return  # already encrypted or empty
    lines = raw.decode("utf-8", errors="replace").splitlines()
    encrypted_chunks = b"".join(_log_encrypt(ln) for ln in lines if ln.strip())
    LOG_FILE.write_bytes(encrypted_chunks)


def log_event(message: str) -> None:
    try:
        ensure_vault_dir()
        _migrate_plaintext_log()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {message}"
        with LOG_FILE.open("ab") as f:
            f.write(_log_encrypt(entry))
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


def _check_crypto_deps():
    try:
        from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
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

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    Fernet = InvalidToken = AESGCM = None  # type: ignore

hash_secret_raw = None
Argon2Type = None
_ARGON2_AVAILABLE = False

def _try_load_argon2():
    global hash_secret_raw, Argon2Type, _ARGON2_AVAILABLE
    try:
        from argon2.low_level import hash_secret_raw as _h, Type as _T
        hash_secret_raw = _h
        Argon2Type = _T
        _ARGON2_AVAILABLE = True
    except ImportError:
        pass

# Magic prefix that marks AES-256-GCM encrypted data (v2 format)
# Legacy Fernet tokens are base64url bytes and never start with this
_V2_MAGIC   = b'PK2\x00'   # vault + master password
_V2T_MAGIC  = b'PKT2'      # team vault (includes ephemeral salt)


def derive_key(password: str, salt: bytes) -> bytes:
    """32-byte key via Argon2id (memory-hard). Falls back to PBKDF2 if argon2-cffi missing."""
    if _ARGON2_AVAILABLE:
        return hash_secret_raw(
            secret=password.encode(),
            salt=salt,
            time_cost=3,
            memory_cost=65536,  # 64 MB — GPU-resistant
            parallelism=4,
            hash_len=32,
            type=Argon2Type.ID,
        )
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)


def _aes_encrypt(data: str, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data.encode(), None)
    return _V2_MAGIC + nonce + ct


def _aes_decrypt(token: bytes, key: bytes) -> str:
    payload = token[len(_V2_MAGIC):]
    nonce, ct = payload[:12], payload[12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception:
        raise ValueError("wrong_password")


def _legacy_fernet_decrypt(token: bytes, password: str) -> str:
    salt = get_or_create_salt()
    legacy_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)
    try:
        return Fernet(base64.urlsafe_b64encode(legacy_key)).decrypt(token).decode()
    except InvalidToken:
        raise ValueError("wrong_password")


def encrypt_data(data: str, password: str) -> bytes:
    salt = get_or_create_salt()
    key = derive_key(password, salt)
    return _aes_encrypt(data, key)


def decrypt_data(token: bytes, password: str) -> str:
    """Decrypt vault. Auto-detects v2 (AES-256-GCM) vs legacy (Fernet/AES-128-CBC)."""
    if token.startswith(_V2_MAGIC):
        salt = get_or_create_salt()
        key = derive_key(password, salt)
        return _aes_decrypt(token, key)
    # Legacy Fernet format — decrypt then signal for migration
    return _legacy_fernet_decrypt(token, password)


# ── Team vault crypto (per-export ephemeral salt, no shared salt file) ──

def team_encrypt(data: str, passphrase: str) -> bytes:
    salt = secrets.token_bytes(32)           # fresh salt per export
    key = derive_key(passphrase, salt)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data.encode(), None)
    return _V2T_MAGIC + salt + nonce + ct    # self-contained


def team_decrypt(token: bytes, passphrase: str) -> str:
    if not token.startswith(_V2T_MAGIC):
        raise ValueError("Not a valid Pushkey team vault file")
    payload = token[len(_V2T_MAGIC):]
    salt, nonce, ct = payload[:32], payload[32:44], payload[44:]
    key = derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception:
        raise ValueError("wrong_password")


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
        is_legacy = not raw.startswith(_V2_MAGIC)
        decrypted = decrypt_data(raw, password)
        data = json.loads(decrypted)
        data = _migrate_vault(data)
        vault = _deserialize_vault(data)
        if is_legacy:
            # Silently upgrade to AES-256-GCM + Argon2id on first unlock
            save_vault(vault, password)
            log_event("vault upgraded to AES-256-GCM + Argon2id")
        return vault
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


def write_health_sidecar(vault):
    try:
        ensure_vault_dir()
        health = {}
        for name, info in vault.items():
            age = days_since(info.get("rotated") or info.get("created"))
            use_age = days_since(info.get("first_used"))
            effective_age = min(age, use_age) if use_age != float("inf") else age
            provider = info.get("provider")
            threshold = 90
            if provider and provider in PROVIDERS:
                threshold = PROVIDERS[provider].get("rotation_days", 90)
            if effective_age > threshold:
                status = "critical"
            elif effective_age > threshold * 0.67:
                status = "warning"
            else:
                status = "healthy"
            health[name] = {
                "status": status,
                "days_old": effective_age if effective_age != float("inf") else None,
                "provider": provider,
                "category": info.get("category", "General"),
                "first_used": info.get("first_used"),
                "last_used": info.get("last_used"),
                "created": info.get("created"),
                "rotated": info.get("rotated"),
                "rotation_count": info.get("rotation_count", 0),
            }
        tmp = HEALTH_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(health, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(HEALTH_FILE))
    except Exception:
        pass


_CONFIG_KEY_CACHE = None


def _config_key() -> bytes:
    global _CONFIG_KEY_CACHE
    if _CONFIG_KEY_CACHE is None:
        salt = get_or_create_salt()
        _CONFIG_KEY_CACHE = hashlib.pbkdf2_hmac("sha256", b"pushkey-config-key", salt, iterations=100_000)
    return _CONFIG_KEY_CACHE


def load_config():
    if not CONFIG_FILE.exists():
        return {"projects": {}}
    raw = CONFIG_FILE.read_bytes()
    # Legacy plaintext JSON
    if raw.lstrip()[:1] == b"{":
        try:
            data = json.loads(raw)
            save_config(data)   # auto-migrate to encrypted
            return data
        except Exception:
            pass
        return {"projects": {}}
    # Encrypted binary
    try:
        key = _config_key()
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(plaintext)
    except Exception:
        return {"projects": {}}


def save_config(config):
    ensure_vault_dir()
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(config, indent=2).encode(), None)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_bytes(nonce + ct)
    os.replace(str(tmp), str(CONFIG_FILE))


# ═══════════════════════════════════════════════
# MFA — TOTP (Google Authenticator / Authy)
# ═══════════════════════════════════════════════

def _mfa_encrypt(data: dict) -> bytes:
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct


def _mfa_decrypt(raw: bytes) -> dict:
    key = _config_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))


def mfa_is_enabled() -> bool:
    return MFA_FILE.exists()


def mfa_load() -> dict:
    if not MFA_FILE.exists():
        return {}
    try:
        return _mfa_decrypt(MFA_FILE.read_bytes())
    except Exception:
        return {}


def mfa_save(data: dict) -> None:
    ensure_vault_dir()
    MFA_FILE.write_bytes(_mfa_encrypt(data))


def mfa_verify(code: str) -> bool:
    data = mfa_load()
    if not data:
        return True   # MFA not set up — pass through
    secret = data.get("secret", "")
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        if totp.verify(code.strip(), valid_window=1):
            return True
        # Check backup codes
        backups = data.get("backup_codes", [])
        if code.strip() in backups:
            backups.remove(code.strip())
            data["backup_codes"] = backups
            mfa_save(data)
            return True
    except Exception:
        pass
    return False


def mfa_generate_secret(account_name: str = "Pushkey") -> tuple[str, str]:
    """Returns (secret, otpauth_uri) for QR code generation."""
    import pyotp
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=account_name, issuer_name="Pushkey")
    return secret, uri


def mfa_generate_backup_codes() -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(10)]


# ═══════════════════════════════════════════════
# LICENSE ENGINE
# ═══════════════════════════════════════════════

_LICENSE_CACHE: dict | None = None
_LICENSE_GRACE_DAYS = 3   # offline grace period


# ── Machine fingerprint ───────────────────────────────────────────────────────

def get_machine_fingerprint() -> str:
    import platform, uuid
    parts = [platform.node(), platform.machine(), str(uuid.getnode()), platform.system()]
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Token store (activation token returned by server) ────────────────────────

def _token_encrypt(data: dict) -> bytes:
    key = _license_key()   # reuse same derived key as license file
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct


def _token_decrypt(raw: bytes) -> dict:
    key = _license_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))


def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return _token_decrypt(TOKEN_FILE.read_bytes())
    except Exception:
        return None


def save_token(data: dict) -> None:
    ensure_vault_dir()
    TOKEN_FILE.write_bytes(_token_encrypt(data))
    TOKEN_FILE.chmod(0o600)


# ── Server calls ──────────────────────────────────────────────────────────────

def _server_post(path: str, payload: dict, timeout: int = 8) -> dict | None:
    try:
        import urllib.request
        url  = f"{ACTIVATION_SERVER.rstrip('/')}{path}"
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=body,
                                       headers={"Content-Type": "application/json"},
                                       method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None   # server unreachable — caller handles grace period


def server_activate(license_key: str, tier: str, email: str = "") -> tuple[bool, str, dict]:
    """Call /v1/activate. Returns (ok, message, response_dict)."""
    import platform as _pl
    resp = _server_post("/v1/activate", {
        "license_key": license_key,
        "fingerprint": get_machine_fingerprint(),
        "tier":        tier,
        "platform":    f"{_pl.system()} {_pl.release()}",
        "email":       email,
    })
    if resp is None:
        return False, "Could not reach activation server. Check your internet connection.", {}
    if not resp.get("ok"):
        return False, resp.get("error", "Activation rejected by server."), resp
    return True, "", resp


def server_heartbeat(license_key: str) -> dict | None:
    """Call /v1/heartbeat. Returns server response or None if unreachable."""
    token = load_token()
    return _server_post("/v1/heartbeat", {
        "license_key": license_key,
        "fingerprint": get_machine_fingerprint(),
        "token":       token.get("token", "") if token else "",
    })


def server_deactivate(license_key: str) -> bool:
    """Call /v1/deactivate. Returns True on success."""
    resp = _server_post("/v1/deactivate", {
        "license_key": license_key,
        "fingerprint": get_machine_fingerprint(),
    })
    return bool(resp and resp.get("ok"))


def maybe_heartbeat() -> None:
    """Called after every successful vault unlock. Refreshes token at most once per 24 h."""
    lic = load_license()
    if lic.get("tier", "free") == "free":
        return   # free tier — no server check needed
    license_key = lic.get("license_key", "")
    if not license_key:
        return

    token = load_token()
    now   = datetime.now()

    # Token still fresh — skip
    if token:
        refreshed_at = token.get("refreshed_at")
        if refreshed_at:
            try:
                age = now - datetime.fromisoformat(refreshed_at)
                if age < timedelta(hours=24):
                    return
            except Exception:
                pass

    resp = server_heartbeat(license_key)
    if resp and resp.get("ok"):
        save_token({
            "token":        resp["token"],
            "tier":         resp["tier"],
            "refreshed_at": now.isoformat(),
        })
        return

    # Server unreachable — check grace period
    if token:
        refreshed_at = token.get("refreshed_at")
        if refreshed_at:
            try:
                age = now - datetime.fromisoformat(refreshed_at)
                if age < timedelta(days=_TOKEN_GRACE_DAYS):
                    return  # still within grace, let them work
            except Exception:
                pass

    # Grace expired — downgrade
    global _LICENSE_CACHE
    _LICENSE_CACHE = {"tier": "free", "_server_unreachable": True}
    log_event("license downgraded: server unreachable beyond grace period")


def deactivate_device() -> tuple[bool, str]:
    """Remove this machine from the activation server and clear local token."""
    lic = load_license()
    license_key = lic.get("license_key", "")
    if not license_key:
        return False, "No active license to deactivate."
    ok = server_deactivate(license_key)
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink(missing_ok=True)
    global _LICENSE_CACHE
    _LICENSE_CACHE = None
    log_event("device deactivated")
    if ok:
        return True, "Device deactivated. You can now activate on another machine."
    return False, "Server unreachable — local token cleared. Deactivation will sync when server is online."


def _license_key() -> bytes:
    salt = get_or_create_salt()
    return hashlib.pbkdf2_hmac("sha256", b"pushkey-license-key", salt, iterations=100_000)


def _license_encrypt(data: dict) -> bytes:
    key = _license_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct


def _license_decrypt(raw: bytes) -> dict:
    key = _license_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))


def load_license() -> dict:
    global _LICENSE_CACHE
    if _LICENSE_CACHE is not None:
        return _LICENSE_CACHE
    if not LICENSE_FILE.exists():
        _LICENSE_CACHE = {"tier": "free"}
        return _LICENSE_CACHE
    try:
        data = _license_decrypt(LICENSE_FILE.read_bytes())
        # Validate expiry
        expires = data.get("expires")
        if expires:
            exp_dt = datetime.fromisoformat(expires)
            grace = exp_dt + timedelta(days=_LICENSE_GRACE_DAYS)
            if datetime.now() > grace:
                _LICENSE_CACHE = {"tier": "free", "_expired": True}
                return _LICENSE_CACHE
        _LICENSE_CACHE = data
        return data
    except Exception:
        _LICENSE_CACHE = {"tier": "free"}
        return _LICENSE_CACHE


def save_license(data: dict) -> None:
    global _LICENSE_CACHE
    ensure_vault_dir()
    LICENSE_FILE.write_bytes(_license_encrypt(data))
    _LICENSE_CACHE = data


def current_tier() -> str:
    return load_license().get("tier", "free")


def tier_limits() -> dict:
    return TIERS.get(current_tier(), TIERS["free"])


def can_do(feature: str) -> bool:
    """Check boolean feature flag for current tier."""
    return bool(tier_limits().get(feature, False))


def within_limit(resource: str, current_count: int) -> bool:
    """Check numeric limit. None = unlimited."""
    limit = tier_limits().get(resource)
    if limit is None:
        return True
    return current_count < limit


def activate_license(license_key: str) -> tuple[bool, str]:
    """
    Validate and activate a license key.
    Format: TIER-XXXXXXXX-XXXXXXXX-XXXXXXXX (base32 encoded payload + checksum)
    Returns (success, message).
    """
    try:
        parts = license_key.strip().upper().split("-")
        if len(parts) < 2:
            return False, "Invalid license key format"

        tier_code = parts[0].lower()
        tier_map = {"free": "free", "strt": "starter", "pro": "pro",
                    "team": "team", "ent": "enterprise",
                    "ltdp": "pro", "ltdt": "team"}   # LTD codes
        tier = tier_map.get(tier_code)
        if not tier:
            return False, f"Unknown tier code: {tier_code}"

        # Checksum: last segment must match SHA-256 of joined middle segments
        payload_parts = parts[1:-1]
        checksum = parts[-1]
        expected = hashlib.sha256("-".join(payload_parts).encode()).hexdigest()[:8].upper()
        if checksum != expected:
            return False, "License key checksum invalid — check for typos"

        # Decode payload: base32 → JSON with tier, expiry, seats, email
        import base64 as _b64
        try:
            raw_payload = _b64.b32decode("".join(payload_parts) + "=" * 4)
            payload = json.loads(raw_payload)
        except Exception:
            # Simple license: no payload, just tier + valid checksum
            payload = {}

        expiry = payload.get("expires")    # ISO date string or None (lifetime)
        seats  = payload.get("seats", 1)
        email  = payload.get("email", "")

        # ── Server-side device registration ──────────────────────────────
        ok, err_msg, srv = server_activate(license_key.strip(), tier, email)
        if not ok:
            return False, err_msg

        data = {
            "tier": tier,
            "license_key": license_key.strip(),
            "activated": datetime.now().isoformat(),
            "expires": expiry,
            "seats": seats,
            "email": email,
            "lifetime": expiry is None,
        }
        save_license(data)
        save_token({
            "token":        srv.get("token", ""),
            "tier":         tier,
            "refreshed_at": datetime.now().isoformat(),
        })
        log_event(f"license activated: {tier} {'(lifetime)' if not expiry else expiry}")
        devices_used = srv.get("devices_used", 1)
        devices_max  = srv.get("devices_max")
        slot_msg     = f" ({devices_used}/{devices_max} devices)" if devices_max else ""
        return True, f"✅ {TIERS[tier]['emoji']} {TIERS[tier]['label']} license activated!{slot_msg}"

    except Exception as e:
        return False, f"Activation error: {e}"


def generate_license_key(tier: str, expires: str | None = None,
                         seats: int = 1, email: str = "") -> str:
    """
    Dev utility — generate a valid license key for testing.
    Production keys should be generated server-side.
    """
    import base64 as _b64
    tier_codes = {"free": "FREE", "starter": "STRT", "pro": "PRO",
                  "team": "TEAM", "enterprise": "ENT"}
    code = tier_codes.get(tier, "PRO")
    payload = json.dumps({"tier": tier, "expires": expires,
                           "seats": seats, "email": email}).encode()
    b32 = _b64.b32encode(payload).decode().rstrip("=")
    # Split into 8-char chunks
    chunks = [b32[i:i+8] for i in range(0, len(b32), 8)]
    payload_str = "-".join(chunks)
    checksum = hashlib.sha256(payload_str.encode()).hexdigest()[:8].upper()
    return f"{code}-{payload_str}-{checksum}"


# ═══════════════════════════════════════════════════════════════
# FIDO2 / YUBIKEY HARDWARE MFA  (#23)
# ═══════════════════════════════════════════════════════════════

def _fido2_encrypt(data: dict) -> bytes:
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct

def _fido2_decrypt(raw: bytes) -> dict:
    key = _config_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))

def fido2_is_enabled() -> bool:
    return FIDO2_FILE.exists()

def fido2_load() -> dict:
    if not FIDO2_FILE.exists():
        return {}
    try:
        return _fido2_decrypt(FIDO2_FILE.read_bytes())
    except Exception:
        return {}

def fido2_save(data: dict) -> None:
    ensure_vault_dir()
    FIDO2_FILE.write_bytes(_fido2_encrypt(data))

def fido2_list_devices() -> list:
    try:
        from fido2.hid import CtapHidDevice
        return list(CtapHidDevice.list_devices())
    except ImportError:
        raise RuntimeError("python-fido2 not installed.\nRun: pip install fido2>=1.1.2")

def fido2_register() -> dict:
    """Register a FIDO2 device. Returns credential dict to persist."""
    from fido2.hid import CtapHidDevice
    from fido2.client import Fido2Client, UserInteraction
    from fido2.server import Fido2Server

    devices = list(CtapHidDevice.list_devices())
    if not devices:
        raise RuntimeError("No FIDO2/YubiKey device found.\nConnect your key and try again.")

    rp = {"id": "pushkey.local", "name": "Pushkey Vault"}
    server = Fido2Server(rp)
    user = {"id": b"pushkey-local-user", "name": "pushkey", "displayName": "Pushkey User"}
    create_options, state = server.register_begin(user, user_verification="discouraged")

    class _Silent(UserInteraction):
        def prompt_up(self): pass
        def request_pin(self, permissions, rp_id): return ""
        def request_uv(self, permissions, rp_id): return True

    client = Fido2Client(devices[0], "https://pushkey.local", user_interaction=_Silent())
    result = client.make_credential(create_options["publicKey"])
    auth_data = server.register_complete(state, result)
    cred = auth_data.credential_data
    return {
        "credential_id": base64.b64encode(bytes(cred.credential_id)).decode(),
        "public_key":    base64.b64encode(bytes(cred.public_key)).decode(),
        "registered":    datetime.now().isoformat(),
        "device_name":   str(devices[0]),
    }

def fido2_authenticate() -> bool:
    """Verify stored FIDO2 credential. Returns True on success."""
    from fido2.hid import CtapHidDevice
    from fido2.client import Fido2Client, UserInteraction
    from fido2.server import Fido2Server
    from fido2.webauthn import AttestedCredentialData

    stored = fido2_load()
    if not stored:
        return False
    devices = list(CtapHidDevice.list_devices())
    if not devices:
        raise RuntimeError("No FIDO2/YubiKey device found.")

    rp = {"id": "pushkey.local", "name": "Pushkey Vault"}
    server = Fido2Server(rp)
    cred_id = base64.b64decode(stored["credential_id"])
    pub_key = base64.b64decode(stored["public_key"])
    credential = AttestedCredentialData.create(b"\x00" * 16, cred_id, pub_key)

    req_options, state = server.authenticate_begin([credential], user_verification="discouraged")

    class _Silent(UserInteraction):
        def prompt_up(self): pass
        def request_pin(self, permissions, rp_id): return ""

    client = Fido2Client(devices[0], "https://pushkey.local", user_interaction=_Silent())
    selection = client.get_assertion(req_options["publicKey"])
    resp = selection.get_response(0)
    server.authenticate_complete(
        state, [credential],
        resp.credential_id, resp.client_data,
        resp.authenticator_data, resp.signature,
    )
    return True


# ═══════════════════════════════════════════════════════════════
# SSO / OIDC DEVICE FLOW  (#25)
# ═══════════════════════════════════════════════════════════════

_SSO_PROVIDERS = {
    "Okta":     {"device_auth": "{issuer}/v1/device/authorize",   "token": "{issuer}/v1/token"},
    "Azure AD": {"device_auth": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
                 "token":       "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"},
    "Google":   {"device_auth": "https://oauth2.googleapis.com/device/code",
                 "token":       "https://oauth2.googleapis.com/token"},
    "Custom":   {"device_auth": "{issuer}/device_authorization",  "token": "{issuer}/token"},
}

def _sso_encrypt(data: dict) -> bytes:
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct

def _sso_decrypt(raw: bytes) -> dict:
    key = _config_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))

def sso_load() -> dict:
    if not SSO_FILE.exists():
        return {}
    try:
        return _sso_decrypt(SSO_FILE.read_bytes())
    except Exception:
        return {}

def sso_save(data: dict) -> None:
    ensure_vault_dir()
    SSO_FILE.write_bytes(_sso_encrypt(data))

def sso_logout() -> None:
    SSO_FILE.unlink(missing_ok=True)
    log_event("SSO logout")

def sso_is_logged_in() -> bool:
    sess = sso_load()
    if not sess.get("access_token"):
        return False
    expires = sess.get("expires_at")
    if expires:
        try:
            return datetime.fromisoformat(expires) > datetime.now()
        except Exception:
            pass
    return True

def sso_device_flow_start(client_id: str, device_auth_url: str,
                           scope: str = "openid email profile") -> dict:
    """RFC 8628 — start device authorization. Returns server response."""
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({"client_id": client_id, "scope": scope}).encode()
    req = urllib.request.Request(device_auth_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def sso_device_flow_poll(client_id: str, token_url: str, device_code: str) -> dict | None:
    """Poll for OIDC token. Returns dict on success, None if still pending."""
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({
        "client_id":   client_id,
        "device_code": device_code,
        "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if "access_token" in result:
                return result
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# DYNAMIC SECRETS  (#26)
# ═══════════════════════════════════════════════════════════════

def load_leases() -> list:
    if not LEASES_FILE.exists():
        return []
    try:
        return json.loads(LEASES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_leases(leases: list) -> None:
    ensure_vault_dir()
    LEASES_FILE.write_text(json.dumps(leases, indent=2), encoding="utf-8")

def create_aws_lease(iam_user: str, admin_key_id: str, admin_secret: str,
                     ttl_hours: int = 24) -> dict:
    """Create a temporary IAM access key and store lease record."""
    import boto3
    iam = boto3.client("iam", aws_access_key_id=admin_key_id,
                       aws_secret_access_key=admin_secret)
    resp = iam.create_access_key(UserName=iam_user)
    new_key = resp["AccessKey"]
    expires = (datetime.now() + timedelta(hours=ttl_hours)).isoformat()
    lease = {
        "id":               secrets.token_hex(8),
        "type":             "aws_iam",
        "iam_user":         iam_user,
        "access_key_id":    new_key["AccessKeyId"],
        "secret_access_key": new_key["SecretAccessKey"],
        "expires":          expires,
        "ttl_hours":        ttl_hours,
        "created":          datetime.now().isoformat(),
        "status":           "active",
    }
    leases = load_leases()
    leases.append(lease)
    save_leases(leases)
    log_event(f"dynamic lease created: aws_iam/{iam_user} ttl={ttl_hours}h")
    return lease

def revoke_lease(lease_id: str, admin_key_id: str = "", admin_secret: str = "") -> bool:
    leases = load_leases()
    lease = next((l for l in leases if l["id"] == lease_id), None)
    if not lease:
        return False
    if lease["type"] == "aws_iam" and admin_key_id and admin_secret:
        try:
            import boto3
            iam = boto3.client("iam", aws_access_key_id=admin_key_id,
                               aws_secret_access_key=admin_secret)
            iam.delete_access_key(UserName=lease["iam_user"],
                                  AccessKeyId=lease["access_key_id"])
        except Exception:
            pass
    save_leases([l for l in leases if l["id"] != lease_id])
    log_event(f"dynamic lease revoked: {lease_id}")
    return True

def check_expired_leases() -> list:
    now = datetime.now()
    return [l for l in load_leases()
            if l.get("expires") and datetime.fromisoformat(l["expires"]) <= now]


# ═══════════════════════════════════════════════════════════════
# CLOUD SYNC CLIENT  (#28)
# ═══════════════════════════════════════════════════════════════

def cloud_push(endpoint: str, token: str, vault_bytes: bytes) -> str:
    """PUT encrypted vault blob. Returns server ETag."""
    import urllib.request
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/v1/vault", data=vault_bytes, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/octet-stream")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read()).get("etag", "")

def cloud_pull(endpoint: str, token: str, current_etag: str = "") -> tuple:
    """GET vault blob. Returns (bytes, etag) or (None, etag) if unchanged."""
    import urllib.request
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/v1/vault", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    if current_etag:
        req.add_header("If-None-Match", current_etag)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            etag = resp.headers.get("ETag", "")
            return resp.read(), etag
    except Exception as exc:
        if "304" in str(exc):
            return None, current_etag
        raise

def cloud_login(endpoint: str, email: str, pw: str) -> str:
    """Auth to cloud sync server. Returns Bearer token."""
    import urllib.request
    data = json.dumps({"email": email, "password": pw}).encode()
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/v1/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read()).get("token", "")


# ── Local health HTTP server for browser extension ────────────
def _start_health_server(port: int = HEALTH_PORT) -> None:
    """Serve health.json on 127.0.0.1:{port}/health for the browser extension."""
    import http.server
    import threading

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_response(404); self.end_headers(); return
            try:
                data = HEALTH_FILE.read_bytes() if HEALTH_FILE.exists() else b"{}"
            except Exception:
                data = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
        def log_message(self, *_): pass

    def _serve():
        try:
            srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
            srv.serve_forever()
        except Exception:
            pass

    threading.Thread(target=_serve, daemon=True).start()


# ═══════════════════════════════════════════════
# PROVIDER DATABASE  (bundled + community registry)
# ═══════════════════════════════════════════════

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
    if PROVIDERS_CACHE.exists():
        try:
            cached = json.loads(PROVIDERS_CACHE.read_text(encoding="utf-8"))
            merged.update(cached.get("providers", {}))
        except Exception:
            pass
    return merged


def update_providers_from_web():
    """Fetch latest providers.json from GitHub. Returns (new_count, updated_count, error_str)."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(PROVIDERS_REGISTRY_URL, timeout=10) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
        remote = data.get("providers", {})
        if not remote:
            return 0, 0, "Registry returned empty providers list"
        existing = _load_providers()
        new_count     = sum(1 for k in remote if k not in existing)
        updated_count = sum(1 for k in remote if k in existing and remote[k] != existing.get(k))
        tmp = PROVIDERS_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(PROVIDERS_CACHE))
        global PROVIDERS
        PROVIDERS = _load_providers()
        log_event(f"providers updated: {new_count} new, {updated_count} changed")
        return new_count, updated_count, None
    except urllib.error.URLError as e:
        return 0, 0, f"Network error: {e.reason}"
    except Exception as e:
        return 0, 0, str(e)


PROVIDERS = _load_providers()


# ═══════════════════════════════════════════════
# CI / CLOUD PLATFORM SYNC
# ═══════════════════════════════════════════════

def _github_encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt secret for GitHub Actions using libsodium sealed box."""
    from nacl import encoding, public
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode())
    import base64
    return base64.b64encode(encrypted).decode()


def sync_github_actions(owner: str, repo: str, token: str,
                        keys: dict[str, str]) -> tuple[int, list[str]]:
    """Push keys to GitHub Actions secrets. Returns (success_count, errors)."""
    import urllib.request, urllib.error
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    # Fetch repo public key
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key",
        headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            pk_data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return 0, [f"GitHub: failed to fetch public key: {e.code} {e.read().decode()[:200]}"]
    except Exception as e:
        return 0, [f"GitHub: {e}"]

    pk_value = pk_data["key"]
    pk_id = pk_data["key_id"]
    success, errors = 0, []

    for key_name, value in keys.items():
        try:
            encrypted = _github_encrypt_secret(pk_value, value)
            body = json.dumps({"encrypted_value": encrypted, "key_id": pk_id}).encode()
            put_req = urllib.request.Request(
                f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{key_name}",
                data=body, headers=headers, method="PUT")
            with urllib.request.urlopen(put_req, timeout=10) as r:
                if r.status in (201, 204):
                    success += 1
                else:
                    errors.append(f"{key_name}: unexpected status {r.status}")
        except urllib.error.HTTPError as e:
            errors.append(f"{key_name}: {e.code} {e.read().decode()[:100]}")
        except Exception as e:
            errors.append(f"{key_name}: {e}")

    return success, errors


def sync_vercel(token: str, project_id: str, env_target: str,
                keys: dict[str, str]) -> tuple[int, list[str]]:
    """Push keys to Vercel project environment variables."""
    import urllib.request, urllib.error
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    success, errors = 0, []
    targets = [env_target] if env_target != "all" else ["production", "preview", "development"]

    for key_name, value in keys.items():
        try:
            body = json.dumps({
                "key": key_name, "value": value,
                "type": "encrypted", "target": targets,
            }).encode()
            req = urllib.request.Request(
                f"https://api.vercel.com/v10/projects/{project_id}/env",
                data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10):
                    success += 1
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode()
                if e.code == 409:   # already exists — try PATCH
                    # list envs to find id
                    list_req = urllib.request.Request(
                        f"https://api.vercel.com/v10/projects/{project_id}/env",
                        headers=headers)
                    with urllib.request.urlopen(list_req, timeout=10) as r:
                        envs = json.loads(r.read()).get("envs", [])
                    existing = next((e for e in envs if e["key"] == key_name), None)
                    if existing:
                        patch_body = json.dumps({"value": value, "type": "encrypted",
                                                  "target": targets}).encode()
                        patch_req = urllib.request.Request(
                            f"https://api.vercel.com/v10/projects/{project_id}/env/{existing['id']}",
                            data=patch_body, headers=headers, method="PATCH")
                        with urllib.request.urlopen(patch_req, timeout=10):
                            success += 1
                    else:
                        errors.append(f"{key_name}: 409 conflict")
                else:
                    errors.append(f"{key_name}: {e.code} {body_txt[:100]}")
        except Exception as e:
            errors.append(f"{key_name}: {e}")

    return success, errors


def sync_railway(token: str, project_id: str, environment_id: str,
                 keys: dict[str, str]) -> tuple[int, list[str]]:
    """Push keys to Railway via GraphQL API."""
    import urllib.request, urllib.error
    query = """
    mutation UpsertVariables($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    variables_dict = {k: v for k, v in keys.items()}
    body = json.dumps({
        "query": query,
        "variables": {
            "input": {
                "projectId": project_id,
                "environmentId": environment_id,
                "variables": variables_dict,
            }
        }
    }).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request("https://backboard.railway.app/graphql/v2",
                                     data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        if result.get("errors"):
            errs = [e.get("message", str(e)) for e in result["errors"]]
            return 0, errs
        return len(keys), []
    except Exception as e:
        return 0, [str(e)]


# ═══════════════════════════════════════════════
# ROTATION API CLIENT
# ═══════════════════════════════════════════════

class RotationResult:
    def __init__(self, new_value=None, new_id=None, error=None, partial=False):
        self.new_value = new_value  # the new key/secret string
        self.new_id = new_id        # provider's internal key id (for later delete)
        self.error = error
        self.partial = partial      # True = new key created but old not deleted


def _rotate_openai(old_key_id, admin_key):
    """Requires an OpenAI Admin API key (sk-admin-...), not a regular key."""
    import urllib.request, urllib.error
    headers = {"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"}
    # Create new key
    body = json.dumps({"name": f"pushkey-rotated-{int(time.time())}"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/organization/admin_api_keys",
                                  data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            new_key_data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return RotationResult(error=f"OpenAI create failed: {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        return RotationResult(error=f"OpenAI create failed: {e}")

    new_value = new_key_data.get("value")
    new_id = new_key_data.get("id")
    if not new_value:
        return RotationResult(error="OpenAI: no key value in response")

    # Delete old key if we have its id
    if old_key_id:
        del_req = urllib.request.Request(
            f"https://api.openai.com/v1/organization/admin_api_keys/{old_key_id}",
            headers=headers, method="DELETE")
        try:
            urllib.request.urlopen(del_req, timeout=15)
        except Exception:
            return RotationResult(new_value=new_value, new_id=new_id, partial=True)

    return RotationResult(new_value=new_value, new_id=new_id)


def _deactivate_anthropic(key_id, admin_key):
    """Deactivates old Anthropic key. New key must be created manually in console."""
    import urllib.request, urllib.error
    if not key_id:
        return RotationResult(error="Anthropic: provide the key ID to deactivate (from console)")
    headers = {
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = json.dumps({"status": "inactive"}).encode()
    req = urllib.request.Request(
        f"https://api.anthropic.com/v1/organizations/api_keys/{key_id}",
        data=body, headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
        return RotationResult(partial=True,
                              error="Old key deactivated. Create new key in Anthropic console, then paste it here.")
    except urllib.error.HTTPError as e:
        return RotationResult(error=f"Anthropic deactivate failed: {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        return RotationResult(error=f"Anthropic deactivate failed: {e}")


def _rotate_aws(aws_access_key_id, aws_secret, username=None):
    """Full AWS IAM rotation. Requires iam:CreateAccessKey + iam:DeleteAccessKey perms."""
    try:
        import boto3
        import botocore.exceptions
    except ImportError:
        return RotationResult(error="AWS rotation requires boto3: pip install boto3")

    session = boto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret,
    )
    iam = session.client("iam")

    # Create new key
    try:
        kwargs = {"UserName": username} if username else {}
        resp = iam.create_access_key(**kwargs)
        new_key = resp["AccessKey"]["AccessKeyId"]
        new_secret = resp["AccessKey"]["SecretAccessKey"]
    except botocore.exceptions.ClientError as e:
        return RotationResult(error=f"AWS create failed: {e.response['Error']['Message']}")
    except Exception as e:
        return RotationResult(error=f"AWS create failed: {e}")

    # Delete old key
    try:
        kwargs = {"AccessKeyId": aws_access_key_id}
        if username:
            kwargs["UserName"] = username
        iam.delete_access_key(**kwargs)
    except Exception:
        return RotationResult(new_value=f"{new_key}:{new_secret}", new_id=new_key, partial=True)

    return RotationResult(new_value=f"{new_key}:{new_secret}", new_id=new_key)


def rotate_key_via_api(provider, key_info, rotation_creds):
    """
    rotation_creds: dict of extra credentials needed (admin_key, key_id, username, etc.)
    Returns RotationResult.
    """
    if provider == "OpenAI":
        return _rotate_openai(
            old_key_id=rotation_creds.get("key_id"),
            admin_key=rotation_creds.get("admin_key"),
        )
    if provider == "Anthropic":
        return _deactivate_anthropic(
            key_id=rotation_creds.get("key_id"),
            admin_key=rotation_creds.get("admin_key"),
        )
    if provider == "AWS":
        return _rotate_aws(
            aws_access_key_id=key_info.get("value", "").split(":")[0],
            aws_secret=rotation_creds.get("aws_secret"),
            username=rotation_creds.get("username"),
        )
    return RotationResult(error=f"{provider} does not support API rotation yet. Use manual rotation.")


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


def inject_env_file(project_path, vault, key_names=None, target_env="all"):
    """Update .env surgically — only touch keys being written, preserve everything else."""
    project_dir = Path(project_path)
    env_path = project_dir / ".env"

    def _env_match(key_env):
        return target_env == "all" or key_env == "all" or key_env == target_env

    if key_names:
        keys_to_write = {k: vault[k]["value"] for k in key_names
                         if k in vault and _env_match(vault[k].get("env", "all"))}
    else:
        keys_to_write = {k: v["value"] for k, v in vault.items()
                         if _env_match(v.get("env", "all"))}

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

C_DARK = {
    # Backgrounds — OLED-punchy, clearly tiered
    "bg":           "#050A0F",
    "bg2":          "#0A1628",
    "bg3":          "#0F2035",
    "bg4":          "#152840",
    "surface":      "#0A1628",
    # Brand accent — CYAN (green demoted to health status only)
    "accent":       "#22D3EE",
    "accent2":      "#06B6D4",
    "accent_dim":   "#051318",
    # Violet — security, MFA, enterprise tier
    "violet":       "#7C3AED",
    "violet_dim":   "#110D1E",
    # Text — cyan-tinted hierarchy
    "text":         "#F0F9FF",
    "text2":        "#7FB3CC",
    "text3":        "#3D6E8A",
    # Borders — visible
    "border":       "#112233",
    "border2":      "#1A3550",
    # Buttons
    "btn":          "#0F2035",
    "btn_hover":    "#152840",
    # Semantic — green LOCKED to healthy status only
    "green":        "#00DC82",
    "green_bg":     "#041A0F",
    "amber":        "#F59E0B",
    "amber_bg":     "#1F1200",
    "red":          "#EF4444",
    "red_bg":       "#1F0808",
    "blue":         "#22D3EE",
    "blue_bg":      "#051318",
    # Environment pills
    "env_dev":      "#22D3EE",
    "env_staging":  "#F59E0B",
    "env_prod":     "#EF4444",
    "env_all":      "#7C3AED",
}

C_LIGHT = {
    "bg":           "#FFFFFF",
    "bg2":          "#F8FAFD",
    "bg3":          "#FFFFFF",
    "bg4":          "#FFFFFF",
    "surface":      "#FFFFFF",
    "accent":       "#0891B2",
    "accent2":      "#0E7490",
    "accent_dim":   "#ECFEFF",
    "violet":       "#8B5CF6",
    "violet_dim":   "#F5F3FF",
    "text":         "#0F172A",
    "text2":        "#64748B",
    "text3":        "#B0BAC8",
    "border":       "#CBD5E1",
    "border2":      "#B6C5D4",
    "btn":          "#F1F5F9",
    "btn_hover":    "#E8EEF5",
    "green":        "#10B981",
    "green_bg":     "#F0FDF9",
    "amber":        "#F59E0B",
    "amber_bg":     "#FFFBEB",
    "red":          "#EF4444",
    "red_bg":       "#FFF5F5",
    "blue":         "#0891B2",
    "blue_bg":      "#ECFEFF",
    "env_dev":      "#0891B2",
    "env_staging":  "#F59E0B",
    "env_prod":     "#EF4444",
    "env_all":      "#8B5CF6",
}

_CURRENT_THEME = "dark"
C = C_DARK

HEALTH_COLORS = {
    "healthy":  "#00DC82",
    "warning":  "#F59E0B",
    "critical": "#EF4444",
}


def set_theme(mode: str):
    global C, _CURRENT_THEME
    _CURRENT_THEME = mode
    C = C_DARK if mode == "dark" else C_LIGHT
    ctk.set_appearance_mode("dark" if mode == "dark" else "light")


# IBM Plex Sans + JetBrains Mono — matches landing page typography
_UI_FONT    = "IBM Plex Sans"
_MONO_FONT  = "JetBrains Mono"

FONT         = (_UI_FONT, 12)
FONT_SM      = (_UI_FONT, 11)
FONT_XS      = (_UI_FONT, 11)
FONT_MONO    = (_MONO_FONT, 12)
FONT_MONO_SM = (_MONO_FONT, 11)
FONT_TITLE   = (_UI_FONT, 20, "bold")
FONT_H2      = (_UI_FONT, 15, "bold")
FONT_H3      = (_UI_FONT, 13, "bold")
FONT_BTN     = (_UI_FONT, 11, "bold")

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

CAT_EMOJI = {
    "AI": "🤖", "Trading": "📈", "Database": "🗄️", "Cloud": "☁️",
    "Payment": "💳", "Communication": "💬", "Comms": "💬",
    "Security": "🛡️", "Crypto": "₿", "General": "🔑",
    "VCS": "🐙", "Monitoring": "📊", "CRM": "👥",
    "Project Management": "📋", "Incident": "🚨",
}


# ═══════════════════════════════════════════════
# HELPER WIDGETS (CTK-native)
# ═══════════════════════════════════════════════

def make_btn(parent, text, command, fg_color=None, text_color=None, width=None, height=28,
             corner_radius=4, anchor=None):
    fg = fg_color or C["btn"]
    tc = text_color or C["text2"]
    kw = dict(
        text=text,
        command=command,
        fg_color=fg,
        text_color=tc,
        hover_color=C["btn_hover"],
        font=FONT_BTN,
        corner_radius=corner_radius,
        height=height,
    )
    if width:
        kw["width"] = width
    if anchor:
        kw["anchor"] = anchor
    return ctk.CTkButton(parent, **kw)


def _draw_arc_gauge(canvas: tk.Canvas, pct: float, color: str,
                    center_text: str, sub_label: str) -> None:
    """Draw a 220° speedometer-style arc gauge. Canvas must be 160×140."""
    import math
    canvas.delete("all")
    bg = canvas["bg"] if canvas["bg"] != "" else C["bg"]
    cx, cy = 80, 76
    r = 52
    stroke = 12

    # Arc spans from 200° to -20° (clockwise), tkinter measures CCW from east
    start = 200
    full_extent = -220

    x0, y0 = cx - r, cy - r
    x1, y1 = cx + r, cy + r

    # Background track
    canvas.create_arc(x0, y0, x1, y1, start=start, extent=full_extent,
                      style="arc", outline=C["bg3"], width=stroke)

    pct = max(0.0, min(1.0, pct))
    if pct > 0.01:
        extent = full_extent * max(0.02, pct)

        # Glow layer — wider dashed arc same color
        canvas.create_arc(x0 - 4, y0 - 4, x1 + 4, y1 + 4,
                          start=start, extent=extent,
                          style="arc", outline=color, width=4, dash=(2, 4))

        # Main colored arc
        canvas.create_arc(x0, y0, x1, y1, start=start, extent=extent,
                          style="arc", outline=color, width=stroke)

        # Needle dot at arc end
        end_rad = math.radians(start + extent)
        dx = cx + r * math.cos(end_rad)
        dy = cy - r * math.sin(end_rad)
        canvas.create_oval(dx - 5, dy - 5, dx + 5, dy + 5,
                           fill=color, outline=bg)

    # Center value text
    canvas.create_text(cx, cy - 6, text=center_text,
                       font=(_MONO_FONT, 26, "bold"), fill=color, anchor="center")

    # Sub-label
    canvas.create_text(cx, cy + 20, text=sub_label,
                       font=(_UI_FONT, 9), fill=C["text3"], anchor="center")


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
    # If actively deployed, age counts from first deployment
    use_age = days_since(key_info.get("first_used"))
    effective_age = min(age, use_age) if use_age != float("inf") else age
    if effective_age > threshold:
        return "critical"
    if effective_age > threshold * 0.67:
        return "warning"
    return "healthy"


def health_color(status):
    return {"healthy": C["green"], "warning": C["amber"], "critical": C["red"]}.get(status, C["text3"])


def days_until_rotation(key_info):
    """Days until scheduled rotation. None if no schedule set. Negative = overdue."""
    schedule = key_info.get("rotation_schedule")
    if not schedule:
        return None
    try:
        interval = int(schedule)
    except (ValueError, TypeError):
        return None
    age = days_since(key_info.get("rotated") or key_info.get("created"))
    if age == float("inf"):
        return None
    return interval - age


# ═══════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════

class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, on_login):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        import threading
        threading.Thread(target=_try_load_argon2, daemon=True).start()
        self.on_login = on_login
        self.is_new = not VAULT_FILE.exists()

        # Centered card layout
        ctk.CTkFrame(self, fg_color="transparent").pack(fill="both", expand=True)

        card = ctk.CTkFrame(self, fg_color=C["bg2"], corner_radius=12,
                            border_width=1, border_color=C["border"])
        card.pack(pady=40, padx=160, fill="x")

        # Brand logo — placeholder shown immediately, real logo loaded after window appears
        ctk.CTkFrame(card, fg_color="transparent", height=24).pack()
        self._logo_slot = ctk.CTkLabel(card, text="⬡", font=(_MONO_FONT, 28, "bold"),
                                        text_color=C["accent"])
        self._logo_slot.pack(pady=(0, 8))
        self._logo_card = card
        self.after(0, self._load_login_logo)

        ctk.CTkLabel(card, text="PushKey", font=(_UI_FONT, 22, "bold"),
                     text_color=C["text"]).pack()
        sub = "Create a master password to get started" if self.is_new \
            else "Enter your master password to unlock"
        ctk.CTkLabel(card, text=sub, font=FONT_XS,
                     text_color=C["text3"]).pack(pady=(4, 20))

        # Form
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(padx=32, fill="x")

        ctk.CTkLabel(form, text="MASTER PASSWORD", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 4))
        self.pw = ctk.CTkEntry(
            form, show="●", font=FONT_MONO_SM, fg_color=C["bg3"],
            text_color=C["text"], border_color=C["border2"], placeholder_text="Enter password",
        )
        self.pw.pack(fill="x", ipady=5)
        self.pw.focus_set()
        self.pw.bind("<Return>", lambda e: self.unlock())

        if self.is_new:
            ctk.CTkLabel(form, text="CONFIRM PASSWORD", font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", pady=(12, 4))
            self.pw2 = ctk.CTkEntry(
                form, show="●", font=FONT_MONO_SM, fg_color=C["bg3"],
                text_color=C["text"], border_color=C["border2"],
                placeholder_text="Re-enter password",
            )
            self.pw2.pack(fill="x", ipady=5)
            self.pw2.bind("<Return>", lambda e: self.unlock())

        make_btn(
            form,
            "Unlock Vault" if not self.is_new else "Create Vault",
            self.unlock,
            fg_color=C["accent"],
            text_color=C["bg"],
            height=38,
        ).pack(fill="x", pady=(16, 0))

        self.err = ctk.CTkLabel(form, text="", font=FONT_XS, text_color=C["red"])
        self.err.pack(pady=(8, 0))

        ctk.CTkFrame(card, fg_color="transparent", height=28).pack()

        ctk.CTkFrame(self, fg_color="transparent").pack(fill="both", expand=True)

    def _load_login_logo(self):
        _logo_path = _asset_dir() / "pushkey_logo.png"
        if not _logo_path.exists():
            return
        try:
            from PIL import Image as _PILImage
            pil = _PILImage.open(_logo_path).convert("RGBA")
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(80, 80))
            self._logo_slot.configure(image=img, text="")
            self._login_logo_img = img  # keep ref
        except Exception:
            pass

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
                # Refresh server token in background (non-blocking)
                import threading
                threading.Thread(target=maybe_heartbeat, daemon=True).start()
                if mfa_is_enabled():
                    self._show_mfa_prompt(pw, vault)
                else:
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

    def _show_mfa_prompt(self, pw, vault):
        win = ctk.CTkToplevel(self)
        win.title("🔐 Two-Factor Authentication")
        win.geometry("380x260")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.lift()

        ctk.CTkLabel(win, text="🔐", font=("Segoe UI", 36)).pack(pady=(20, 0))
        ctk.CTkLabel(win, text="Two-Factor Authentication",
                     font=FONT_H2, text_color=C["text"]).pack(pady=(4, 2))
        ctk.CTkLabel(win, text="Enter the 6-digit code from your authenticator app\nor a backup code",
                     font=FONT_XS, text_color=C["text3"], justify="center").pack()

        code_var = tk.StringVar()
        code_entry = ctk.CTkEntry(win, textvariable=code_var, font=("Consolas", 20, "bold"),
                                   fg_color=C["bg3"], text_color=C["green"],
                                   border_color=C["border2"], width=200, justify="center")
        code_entry.pack(pady=14, ipady=6)
        code_entry.focus_set()

        err_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["red"])
        err_lbl.pack()

        def verify():
            code = code_var.get().strip().replace(" ", "")
            if mfa_verify(code):
                win.destroy()
                self.on_login(pw, vault)
            else:
                err_lbl.configure(text="❌  Invalid code — try again")
                code_var.set("")

        code_entry.bind("<Return>", lambda e: verify())
        make_btn(win, "✓ Verify", verify,
                 fg_color=C["green_bg"], text_color=C["green"], width=160, height=36).pack(pady=8)


# ═══════════════════════════════════════════════
# MAIN APP SCREEN
# ═══════════════════════════════════════════════

class AppFrame(ctk.CTkFrame):
    def __init__(self, master, password, vault, on_lock, app=None):
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.password = password
        self.vault = vault
        self.on_lock = on_lock
        self.app = app
        self.config = load_config()
        self.revealed = set()
        self._group_by = "file"
        self._collapsed_groups = set()
        self._bulk_select_vars = {}
        self._clipboard_jobs = []
        self._search_var = tk.StringVar()
        self._timeline_subtab = tk.StringVar(value="lifecycle")
        self._timeline_page = 0
        self._timeline_filter = tk.StringVar(value="all")
        self._forecast_window = tk.StringVar(value="30")
        self._tab_rendered: set = set()
        self._tab_dirty: set = set()
        self._search_debounce_id = None

        # ── Top bar ──
        top = ctk.CTkFrame(self, fg_color=C["bg2"], corner_radius=0, height=52)
        top.pack(fill="x")
        top.pack_propagate(False)

        # Brand (left)
        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=(16, 0))
        _logo_path = _asset_dir() / "pushkey_logo.png"
        _logo_loaded = False
        if _logo_path.exists():
            try:
                from PIL import Image as _PILImage
                self._top_pil = _PILImage.open(_logo_path).convert("RGBA")
                self._top_logo_img = ctk.CTkImage(
                    light_image=self._top_pil, dark_image=self._top_pil, size=(28, 28))
                ctk.CTkLabel(brand, image=self._top_logo_img, text="").pack(side="left", padx=(0, 8))
                _logo_loaded = True
            except Exception:
                _logo_loaded = False
        if not _logo_loaded:
            brand_icon = ctk.CTkFrame(brand, fg_color=C["accent_dim"],
                                       width=28, height=28, corner_radius=6)
            brand_icon.pack(side="left", padx=(0, 8))
            brand_icon.pack_propagate(False)
            ctk.CTkLabel(brand_icon, text="⬡", font=(_MONO_FONT, 13, "bold"),
                         text_color=C["accent"]).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(brand, text="PushKey", font=(_UI_FONT, 14, "bold"),
                     text_color=C["text"]).pack(side="left")
        # Tier badge
        t = TIERS[current_tier()]
        tier_lbl = ctk.CTkLabel(brand, text=f"  {t['label']}",
                                 font=FONT_XS, text_color=t["color"], cursor="hand2")
        tier_lbl.pack(side="left", padx=(6, 0))
        tier_lbl.bind("<Button-1>", lambda e: self._enter_license())

        # Right controls — theme toggle + settings + lock only
        right = ctk.CTkFrame(top, fg_color="transparent")
        right.pack(side="right", padx=(0, 14))

        self._theme_btn = make_btn(
            right, "☀" if _CURRENT_THEME == "dark" else "☾",
            self._toggle_theme,
            fg_color=C["btn"], text_color=C["text2"], width=32, height=32,
        )
        self._theme_btn.pack(side="left", padx=3)

        make_btn(right, "⚙", self._show_settings,
                 fg_color=C["btn"], text_color=C["text2"], width=32, height=32,
                 ).pack(side="left", padx=3)

        make_btn(right, "Lock", self.lock,
                 fg_color=C["red_bg"], text_color=C["red"], width=64, height=32,
                 ).pack(side="left", padx=(6, 0))

        # Auto-lock
        self._lock_timeout = 5 * 60 * 1000
        self._lock_timer_id = None
        self._reset_lock_timer()
        self.master.bind("<Key>", lambda e: self._reset_lock_timer(), add="+")
        self.master.bind("<Button>", lambda e: self._reset_lock_timer(), add="+")

        # ── Body: sidebar + content ──
        body = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)

        # Sidebar (180px)
        self._sidebar = ctk.CTkFrame(body, fg_color=C["bg2"], corner_radius=0, width=180)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Thin accent border on right edge of sidebar
        ctk.CTkFrame(body, fg_color=C["border"], width=1, corner_radius=0).pack(side="left", fill="y")

        # Content area
        content = ctk.CTkFrame(body, fg_color=C["bg"], corner_radius=0)
        content.pack(side="left", fill="both", expand=True)

        # ── Sidebar nav ──
        self._nav_btns = {}
        self._active_nav = tk.StringVar(value="dashboard")

        # Logo spacer
        ctk.CTkFrame(self._sidebar, fg_color="transparent", height=16).pack()

        nav_items = [
            ("dashboard", "Dashboard"),
            ("keys",      "All Keys"),
            ("projects",  "Projects"),
            ("security",  "Security"),
            ("cloud",     "Cloud"),
            ("timeline",  "Timeline"),
        ]

        for key, label in nav_items:
            btn = ctk.CTkButton(
                self._sidebar,
                text=label,
                font=FONT_SM,
                anchor="w",
                fg_color="transparent",
                text_color=C["text2"],
                hover_color=C["bg4"],
                corner_radius=6,
                height=36,
                command=lambda k=key: self._nav_switch(k),
            )
            btn.pack(fill="x", padx=10, pady=1)
            self._nav_btns[key] = btn

        # Bottom sidebar items
        ctk.CTkFrame(self._sidebar, fg_color=C["border"], height=1).pack(
            fill="x", padx=12, pady=(8, 0))
        key_count = len([k for k in self.vault if not k.startswith("_")])
        self._sidebar_count_lbl = ctk.CTkLabel(
            self._sidebar,
            text=f"{key_count} key{'s' if key_count != 1 else ''}",
            font=FONT_XS, text_color=C["text3"],
        )
        self._sidebar_count_lbl.pack(padx=14, pady=(6, 0), anchor="w")

        # ── Content frames (grid-stacked, tkraise to switch) ──
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.dash_frame  = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
        self.keys_frame  = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
        self.proj_frame  = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
        self.scan_frame  = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
        self.cloud_frame = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
        self.timeline_frame = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)

        for f in (self.dash_frame, self.keys_frame, self.proj_frame,
                  self.scan_frame, self.cloud_frame, self.timeline_frame):
            f.grid(row=0, column=0, sticky="nsew")

        # Show dashboard by default
        self._nav_switch("dashboard")

        self._scan_results = []
        self._git_scan_results = []
        self._scan_ts = None

        self.after(600, self._check_rotation_schedule)
        # Start local health HTTP server for browser extension
        _start_health_server()
        # Start cloud auto-sync background thread
        self._start_cloud_sync()

    def save(self):
        save_vault(self.vault, self.password)
        save_config(self.config)
        write_health_sidecar(self.vault)

    # ── Nav + theme ───────────────────────────────────────────

    _NAV_FRAMES = {
        "dashboard": "dash_frame",
        "keys":      "keys_frame",
        "projects":  "proj_frame",
        "security":  "scan_frame",
        "cloud":     "cloud_frame",
        "timeline":  "timeline_frame",
    }

    # Maps nav key → render method name (security tab uses render_scan)
    _NAV_RENDER = {
        "dashboard": "render_dashboard",
        "keys":      "render_keys",
        "projects":  "render_projects",
        "security":  "render_scan",
        "cloud":     "render_cloud",
        "timeline":  "render_timeline",
    }

    def _nav_switch(self, key: str):
        self._active_nav.set(key)
        for k, btn in self._nav_btns.items():
            if k == key:
                btn.configure(fg_color=C["accent_dim"], text_color=C["accent"])
            else:
                btn.configure(fg_color="transparent", text_color=C["text2"])
        frame = getattr(self, self._NAV_FRAMES[key])
        frame.tkraise()

        if key not in self._tab_rendered:
            getattr(self, self._NAV_RENDER[key])()
            self._tab_rendered.add(key)
        elif key in self._tab_dirty:
            getattr(self, self._NAV_RENDER[key])()
        self._tab_dirty.discard(key)

    def _invalidate_tabs(self, *tabs: str):
        active = self._active_nav.get()
        for t in tabs:
            if t == active:
                getattr(self, self._NAV_RENDER[t])()
            else:
                self._tab_dirty.add(t)

    def _toggle_theme(self):
        new_mode = "light" if _CURRENT_THEME == "dark" else "dark"
        set_theme(new_mode)
        self.config["theme"] = new_mode
        save_config(self.config)
        if self.app is not None:
            pw, vault = self.password, self.vault
            self.master.after(0, lambda: self.app.reload_app(pw, vault))
        else:
            self._theme_btn.configure(text="☀" if new_mode == "dark" else "☾")

    def _show_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("400x480")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.lift()

        ctk.CTkLabel(win, text="Settings", font=FONT_H2,
                     text_color=C["text"]).pack(anchor="w", padx=20, pady=(18, 12))

        def section(label):
            ctk.CTkLabel(win, text=label, font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", padx=20, pady=(10, 4))

        def row_btn(label, cmd, color=None, text_col=None):
            make_btn(win, label, cmd,
                     fg_color=color or C["btn"],
                     text_color=text_col or C["text2"],
                     width=360, height=34,
                     anchor="w",
                     ).pack(padx=20, pady=2)

        section("VAULT")
        row_btn("Change Master Password", self.change_master_password)
        row_btn("Export Vault", self.export_vault)
        row_btn("Import Vault", self.import_vault)
        row_btn("Import Template", self.show_template)

        section("SECURITY")
        mfa_label = "MFA  ✓  Enabled" if mfa_is_enabled() else "Set Up MFA"
        mfa_col = C["green"] if mfa_is_enabled() else C["text2"]
        row_btn(mfa_label, self.manage_mfa, text_col=mfa_col)
        row_btn("Audit Log", self.show_log)
        row_btn("Policies", self.manage_policies)

        section("TEAM")
        row_btn("Share Vault Export", self.team_share, text_col=C["accent"])
        row_btn("Import Team Export", self.team_import, text_col=C["accent"])

        section("DATA")
        row_btn("Update Providers Registry", self.do_update_providers)

        ctk.CTkFrame(win, fg_color=C["border"], height=1).pack(
            fill="x", padx=20, pady=(16, 10))
        make_btn(win, "Close", win.destroy,
                 fg_color=C["red_bg"], text_color=C["red"],
                 width=100, height=32).pack(pady=4)

    # ── License gate ─────────────────────────────────────────
    def _gate(self, feature: str, current_count: int = 0) -> bool:
        """
        Returns True if allowed. Shows upgrade prompt and returns False if blocked.
        feature: key from UPGRADE_MESSAGES or 'max_keys'/'max_projects' etc.
        """
        # Numeric limits
        if feature in ("max_keys", "max_projects"):
            if within_limit(feature, current_count):
                return True
        # Boolean feature flags
        elif can_do(feature):
            return True

        if feature not in UPGRADE_MESSAGES:
            return True   # unknown feature — let through

        title, body, min_tier = UPGRADE_MESSAGES[feature]
        tier_data = TIERS[min_tier]
        limits = tier_limits()
        tier_name = TIERS[current_tier()]["label"]

        win = ctk.CTkToplevel(self)
        win.title("Upgrade Pushkey")
        win.geometry("440x320")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=title, font=FONT_H2, text_color=C["amber"]).pack(pady=(20, 4))
        ctk.CTkLabel(win, text=body, font=FONT_XS, text_color=C["text3"]).pack()

        # Current vs needed
        sf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        sf.pack(fill="x", padx=24, pady=16)
        row = ctk.CTkFrame(sf, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(row, text=f"Your plan:  {TIERS[current_tier()]['emoji']} {tier_name}",
                     font=FONT_SM, text_color=C["text3"]).pack(anchor="w")
        ctk.CTkLabel(row, text=f"Required:   {tier_data['emoji']} {tier_data['label']}+",
                     font=FONT_SM, text_color=tier_data["color"]).pack(anchor="w", pady=(4, 0))

        if feature == "max_keys":
            limit = tier_limits().get("max_keys")
            ctk.CTkLabel(row, text=f"Keys used:  {current_count} / {limit}",
                         font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(4, 0))
        if feature == "max_projects":
            limit = tier_limits().get("max_projects")
            ctk.CTkLabel(row, text=f"Projects:   {current_count} / {limit}",
                         font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(4, 0))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(0, 16))
        make_btn(btn_row, f"Enter License Key", lambda: (win.destroy(), self._enter_license()),
                 fg_color=C["green_bg"], text_color=C["green"], width=160, height=34).pack(side="left")
        make_btn(btn_row, "Not now", win.destroy, width=90, height=34).pack(side="right")

        return False

    def _enter_license(self):
        win = ctk.CTkToplevel(self)
        win.title("🔑 Activate License")
        win.geometry("480x260")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        tier_data = TIERS[current_tier()]
        ctk.CTkLabel(win, text="🔑 Activate License", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(16, 2))
        ctk.CTkLabel(win, text=f"Current plan: {tier_data['emoji']} {tier_data['label']}",
                     font=FONT_XS, text_color=tier_data["color"]).pack()

        ctk.CTkLabel(win, text="LICENSE KEY", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=20, pady=(16, 2))
        key_entry = ctk.CTkEntry(win, font=FONT_MONO_SM, fg_color=C["bg3"],
                                  text_color=C["text"], border_color=C["border2"],
                                  placeholder_text="PRO-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        key_entry.pack(fill="x", padx=20, ipady=4)
        key_entry.focus_set()

        msg_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"],
                                wraplength=420)
        msg_lbl.pack(pady=(6, 0))

        def activate():
            ok, msg = activate_license(key_entry.get())
            if ok:
                global _LICENSE_CACHE
                _LICENSE_CACHE = None   # force reload
                msg_lbl.configure(text=msg, text_color=C["green"])
                self._invalidate_tabs("dashboard")
                self.after(1500, win.destroy)
            else:
                msg_lbl.configure(text=f"❌ {msg}", text_color=C["red"])

        key_entry.bind("<Return>", lambda e: activate())

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=12)
        make_btn(btn_row, "✅ Activate", activate,
                 fg_color=C["green_bg"], text_color=C["green"], width=160, height=34).pack(side="left", padx=4)

        if current_tier() != "free":
            def do_deactivate():
                ok, msg = deactivate_device()
                color = C["green"] if ok else C["amber"]
                msg_lbl.configure(text=msg, text_color=color)
                global _LICENSE_CACHE
                _LICENSE_CACHE = None
                self._invalidate_tabs("dashboard")

            make_btn(btn_row, "🗑 Deactivate Device", do_deactivate,
                     fg_color=C["bg3"], text_color=C["text3"], width=160, height=34).pack(side="left", padx=4)

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

    def _check_rotation_schedule(self):
        """On unlock: prompt for each overdue scheduled key, one dialog at a time."""
        due = [(n, i) for n, i in self.vault.items()
               if days_until_rotation(i) is not None and days_until_rotation(i) <= 0]
        if not due:
            return
        # Sort most overdue first
        due.sort(key=lambda x: days_until_rotation(x[1]) or 0)
        self._prompt_rotation_queue(due)

    def _prompt_rotation_queue(self, queue):
        if not queue:
            return
        name, info = queue[0]
        remaining = queue[1:]

        provider = info.get("provider")
        prov_data = PROVIDERS.get(provider, {})
        days_left = days_until_rotation(info)
        overdue_days = abs(days_left) if days_left is not None else 0
        schedule = info.get("rotation_schedule", "?")

        win = ctk.CTkToplevel(self)
        win.title(f"Rotation Due — {name}")
        win.geometry("500x340")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.lift()

        # Header
        ctk.CTkLabel(win, text="Rotation Due", font=FONT_H2, text_color=C["amber"]).pack(pady=(16, 2))
        ctk.CTkLabel(win, text=f"{name}  ·  overdue by {overdue_days} day(s)  ·  schedule: every {schedule}d",
                     font=FONT_XS, text_color=C["text3"]).pack()

        # Provider info + link
        if provider:
            pf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
            pf.pack(fill="x", padx=20, pady=(14, 0))
            pr = ctk.CTkFrame(pf, fg_color="transparent")
            pr.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(pr, text=f"Provider: {provider}", font=FONT_SM,
                         text_color=C["text"]).pack(side="left")
            if prov_data.get("url"):
                url = prov_data["url"]
                make_btn(pr, "Open Dashboard →",
                         lambda u=url: webbrowser.open(u),
                         fg_color=C["accent"], text_color="white", width=140).pack(side="right")
                ctk.CTkLabel(pf, text=url, font=FONT_XS, text_color=C["text3"],
                             wraplength=440).pack(anchor="w", padx=12, pady=(0, 8))

        # New key paste
        ctk.CTkLabel(win, text="PASTE NEW KEY VALUE", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=20, pady=(14, 2))
        new_val = ctk.CTkEntry(win, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                               border_color=C["border2"], width=440)
        new_val.pack(padx=20, ipady=4)

        status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"])
        status_lbl.pack(pady=(4, 0))

        def do_rotate():
            val = new_val.get().strip()
            if not val:
                status_lbl.configure(text="Paste your new key value above")
                return
            win.destroy()
            self._apply_rotation(name, val)
            self._invalidate_tabs("dashboard", "keys", "timeline")
            if remaining:
                self.after(300, lambda: self._prompt_rotation_queue(remaining))

        def skip():
            win.destroy()
            if remaining:
                self.after(300, lambda: self._prompt_rotation_queue(remaining))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=12)
        make_btn(btn_row, "Rotate & Sync", do_rotate,
                 fg_color=C["green_bg"], text_color=C["green"], width=140, height=34).pack(side="left")
        make_btn(btn_row, f"Remind me later ({len(remaining)} more)", skip,
                 width=200, height=34).pack(side="right")

        new_val.bind("<Return>", lambda e: do_rotate())

    def manage_mfa(self):
        if mfa_is_enabled():
            self._disable_mfa()
        else:
            self._setup_mfa()

    def _setup_mfa(self):
        secret, uri = mfa_generate_secret("Pushkey Vault")
        backup_codes = mfa_generate_backup_codes()

        win = ctk.CTkToplevel(self)
        win.title("🔐 Set Up Two-Factor Authentication")
        win.geometry("480x560")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="🔐 Enable Two-Factor Auth",
                     font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(win, text="Scan the QR code with Google Authenticator or Authy",
                     font=FONT_XS, text_color=C["text3"]).pack()

        # QR code
        try:
            import qrcode
            from PIL import Image as PILImage
            qr = qrcode.make(uri)
            qr = qr.resize((200, 200), PILImage.LANCZOS)
            img = ctk.CTkImage(light_image=qr, dark_image=qr, size=(200, 200))
            ctk.CTkLabel(win, image=img, text="").pack(pady=12)
        except Exception:
            ctk.CTkLabel(win, text="(install qrcode + pillow to see QR code)",
                         font=FONT_XS, text_color=C["text3"]).pack(pady=8)

        # Manual secret
        sf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=4)
        sf.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(sf, text="MANUAL ENTRY KEY", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(sf, text=secret, font=FONT_MONO_SM, text_color=C["green"]).pack(anchor="w", padx=10, pady=(0, 6))

        # Verify code before saving
        ctk.CTkLabel(win, text="ENTER 6-DIGIT CODE TO CONFIRM", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=20, pady=(4, 2))
        code_var = tk.StringVar()
        code_entry = ctk.CTkEntry(win, textvariable=code_var, font=("Consolas", 18, "bold"),
                                   fg_color=C["bg3"], text_color=C["green"],
                                   width=180, justify="center")
        code_entry.pack(pady=4, ipady=4)
        code_entry.focus_set()

        err_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["red"])
        err_lbl.pack()

        def activate():
            import pyotp
            code = code_var.get().strip()
            totp = pyotp.TOTP(secret)
            if not totp.verify(code, valid_window=1):
                err_lbl.configure(text="❌  Code incorrect — try again")
                return
            mfa_save({"secret": secret, "backup_codes": backup_codes, "enabled_at": datetime.now().isoformat()})
            win.destroy()
            # Show backup codes
            self._show_backup_codes(backup_codes)
            self._invalidate_tabs("security")
            log_event("MFA enabled")

        code_entry.bind("<Return>", lambda e: activate())
        make_btn(win, "✓ Activate MFA", activate,
                 fg_color=C["green_bg"], text_color=C["green"], width=180, height=34).pack(pady=8)

    def _show_backup_codes(self, codes):
        win = ctk.CTkToplevel(self)
        win.title("🔑 Backup Codes — Save These!")
        win.geometry("420x400")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="🔑 Save Your Backup Codes",
                     font=FONT_H2, text_color=C["amber"]).pack(pady=(16, 4))
        ctk.CTkLabel(win, text="Each code can only be used once.\nStore them somewhere safe — you need these if you lose your phone.",
                     font=FONT_XS, text_color=C["text3"], justify="center").pack(pady=(0, 12))

        grid = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        grid.pack(fill="x", padx=20)
        for i, code in enumerate(codes):
            row, col = divmod(i, 2)
            ctk.CTkLabel(grid, text=f"  {code}  ", font=FONT_MONO,
                         text_color=C["text"], fg_color=C["bg3"], corner_radius=4).grid(
                row=row, column=col, padx=8, pady=4, sticky="ew")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append("\n".join(codes))
        make_btn(win, "📋 Copy All", copy_all, fg_color=C["accent"], text_color="white", width=120).pack(pady=12)
        make_btn(win, "Done", win.destroy, width=100).pack()

    def _disable_mfa(self):
        if not messagebox.askyesno("Disable MFA",
                                    "⚠️  Disable two-factor authentication?\n\nThis will remove the extra security layer."):
            return
        MFA_FILE.unlink(missing_ok=True)
        self._invalidate_tabs("security")
        log_event("MFA disabled")
        messagebox.showinfo("MFA Disabled", "Two-factor authentication has been disabled.")

    # ── Hardware MFA (YubiKey / FIDO2) ───────────────────────────
    def manage_hardware_mfa(self):
        if not self._gate("hardware_mfa"):
            return

        win = ctk.CTkToplevel(self)
        win.title("🔐 YubiKey / FIDO2 Hardware MFA")
        win.geometry("480x400")
        win.configure(fg_color=C["bg2"])
        win.transient(self); win.grab_set()

        ctk.CTkLabel(win, text="🔐  Hardware MFA", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        is_enrolled = fido2_is_enabled()
        stored = fido2_load() if is_enrolled else {}

        if is_enrolled:
            ctk.CTkLabel(win, text="✓  YubiKey enrolled", font=FONT_XS, text_color=C["green"]).pack()
            ctk.CTkLabel(win, text=f"Registered: {stored.get('registered','?')[:10]}  ·  Device: {stored.get('device_name','?')}",
                         font=FONT_XS, text_color=C["text3"]).pack(pady=4)

            status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"], wraplength=420)
            status_lbl.pack(pady=4)

            def test_key():
                status_lbl.configure(text="Touch your YubiKey…", text_color=C["amber"])
                win.update()
                try:
                    ok = fido2_authenticate()
                    if ok:
                        status_lbl.configure(text="✓ Authentication successful!", text_color=C["green"])
                    else:
                        status_lbl.configure(text="✗ Verification failed", text_color=C["red"])
                except Exception as e:
                    status_lbl.configure(text=f"Error: {e}", text_color=C["red"])

            def remove_key():
                if messagebox.askyesno("Remove YubiKey", "Remove enrolled YubiKey?\nYou can re-enroll at any time."):
                    FIDO2_FILE.unlink(missing_ok=True)
                    win.destroy()
                    log_event("FIDO2 credential removed")
                    messagebox.showinfo("Removed", "YubiKey credential removed.")

            make_btn(win, "Test YubiKey", test_key, fg_color=C["accent"], text_color="white", width=160, height=34).pack(pady=8)
            make_btn(win, "Remove Enrollment", remove_key, fg_color=C["red_bg"], text_color=C["red"], width=160).pack(pady=4)
        else:
            ctk.CTkLabel(win, text="No hardware key enrolled.\nConnect your YubiKey and click Enroll.",
                         font=FONT_XS, text_color=C["text3"], justify="center").pack(pady=12)

            status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"], wraplength=420)
            status_lbl.pack(pady=4)

            def enroll():
                status_lbl.configure(text="Searching for FIDO2 device…", text_color=C["amber"])
                win.update()
                try:
                    cred = fido2_register()
                    fido2_save(cred)
                    status_lbl.configure(text="✓ YubiKey enrolled!", text_color=C["green"])
                    log_event("FIDO2 credential registered")
                    win.after(1200, lambda: (win.destroy(), self._invalidate_tabs("security")))
                except Exception as e:
                    status_lbl.configure(text=f"Error: {e}", text_color=C["red"])

            make_btn(win, "Enroll YubiKey", enroll,
                     fg_color=C["green_bg"], text_color=C["green"], width=160, height=34).pack(pady=12)

        ctk.CTkLabel(win, text="Hardware MFA requires Enterprise tier.\nOnly one key per vault is supported in this release.",
                     font=FONT_XS, text_color=C["text3"], justify="center").pack(pady=(16, 8))

    # ── SSO / OIDC Device Flow ────────────────────────────────────
    def manage_sso(self):
        if not self._gate("sso"):
            return

        win = ctk.CTkToplevel(self)
        win.title("🏛️ SSO / OIDC Login")
        win.geometry("520x480")
        win.configure(fg_color=C["bg2"])
        win.transient(self); win.grab_set()

        ctk.CTkLabel(win, text="🏛️  SSO Authentication", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))

        is_in = sso_is_logged_in()
        sess = sso_load()
        if is_in:
            ctk.CTkLabel(win, text=f"✓  Signed in via {sess.get('provider','OIDC')}",
                         font=FONT_XS, text_color=C["green"]).pack(pady=4)
            email = sess.get("email", sess.get("sub", ""))
            if email:
                ctk.CTkLabel(win, text=email, font=FONT_MONO_SM, text_color=C["text3"]).pack()

            def logout():
                sso_logout()
                win.destroy()
                messagebox.showinfo("SSO", "Signed out of SSO.")

            make_btn(win, "Sign Out", logout, fg_color=C["red_bg"], text_color=C["red"], width=140, height=34).pack(pady=12)
            return

        # Provider selector
        prov_var = tk.StringVar(value="Okta")
        ctk.CTkLabel(win, text="PROVIDER", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=20)
        ctk.CTkOptionMenu(win, values=list(_SSO_PROVIDERS.keys()), variable=prov_var,
                          fg_color=C["bg3"], button_color=C["accent"],
                          button_hover_color=C["accent2"],
                          text_color=C["text"], font=FONT_SM, width=200).pack(anchor="w", padx=20, pady=(2, 8))

        fields_f = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        fields_f.pack(fill="x", padx=20, pady=(0, 8))
        field_entries: dict = {}

        def refresh_fields(*_):
            for w in fields_f.winfo_children(): w.destroy()
            field_entries.clear()
            p = prov_var.get()
            for key, label in [("client_id", "Client ID"), ("issuer", "Issuer URL / Tenant")]:
                ctk.CTkLabel(fields_f, text=label.upper(), font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
                e = ctk.CTkEntry(fields_f, font=FONT_MONO_SM, fg_color=C["bg3"],
                                 text_color=C["text"], border_color=C["border2"])
                saved = self.config.get("sso_settings", {}).get(key, "")
                if saved: e.insert(0, saved)
                e.pack(fill="x", padx=10, pady=(0, 4), ipady=2)
                field_entries[key] = e

        prov_var.trace_add("write", refresh_fields)
        refresh_fields()

        status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"], wraplength=460)
        status_lbl.pack(padx=20, pady=4)

        def start_flow():
            p = prov_var.get()
            client_id = field_entries["client_id"].get().strip()
            issuer    = field_entries["issuer"].get().strip()
            if not client_id or not issuer:
                status_lbl.configure(text="Client ID and Issuer required.", text_color=C["red"]); return

            tmpl = _SSO_PROVIDERS[p]
            device_url = tmpl["device_auth"].replace("{issuer}", issuer).replace("{tenant}", issuer)
            token_url  = tmpl["token"].replace("{issuer}", issuer).replace("{tenant}", issuer)

            # Persist non-secret settings
            self.config.setdefault("sso_settings", {}).update(
                {"provider": p, "client_id": client_id, "issuer": issuer})
            save_config(self.config)

            status_lbl.configure(text="Starting device flow…", text_color=C["amber"])
            win.update()

            try:
                resp = sso_device_flow_start(client_id, device_url)
            except Exception as e:
                status_lbl.configure(text=f"Error: {e}", text_color=C["red"]); return

            user_code = resp.get("user_code", "")
            verify_uri = resp.get("verification_uri_complete") or resp.get("verification_uri", "")
            device_code = resp.get("device_code", "")
            interval = int(resp.get("interval", 5))

            msg = f"Visit: {verify_uri}\nCode: {user_code}"
            status_lbl.configure(text=msg, text_color=C["amber"])
            if verify_uri:
                webbrowser.open(verify_uri)
            win.update()

            # Poll for token
            def poll():
                token_resp = sso_device_flow_poll(client_id, token_url, device_code)
                if token_resp:
                    exp = datetime.now() + timedelta(seconds=int(token_resp.get("expires_in", 3600)))
                    sso_save({
                        "provider":     p,
                        "access_token": token_resp["access_token"],
                        "expires_at":   exp.isoformat(),
                        "email":        token_resp.get("email", ""),
                        "sub":          token_resp.get("sub", ""),
                    })
                    status_lbl.configure(text="✓ Signed in!", text_color=C["green"])
                    log_event(f"SSO login via {p}")
                    win.after(1200, win.destroy)
                else:
                    win.after(interval * 1000, poll)

            win.after(interval * 1000, poll)

        make_btn(win, "Sign In with SSO", start_flow,
                 fg_color=C["green_bg"], text_color=C["green"], width=180, height=34).pack(pady=8)

    # ── Cloud sync helpers ────────────────────────────────────────
    def _start_cloud_sync(self):
        import threading
        def _loop():
            while True:
                time.sleep(300)
                try:
                    self._cloud_sync_once(silent=True)
                except Exception:
                    pass
        threading.Thread(target=_loop, daemon=True).start()

    def _cloud_sync_once(self, silent: bool = False):
        cfg = self.config.get("cloud", {})
        endpoint = cfg.get("endpoint", "").strip()
        token    = cfg.get("token", "").strip()
        if not endpoint or not token:
            if not silent:
                raise RuntimeError("Cloud sync not configured. Enter endpoint and token.")
            return
        vault_bytes = VAULT_FILE.read_bytes() if VAULT_FILE.exists() else b""
        if not vault_bytes:
            return
        etag = cloud_push(endpoint, token, vault_bytes)
        self.config.setdefault("cloud", {})["last_synced"] = datetime.now().isoformat()
        self.config["cloud"]["etag"] = etag
        save_config(self.config)

    # ── Cloud tab renderer ────────────────────────────────────────
    def render_cloud(self):
        for w in self.cloud_frame.winfo_children():
            w.destroy()

        outer = ctk.CTkFrame(self.cloud_frame, fg_color=C["bg"], corner_radius=0)
        outer.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(outer, fg_color=C["bg2"], corner_radius=0, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="☁️  CLOUD SYNC", font=("Consolas", 11, "bold"),
                     text_color=C["text"]).pack(side="left", padx=16)
        make_btn(hdr, "Sync Now", lambda: self._do_cloud_sync_now(),
                 fg_color=C["accent"], text_color="white").pack(side="right", padx=12, pady=8)

        scroll = ctk.CTkScrollableFrame(outer, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True)
        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=24, pady=16)

        tier = current_tier()
        if not can_do("cloud_sync"):
            ctk.CTkLabel(pad, text="☁️", font=("Segoe UI", 36)).pack(pady=(20, 0))
            ctk.CTkLabel(pad, text="Cloud Sync requires Starter or higher",
                         font=FONT_H2, text_color=C["text"]).pack(pady=(8, 4))
            ctk.CTkLabel(pad, text="Zero-knowledge encrypted backup — server never sees your keys.",
                         font=FONT_XS, text_color=C["text3"]).pack()
            make_btn(pad, "Upgrade Now", lambda: self._gate("cloud_sync"),
                     fg_color=C["amber_bg"], text_color=C["amber"], width=160, height=34).pack(pady=20)
            return

        cfg = self.config.get("cloud", {})
        last_sync = cfg.get("last_synced", "")

        # Status banner
        if last_sync:
            banner_color = C["green_bg"]
            banner_text  = f"✓  Last synced {last_sync[:16]}  ·  {VAULT_FILE.stat().st_size // 1024 + 1} KB"
            banner_fg    = C["green"]
        else:
            banner_color = C["surface"]
            banner_text  = "Not yet synced"
            banner_fg    = C["text3"]
        banner = ctk.CTkFrame(pad, fg_color=banner_color, corner_radius=6)
        banner.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(banner, text=banner_text, font=FONT_XS, text_color=banner_fg).pack(padx=12, pady=8)

        # Settings form
        form = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6)
        form.pack(fill="x", pady=(0, 12))

        entries = {}
        for key, label, is_secret in [
            ("endpoint", "Sync Endpoint URL", False),
            ("token",    "Bearer Token",       True),
        ]:
            ctk.CTkLabel(form, text=label.upper(), font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=12, pady=(8, 0))
            e = ctk.CTkEntry(form, font=FONT_MONO_SM, fg_color=C["bg3"],
                             text_color=C["text"], border_color=C["border2"],
                             show="*" if is_secret else "")
            saved = cfg.get(key, "")
            if saved: e.insert(0, saved)
            e.pack(fill="x", padx=12, pady=(0, 6), ipady=2)
            entries[key] = e

        status_lbl = ctk.CTkLabel(pad, text="", font=FONT_XS, text_color=C["text3"], wraplength=500)
        status_lbl.pack(pady=4)

        def save_settings():
            self.config.setdefault("cloud", {}).update({
                "endpoint": entries["endpoint"].get().strip(),
                "token":    entries["token"].get().strip(),
            })
            save_config(self.config)
            status_lbl.configure(text="Settings saved.", text_color=C["green"])

        btn_row = ctk.CTkFrame(pad, fg_color="transparent")
        btn_row.pack(fill="x")
        make_btn(btn_row, "Save Settings", save_settings,
                 fg_color=C["accent"], text_color="white", width=140, height=32).pack(side="left", padx=(0, 8))

        # Self-host hint
        hint = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6)
        hint.pack(fill="x", pady=(16, 0))
        ctk.CTkLabel(hint, text="SELF-HOSTED BACKEND",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(hint,
                     text="Run pushkey_cloud_api.py (FastAPI + SQLite) on your own server.\n"
                          "API: PUT /api/v1/vault, GET /api/v1/vault, POST /api/v1/auth/login",
                     font=FONT_XS, text_color=C["text3"], justify="left", wraplength=500).pack(anchor="w", padx=12, pady=(4, 8))

    def _do_cloud_sync_now(self):
        try:
            self._cloud_sync_once(silent=False)
            self.render_cloud()
            messagebox.showinfo("Cloud Sync", "✓ Vault synced to cloud.")
        except Exception as e:
            messagebox.showerror("Cloud Sync", f"Sync failed:\n{e}")

    # ── Dynamic Secrets (Enterprise) ──────────────────────────────
    def manage_dynamic_secrets(self):
        if not self._gate("dynamic_secrets"):
            return

        leases = load_leases()
        now = datetime.now()

        win = ctk.CTkToplevel(self)
        win.title("⚙️ Dynamic Secrets")
        win.geometry("620x560")
        win.configure(fg_color=C["bg2"])
        win.transient(self); win.grab_set()

        ctk.CTkLabel(win, text="⚙️  Dynamic Secrets", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(win, text="Lease-based on-demand credentials. Automatically expire.",
                     font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 10))

        # Lease list
        list_frame = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0, height=200)
        list_frame.pack(fill="x", padx=16, pady=(0, 8))

        def refresh_leases():
            for w in list_frame.winfo_children(): w.destroy()
            leases[:] = load_leases()
            if not leases:
                ctk.CTkLabel(list_frame, text="No active leases.", font=FONT_XS,
                             text_color=C["text3"]).pack(pady=12)
                return
            for l in leases:
                exp = datetime.fromisoformat(l["expires"]) if l.get("expires") else None
                expired = exp and exp <= now
                row = ctk.CTkFrame(list_frame, fg_color=C["red_bg"] if expired else C["surface"], corner_radius=4)
                row.pack(fill="x", pady=2)
                left = ctk.CTkFrame(row, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True, padx=10, pady=6)
                ctk.CTkLabel(left, text=f"{l['type'].upper()} / {l.get('iam_user', l['id'])}",
                             font=("Consolas", 10, "bold"),
                             text_color=C["red"] if expired else C["accent"]).pack(anchor="w")
                exp_str = exp.strftime("%Y-%m-%d %H:%M") if exp else "?"
                status_str = "EXPIRED" if expired else "active"
                ctk.CTkLabel(left,
                             text=f"ID: {l['id']}  ·  Expires: {exp_str}  ·  {status_str}",
                             font=FONT_XS, text_color=C["text3"]).pack(anchor="w")

                def do_revoke(lid=l["id"]):
                    revoke_lease(lid)
                    refresh_leases()

                make_btn(row, "Revoke", do_revoke,
                         fg_color=C["red_bg"], text_color=C["red"], width=70).pack(side="right", padx=8, pady=6)

        refresh_leases()

        # New AWS IAM lease
        sep = ctk.CTkFrame(win, fg_color=C["border"], height=1)
        sep.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(win, text="NEW AWS IAM LEASE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=20)

        form = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        form.pack(fill="x", padx=16, pady=(4, 8))
        f_entries = {}

        for key, label, secret in [
            ("iam_user",      "IAM Username",                  False),
            ("admin_key_id",  "Admin AWS Access Key ID",       False),
            ("admin_secret",  "Admin AWS Secret Access Key",   True),
            ("ttl_hours",     "TTL (hours, default 24)",       False),
        ]:
            ctk.CTkLabel(form, text=label.upper(), font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
            e = ctk.CTkEntry(form, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
                             border_color=C["border2"], show="*" if secret else "")
            e.pack(fill="x", padx=10, pady=(0, 4), ipady=2)
            f_entries[key] = e

        status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"], wraplength=560)
        status_lbl.pack(pady=4)

        def create_lease():
            iam_user    = f_entries["iam_user"].get().strip()
            key_id      = f_entries["admin_key_id"].get().strip()
            secret_key  = f_entries["admin_secret"].get().strip()
            ttl_str     = f_entries["ttl_hours"].get().strip()
            ttl_hours   = int(ttl_str) if ttl_str.isdigit() else 24
            if not iam_user or not key_id or not secret_key:
                status_lbl.configure(text="All fields required.", text_color=C["red"]); return
            status_lbl.configure(text="Creating IAM key…", text_color=C["amber"]); win.update()
            try:
                lease = create_aws_lease(iam_user, key_id, secret_key, ttl_hours)
                status_lbl.configure(
                    text=f"✓ Key created: {lease['access_key_id']}\nSecret shown once — copy now.",
                    text_color=C["green"])
                self.clipboard_clear()
                self.clipboard_append(f"{lease['access_key_id']}\n{lease['secret_access_key']}")
                refresh_leases()
            except Exception as e:
                status_lbl.configure(text=f"Error: {e}", text_color=C["red"])

        make_btn(win, "Create AWS Lease", create_lease,
                 fg_color=C["green_bg"], text_color=C["green"], width=180, height=34).pack(pady=8)

    def manage_policies(self):
        """Policy group editor — named permission sets for team sharing."""
        policies = self.vault.get("_policies", {})

        win = ctk.CTkToplevel(self)
        win.title("🏛️ Policy Groups")
        win.geometry("580x560")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="🏛️  Policy Groups", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 2))
        ctk.CTkLabel(win, text="Named permission sets for team vault exports. Apply a policy when sharing.",
                     font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 10))

        list_frame = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0, height=200)
        list_frame.pack(fill="x", padx=16, pady=(0, 8))

        def refresh_list():
            for w in list_frame.winfo_children():
                w.destroy()
            if not policies:
                ctk.CTkLabel(list_frame, text="No policies yet — create one below.",
                             font=FONT_XS, text_color=C["text3"]).pack(pady=12)
                return
            for pname, pdata in policies.items():
                row = ctk.CTkFrame(list_frame, fg_color=C["surface"], corner_radius=4)
                row.pack(fill="x", pady=2)
                left = ctk.CTkFrame(row, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True, padx=10, pady=8)
                ctk.CTkLabel(left, text=pname, font=("Consolas", 10, "bold"),
                             text_color=C["accent"]).pack(anchor="w")
                cats = ", ".join(pdata.get("allowed_categories", [])) or "all categories"
                role = pdata.get("default_role", "editor")
                ctk.CTkLabel(left, text=f"Role: {role}  ·  Categories: {cats}",
                             font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
                make_btn(row, "🗑️", lambda p=pname: (policies.pop(p), _save_and_refresh()),
                         fg_color=C["red_bg"], text_color=C["red"], width=30).pack(side="right", padx=8, pady=8)

        def _save_and_refresh():
            self.vault["_policies"] = policies
            self.save()
            refresh_list()

        refresh_list()

        # Create new policy
        ctk.CTkFrame(win, fg_color=C["border"], height=1).pack(fill="x", padx=16, pady=(4, 8))
        ctk.CTkLabel(win, text="CREATE NEW POLICY", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=16)

        nf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        nf.pack(fill="x", padx=16, pady=(4, 8))

        nr = ctk.CTkFrame(nf, fg_color="transparent")
        nr.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(nr, text="NAME", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(0, 8))
        name_entry = ctk.CTkEntry(nr, font=FONT_SM, fg_color=C["bg3"],
                                   text_color=C["text"], width=200, placeholder_text="e.g. frontend-team")
        name_entry.pack(side="left")

        rr = ctk.CTkFrame(nf, fg_color="transparent")
        rr.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(rr, text="DEFAULT ROLE", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(0, 8))
        role_var = tk.StringVar(value="editor")
        ctk.CTkOptionMenu(rr, values=["owner", "editor", "viewer"], variable=role_var,
                          fg_color=C["bg3"], button_color=C["bg4"], text_color=C["text"],
                          font=FONT_XS, width=110).pack(side="left")

        ctk.CTkLabel(nf, text="ALLOWED CATEGORIES  (unchecked = blocked)",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 2))
        cat_frame = ctk.CTkFrame(nf, fg_color="transparent")
        cat_frame.pack(fill="x", padx=10, pady=(0, 8))
        cat_vars = {}
        all_cats = sorted(CAT_COLORS.keys())
        for i, cat in enumerate(all_cats):
            cv = tk.BooleanVar(value=True)
            cat_vars[cat] = cv
            emoji = CAT_EMOJI.get(cat, "🔑")
            ctk.CTkCheckBox(cat_frame, text=f"{emoji} {cat}", variable=cv,
                            fg_color=C["accent"], hover_color=C["accent2"],
                            text_color=CAT_COLORS.get(cat, C["text"]),
                            font=FONT_XS).grid(row=i//3, column=i%3, sticky="w", padx=4, pady=2)

        def create_policy():
            pname = name_entry.get().strip()
            if not pname:
                return
            allowed = [c for c, v in cat_vars.items() if v.get()]
            policies[pname] = {
                "default_role": role_var.get(),
                "allowed_categories": allowed,
                "created": datetime.now().isoformat(),
            }
            name_entry.delete(0, "end")
            _save_and_refresh()

        make_btn(nf, "✅ Create Policy", create_policy,
                 fg_color=C["green_bg"], text_color=C["green"], width=160).pack(pady=(0, 8))

    def show_log(self):
        entries = _log_decrypt_all()
        win = ctk.CTkToplevel(self)
        win.title("Audit Log")
        win.geometry("640x480")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Audit Log", font=FONT_H2, text_color=C["text"]).pack(pady=(14, 2))
        ctk.CTkLabel(win, text=f"{len(entries)} entries  ·  encrypted at rest",
                     font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 8))

        box = ctk.CTkTextbox(win, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text2"],
                              corner_radius=4)
        box.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        box.insert("1.0", "\n".join(reversed(entries)) if entries else "(no entries)")
        box.configure(state="disabled")
        make_btn(win, "Close", win.destroy, width=100).pack(pady=(0, 12))

    def do_update_providers(self):
        new_c, upd_c, err = update_providers_from_web()
        if err:
            messagebox.showerror("Update Failed", f"Could not fetch provider registry:\n{err}\n\nUsing bundled providers.")
        else:
            total = len(PROVIDERS)
            messagebox.showinfo("Providers Updated",
                                f"Registry updated.\n\n"
                                f"  {new_c} new provider(s) added\n"
                                f"  {upd_c} provider(s) updated\n"
                                f"  {total} total providers loaded")

    def team_share(self):
        if not self._gate("team_rbac"):
            return
        ROLES = ["owner", "editor", "viewer"]
        ROLE_COLORS = {"owner": C["green"], "editor": C["amber"], "viewer": C["text3"]}
        ROLE_PERMS = {
            "owner":  {"can_read": True,  "can_rotate": True,  "can_delete": True},
            "editor": {"can_read": True,  "can_rotate": True,  "can_delete": False},
            "viewer": {"can_read": True,  "can_rotate": False, "can_delete": False},
        }

        win = ctk.CTkToplevel(self)
        win.title("👥 Share Team Vault")
        win.geometry("560x580")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="👥 Share Team Vault", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(win, text="Set permissions per key, then encrypt with a shared passphrase.",
                     font=FONT_XS, text_color=C["text3"]).pack()

        # Per-key role assignment
        ctk.CTkLabel(win, text="KEY PERMISSIONS", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=16, pady=(12, 4))
        key_scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=4, height=220)
        key_scroll.pack(fill="x", padx=16, pady=(0, 8))

        role_vars = {}
        for kname in sorted(self.vault.keys()):
            row = ctk.CTkFrame(key_scroll, fg_color=C["surface"], corner_radius=4)
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=kname, font=FONT_MONO_SM,
                         text_color=C["text"], width=220, anchor="w").pack(side="left", padx=8, pady=6)
            rv = tk.StringVar(value=self.vault[kname].get("team_role", "editor"))
            role_vars[kname] = rv
            om = ctk.CTkOptionMenu(row, values=ROLES, variable=rv, width=100,
                                   fg_color=C["bg3"], button_color=C["bg4"],
                                   button_hover_color=C["btn_hover"], text_color=C["text"], font=FONT_XS)
            om.pack(side="right", padx=8)

        # Policy group quick-apply
        policies = self.vault.get("_policies", {})
        def_row = ctk.CTkFrame(win, fg_color="transparent")
        def_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(def_row, text="SET ALL TO:", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(0, 8))
        for role in ROLES:
            make_btn(def_row, role.capitalize(),
                     lambda r=role: [v.set(r) for v in role_vars.values()],
                     fg_color=C["surface"], text_color=ROLE_COLORS[role], width=70, height=24).pack(side="left", padx=2)

        if policies:
            pol_row = ctk.CTkFrame(win, fg_color="transparent")
            pol_row.pack(fill="x", padx=16, pady=(0, 8))
            ctk.CTkLabel(pol_row, text="🏛️ APPLY POLICY:", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left", padx=(0, 8))
            for pname, pdata in policies.items():
                def apply_policy(pd=pdata):
                    allowed_cats = set(pd.get("allowed_categories", list(CAT_COLORS.keys())))
                    default_role = pd.get("default_role", "editor")
                    for kname, rv in role_vars.items():
                        cat = self.vault.get(kname, {}).get("category", "General")
                        rv.set(default_role if cat in allowed_cats else "viewer")
                make_btn(pol_row, pname, apply_policy,
                         fg_color=C["bg4"], text_color=C["accent"],
                         width=100, height=24).pack(side="left", padx=2)

        # Passphrase
        pf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=4)
        pf.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(pf, text="TEAM PASSPHRASE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(8, 2))
        tp = ctk.CTkEntry(pf, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                          border_color=C["border2"], show="*")
        tp.pack(fill="x", padx=10, ipady=4)
        ctk.CTkLabel(pf, text="CONFIRM", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 2))
        tp2 = ctk.CTkEntry(pf, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                           border_color=C["border2"], show="*")
        tp2.pack(fill="x", padx=10, ipady=4, pady=(0, 8))

        status = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["red"])
        status.pack()

        def do_share():
            passphrase = tp.get().strip()
            if not passphrase:
                status.configure(text="Enter a team passphrase"); return
            if passphrase != tp2.get().strip():
                status.configure(text="Passphrases don't match"); return
            path = filedialog.asksaveasfilename(
                title="Save team vault", defaultextension=".pushkey-team",
                filetypes=[("Pushkey Team Vault", "*.pushkey-team")],
                initialfile="team-vault.pushkey-team")
            if not path:
                return
            # Build permissions map
            permissions = {k: {**ROLE_PERMS[rv.get()], "role": rv.get()}
                           for k, rv in role_vars.items()}
            # Tag roles back on vault keys for future shares
            for k, rv in role_vars.items():
                if k in self.vault:
                    self.vault[k]["team_role"] = rv.get()
            payload = json.dumps({"vault": self.vault, "permissions": permissions,
                                   "shared_by": "pushkey",
                                   "exported_at": datetime.now().isoformat()}, indent=2)
            Path(path).write_bytes(team_encrypt(payload, passphrase))
            win.destroy()
            messagebox.showinfo("✅ Shared",
                                f"Team vault saved.\n\nPermissions:\n" +
                                "\n".join(f"  {k}: {v['role']}" for k, v in list(permissions.items())[:5]) +
                                (f"\n  ...and {len(permissions)-5} more" if len(permissions) > 5 else ""))
            log_event(f"team vault exported to {path}")

        make_btn(win, "🔒 Encrypt & Share", do_share,
                 fg_color=C["green_bg"], text_color=C["green"], width=180, height=34).pack(pady=10)

    def team_import(self):
        path = filedialog.askopenfilename(
            title="Import team vault",
            filetypes=[("Pushkey Team Vault", "*.pushkey-team"), ("All files", "*.*")],
        )
        if not path:
            return

        win = ctk.CTkToplevel(self)
        win.title("Import Team Vault")
        win.geometry("460x240")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Import Team Vault", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(win, text=Path(path).name, font=FONT_MONO_SM, text_color=C["text3"]).pack()

        ctk.CTkLabel(win, text="TEAM PASSPHRASE", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=20, pady=(16, 2))
        tp = ctk.CTkEntry(win, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                          border_color=C["border2"], show="*", width=400)
        tp.pack(padx=20, ipady=4)
        tp.focus_set()

        status = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["red"])
        status.pack(pady=(6, 0))

        def do_import():
            passphrase = tp.get().strip()
            if not passphrase:
                status.configure(text="Enter the team passphrase")
                return
            try:
                raw = Path(path).read_bytes()
                data = json.loads(team_decrypt(raw, passphrase))
            except ValueError:
                status.configure(text="Wrong passphrase or corrupted file")
                return
            except Exception as e:
                status.configure(text=f"Error: {e}")
                return

            team_vault   = data.get("vault", {})
            permissions  = data.get("permissions", {})
            new_keys     = [k for k in team_vault if k not in self.vault]
            updated_keys = [k for k in team_vault if k in self.vault
                            and team_vault[k].get("value") != self.vault[k].get("value")]

            # Build role summary for confirm dialog
            role_summary = {}
            for k, p in permissions.items():
                r = p.get("role", "editor")
                role_summary.setdefault(r, 0)
                role_summary[r] += 1
            roles_str = "  ".join(f"{r}: {n}" for r, n in sorted(role_summary.items()))

            if not messagebox.askyesno("Confirm Import",
                                        f"Team vault — {len(team_vault)} key(s)\n\n"
                                        f"  🆕 {len(new_keys)} new\n"
                                        f"  🔄 {len(updated_keys)} updated\n\n"
                                        f"Roles: {roles_str or 'none set'}\n\n"
                                        f"Merge into your vault?"):
                win.destroy()
                return

            # Apply permissions as metadata on each key
            for k, key_data in team_vault.items():
                if k in permissions:
                    key_data["_rbac"] = permissions[k]
            self.vault.update(team_vault)
            self.save()
            self._invalidate_tabs("dashboard", "keys", "timeline")
            win.destroy()
            log_event(f"team vault imported from {path}: {len(new_keys)} new, {len(updated_keys)} updated")
            messagebox.showinfo("✅ Imported",
                                f"Merged {len(new_keys)} new + {len(updated_keys)} updated keys.\n"
                                f"Permissions applied. Re-encrypted with your master password.")

        tp.bind("<Return>", lambda e: do_import())
        make_btn(win, "Decrypt & Merge", do_import, fg_color=C["green_bg"], text_color=C["green"],
                 width=160, height=34).pack(pady=14)

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
        self._invalidate_tabs("dashboard", "keys", "timeline")
        messagebox.showinfo("Imported", f"Merged {len(new_keys)} new + {len(updated)} updated keys.")

    # ═══════════════════════════════════════════
    # TIMELINE TAB
    # ═══════════════════════════════════════════

    def render_timeline(self):
        for w in self.timeline_frame.winfo_children():
            w.destroy()

        # Header
        header = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(header, text="Timeline", font=FONT_H2,
                     text_color=C["text"]).pack(side="left")

        # Sub-tab bar
        sub_bar = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        sub_bar.pack(fill="x", padx=20, pady=(12, 0))

        subtabs = [("lifecycle", "Lifecycle"), ("activity", "Activity"), ("forecast", "Forecast")]
        for key, label in subtabs:
            is_active = self._timeline_subtab.get() == key
            make_btn(
                sub_bar, label,
                lambda k=key: (self._timeline_subtab.set(k), self._switch_timeline_subtab()),
                fg_color=C["accent_dim"] if is_active else "transparent",
                text_color=C["accent"] if is_active else C["text2"],
                width=90, height=28, corner_radius=6,
            ).pack(side="left", padx=(0, 4))

        ctk.CTkFrame(self.timeline_frame, fg_color=C["border"], height=1).pack(
            fill="x", padx=20, pady=(8, 0))

        # Sub-tab content container
        self._timeline_content = ctk.CTkFrame(self.timeline_frame,
                                               fg_color="transparent", corner_radius=0)
        self._timeline_content.pack(fill="both", expand=True)

        self._switch_timeline_subtab()

    def _switch_timeline_subtab(self):
        for w in self._timeline_content.winfo_children():
            w.destroy()
        sub = self._timeline_subtab.get()
        if sub == "lifecycle":
            self._render_lifecycle()
        elif sub == "activity":
            self._render_activity_tab()
        else:
            self._render_forecast_tab()

    def _render_lifecycle(self):
        real_keys = [(n, v) for n, v in self.vault.items() if not n.startswith("_")]
        if not real_keys:
            ctk.CTkLabel(self._timeline_content, text="No keys yet.",
                         font=FONT_H3, text_color=C["text3"]).pack(pady=40)
            return

        container = ctk.CTkScrollableFrame(self._timeline_content,
                                            fg_color=C["bg"], corner_radius=0)
        container.pack(fill="both", expand=True)

        def _parse_dt(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return None

        now = datetime.now()
        all_created = [_parse_dt(v.get("created")) for _, v in real_keys]
        all_created = [d for d in all_created if d]
        t_start = min(all_created) if all_created else now - timedelta(days=90)
        t_end   = now + timedelta(days=30)
        span = (t_end - t_start).total_seconds()
        if span <= 0:
            span = 1

        NAME_W = 150
        ROW_H  = 32
        PAD    = 12

        header_row = ctk.CTkFrame(container, fg_color=C["bg2"], height=24)
        header_row.pack(fill="x", padx=PAD, pady=(8, 2))
        ctk.CTkLabel(header_row, text="KEY", font=FONT_XS,
                     text_color=C["text3"], width=NAME_W, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(header_row, text="CREATED ──────────── NOW ──── DUE", font=FONT_XS,
                     text_color=C["text3"], anchor="w").pack(side="left", fill="x", expand=True, padx=4)

        for idx, (name, info) in enumerate(sorted(real_keys, key=lambda x: x[0])):
            row_bg = C["bg"] if idx % 2 == 0 else C["bg2"]
            row = ctk.CTkFrame(container, fg_color=row_bg, height=ROW_H, corner_radius=0)
            row.pack(fill="x", padx=PAD, pady=1)
            row.pack_propagate(False)
            row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            lbl = ctk.CTkLabel(row, text=name, font=FONT_MONO_SM,
                               text_color=C["text"], width=NAME_W, anchor="w", cursor="hand2")
            lbl.pack(side="left", padx=4)
            lbl.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            cv = tk.Canvas(row, bg=row_bg, highlightthickness=0, height=ROW_H)
            cv.pack(side="left", fill="x", expand=True, padx=4)

            def _draw_lane(canvas=cv, inf=info, rb=row_bg):
                if not canvas.winfo_exists():
                    return
                canvas.update_idletasks()
                W = canvas.winfo_width()
                if W < 20:
                    return
                H = ROW_H

                created_dt = _parse_dt(inf.get("created"))
                rotated_dt = _parse_dt(inf.get("rotated"))
                status = health_status(inf)
                dot_color = health_color(status)

                def _t_to_x(dt):
                    if dt is None:
                        return None
                    return int((dt - t_start).total_seconds() / span * (W - 10))

                cx_created = _t_to_x(created_dt)
                cx_rotated = _t_to_x(rotated_dt)
                cx_now     = _t_to_x(now)
                days_left  = days_until_rotation(inf)
                cx_due     = _t_to_x(
                    now + timedelta(days=days_left)
                    if days_left is not None else None
                )

                y = H // 2

                if cx_created is not None and cx_now is not None:
                    canvas.create_line(cx_created, y, cx_now, y,
                                       fill=C["border2"], width=2)

                if cx_created is not None:
                    canvas.create_oval(cx_created - 4, y - 4, cx_created + 4, y + 4,
                                       outline=dot_color, fill=rb, width=2)

                if cx_rotated is not None:
                    canvas.create_oval(cx_rotated - 4, y - 4, cx_rotated + 4, y + 4,
                                       fill=dot_color, outline="")

                if cx_now is not None:
                    canvas.create_line(cx_now, 4, cx_now, H - 4,
                                       fill=C["accent"], width=1, dash=(3, 3))

                if cx_due is not None and cx_now is not None and cx_due > cx_now:
                    canvas.create_line(cx_due, 4, cx_due, H - 4,
                                       fill=C["amber"], width=1)
                elif cx_now is not None:
                    canvas.create_line(cx_now, y, min(W - 4, cx_now + 20), y,
                                       fill=C["red"], width=2, dash=(4, 2))

            cv.after(60, _draw_lane)

    def _render_activity_tab(self):
        all_log = list(reversed(_log_decrypt_all()))  # newest first
        PAGE_SIZE = 25

        filter_val = self._timeline_filter.get()
        _filter_map = {
            "rotations": "rotated",
            "imports":   "import",
            "logins":    "unlock",
        }

        if filter_val != "all" and filter_val in _filter_map:
            kw = _filter_map[filter_val]
            all_log = [ln for ln in all_log if kw in ln.lower()]

        total_pages = max(1, (len(all_log) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._timeline_page = max(0, min(self._timeline_page, total_pages - 1))
        page_entries = all_log[self._timeline_page * PAGE_SIZE:(self._timeline_page + 1) * PAGE_SIZE]

        # Filter bar
        filter_bar = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
        filter_bar.pack(fill="x", padx=20, pady=(12, 6))
        for fval, flabel in [("all", "All"), ("rotations", "Rotations"),
                              ("imports", "Imports"), ("logins", "Logins")]:
            is_active = self._timeline_filter.get() == fval
            make_btn(
                filter_bar, flabel,
                lambda v=fval: (self._timeline_filter.set(v),
                                setattr(self, "_timeline_page", 0),
                                self._switch_timeline_subtab()),
                fg_color=C["accent_dim"] if is_active else C["btn"],
                text_color=C["accent"] if is_active else C["text2"],
                width=80, height=24, corner_radius=12,
            ).pack(side="left", padx=2)

        # Log entries
        scroll = ctk.CTkScrollableFrame(self._timeline_content,
                                         fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        _event_colors = {
            "rotated":  C["green"],
            "added":    C["accent"],
            "imported": C["accent"],
            "deleted":  C["amber"],
            "overdue":  C["red"],
            "unlock":   C["text3"],
        }

        if not page_entries:
            ctk.CTkLabel(scroll, text="No activity yet.", font=FONT_XS,
                         text_color=C["text3"]).pack(pady=40)
        else:
            for line in page_entries:
                dot_color = C["text3"]
                for kw, col in _event_colors.items():
                    if kw in line.lower():
                        dot_color = col
                        break

                m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
                ts_str = m.group(1) if m else ""
                body   = m.group(2) if m else line

                entry = ctk.CTkFrame(scroll, fg_color="transparent")
                entry.pack(fill="x", padx=20, pady=1)

                ctk.CTkLabel(entry, text="●", font=(_MONO_FONT, 9),
                             text_color=dot_color, width=14).pack(side="left")
                ctk.CTkLabel(entry, text=ts_str, font=FONT_XS,
                             text_color=C["text3"], width=130,
                             anchor="w").pack(side="left", padx=(4, 8))
                ctk.CTkLabel(entry, text=body, font=FONT_XS,
                             text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)

        # Pagination controls
        if total_pages > 1:
            pg_bar = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
            pg_bar.pack(fill="x", padx=20, pady=8)
            make_btn(pg_bar, "← Prev",
                     lambda: (setattr(self, "_timeline_page", self._timeline_page - 1),
                              self._switch_timeline_subtab()),
                     fg_color=C["btn"], text_color=C["text2"], width=70,
                     ).pack(side="left")
            ctk.CTkLabel(pg_bar,
                         text=f"Page {self._timeline_page + 1} of {total_pages}",
                         font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=12)
            make_btn(pg_bar, "Next →",
                     lambda: (setattr(self, "_timeline_page", self._timeline_page + 1),
                              self._switch_timeline_subtab()),
                     fg_color=C["btn"], text_color=C["text2"], width=70,
                     ).pack(side="left")

    def _render_forecast_tab(self):
        keys_with_schedule = [
            (n, i) for n, i in self.vault.items()
            if not n.startswith("_")
            and i.get("rotation_schedule")
            and isinstance(i["rotation_schedule"], (int, float))
        ]

        if not keys_with_schedule:
            ctk.CTkLabel(self._timeline_content,
                         text="No keys have rotation schedules set.\nSet one in the key detail view.",
                         font=FONT_XS, text_color=C["text3"],
                         justify="center").pack(pady=60)
            return

        DAYS = 90
        COL_W = 18
        ROW_H = 28
        NAME_W = 160
        PAD = 16

        now = datetime.now().date()
        day_range = [now + timedelta(days=d) for d in range(DAYS)]

        outer = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=PAD, pady=(12, 0))

        # Month headers
        month_bar = tk.Canvas(outer, bg=C["bg"], height=20, highlightthickness=0)
        month_bar.pack(fill="x")

        x = NAME_W + 4
        prev_month = None
        for i, day in enumerate(day_range):
            if day.month != prev_month:
                month_bar.create_text(x + 2, 10,
                                      text=day.strftime("%b"),
                                      font=(_UI_FONT, 9), fill=C["text3"],
                                      anchor="w")
                prev_month = day.month
            x += COL_W

        # Day columns + key rows
        canvas_h = ROW_H * len(keys_with_schedule) + 4
        canvas_w = NAME_W + COL_W * DAYS + 4

        scroll_x = tk.Scrollbar(outer, orient="horizontal")
        scroll_x.pack(side="bottom", fill="x")

        cv = tk.Canvas(outer, bg=C["bg"], height=canvas_h,
                       xscrollcommand=scroll_x.set, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.configure(scrollregion=(0, 0, canvas_w, canvas_h))
        scroll_x.config(command=cv.xview)

        for row_idx, (name, info) in enumerate(sorted(keys_with_schedule,
                                                       key=lambda x: x[0])):
            y0 = row_idx * ROW_H
            y1 = y0 + ROW_H
            row_bg = C["bg"] if row_idx % 2 == 0 else C["bg2"]
            cv.create_rectangle(0, y0, canvas_w, y1, fill=row_bg, outline="")

            cv.create_text(4, (y0 + y1) // 2, text=name,
                           font=(_MONO_FONT, 10), fill=C["text"], anchor="w")

            due_days = days_until_rotation(info)

            for col_idx, day in enumerate(day_range):
                x0 = NAME_W + col_idx * COL_W
                x1 = x0 + COL_W - 1

                if day == now:
                    cv.create_rectangle(x0, y0, x1, y1,
                                        fill=C["accent_dim"], outline="")

                if due_days is not None:
                    days_from_now = (day - now).days
                    if due_days <= 0 and days_from_now == 0:
                        cv.create_rectangle(x0 + 1, y0 + 4, x1 - 1, y1 - 4,
                                            fill=C["red"], outline="")
                    elif days_from_now >= 0 and days_from_now == int(due_days):
                        cell_color = C["amber"] if due_days <= 7 else C["green_bg"]
                        cv.create_rectangle(x0 + 1, y0 + 4, x1 - 1, y1 - 4,
                                            fill=cell_color, outline="")

    def render_all(self):
        self.render_dashboard()
        self.render_keys()
        self.render_projects()
        self.render_scan()
        self.render_cloud()
        self.render_timeline()

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
        real_keys = [(n, v) for n, v in keys if not n.startswith("_")]
        total = len(real_keys)
        healthy  = sum(1 for _, v in real_keys if health_status(v) == "healthy")
        warning  = sum(1 for _, v in real_keys if health_status(v) == "warning")
        critical = sum(1 for _, v in real_keys if health_status(v) == "critical")
        projects = len(self.config.get("projects", {}))
        key_limit = tier_limits().get("max_keys")

        # ── Page header ──
        hdr_row = ctk.CTkFrame(pad, fg_color="transparent")
        hdr_row.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(hdr_row, text="Dashboard", font=FONT_H2,
                     text_color=C["text"]).pack(side="left")
        t = TIERS[current_tier()]
        tier_pill = ctk.CTkFrame(hdr_row, fg_color=C["accent_dim"], corner_radius=10)
        tier_pill.pack(side="right")
        ctk.CTkLabel(tier_pill, text=f"{t['label']} Plan",
                     font=FONT_XS, text_color=C["accent"]).pack(padx=8, pady=2)

        # ── Row 1: [Security Gauge] [Stat Cards] [Velocity Gauge] ──
        row1 = ctk.CTkFrame(pad, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 16))

        # Security score gauge (left)
        health_pct = healthy / total if total else 1.0
        score_color = (
            C["red"]    if health_pct < 0.50 else
            C["amber"]  if health_pct < 0.75 else
            C["accent"] if health_pct < 0.90 else
            C["green"]
        )
        score_label = (
            "CRITICAL" if health_pct < 0.50 else
            "AT RISK"  if health_pct < 0.75 else
            "SECURE"   if health_pct < 0.90 else
            "OPTIMAL"
        )
        gauge_left = ctk.CTkFrame(row1, fg_color=C["surface"], corner_radius=8,
                                   border_width=1, border_color=C["border"],
                                   width=170)
        gauge_left.pack(side="left", padx=(0, 8), fill="y")
        gauge_left.pack_propagate(False)
        ctk.CTkLabel(gauge_left, text="Security Score", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=12, pady=(10, 0))
        score_canvas = tk.Canvas(gauge_left, width=160, height=140,
                                  bg=C["surface"], highlightthickness=0)
        score_canvas.pack(pady=(0, 8))
        _draw_arc_gauge(score_canvas, health_pct, score_color,
                        str(int(health_pct * 100)), score_label)

        # Stat cards (center, expanding)
        stats_frame = ctk.CTkFrame(row1, fg_color="transparent")
        stats_frame.pack(side="left", fill="both", expand=True)

        key_display = f"{total} / {key_limit}" if key_limit else str(total)
        key_color   = C["amber"] if key_limit and total >= key_limit * 0.8 else C["text"]
        needs_rotation = warning + critical

        stat_defs = [
            ("Total Keys",    key_display,         key_color,   None,          None),
            ("Healthy",       str(healthy),         C["green"],  healthy,       total),
            ("Need Rotation", str(needs_rotation),
             C["amber"] if needs_rotation else C["green"], needs_rotation, total),
            ("Projects",      str(projects),        C["accent"], None,          None),
        ]
        for label, val, color, bar_val, bar_max in stat_defs:
            card = ctk.CTkFrame(stats_frame, fg_color=C["surface"], corner_radius=8,
                                border_width=1, border_color=C["border"])
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkLabel(card, text=label, font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", padx=14, pady=(12, 2))
            ctk.CTkLabel(card, text=val, font=(_UI_FONT, 26, "bold"),
                         text_color=color).pack(anchor="w", padx=14)
            if bar_val is not None and bar_max and bar_max > 0:
                bar_bg = ctk.CTkFrame(card, fg_color=C["bg3"], height=6, corner_radius=3)
                bar_bg.pack(fill="x", padx=14, pady=(4, 12))
                bar_bg.pack_propagate(False)
                pct_bar = max(0.02, bar_val / bar_max)
                bar_fill = ctk.CTkFrame(bar_bg, fg_color=color, height=6, corner_radius=3,
                                        width=int(pct_bar * 160))
                bar_fill.place(x=0, y=0, relheight=1)
            else:
                ctk.CTkFrame(card, fg_color="transparent", height=22).pack()

        # Rotation velocity gauge (right)
        log_lines = _log_decrypt_all()
        rotations_30d = sum(
            1 for ln in log_lines
            if "rotated" in ln.lower() and _log_line_age_days(ln) <= 30
        )
        target_30d = max(1, len(real_keys) // 3)
        velocity_pct = min(1.0, rotations_30d / target_30d)

        gauge_right = ctk.CTkFrame(row1, fg_color=C["surface"], corner_radius=8,
                                    border_width=1, border_color=C["border"],
                                    width=170)
        gauge_right.pack(side="left", padx=(0, 0), fill="y")
        gauge_right.pack_propagate(False)
        ctk.CTkLabel(gauge_right, text="Rotation Rate", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=12, pady=(10, 0))
        vel_canvas = tk.Canvas(gauge_right, width=160, height=140,
                                bg=C["surface"], highlightthickness=0)
        vel_canvas.pack(pady=(0, 8))
        _draw_arc_gauge(vel_canvas, velocity_pct, C["accent"],
                        str(rotations_30d), "THIS MONTH")

        # ── Row 2: Rotation Forecast Gantt ──
        keys_with_schedule = [
            (n, i) for n, i in real_keys
            if i.get("rotation_schedule") and isinstance(i["rotation_schedule"], (int, float))
        ]
        if keys_with_schedule:
            forecast_hdr = ctk.CTkFrame(pad, fg_color="transparent")
            forecast_hdr.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(forecast_hdr, text="ROTATION FORECAST", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left")

            window_days = int(self._forecast_window.get())
            # Filter to only keys due within the selected window
            keys_with_schedule = [
                (n, i) for n, i in keys_with_schedule
                if days_until_rotation(i) is None or days_until_rotation(i) <= window_days
            ]

            win_menu = ctk.CTkOptionMenu(
                forecast_hdr,
                values=["30", "60", "90"],
                variable=self._forecast_window,
                command=lambda _: self.render_dashboard(),
                width=72, height=24, font=FONT_XS,
                fg_color=C["btn"], button_color=C["btn"],
                button_hover_color=C["btn_hover"], text_color=C["text2"],
            )
            win_menu.pack(side="right")

            gantt_frame = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6,
                                       border_width=1, border_color=C["border"])
            gantt_frame.pack(fill="x", pady=(0, 16))

            for name, info in sorted(keys_with_schedule,
                                     key=lambda x: days_until_rotation(x[1]) or 0):
                schedule = int(info["rotation_schedule"])
                days_left = days_until_rotation(info) or 0
                days_used = schedule - days_left
                fill_pct = max(0.02, min(1.0, days_used / schedule))
                status = health_status(info)
                bar_color = health_color(status)
                overdue = days_left <= 0

                row = ctk.CTkFrame(gantt_frame, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=3)

                # Key name
                ctk.CTkLabel(row, text=name, font=FONT_MONO_SM,
                             text_color=C["text"], width=160,
                             anchor="w").pack(side="left")

                # Bar area
                bar_wrap = ctk.CTkFrame(row, fg_color=C["bg3"], height=8,
                                        corner_radius=4)
                bar_wrap.pack(side="left", fill="x", expand=True, padx=(8, 8))
                bar_wrap.pack_propagate(False)

                def _draw_bar(bw=bar_wrap, pct=fill_pct, col=bar_color):
                    if not bw.winfo_exists():
                        return
                    bw.update_idletasks()
                    w = bw.winfo_width()
                    if w > 10:
                        bar = ctk.CTkFrame(bw, fg_color=col, height=8,
                                           corner_radius=4, width=int(pct * w))
                        bar.place(x=0, y=0, relheight=1)

                bar_wrap.after(50, _draw_bar)

                # Days label + Rotate button
                days_lbl = "OVERDUE" if overdue else f"{abs(int(days_left))}d left"
                ctk.CTkLabel(row, text=days_lbl, font=FONT_XS,
                             text_color=bar_color, width=70).pack(side="left")
                make_btn(row, "Rotate",
                         lambda n=name: (self.rotate_key(n), self._invalidate_tabs("dashboard", "keys", "timeline")),
                         fg_color=C["red_bg"] if overdue else C["btn"],
                         text_color=C["red"] if overdue else C["text2"],
                         width=60, height=24).pack(side="right")

        # Scheduled rotations due
        due_keys = [(n, i) for n, i in keys
                    if days_until_rotation(i) is not None and days_until_rotation(i) <= 0]
        upcoming_keys = [(n, i) for n, i in keys
                         if days_until_rotation(i) is not None and 0 < days_until_rotation(i) <= 7]

        if due_keys or upcoming_keys:
            ctk.CTkLabel(pad, text="🔄  SCHEDULED ROTATIONS", font=FONT_XS,
                         text_color=C["amber"]).pack(anchor="w", pady=(8, 4))
            for name, info in sorted(due_keys + upcoming_keys,
                                     key=lambda x: days_until_rotation(x[1]) or 0):
                days_left = days_until_rotation(info)
                overdue = days_left is not None and days_left <= 0
                row = ctk.CTkFrame(pad, fg_color=C["amber_bg"] if overdue else C["surface"], corner_radius=4)
                row.pack(fill="x", pady=2)
                left = ctk.CTkFrame(row, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True, padx=10, pady=8)
                ctk.CTkLabel(left, text=name, font=FONT_MONO, text_color=C["text"]).pack(anchor="w")
                if overdue:
                    msg = f"Overdue by {abs(days_left)} day(s) — scheduled every {info.get('rotation_schedule')}d"
                    clr = C["amber"]
                else:
                    msg = f"Due in {days_left} day(s) — scheduled every {info.get('rotation_schedule')}d"
                    clr = C["text3"]
                ctk.CTkLabel(left, text=msg, font=FONT_XS, text_color=clr).pack(anchor="w")
                prov = info.get("provider")
                prov_url = PROVIDERS.get(prov, {}).get("url")
                btn_col = ctk.CTkFrame(row, fg_color="transparent")
                btn_col.pack(side="right", padx=8, pady=8)
                make_btn(btn_col, "Rotate Now", lambda n=name: (self.rotate_key(n), self._invalidate_tabs("dashboard", "keys", "timeline")),
                         fg_color=C["amber_bg"], text_color=C["amber"], width=90).pack()
                if prov_url:
                    make_btn(btn_col, f"Open {prov or 'Dashboard'}",
                             lambda u=prov_url: webbrowser.open(u),
                             fg_color="transparent", text_color=C["accent"], width=120).pack(pady=(4, 0))

        # ── Row 3: Recent Activity Feed ──
        all_log = list(reversed(_log_decrypt_all()))  # newest first
        if all_log:
            feed_hdr = ctk.CTkFrame(pad, fg_color="transparent")
            feed_hdr.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(feed_hdr, text="RECENT ACTIVITY", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left")
            view_all = make_btn(feed_hdr, "View all →",
                                lambda: (self._timeline_subtab.set("activity"),
                                         self._nav_switch("timeline")),
                                fg_color="transparent", text_color=C["accent"],
                                width=80, height=22)
            view_all.pack(side="right")

            feed_frame = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6,
                                      border_width=1, border_color=C["border"])
            feed_frame.pack(fill="x", pady=(0, 16))

            _event_colors = {
                "rotated":  C["green"],
                "added":    C["accent"],
                "imported": C["accent"],
                "deleted":  C["amber"],
                "overdue":  C["red"],
            }

            for line in all_log[:8]:
                dot_color = C["text3"]
                for kw, col in _event_colors.items():
                    if kw in line.lower():
                        dot_color = col
                        break

                entry = ctk.CTkFrame(feed_frame, fg_color="transparent")
                entry.pack(fill="x", padx=12, pady=2)

                ctk.CTkLabel(entry, text="●", font=(_MONO_FONT, 9),
                             text_color=dot_color, width=16).pack(side="left")

                # Strip the timestamp prefix for display, show age
                display = line
                m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
                if m:
                    age = _log_line_age_days(line)
                    if age < 1/24:
                        age_str = f"{int(age * 1440)}m ago"
                    elif age < 1:
                        age_str = f"{int(age * 24)}h ago"
                    else:
                        age_str = f"{int(age)}d ago"
                    display = m.group(2)
                    ctk.CTkLabel(entry, text=age_str, font=FONT_XS,
                                 text_color=C["text3"], width=55,
                                 anchor="w").pack(side="left", padx=(2, 6))

                ctk.CTkLabel(entry, text=display, font=FONT_XS,
                             text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)

        # ── Action needed callout cards ──
        if critical + warning > 0:
            ctk.CTkLabel(pad, text="ACTION NEEDED", font=FONT_XS,
                         text_color=C["red"]).pack(anchor="w", pady=(0, 6))
            for name, info in sorted(
                    keys, key=lambda x: days_since(x[1].get("rotated") or x[1].get("created")),
                    reverse=True):
                status = health_status(info)
                if status not in ("critical", "warning"):
                    continue
                age = days_since(info.get("rotated") or info.get("created"))
                provider = info.get("provider")
                prov_data = PROVIDERS.get(provider, {})
                border_col = C["red"] if status == "critical" else C["amber"]

                # Callout card with colored left border accent
                outer = ctk.CTkFrame(pad, fg_color=border_col, corner_radius=6)
                outer.pack(fill="x", pady=2)
                inner = ctk.CTkFrame(outer, fg_color=C["surface"], corner_radius=5)
                inner.pack(fill="both", expand=True, padx=(3, 0))

                left = ctk.CTkFrame(inner, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True, padx=12, pady=8)
                ctk.CTkLabel(left, text=name, font=FONT_MONO,
                             text_color=C["text"]).pack(anchor="w")
                action_msg = f"{age}d old — rotate immediately" if status == "critical" \
                    else f"{age}d old — rotate soon"
                ctk.CTkLabel(left, text=action_msg, font=FONT_XS,
                             text_color=border_col).pack(anchor="w")

                if prov_data.get("url"):
                    make_btn(inner, f"Open {provider}", lambda u=prov_data["url"]: webbrowser.open(u),
                             fg_color=C["btn"], text_color=C["accent"],
                             width=100, height=28).pack(side="right", padx=10)

            ctk.CTkFrame(pad, fg_color=C["border"], height=1).pack(fill="x", pady=(12, 0))

        # ── All keys health list ──
        ctk.CTkLabel(pad, text="ALL KEYS", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", pady=(12, 6))

        if not real_keys:
            # Empty state
            empty = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=8)
            empty.pack(fill="x", pady=20)
            ctk.CTkLabel(empty, text="No keys yet", font=FONT_H3,
                         text_color=C["text"]).pack(pady=(20, 4))
            ctk.CTkLabel(empty, text="Add your first key to start tracking rotation health",
                         font=FONT_XS, text_color=C["text3"]).pack()
            make_btn(empty, "+ New Key", self._show_add_key_modal,
                     fg_color=C["accent"], text_color=C["bg"],
                     height=34).pack(pady=(12, 20))
            return

        for name, info in sorted(real_keys, key=lambda x: x[0]):
            status = health_status(info)
            age = days_since(info.get("rotated") or info.get("created"))
            cat = info.get("category", "General")
            cat_color = CAT_COLORS.get(cat, C["text3"])
            age_text = f"{age}d" if age != float("inf") else "?"
            _hp = {"healthy": (C["green_bg"], C["green"], "Healthy"),
                   "warning":  (C["amber_bg"], C["amber"], "Rotate Soon"),
                   "critical": (C["red_bg"],   C["red"],   "Critical")}
            h_bg, h_fg, h_lbl = _hp.get(status, (C["bg3"], C["text3"], "Unknown"))

            row = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6,
                               border_width=1, border_color=C["border"], cursor="hand2")
            row.pack(fill="x", pady=2)
            row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            # Category dot
            ctk.CTkLabel(row, text="●", font=(_MONO_FONT, 10),
                         text_color=cat_color, width=20).pack(side="left", padx=(10, 0))

            left = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
            left.pack(side="left", fill="x", expand=True, pady=8, padx=6)
            left.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
            lbl = ctk.CTkLabel(left, text=name, font=FONT_MONO_SM,
                               text_color=C["text"], anchor="w", cursor="hand2")
            lbl.pack(anchor="w")
            lbl.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
            ctk.CTkLabel(left, text=cat, font=FONT_XS,
                         text_color=cat_color).pack(anchor="w")

            # Health pill on right
            pill = ctk.CTkFrame(row, fg_color=h_bg, corner_radius=10)
            pill.pack(side="right", padx=12)
            ctk.CTkLabel(pill, text=f"● {h_lbl}", font=FONT_XS,
                         text_color=h_fg).pack(padx=8, pady=3)

    # ═══════════════════════════════════════════
    # ALL KEYS TAB
    # ═══════════════════════════════════════════

    def render_keys(self):
        for w in self.keys_frame.winfo_children():
            w.destroy()

        # ── Header bar: title + action buttons ──
        header = ctk.CTkFrame(self.keys_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 0))

        ctk.CTkLabel(header, text="All Keys", font=FONT_H2,
                     text_color=C["text"]).pack(side="left")

        right_btns = ctk.CTkFrame(header, fg_color="transparent")
        right_btns.pack(side="right")
        make_btn(right_btns, "Scan Import", self.scan_import_folder,
                 fg_color=C["btn"], text_color=C["text2"], height=30).pack(side="left", padx=3)
        make_btn(right_btns, "Upload File", self.bulk_upload_keys,
                 fg_color=C["btn"], text_color=C["text2"], height=30).pack(side="left", padx=3)
        make_btn(right_btns, "+ New Key", self._show_add_key_modal,
                 fg_color=C["accent"], text_color=C["bg"], height=30).pack(side="left", padx=(6, 0))

        # ── Search bar ──
        search_wrap = ctk.CTkFrame(self.keys_frame, fg_color=C["bg3"],
                                    corner_radius=8, border_width=1,
                                    border_color=C["border"])
        search_wrap.pack(fill="x", padx=20, pady=(12, 0))
        ctk.CTkEntry(
            search_wrap, textvariable=self._search_var,
            placeholder_text="Search keys by name, provider, or category...",
            fg_color="transparent", text_color=C["text"],
            border_width=0, font=FONT_SM,
        ).pack(fill="x", padx=4, ipady=4)
        self._search_var.trace_add("write", self._on_search_change)

        # ── Env filter pills ──
        pill_bar = ctk.CTkFrame(self.keys_frame, fg_color="transparent")
        pill_bar.pack(fill="x", padx=20, pady=(8, 4))
        self._env_filter_var = tk.StringVar(value="all")
        for level in ["all"] + ENV_LEVELS[1:]:
            color = C.get(f"env_{level}", C["text3"])
            is_active = level == "all"
            make_btn(
                pill_bar, level.upper(),
                lambda l=level: (self._env_filter_var.set(l), self._render_key_rows()),
                fg_color=C["accent_dim"] if is_active else C["bg3"],
                text_color=C["accent"] if is_active else C["text3"],
                width=58, height=24, corner_radius=12,
            ).pack(side="left", padx=2)

        # ── Column header ──
        col_hdr = ctk.CTkFrame(self.keys_frame, fg_color="transparent")
        col_hdr.pack(fill="x", padx=20, pady=(4, 2))
        ctk.CTkLabel(col_hdr, text="KEY NAME", font=FONT_XS,
                     text_color=C["text3"], width=200, anchor="w").pack(side="left")
        ctk.CTkLabel(col_hdr, text="PROVIDER", font=FONT_XS,
                     text_color=C["text3"], width=120, anchor="w").pack(side="left")
        ctk.CTkLabel(col_hdr, text="ENV", font=FONT_XS,
                     text_color=C["text3"], width=70, anchor="w").pack(side="left")
        ctk.CTkLabel(col_hdr, text="STATUS", font=FONT_XS,
                     text_color=C["text3"], width=100, anchor="w").pack(side="left")

        # Thin divider under header
        ctk.CTkFrame(self.keys_frame, fg_color=C["border"], height=1).pack(
            fill="x", padx=20)

        # ── Scrollable key list ──
        self.keys_scroll = ctk.CTkScrollableFrame(
            self.keys_frame, fg_color=C["bg"], corner_radius=0)
        self.keys_scroll.pack(fill="both", expand=True)

        self._render_key_rows()

    def _on_search_change(self, *_):
        if self._search_debounce_id:
            self.after_cancel(self._search_debounce_id)
        self._search_debounce_id = self.after(200, self._render_key_rows)

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

        # Apply search + env filter
        query = self._search_var.get().lower().strip()
        env_filter = getattr(self, "_env_filter_var", None)
        env_sel = env_filter.get() if env_filter else "all"
        filtered_vault = {
            n: i for n, i in self.vault.items()
            if (not query or query in n.lower()
                or query in (i.get("provider") or "").lower()
                or query in (i.get("source_file") or "").lower()
                or query in (i.get("category") or "").lower())
            and (env_sel == "all" or i.get("env", "all") in ("all", env_sel))
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

            # Show "+ Add Key" button on manual groups when grouping by file
            if self._group_by == "file" and group_key != "Manual" and group_key != "manual":
                clean_name = group_key.replace(".manual", "")
                make_btn(hdr, "+ Add Key", lambda g=clean_name: self.add_group_manual(prefill_group=g),
                         fg_color="transparent", text_color=C["text3"], width=70, height=18).pack(side="right")

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
        cat = info.get("category", "General")
        env = info.get("env", "all")
        val = info["value"]

        # Health pill config
        _hp = {
            "healthy":  (C["green_bg"],  C["green"],  "Healthy"),
            "warning":  (C["amber_bg"],  C["amber"],  "Rotate Soon"),
            "critical": (C["red_bg"],    C["red"],    "Critical"),
        }
        h_bg, h_fg, h_label = _hp.get(status, (C["bg3"], C["text3"], "Unknown"))

        # Env pill config
        env_color = C.get(f"env_{env}", C["text3"])
        env_bg    = C.get(f"{'blue' if env=='dev' else 'amber' if env=='staging' else 'red' if env=='prod' else 'violet'}_bg",
                          C["bg3"])

        row = ctk.CTkFrame(self.keys_scroll, fg_color=C["surface"],
                           corner_radius=5, border_width=1, border_color=C["border"],
                           height=36)
        row.pack(fill="x", padx=2, pady=1)
        row.pack_propagate(False)

        # Checkbox
        sel_var = ctk.BooleanVar(value=False)
        self._bulk_select_vars[name] = sel_var
        ctk.CTkCheckBox(
            row, variable=sel_var, text="",
            fg_color=C["accent"], hover_color=C["accent2"],
            border_color=C["border2"], checkmark_color=C["bg"],
            width=14, height=14,
        ).pack(side="left", padx=(8, 3), pady=0)

        # Category color dot
        cat_col = CAT_COLORS.get(cat, C["text3"])
        ctk.CTkLabel(row, text="●", font=(_MONO_FONT, 9),
                     text_color=cat_col, width=12).pack(side="left", padx=(0, 6))

        # Key name (single line, clickable)
        info_frame = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
        info_frame.pack(side="left", fill="x", expand=True)
        info_frame.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        lbl_n = ctk.CTkLabel(info_frame, text=name, font=FONT_MONO,
                              text_color=C["text"], cursor="hand2", anchor="w")
        lbl_n.pack(anchor="w")
        lbl_n.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

        # Provider column
        prov_frame = ctk.CTkFrame(row, fg_color="transparent", width=100)
        prov_frame.pack(side="left")
        prov_frame.pack_propagate(False)
        if provider:
            ctk.CTkLabel(prov_frame, text=provider, font=FONT_XS,
                         text_color=cat_col, anchor="w").pack(anchor="w")

        # Env pill column
        env_frame = ctk.CTkFrame(row, fg_color="transparent", width=58)
        env_frame.pack(side="left")
        env_frame.pack_propagate(False)
        if env != "all":
            pill = ctk.CTkFrame(env_frame, fg_color=env_bg, corner_radius=8)
            pill.pack(anchor="w")
            ctk.CTkLabel(pill, text=env.upper(), font=FONT_XS,
                         text_color=env_color).pack(padx=5, pady=0)

        # Health pill column
        health_frame = ctk.CTkFrame(row, fg_color="transparent", width=88)
        health_frame.pack(side="left")
        health_frame.pack_propagate(False)
        h_pill = ctk.CTkFrame(health_frame, fg_color=h_bg, corner_radius=10)
        h_pill.pack(anchor="w")
        ctk.CTkLabel(h_pill, text=f"● {h_label}", font=FONT_XS,
                     text_color=h_fg).pack(padx=6, pady=1)

        # Value display
        if revealed:
            display = val
        elif len(val) > 8:
            display = val[:4] + "●" * min(12, len(val) - 8) + val[-4:]
        else:
            display = "●" * len(val)
        ctk.CTkLabel(row, text=display, font=FONT_MONO_SM,
                     text_color=C["accent"] if revealed else C["text3"],
                     width=160, anchor="w").pack(side="left", padx=4)

        # Action buttons
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right", padx=4, pady=0)

        make_btn(btns, "Copy", lambda v=val: self.copy_key(v),
                 fg_color=C["btn"], text_color=C["text2"],
                 width=40, height=22).pack(side="left", padx=1)
        make_btn(btns, "Show" if not revealed else "Hide",
                 lambda n=name: self.toggle_reveal(n),
                 fg_color=C["btn"], text_color=C["text2"],
                 width=40, height=22).pack(side="left", padx=1)
        make_btn(btns, "Rotate", lambda n=name: self.rotate_key(n),
                 fg_color=C["amber_bg"], text_color=C["amber"],
                 width=48, height=22).pack(side="left", padx=1)
        if prov_data.get("url"):
            make_btn(btns, "Open", lambda u=prov_data["url"]: webbrowser.open(u),
                     fg_color=C["btn"], text_color=C["accent"],
                     width=40, height=22).pack(side="left", padx=1)
        make_btn(btns, "Del", lambda n=name: self.delete_key(n),
                 fg_color=C["red_bg"], text_color=C["red"],
                 width=32, height=22).pack(side="left", padx=1)

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
        self._invalidate_tabs("dashboard", "keys", "timeline")

    def _show_add_key_modal(self):
        win = ctk.CTkToplevel(self)
        win.title("New Key")
        win.geometry("520x360")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.lift()

        ctk.CTkLabel(win, text="Add New Key", font=FONT_H2,
                     text_color=C["text"]).pack(anchor="w", padx=24, pady=(20, 16))

        def field(parent, label, widget_fn):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=24, pady=(0, 10))
            ctk.CTkLabel(f, text=label, font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", pady=(0, 3))
            return widget_fn(f)

        self.add_name = field(win, "KEY NAME", lambda p: ctk.CTkEntry(
            p, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
            border_color=C["border2"], placeholder_text="OPENAI_API_KEY",
        ))
        self.add_name.pack(fill="x", ipady=4)

        self.add_value = field(win, "VALUE", lambda p: ctk.CTkEntry(
            p, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"],
            border_color=C["border2"], show="●", placeholder_text="sk-...",
        ))
        self.add_value.pack(fill="x", ipady=4)

        row2 = ctk.CTkFrame(win, fg_color="transparent")
        row2.pack(fill="x", padx=24, pady=(0, 10))

        cf = ctk.CTkFrame(row2, fg_color="transparent")
        cf.pack(side="left", padx=(0, 12), fill="x", expand=True)
        ctk.CTkLabel(cf, text="CATEGORY", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 3))
        self.add_cat = ctk.CTkOptionMenu(
            cf, values=["General", "Trading", "AI", "Database", "Cloud",
                        "Payment", "Comms", "Security", "Crypto"],
            fg_color=C["bg3"], button_color=C["bg4"],
            button_hover_color=C["btn_hover"], text_color=C["text"], font=FONT_XS,
        )
        self.add_cat.set("General")
        self.add_cat.pack(fill="x")

        ef = ctk.CTkFrame(row2, fg_color="transparent")
        ef.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(ef, text="ENVIRONMENT", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 3))
        self.add_env = ctk.CTkOptionMenu(
            ef, values=ENV_LEVELS,
            fg_color=C["bg3"], button_color=C["bg4"],
            button_hover_color=C["btn_hover"], text_color=C["text"], font=FONT_XS,
        )
        self.add_env.set("all")
        self.add_env.pack(fill="x")

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(4, 0))
        make_btn(btn_row, "Add Key", lambda: (self.add_key(), win.destroy()),
                 fg_color=C["accent"], text_color=C["bg"],
                 height=36).pack(side="left", padx=(0, 8))
        make_btn(btn_row, "Cancel", win.destroy,
                 fg_color=C["btn"], text_color=C["text2"],
                 height=36).pack(side="left")

        self.add_name.focus_set()
        self.add_name.bind("<Return>", lambda e: self.add_value.focus_set())
        self.add_value.bind("<Return>", lambda e: (self.add_key(), win.destroy()))

    def add_key(self):
        name = self.add_name.get().strip().upper().replace(" ", "_")
        value = self.add_value.get().strip()
        category = self.add_cat.get()
        env = self.add_env.get() if hasattr(self, "add_env") else "all"

        if not name or not value:
            messagebox.showwarning("Missing info", "Enter both a key name and value")
            return

        # Only gate new keys, not rotations of existing
        if name not in self.vault:
            real_keys = [k for k in self.vault if not k.startswith("_")]
            if not self._gate("max_keys", len(real_keys)):
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
                "env": env,
            }
            msg = f"{name} added"

        self.save()
        injected, errors = self._auto_inject_key(name)
        if injected:
            msg += f" and synced to {injected} project(s)"
        if errors:
            msg += f"\n\nSync failed for {len(errors)} project(s):\n" + "\n".join(errors)

        try:
            self.add_name.delete(0, "end")
            self.add_value.delete(0, "end")
        except Exception:
            pass
        self._invalidate_tabs("dashboard", "keys", "timeline")
        messagebox.showinfo("Done", msg)

    def add_group_manual(self, prefill_group=None):
        """Dialog to add keys to a new or existing group."""
        # Collect existing groups from vault (source_file ending in .manual)
        existing_groups = sorted({
            info["source_file"].replace(".manual", "")
            for info in self.vault.values()
            if info.get("source_file", "").endswith(".manual")
        })

        win = ctk.CTkToplevel(self)
        win.title("Add Keys to Group")
        win.geometry("560x600")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Add Keys to Group", font=FONT_H2, text_color=C["text"]).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(win, text="Pick an existing group to add keys to it, or type a new name.",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=16, pady=(0, 10))

        # Group name section
        gf = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        gf.pack(fill="x", padx=16, pady=(0, 10))

        # Existing group picker (only shown if groups exist)
        group_var = tk.StringVar(value=prefill_group or "")

        if existing_groups:
            picker_row = ctk.CTkFrame(gf, fg_color="transparent")
            picker_row.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(picker_row, text="EXISTING GROUP", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left", padx=(0, 8))

            existing_options = ["— new group —"] + existing_groups
            picker_var = tk.StringVar(value=prefill_group if prefill_group in existing_groups else "— new group —")
            picker = ctk.CTkOptionMenu(
                picker_row, values=existing_options, variable=picker_var,
                fg_color=C["bg3"], button_color=C["accent"], button_hover_color=C["accent2"],
                text_color=C["text"], font=FONT_SM, width=240,
            )
            picker.pack(side="left")

            def on_pick(choice):
                if choice == "— new group —":
                    group_var.set("")
                    name_entry.configure(state="normal")
                    name_entry.focus_set()
                    _refresh_existing_preview("")
                else:
                    group_var.set(choice)
                    name_entry.configure(state="normal")
                    name_entry.delete(0, "end")
                    name_entry.insert(0, choice)
                    name_entry.configure(state="disabled")
                    _refresh_existing_preview(choice)

            picker.configure(command=on_pick)

        name_row = ctk.CTkFrame(gf, fg_color="transparent")
        name_row.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(name_row, text="GROUP NAME", font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=(0, 8))
        name_entry = ctk.CTkEntry(name_row, textvariable=group_var,
                                   placeholder_text="e.g. plaid, stripe, alpaca",
                                   fg_color=C["bg3"], text_color=C["text"], width=260)
        name_entry.pack(side="left")

        # Existing keys preview (populated when picking an existing group)
        preview_frame = ctk.CTkFrame(win, fg_color="transparent")
        preview_frame.pack(fill="x", padx=16, pady=(0, 4))

        def _refresh_existing_preview(group_name):
            for w in preview_frame.winfo_children():
                w.destroy()
            if not group_name:
                return
            label = f"{group_name}.manual"
            members = [(n, i) for n, i in self.vault.items() if i.get("source_file") == label]
            if not members:
                return
            ctk.CTkLabel(preview_frame, text=f"EXISTING KEYS IN '{group_name.upper()}'",
                         font=FONT_XS, text_color=C["text3"]).pack(anchor="w", pady=(0, 4))
            for kname, _ in sorted(members):
                r = ctk.CTkFrame(preview_frame, fg_color=C["surface"], corner_radius=4)
                r.pack(fill="x", pady=1)
                ctk.CTkLabel(r, text=kname, font=FONT_MONO_SM,
                             text_color=C["text2"]).pack(anchor="w", padx=10, pady=4)

        # Pre-fill if coming from context menu
        if prefill_group and prefill_group in existing_groups:
            name_entry.configure(state="disabled")
            _refresh_existing_preview(prefill_group)

        # New key rows
        ctk.CTkLabel(win, text="NEW KEYS TO ADD", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=16, pady=(4, 4))
        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0, height=200)
        scroll.pack(fill="x", padx=16)

        key_rows = []

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

        # Start with one blank row when adding to existing group, two for new
        if prefill_group and prefill_group in existing_groups:
            add_row()
        else:
            add_row("CLIENT_ID", False)
            add_row("SECRET", True)

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
            self._invalidate_tabs("dashboard", "keys", "timeline")
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
        self._invalidate_tabs("dashboard", "keys", "timeline")
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

        self._invalidate_tabs("dashboard", "keys", "timeline")
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
                        inject_env_file(path, self.vault, proj_keys if proj_keys else None,
                                        target_env=proj_info.get("target_env", "all"))
                        self._stamp_keys_used(relevant_keys)
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
                        inject_env_file(path, self.vault, keys_to_write,
                                        target_env=proj_info.get("target_env", "all"))
                        self._stamp_keys_used([key_name])
                        count += 1
                    except Exception as e:
                        log_event(f"env inject failed for {path}: {e}")
                        errors.append(f"{proj_name}: {e}")
        return count, errors

    def _stamp_keys_used(self, key_names):
        now = datetime.now().isoformat()
        changed = False
        for name in key_names:
            if name in self.vault:
                if not self.vault[name].get("first_used"):
                    self.vault[name]["first_used"] = now
                self.vault[name]["last_used"] = now
                changed = True
        if changed:
            self.save()

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

    def _rbac_check(self, name: str, action: str) -> bool:
        """Returns True if action allowed. action: 'can_rotate' | 'can_delete' | 'can_read'"""
        rbac = self.vault.get(name, {}).get("_rbac")
        if not rbac:
            return True
        allowed = rbac.get(action, True)
        if not allowed:
            role = rbac.get("role", "viewer")
            messagebox.showwarning("🔒 Permission Denied",
                                   f"Your role for '{name}' is '{role}'.\n"
                                   f"You don't have permission to {action.replace('can_', '')} this key.")
        return allowed

    def delete_key(self, name):
        if not self._rbac_check(name, "can_delete"):
            return
        if messagebox.askyesno("Delete?", f"Delete '{name}'?\nThis cannot be undone."):
            del self.vault[name]
            self.revealed.discard(name)
            self.save()
            self._invalidate_tabs("dashboard", "keys", "timeline")

    def _apply_rotation(self, name, new_value):
        info = self.vault[name]
        now = datetime.now().isoformat()
        old_val = info["value"]
        info.setdefault("history", [])
        info["history"].insert(0, {"value": old_val, "retired": now})
        info["history"] = info["history"][:10]
        info["previous"] = old_val
        info["value"] = new_value
        info["rotated"] = now
        info["rotation_count"] = info.get("rotation_count", 0) + 1
        self.save()
        injected, errors = self._auto_inject_key(name)
        self._invalidate_tabs("dashboard", "keys", "timeline")
        msg = f"{name} rotated"
        if injected:
            msg += f" and synced to {injected} project(s)"
        if errors:
            msg += f"\n\nSync failed for {len(errors)} project(s):\n" + "\n".join(errors)
        return msg

    def rotate_key(self, name):
        if not self._rbac_check(name, "can_rotate"):
            return
        info = self.vault.get(name)
        if not info:
            return
        provider = info.get("provider")
        prov_data = PROVIDERS.get(provider, {})

        API_ROTATE_PROVIDERS = {"OpenAI", "Anthropic", "AWS"}
        can_api_rotate = provider in API_ROTATE_PROVIDERS

        win = ctk.CTkToplevel(self)
        win.title(f"Rotate {name}")
        win.geometry("520x420" if can_api_rotate else "500x240")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Rotate {name}", font=FONT_H2, text_color=C["text"]).pack(pady=(16, 4))

        if can_api_rotate:
            # ── API auto-rotation section ──
            api_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=4)
            api_frame.pack(fill="x", padx=16, pady=(4, 8))
            ctk.CTkLabel(api_frame, text="AUTO-ROTATE VIA API", font=FONT_XS,
                         text_color=C["green"]).pack(anchor="w", padx=10, pady=(8, 2))

            api_fields = {}
            field_specs = {
                "OpenAI": [("admin_key", "Admin API key (sk-admin-...)", True),
                            ("key_id",   "Old key ID (optional, for deletion)", False)],
                "Anthropic": [("admin_key", "Admin API key (sk-ant-admin-...)", True),
                               ("key_id",   "Old key ID (to deactivate)", False)],
                "AWS":      [("aws_secret", "Current AWS Secret Access Key", True),
                              ("username",  "IAM username (blank = current user)", False)],
            }
            for field_key, label, required in field_specs.get(provider, []):
                ctk.CTkLabel(api_frame, text=label.upper(), font=FONT_XS,
                             text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                e = ctk.CTkEntry(api_frame, font=FONT_MONO_SM, fg_color=C["bg3"],
                                 text_color=C["text"], border_color=C["border2"], show="*" if required else "")
                e.pack(fill="x", padx=10, pady=(0, 4))
                api_fields[field_key] = e

            status_lbl = ctk.CTkLabel(api_frame, text="", font=FONT_XS, text_color=C["text3"])
            status_lbl.pack(anchor="w", padx=10, pady=(2, 8))

            def do_api_rotate():
                creds = {k: v.get().strip() for k, v in api_fields.items()}
                status_lbl.configure(text="Rotating...", text_color=C["amber"])
                win.update()
                result = rotate_key_via_api(provider, info, creds)
                if result.error and not result.partial:
                    status_lbl.configure(text=result.error[:120], text_color=C["red"])
                    return
                if result.new_value and not result.partial:
                    win.destroy()
                    msg = self._apply_rotation(name, result.new_value)
                    messagebox.showinfo("Auto-Rotated", msg)
                elif result.partial:
                    # Anthropic: old key deactivated, need new key pasted
                    status_lbl.configure(text=result.error or "Old key deactivated. Paste new key below.", text_color=C["amber"])
                    if prov_data.get("url"):
                        webbrowser.open(prov_data["url"])

            make_btn(api_frame, "Auto-Rotate Now", do_api_rotate,
                     fg_color=C["green_bg"], text_color=C["green"], width=160).pack(padx=10, pady=(0, 8))

            ctk.CTkLabel(win, text="— or paste manually —", font=FONT_XS,
                         text_color=C["text3"]).pack(pady=(4, 0))
        else:
            if prov_data.get("url"):
                webbrowser.open(prov_data["url"])
            if provider:
                ctk.CTkLabel(win, text=f"{provider} dashboard opened in browser — copy your new key",
                             font=FONT_XS, text_color=C["text3"]).pack()

        # ── Manual paste section (always shown) ──
        ctk.CTkLabel(win, text="PASTE NEW KEY VALUE", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=20, pady=(12, 2))
        new_val = ctk.CTkEntry(win, font=FONT_MONO, fg_color=C["bg3"], text_color=C["text"],
                               border_color=C["border2"], width=440)
        new_val.pack(padx=20, ipady=4)
        new_val.focus_set()

        def do_rotate():
            val = new_val.get().strip()
            if not val:
                messagebox.showwarning("Empty", "Paste the new key value")
                return
            win.destroy()
            msg = self._apply_rotation(name, val)
            messagebox.showinfo("Rotated", msg)

        new_val.bind("<Return>", lambda e: do_rotate())
        make_btn(win, "Save & Sync", do_rotate, fg_color=C["green_bg"], text_color=C["green"],
                 width=160, height=34).pack(pady=12)

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
        win.geometry("560x460")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Rotation History — {name}", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(12, 2))
        ctk.CTkLabel(win, text=f"{len(history)} previous value(s)  ·  click Rollback to restore",
                     font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=16)

        def do_rollback(old_val, entry_idx):
            if not messagebox.askyesno("Rollback?",
                                        f"Restore this value as the current '{name}'?\n\n"
                                        f"Current value will be moved to history.",
                                        parent=win):
                return
            win.destroy()
            msg = self._apply_rotation(name, old_val)
            messagebox.showinfo("Rolled Back", f"Rolled back to entry #{entry_idx + 1}.\n{msg}")

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
            ctk.CTkLabel(rv, text=masked, font=FONT_MONO_SM,
                         text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)
            make_btn(rv, "Rollback", lambda v=val, idx=i: do_rollback(v, idx),
                     fg_color=C["amber_bg"], text_color=C["amber"], width=70).pack(side="right", padx=(4, 0))
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
        env = info.get("env", "all")
        info_field("ENVIRONMENT", env.upper(), fg=ENV_COLORS.get(env, C["text3"]))
        info_field("PROVIDER", provider or "Unknown")
        info_field("CREATED", (info.get("created") or "")[:16].replace("T", " ") or "—", mono=True)
        info_field("LAST ROTATED", (info.get("rotated") or "")[:16].replace("T", " ") or "Never", mono=True)
        info_field("ROTATION COUNT", str(info.get("rotation_count", 0)))

        # Rotation schedule — editable inline
        sched_frame = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=4)
        sched_frame.pack(fill="x", pady=2)
        sf_top = ctk.CTkFrame(sched_frame, fg_color="transparent")
        sf_top.pack(fill="x", padx=10, pady=(6, 4))
        ctk.CTkLabel(sf_top, text="ROTATION SCHEDULE", font=FONT_XS, text_color=C["text3"]).pack(side="left")
        days_left = days_until_rotation(info)
        if days_left is not None:
            if days_left <= 0:
                sched_status = f"overdue {abs(days_left)}d"
                sc = C["amber"]
            else:
                sched_status = f"due in {days_left}d"
                sc = C["green"]
            ctk.CTkLabel(sf_top, text=sched_status, font=FONT_XS, text_color=sc).pack(side="right")
        sched_row = ctk.CTkFrame(sched_frame, fg_color="transparent")
        sched_row.pack(fill="x", padx=10, pady=(0, 6))
        sched_var = tk.StringVar(value=str(info.get("rotation_schedule", "")))
        sched_entry = ctk.CTkEntry(sched_row, textvariable=sched_var, font=FONT_MONO_SM,
                                   fg_color=C["bg3"], text_color=C["text"],
                                   placeholder_text="days, e.g. 30  (blank = no schedule)", width=200)
        sched_entry.pack(side="left")

        def save_schedule():
            val = sched_var.get().strip()
            if val:
                try:
                    int(val)
                except ValueError:
                    return
                info["rotation_schedule"] = int(val)
            else:
                info.pop("rotation_schedule", None)
            self.save()
            self.render_dashboard()

        make_btn(sched_row, "Set", save_schedule, fg_color=C["accent"], text_color="white",
                 width=50).pack(side="left", padx=(6, 0))
        if info.get("first_used"):
            use_days = days_since(info["first_used"])
            info_field("FIRST DEPLOYED", (info["first_used"])[:16].replace("T", " "), mono=True)
            info_field("IN USE FOR", f"{use_days} days", fg=health_color(health_status(info)))
        if info.get("last_used"):
            info_field("LAST DEPLOYED", (info["last_used"])[:16].replace("T", " "), mono=True)

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
        template_path = _asset_dir() / "KEY_IMPORT_TEMPLATE.md"

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
    # SECURITY SCAN TAB
    # ═══════════════════════════════════════════

    SCAN_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json",
                       ".yaml", ".yml", ".toml", ".sh", ".env.example",
                       ".md", ".txt", ".cfg", ".ini", ".conf"}
    SCAN_SKIP_DIRS  = {".git", "__pycache__", "node_modules", ".venv",
                       "venv", ".mypy_cache", "dist", "build", ".next"}

    def _run_scan(self):
        findings = []
        projects = self.config.get("projects", {})
        scan_roots = {info["path"] for info in projects.values()
                      if info.get("path") and os.path.isdir(info["path"])}
        if not scan_roots:
            return findings

        # Build lookup: value -> key_name (skip very short / empty values)
        value_map = {}
        for name, info in self.vault.items():
            val = info.get("value", "")
            if val and len(val) >= 8:
                value_map[val] = name

        if not value_map:
            return findings

        for root in scan_roots:
            for dirpath, dirnames, filenames in os.walk(root):
                # Prune skip dirs in-place
                dirnames[:] = [d for d in dirnames if d not in self.SCAN_SKIP_DIRS]
                for fname in filenames:
                    _, ext = os.path.splitext(fname)
                    # Always skip .env (that's the intended home)
                    if fname == ".env":
                        continue
                    if ext.lower() not in self.SCAN_EXTENSIONS and fname not in {".env.example"}:
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for lineno, line in enumerate(f, 1):
                                for val, key_name in value_map.items():
                                    if val in line:
                                        findings.append({
                                            "key":    key_name,
                                            "file":   fpath,
                                            "line":   lineno,
                                            "snippet": line.rstrip()[:120],
                                        })
                    except Exception:
                        pass
        return findings

    def _run_git_scan(self):
        """Scan git history of linked projects for committed vault key values."""
        findings = []
        value_map = {info["value"]: name for name, info in self.vault.items()
                     if info.get("value") and len(info["value"]) >= 8}
        if not value_map:
            return findings

        import subprocess
        scan_roots = {info["path"] for info in self.config.get("projects", {}).values()
                      if info.get("path") and os.path.isdir(info["path"])}

        for root in scan_roots:
            # Check it's a git repo
            check = subprocess.run(["git", "rev-parse", "--git-dir"],
                                   cwd=root, capture_output=True, timeout=5)
            if check.returncode != 0:
                continue
            try:
                result = subprocess.run(
                    ["git", "log", "--all", "-p", "--no-color", "--format=COMMIT:%H|%an|%ad|%s"],
                    cwd=root, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60
                )
                lines = result.stdout.splitlines()
                current_commit = {}
                current_file = ""
                lineno = 0
                for line in lines:
                    if line.startswith("COMMIT:"):
                        parts = line[7:].split("|", 3)
                        current_commit = {
                            "hash": parts[0][:8] if len(parts) > 0 else "?",
                            "author": parts[1] if len(parts) > 1 else "?",
                            "date": parts[2][:10] if len(parts) > 2 else "?",
                            "message": parts[3][:60] if len(parts) > 3 else "",
                        }
                        lineno = 0
                    elif line.startswith("diff --git"):
                        # Extract file name
                        parts = line.split(" b/", 1)
                        current_file = parts[1] if len(parts) > 1 else line
                        lineno = 0
                    elif line.startswith("@@"):
                        # Parse line number from hunk header
                        try:
                            hunk = line.split("+")[1].split(",")[0]
                            lineno = int(hunk) - 1
                        except Exception:
                            lineno = 0
                    elif line.startswith("+") and not line.startswith("+++"):
                        lineno += 1
                        for val, key_name in value_map.items():
                            if val in line:
                                findings.append({
                                    "key": key_name,
                                    "repo": root,
                                    "file": current_file,
                                    "line": lineno,
                                    "commit": current_commit.get("hash", "?"),
                                    "author": current_commit.get("author", "?"),
                                    "date": current_commit.get("date", "?"),
                                    "message": current_commit.get("message", ""),
                                    "snippet": line[1:].strip()[:100],
                                })
                    elif line.startswith("-"):
                        pass  # don't count deleted lines
                    else:
                        lineno += 1
            except subprocess.TimeoutExpired:
                findings.append({"key": "__error__", "repo": root,
                                  "message": "Git scan timed out (large repo)", "file": "", "line": 0,
                                  "commit": "", "author": "", "date": "", "snippet": ""})
            except Exception as e:
                pass
        return findings

    def run_security_scan(self):
        self._scan_results = self._run_scan()
        self._git_scan_results = self._run_git_scan() if self._gate("git_scan") else []
        self._scan_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_event(f"security scan: {len(self._scan_results)} file finding(s), "
                  f"{len(self._git_scan_results)} git finding(s)")
        self.render_scan()

    def render_scan(self):
        for w in self.scan_frame.winfo_children():
            w.destroy()

        outer = ctk.CTkFrame(self.scan_frame, fg_color=C["bg"], corner_radius=0)
        outer.pack(fill="both", expand=True)

        # Header bar
        hdr = ctk.CTkFrame(outer, fg_color=C["bg2"], corner_radius=0, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🔍  SECRET SCANNER", font=("Consolas", 11, "bold"),
                     text_color=C["text"]).pack(side="left", padx=16)
        if self._scan_ts:
            ctk.CTkLabel(hdr, text=f"Last scan: {self._scan_ts}",
                         font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=8)
        make_btn(hdr, "Run Scan", self.run_security_scan,
                 fg_color=C["amber_bg"], text_color=C["amber"]).pack(side="right", padx=12, pady=8)

        scroll = ctk.CTkScrollableFrame(outer, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=20, pady=16)

        # ── Enterprise feature strip ──────────────────────────────
        ent_row = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6)
        ent_row.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(ent_row, text="ENTERPRISE", font=FONT_XS,
                     text_color=C["amber"]).pack(side="left", padx=12, pady=8)
        make_btn(ent_row, "🔐 YubiKey MFA",     self.manage_hardware_mfa,
                 fg_color=C["bg3"], text_color=C["text"], width=120, height=28).pack(side="left", padx=4, pady=8)
        make_btn(ent_row, "🏛️ SSO Login",       self.manage_sso,
                 fg_color=C["bg3"], text_color=C["text"], width=110, height=28).pack(side="left", padx=4)
        make_btn(ent_row, "⚙️ Dynamic Secrets", self.manage_dynamic_secrets,
                 fg_color=C["bg3"], text_color=C["text"], width=140, height=28).pack(side="left", padx=4)

        if not self._scan_ts:
            # Pre-scan state
            ctk.CTkFrame(pad, fg_color="transparent", height=40).pack()
            ctk.CTkLabel(pad, text="⚠", font=("Segoe UI", 32), text_color=C["amber"]).pack()
            ctk.CTkLabel(pad, text="Scan your projects for exposed secrets",
                         font=FONT_H2, text_color=C["text"]).pack(pady=(8, 4))
            ctk.CTkLabel(pad, text="Finds vault key values hardcoded in source files outside of .env",
                         font=FONT_XS, text_color=C["text3"]).pack()
            exts = "  ".join(sorted(self.SCAN_EXTENSIONS))
            ctk.CTkLabel(pad, text=f"Scans: {exts}", font=FONT_XS,
                         text_color=C["text3"], wraplength=560).pack(pady=(8, 0))
            make_btn(pad, "Run Scan Now", self.run_security_scan,
                     fg_color=C["amber_bg"], text_color=C["amber"], width=160, height=34).pack(pady=24)
            return

        findings = self._scan_results
        if not findings:
            ctk.CTkFrame(pad, fg_color="transparent", height=40).pack()
            ctk.CTkLabel(pad, text="✓", font=("Segoe UI", 32), text_color=C["green"]).pack()
            ctk.CTkLabel(pad, text="No exposed secrets found", font=FONT_H2,
                         text_color=C["green"]).pack(pady=(8, 4))
            ctk.CTkLabel(pad, text="All scanned project files look clean.",
                         font=FONT_XS, text_color=C["text3"]).pack()
            return

        # Group findings by key name
        by_key = {}
        for f in findings:
            by_key.setdefault(f["key"], []).append(f)

        ctk.CTkLabel(pad, text=f"{len(findings)} EXPOSURE(S) FOUND ACROSS {len(by_key)} KEY(S)",
                     font=FONT_XS, text_color=C["red"]).pack(anchor="w", pady=(0, 12))

        for key_name, hits in sorted(by_key.items()):
            grp = ctk.CTkFrame(pad, fg_color=C["red_bg"], corner_radius=6)
            grp.pack(fill="x", pady=(0, 10))

            # Group header
            ghdr = ctk.CTkFrame(grp, fg_color="transparent")
            ghdr.pack(fill="x", padx=12, pady=(8, 4))
            ctk.CTkLabel(ghdr, text=key_name, font=("Consolas", 10, "bold"),
                         text_color=C["red"]).pack(side="left")
            ctk.CTkLabel(ghdr, text=f"{len(hits)} file(s)", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left", padx=8)
            make_btn(ghdr, "Rotate Now", lambda n=key_name: (self.rotate_key(n), self.render_scan()),
                     fg_color=C["red_bg"], text_color=C["red"], width=90).pack(side="right")

            # Hits
            for hit in hits:
                row = ctk.CTkFrame(grp, fg_color=C["surface"], corner_radius=4)
                row.pack(fill="x", padx=10, pady=(0, 4))
                loc = ctk.CTkFrame(row, fg_color="transparent")
                loc.pack(fill="x", padx=10, pady=(6, 2))
                short_path = hit["file"]
                # Trim to last 3 path components for readability
                parts = Path(hit["file"]).parts
                short_path = str(Path(*parts[-3:])) if len(parts) > 3 else hit["file"]
                ctk.CTkLabel(loc, text=f"{short_path}:{hit['line']}",
                             font=FONT_MONO_SM, text_color=C["amber"]).pack(side="left")
                make_btn(loc, "Open", lambda fp=hit["file"], ln=hit["line"]: self._open_file_at_line(fp, ln),
                         width=50).pack(side="right")
                snippet = hit["snippet"].strip()[:100]
                ctk.CTkLabel(row, text=snippet, font=FONT_MONO_SM,
                             text_color=C["text3"], anchor="w",
                             wraplength=540).pack(anchor="w", padx=10, pady=(0, 6))

        # ── Git history scan results ──
        git_findings = getattr(self, "_git_scan_results", [])
        real_git = [f for f in git_findings if f.get("key") != "__error__"]
        errors = [f for f in git_findings if f.get("key") == "__error__"]

        ctk.CTkFrame(pad, fg_color=C["border"], height=1).pack(fill="x", pady=(16, 8))
        ctk.CTkLabel(pad, text="🕵️  GIT HISTORY SCAN", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 4))

        if not self._scan_ts:
            ctk.CTkLabel(pad, text="Run scan above to also check git commit history.",
                         font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        elif not real_git and not errors:
            ctk.CTkLabel(pad, text="✅  No secrets found in git history.",
                         font=FONT_XS, text_color=C["green"]).pack(anchor="w")
        else:
            if errors:
                for e in errors:
                    ctk.CTkLabel(pad, text=f"⚠️  {e.get('message', 'scan error')} — {e.get('repo', '')}",
                                 font=FONT_XS, text_color=C["amber"]).pack(anchor="w")

            if real_git:
                by_key = {}
                for f in real_git:
                    by_key.setdefault(f["key"], []).append(f)

                ctk.CTkLabel(pad,
                             text=f"⚠️  {len(real_git)} commit(s) contain vault key values — rotation alone is NOT enough.\n"
                                  f"    Use BFG Repo-Cleaner or git filter-repo to purge history.",
                             font=FONT_XS, text_color=C["amber"], wraplength=560, justify="left").pack(anchor="w", pady=(0, 8))

                for key_name, hits in sorted(by_key.items()):
                    grp = ctk.CTkFrame(pad, fg_color=C["amber_bg"], corner_radius=6)
                    grp.pack(fill="x", pady=(0, 8))
                    ghdr = ctk.CTkFrame(grp, fg_color="transparent")
                    ghdr.pack(fill="x", padx=12, pady=(8, 4))
                    ctk.CTkLabel(ghdr, text=key_name, font=("Consolas", 10, "bold"),
                                 text_color=C["amber"]).pack(side="left")
                    ctk.CTkLabel(ghdr, text=f"{len(hits)} commit(s)", font=FONT_XS,
                                 text_color=C["text3"]).pack(side="left", padx=8)
                    make_btn(ghdr, "Rotate Now",
                             lambda n=key_name: (self.rotate_key(n), self.render_scan()),
                             fg_color=C["amber_bg"], text_color=C["amber"], width=90).pack(side="right")

                    for hit in hits[:5]:   # cap at 5 per key to avoid huge lists
                        row = ctk.CTkFrame(grp, fg_color=C["surface"], corner_radius=4)
                        row.pack(fill="x", padx=10, pady=(0, 3))
                        meta = f"commit {hit['commit']}  ·  {hit['author']}  ·  {hit['date']}  ·  {hit['file']}"
                        ctk.CTkLabel(row, text=meta, font=FONT_XS,
                                     text_color=C["text3"]).pack(anchor="w", padx=10, pady=(4, 0))
                        ctk.CTkLabel(row, text=hit.get("message", ""), font=FONT_XS,
                                     text_color=C["text2"]).pack(anchor="w", padx=10)
                        ctk.CTkLabel(row, text=hit.get("snippet", "")[:100], font=FONT_MONO_SM,
                                     text_color=C["red"], wraplength=520).pack(anchor="w", padx=10, pady=(0, 6))
                    if len(hits) > 5:
                        ctk.CTkLabel(grp, text=f"  …and {len(hits)-5} more commit(s)",
                                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=12, pady=(0, 6))

    def _open_file_at_line(self, filepath, lineno):
        try:
            # Try VS Code first, fall back to OS default
            import subprocess
            result = subprocess.run(["code", "--goto", f"{filepath}:{lineno}"],
                                    capture_output=True, timeout=3)
            if result.returncode != 0:
                raise OSError
        except Exception:
            webbrowser.open(f"file:///{filepath}")

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

        # Target env for this project
        r2e = ctk.CTkFrame(form, fg_color="transparent")
        r2e.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(r2e, text="TARGET ENV  (only inject keys matching this env)",
                     font=FONT_XS, text_color=C["text3"]).pack(anchor="w")
        self.proj_env = ctk.CTkOptionMenu(
            r2e, values=ENV_LEVELS,
            fg_color=C["bg3"], button_color=C["bg4"], button_hover_color=C["btn_hover"],
            text_color=C["text"], font=FONT_XS, width=120,
        )
        self.proj_env.set("all")
        self.proj_env.pack(anchor="w", ipady=2)

        r2b = ctk.CTkFrame(form, fg_color="transparent")
        r2b.pack(fill="x", padx=12, pady=(0, 12))
        make_btn(r2b, "+ Link Project", self.add_project, fg_color=C["green_bg"], text_color=C["green"], width=110).pack(side="left")

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
            tenv = proj_info.get("target_env", "all")
            if tenv != "all":
                ctk.CTkLabel(name_row2, text=f"  {tenv.upper()}",
                             font=FONT_XS, text_color=ENV_COLORS.get(tenv, C["text3"])).pack(side="left")

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
            make_btn(btn_f, "🔄 Sync .env", lambda p=proj_name: self.sync_project(p),
                     fg_color=C["accent"], text_color="white", width=90).pack(pady=2)
            make_btn(btn_f, "☁️ CI Sync", lambda p=proj_name: self.ci_sync_project(p),
                     fg_color=C["bg4"], text_color=C["accent"], width=90).pack(pady=2)
            make_btn(btn_f, "🔑 Assign Keys", lambda p=proj_name: self.assign_keys_to_project(p), width=90).pack(pady=2)
            make_btn(btn_f, "🗑️ Remove", lambda p=proj_name: self.remove_project(p),
                     fg_color=C["red_bg"], text_color="#FCA5A5", width=90).pack(pady=2)

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

        proj_count = len(self.config.get("projects", {}))
        if not self._gate("max_projects", proj_count):
            return

        if "projects" not in self.config:
            self.config["projects"] = {}

        target_env = self.proj_env.get() if hasattr(self, "proj_env") else "all"
        matched = self._auto_match_keys(name)
        self.config["projects"][name] = {
            "path": path,
            "keys": matched,
            "added": datetime.now().isoformat(),
            "target_env": target_env,
        }

        try:
            inject_env_file(path, self.vault, target_env=target_env)
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
                inject_env_file(path, self.vault, keys_to_write if keys_to_write else None,
                                target_env=proj.get("target_env", "all"))
                self._stamp_keys_used(keys_to_write)
                log_event(f"sync: wrote {len(keys_to_write)} keys to {path}/.env")
                messagebox.showinfo("Synced", f".env written to:\n{path}\n\n{len(keys_to_write)} key(s) synced.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to write .env:\n{e}")

        make_btn(btn_f, "Confirm & Write .env", confirm, fg_color=C["green_bg"], text_color=C["green"], width=160).pack(side="left")
        make_btn(btn_f, "Cancel", win.destroy, width=80).pack(side="left", padx=(8, 0))

    def ci_sync_project(self, proj_name):
        if not self._gate("ci_sync"):
            return
        proj = self.config["projects"].get(proj_name, {})
        assigned = set(proj.get("keys", []))
        keys_to_sync = {k: self.vault[k]["value"] for k in assigned if k in self.vault}

        win = ctk.CTkToplevel(self)
        win.title(f"☁️ CI Sync — {proj_name}")
        win.geometry("540x560")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="☁️  CI / Cloud Sync", font=FONT_H2,
                     text_color=C["text"]).pack(pady=(16, 2))
        ctk.CTkLabel(win, text=f"Push {len(keys_to_sync)} key(s) to your cloud platform",
                     font=FONT_XS, text_color=C["text3"]).pack(pady=(0, 12))

        # Platform selector
        platform_var = tk.StringVar(value=proj.get("ci_platform", "GitHub Actions"))
        platforms = ["GitHub Actions", "Vercel", "Railway"]
        ctk.CTkLabel(win, text="PLATFORM", font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=20)
        platform_menu = ctk.CTkOptionMenu(win, values=platforms, variable=platform_var,
                                          fg_color=C["bg3"], button_color=C["accent"],
                                          button_hover_color=C["accent2"],
                                          text_color=C["text"], font=FONT_SM, width=200)
        platform_menu.pack(anchor="w", padx=20, pady=(2, 10))

        # Dynamic fields frame
        fields_frame = ctk.CTkFrame(win, fg_color=C["surface"], corner_radius=6)
        fields_frame.pack(fill="x", padx=20, pady=(0, 8))
        field_entries = {}

        PLATFORM_FIELDS = {
            "GitHub Actions": [
                ("github_owner", "GitHub owner / org", False),
                ("github_repo",  "Repository name",   False),
                ("github_token", "Personal access token (repo scope)", True),
            ],
            "Vercel": [
                ("vercel_token",      "Vercel API token",  True),
                ("vercel_project_id", "Project ID",        False),
                ("vercel_target",     "Environment (production/preview/development/all)", False),
            ],
            "Railway": [
                ("railway_token",      "Railway API token",  True),
                ("railway_project_id", "Project ID",         False),
                ("railway_env_id",     "Environment ID",     False),
            ],
        }

        def refresh_fields(*_):
            for w in fields_frame.winfo_children():
                w.destroy()
            field_entries.clear()
            plat = platform_var.get()
            for key, label, secret in PLATFORM_FIELDS.get(plat, []):
                ctk.CTkLabel(fields_frame, text=label.upper(),
                             font=FONT_XS, text_color=C["text3"]).pack(anchor="w", padx=10, pady=(6, 0))
                saved = proj.get(key, "")
                e = ctk.CTkEntry(fields_frame, font=FONT_MONO_SM, fg_color=C["bg3"],
                                 text_color=C["text"], show="*" if secret else "",
                                 border_color=C["border2"])
                if saved:
                    e.insert(0, saved)
                e.pack(fill="x", padx=10, pady=(0, 4), ipady=2)
                field_entries[key] = e

        platform_var.trace_add("write", refresh_fields)
        refresh_fields()

        status_lbl = ctk.CTkLabel(win, text="", font=FONT_XS, text_color=C["text3"],
                                   wraplength=480, justify="left")
        status_lbl.pack(padx=20, pady=(4, 0))

        def do_sync():
            plat = platform_var.get()
            creds = {k: e.get().strip() for k, e in field_entries.items()}
            # Persist non-secret creds
            for k, v in creds.items():
                if "token" not in k:
                    proj[k] = v
            proj["ci_platform"] = plat
            save_config(self.config)

            status_lbl.configure(text="Syncing…", text_color=C["amber"])
            win.update()

            if plat == "GitHub Actions":
                ok, errs = sync_github_actions(
                    creds.get("github_owner", ""),
                    creds.get("github_repo", ""),
                    creds.get("github_token", ""),
                    keys_to_sync)
            elif plat == "Vercel":
                ok, errs = sync_vercel(
                    creds.get("vercel_token", ""),
                    creds.get("vercel_project_id", ""),
                    creds.get("vercel_target", "production"),
                    keys_to_sync)
            elif plat == "Railway":
                ok, errs = sync_railway(
                    creds.get("railway_token", ""),
                    creds.get("railway_project_id", ""),
                    creds.get("railway_env_id", ""),
                    keys_to_sync)
            else:
                ok, errs = 0, ["Unknown platform"]

            if errs:
                status_lbl.configure(
                    text=f"⚠️  {ok} synced, {len(errs)} error(s):\n" + "\n".join(errs[:3]),
                    text_color=C["amber"])
            else:
                log_event(f"CI sync: {ok} key(s) → {plat} for {proj_name}")
                status_lbl.configure(
                    text=f"✅  {ok} key(s) synced to {plat} successfully.",
                    text_color=C["green"])

        make_btn(win, "☁️ Push to Cloud", do_sync,
                 fg_color=C["accent"], text_color="white", width=180, height=34).pack(pady=12)

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
        _check_crypto_deps()
        # Load persisted theme before any widgets are created
        _boot_cfg = {}
        if CONFIG_FILE.exists():
            try:
                raw = CONFIG_FILE.read_bytes()
                if raw.lstrip()[:1] == b"{":
                    _boot_cfg = json.loads(raw)
            except Exception:
                pass
        _saved_theme = _boot_cfg.get("theme", "light")
        set_theme(_saved_theme)

        self.root = ctk.CTk()
        self.root.title("Pushkey")
        self.root.geometry("960x680")
        self.root.configure(fg_color=C["bg"])
        try:
            _ico = Path(__file__).with_name("pushkey.ico")
            if _ico.exists():
                self.root.iconbitmap(str(_ico))
        except Exception:
            pass
        self.root.resizable(True, True)
        self.root.minsize(800, 560)
        self.root.update()  # show window immediately before heavy init

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
        write_health_sidecar(vault)
        self.switch(AppFrame, password=pw, vault=vault, on_lock=self.show_login, app=self)

    def reload_app(self, pw, vault):
        self.root.configure(fg_color=C["bg"])
        self.switch(AppFrame, password=pw, vault=vault, on_lock=self.show_login, app=self)


def _cli_main(args):
    """Headless CLI — no GUI launched."""
    import argparse, getpass

    parser = argparse.ArgumentParser(prog="pushkey", description="Pushkey CLI — encrypted key vault")
    parser.add_argument("--password", "-p", help="Master password (or set PUSHKEY_PASSWORD env var)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # pushkey inject <path> [--env dev]
    p_inj = sub.add_parser("inject", help="Write .env to a folder")
    p_inj.add_argument("path", help="Project folder path")
    p_inj.add_argument("--env", default="all", choices=ENV_LEVELS, help="Target environment")
    p_inj.add_argument("--keys", nargs="*", help="Specific key names to inject (default: all)")

    # pushkey list [--env dev]
    p_lst = sub.add_parser("list", help="List keys and health status")
    p_lst.add_argument("--env", default="all", choices=ENV_LEVELS + ["all"])
    p_lst.add_argument("--json", action="store_true", dest="as_json", help="Output JSON")

    # pushkey status
    sub.add_parser("status", help="Health summary")

    # pushkey rotate <key>
    p_rot = sub.add_parser("rotate", help="Rotate a key value")
    p_rot.add_argument("key", help="Key name")
    p_rot.add_argument("--value", "-v", help="New value (prompted if omitted)")

    ns = parser.parse_args(args)

    pw = ns.password or os.environ.get("PUSHKEY_PASSWORD")
    if not pw:
        try:
            pw = getpass.getpass("Pushkey master password: ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            raise SystemExit(1)

    ensure_vault_dir()
    try:
        vault = load_vault(pw)
    except ValueError as e:
        print(f"Error: {e}")
        raise SystemExit(1)

    if ns.cmd == "inject":
        path = ns.path
        if not os.path.isdir(path):
            print(f"Error: folder not found: {path}")
            raise SystemExit(1)
        try:
            inject_env_file(path, vault, key_names=ns.keys, target_env=ns.env)
            written = [k for k in (ns.keys or vault.keys())
                       if k in vault and (ns.env == "all" or vault[k].get("env", "all") in ("all", ns.env))]
            print(f"OK  wrote {len(written)} key(s) to {path}/.env")
        except Exception as e:
            print(f"Error: {e}")
            raise SystemExit(1)

    elif ns.cmd == "list":
        rows = []
        for name, info in sorted(vault.items()):
            env = info.get("env", "all")
            if ns.env != "all" and env not in ("all", ns.env):
                continue
            status = health_status(info)
            age = days_since(info.get("rotated") or info.get("created"))
            age_str = f"{age}d" if age != float("inf") else "?"
            rows.append({"name": name, "status": status, "age": age_str,
                         "env": env, "provider": info.get("provider", "")})
        if ns.as_json:
            print(json.dumps(rows, indent=2))
        else:
            status_icon = {"healthy": "✓", "warning": "!", "critical": "✗"}
            for r in rows:
                icon = status_icon.get(r["status"], "?")
                print(f"{icon}  {r['name']:<40} {r['status']:<10} {r['age']:<8} {r['env']:<10} {r['provider']}")

    elif ns.cmd == "status":
        total = len(vault)
        by_status = {"healthy": 0, "warning": 0, "critical": 0}
        for info in vault.values():
            by_status[health_status(info)] += 1
        print(f"Pushkey vault — {total} key(s)")
        print(f"  ✓ healthy:   {by_status['healthy']}")
        print(f"  ! warning:   {by_status['warning']}")
        print(f"  ✗ critical:  {by_status['critical']}")

    elif ns.cmd == "rotate":
        if ns.key not in vault:
            print(f"Error: key '{ns.key}' not found in vault")
            raise SystemExit(1)
        new_val = ns.value
        if not new_val:
            try:
                new_val = getpass.getpass(f"New value for {ns.key}: ")
            except (EOFError, KeyboardInterrupt):
                print("Aborted.")
                raise SystemExit(1)
        now = __import__("datetime").datetime.now().isoformat()
        info = vault[ns.key]
        info.setdefault("history", []).insert(0, {"value": info["value"], "retired": now})
        info["history"] = info["history"][:10]
        info["value"] = new_val
        info["rotated"] = now
        info["rotation_count"] = info.get("rotation_count", 0) + 1
        save_vault(vault, pw)
        print(f"OK  {ns.key} rotated")


def main():
    import sys
    # If CLI args present (beyond script name), run headless
    if len(sys.argv) > 1:
        _cli_main(sys.argv[1:])
        return
    ensure_vault_dir()
    PushkeyApp()


if __name__ == "__main__":
    main()

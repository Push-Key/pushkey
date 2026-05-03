"""
Pushkey — shared constants and lowest-level vault directory utilities.
Zero local imports — safe to import from any other pushkey module.
"""
import os
import secrets
from pathlib import Path

VAULT_DIR = Path.home() / ".pushkey"
VAULT_FILE = VAULT_DIR / "vault.enc"
SALT_FILE = VAULT_DIR / ".salt"
CONFIG_FILE = VAULT_DIR / "config.json"
LOG_FILE = VAULT_DIR / "pushkey.log"
HEALTH_FILE = VAULT_DIR / "health.json"
PROVIDERS_CACHE = VAULT_DIR / "providers.json"
PROVIDERS_REGISTRY_URL = "https://raw.githubusercontent.com/ebothegreat/pushkey/main/providers.json"
IMPORT_DIR = VAULT_DIR / "import"
MFA_FILE = VAULT_DIR / ".mfa"
LICENSE_FILE = VAULT_DIR / ".license"
TOKEN_FILE = VAULT_DIR / ".token"
FIDO2_FILE = VAULT_DIR / ".fido2"
SSO_FILE = VAULT_DIR / ".sso"
LEASES_FILE = VAULT_DIR / "leases.json"
HEALTH_PORT = 7654

ACTIVATION_SERVER = os.environ.get("PUSHKEY_SERVER", "https://api.pushkey.dev")
_TOKEN_GRACE_DAYS = 10

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
    "max_keys":        ("🔑 Key limit reached",              "Upgrade to add more keys.",             "starter"),
    "max_projects":    ("📁 Project limit reached",          "Upgrade to link more projects.",        "starter"),
    "cloud_sync":      ("☁️ Cloud sync is Pro+",             "Upgrade for encrypted cloud backup.",   "starter"),
    "ci_sync":         ("⚡ CI sync is Pro+",                 "Upgrade to push to GitHub/Vercel.",     "pro"),
    "team_rbac":       ("👥 Team RBAC is Team+",              "Upgrade to share with your team.",      "team"),
    "hardware_mfa":    ("🔐 YubiKey is Enterprise",          "Upgrade for hardware MFA.",             "enterprise"),
    "sso":             ("🏛️ SSO is Enterprise",               "Upgrade for SAML/Okta/Azure AD.",       "enterprise"),
    "dynamic_secrets": ("⚙️ Dynamic secrets is Enterprise",  "Upgrade for lease-based secrets.",      "enterprise"),
    "git_scan":        ("🕵️ Git scan is Starter+",            "Upgrade to scan commit history.",       "starter"),
}

VAULT_SCHEMA_VERSION = 2
ENV_LEVELS = ["all", "dev", "staging", "prod"]
ENV_COLORS = {"all": "#3D5166", "dev": "#059669", "staging": "#F59E0B", "prod": "#F87171"}


def ensure_vault_dir():
    VAULT_DIR.mkdir(mode=0o700, exist_ok=True)
    IMPORT_DIR.mkdir(exist_ok=True)
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
            "Example: alpaca.txt → ALPACA_KEY, ALPACA_SECRET\n",
            encoding="utf-8",
        )

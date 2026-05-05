"""
Pushkey — scoped agent token management.

Agent tokens let CI pipelines and AI agents unlock the vault without
exposing the master password. The vault key is wrapped (key-encrypted)
with each token at creation time; the master password is never stored.

Scopes
------
read   : list_keys, get_key, check_health, list_projects
write  : add_key, rotate_key, assign_key
inject : inject_env
"""
import hashlib
import json
import secrets
from datetime import datetime

import pushkey_shared as _s
from pushkey_crypto import AESGCM, get_or_create_salt

VALID_SCOPES = {"read", "write", "inject"}


# ── Storage helpers ─────────────────────────────────────────────────────────

def _storage_key() -> bytes:
    salt = get_or_create_salt()
    return hashlib.pbkdf2_hmac("sha256", b"pushkey-agent-tokens-v1", salt, 100_000)


def _load_raw() -> list:
    if not _s.AGENT_TOKENS_FILE.exists():
        return []
    try:
        raw = _s.AGENT_TOKENS_FILE.read_bytes()
        key = _storage_key()
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(plaintext).get("tokens", [])
    except Exception:
        return []


def _save_raw(tokens: list) -> None:
    _s.ensure_vault_dir()
    key = _storage_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps({"tokens": tokens}).encode(), None)
    _s.AGENT_TOKENS_FILE.write_bytes(nonce + ct)
    try:
        _s.AGENT_TOKENS_FILE.chmod(0o600)
    except Exception:
        pass


# ── Key wrapping ─────────────────────────────────────────────────────────────

def _wrap(vault_key: bytes, token_value: str) -> str:
    """Wrap vault_key with a per-token random salt. Format: 'v2:<base64(salt(16)+nonce(12)+ct)>'."""
    import base64
    salt = secrets.token_bytes(16)
    wrapping_key = hashlib.pbkdf2_hmac("sha256", token_value.encode(), salt, 100_000)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(wrapping_key).encrypt(nonce, vault_key, None)
    return "v2:" + base64.b64encode(salt + nonce + ct).decode()


def _unwrap(wrapped: str, token_value: str) -> bytes:
    """Unwrap. 'v2:' prefix = random salt; no prefix = legacy static salt."""
    import base64
    if wrapped.startswith("v2:"):
        raw = base64.b64decode(wrapped[3:])
        salt, nonce, ct = raw[:16], raw[16:28], raw[28:]
        wrapping_key = hashlib.pbkdf2_hmac("sha256", token_value.encode(), salt, 100_000)
    else:
        raw = base64.b64decode(wrapped)
        nonce, ct = raw[:12], raw[12:]
        wrapping_key = hashlib.pbkdf2_hmac("sha256", token_value.encode(), b"pk-agent-wrap-v1", 100_000)
    return AESGCM(wrapping_key).decrypt(nonce, ct, None)


# ── Public API ───────────────────────────────────────────────────────────────

def create_token(name: str, scopes: list[str], vault_key: bytes) -> tuple[bool, str, str]:
    """
    Create a scoped agent token.

    Requires the caller to supply the raw vault_key (obtained after unlocking
    the vault with the master password — see pushkey_mcp._get_vault_key).

    Returns (success, token_value_or_error, token_id).
    token_value is shown exactly once and never stored in plaintext.
    """
    from pushkey_tiers import current_tier
    tier = current_tier()
    limit = _s.TIERS.get(tier, {}).get("max_agent_tokens", 0)
    if limit == 0:
        return False, (
            "Agent tokens require Pro or higher. "
            "Upgrade at pushkey.dev/pricing."
        ), ""

    tokens = _load_raw()
    if limit is not None and len(tokens) >= limit:
        return False, (
            f"Agent token limit reached ({limit} on {tier.title()} plan). "
            "Upgrade to Team for 5 tokens or Enterprise for unlimited."
        ), ""

    bad = [s for s in scopes if s not in VALID_SCOPES]
    if bad:
        return False, f"Invalid scopes: {bad}. Valid: {sorted(VALID_SCOPES)}", ""

    token_value = f"pk_agent_{secrets.token_hex(24)}"
    token_hash = hashlib.sha256(token_value.encode()).hexdigest()
    token_id = f"at_{secrets.token_hex(6)}"

    tokens.append({
        "id": token_id,
        "token_hash": token_hash,
        "name": name,
        "scopes": scopes,
        "created": datetime.now().isoformat(),
        "last_used": None,
        "wrapped_vault_key": _wrap(vault_key, token_value),
    })
    _save_raw(tokens)
    return True, token_value, token_id


def list_tokens() -> list[dict]:
    """Return token metadata — no values, no wrapped keys."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "scopes": t["scopes"],
            "created": t["created"],
            "last_used": t["last_used"],
        }
        for t in _load_raw()
    ]


def revoke_token(token_id: str) -> bool:
    """Remove a token by ID. Returns False if not found."""
    tokens = _load_raw()
    updated = [t for t in tokens if t["id"] != token_id]
    if len(updated) == len(tokens):
        return False
    _save_raw(updated)
    return True


def authenticate_token(token_value: str) -> tuple[bytes | None, list[str], str]:
    """
    Validate an agent token and return the vault key.

    Returns (vault_key, scopes, error_msg).
    vault_key is None on failure.
    """
    if not token_value.startswith("pk_agent_"):
        return None, [], "not an agent token"

    token_hash = hashlib.sha256(token_value.encode()).hexdigest()
    tokens = _load_raw()
    for i, t in enumerate(tokens):
        if t.get("token_hash") == token_hash:
            try:
                vault_key = _unwrap(t["wrapped_vault_key"], token_value)
                tokens[i]["last_used"] = datetime.now().isoformat()
                _save_raw(tokens)
                return vault_key, t.get("scopes", ["read"]), ""
            except Exception:
                return None, [], "token authentication failed (key unwrap error)"
    return None, [], "token not found or revoked"

"""
Pushkey — license and tier engine.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

import pushkey_shared as _s
from pushkey_crypto import AESGCM, get_or_create_salt, log_event

_LICENSE_CACHE: dict | None = None
_LICENSE_GRACE_DAYS = 3


def get_machine_fingerprint() -> str:
    import platform
    import uuid
    parts = [platform.node(), platform.machine(), str(uuid.getnode()), platform.system()]
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()


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


def _token_encrypt(data: dict) -> bytes:
    key = _license_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode(), None)
    return nonce + ct


def _token_decrypt(raw: bytes) -> dict:
    key = _license_key()
    nonce, ct = raw[:12], raw[12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, None))


def load_token() -> dict | None:
    if not _s.TOKEN_FILE.exists():
        return None
    try:
        return _token_decrypt(_s.TOKEN_FILE.read_bytes())
    except Exception:
        return None


def save_token(data: dict) -> None:
    _s.ensure_vault_dir()
    _s.TOKEN_FILE.write_bytes(_token_encrypt(data))
    _s.TOKEN_FILE.chmod(0o600)


def _server_post(path: str, payload: dict, timeout: int = 8) -> dict | None:
    try:
        import urllib.request
        url = f"{_s.ACTIVATION_SERVER.rstrip('/')}{path}"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


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
    import platform as _pl
    token = load_token()
    agent_token_count = 0
    try:
        import pushkey_agent_tokens as _at
        agent_token_count = len(_at.list_tokens())
    except Exception:
        pass
    return _server_post("/v1/heartbeat", {
        "license_key":       license_key,
        "fingerprint":       get_machine_fingerprint(),
        "token":             token.get("token", "") if token else "",
        "platform":          f"{_pl.system()} {_pl.release()}",
        "version":           getattr(_s, "VERSION", ""),
        "agent_token_count": agent_token_count,
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
        return
    license_key = lic.get("license_key", "")
    if not license_key:
        return
    token = load_token()
    now = datetime.now()
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
    if token:
        refreshed_at = token.get("refreshed_at")
        if refreshed_at:
            try:
                age = now - datetime.fromisoformat(refreshed_at)
                if age < timedelta(days=_s._TOKEN_GRACE_DAYS):
                    return
            except Exception:
                pass
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
    if _s.TOKEN_FILE.exists():
        _s.TOKEN_FILE.unlink(missing_ok=True)
    global _LICENSE_CACHE
    _LICENSE_CACHE = None
    log_event("device deactivated")
    if ok:
        return True, "Device deactivated. You can now activate on another machine."
    return False, "Server unreachable — local token cleared. Deactivation will sync when server is online."


def load_license() -> dict:
    global _LICENSE_CACHE
    if _LICENSE_CACHE is not None:
        return _LICENSE_CACHE
    if not _s.LICENSE_FILE.exists():
        _LICENSE_CACHE = {"tier": "free"}
        return _LICENSE_CACHE
    try:
        data = _license_decrypt(_s.LICENSE_FILE.read_bytes())
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
    _s.ensure_vault_dir()
    _s.LICENSE_FILE.write_bytes(_license_encrypt(data))
    _LICENSE_CACHE = data


def current_tier() -> str:
    return load_license().get("tier", "free")


def tier_limits() -> dict:
    return _s.TIERS.get(current_tier(), _s.TIERS["free"])


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
                    "ltdp": "pro", "ltdt": "team"}
        tier = tier_map.get(tier_code)
        if not tier:
            return False, f"Unknown tier code: {tier_code}"
        payload_parts = parts[1:-1]
        checksum = parts[-1]
        expected = hashlib.sha256("-".join(payload_parts).encode()).hexdigest()[:8].upper()
        if checksum != expected:
            return False, "License key checksum invalid — check for typos"
        import base64 as _b64
        try:
            raw_payload = _b64.b32decode("".join(payload_parts) + "=" * 4)
            payload = json.loads(raw_payload)
        except Exception:
            payload = {}
        expiry = payload.get("expires")
        seats = payload.get("seats", 1)
        email = payload.get("email", "")
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
        devices_max = srv.get("devices_max")
        slot_msg = f" ({devices_used}/{devices_max} devices)" if devices_max else ""
        return True, f"✅ {_s.TIERS[tier]['emoji']} {_s.TIERS[tier]['label']} license activated!{slot_msg}"
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
    chunks = [b32[i:i+8] for i in range(0, len(b32), 8)]
    payload_str = "-".join(chunks)
    checksum = hashlib.sha256(payload_str.encode()).hexdigest()[:8].upper()
    return f"{code}-{payload_str}-{checksum}"

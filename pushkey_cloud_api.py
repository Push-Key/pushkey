"""
Pushkey Cloud Sync API — self-hostable FastAPI backend (#28)
============================================================
Zero-knowledge: server stores only the encrypted vault blob.
It never sees plaintext keys. Auth is email + password (hashed).

Requirements:
    pip install fastapi uvicorn[standard] passlib[bcrypt] python-jose[cryptography]

Run:
    uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000

Configure Pushkey to use: http://your-server:8000
"""

import hashlib
import html as _html
import json
import os
import secrets
import time
from pathlib import Path

# Load .env if present
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
from pathlib import Path
from datetime import datetime, timedelta, timezone

def _utcnow() -> datetime:
    """Replacement for deprecated datetime.utcnow() — returns naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

try:
    from fastapi import FastAPI, HTTPException, Depends, Request, Header
    from fastapi.responses import JSONResponse, Response
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from fastapi.middleware.cors import CORSMiddleware
    from passlib.context import CryptContext
    from jose import jwt, JWTError
except ImportError:
    raise SystemExit(
        "Missing deps — run:\n  pip install fastapi uvicorn[standard] passlib[bcrypt] python-jose[cryptography]"
    )

# ── Config ──────────────────────────────────────────────────────
DATA_DIR  = Path(os.environ.get("PUSHKEY_DATA_DIR", "~/.pushkey-cloud")).expanduser()
ALGORITHM = "HS256"
TOKEN_TTL = int(os.environ.get("PUSHKEY_TOKEN_TTL_HOURS", "720"))  # 30 days

_DEV_MODE  = os.environ.get("PUSHKEY_ENV", "production").lower() in ("development", "dev", "local")
SECRET_KEY = os.environ.get("PUSHKEY_JWT_SECRET", "")
if not SECRET_KEY:
    if _DEV_MODE:
        SECRET_KEY = secrets.token_hex(32)
        print("[pushkey] WARNING: PUSHKEY_JWT_SECRET not set — ephemeral secret active (dev mode only)")
    else:
        raise SystemExit(
            "\n[pushkey] FATAL: PUSHKEY_JWT_SECRET environment variable is required.\n"
            "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "For local dev only, set PUSHKEY_ENV=development to bypass this check.\n"
        )

DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"
VAULTS_DIR = DATA_DIR / "vaults"
VAULTS_DIR.mkdir(exist_ok=True)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer  = HTTPBearer()
app     = FastAPI(title="Pushkey Cloud Sync", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://www.push-key.com",
        "https://push-key.com",
        os.environ.get("ADMIN_ORIGIN", ""),
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Admin config ─────────────────────────────────────────────────
LICENSES_FILE = DATA_DIR / "licenses.json"
ADMIN_SECRET = os.environ.get("PUSHKEY_ADMIN_SECRET", "")
if not ADMIN_SECRET:
    if _DEV_MODE:
        ADMIN_SECRET = "dev-change-me"
        print("[pushkey] WARNING: PUSHKEY_ADMIN_SECRET not set — using 'dev-change-me' (dev mode only)")
    else:
        raise SystemExit(
            "\n[pushkey] FATAL: PUSHKEY_ADMIN_SECRET environment variable is required.\n"
            "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "For local dev only, set PUSHKEY_ENV=development to bypass this check.\n"
        )
TIER_PREFIXES = {"free": "FREE", "starter": "STRT", "pro": "PRO", "team": "TEAM", "enterprise": "ENT"}


# ── User store (flat JSON, fine for <1000 users) ─────────────────
def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text())

def _save_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2))


# ── JWT helpers ──────────────────────────────────────────────────
def _create_token(email: str) -> str:
    exp = _utcnow() + timedelta(hours=TOKEN_TTL)
    return jwt.encode({"sub": email, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def _decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def _current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    return _decode_token(creds.credentials)


# ── Auth endpoints ───────────────────────────────────────────────
@app.post("/api/v1/auth/register")
async def register(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _rate_check(_AUTH_HITS, ip, AUTH_RATE_MAX, AUTH_RATE_WINDOW_SEC):
        raise HTTPException(429, f"Too many requests — try again in {AUTH_RATE_WINDOW_SEC}s")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    pw    = body.get("password", "")
    if not email or not pw or len(pw) < 8:
        raise HTTPException(400, "email and password (>=8 chars) required")
    users = _load_users()
    if email in users:
        raise HTTPException(409, "email already registered")
    users[email] = {"hash": pwd_ctx.hash(pw), "created": _utcnow().isoformat()}
    _save_users(users)
    return {"token": _create_token(email)}

@app.post("/api/v1/auth/login")
async def login(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _rate_check(_AUTH_HITS, ip, AUTH_RATE_MAX, AUTH_RATE_WINDOW_SEC):
        raise HTTPException(429, f"Too many requests — try again in {AUTH_RATE_WINDOW_SEC}s")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    pw    = body.get("password", "")
    users = _load_users()
    user  = users.get(email)
    if not user or not pwd_ctx.verify(pw, user["hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": _create_token(email)}


# ── Password reset ───────────────────────────────────────────────
RESET_TOKEN_TTL_MIN = 30  # token expires after 30 min

@app.post("/api/v1/auth/request-reset")
async def auth_request_reset(request: Request):
    """Send password reset email with one-time token. Always returns success to prevent enumeration."""
    body  = await request.json()
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")

    users = _load_users()
    if email in users:
        # Generate token, store hash, expiry
        token = secrets.token_urlsafe(32)
        users[email]["reset_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
        users[email]["reset_expires"]    = (_utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MIN)).isoformat()
        _save_users(users)

        # Send email if SMTP configured
        if SMTP_HOST and FROM_EMAIL:
            try:
                import smtplib
                from email.mime.text import MIMEText
                reset_link = f"{APP_URL}/reset?token={token}&email={email}"
                reset_body = f"""
      <h1 style="margin:0 0 12px 0;color:#FFFFFF;font-size:22px;font-weight:700;">Reset your password</h1>
      <p style="margin:0 0 24px 0;color:#7A9BB5;font-size:14px;line-height:1.6;">
        We received a request to reset the password for your Pushkey cloud sync account.<br>
        This link expires in <strong style="color:#C8D8E8;">{RESET_TOKEN_TTL_MIN} minutes</strong>.
      </p>
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:24px;">
        <tr><td align="center">
          <a href="{reset_link}" style="display:inline-block;background:#22D3EE;color:#070B11;font-size:15px;font-weight:700;padding:14px 32px;border-radius:10px;text-decoration:none;letter-spacing:0.2px;">
            &#x1F511; Reset Password
          </a>
        </td></tr>
      </table>
      <div style="background:#070B11;border:1px solid #1A2A38;border-radius:8px;padding:12px 16px;margin-bottom:20px;">
        <p style="margin:0;color:#3D5A73;font-size:11px;font-family:'Courier New',Courier,monospace;word-break:break-all;">{reset_link}</p>
      </div>
      <p style="margin:0;color:#3D5A73;font-size:12px;line-height:1.6;">
        If you didn&rsquo;t request this, you can safely ignore this email &mdash; your password will not change.
      </p>"""
                reset_html = _email_html(
                    title="Reset your Pushkey password",
                    preview=f"Reset link inside — expires in {RESET_TOKEN_TTL_MIN} minutes.",
                    body_html=reset_body,
                )
                reset_plain = f"""Reset your Pushkey password

Click the link below within {RESET_TOKEN_TTL_MIN} minutes:

{reset_link}

If you didn't request this, ignore this email — your password won't change.
"""
                from email.mime.multipart import MIMEMultipart
                m = MIMEMultipart("alternative")
                m["Subject"] = "Reset your Pushkey password"
                m["From"]    = FROM_EMAIL
                m["To"]      = email
                m.attach(MIMEText(reset_plain, "plain"))
                m.attach(MIMEText(reset_html,  "html"))
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                    s.starttls()
                    s.login(SMTP_USER, SMTP_PASS)
                    s.sendmail(FROM_EMAIL, [email], m.as_string())
            except Exception:
                pass

    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@app.post("/api/v1/auth/confirm-reset")
async def auth_confirm_reset(request: Request):
    """Verify reset token and set new password."""
    body     = await request.json()
    email    = body.get("email", "").strip().lower()
    token    = body.get("token", "")
    new_pw   = body.get("password", "")

    if not email or not token or not new_pw:
        raise HTTPException(400, "email, token, and password required")
    if len(new_pw) < 8:
        raise HTTPException(400, "password must be at least 8 chars")

    users = _load_users()
    user  = users.get(email)
    if not user or "reset_token_hash" not in user or "reset_expires" not in user:
        raise HTTPException(401, "Invalid or expired reset token")

    expected_hash = hashlib.sha256(token.encode()).hexdigest()
    if expected_hash != user["reset_token_hash"]:
        raise HTTPException(401, "Invalid or expired reset token")

    if user["reset_expires"] < _utcnow().isoformat():
        raise HTTPException(401, "Reset token expired — request a new one")

    user["hash"] = pwd_ctx.hash(new_pw)
    user.pop("reset_token_hash", None)
    user.pop("reset_expires", None)
    _save_users(users)
    return {"ok": True, "token": _create_token(email)}


# ── Vault blob endpoints (zero-knowledge) ────────────────────────
def _vault_path(email: str) -> Path:
    safe = hashlib.sha256(email.encode()).hexdigest()
    return VAULTS_DIR / f"{safe}.enc"

def _etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]

@app.put("/api/v1/vault")
async def put_vault(request: Request, email: str = Depends(_current_user)):
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty body")
    vpath = _vault_path(email)
    vpath.write_bytes(blob)
    tag = _etag(blob)
    return {"etag": tag, "size": len(blob), "updated": _utcnow().isoformat()}

@app.get("/api/v1/vault")
async def get_vault(
    if_none_match: str = Header(default="", alias="if-none-match"),
    email: str = Depends(_current_user),
):
    vpath = _vault_path(email)
    if not vpath.exists():
        raise HTTPException(404, "No vault stored")
    blob = vpath.read_bytes()
    tag  = _etag(blob)
    if if_none_match and if_none_match == tag:
        return Response(status_code=304)
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"ETag": tag, "Content-Length": str(len(blob))})

@app.get("/api/v1/vault/meta")
async def vault_meta(email: str = Depends(_current_user)):
    vpath = _vault_path(email)
    if not vpath.exists():
        return {"exists": False}
    blob = vpath.read_bytes()
    return {"exists": True, "size": len(blob), "etag": _etag(blob),
            "modified": datetime.fromtimestamp(vpath.stat().st_mtime).isoformat()}

@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "pushkey-cloud"}


# ── Event log (append-only JSONL for analytics) ──────────────────
EVENTS_FILE = DATA_DIR / "events.jsonl"
AUDIT_FILE  = DATA_DIR / "audit.jsonl"

def _log_event(event_type: str, data: dict) -> None:
    entry = {"ts": _utcnow().isoformat(), "type": event_type, **data}
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")

def _load_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text().splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out

def _log_audit(action: str, target: str, details: dict | None = None) -> None:
    """Record admin action for compliance audit trail."""
    entry = {
        "ts":      _utcnow().isoformat(),
        "action":  action,
        "target":  target,
        "details": details or {},
    }
    with AUDIT_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")

def _load_audit() -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text().splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ── Client-facing heartbeat ──────────────────────────────────────
# Simple in-memory token bucket rate limiter
RATE_LIMIT_MAX        = int(os.environ.get("HEARTBEAT_RATE_MAX", "10"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("HEARTBEAT_RATE_WINDOW", "60"))
AUTH_RATE_MAX         = int(os.environ.get("AUTH_RATE_MAX", "5"))
AUTH_RATE_WINDOW_SEC  = int(os.environ.get("AUTH_RATE_WINDOW", "60"))
PORTAL_RATE_MAX       = int(os.environ.get("PORTAL_RATE_MAX", "20"))
PORTAL_RATE_WINDOW_SEC = int(os.environ.get("PORTAL_RATE_WINDOW", "60"))

_HEARTBEAT_HITS: dict[str, list[float]] = {}
_AUTH_HITS:      dict[str, list[float]] = {}
_PORTAL_HITS:    dict[str, list[float]] = {}


def _rate_check(bucket: dict, key: str, max_hits: int, window_sec: int) -> bool:
    """Generic token-bucket check. Returns True if allowed."""
    now = time.time()
    hits = [h for h in bucket.get(key, []) if now - h < window_sec]
    if len(hits) >= max_hits:
        bucket[key] = hits
        return False
    hits.append(now)
    bucket[key] = hits
    if len(bucket) > 10000:
        bucket.clear()
    return True


def _check_rate_limit(key: str) -> bool:
    return _rate_check(_HEARTBEAT_HITS, key, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SEC)


async def _handle_heartbeat(body: dict) -> dict:
    """Shared logic for both /v1/heartbeat and /api/v1/heartbeat."""
    import platform as _pl
    key = body.get("license_key", "").strip().upper()
    if not key:
        raise HTTPException(400, "license_key required")
    if not _check_rate_limit(key):
        raise HTTPException(429, f"Too many heartbeats — limit is {RATE_LIMIT_MAX} per {RATE_LIMIT_WINDOW_SEC}s")

    # Accept platform from body, or auto-detect if missing
    platform = body.get("platform", "") or f"{_pl.system()} {_pl.release()}"
    version  = body.get("version", "")

    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")

    entry = lic[key]
    if entry["status"] == "revoked":
        raise HTTPException(403, "License revoked")

    entry["last_heartbeat"] = _utcnow().isoformat()
    entry["platform"] = platform
    agent_token_count = body.get("agent_token_count", 0)
    if isinstance(agent_token_count, int):
        entry["agent_token_count"] = agent_token_count
    _save_licenses(lic)

    _log_event("heartbeat", {"key": key[:8] + "…", "tier": entry["tier"], "platform": platform, "version": version, "agent_tokens": agent_token_count})

    # Return shape compatible with both old token flow and new admin flow
    return {"ok": True, "status": entry["status"], "tier": entry["tier"], "token": ""}


@app.post("/v1/heartbeat")       # path desktop app calls
@app.post("/api/v1/heartbeat")   # path admin API uses
async def heartbeat(request: Request):
    return await _handle_heartbeat(await request.json())


# ── Admin helpers ────────────────────────────────────────────────
def _load_licenses() -> dict:
    if not LICENSES_FILE.exists():
        return {}
    return json.loads(LICENSES_FILE.read_text())

def _save_licenses(data: dict) -> None:
    LICENSES_FILE.write_text(json.dumps(data, indent=2))

def _require_admin(x_admin_secret: str = Header(default="")):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(403, "Forbidden")

def _gen_key(tier: str) -> str:
    import secrets as _sec, string as _s
    chars = _s.ascii_uppercase + _s.digits
    prefix = TIER_PREFIXES.get(tier, "FREE")
    seg1 = "".join(_sec.choice(chars) for _ in range(8))
    seg2 = "".join(_sec.choice(chars) for _ in range(16))
    seg3 = "".join(_sec.choice(chars) for _ in range(4))
    return f"{prefix}-{seg1}-{seg2}-{seg3}"


SMTP_HOST  = os.environ.get("SMTP_HOST", "")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER", "")
SMTP_PASS  = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)
APP_URL    = os.environ.get("APP_URL", "https://pushkey.app")


def _email_html(title: str, preview: str, body_html: str) -> str:
    """Wrap body_html in a clean, dark-branded email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#0A0F1E;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<!-- preview text -->
<span style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{preview}</span>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0A0F1E;padding:40px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">

      <!-- logo bar -->
      <tr><td style="padding-bottom:28px;text-align:center;">
        <table cellpadding="0" cellspacing="0" border="0" style="display:inline-table;">
          <tr>
            <td style="background:#22D3EE;border-radius:10px;width:36px;height:36px;text-align:center;vertical-align:middle;">
              <!-- key icon -->
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:8px auto;">
                <circle cx="8" cy="15" r="4" stroke="#0A0F1E" stroke-width="2"/>
                <path d="M12 15h9M18 15v-3" stroke="#0A0F1E" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </td>
            <td style="padding-left:10px;vertical-align:middle;">
              <span style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:-0.3px;">Pushkey</span>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- card -->
      <tr><td style="background:#0D1620;border:1px solid #1A2A38;border-radius:16px;padding:36px 40px;">
        {body_html}
      </td></tr>

      <!-- footer -->
      <tr><td style="padding-top:24px;text-align:center;">
        <p style="margin:0;color:#3D5A73;font-size:12px;line-height:1.6;">
          You received this because a Pushkey license was issued to this address.<br>
          Questions? Reply to this email — we read every one.<br>
          <a href="{APP_URL}" style="color:#22D3EE;text-decoration:none;">{APP_URL}</a>
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def _send_email_html(to: str, subject: str, html: str, plain: str) -> dict:
    if not SMTP_HOST:
        return {"sent": False, "reason": "smtp_not_configured"}
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to], msg.as_string())
        return {"sent": True}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}


def _send_invite_email(to_email: str, name: str, tier: str, key: str, expires_at: str | None) -> dict:
    import base64

    # High-quality brand SVGs encoded as data URIs — vector, crisp at any size
    def _b64svg(svg: str) -> str:
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

    WIN_LOGO = _b64svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 88 88">'
        '<path fill="#f25022" d="M0 0h42v42H0z"/>'
        '<path fill="#7fba00" d="M46 0h42v42H46z"/>'
        '<path fill="#00a4ef" d="M0 46h42v42H0z"/>'
        '<path fill="#ffb900" d="M46 46h42v42H46z"/>'
        '</svg>'
    )
    APPLE_LOGO = _b64svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 814 1000">'
        '<path fill="#22D3EE" d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 790.7 0 663 0 541.8c0-207.5 135.4-317.3 269-317.3 70.1 0 128.4 46.4 172.5 46.4 42.8 0 109.6-49 192.5-49 31 0 133.9 2.6 198.3 99zm-234-181.5c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/>'
        '</svg>'
    )
    LINUX_LOGO = _b64svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
        '<path fill="#22D3EE" d="M24 4C15.2 4 9 11.4 9 20c0 4.2 1.5 8 4 10.8-.5.8-.9 1.7-1.3 2.5-.9 1.9-1.5 3.8-.8 5 .5.9 1.6 1.2 2.7 1.2 1.3 0 2.7-.4 3.9-.7 1-.3 1.9-.5 2.5-.5.6 0 1.4.2 2.3.5 1.3.4 2.7.7 3.9.7 1.1 0 2.2-.3 2.7-1.2.7-1.2.1-3.1-.8-5-.4-.8-.8-1.7-1.3-2.5C30.5 28 32 24.2 32 20c0-8.6-3.5-16-8-16zm0 3c3.3 0 6 5.4 6 13s-2.7 13-6 13-6-5.4-6-13 2.7-13 6-13z"/>'
        '<circle fill="#0A1020" cx="20" cy="20" r="2"/>'
        '<circle fill="#0A1020" cx="28" cy="20" r="2"/>'
        '<path fill="#22D3EE" d="M21 25c0 1.1 1.3 2 3 2s3-.9 3-2"/>'
        '</svg>'
    )

    display_name = name or to_email.split("@")[0]
    first_name   = display_name.split()[0] if display_name else display_name
    tier_label   = tier.capitalize()
    expiry_plain = f"\nExpires: {expires_at[:10]}" if expires_at else ""

    TIER_COLOR   = {"free": "#7A9BB5", "starter": "#22D3EE", "pro": "#7C3AED", "team": "#00DC82", "enterprise": "#F59E0B"}
    TIER_EMOJI   = {"free": "🔓", "starter": "⚡", "pro": "🚀", "team": "👥", "enterprise": "🏢"}
    TIER_BULLETS = {
        "free":       ["Secure local vault", "Up to 10 keys", "CLI access"],
        "starter":    ["Secure local vault", "Unlimited keys", "CLI + GUI access", "Key health monitoring"],
        "pro":        ["Everything in Starter", "Cloud sync (1 device)", "API auto-rotation", "Key injection into .env files"],
        "team":       ["Everything in Pro", "Up to 5 devices", "Team vault sharing", "Audit log + timeline"],
        "enterprise": ["Everything in Team", "Unlimited devices", "SSO + SAML", "Priority support"],
    }
    tier_color   = TIER_COLOR.get(tier, "#22D3EE")
    tier_emoji   = TIER_EMOJI.get(tier, "🔑")
    bullets      = TIER_BULLETS.get(tier, TIER_BULLETS["starter"])

    def _svg_img(svg_body: str, w: int = 18, h: int = 18) -> str:
        """Encode an SVG as a data-URI <img> so Gmail renders it."""
        svg = f'<svg width="{w}" height="{h}" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">{svg_body}</svg>'
        b64 = base64.b64encode(svg.encode()).decode()
        return f'<img src="data:image/svg+xml;base64,{b64}" width="{w}" height="{h}" alt="" style="display:block;vertical-align:middle;">'

    # Lucide-style SVG paths
    ico_download = _svg_img('<path d="M12 3v13M7 11l5 5 5-5" stroke="#22D3EE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 21h18" stroke="#22D3EE" stroke-width="2" stroke-linecap="round"/>')
    ico_settings = _svg_img('<circle cx="12" cy="12" r="3" stroke="#22D3EE" stroke-width="2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" stroke="#22D3EE" stroke-width="2"/>')
    ico_key      = _svg_img('<circle cx="8" cy="15" r="4" stroke="#22D3EE" stroke-width="2"/><path d="M12 15h9M18 15v-3" stroke="#22D3EE" stroke-width="2" stroke-linecap="round"/>')
    ico_check    = _svg_img('<path d="M20 6L9 17l-5-5" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'.replace("{c}", tier_color), 16, 16)
    ico_clock    = _svg_img('<circle cx="12" cy="12" r="9" stroke="#F59E0B" stroke-width="2"/><path d="M12 7v5l3 3" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/>', 14, 14)

    expiry_row = f"""
        <tr><td style="padding-top:10px;border-top:1px solid #1A2A38;">
          <table cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td style="vertical-align:middle;padding-right:6px;">{ico_clock}</td>
              <td style="vertical-align:middle;"><span style="color:#F59E0B;font-size:12px;font-weight:600;">Trial expires {expires_at[:10]} &mdash; activate before then</span></td>
            </tr>
          </table>
        </td></tr>""" if expires_at else ""

    bullets_html = ""
    for b in bullets:
        bullets_html += f"""
          <tr><td style="padding-bottom:8px;">
            <table cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="vertical-align:middle;padding-right:8px;padding-top:1px;">{ico_check}</td>
                <td style="vertical-align:middle;"><span style="color:#C8D8E8;font-size:13px;">{b}</span></td>
              </tr>
            </table>
          </td></tr>"""

    body = f"""
      <!-- greeting -->
      <p style="margin:0 0 4px 0;color:#7A9BB5;font-size:14px;">Hey {first_name} 👋</p>
      <h1 style="margin:0 0 6px 0;color:#FFFFFF;font-size:24px;font-weight:800;line-height:1.2;">Your {tier_emoji} Pushkey {tier_label} license is ready</h1>
      <p style="margin:0 0 28px 0;color:#7A9BB5;font-size:14px;line-height:1.6;">
        Welcome to Pushkey — your secrets are now under your control.<br>Follow the 3 steps below to get set up in under 2 minutes.
      </p>

      <!-- key card -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#070B11;border:2px solid {tier_color}44;border-radius:14px;margin-bottom:28px;">
        <tr><td style="padding:20px 24px;">

          <!-- tier badge -->
          <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;">
            <tr>
              <td style="background:{tier_color}18;border:1px solid {tier_color}44;border-radius:20px;padding:4px 12px;">
                <span style="color:{tier_color};font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;">{tier_emoji} {tier_label} Plan</span>
              </td>
            </tr>
          </table>

          <!-- key label -->
          <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:8px;">
            <tr>
              <td style="vertical-align:middle;padding-right:6px;">{ico_key}</td>
              <td style="vertical-align:middle;"><span style="color:#7A9BB5;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;">Your License Key</span></td>
            </tr>
          </table>

          <!-- key value -->
          <div style="background:#0A1020;border:1px solid #1E3040;border-radius:8px;padding:12px 16px;margin-bottom:4px;">
            <code style="color:#22D3EE;font-size:16px;font-family:'Courier New',Courier,monospace;letter-spacing:1.5px;word-break:break-all;font-weight:700;">{key}</code>
          </div>
          <p style="margin:6px 0 0 0;color:#3D5A73;font-size:11px;">&#128274; Keep this key private — do not share it publicly</p>

          {expiry_row}
        </td></tr>
      </table>

      <!-- what you get -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#0A1020;border:1px solid #1A2A38;border-radius:12px;margin-bottom:28px;">
        <tr><td style="padding:16px 20px 8px 20px;">
          <p style="margin:0 0 12px 0;color:#C8D8E8;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;">&#10024; What&rsquo;s included in your {tier_label} plan</p>
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            {bullets_html}
          </table>
        </td></tr>
      </table>

      <!-- steps header -->
      <p style="margin:0 0 16px 0;color:#C8D8E8;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;">&#128640; Get started in 3 steps</p>

      <!-- step 1 -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#070B11;border:1px solid #1A2A38;border-radius:10px;margin-bottom:8px;">
        <tr><td style="padding:16px 20px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="width:36px;vertical-align:top;padding-top:2px;">
                <div style="width:28px;height:28px;background:#22D3EE18;border:1px solid #22D3EE44;border-radius:50%;text-align:center;line-height:28px;color:#22D3EE;font-size:13px;font-weight:800;">1</div>
              </td>
              <td style="padding-left:12px;vertical-align:top;">
                <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:4px;">
                  <tr>
                    <td style="vertical-align:middle;padding-right:6px;">{ico_download}</td>
                    <td style="vertical-align:middle;"><span style="color:#FFFFFF;font-size:14px;font-weight:700;">Download &amp; install Pushkey</span></td>
                  </tr>
                </table>
                <p style="margin:0 0 10px 0;color:#7A9BB5;font-size:13px;line-height:1.5;">Choose your platform and run the installer, then launch Pushkey.</p>
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding-right:8px;">
                      <a href="{APP_URL}/download?os=windows" style="display:inline-block;background:#22D3EE;color:#070B11;font-size:12px;font-weight:700;padding:8px 16px;border-radius:8px;text-decoration:none;vertical-align:middle;">
                        <img src="{WIN_LOGO}" width="16" height="16" alt="" style="display:inline-block;vertical-align:middle;margin-right:6px;">Windows
                      </a>
                    </td>
                    <td style="padding-right:8px;">
                      <a href="{APP_URL}/download?os=mac" style="display:inline-block;background:#1A2A38;border:1px solid #22D3EE55;color:#22D3EE;font-size:12px;font-weight:700;padding:8px 16px;border-radius:8px;text-decoration:none;vertical-align:middle;">
                        <img src="{APPLE_LOGO}" width="14" height="16" alt="" style="display:inline-block;vertical-align:middle;margin-right:6px;">macOS
                      </a>
                    </td>
                    <td>
                      <a href="{APP_URL}/download?os=linux" style="display:inline-block;background:#1A2A38;border:1px solid #22D3EE55;color:#22D3EE;font-size:12px;font-weight:700;padding:8px 16px;border-radius:8px;text-decoration:none;vertical-align:middle;">
                        <img src="{LINUX_LOGO}" width="16" height="16" alt="" style="display:inline-block;vertical-align:middle;margin-right:6px;">Linux
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>

      <!-- step 2 -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#070B11;border:1px solid #1A2A38;border-radius:10px;margin-bottom:8px;">
        <tr><td style="padding:16px 20px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="width:36px;vertical-align:top;padding-top:2px;">
                <div style="width:28px;height:28px;background:#22D3EE18;border:1px solid #22D3EE44;border-radius:50%;text-align:center;line-height:28px;color:#22D3EE;font-size:13px;font-weight:800;">2</div>
              </td>
              <td style="padding-left:12px;vertical-align:top;">
                <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:4px;">
                  <tr>
                    <td style="vertical-align:middle;padding-right:6px;">{ico_settings}</td>
                    <td style="vertical-align:middle;"><span style="color:#FFFFFF;font-size:14px;font-weight:700;">Open Settings &rarr; License</span></td>
                  </tr>
                </table>
                <p style="margin:0;color:#7A9BB5;font-size:13px;line-height:1.5;">Once Pushkey is open, click the <strong style="color:#C8D8E8;">gear icon ⚙️</strong> in the left sidebar to open Settings, then click the <strong style="color:#C8D8E8;">License</strong> tab.</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>

      <!-- step 3 -->
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#070B11;border:1px solid #1A2A38;border-radius:10px;margin-bottom:28px;">
        <tr><td style="padding:16px 20px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="width:36px;vertical-align:top;padding-top:2px;">
                <div style="width:28px;height:28px;background:#22D3EE18;border:1px solid #22D3EE44;border-radius:50%;text-align:center;line-height:28px;color:#22D3EE;font-size:13px;font-weight:800;">3</div>
              </td>
              <td style="padding-left:12px;vertical-align:top;">
                <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:4px;">
                  <tr>
                    <td style="vertical-align:middle;padding-right:6px;">{ico_key}</td>
                    <td style="vertical-align:middle;"><span style="color:#FFFFFF;font-size:14px;font-weight:700;">Paste your key &amp; activate</span></td>
                  </tr>
                </table>
                <p style="margin:0 0 8px 0;color:#7A9BB5;font-size:13px;line-height:1.5;">Copy your license key from above, paste it into the license field, and click <strong style="color:#C8D8E8;">Activate</strong>. That&rsquo;s it &mdash; you&rsquo;re in. 🎉</p>
                <div style="background:#0A1020;border:1px solid #1E3040;border-radius:6px;padding:8px 12px;display:inline-block;">
                  <code style="color:#22D3EE;font-size:13px;font-family:'Courier New',Courier,monospace;letter-spacing:1px;">{key}</code>
                </div>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>

      <!-- divider -->
      <div style="height:1px;background:#1A2A38;margin-bottom:20px;"></div>

      <!-- support -->
      <p style="margin:0;color:#7A9BB5;font-size:13px;line-height:1.7;">
        &#128172; <strong style="color:#C8D8E8;">Need help?</strong> Just reply to this email &mdash; we respond within 24 hours.<br>
        &#127760; Docs &amp; guides at <a href="{APP_URL}" style="color:#22D3EE;text-decoration:none;">{APP_URL}</a>
      </p>"""

    html = _email_html(
        title=f"Your Pushkey {tier_label} License",
        preview=f"{tier_emoji} Your {tier_label} license key is inside — get set up in 3 steps.",
        body_html=body,
    )

    plain = f"""Hey {first_name},

Your {tier_emoji} Pushkey {tier_label} license is ready.

LICENSE KEY
-----------
{key}{expiry_plain}

Keep this key private — do not share it publicly.

WHAT'S INCLUDED ({tier_label.upper()})
{chr(10).join("  • " + b for b in bullets)}

GET STARTED IN 3 STEPS
-----------------------
1. Download Pushkey for your platform
   Windows : {APP_URL}/download?os=windows
   macOS   : {APP_URL}/download?os=mac
   Linux   : {APP_URL}/download?os=linux
   Run the installer and launch the app.

2. Open Settings → License
   Click the gear icon ⚙ in the sidebar, then the License tab.

3. Paste your key and click Activate
   Copy the key above, paste it in, hit Activate. Done! 🎉

Need help? Reply to this email — we respond within 24 hours.
Docs & guides: {APP_URL}

— The Pushkey Team
"""

    return _send_email_html(to_email, f"{tier_emoji} Your Pushkey {tier_label} license key is ready", html, plain)


def _auto_expire(lic: dict) -> bool:
    """Set status=expired for any record past its expires_at. Returns True if any changed."""
    now = _utcnow().isoformat()
    changed = False
    for entry in lic.values():
        if (
            entry.get("expires_at")
            and entry["status"] == "active"
            and entry["expires_at"] < now
        ):
            entry["status"] = "expired"
            entry["stage"]  = "churned"
            changed = True
    return changed


# ── Admin endpoints ──────────────────────────────────────────────
@app.get("/api/admin/stats")
async def admin_stats(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    now = _utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week  = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).isoformat()
    yesterday = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).isoformat()
    active     = [v for v in lic.values() if v["status"] == "active"]
    new_today  = sum(1 for v in lic.values() if v.get("activated", "") >= today)
    yesterday_new = sum(1 for v in lic.values() if yesterday <= v.get("activated", "") < today)
    return {
        "total":              len(lic),
        "total_active":       len(active),
        "new_today":          new_today,
        "pro_team":           sum(1 for v in active if v["tier"] in ("pro", "team")),
        "revoked":            sum(1 for v in lic.values() if v["status"] == "revoked"),
        "week_delta":         sum(1 for v in lic.values() if v.get("activated", "") >= week),
        "today_delta":        new_today - yesterday_new,
        "mcp_users":          sum(1 for v in lic.values() if v.get("agent_token_count", 0) > 0),
        "total_agent_tokens": sum(v.get("agent_token_count", 0) for v in lic.values()),
    }


@app.get("/api/admin/licenses")
async def admin_list_licenses(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    if _auto_expire(lic):
        _save_licenses(lic)
    return list(lic.values())


@app.post("/api/admin/licenses/generate")
async def admin_generate(request: Request, _: None = Depends(_require_admin)):
    body = await request.json()
    tier = body.get("tier", "free").lower()
    if tier not in TIER_PREFIXES:
        raise HTTPException(400, f"tier must be one of: {list(TIER_PREFIXES)}")
    lic = _load_licenses()
    key = _gen_key(tier)
    while key in lic:
        key = _gen_key(tier)
    entry = {
        "key":            key,
        "tier":           tier,
        "email":          body.get("email", ""),
        "platform":       body.get("platform", ""),
        "activated":      _utcnow().isoformat(),
        "last_heartbeat": None,
        "status":         "active",
        "notes":          body.get("notes", ""),
    }
    lic[key] = entry
    _save_licenses(lic)
    _log_event("activated", {"key": key[:8] + "…", "tier": tier, "email": entry["email"]})
    _log_audit("generate_license", key, {"tier": tier, "email": entry["email"]})
    return entry


VALID_SOURCES = {"Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"}
VALID_TRIAL_DAYS = {7, 14, 30}


@app.post("/api/admin/licenses/issue")
async def admin_issue(request: Request, _: None = Depends(_require_admin)):
    body       = await request.json()
    tier       = body.get("tier", "free").lower()
    email      = body.get("email", "").strip().lower()
    name       = body.get("name", "").strip()
    company    = body.get("company", "").strip()
    source     = body.get("source", "Direct").strip()
    trial_days = body.get("trial_days")  # int or null
    follow_up  = body.get("follow_up_date", "")
    notes      = body.get("notes", "").strip()
    send_email = bool(body.get("send_email", False))

    if tier not in TIER_PREFIXES:
        raise HTTPException(400, f"tier must be one of: {list(TIER_PREFIXES)}")
    if not email:
        raise HTTPException(400, "email is required")
    if source not in VALID_SOURCES:
        source = "Other"
    if trial_days is not None and trial_days not in VALID_TRIAL_DAYS:
        raise HTTPException(400, f"trial_days must be one of: {list(VALID_TRIAL_DAYS)} or null")

    expires_at = None
    if trial_days is not None:
        expires_at = (_utcnow() + timedelta(days=trial_days)).isoformat()

    lic = _load_licenses()
    key = _gen_key(tier)
    while key in lic:
        key = _gen_key(tier)

    entry = {
        "key":            key,
        "tier":           tier,
        "email":          email,
        "name":           name,
        "company":        company,
        "source":         source,
        "platform":       "",
        "activated":      _utcnow().isoformat(),
        "last_heartbeat": None,
        "status":         "active",
        "notes":          notes,
        "expires_at":     expires_at,
        "follow_up_date": follow_up,
        "stage":          "trial" if trial_days else "active",
        "sent_invite":    False,
    }

    email_result = {"sent": False, "reason": "not_requested"}
    if send_email:
        email_result = _send_invite_email(email, name, tier, key, expires_at)
        entry["sent_invite"] = email_result.get("sent", False)

    lic[key] = entry
    _save_licenses(lic)
    _log_event("issued", {"key": key[:8] + "…", "tier": tier, "email": email})
    _log_audit("issue_license", key, {
        "tier": tier, "email": email, "trial_days": trial_days,
        "send_email": send_email, "email_sent": email_result.get("sent", False),
    })
    return {**entry, "email_result": email_result}


@app.get("/api/admin/contacts")
async def admin_contacts(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    if _auto_expire(lic):
        _save_licenses(lic)

    by_email: dict[str, dict] = {}
    for entry in lic.values():
        email = entry.get("email", "").lower()
        if not email:
            continue
        if email not in by_email:
            by_email[email] = {
                "email":           email,
                "name":            entry.get("name", ""),
                "company":         entry.get("company", ""),
                "source":          entry.get("source", ""),
                "follow_up_date":  entry.get("follow_up_date", ""),
                "stage":           entry.get("stage", ""),
                "notes":           entry.get("notes", ""),
                "keys":            [],
                "latest_activity": "",
            }
        contact = by_email[email]
        for field in ("name", "company", "source", "notes"):
            if entry.get(field) and not contact[field]:
                contact[field] = entry[field]
        if entry.get("follow_up_date") and not contact["follow_up_date"]:
            contact["follow_up_date"] = entry["follow_up_date"]
        if entry.get("stage") == "converted":
            contact["stage"] = "converted"
        elif not contact["stage"] and entry.get("stage"):
            contact["stage"] = entry["stage"]

        contact["keys"].append({
            "key":        entry["key"],
            "tier":       entry["tier"],
            "status":     entry["status"],
            "expires_at": entry.get("expires_at"),
            "activated":  entry.get("activated", ""),
        })
        act = entry.get("last_heartbeat") or entry.get("activated", "")
        if act and act > contact["latest_activity"]:
            contact["latest_activity"] = act

    today = _utcnow().date().isoformat()
    contacts_list = list(by_email.values())
    # Sort by latest_activity descending first (most recent on top within a group)
    contacts_list.sort(key=lambda c: c["latest_activity"], reverse=True)
    # Then stable-sort by overdue flag ascending (overdue=0 floats to top)
    contacts_list.sort(key=lambda c: 0 if (c["follow_up_date"] and c["follow_up_date"] <= today) else 1)
    return contacts_list


@app.patch("/api/admin/contacts/{email}")
async def admin_update_contact(
    email: str, request: Request, _: None = Depends(_require_admin)
):
    email = email.lower()
    body  = await request.json()
    lic   = _load_licenses()
    matched = [v for v in lic.values() if v.get("email", "").lower() == email]
    if not matched:
        raise HTTPException(404, "Contact not found")
    allowed = {"name", "company", "follow_up_date", "stage", "notes", "source"}
    changes = {k: v for k, v in body.items() if k in allowed}
    for entry in matched:
        for field in allowed:
            if field in body:
                entry[field] = body[field]
    _save_licenses(lic)
    _log_audit("update_contact", email, {"fields": list(changes.keys()), "updated": len(matched)})
    return {"ok": True, "updated": len(matched)}


@app.post("/api/admin/licenses/{key}/send-invite")
async def admin_send_invite(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    entry  = lic[key]
    result = _send_invite_email(
        entry["email"], entry.get("name", ""), entry["tier"],
        key, entry.get("expires_at")
    )
    if result.get("sent"):
        entry["sent_invite"] = True
        _save_licenses(lic)
    _log_audit("send_invite", key, {"email": entry["email"], "sent": result.get("sent", False)})
    return result


@app.post("/api/admin/licenses/{key}/expire")
async def admin_expire(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "expired"
    _save_licenses(lic)
    _log_event("expired", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("expire_license", key, {"tier": lic[key]["tier"]})
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/revoke")
async def admin_revoke(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "revoked"
    lic[key]["last_heartbeat"] = None
    _save_licenses(lic)
    _log_event("revoked", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("revoke_license", key, {"tier": lic[key]["tier"]})
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/renew")
async def admin_renew(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "active"
    _save_licenses(lic)
    _log_event("renewed", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("renew_license", key, {"tier": lic[key]["tier"]})
    return {"ok": True}


@app.get("/api/admin/analytics")
async def admin_analytics(_: None = Depends(_require_admin)):
    """
    Returns 30-day time-series data for the analytics dashboard:
    - daily_activations: [{date, count}] for last 30 days
    - daily_heartbeats:  [{date, count}] for last 30 days
    - event_totals: counts by event type
    - tier_history: activations by tier for last 30 days
    """
    events = _load_events()
    now = _utcnow()

    # Build 30-day date buckets
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    act_counts:  dict[str, int] = {d: 0 for d in days}
    hb_counts:   dict[str, int] = {d: 0 for d in days}
    tier_counts: dict[str, dict[str, int]] = {d: {} for d in days}
    totals: dict[str, int] = {}

    cutoff = (now - timedelta(days=30)).isoformat()
    for ev in events:
        ts = ev.get("ts", "")
        if ts < cutoff:
            continue
        date = ts[:10]
        etype = ev.get("type", "")
        totals[etype] = totals.get(etype, 0) + 1
        if date in act_counts:
            if etype == "activated":
                act_counts[date] += 1
                tier = ev.get("tier", "unknown")
                tier_counts[date][tier] = tier_counts[date].get(tier, 0) + 1
            elif etype == "heartbeat":
                hb_counts[date] += 1

    return {
        "daily_activations": [{"date": d, "count": act_counts[d]} for d in days],
        "daily_heartbeats":  [{"date": d, "count": hb_counts[d]}  for d in days],
        "tier_history":      [{"date": d, "tiers": tier_counts[d]} for d in days],
        "event_totals":      totals,
    }


@app.get("/api/admin/export")
async def admin_export(
    request: Request,
    tier:   str = "",
    status: str = "",
    search: str = "",
    _: None = Depends(_require_admin),
):
    """Export licenses CSV with optional filters: ?tier=&status=&search="""
    import csv, io
    lic_values = list(_load_licenses().values())

    if tier:
        t = tier.lower()
        if t == "ent": t = "enterprise"
        lic_values = [v for v in lic_values if v.get("tier") == t]
    if status:
        lic_values = [v for v in lic_values if v.get("status") == status.lower()]
    if search:
        q = search.lower()
        lic_values = [v for v in lic_values if any(
            q in str(v.get(f, "")).lower()
            for f in ("key", "email", "name", "company", "platform", "tier", "status")
        )]

    out = io.StringIO()
    fields = [
        "key", "tier", "email", "name", "company", "platform",
        "activated", "expires_at", "last_heartbeat", "status",
        "stage", "source", "follow_up_date", "notes",
    ]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(lic_values)

    suffix = "all" if not (tier or status or search) else "filtered"
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=licenses-{suffix}.csv"},
    )


@app.get("/api/admin/backup")
async def admin_backup(_: None = Depends(_require_admin)):
    """Returns tar.gz of all data files (licenses, tickets, audit log, events, users — NOT vault blobs)."""
    import tarfile, io
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname in ("licenses.json", "tickets.json", "audit.jsonl", "events.jsonl", "users.json"):
            fpath = DATA_DIR / fname
            if fpath.exists():
                tar.add(fpath, arcname=fname)
    buf.seek(0)
    _log_audit("backup", "data_dir", {"size_bytes": len(buf.getvalue())})
    timestamp = _utcnow().strftime("%Y-%m-%d-%H%M%S")
    return Response(
        content=buf.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename=pushkey-backup-{timestamp}.tar.gz"},
    )


# ── Support tickets ──────────────────────────────────────────────
TICKETS_FILE = DATA_DIR / "tickets.json"

def _load_tickets() -> list[dict]:
    if not TICKETS_FILE.exists():
        return []
    return json.loads(TICKETS_FILE.read_text())

def _save_tickets(tickets: list[dict]) -> None:
    TICKETS_FILE.write_text(json.dumps(tickets, indent=2))


@app.post("/api/admin/tickets")
async def admin_create_ticket(request: Request, _: None = Depends(_require_admin)):
    body  = await request.json()
    email = body.get("email", "").strip().lower()
    subj  = body.get("subject", "").strip()
    msg   = body.get("message", "").strip()
    pri   = body.get("priority", "medium")
    if not subj or not msg:
        raise HTTPException(400, "subject and message required")
    if pri not in {"low", "medium", "high"}:
        pri = "medium"

    tickets = _load_tickets()
    ticket = {
        "id":         secrets.token_hex(8),
        "email":      email,
        "subject":    subj,
        "message":    msg,
        "priority":   pri,
        "status":     "open",
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
        "replies":    [],
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    _log_audit("create_ticket", ticket["id"], {"email": email, "subject": subj, "priority": pri})

    # Notify admin via email if SMTP configured
    if SMTP_HOST and FROM_EMAIL:
        try:
            import smtplib
            from email.mime.text import MIMEText  # noqa (used by MIMEMultipart attach below)
            PRI_COLOR = {"low": "#22D3EE", "medium": "#F59E0B", "high": "#EF4444"}
            pri_color = PRI_COLOR.get(pri, "#22D3EE")
            safe_email = _html.escape(email)
            safe_subj  = _html.escape(subj)
            safe_msg   = _html.escape(msg)
            ticket_body = f"""
      <h1 style="margin:0 0 20px 0;color:#FFFFFF;font-size:20px;font-weight:700;">New Support Ticket</h1>
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#070B11;border:1px solid #1A2A38;border-radius:12px;margin-bottom:24px;">
        <tr><td style="padding:20px 24px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="padding-bottom:12px;border-bottom:1px solid #1A2A38;">
                <span style="display:inline-block;background:{pri_color}22;border:1px solid {pri_color}55;border-radius:6px;padding:3px 10px;color:{pri_color};font-size:11px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">{pri} priority</span>
              </td>
            </tr>
            <tr><td style="padding-top:14px;padding-bottom:6px;">
              <p style="margin:0;color:#7A9BB5;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">From</p>
              <p style="margin:4px 0 0 0;color:#C8D8E8;font-size:14px;">{safe_email}</p>
            </td></tr>
            <tr><td style="padding-bottom:6px;">
              <p style="margin:0;color:#7A9BB5;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Subject</p>
              <p style="margin:4px 0 0 0;color:#C8D8E8;font-size:14px;font-weight:600;">{safe_subj}</p>
            </td></tr>
            <tr><td style="padding-bottom:4px;">
              <p style="margin:0;color:#7A9BB5;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Message</p>
              <p style="margin:4px 0 0 0;color:#C8D8E8;font-size:14px;line-height:1.6;white-space:pre-wrap;">{safe_msg}</p>
            </td></tr>
          </table>
        </td></tr>
      </table>
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr><td align="center">
          <a href="{APP_URL}/admin/support" style="display:inline-block;background:#22D3EE;color:#070B11;font-size:14px;font-weight:700;padding:12px 28px;border-radius:10px;text-decoration:none;">
            View in Admin
          </a>
        </td></tr>
      </table>"""
            ticket_html = _email_html(
                title=f"[Support] {safe_subj}",
                preview=f"New {pri} priority ticket from {safe_email}: {safe_subj}",
                body_html=ticket_body,
            )
            ticket_plain = f"New Pushkey support ticket:\n\nFrom: {email}\nSubject: {subj}\nPriority: {pri}\n\n{msg}\n\nView in admin: {APP_URL}/admin/support"
            from email.mime.multipart import MIMEMultipart
            m = MIMEMultipart("alternative")
            m["Subject"] = f"[Pushkey Support — {pri.upper()}] {subj}"
            m["From"]    = FROM_EMAIL
            m["To"]      = FROM_EMAIL
            m.attach(MIMEText(ticket_plain, "plain"))
            m.attach(MIMEText(ticket_html,  "html"))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(FROM_EMAIL, [FROM_EMAIL], m.as_string())
        except Exception:
            pass  # email failure shouldn't break ticket creation

    return ticket


@app.get("/api/admin/tickets")
async def admin_list_tickets(_: None = Depends(_require_admin)):
    return list(reversed(_load_tickets()))


@app.patch("/api/admin/tickets/{ticket_id}")
async def admin_update_ticket(ticket_id: str, request: Request, _: None = Depends(_require_admin)):
    body    = await request.json()
    tickets = _load_tickets()
    target  = next((t for t in tickets if t["id"] == ticket_id), None)
    if not target:
        raise HTTPException(404, "Ticket not found")

    if "status" in body and body["status"] in {"open", "pending", "resolved"}:
        target["status"] = body["status"]
    if "reply" in body and body["reply"].strip():
        target["replies"].append({
            "ts":   _utcnow().isoformat(),
            "body": body["reply"].strip(),
        })
    target["updated_at"] = _utcnow().isoformat()
    _save_tickets(tickets)
    _log_audit("update_ticket", ticket_id, {"status": target["status"], "had_reply": "reply" in body})
    return target


# ── Customer self-serve portal ───────────────────────────────────
@app.post("/api/v1/portal/lookup")
async def portal_lookup(request: Request):
    """
    Customer enters their license key to view info.
    Returns sanitized license info — never exposes other customers' data.
    """
    ip = request.client.host if request.client else "unknown"
    if not _rate_check(_PORTAL_HITS, ip, PORTAL_RATE_MAX, PORTAL_RATE_WINDOW_SEC):
        raise HTTPException(429, f"Too many requests — try again in {PORTAL_RATE_WINDOW_SEC}s")
    body = await request.json()
    key = body.get("license_key", "").strip().upper()
    if not key:
        raise HTTPException(400, "license_key required")

    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")

    entry = lic[key]
    # Auto-expire if past expiry
    if (entry.get("expires_at")
            and entry["status"] == "active"
            and entry["expires_at"] < _utcnow().isoformat()):
        entry["status"] = "expired"
        _save_licenses(lic)

    return {
        "key":            entry["key"],
        "tier":           entry["tier"],
        "status":         entry["status"],
        "email":          entry.get("email", ""),
        "name":           entry.get("name", ""),
        "activated":      entry.get("activated", ""),
        "expires_at":     entry.get("expires_at"),
        "last_heartbeat": entry.get("last_heartbeat"),
        "platform":       entry.get("platform", ""),
        "stage":          entry.get("stage", ""),
    }


@app.post("/api/v1/portal/request-renewal")
async def portal_request_renewal(request: Request):
    """Customer requests renewal — opens a support ticket internally."""
    body = await request.json()
    key      = body.get("license_key", "").strip().upper()
    message  = body.get("message", "").strip()

    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    entry = lic[key]
    email = entry.get("email", "")

    tickets = _load_tickets()
    ticket = {
        "id":         secrets.token_hex(8),
        "email":      email,
        "subject":    f"Renewal request — {entry['tier'].upper()} key",
        "message":    message or f"Customer requested renewal for {key[:12]}…",
        "priority":   "medium",
        "status":     "open",
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
        "replies":    [],
        "type":       "renewal_request",
        "license_key": key,
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    _log_audit("portal_renewal_request", key, {"email": email})
    return {"ok": True, "ticket_id": ticket["id"]}


# ── Audit log endpoint ───────────────────────────────────────────
@app.get("/api/admin/audit")
async def admin_audit_log(_: None = Depends(_require_admin)):
    """Returns last 500 audit entries (newest first)."""
    entries = _load_audit()
    return list(reversed(entries[-500:]))


# ── Bulk operations ──────────────────────────────────────────────
@app.post("/api/admin/licenses/bulk")
async def admin_bulk_action(request: Request, _: None = Depends(_require_admin)):
    """
    Bulk action across multiple keys.
    Body: {"action": "expire"|"revoke"|"renew", "keys": ["KEY1","KEY2",...]}
    """
    body   = await request.json()
    action = body.get("action", "")
    keys   = body.get("keys", [])
    if action not in {"expire", "revoke", "renew"}:
        raise HTTPException(400, "action must be one of: expire, revoke, renew")
    if not keys:
        raise HTTPException(400, "keys list required")

    lic = _load_licenses()
    affected: list[str] = []
    not_found: list[str] = []
    for key in keys:
        if key not in lic:
            not_found.append(key)
            continue
        if action == "expire":
            lic[key]["status"] = "expired"
        elif action == "revoke":
            lic[key]["status"] = "revoked"
            lic[key]["last_heartbeat"] = None
        elif action == "renew":
            lic[key]["status"] = "active"
        affected.append(key)
        _log_event(f"bulk_{action}", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _save_licenses(lic)
    _log_audit(f"bulk_{action}", f"{len(affected)} licenses", {
        "affected": [k[:8] + "…" for k in affected],
        "not_found": len(not_found),
    })
    return {"ok": True, "affected": len(affected), "not_found": len(not_found)}


# ── Settings ─────────────────────────────────────────────────────
@app.get("/api/admin/settings")
async def admin_settings(_: None = Depends(_require_admin)):
    """Returns config (no secret values, just presence)."""
    return {
        "smtp": {
            "host":     SMTP_HOST,
            "port":     SMTP_PORT,
            "user":     SMTP_USER,
            "password": "•••••••" if SMTP_PASS else "",
            "from":     FROM_EMAIL,
            "configured": bool(SMTP_HOST and SMTP_USER and SMTP_PASS),
        },
        "app_url":             APP_URL,
        "admin_secret_set":    ADMIN_SECRET != "dev-change-me",
        "data_dir":            str(DATA_DIR),
        "license_count":       len(_load_licenses()),
        "event_count":         len(_load_events()),
        "version":             "1.0.3",
    }


@app.post("/api/admin/settings/test-email")
async def admin_test_email(request: Request, _: None = Depends(_require_admin)):
    """Send a test email to verify SMTP config."""
    body = await request.json()
    to_email = body.get("to", "").strip().lower()
    if not to_email:
        raise HTTPException(400, "Recipient email required")

    if not SMTP_HOST:
        return {"sent": False, "reason": "SMTP not configured. Set SMTP_HOST/SMTP_USER/SMTP_PASS env vars."}

    test_body = """
      <h1 style="margin:0 0 12px 0;color:#FFFFFF;font-size:20px;font-weight:700;">SMTP test successful</h1>
      <p style="margin:0 0 20px 0;color:#7A9BB5;font-size:14px;line-height:1.6;">
        Your Pushkey email configuration is working correctly.<br>
        License keys, invites, and password resets will be delivered.
      </p>
      <div style="background:#00DC8222;border:1px solid #00DC8255;border-radius:10px;padding:16px 20px;">
        <p style="margin:0;color:#00DC82;font-size:14px;font-weight:600;">&#x2713; All systems go</p>
      </div>"""
    html = _email_html("Pushkey SMTP Test", "Your SMTP config is working correctly.", test_body)
    result = _send_email_html(to_email, "Pushkey SMTP Test", html, "Pushkey SMTP test — your email config is working correctly.")
    if result["sent"]:
        return {"sent": True, "to": to_email}
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

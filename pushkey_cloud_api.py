"""
Pushkey Cloud Sync API — self-hostable FastAPI backend (#28)
============================================================
Zero-knowledge: server stores only the encrypted vault blob.
It never sees plaintext keys. Auth is email + password (hashed).

Requirements:
    pip install fastapi uvicorn[standard] passlib[argon2] bcrypt python-jose[cryptography]

Run:
    uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000

Configure Pushkey to use: http://your-server:8000
"""

import hashlib
import hmac
import html as _html
import json
import logging
import os
import secrets
import smtplib
import threading
import time
import base64
import tempfile
from collections import Counter, deque
from pathlib import Path
import sqlite3

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - optional in local/dev installs
    redis_lib = None

# Load .env if present
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
from datetime import datetime, timedelta, timezone
from pushkey_shared import TIERS as PRODUCT_TIERS

def _utcnow() -> datetime:
    """Replacement for deprecated datetime.utcnow() — returns naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

try:
    from fastapi import FastAPI, HTTPException, Depends, Request, Header, Cookie
    from fastapi.responses import JSONResponse, Response
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from passlib.context import CryptContext
    from jose import jwt, JWTError
except ImportError:
    raise SystemExit(
        "Missing deps — run:\n  pip install fastapi uvicorn[standard] passlib[bcrypt] python-jose[cryptography]"
    )

# ── Config ──────────────────────────────────────────────────────
DATA_DIR  = Path(os.environ.get("PUSHKEY_DATA_DIR", "~/.pushkey-cloud")).expanduser()
ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.environ.get("PUSHKEY_TOKEN_TTL_HOURS", "1"))
TOKEN_ISSUER = os.environ.get("PUSHKEY_TOKEN_ISSUER", "pushkey-cloud")
TOKEN_AUDIENCE = os.environ.get("PUSHKEY_TOKEN_AUDIENCE", "pushkey-user-api")
_cloud_metadata_url = os.environ.get("PUSHKEY_CLOUD_DATABASE_URL", "").strip()
if not _cloud_metadata_url:
    _candidate_metadata_url = os.environ.get("DATABASE_URL", "").strip()
    if _candidate_metadata_url.lower().startswith("postgres"):
        _cloud_metadata_url = _candidate_metadata_url
CLOUD_METADATA_URL = _cloud_metadata_url

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
VAULT_STORE_DB = DATA_DIR / "vaults.sqlite"
VAULT_OBJECTS_DIR = DATA_DIR / "vault_objects"
LEGACY_VAULTS_DIR = DATA_DIR / "vaults"
RATE_LIMIT_DB = DATA_DIR / "rate_limits.sqlite"
MAX_REQUEST_BYTES = int(os.environ.get("PUSHKEY_MAX_REQUEST_BYTES", str(1024 * 1024)))
TRUSTED_HOSTS = [
    host.strip()
    for host in os.environ.get("PUSHKEY_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if host.strip()
]
ALLOWED_CORS_ORIGINS = [
    origin
    for origin in [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://www.push-key.com",
        "https://push-key.com",
        os.environ.get("ADMIN_ORIGIN", "").strip(),
    ]
    if origin
]
if MAX_REQUEST_BYTES <= 0:
    raise RuntimeError("PUSHKEY_MAX_REQUEST_BYTES must be greater than zero")
VAULT_OBJECTS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

pwd_ctx = CryptContext(schemes=["argon2", "bcrypt"], deprecated=["bcrypt"])
bearer  = HTTPBearer()
app     = FastAPI(title="Pushkey Cloud Sync", docs_url=None, redoc_url=None)
app.state.request_logs = deque(maxlen=1000)
app.state.metrics = {
    "requests_total": 0,
    "status_families": Counter(),
    "routes": Counter(),
}
app.state.idempotency_cache = {}
app.state.alerts = deque(maxlen=1000)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "If-None-Match",
        "X-CSRF-Token",
        "X-Device-ID",
        "X-Idempotency-Key",
        "X-Request-ID",
    ],
    expose_headers=["ETag", "X-Request-ID"],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    headers = dict(exc.headers or {})
    if exc.status_code == 429:
        path = request.url.path
        retry_after = RATE_LIMIT_WINDOW_SEC
        if path.startswith("/api/v1/auth") or path.startswith("/api/admin/auth"):
            retry_after = AUTH_RATE_WINDOW_SEC
        elif path.startswith("/api/portal"):
            retry_after = PORTAL_RATE_WINDOW_SEC
        headers.setdefault("Retry-After", str(retry_after))
        app.state.alerts.append(
            {
                "ts": _utcnow().isoformat(),
                "type": "rate_limit",
                "path": path,
                "method": request.method,
                "client": request.client.host if request.client else "unknown",
                "request_id": request.headers.get("X-Request-ID", ""),
            }
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


@app.middleware("http")
async def _cloud_security_boundary(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
    request.state.request_id = request_id
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                response.headers["X-Request-ID"] = request_id
                return response
        except ValueError:
            response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            response.headers["X-Request-ID"] = request_id
            return response

    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    status_family = f"{response.status_code // 100}xx"
    route_key = f"{request.method} {request.url.path}"
    app.state.metrics["requests_total"] += 1
    app.state.metrics["status_families"][status_family] += 1
    app.state.metrics["routes"][route_key] += 1
    app.state.request_logs.append(
        {
            "ts": _utcnow().isoformat(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "client": request.client.host if request.client else "unknown",
        }
    )
    return response

# ── Admin config ─────────────────────────────────────────────────
ADMIN_BOOTSTRAP_EMAIL = os.environ.get("PUSHKEY_ADMIN_EMAIL", "").strip().lower()
ADMIN_BOOTSTRAP_PASSWORD = os.environ.get("PUSHKEY_ADMIN_PASSWORD", "")
ADMIN_BOOTSTRAP_MFA_SECRET = os.environ.get("PUSHKEY_ADMIN_TOTP_SECRET", "").strip()
ADMIN_SESSION_TTL_MIN = int(os.environ.get("PUSHKEY_ADMIN_SESSION_TTL_MIN", "30"))
ADMIN_COOKIE_SECURE = os.environ.get("PUSHKEY_ADMIN_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
ADMIN_LOGIN_LOCKOUT_FAILURES = int(os.environ.get("PUSHKEY_ADMIN_LOGIN_LOCKOUT_FAILURES", "3"))
ADMIN_LOGIN_LOCKOUT_MIN = int(os.environ.get("PUSHKEY_ADMIN_LOGIN_LOCKOUT_MIN", "15"))
ADMIN_MFA_RECOVERY_CODE_COUNT = int(os.environ.get("PUSHKEY_ADMIN_MFA_RECOVERY_CODE_COUNT", "8"))
ADMIN_ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "support": {"read", "support"},
    "billing": {"read", "billing"},
    "admin": {"read", "support", "billing", "settings"},
    "owner": {"read", "support", "billing", "settings", "backup", "admins"},
}
if ADMIN_SESSION_TTL_MIN <= 0:
    raise RuntimeError("PUSHKEY_ADMIN_SESSION_TTL_MIN must be greater than zero")
if ADMIN_LOGIN_LOCKOUT_FAILURES <= 0:
    raise RuntimeError("PUSHKEY_ADMIN_LOGIN_LOCKOUT_FAILURES must be greater than zero")
if ADMIN_LOGIN_LOCKOUT_MIN <= 0:
    raise RuntimeError("PUSHKEY_ADMIN_LOGIN_LOCKOUT_MIN must be greater than zero")
if ADMIN_MFA_RECOVERY_CODE_COUNT <= 0:
    raise RuntimeError("PUSHKEY_ADMIN_MFA_RECOVERY_CODE_COUNT must be greater than zero")
if not ADMIN_BOOTSTRAP_EMAIL or not ADMIN_BOOTSTRAP_PASSWORD:
    if _DEV_MODE:
        ADMIN_BOOTSTRAP_EMAIL = ADMIN_BOOTSTRAP_EMAIL or "admin@localhost"
        ADMIN_BOOTSTRAP_PASSWORD = ADMIN_BOOTSTRAP_PASSWORD or "dev-change-me"
        print("[pushkey] WARNING: admin bootstrap credentials defaulted (dev mode only)")
    else:
        raise SystemExit(
            "\n[pushkey] FATAL: PUSHKEY_ADMIN_EMAIL and PUSHKEY_ADMIN_PASSWORD are required.\n"
            "Generate a password: python -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
            "For local dev only, set PUSHKEY_ENV=development to bypass this check.\n"
        )
TOKEN_SIGNING_KEYS = [
    key.strip()
    for key in (SECRET_KEY + "," + os.environ.get("PUSHKEY_JWT_PREVIOUS_SECRETS", "")).split(",")
    if key.strip()
]
_KNOWN_PREFIXES = {"free": "FREE", "starter": "STRT", "pro": "PRO", "team": "TEAM", "enterprise": "ENT"}
TIER_PREFIXES = {tier: _KNOWN_PREFIXES[tier] for tier in PRODUCT_TIERS}
DEVICE_LIMITS = {
    tier: definition["max_devices"] for tier, definition in PRODUCT_TIERS.items()
}
DEVICE_TOKEN_TTL_DAYS = int(os.environ.get("PUSHKEY_DEVICE_TOKEN_TTL_DAYS", "7"))
if DEVICE_TOKEN_TTL_DAYS <= 0:
    raise RuntimeError("PUSHKEY_DEVICE_TOKEN_TTL_DAYS must be greater than zero")
DEVICE_TOKEN_VERSION = 1
DEVICE_TOKEN_AUDIENCE = "pushkey-device-license-v1"
_LICENSE_LOCK = threading.RLock()
_ADMIN_SESSION_LOCK = threading.RLock()
_USER_LOCK = threading.RLock()

_OPS_METADATA = MetaData()

_OPS_DOCUMENTS = Table(
    "cloud_documents",
    _OPS_METADATA,
    Column("name", String, primary_key=True),
    Column("payload_json", Text, nullable=False),
    Column("updated_at", String, nullable=False),
)

_OPS_EVENTS = Table(
    "cloud_events",
    _OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stream_name", String, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

Index("idx_cloud_events_stream_id", _OPS_EVENTS.c.stream_name, _OPS_EVENTS.c.id)


class _CloudStateStore:
    def __init__(self, db_path: Path, *, metadata_url: str | None = None):
        self.db_path = db_path
        self._metadata_url = metadata_url
        self._lock = threading.RLock()
        self._engine = self._build_engine()
        self._dialect_name = self._engine.dialect.name
        _OPS_METADATA.create_all(self._engine)

    def _build_engine(self):
        url = _vault_database_url(self.db_path, self._metadata_url)
        options = {"poolclass": NullPool, "future": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        return create_engine(url, **options)

    def _connect(self):
        return self._engine.connect()

    def _dialect_insert(self, table):
        if self._dialect_name == "postgresql":
            return pg_insert(table)
        if self._dialect_name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(f"Unsupported database dialect: {self._dialect_name}")

    def load_document(self, name: str, default_factory) -> dict | list:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    select(_OPS_DOCUMENTS.c.payload_json).where(_OPS_DOCUMENTS.c.name == name)
                ).mappings().first()
                if not row:
                    return default_factory()
                payload = row["payload_json"]
                if not payload or not str(payload).strip():
                    return default_factory()
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    return default_factory()

    def save_document(self, name: str, data: dict | list) -> None:
        payload = json.dumps(data, indent=2)
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    stmt = self._dialect_insert(_OPS_DOCUMENTS).values(
                        {
                            "name": name,
                            "payload_json": payload,
                            "updated_at": now,
                        }
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[_OPS_DOCUMENTS.c.name],
                        set_={
                            "payload_json": stmt.excluded.payload_json,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    conn.execute(stmt)

    def insert_document_if_absent(self, name: str, data: dict | list) -> None:
        payload = json.dumps(data, indent=2)
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    stmt = self._dialect_insert(_OPS_DOCUMENTS).values(
                        {
                            "name": name,
                            "payload_json": payload,
                            "updated_at": now,
                        }
                    )
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=[_OPS_DOCUMENTS.c.name]
                    )
                    conn.execute(stmt)

    def mutate_document(self, name: str, default_factory, mutator):
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    row = conn.execute(
                        select(_OPS_DOCUMENTS.c.payload_json)
                        .where(_OPS_DOCUMENTS.c.name == name)
                        # Row lock so concurrent multi-worker mutations on
                        # PostgreSQL serialize instead of last-write-wins;
                        # SQLite ignores FOR UPDATE (single-writer already).
                        .with_for_update()
                    ).mappings().first()
                    if not row:
                        data = default_factory()
                    else:
                        payload = row["payload_json"]
                        if not payload or not str(payload).strip():
                            data = default_factory()
                        else:
                            try:
                                data = json.loads(payload)
                            except json.JSONDecodeError:
                                data = default_factory()
                    result = mutator(data)
                    now = _utcnow().isoformat()
                    stmt = self._dialect_insert(_OPS_DOCUMENTS).values(
                        {
                            "name": name,
                            "payload_json": json.dumps(data, indent=2),
                            "updated_at": now,
                        }
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[_OPS_DOCUMENTS.c.name],
                        set_={
                            "payload_json": stmt.excluded.payload_json,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    conn.execute(stmt)
                    return result

    def append_event(self, stream_name: str, entry: dict) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    conn.execute(
                        self._dialect_insert(_OPS_EVENTS).values(
                            {
                                "stream_name": stream_name,
                                "payload_json": json.dumps(entry),
                                "created_at": _utcnow().isoformat(),
                            }
                        )
                    )

    def load_events(self, stream_name: str, limit: int | None = None) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                stmt = select(_OPS_EVENTS.c.id, _OPS_EVENTS.c.payload_json).where(
                    _OPS_EVENTS.c.stream_name == stream_name
                )
                if limit is not None:
                    stmt = stmt.order_by(_OPS_EVENTS.c.id.desc()).limit(limit)
                else:
                    stmt = stmt.order_by(_OPS_EVENTS.c.id)
                rows = conn.execute(stmt).mappings().all()
                if limit is not None:
                    rows = list(reversed(rows))
                out: list[dict] = []
                for row in rows:
                    try:
                        out.append(json.loads(row["payload_json"]))
                    except Exception:
                        logging.warning(
                            "Skipping corrupt event row (stream=%s, id=%s)",
                            stream_name,
                            row["id"],
                        )
                return out


def _load_users() -> dict:
    with _USER_LOCK:
        return _STATE_STORE.load_document("users", dict)

def _save_users(users: dict) -> None:
    with _USER_LOCK:
        _STATE_STORE.save_document("users", users)


# ── JWT helpers ──────────────────────────────────────────────────
def _create_token(email: str) -> str:
    now = _utcnow()
    exp = now + timedelta(hours=TOKEN_TTL_HOURS)
    return jwt.encode(
        {
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "sub": email,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": secrets.token_urlsafe(16),
        },
        TOKEN_SIGNING_KEYS[0],
        algorithm=ALGORITHM,
    )

def _decode_token(token: str) -> str:
    for signing_key in TOKEN_SIGNING_KEYS:
        try:
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[ALGORITHM],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER,
            )
            return payload["sub"]
        except JWTError:
            continue
    raise HTTPException(status_code=401, detail="Invalid or expired token")

def _current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    email = _decode_token(creds.credentials)
    if email not in _load_users():
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return email


# ── Auth endpoints ───────────────────────────────────────────────
@app.post("/api/v1/auth/register")
async def register(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _rate_check_shared_request(
        "auth", ip, request, AUTH_RATE_MAX, AUTH_RATE_WINDOW_SEC
    ):
        raise HTTPException(429, f"Too many requests — try again in {AUTH_RATE_WINDOW_SEC}s")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    pw    = body.get("password", "")
    if not email or not pw or len(pw) < 8:
        raise HTTPException(400, "email and password (>=8 chars) required")
    with _USER_LOCK:
        users = _load_users()
        if email in users:
            raise HTTPException(409, "email already registered")
        users[email] = {"hash": pwd_ctx.hash(pw), "created": _utcnow().isoformat()}
        _save_users(users)
    return {"token": _create_token(email)}

@app.post("/api/v1/auth/login")
async def login(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _rate_check_shared_request(
        "auth", ip, request, AUTH_RATE_MAX, AUTH_RATE_WINDOW_SEC
    ):
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
def _etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vault_user_key(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()


def _normalize_database_url(database_url: str) -> str:
    normalized = database_url.strip()
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized[len("postgres://"):]
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized[len("postgresql://"):]
    return normalized


def _vault_database_url(db_path: Path, metadata_url: str | None) -> str:
    if metadata_url:
        return _normalize_database_url(metadata_url)
    return f"sqlite+pysqlite:///{db_path.resolve().as_posix()}"


def _vault_advisory_lock_key(user_key: str) -> int:
    return int(user_key[:16], 16) & 0x7FFFFFFFFFFFFFFF


_VAULT_METADATA = MetaData()

_VAULT_CURRENT = Table(
    "vault_current",
    _VAULT_METADATA,
    Column("user_key", String, primary_key=True),
    Column("revision_number", Integer, nullable=False),
    Column("object_key", String, nullable=False),
    Column("etag", String, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("updated_at", String, nullable=False),
)

_VAULT_HISTORY = Table(
    "vault_history",
    _VAULT_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_key", String, nullable=False),
    Column("revision_number", Integer, nullable=False),
    Column("object_key", String, nullable=False),
    Column("etag", String, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("stored_at", String, nullable=False),
    Column("source_key", String, nullable=False, unique=True),
)

_VAULT_REVISION_TRANSACTIONS = Table(
    "vault_revision_transactions",
    _VAULT_METADATA,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("revision_number", Integer, nullable=False),
    Column("object_key", String, nullable=False),
    Column("etag", String, nullable=False),
    Column("previous_etag", String),
    Column("object_sha256", String, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("idempotency_key", String),
    Column("request_id", String),
    Column("audit_id", String),
    Column("committed_at", String, nullable=False),
    UniqueConstraint("user_id", "revision_number", name="uq_vault_revision_transactions_user_revision"),
    UniqueConstraint("user_id", "idempotency_key", name="uq_vault_revision_transactions_user_idempotency"),
)

Index("idx_vault_history_user_revision", _VAULT_HISTORY.c.user_key, _VAULT_HISTORY.c.revision_number, unique=True)
Index("idx_vault_history_user_stored", _VAULT_HISTORY.c.user_key, _VAULT_HISTORY.c.stored_at, _VAULT_HISTORY.c.revision_number)
Index("idx_vault_revision_transactions_user_commit", _VAULT_REVISION_TRANSACTIONS.c.user_id, _VAULT_REVISION_TRANSACTIONS.c.committed_at)


class _VaultConflict(Exception):
    def __init__(self, current_etag: str):
        super().__init__("vault revision conflict")
        self.current_etag = current_etag


class _VaultStore:
    def __init__(
        self,
        db_path: Path,
        legacy_dir: Path,
        *,
        metadata_url: str | None = None,
        engine=None,
        create_schema: bool = True,
    ):
        self.db_path = db_path
        self.legacy_dir = legacy_dir
        self.object_dir = VAULT_OBJECTS_DIR
        self._lock = threading.RLock()
        self._metadata_url = metadata_url
        self._engine = engine or self._build_engine()
        self._dialect_name = self._engine.dialect.name
        if create_schema:
            _VAULT_METADATA.create_all(self._engine)

    def _build_engine(self):
        url = _vault_database_url(self.db_path, self._metadata_url)
        options = {"poolclass": NullPool, "future": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        return create_engine(url, **options)

    def _connect(self):
        return self._engine.connect()

    def _dialect_insert(self, table):
        if self._dialect_name == "postgresql":
            return pg_insert(table)
        if self._dialect_name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(f"Unsupported database dialect: {self._dialect_name}")

    def _object_path(self, object_key: str) -> Path:
        return self.object_dir / f"{object_key}.blob"

    def _write_object(self, object_key: str, blob: bytes) -> None:
        self.object_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._object_path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            ) as handle:
                handle.write(blob)
                handle.flush()
                tmp_path = Path(handle.name)
            os.replace(tmp_path, target)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _read_object(self, object_key: str) -> bytes:
        return self._object_path(object_key).read_bytes()

    def _delete_object(self, object_key: str) -> None:
        try:
            self._object_path(object_key).unlink()
        except OSError:
            pass

    def _legacy_paths(self, user_key: str) -> tuple[Path, Path]:
        current = self.legacy_dir / f"{user_key}.enc"
        history = self.legacy_dir / f"{user_key}.history"
        return current, history

    def _upsert_current(self, conn, values: dict) -> None:
        stmt = self._dialect_insert(_VAULT_CURRENT).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[_VAULT_CURRENT.c.user_key],
            set_={
                "revision_number": stmt.excluded.revision_number,
                "object_key": stmt.excluded.object_key,
                "etag": stmt.excluded.etag,
                "size_bytes": stmt.excluded.size_bytes,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        conn.execute(stmt)

    @staticmethod
    def _current_row(conn, user_key: str):
        return conn.execute(
            select(
                _VAULT_CURRENT.c.revision_number,
                _VAULT_CURRENT.c.object_key,
                _VAULT_CURRENT.c.etag,
                _VAULT_CURRENT.c.size_bytes,
                _VAULT_CURRENT.c.updated_at,
            ).where(_VAULT_CURRENT.c.user_key == user_key)
        ).mappings().first()

    @staticmethod
    def _transaction_row(conn, user_key: str, idempotency_key: str):
        return conn.execute(
            select(
                _VAULT_REVISION_TRANSACTIONS.c.id,
                _VAULT_REVISION_TRANSACTIONS.c.user_id,
                _VAULT_REVISION_TRANSACTIONS.c.revision_number,
                _VAULT_REVISION_TRANSACTIONS.c.object_key,
                _VAULT_REVISION_TRANSACTIONS.c.etag,
                _VAULT_REVISION_TRANSACTIONS.c.previous_etag,
                _VAULT_REVISION_TRANSACTIONS.c.object_sha256,
                _VAULT_REVISION_TRANSACTIONS.c.size_bytes,
                _VAULT_REVISION_TRANSACTIONS.c.idempotency_key,
                _VAULT_REVISION_TRANSACTIONS.c.request_id,
                _VAULT_REVISION_TRANSACTIONS.c.audit_id,
                _VAULT_REVISION_TRANSACTIONS.c.committed_at,
            ).where(
                _VAULT_REVISION_TRANSACTIONS.c.user_id == user_key,
                _VAULT_REVISION_TRANSACTIONS.c.idempotency_key == idempotency_key,
            )
        ).mappings().first()

    @staticmethod
    def _transaction_response(row) -> dict:
        return {
            "etag": row["etag"],
            "size": row["size_bytes"],
            "updated": row["committed_at"],
        }

    @staticmethod
    def _cleanup_legacy_files(current_path: Path, history_dir: Path) -> None:
        try:
            if current_path.exists():
                current_path.unlink()
        except OSError:
            pass
        if history_dir.exists():
            for item in history_dir.glob("*"):
                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                except OSError:
                    pass
            try:
                history_dir.rmdir()
            except OSError:
                pass

    def _advisory_lock(self, conn, user_key: str) -> None:
        if self._dialect_name != "postgresql":
            return
        conn.execute(select(func.pg_advisory_xact_lock(_vault_advisory_lock_key(user_key))))

    def _insert_ignore_row(self, conn, table, values: dict, index_elements: list[str]) -> None:
        stmt = self._dialect_insert(table).values(values)
        stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
        conn.execute(stmt)

    def _ensure_imported(self, conn, user_key: str) -> None:
        current = self._current_row(conn, user_key)
        if current is not None:
            return

        current_path, history_dir = self._legacy_paths(user_key)
        if not current_path.exists():
            return

        history_items = []
        if history_dir.exists():
            history_items = [item for item in sorted(history_dir.glob("*.enc")) if item.is_file()]

        current_blob = current_path.read_bytes()
        now = _utcnow().isoformat()
        previous_etag = None
        created_object_keys: list[str] = []

        try:
            for revision_number, item in enumerate(history_items, start=1):
                blob = item.read_bytes()
                etag = _etag(blob)
                blob_sha = _sha256(blob)
                object_key = f"legacy_{user_key}_history_{revision_number}_{secrets.token_hex(8)}"
                self._write_object(object_key, blob)
                created_object_keys.append(object_key)
                source_key = f"legacy:{item.name}"
                self._insert_ignore_row(
                    conn,
                    _VAULT_HISTORY,
                    {
                        "user_key": user_key,
                        "revision_number": revision_number,
                        "object_key": object_key,
                        "etag": etag,
                        "size_bytes": len(blob),
                        "stored_at": now,
                        "source_key": source_key,
                    },
                    ["source_key"],
                )
                self._insert_ignore_row(
                    conn,
                    _VAULT_REVISION_TRANSACTIONS,
                    {
                        "id": hashlib.sha256(f"{source_key}:{blob_sha}".encode()).hexdigest(),
                        "user_id": user_key,
                        "revision_number": revision_number,
                        "object_key": object_key,
                        "etag": etag,
                        "previous_etag": previous_etag,
                        "object_sha256": blob_sha,
                        "size_bytes": len(blob),
                        "idempotency_key": source_key,
                        "request_id": "legacy-import",
                        "audit_id": None,
                        "committed_at": now,
                    },
                    ["id"],
                )
                previous_etag = etag

            current_etag = _etag(current_blob)
            current_sha = _sha256(current_blob)
            current_revision = len(history_items) + 1
            current_object_key = f"legacy_{user_key}_current_{secrets.token_hex(8)}"
            self._write_object(current_object_key, current_blob)
            created_object_keys.append(current_object_key)

            self._upsert_current(
                conn,
                {
                    "user_key": user_key,
                    "revision_number": current_revision,
                    "object_key": current_object_key,
                    "etag": current_etag,
                    "size_bytes": len(current_blob),
                    "updated_at": now,
                },
            )
            self._insert_ignore_row(
                conn,
                _VAULT_REVISION_TRANSACTIONS,
                {
                    "id": hashlib.sha256(f"legacy:{current_path.name}:{current_sha}".encode()).hexdigest(),
                    "user_id": user_key,
                    "revision_number": current_revision,
                    "object_key": current_object_key,
                    "etag": current_etag,
                    "previous_etag": previous_etag,
                    "object_sha256": current_sha,
                    "size_bytes": len(current_blob),
                    "idempotency_key": f"legacy:{current_path.name}",
                    "request_id": "legacy-import",
                    "audit_id": None,
                    "committed_at": now,
                },
                ["id"],
            )
        except Exception:
            for object_key in created_object_keys:
                self._delete_object(object_key)
            raise

        self._cleanup_legacy_files(current_path, history_dir)

    def put(
        self,
        email: str,
        blob: bytes,
        if_match: str = "",
        *,
        idempotency_key: str = "",
        request_id: str = "",
    ) -> dict:
        user_key = _vault_user_key(email)
        idempotency_key = idempotency_key.strip() or None
        object_key = ""
        with self._lock:
            with self._connect() as conn:
                try:
                    with conn.begin():
                        self._ensure_imported(conn, user_key)
                        self._advisory_lock(conn, user_key)
                        if idempotency_key:
                            existing = self._transaction_row(conn, user_key, idempotency_key)
                            if existing is not None:
                                return self._transaction_response(existing)
                        current = self._current_row(conn, user_key)
                        current_etag = current["etag"] if current else ""
                        if current is not None and if_match and if_match != current_etag:
                            raise _VaultConflict(current_etag)

                        now = _utcnow().isoformat()
                        new_etag = _etag(blob)
                        blob_sha = _sha256(blob)
                        revision_number = 1
                        object_key = f"vault_{user_key}_{secrets.token_hex(16)}"
                        self._write_object(object_key, blob)
                        if current is not None:
                            self._insert_ignore_row(
                                conn,
                                _VAULT_HISTORY,
                                {
                                    "user_key": user_key,
                                    "revision_number": int(current["revision_number"]),
                                    "object_key": current["object_key"],
                                    "etag": current["etag"],
                                    "size_bytes": int(current["size_bytes"]),
                                    "stored_at": now,
                                    "source_key": current["object_key"],
                                },
                                ["source_key"],
                            )
                            revision_number = int(current["revision_number"]) + 1

                        self._upsert_current(
                            conn,
                            {
                                "user_key": user_key,
                                "revision_number": revision_number,
                                "object_key": object_key,
                                "etag": new_etag,
                                "size_bytes": len(blob),
                                "updated_at": now,
                            },
                        )
                        conn.execute(
                            self._dialect_insert(_VAULT_REVISION_TRANSACTIONS).values(
                                {
                                    "id": secrets.token_hex(16),
                                    "user_id": user_key,
                                    "revision_number": revision_number,
                                    "object_key": object_key,
                                    "etag": new_etag,
                                    "previous_etag": current_etag or None,
                                    "object_sha256": blob_sha,
                                    "size_bytes": len(blob),
                                    "idempotency_key": idempotency_key,
                                    "request_id": request_id or None,
                                    "audit_id": None,
                                    "committed_at": now,
                                }
                            )
                        )
                    return {"etag": new_etag, "size": len(blob), "updated": now}
                except IntegrityError:
                    if object_key:
                        self._delete_object(object_key)
                    if idempotency_key:
                        existing = self._transaction_row(conn, user_key, idempotency_key)
                        if existing is not None:
                            return self._transaction_response(existing)
                    raise
                except Exception:
                    if object_key:
                        self._delete_object(object_key)
                    raise

    def get(self, email: str):
        user_key = _vault_user_key(email)
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    self._ensure_imported(conn, user_key)
                    return self._current_row(conn, user_key)

    def history(self, email: str) -> list[dict]:
        user_key = _vault_user_key(email)
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    self._ensure_imported(conn, user_key)
                    rows = conn.execute(
                        select(
                            _VAULT_HISTORY.c.revision_number,
                            _VAULT_HISTORY.c.etag,
                            _VAULT_HISTORY.c.size_bytes,
                            _VAULT_HISTORY.c.stored_at,
                        ).where(_VAULT_HISTORY.c.user_key == user_key).order_by(
                            _VAULT_HISTORY.c.revision_number.asc(),
                            _VAULT_HISTORY.c.id.asc(),
                        )
                    ).mappings().all()
        return [
            {
                "etag": row["etag"],
                "size": row["size_bytes"],
                "stored": row["stored_at"],
            }
            for row in rows
        ]

    def delete(self, email: str) -> None:
        user_key = _vault_user_key(email)
        current_path, history_dir = self._legacy_paths(user_key)
        object_keys: list[str] = []
        with self._lock:
            with self._connect() as conn:
                with conn.begin():
                    self._ensure_imported(conn, user_key)
                    object_keys.extend(
                        conn.execute(
                            select(_VAULT_HISTORY.c.object_key).where(_VAULT_HISTORY.c.user_key == user_key)
                        ).scalars().all()
                    )
                    current = self._current_row(conn, user_key)
                    if current is not None:
                        object_keys.append(current["object_key"])
                    conn.execute(
                        delete(_VAULT_REVISION_TRANSACTIONS).where(_VAULT_REVISION_TRANSACTIONS.c.user_id == user_key)
                    )
                    conn.execute(delete(_VAULT_HISTORY).where(_VAULT_HISTORY.c.user_key == user_key))
                    conn.execute(delete(_VAULT_CURRENT).where(_VAULT_CURRENT.c.user_key == user_key))
        for object_key in dict.fromkeys(object_keys):
            self._delete_object(object_key)
        self._cleanup_legacy_files(current_path, history_dir)


_vault_store = _VaultStore(VAULT_STORE_DB, LEGACY_VAULTS_DIR, metadata_url=CLOUD_METADATA_URL)
_STATE_STORE = _CloudStateStore(VAULT_STORE_DB, metadata_url=CLOUD_METADATA_URL)

@app.put("/api/v1/vault")
async def put_vault(
    request: Request,
    if_match: str = Header(default="", alias="if-match"),
    idempotency_key: str = Header(default="", alias="x-idempotency-key"),
    email: str = Depends(_current_user),
):
    cache_key = ("PUT", email, idempotency_key)
    if idempotency_key and cache_key in app.state.idempotency_cache:
        return app.state.idempotency_cache[cache_key]

    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty body")
    try:
        result = _vault_store.put(
            email,
            blob,
            if_match,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", request.headers.get("X-Request-ID", "")),
        )
    except _VaultConflict as exc:
        return JSONResponse(
            {
                "detail": "vault revision conflict",
                "current_etag": exc.current_etag,
            },
            status_code=409,
        )
    if idempotency_key:
        app.state.idempotency_cache[cache_key] = result
    return result

@app.get("/api/v1/vault")
async def get_vault(
    if_none_match: str = Header(default="", alias="if-none-match"),
    email: str = Depends(_current_user),
):
    row = _vault_store.get(email)
    if row is None:
        raise HTTPException(404, "No vault stored")
    tag = row["etag"]
    if if_none_match and if_none_match == tag:
        return Response(status_code=304)
    blob = _vault_store._read_object(row["object_key"])
    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={"ETag": tag, "Content-Length": str(len(blob))},
    )

@app.get("/api/v1/vault/meta")
async def vault_meta(email: str = Depends(_current_user)):
    row = _vault_store.get(email)
    if row is None:
        return {"exists": False}
    return {
        "exists": True,
        "size": row["size_bytes"],
        "etag": row["etag"],
        "modified": row["updated_at"],
    }

@app.get("/api/v1/vault/history")
async def vault_history(email: str = Depends(_current_user)):
    return {"versions": _vault_store.history(email)}


@app.get("/api/v1/account/export")
async def account_export(email: str = Depends(_current_user)):
    users = _load_users()
    user = users.get(email, {})
    vault = {"exists": False}
    row = _vault_store.get(email)
    if row is not None:
        vault = {
            "exists": True,
            "size": row["size_bytes"],
            "etag": row["etag"],
            "modified": row["updated_at"],
        }
    return {
        "account": {
            "email": email,
            "created": user.get("created"),
        },
        "vault": vault,
    }


@app.delete("/api/v1/account")
async def account_delete(email: str = Depends(_current_user)):
    users = _load_users()
    users.pop(email, None)
    _save_users(users)
    _vault_store.delete(email)
    return {"ok": True}

@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "pushkey-cloud"}


@app.get("/api/v1/ops/metrics")
async def ops_metrics():
    metrics = app.state.metrics
    return {
        "requests_total": metrics["requests_total"],
        "status_families": dict(metrics["status_families"]),
        "routes": dict(metrics["routes"]),
    }


# ── Event log (append-only event streams for analytics) ─────────
_LOG_LOCK = threading.RLock()

def _log_outbox(
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
    request_id: str = "",
) -> dict:
    entry = {
        "id": secrets.token_hex(16),
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "event_type": event_type,
        "payload": payload,
        "request_id": request_id,
        "created_at": _utcnow().isoformat(),
        "dispatched_at": None,
    }
    _STATE_STORE.append_event("outbox", entry)
    return entry

def _log_event(event_type: str, data: dict) -> None:
    entry = {"ts": _utcnow().isoformat(), "type": event_type, **data}
    with _LOG_LOCK:
        _STATE_STORE.append_event("events", entry)
        _log_outbox("event", event_type, event_type, data, data.get("request_id", ""))

def _load_events() -> list[dict]:
    return _STATE_STORE.load_events("events")

def _log_audit(
    action: str,
    target: str,
    details: dict | None = None,
    actor: dict | None = None,
    request: Request | None = None,
) -> None:
    """Record admin action for compliance audit trail."""
    request_id = request.headers.get("x-request-id", "") if request else ""
    entry = {
        "id":      secrets.token_hex(16),
        "ts":      _utcnow().isoformat(),
        "action":  action,
        "target":  target,
        "details": details or {},
        "actor_id": actor.get("id", "system") if actor else "system",
        "actor_email": actor.get("email", "") if actor else "",
        "actor_role": actor.get("role", "") if actor else "",
        "request_id": request_id,
        "ip": request.client.host if request and request.client else "",
    }
    with _LOG_LOCK:
        _STATE_STORE.append_event("audit", entry)
        _log_outbox("audit", target, action, entry, request_id)

def _load_audit() -> list[dict]:
    return _STATE_STORE.load_events("audit")

def _load_outbox() -> list[dict]:
    return _STATE_STORE.load_events("outbox")


# ── Client-facing heartbeat ──────────────────────────────────────
# Legacy in-memory token bucket helper remains for unit tests.
RATE_LIMIT_MAX        = int(os.environ.get("HEARTBEAT_RATE_MAX", "10"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("HEARTBEAT_RATE_WINDOW", "60"))
RATE_LIMIT_MAX_ENTRIES = int(os.environ.get("RATE_LIMIT_MAX_ENTRIES", "10000"))
RATE_LIMIT_GLOBAL_MULTIPLIER = int(
    os.environ.get("RATE_LIMIT_GLOBAL_MULTIPLIER", "100")
)
AUTH_RATE_MAX         = int(os.environ.get("AUTH_RATE_MAX", "5"))
AUTH_RATE_WINDOW_SEC  = int(os.environ.get("AUTH_RATE_WINDOW", "60"))
PORTAL_RATE_MAX       = int(os.environ.get("PORTAL_RATE_MAX", "20"))
PORTAL_RATE_WINDOW_SEC = int(os.environ.get("PORTAL_RATE_WINDOW", "60"))

for _config_name, _config_value in {
    "HEARTBEAT_RATE_MAX": RATE_LIMIT_MAX,
    "HEARTBEAT_RATE_WINDOW": RATE_LIMIT_WINDOW_SEC,
    "AUTH_RATE_MAX": AUTH_RATE_MAX,
    "AUTH_RATE_WINDOW": AUTH_RATE_WINDOW_SEC,
    "PORTAL_RATE_MAX": PORTAL_RATE_MAX,
    "PORTAL_RATE_WINDOW": PORTAL_RATE_WINDOW_SEC,
    "RATE_LIMIT_MAX_ENTRIES": RATE_LIMIT_MAX_ENTRIES,
    "RATE_LIMIT_GLOBAL_MULTIPLIER": RATE_LIMIT_GLOBAL_MULTIPLIER,
}.items():
    if _config_value <= 0:
        raise RuntimeError(f"{_config_name} must be greater than zero")

_HEARTBEAT_HITS: dict[str, list[float]] = {}
_ACTIVATION_HITS: dict[str, list[float]] = {}
_DEACTIVATION_HITS: dict[str, list[float]] = {}
_AUTH_HITS:      dict[str, list[float]] = {}
_PORTAL_HITS:    dict[str, list[float]] = {}
_RATE_LOCK = threading.Lock()
RATE_LIMIT_BACKEND = os.environ.get("PUSHKEY_RATE_LIMIT_BACKEND", "").strip().lower()
RATE_LIMIT_REDIS_URL = os.environ.get(
    "PUSHKEY_RATE_LIMIT_REDIS_URL",
    os.environ.get("REDIS_URL", ""),
).strip()
RATE_LIMIT_KEY_PREFIX = os.environ.get(
    "PUSHKEY_RATE_LIMIT_KEY_PREFIX",
    "pushkey:rate-limits",
).strip() or "pushkey:rate-limits"


def _ensure_rate_limit_store(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_buckets (
            bucket TEXT PRIMARY KEY,
            hits_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limit_buckets_updated_at "
        "ON rate_limit_buckets(updated_at)"
    )


def _load_rate_limit_hits(
    conn: sqlite3.Connection, bucket: str, cutoff: float
) -> list[float]:
    row = conn.execute(
        "SELECT hits_json FROM rate_limit_buckets WHERE bucket = ?",
        (bucket,),
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        hits = [float(hit) for hit in json.loads(row[0])]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [hit for hit in hits if hit > cutoff]


def _store_rate_limit_hits(
    conn: sqlite3.Connection, bucket: str, hits: list[float], now: float
) -> None:
    conn.execute(
        """
        INSERT INTO rate_limit_buckets(bucket, hits_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(bucket) DO UPDATE SET
            hits_json=excluded.hits_json,
            updated_at=excluded.updated_at
        """,
        (bucket, json.dumps(hits), now),
    )


def _rate_identity_key(identity: str) -> str:
    normalized = identity.strip().casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _rate_limit_bucket_key(namespace: str, kind: str, identity: str | None = None) -> str:
    suffix = _rate_identity_key(identity) if identity is not None else "global"
    return f"{RATE_LIMIT_KEY_PREFIX}:{namespace}:{kind}:{suffix}"


class _SQLiteRateLimitStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def allow(self, namespace: str, identity: str, max_hits: int, window_sec: int) -> bool:
        now = time.time()
        cutoff = now - window_sec
        identity_bucket = _rate_limit_bucket_key(namespace, "identity", identity)
        global_bucket = _rate_limit_bucket_key(namespace, "global")
        global_limit = max_hits * max(1, RATE_LIMIT_GLOBAL_MULTIPLIER)

        with _RATE_LOCK:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                _ensure_rate_limit_store(conn)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM rate_limit_buckets WHERE updated_at <= ?",
                    (cutoff,),
                )

                staged: list[tuple[str, list[float]]] = []
                for bucket, limit in (
                    (identity_bucket, max_hits),
                    (global_bucket, global_limit),
                ):
                    hits = _load_rate_limit_hits(conn, bucket, cutoff)
                    if len(hits) >= limit:
                        conn.rollback()
                        return False
                    hits.append(now)
                    staged.append((bucket, hits))

                for bucket, hits in staged:
                    _store_rate_limit_hits(conn, bucket, hits, now)

                conn.commit()
                return True


class _RedisRateLimitStore:
    _SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local identity_limit = tonumber(ARGV[3])
local global_limit = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local buckets = {
  {key = KEYS[1], limit = identity_limit},
  {key = KEYS[2], limit = global_limit},
}
for i = 1, #buckets do
  redis.call("ZREMRANGEBYSCORE", buckets[i].key, "-inf", now - window)
  local count = redis.call("ZCARD", buckets[i].key)
  if count >= buckets[i].limit then
    return 0
  end
end
for i = 1, #buckets do
  local seq_key = buckets[i].key .. ":seq"
  local seq = redis.call("INCR", seq_key)
  redis.call("ZADD", buckets[i].key, now, tostring(now) .. ":" .. tostring(seq))
  redis.call("EXPIRE", buckets[i].key, ttl)
  redis.call("EXPIRE", seq_key, ttl)
end
return 1
"""

    def __init__(self, url: str):
        if redis_lib is None:
            raise SystemExit(
                "Redis rate limiting was requested but the 'redis' package is not installed."
            )
        self.url = url
        self.client = redis_lib.Redis.from_url(url, decode_responses=True)
        try:
            self.client.ping()
        except Exception as exc:  # pragma: no cover - connection failure is environment-specific
            raise SystemExit(f"Unable to connect to Redis rate-limit backend: {exc}") from exc

    def allow(self, namespace: str, identity: str, max_hits: int, window_sec: int) -> bool:
        now = time.time()
        identity_bucket = _rate_limit_bucket_key(namespace, "identity", identity)
        global_bucket = _rate_limit_bucket_key(namespace, "global")
        global_limit = max_hits * max(1, RATE_LIMIT_GLOBAL_MULTIPLIER)
        ttl = max(window_sec * 2, 60)
        try:
            allowed = self.client.eval(
                self._SCRIPT,
                2,
                identity_bucket,
                global_bucket,
                now,
                window_sec,
                max_hits,
                global_limit,
                ttl,
            )
        except Exception as exc:  # pragma: no cover - backend-specific
            raise RuntimeError(f"Redis rate-limit check failed: {exc}") from exc
        return bool(int(allowed))


def _build_rate_limit_store():
    backend = RATE_LIMIT_BACKEND
    if backend == "sqlite":
        return _SQLiteRateLimitStore(RATE_LIMIT_DB)
    if backend == "redis":
        return _RedisRateLimitStore(RATE_LIMIT_REDIS_URL or "redis://localhost:6379/0")
    if RATE_LIMIT_REDIS_URL:
        return _RedisRateLimitStore(RATE_LIMIT_REDIS_URL)
    if backend == "":
        return _SQLiteRateLimitStore(RATE_LIMIT_DB)
    raise RuntimeError(
        "PUSHKEY_RATE_LIMIT_BACKEND must be 'sqlite' or 'redis' when set"
    )


_RATE_LIMIT_STORE = _build_rate_limit_store()


def _rate_check_shared_request(
    namespace: str, identity: str, request: Request, max_hits: int, window_sec: int
) -> bool:
    """Shared limiter backed by the configured durable store."""
    return _RATE_LIMIT_STORE.allow(namespace, identity, max_hits, window_sec)


def _rate_check(bucket: dict, key: str, max_hits: int, window_sec: int) -> bool:
    """Bounded, thread-safe sliding-window check. Returns True if allowed."""
    now = time.time()
    with _RATE_LOCK:
        cutoff = now - window_sec
        hits = [h for h in bucket.get(key, ()) if h > cutoff]
        if len(hits) >= max_hits:
            bucket[key] = hits
            return False
        hits.append(now)
        bucket[key] = hits

        # Remove expired/empty entries before enforcing the hard memory bound.
        if len(bucket) > RATE_LIMIT_MAX_ENTRIES:
            for stale_key in list(bucket):
                live = [h for h in bucket[stale_key] if h > cutoff]
                if live:
                    bucket[stale_key] = live
                else:
                    bucket.pop(stale_key, None)
            if len(bucket) > RATE_LIMIT_MAX_ENTRIES:
                oldest = sorted(
                    bucket, key=lambda item: bucket[item][-1]
                )[: len(bucket) - RATE_LIMIT_MAX_ENTRIES]
                for stale_key in oldest:
                    bucket.pop(stale_key, None)
        return True


def _rate_check_request(
    bucket: dict, identity: str, request: Request, max_hits: int, window_sec: int
) -> bool:
    """Limit one license identity and aggregate endpoint traffic."""
    if not _rate_check(bucket, f"identity:{identity}", max_hits, window_sec):
        return False
    return _rate_check(
        bucket,
        "global",
        max_hits * max(1, RATE_LIMIT_GLOBAL_MULTIPLIER),
        window_sec,
    )


def _check_rate_limit(key: str, request: Request) -> bool:
    return _rate_check_shared_request(
        "heartbeat", key, request, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SEC
    )


def _normalized_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if expiry.tzinfo:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return expiry


def _license_state(entry: dict) -> str:
    """Return the authoritative current status and apply time-based expiry."""
    status = entry.get("status", "active")
    expires_at = entry.get("expires_at")
    if status == "active" and expires_at:
        try:
            expiry = _normalized_expiry(expires_at)
        except (TypeError, ValueError):
            entry["status"] = "invalid"
            return "invalid"
        if expiry <= _utcnow():
            entry["status"] = "expired"
            entry["stage"] = "churned"
            return "expired"
    return status


def _device_token(license_key: str, fingerprint: str, tier: str) -> str:
    """Issue a signed, expiring token bound to one license/device/tier."""
    payload = {
        "kh": hashlib.sha256(license_key.encode()).hexdigest(),
        "fp": fingerprint,
        "tier": tier,
        "v": DEVICE_TOKEN_VERSION,
        "aud": DEVICE_TOKEN_AUDIENCE,
        "exp": (
            _utcnow() + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
        ).isoformat(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signing_key = hmac.new(SECRET_KEY.encode(), b"pushkey/device-token/v1", hashlib.sha256).digest()
    signature = hmac.new(signing_key, encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _valid_device_token(
    token: str, license_key: str, fingerprint: str, tier: str
) -> bool:
    try:
        encoded, signature = token.split(".", 1)
        signing_key = hmac.new(SECRET_KEY.encode(), b"pushkey/device-token/v1", hashlib.sha256).digest()
        expected = hmac.new(signing_key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return (
            payload["kh"] == hashlib.sha256(license_key.encode()).hexdigest()
            and payload["fp"] == fingerprint
            and payload["tier"] == tier
            and payload["v"] == DEVICE_TOKEN_VERSION
            and payload["aud"] == DEVICE_TOKEN_AUDIENCE
            and _utcnow() <= datetime.fromisoformat(payload["exp"])
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _require_usable_license(licenses: dict, key: str) -> dict:
    entry = licenses.get(key)
    if entry is None:
        raise HTTPException(404, {"code": "license_not_found", "message": "License not found"})
    status = _license_state(entry)
    if status == "revoked":
        raise HTTPException(403, {"code": "license_revoked", "message": "License revoked"})
    if status == "expired":
        raise HTTPException(403, {"code": "license_expired", "message": "License expired"})
    if status != "active":
        raise HTTPException(403, {"code": "license_unusable", "message": f"License {status}"})
    tier = entry.get("tier", "")
    if tier not in DEVICE_LIMITS:
        raise HTTPException(500, {"code": "invalid_license_tier", "message": "License has invalid tier"})
    return entry


async def _handle_activate(body: dict, request: Request) -> dict:
    key = body.get("license_key", "").strip().upper()
    fingerprint = body.get("fingerprint", "").strip()
    if not key:
        raise HTTPException(400, {"code": "invalid_request", "message": "license_key required"})
    if not fingerprint:
        raise HTTPException(400, {"code": "invalid_request", "message": "fingerprint required"})
    if not _rate_check_shared_request(
        "activate", key, request, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SEC
    ):
        raise HTTPException(429, {"code": "rate_limited", "message": "Too many activation requests"})

    def activate_device(licenses):
        entry = _require_usable_license(licenses, key)
        tier = entry["tier"]
        devices = entry.setdefault("devices", {})
        max_devices = DEVICE_LIMITS[tier]
        if fingerprint not in devices and (max_devices is not None and len(devices) >= max_devices):
            plural = "device" if max_devices == 1 else "devices"
            raise HTTPException(409, {"code": "device_limit_reached", "message": f"Device limit reached ({max_devices} {plural} for {tier.title()} plan)."})
        now = _utcnow().isoformat()
        device = devices.setdefault(fingerprint, {"activated_at": now})
        device.update({"last_seen": now, "platform": body.get("platform", ""), "version": body.get("version", "")})
        entry["last_heartbeat"] = now
        entry["platform"] = body.get("platform", "")
        return entry.copy(), device.copy(), len(devices), max_devices

    entry, device, devices_used, max_devices = _mutate_licenses(activate_device)
    tier = entry["tier"]
    _log_event(
        "device_activated",
        {"key": key[:8] + "…", "tier": tier, "platform": device["platform"]},
    )
    return {
        "ok": True,
        "status": "active",
        "tier": tier,
        "expires_at": entry.get("expires_at"),
        "token": _device_token(key, fingerprint, tier),
        "devices_used": devices_used,
        "devices_max": max_devices,
    }


async def _handle_deactivate(body: dict, request: Request) -> dict:
    key = body.get("license_key", "").strip().upper()
    fingerprint = body.get("fingerprint", "").strip()
    token = body.get("token", "")
    if not key:
        raise HTTPException(400, {"code": "invalid_request", "message": "license_key required"})
    if not fingerprint:
        raise HTTPException(400, {"code": "invalid_request", "message": "fingerprint required"})
    if not _rate_check_shared_request(
        "deactivate", key, request, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_SEC
    ):
        raise HTTPException(429, {"code": "rate_limited", "message": "Too many deactivation requests"})

    def deactivate_device(licenses):
        entry = _require_usable_license(licenses, key)
        if fingerprint not in entry.setdefault("devices", {}):
            raise HTTPException(403, {"code": "device_unregistered", "message": "Device not registered"})
        if not _valid_device_token(token, key, fingerprint, entry["tier"]):
            raise HTTPException(403, {"code": "token_expired", "message": "Invalid or expired device token"})
        entry["devices"].pop(fingerprint)
    _mutate_licenses(deactivate_device)
    _log_event("device_deactivated", {"key": key[:8] + "…"})
    return {"ok": True}


async def _handle_heartbeat(
    body: dict, request: Request, *, strict: bool = True
) -> dict:
    """Shared logic for both /v1/heartbeat and /api/v1/heartbeat."""
    import platform as _pl
    key = body.get("license_key", "").strip().upper()
    if not key:
        raise HTTPException(400, {"code": "invalid_request", "message": "license_key required"})
    if not _check_rate_limit(key, request):
        raise HTTPException(429, {"code": "rate_limited", "message": f"Too many heartbeats — limit is {RATE_LIMIT_MAX} per {RATE_LIMIT_WINDOW_SEC}s"})

    # Accept platform from body, or auto-detect if missing
    platform = body.get("platform", "") or f"{_pl.system()} {_pl.release()}"
    version  = body.get("version", "")

    fingerprint = body.get("fingerprint", "").strip()
    token = body.get("token", "")
    agent_token_count = body.get("agent_token_count", 0)
    if strict and (not fingerprint or not token):
        raise HTTPException(400, {"code": "invalid_request", "message": "fingerprint and token required"})
    def update_heartbeat(lic):
        entry = _require_usable_license(lic, key)
        if fingerprint:
            devices = entry.setdefault("devices", {})
            if fingerprint not in devices:
                raise HTTPException(403, {"code": "device_unregistered", "message": "Device not registered. Please reactivate your license."})
            if not _valid_device_token(token, key, fingerprint, entry["tier"]):
                raise HTTPException(403, {"code": "token_expired", "message": "Invalid or expired device token"})
            devices[fingerprint].update({
                "last_seen": _utcnow().isoformat(),
                "platform": platform,
                "version": version,
            })
        entry["last_heartbeat"] = _utcnow().isoformat()
        entry["platform"] = platform
        if isinstance(agent_token_count, int):
            entry["agent_token_count"] = agent_token_count
        return entry.copy()

    entry = _mutate_licenses(update_heartbeat)

    _log_event("heartbeat", {"key": key[:8] + "…", "tier": entry["tier"], "platform": platform, "version": version, "agent_tokens": agent_token_count})

    return {
        "ok": True,
        "status": entry["status"],
        "tier": entry["tier"],
        "expires_at": entry.get("expires_at"),
        "token": _device_token(key, fingerprint, entry["tier"]) if fingerprint else "",
    }


@app.post("/v1/heartbeat")
async def heartbeat(request: Request):
    return await _handle_heartbeat(await request.json(), request, strict=True)


@app.post("/api/v1/heartbeat")
async def heartbeat_alias(request: Request):
    return await _handle_heartbeat(await request.json(), request, strict=True)


@app.post("/v1/activate")
@app.post("/api/v1/activate")
async def activate(request: Request):
    return await _handle_activate(await request.json(), request)


@app.post("/v1/deactivate")
@app.post("/api/v1/deactivate")
async def deactivate(request: Request):
    return await _handle_deactivate(await request.json(), request)


# ── Admin helpers ────────────────────────────────────────────────
def _load_licenses() -> dict:
    with _LICENSE_LOCK:
        return _STATE_STORE.load_document("licenses", dict)

def _save_licenses(data: dict) -> None:
    with _LICENSE_LOCK:
        _STATE_STORE.save_document("licenses", data)


def _mutate_licenses(mutator):
    """Run one synchronous license read-modify-write transaction."""
    with _LICENSE_LOCK:
        return _STATE_STORE.mutate_document("licenses", dict, mutator)

def _load_admins() -> dict:
    admins = _STATE_STORE.load_document("admins", dict)
    if admins:
        return admins
    admin_id = hashlib.sha256(ADMIN_BOOTSTRAP_EMAIL.encode()).hexdigest()[:16]
    data = {
        admin_id: {
            "id": admin_id,
            "email": ADMIN_BOOTSTRAP_EMAIL,
            "display_name": ADMIN_BOOTSTRAP_EMAIL.split("@", 1)[0] or "admin",
            "hash": pwd_ctx.hash(ADMIN_BOOTSTRAP_PASSWORD),
            "role": "owner",
            "mfa_secret": ADMIN_BOOTSTRAP_MFA_SECRET,
            "created": _utcnow().isoformat(),
            "disabled": False,
        }
    }
    _STATE_STORE.insert_document_if_absent("admins", data)
    return _STATE_STORE.load_document("admins", dict)


def _save_admins(data: dict) -> None:
    _STATE_STORE.save_document("admins", data)


def _admin_display_name(admin: dict) -> str:
    display_name = str(admin.get("display_name", "")).strip()
    if display_name:
        return display_name
    email = str(admin.get("email", "")).strip()
    if email:
        return email.split("@", 1)[0]
    return str(admin.get("id", "admin"))


def _admin_public_record(admin: dict) -> dict:
    sessions = _load_admin_sessions()
    session_count = sum(
        1
        for session in sessions.values()
        if session.get("admin_id") == admin.get("id") and not session.get("revoked")
    )
    return {
        "id": admin.get("id", ""),
        "email": admin.get("email", ""),
        "display_name": _admin_display_name(admin),
        "role": admin.get("role", "viewer"),
        "disabled": bool(admin.get("disabled")),
        "created": admin.get("created", ""),
        "mfa_enabled": bool(admin.get("mfa_secret")),
        "session_count": session_count,
    }


def _admin_email_in_use(admins: dict, email: str, *, exclude_id: str | None = None) -> bool:
    email = email.strip().lower()
    for admin_id, admin in admins.items():
        if exclude_id is not None and admin_id == exclude_id:
            continue
        if admin.get("email", "").strip().lower() == email:
            return True
    return False


def _active_owner_count(admins: dict, *, exclude_id: str | None = None) -> int:
    return sum(
        1
        for admin_id, admin in admins.items()
        if (exclude_id is None or admin_id != exclude_id)
        and admin.get("role", "viewer") == "owner"
        and not admin.get("disabled")
    )


def _new_admin_id(admins: dict) -> str:
    while True:
        admin_id = secrets.token_hex(8)
        if admin_id not in admins:
            return admin_id


def _load_admin_sessions() -> dict:
    with _ADMIN_SESSION_LOCK:
        return _STATE_STORE.load_document("admin_sessions", dict)


def _save_admin_sessions(data: dict) -> None:
    with _ADMIN_SESSION_LOCK:
        _STATE_STORE.save_document("admin_sessions", data)


def _revoke_admin_sessions(admin_id: str, *, except_hash: str | None = None) -> int:
    sessions = _load_admin_sessions()
    revoked = 0
    for token_hash, session in sessions.items():
        if token_hash == except_hash:
            continue
        if session.get("admin_id") == admin_id and not session.get("revoked"):
            session["revoked"] = True
            revoked += 1
    if revoked:
        _save_admin_sessions(sessions)
    return revoked


def _admin_by_email(email: str) -> dict | None:
    email = email.strip().lower()
    for admin in _load_admins().values():
        if admin.get("email", "").lower() == email:
            return admin
    return None


def _admin_is_locked(admin: dict) -> bool:
    until = admin.get("lockout_until") or ""
    return bool(until and until > _utcnow().isoformat())


def _record_failed_admin_login(admin: dict, request: Request) -> None:
    admins = _load_admins()
    current = admins.get(admin["id"])
    if not current:
        return
    failures = int(current.get("failed_login_count", 0)) + 1
    current["failed_login_count"] = failures
    if failures >= ADMIN_LOGIN_LOCKOUT_FAILURES:
        current["lockout_until"] = (_utcnow() + timedelta(minutes=ADMIN_LOGIN_LOCKOUT_MIN)).isoformat()
        _log_audit(
            "admin_login_lockout",
            current["id"],
            {"failures": failures},
            actor=current,
            request=request,
        )
    _save_admins(admins)


def _reset_admin_login_failures(admin: dict) -> None:
    admins = _load_admins()
    current = admins.get(admin["id"])
    if not current:
        return
    current["failed_login_count"] = 0
    current["lockout_until"] = ""
    _save_admins(admins)


def _totp_code(secret: str, counter: int) -> str:
    import struct
    normalized = secret.replace(" ", "").upper()
    padded = normalized + "=" * (-len(normalized) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _verify_totp(secret: str, code: str, now: int | None = None) -> bool:
    if not secret:
        return True
    if not code or not code.isdigit():
        return False
    step = int((now or time.time()) // 30)
    return any(hmac.compare_digest(_totp_code(secret, step + drift), code) for drift in (-1, 0, 1))


def _new_mfa_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _new_mfa_recovery_codes() -> list[str]:
    return [f"PK-MFA-{secrets.token_urlsafe(10).replace('-', '').replace('_', '')[:12].upper()}" for _ in range(ADMIN_MFA_RECOVERY_CODE_COUNT)]


def _hash_mfa_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _issue_admin_session(admin: dict, request: Request) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    sessions = _load_admin_sessions()
    expires_at = (_utcnow() + timedelta(minutes=ADMIN_SESSION_TTL_MIN)).isoformat()
    sessions[token_hash] = {
        "admin_id": admin["id"],
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "created": _utcnow().isoformat(),
        "expires_at": expires_at,
        "revoked": False,
        "ip": request.client.host if request.client else "",
        "last_used": _utcnow().isoformat(),
    }
    _save_admin_sessions(sessions)
    return token, csrf


def _set_admin_cookies(response: Response, token: str, csrf: str) -> None:
    response.set_cookie(
        "pk_admin_session",
        token,
        httponly=True,
        secure=ADMIN_COOKIE_SECURE,
        samesite="strict",
        max_age=ADMIN_SESSION_TTL_MIN * 60,
        path="/",
    )
    response.set_cookie(
        "pk_admin_csrf",
        csrf,
        httponly=False,
        secure=ADMIN_COOKIE_SECURE,
        samesite="strict",
        max_age=ADMIN_SESSION_TTL_MIN * 60,
        path="/",
    )


def _clear_admin_cookies(response: Response) -> None:
    response.delete_cookie("pk_admin_session", path="/")
    response.delete_cookie("pk_admin_csrf", path="/")


def _require_admin(
    request: Request,
    pk_admin_session: str = Cookie(default=""),
    x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
) -> dict:
    if not pk_admin_session:
        raise HTTPException(401, "Not authenticated")
    token_hash = hashlib.sha256(pk_admin_session.encode()).hexdigest()
    sessions = _load_admin_sessions()
    session = sessions.get(token_hash)
    if not session or session.get("revoked"):
        raise HTTPException(401, "Not authenticated")
    if session["expires_at"] < _utcnow().isoformat():
        session["revoked"] = True
        _save_admin_sessions(sessions)
        raise HTTPException(401, "Session expired")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = session.get("csrf_hash", "")
        actual = hashlib.sha256(x_csrf_token.encode()).hexdigest() if x_csrf_token else ""
        if not expected or not hmac.compare_digest(expected, actual):
            raise HTTPException(403, "CSRF check failed")
    admin = _load_admins().get(session["admin_id"])
    if not admin or admin.get("disabled"):
        raise HTTPException(403, "Admin disabled")
    session["last_used"] = _utcnow().isoformat()
    _save_admin_sessions(sessions)
    return {"id": admin["id"], "email": admin["email"], "role": admin.get("role", "viewer")}


def _require_admin_permission(permission: str):
    def dependency(actor: dict = Depends(_require_admin)) -> dict:
        role = actor.get("role", "viewer")
        if permission not in ADMIN_ROLE_PERMISSIONS.get(role, set()):
            raise HTTPException(403, "Admin role lacks required permission")
        return actor
    return dependency

def _gen_key(tier: str) -> str:
    import secrets as _sec, string as _s
    chars = _s.ascii_uppercase + _s.digits
    prefix = TIER_PREFIXES.get(tier, "FREE")
    seg1 = "".join(_sec.choice(chars) for _ in range(8))
    seg2 = "".join(_sec.choice(chars) for _ in range(16))
    seg3 = "".join(_sec.choice(chars) for _ in range(4))
    return f"{prefix}-{seg1}-{seg2}-{seg3}"


@app.post("/api/admin/auth/login")
async def admin_login(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _rate_check_shared_request(
        "auth", f"admin:{ip}", request, AUTH_RATE_MAX, AUTH_RATE_WINDOW_SEC
    ):
        raise HTTPException(429, "Too many login attempts")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    mfa_code = body.get("mfa_code", "")
    admin = _admin_by_email(email) if email else None
    if admin and _admin_is_locked(admin):
        raise HTTPException(423, "Admin account locked")
    if not admin or admin.get("disabled") or not pwd_ctx.verify(password, admin["hash"]):
        if admin and not admin.get("disabled"):
            _record_failed_admin_login(admin, request)
        raise HTTPException(401, "Invalid credentials")
    if not _verify_totp(admin.get("mfa_secret", ""), mfa_code):
        _record_failed_admin_login(admin, request)
        raise HTTPException(401, "Invalid credentials")
    _reset_admin_login_failures(admin)
    token, csrf = _issue_admin_session(admin, request)
    response = JSONResponse({
        "ok": True,
        "admin": {"id": admin["id"], "email": admin["email"], "role": admin.get("role", "viewer")},
        "csrf_token": csrf,
        "mfa_required": bool(admin.get("mfa_secret")),
    })
    _set_admin_cookies(response, token, csrf)
    _log_audit("admin_login", admin["id"], actor=admin, request=request)
    return response


@app.post("/api/admin/auth/logout")
async def admin_logout(
    response: Response,
    actor: dict = Depends(_require_admin),
    pk_admin_session: str = Cookie(default=""),
):
    sessions = _load_admin_sessions()
    if pk_admin_session:
        token_hash = hashlib.sha256(pk_admin_session.encode()).hexdigest()
        if token_hash in sessions:
            sessions[token_hash]["revoked"] = True
            _save_admin_sessions(sessions)
    _clear_admin_cookies(response)
    _log_audit("admin_logout", actor["id"], actor=actor)
    return {"ok": True}


@app.post("/api/admin/auth/refresh")
async def admin_refresh(
    request: Request,
    actor: dict = Depends(_require_admin),
    pk_admin_session: str = Cookie(default=""),
):
    old_hash = hashlib.sha256(pk_admin_session.encode()).hexdigest()
    sessions = _load_admin_sessions()
    if old_hash in sessions:
        sessions[old_hash]["revoked"] = True
        _save_admin_sessions(sessions)
    token, csrf = _issue_admin_session(actor, request)
    response = JSONResponse({"ok": True, "csrf_token": csrf, "admin": actor})
    _set_admin_cookies(response, token, csrf)
    _log_audit("admin_session_refresh", actor["id"], actor=actor, request=request)
    return response


@app.get("/api/admin/auth/me")
async def admin_me(actor: dict = Depends(_require_admin)):
    return {"admin": actor}


@app.post("/api/admin/auth/mfa/setup")
async def admin_mfa_setup(
    request: Request,
    actor: dict = Depends(_require_admin),
):
    secret = _new_mfa_secret()
    codes = _new_mfa_recovery_codes()
    admins = _load_admins()
    admin = admins.get(actor["id"])
    if not admin:
        raise HTTPException(404, "Admin not found")
    admin["mfa_pending_secret"] = secret
    admin["mfa_pending_recovery_hashes"] = [_hash_mfa_recovery_code(code) for code in codes]
    _save_admins(admins)
    _log_audit("admin_mfa_setup", actor["id"], actor=actor, request=request)
    return {"secret": secret, "recovery_codes": codes}


@app.post("/api/admin/auth/mfa/confirm")
async def admin_mfa_confirm(
    request: Request,
    actor: dict = Depends(_require_admin),
):
    body = await request.json()
    code = str(body.get("code", ""))
    admins = _load_admins()
    admin = admins.get(actor["id"])
    if not admin:
        raise HTTPException(404, "Admin not found")
    secret = admin.get("mfa_pending_secret", "")
    if not secret or not _verify_totp(secret, code):
        raise HTTPException(400, "Invalid MFA confirmation code")
    admin["mfa_secret"] = secret
    admin["mfa_recovery_hashes"] = admin.get("mfa_pending_recovery_hashes", [])
    admin.pop("mfa_pending_secret", None)
    admin.pop("mfa_pending_recovery_hashes", None)
    _save_admins(admins)
    _log_audit("admin_mfa_confirm", actor["id"], actor=actor, request=request)
    return {"enabled": True}


@app.get("/api/admin/admins")
async def admin_list(
    actor: dict = Depends(_require_admin_permission("admins")),
):
    admins = _load_admins()
    records = sorted(admins.values(), key=lambda admin: admin.get("email", "").lower())
    return {"admins": [_admin_public_record(admin) for admin in records], "count": len(records)}


@app.post("/api/admin/admins")
async def admin_create(
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    role = str(body.get("role", "viewer")).strip() or "viewer"
    display_name = str(body.get("display_name", "")).strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Admin email required")
    if len(password) < 8:
        raise HTTPException(400, "Admin password too short")
    if role not in ADMIN_ROLE_PERMISSIONS:
        raise HTTPException(400, "Invalid admin role")

    admins = _load_admins()
    if _admin_email_in_use(admins, email):
        raise HTTPException(409, "Admin already exists")

    admin_id = _new_admin_id(admins)
    admin = {
        "id": admin_id,
        "email": email,
        "display_name": display_name,
        "hash": pwd_ctx.hash(password),
        "role": role,
        "mfa_secret": "",
        "mfa_recovery_hashes": [],
        "created": _utcnow().isoformat(),
        "disabled": False,
    }
    admins[admin_id] = admin
    _save_admins(admins)
    _log_audit(
        "admin_create",
        admin_id,
        {"email": email, "role": role, "display_name": _admin_display_name(admin)},
        actor=actor,
        request=request,
    )
    return _admin_public_record(admin)


@app.patch("/api/admin/admins/{admin_id}")
async def admin_update(
    admin_id: str,
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    body = await request.json()
    if not any(key in body for key in ("email", "password", "role", "display_name")):
        raise HTTPException(400, "No changes requested")

    admins = _load_admins()
    admin = admins.get(admin_id)
    if not admin:
        raise HTTPException(404, "Admin not found")

    changes: dict[str, dict | str] = {}

    if "email" in body:
        email = str(body.get("email", "")).strip().lower()
        if not email or "@" not in email:
            raise HTTPException(400, "Admin email required")
        if _admin_email_in_use(admins, email, exclude_id=admin_id):
            raise HTTPException(409, "Admin already exists")
        if email != admin.get("email", "").strip().lower():
            changes["email"] = {"from": admin.get("email", ""), "to": email}
            admin["email"] = email

    if "display_name" in body:
        display_name = str(body.get("display_name", "")).strip()
        if display_name != str(admin.get("display_name", "")).strip():
            changes["display_name"] = {"from": admin.get("display_name", ""), "to": display_name}
            admin["display_name"] = display_name

    if "password" in body:
        password = str(body.get("password", ""))
        if len(password) < 8:
            raise HTTPException(400, "Admin password too short")
        admin["hash"] = pwd_ctx.hash(password)
        changes["password"] = "updated"

    if "role" in body:
        role = str(body.get("role", "")).strip()
        if role not in ADMIN_ROLE_PERMISSIONS:
            raise HTTPException(400, "Invalid admin role")
        current_role = admin.get("role", "viewer")
        if current_role == "owner" and role != "owner" and _active_owner_count(admins, exclude_id=admin_id) == 0:
            raise HTTPException(400, "At least one active owner is required")
        if role != current_role:
            changes["role"] = {"from": current_role, "to": role}
            admin["role"] = role

    _save_admins(admins)
    _log_audit(
        "admin_update",
        admin_id,
        {
            "changes": changes,
            "email": admin.get("email", ""),
            "role": admin.get("role", ""),
            "display_name": _admin_display_name(admin),
        },
        actor=actor,
        request=request,
    )
    return _admin_public_record(admin)


@app.post("/api/admin/admins/{admin_id}/disable")
async def admin_disable(
    admin_id: str,
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    admins = _load_admins()
    admin = admins.get(admin_id)
    if not admin:
        raise HTTPException(404, "Admin not found")
    if admin.get("role", "viewer") == "owner" and not admin.get("disabled") and _active_owner_count(admins, exclude_id=admin_id) == 0:
        raise HTTPException(400, "At least one active owner is required")

    admin["disabled"] = True
    revoked = _revoke_admin_sessions(admin_id)
    _save_admins(admins)
    _log_audit(
        "admin_disable",
        admin_id,
        {"revoked": revoked, "email": admin.get("email", "")},
        actor=actor,
        request=request,
    )
    return {"ok": True, "admin": _admin_public_record(admin), "revoked": revoked}


@app.post("/api/admin/admins/{admin_id}/enable")
async def admin_enable(
    admin_id: str,
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    admins = _load_admins()
    admin = admins.get(admin_id)
    if not admin:
        raise HTTPException(404, "Admin not found")

    admin["disabled"] = False
    _save_admins(admins)
    _log_audit(
        "admin_enable",
        admin_id,
        {"email": admin.get("email", "")},
        actor=actor,
        request=request,
    )
    return {"ok": True, "admin": _admin_public_record(admin)}


@app.post("/api/admin/admins/{admin_id}/sessions/revoke")
async def admin_revoke_sessions(
    admin_id: str,
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    admins = _load_admins()
    if admin_id not in admins:
        raise HTTPException(404, "Admin not found")
    revoked = _revoke_admin_sessions(admin_id)
    _log_audit(
        "admin_sessions_revoke",
        admin_id,
        {"revoked": revoked, "target_email": admins[admin_id].get("email", "")},
        actor=actor,
        request=request,
    )
    return {"ok": True, "admin_id": admin_id, "revoked": revoked}


@app.post("/api/admin/admins/{admin_id}/mfa/reset")
async def admin_reset_mfa(
    admin_id: str,
    request: Request,
    actor: dict = Depends(_require_admin_permission("admins")),
):
    admins = _load_admins()
    if admin_id not in admins:
        raise HTTPException(404, "Admin not found")
    target = admins[admin_id]
    target["mfa_secret"] = ""
    target["mfa_recovery_hashes"] = []
    target.pop("mfa_pending_secret", None)
    target.pop("mfa_pending_recovery_hashes", None)
    _save_admins(admins)
    _log_audit("admin_mfa_reset", admin_id, {"target_email": target.get("email", "")}, actor=actor, request=request)
    return {"ok": True, "admin_id": admin_id, "reset": True}


SMTP_HOST  = os.environ.get("SMTP_HOST", "")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER", "")
SMTP_PASS  = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)
APP_URL    = os.environ.get("APP_URL", "https://pushkey.app")
SMTP_TIMEOUT_SEC = float(os.environ.get("SMTP_TIMEOUT_SEC", "10"))
SMTP_RETRY_ATTEMPTS = int(os.environ.get("SMTP_RETRY_ATTEMPTS", "3"))
SMTP_RETRY_DELAY_SEC = float(os.environ.get("SMTP_RETRY_DELAY_SEC", "0.25"))
DEAD_LETTER_DIR = DATA_DIR / "dead-letter"
DEAD_LETTER_DIR.mkdir(exist_ok=True)


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
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))
    last_error = ""
    for attempt in range(1, max(1, SMTP_RETRY_ATTEMPTS) + 1):
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SEC) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(FROM_EMAIL, [to], msg.as_string())
            return {"sent": True, "attempts": attempt}
        except Exception as exc:
            last_error = str(exc)
            if attempt < max(1, SMTP_RETRY_ATTEMPTS) and SMTP_RETRY_DELAY_SEC > 0:
                time.sleep(SMTP_RETRY_DELAY_SEC)

    dead_letter = {
        "ts": _utcnow().isoformat(),
        "to": to,
        "subject": subject,
        "smtp_host": SMTP_HOST,
        "attempts": max(1, SMTP_RETRY_ATTEMPTS),
        "error": last_error,
    }
    target = DEAD_LETTER_DIR / f"email-{int(time.time() * 1000)}-{secrets.token_hex(4)}.json"
    target.write_text(json.dumps(dead_letter, indent=2), encoding="utf-8")
    return {"sent": False, "reason": "dead_lettered", "attempts": max(1, SMTP_RETRY_ATTEMPTS)}


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
            and _normalized_expiry(entry["expires_at"]) <= _utcnow()
        ):
            entry["status"] = "expired"
            entry["stage"]  = "churned"
            changed = True
    return changed


# ── Admin endpoints ──────────────────────────────────────────────
@app.get("/api/admin/stats")
async def admin_stats(_: dict = Depends(_require_admin_permission("read"))):
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
async def admin_list_licenses(_: dict = Depends(_require_admin_permission("read"))):
    lic = _mutate_licenses(lambda licenses: (_auto_expire(licenses), licenses)[1])
    return list(lic.values())


@app.post("/api/admin/licenses/generate")
async def admin_generate(request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
    body = await request.json()
    tier = body.get("tier", "free").lower()
    if tier not in TIER_PREFIXES:
        raise HTTPException(400, f"tier must be one of: {list(TIER_PREFIXES)}")
    def generate(lic):
        key = _gen_key(tier)
        while key in lic:
            key = _gen_key(tier)
        entry = {
            "key": key, "tier": tier, "email": body.get("email", ""),
            "platform": body.get("platform", ""), "activated": _utcnow().isoformat(),
            "last_heartbeat": None, "status": "active",
            "notes": body.get("notes", ""),
        }
        lic[key] = entry
        return entry.copy()
    entry = _mutate_licenses(generate)
    key = entry["key"]
    _log_event("activated", {"key": key[:8] + "…", "tier": tier, "email": entry["email"]})
    _log_audit("generate_license", key, {"tier": tier, "email": entry["email"]}, actor=actor, request=request)
    return entry


VALID_SOURCES = {"Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"}
VALID_TRIAL_DAYS = {7, 14, 30}


@app.post("/api/admin/licenses/issue")
async def admin_issue(request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
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

    def issue(lic):
        key = _gen_key(tier)
        while key in lic:
            key = _gen_key(tier)
        entry = {
        "key": key,
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
        lic[key] = entry
        return entry.copy()

    email_result = {"sent": False, "reason": "not_requested"}
    entry = _mutate_licenses(issue)
    key = entry["key"]
    if send_email:
        email_result = _send_invite_email(email, name, tier, key, expires_at)
        if email_result.get("sent"):
            def mark_invited(lic):
                if key in lic:
                    lic[key]["sent_invite"] = True
                    return lic[key].copy()
                return entry
            entry = _mutate_licenses(mark_invited)
    _log_event("issued", {"key": key[:8] + "…", "tier": tier, "email": email})
    _log_audit("issue_license", key, {
        "tier": tier, "email": email, "trial_days": trial_days,
        "send_email": send_email, "email_sent": email_result.get("sent", False),
    }, actor=actor, request=request)
    return {**entry, "email_result": email_result}


@app.get("/api/admin/contacts")
async def admin_contacts(_: dict = Depends(_require_admin_permission("read"))):
    lic = _mutate_licenses(lambda licenses: (_auto_expire(licenses), licenses)[1])

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
    email: str, request: Request, actor: dict = Depends(_require_admin_permission("support"))
):
    email = email.lower()
    body  = await request.json()
    allowed = {"name", "company", "follow_up_date", "stage", "notes", "source"}
    changes = {k: v for k, v in body.items() if k in allowed}
    def update_contact(lic):
        matched = [v for v in lic.values() if v.get("email", "").lower() == email]
        if not matched:
            raise HTTPException(404, "Contact not found")
        for entry in matched:
            for field in allowed:
                if field in body:
                    entry[field] = body[field]
        return len(matched)
    matched_count = _mutate_licenses(update_contact)
    _log_audit("update_contact", email, {"fields": list(changes.keys()), "updated": matched_count}, actor=actor, request=request)
    return {"ok": True, "updated": matched_count}


@app.post("/api/admin/licenses/{key}/send-invite")
async def admin_send_invite(key: str, request: Request, actor: dict = Depends(_require_admin_permission("support"))):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    entry = lic[key].copy()
    result = _send_invite_email(
        entry["email"], entry.get("name", ""), entry["tier"],
        key, entry.get("expires_at")
    )
    if result.get("sent"):
        def mark_invited(licenses):
            if key not in licenses:
                raise HTTPException(404, "License not found")
            licenses[key]["sent_invite"] = True
        _mutate_licenses(mark_invited)
    _log_audit("send_invite", key, {"email": entry["email"], "sent": result.get("sent", False)}, actor=actor, request=request)
    return result


@app.post("/api/admin/licenses/{key}/expire")
async def admin_expire(key: str, request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
    def expire(lic):
        if key not in lic:
            raise HTTPException(404, "License not found")
        lic[key]["status"] = "expired"
        return lic[key].copy()
    entry = _mutate_licenses(expire)
    lic = {key: entry}
    _log_event("expired", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("expire_license", key, {"tier": lic[key]["tier"]}, actor=actor, request=request)
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/revoke")
async def admin_revoke(key: str, request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
    def revoke(lic):
        if key not in lic:
            raise HTTPException(404, "License not found")
        lic[key]["status"] = "revoked"
        lic[key]["last_heartbeat"] = None
        return lic[key].copy()
    entry = _mutate_licenses(revoke)
    lic = {key: entry}
    _log_event("revoked", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("revoke_license", key, {"tier": lic[key]["tier"]}, actor=actor, request=request)
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/renew")
async def admin_renew(key: str, request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
    def renew(lic):
        if key not in lic:
            raise HTTPException(404, "License not found")
        lic[key]["status"] = "active"
        return lic[key].copy()
    entry = _mutate_licenses(renew)
    lic = {key: entry}
    _log_event("renewed", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
    _log_audit("renew_license", key, {"tier": lic[key]["tier"]}, actor=actor, request=request)
    return {"ok": True}


@app.get("/api/admin/analytics")
async def admin_analytics(_: dict = Depends(_require_admin_permission("read"))):
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
    _: dict = Depends(_require_admin_permission("read")),
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
async def admin_backup(request: Request, actor: dict = Depends(_require_admin_permission("backup"))):
    """Returns tar.gz of all data files (licenses, tickets, audit log, events, users — NOT vault blobs)."""
    import tarfile, io
    buf = io.BytesIO()
    licenses = _load_licenses()
    tickets = _load_tickets()
    audit_entries = _load_audit()
    event_entries = _load_events()
    outbox_entries = _load_outbox()
    users = _load_users()

    def _jsonl_bytes(entries: list[dict]) -> bytes:
        text = "\n".join(json.dumps(entry) for entry in entries)
        if text:
            text += "\n"
        return text.encode("utf-8")

    exports = {
        "licenses.json": json.dumps(licenses, indent=2).encode("utf-8"),
        "tickets.json": json.dumps(tickets, indent=2).encode("utf-8"),
        "audit.jsonl": _jsonl_bytes(audit_entries),
        "events.jsonl": _jsonl_bytes(event_entries),
        "outbox.jsonl": _jsonl_bytes(outbox_entries),
        "users.json": json.dumps(users, indent=2).encode("utf-8"),
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname, payload in exports.items():
            info = tarfile.TarInfo(fname)
            info.size = len(payload)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(payload))
    buf.seek(0)
    _log_audit("backup", "data_dir", {"size_bytes": len(buf.getvalue())}, actor=actor, request=request)
    timestamp = _utcnow().strftime("%Y-%m-%d-%H%M%S")
    return Response(
        content=buf.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename=pushkey-backup-{timestamp}.tar.gz"},
    )


# ── Support tickets ──────────────────────────────────────────────
def _load_tickets() -> list[dict]:
    return _STATE_STORE.load_document("tickets", list)

def _save_tickets(tickets: list[dict]) -> None:
    _STATE_STORE.save_document("tickets", tickets)


@app.post("/api/admin/tickets")
async def admin_create_ticket(request: Request, actor: dict = Depends(_require_admin_permission("support"))):
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
    _log_audit("create_ticket", ticket["id"], {"email": email, "subject": subj, "priority": pri}, actor=actor, request=request)

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
async def admin_list_tickets(_: dict = Depends(_require_admin_permission("support"))):
    return list(reversed(_load_tickets()))


@app.patch("/api/admin/tickets/{ticket_id}")
async def admin_update_ticket(ticket_id: str, request: Request, actor: dict = Depends(_require_admin_permission("support"))):
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
    _log_audit("update_ticket", ticket_id, {"status": target["status"], "had_reply": "reply" in body}, actor=actor, request=request)
    return target


# ── Customer self-serve portal ───────────────────────────────────
@app.post("/api/v1/portal/lookup")
async def portal_lookup(request: Request):
    """
    Customer enters their license key to view info.
    Returns sanitized license info — never exposes other customers' data.
    """
    ip = request.client.host if request.client else "unknown"
    if not _rate_check_shared_request(
        "portal", ip, request, PORTAL_RATE_MAX, PORTAL_RATE_WINDOW_SEC
    ):
        raise HTTPException(429, f"Too many requests — try again in {PORTAL_RATE_WINDOW_SEC}s")
    body = await request.json()
    key = body.get("license_key", "").strip().upper()
    if not key:
        raise HTTPException(400, "license_key required")

    def lookup(lic):
        if key not in lic:
            raise HTTPException(404, "License not found")
        _license_state(lic[key])
        return lic[key].copy()
    entry = _mutate_licenses(lookup)

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
    _log_audit("portal_renewal_request", key, {"email": email}, request=request)
    return {"ok": True, "ticket_id": ticket["id"]}


# ── Audit log endpoint ───────────────────────────────────────────
@app.get("/api/admin/audit")
async def admin_audit_log(_: dict = Depends(_require_admin_permission("read"))):
    """Returns last 500 audit entries (newest first)."""
    entries = _load_audit()
    return list(reversed(entries[-500:]))


# ── Bulk operations ──────────────────────────────────────────────
@app.post("/api/admin/licenses/bulk")
async def admin_bulk_action(request: Request, actor: dict = Depends(_require_admin_permission("billing"))):
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

    def update_many(lic):
        affected: list[tuple[str, str]] = []
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
            affected.append((key, lic[key]["tier"]))
        return affected, not_found
    affected_with_tiers, not_found = _mutate_licenses(update_many)
    affected = [key for key, _tier in affected_with_tiers]
    for key, tier in affected_with_tiers:
        _log_event(f"bulk_{action}", {"key": key[:8] + "…", "tier": tier})
    _log_audit(
        f"bulk_{action}",
        f"{len(affected)} licenses",
        {"affected": [k[:8] for k in affected], "not_found": len(not_found)},
        actor=actor,
        request=request,
    )
    return {"ok": True, "affected": len(affected), "not_found": len(not_found)}


# ── Settings ─────────────────────────────────────────────────────
@app.get("/api/admin/settings")
async def admin_settings(_: dict = Depends(_require_admin_permission("settings"))):
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
        "admin_auth":          "cookie_session",
        "data_dir":            str(DATA_DIR),
        "license_count":       len(_load_licenses()),
        "event_count":         len(_load_events()),
        "version":             "1.0.3",
    }


@app.post("/api/admin/settings/test-email")
async def admin_test_email(request: Request, _: dict = Depends(_require_admin_permission("settings"))):
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

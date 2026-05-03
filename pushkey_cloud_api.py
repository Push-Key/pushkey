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
import json
import os
import secrets
import time
from pathlib import Path
from datetime import datetime, timedelta

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
DATA_DIR   = Path(os.environ.get("PUSHKEY_DATA_DIR", "~/.pushkey-cloud")).expanduser()
SECRET_KEY = os.environ.get("PUSHKEY_JWT_SECRET", secrets.token_hex(32))
ALGORITHM  = "HS256"
TOKEN_TTL  = int(os.environ.get("PUSHKEY_TOKEN_TTL_HOURS", "720"))  # 30 days

DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"
VAULTS_DIR = DATA_DIR / "vaults"
VAULTS_DIR.mkdir(exist_ok=True)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer  = HTTPBearer()
app     = FastAPI(title="Pushkey Cloud Sync", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", os.environ.get("ADMIN_ORIGIN", "")],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Admin config ─────────────────────────────────────────────────
LICENSES_FILE = DATA_DIR / "licenses.json"
ADMIN_SECRET  = os.environ.get("PUSHKEY_ADMIN_SECRET", "dev-change-me")
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
    exp = datetime.utcnow() + timedelta(hours=TOKEN_TTL)
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
    body = await request.json()
    email = body.get("email", "").strip().lower()
    pw    = body.get("password", "")
    if not email or not pw or len(pw) < 8:
        raise HTTPException(400, "email and password (>=8 chars) required")
    users = _load_users()
    if email in users:
        raise HTTPException(409, "email already registered")
    users[email] = {"hash": pwd_ctx.hash(pw), "created": datetime.utcnow().isoformat()}
    _save_users(users)
    return {"token": _create_token(email)}

@app.post("/api/v1/auth/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email", "").strip().lower()
    pw    = body.get("password", "")
    users = _load_users()
    user  = users.get(email)
    if not user or not pwd_ctx.verify(pw, user["hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": _create_token(email)}


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
    return {"etag": tag, "size": len(blob), "updated": datetime.utcnow().isoformat()}

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


# ── Admin endpoints ──────────────────────────────────────────────
@app.get("/api/admin/stats")
async def admin_stats(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week  = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).isoformat()
    yesterday = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).isoformat()
    active     = [v for v in lic.values() if v["status"] == "active"]
    new_today  = sum(1 for v in lic.values() if v.get("activated", "") >= today)
    yesterday_new = sum(1 for v in lic.values() if yesterday <= v.get("activated", "") < today)
    return {
        "total":        len(lic),
        "total_active": len(active),
        "new_today":    new_today,
        "pro_team":     sum(1 for v in active if v["tier"] in ("pro", "team")),
        "revoked":      sum(1 for v in lic.values() if v["status"] == "revoked"),
        "week_delta":   sum(1 for v in lic.values() if v.get("activated", "") >= week),
        "today_delta":  new_today - yesterday_new,
    }


@app.get("/api/admin/licenses")
async def admin_list_licenses(_: None = Depends(_require_admin)):
    return list(_load_licenses().values())


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
        "activated":      datetime.utcnow().isoformat(),
        "last_heartbeat": None,
        "status":         "active",
        "notes":          body.get("notes", ""),
    }
    lic[key] = entry
    _save_licenses(lic)
    return entry


@app.post("/api/admin/licenses/{key}/expire")
async def admin_expire(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "expired"
    _save_licenses(lic)
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/revoke")
async def admin_revoke(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "revoked"
    lic[key]["last_heartbeat"] = None
    _save_licenses(lic)
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/renew")
async def admin_renew(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "active"
    _save_licenses(lic)
    return {"ok": True}


@app.get("/api/admin/export")
async def admin_export(_: None = Depends(_require_admin)):
    import csv, io
    lic = _load_licenses()
    out = io.StringIO()
    fields = ["key", "tier", "email", "platform", "activated", "last_heartbeat", "status", "notes"]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(lic.values())
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=licenses.csv"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
PushKey License Activation Server
==================================
Tracks device registrations per license key.
Enforces max_devices per tier server-side.

Endpoints:
  POST /v1/activate    — register this machine against a license key
  POST /v1/deactivate  — remove this machine's registration
  POST /v1/heartbeat   — refresh token (called every 24h by client)
  GET  /v1/health      — uptime check

Deploy: Railway / Fly.io / any Python host
Env vars required:
  SERVER_SECRET  — random string, sign tokens (generate once, never change)
  ADMIN_SECRET   — for /admin endpoints (optional, set to enable)
"""

import os, json, hashlib, hmac, sqlite3, secrets
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

SERVER_SECRET = os.environ.get("SERVER_SECRET", "")
ADMIN_SECRET  = os.environ.get("ADMIN_SECRET", "")
DB_PATH       = os.environ.get("DB_PATH", "activations.db")

if not SERVER_SECRET:
    raise RuntimeError("SERVER_SECRET env var must be set")

TOKEN_TTL_DAYS   = 7
_GRACE_DAYS      = 3   # extra days after token expiry before client downgrades

# ── Tier definitions (mirrors pushkey.py) ────────────────────────────────────

TIERS = {
    "free":       {"max_devices": 1},
    "starter":    {"max_devices": 1},
    "pro":        {"max_devices": 3},
    "team":       {"max_devices": 5},
    "enterprise": {"max_devices": None},  # unlimited
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS activations (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash           TEXT    NOT NULL,
            fingerprint        TEXT    NOT NULL,
            tier               TEXT    NOT NULL,
            max_devices        INTEGER,
            platform           TEXT,
            email              TEXT,
            activated_at       TEXT    NOT NULL,
            last_seen          TEXT    NOT NULL,
            agent_token_count  INTEGER DEFAULT 0,
            UNIQUE(key_hash, fingerprint)
        );
        CREATE TABLE IF NOT EXISTS revoked_keys (
            key_hash  TEXT PRIMARY KEY,
            reason    TEXT,
            revoked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_key_hash ON activations(key_hash);
    """)
    # Non-destructive migration for existing DBs
    try:
        db.execute("ALTER TABLE activations ADD COLUMN agent_token_count INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass  # column already exists
    db.commit()
    db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="PushKey License Server", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Token helpers ─────────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    return hmac.new(SERVER_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

def issue_token(key_hash: str, fingerprint: str, tier: str) -> str:
    expires = (datetime.utcnow() + timedelta(days=TOKEN_TTL_DAYS)).isoformat()
    payload = f"{key_hash}|{fingerprint}|{tier}|{expires}"
    sig     = _sign(payload)
    import base64
    raw = json.dumps({"kh": key_hash, "fp": fingerprint, "tier": tier, "exp": expires, "sig": sig})
    return base64.b64encode(raw.encode()).decode()

def verify_token(token: str) -> dict | None:
    try:
        import base64
        raw  = base64.b64decode(token.encode()).decode()
        data = json.loads(raw)
        payload  = f"{data['kh']}|{data['fp']}|{data['tier']}|{data['exp']}"
        expected = _sign(payload)
        if not hmac.compare_digest(data["sig"], expected):
            return None
        if datetime.utcnow() > datetime.fromisoformat(data["exp"]):
            return None
        return data
    except Exception:
        return None

def _hash_key(license_key: str) -> str:
    return hashlib.sha256(license_key.strip().upper().encode()).hexdigest()

def _now() -> str:
    return datetime.utcnow().isoformat()

# ── Request / Response models ─────────────────────────────────────────────────

class ActivateRequest(BaseModel):
    license_key: str
    fingerprint: str
    tier:        str
    platform:    str = ""
    email:       str = ""

class DeactivateRequest(BaseModel):
    license_key: str
    fingerprint: str

class HeartbeatRequest(BaseModel):
    license_key:       str
    fingerprint:       str
    token:             str
    agent_token_count: int = 0
    version:           str = ""
    platform:          str = ""

class RevokeRequest(BaseModel):
    license_key: str
    reason:      str = ""

# ── Admin guard ───────────────────────────────────────────────────────────────

def require_admin(x_admin_secret: str = Header(default="")):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/v1/health")
def health():
    return {"ok": True, "ts": _now()}


@app.post("/v1/activate")
def activate(req: ActivateRequest):
    # Normalise + validate tier
    tier = req.tier.lower()
    if tier not in TIERS:
        raise HTTPException(400, f"Unknown tier: {tier}")

    max_dev = TIERS[tier]["max_devices"]  # server is authoritative, ignore client value
    key_hash = _hash_key(req.license_key)

    db = get_db()
    try:
        # Check revocation
        if db.execute("SELECT 1 FROM revoked_keys WHERE key_hash=?", [key_hash]).fetchone():
            return {"ok": False, "error": "License key has been revoked. Contact support."}

        # Count existing devices for this key
        rows = db.execute(
            "SELECT fingerprint FROM activations WHERE key_hash=?", [key_hash]
        ).fetchall()
        existing_fps = {r["fingerprint"] for r in rows}

        if req.fingerprint not in existing_fps:
            if max_dev is not None and len(existing_fps) >= max_dev:
                return {
                    "ok": False,
                    "error": (
                        f"Device limit reached ({max_dev} device{'s' if max_dev != 1 else ''} "
                        f"for {tier.title()} plan). Deactivate another device first, "
                        f"or upgrade to Pro for more devices."
                    ),
                    "devices_used": len(existing_fps),
                    "devices_max": max_dev,
                }

            # Register new device
            db.execute(
                """INSERT INTO activations
                   (key_hash, fingerprint, tier, max_devices, platform, email, activated_at, last_seen)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [key_hash, req.fingerprint, tier, max_dev, req.platform, req.email, _now(), _now()],
            )
        else:
            # Already registered — just refresh last_seen + tier (handles upgrades)
            db.execute(
                "UPDATE activations SET last_seen=?, tier=? WHERE key_hash=? AND fingerprint=?",
                [_now(), tier, key_hash, req.fingerprint],
            )

        db.commit()
        token = issue_token(key_hash, req.fingerprint, tier)
        return {
            "ok": True,
            "token": token,
            "tier": tier,
            "devices_used": len(existing_fps) + (0 if req.fingerprint in existing_fps else 1),
            "devices_max": max_dev,
        }
    finally:
        db.close()


@app.post("/v1/deactivate")
def deactivate(req: DeactivateRequest):
    key_hash = _hash_key(req.license_key)
    db = get_db()
    try:
        db.execute(
            "DELETE FROM activations WHERE key_hash=? AND fingerprint=?",
            [key_hash, req.fingerprint],
        )
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/v1/heartbeat")
def heartbeat(req: HeartbeatRequest):
    key_hash = _hash_key(req.license_key)
    db = get_db()
    try:
        # Check revocation
        if db.execute("SELECT 1 FROM revoked_keys WHERE key_hash=?", [key_hash]).fetchone():
            return {"ok": False, "error": "License revoked."}

        row = db.execute(
            "SELECT tier FROM activations WHERE key_hash=? AND fingerprint=?",
            [key_hash, req.fingerprint],
        ).fetchone()

        if not row:
            return {"ok": False, "error": "Device not registered. Please reactivate your license."}

        db.execute(
            "UPDATE activations SET last_seen=?, agent_token_count=? WHERE key_hash=? AND fingerprint=?",
            [_now(), req.agent_token_count, key_hash, req.fingerprint],
        )
        db.commit()

        token = issue_token(key_hash, req.fingerprint, row["tier"])
        return {"ok": True, "token": token, "tier": row["tier"]}
    finally:
        db.close()


# ── Admin endpoints ────────────────────────────────────────────────────────────

@app.get("/admin/activations", dependencies=[Depends(require_admin)])
def list_activations(key_hash: str = ""):
    db = get_db()
    try:
        if key_hash:
            rows = db.execute("SELECT * FROM activations WHERE key_hash=?", [key_hash]).fetchall()
        else:
            rows = db.execute("SELECT * FROM activations ORDER BY activated_at DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.post("/admin/revoke", dependencies=[Depends(require_admin)])
def revoke_key(req: RevokeRequest):
    key_hash = _hash_key(req.license_key)
    db = get_db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO revoked_keys (key_hash, reason, revoked_at) VALUES (?,?,?)",
            [key_hash, req.reason, _now()],
        )
        # Remove all device registrations for this key
        db.execute("DELETE FROM activations WHERE key_hash=?", [key_hash])
        db.commit()
        return {"ok": True, "revoked": key_hash}
    finally:
        db.close()


@app.delete("/admin/deactivate-all/{key_hash}", dependencies=[Depends(require_admin)])
def admin_deactivate_all(key_hash: str):
    db = get_db()
    try:
        db.execute("DELETE FROM activations WHERE key_hash=?", [key_hash])
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Local dev entry ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)

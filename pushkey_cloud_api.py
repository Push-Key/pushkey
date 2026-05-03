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


# ── Event log (append-only JSONL for analytics) ──────────────────
EVENTS_FILE = DATA_DIR / "events.jsonl"

def _log_event(event_type: str, data: dict) -> None:
    entry = {"ts": datetime.utcnow().isoformat(), "type": event_type, **data}
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


# ── Client-facing heartbeat ──────────────────────────────────────
async def _handle_heartbeat(body: dict) -> dict:
    """Shared logic for both /v1/heartbeat and /api/v1/heartbeat."""
    import platform as _pl
    key = body.get("license_key", "").strip().upper()
    # Accept platform from body, or auto-detect if missing
    platform = body.get("platform", "") or f"{_pl.system()} {_pl.release()}"
    version  = body.get("version", "")

    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")

    entry = lic[key]
    if entry["status"] == "revoked":
        raise HTTPException(403, "License revoked")

    entry["last_heartbeat"] = datetime.utcnow().isoformat()
    entry["platform"] = platform
    _save_licenses(lic)

    _log_event("heartbeat", {"key": key[:8] + "…", "tier": entry["tier"], "platform": platform, "version": version})

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


def _send_invite_email(to_email: str, name: str, tier: str, key: str, expires_at: str | None) -> dict:
    if not SMTP_HOST:
        return {"sent": False, "reason": "smtp_not_configured"}
    import smtplib
    from email.mime.text import MIMEText

    display_name = name or to_email.split("@")[0]
    tier_label   = tier.capitalize()
    expiry_line  = f"\nThis key expires on {expires_at[:10]}.\n" if expires_at else ""

    plain = f"""Hi {display_name},

Here's your Pushkey {tier_label} license key:

  {key}

To activate:
1. Download Pushkey: {APP_URL}/download
2. Open Settings → License
3. Enter your key
{expiry_line}
Questions? Reply to this email.
"""
    msg = MIMEText(plain, "plain")
    msg["Subject"] = f"Your Pushkey {tier_label} access key"
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        return {"sent": True}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}


def _auto_expire(lic: dict) -> bool:
    """Set status=expired for any record past its expires_at. Returns True if any changed."""
    now = datetime.utcnow().isoformat()
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
        "activated":      datetime.utcnow().isoformat(),
        "last_heartbeat": None,
        "status":         "active",
        "notes":          body.get("notes", ""),
    }
    lic[key] = entry
    _save_licenses(lic)
    _log_event("activated", {"key": key[:8] + "…", "tier": tier, "email": entry["email"]})
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
        expires_at = (datetime.utcnow() + timedelta(days=trial_days)).isoformat()

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
        "activated":      datetime.utcnow().isoformat(),
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

    today = datetime.utcnow().date().isoformat()
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
    for entry in matched:
        for field in allowed:
            if field in body:
                entry[field] = body[field]
    _save_licenses(lic)
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
    return result


@app.post("/api/admin/licenses/{key}/expire")
async def admin_expire(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "expired"
    _save_licenses(lic)
    _log_event("expired", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
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
    return {"ok": True}


@app.post("/api/admin/licenses/{key}/renew")
async def admin_renew(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    lic[key]["status"] = "active"
    _save_licenses(lic)
    _log_event("renewed", {"key": key[:8] + "…", "tier": lic[key]["tier"]})
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
    now = datetime.utcnow()

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

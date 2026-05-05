"""
Pushkey — local-only HTTP API consumed by the bundled Next.js web app.

Bound to 127.0.0.1, gated by a per-launch bearer token (PUSHKEY_LAUNCH_TOKEN
env or auto-generated), with strict Origin pinning. Vault key lives in process
memory only; never persisted, never returned over the wire. Idle autolock
zeroes the in-memory key.

Phase 1: status / unlock / lock / keys (list + reveal).
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import json

import pushkey_shared as _s
from pushkey_crypto import _V3_MAGIC, _deserialize_vault, _migrate_vault, decrypt_data_v3
from pushkey_vault import load_vault


AUTOLOCK_SECONDS_DEFAULT = 15 * 60


class UnlockBody(BaseModel):
    password: Optional[str] = None
    recovery_code: Optional[str] = None


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


class _Session:
    """In-memory vault state. One process = one session."""
    def __init__(self) -> None:
        self.vault: Optional[dict] = None
        self.vault_key: Optional[bytes] = None
        self.password: Optional[str] = None
        self.unlocked_at: float = 0.0
        self.last_activity: float = 0.0
        self.autolock_seconds: int = AUTOLOCK_SECONDS_DEFAULT

    @property
    def locked(self) -> bool:
        if self.vault is None:
            return True
        if self.autolock_seconds and (time.time() - self.last_activity) > self.autolock_seconds:
            self.lock()
            return True
        return False

    def unlock(self, vault: dict, vault_key: Optional[bytes], password: str) -> None:
        self.vault = vault
        self.vault_key = vault_key
        self.password = password
        now = time.time()
        self.unlocked_at = now
        self.last_activity = now

    def touch(self) -> None:
        self.last_activity = time.time()

    def lock(self) -> None:
        self.vault = None
        self.vault_key = None
        self.password = None
        self.unlocked_at = 0.0


def _load_with_recovery(recovery_code: str) -> tuple:
    """Decrypt V3 vault using recovery code. Returns (vault_dict, vault_key) or (None, None)."""
    if not _s.VAULT_FILE.exists():
        return {}, None
    raw = _s.VAULT_FILE.read_bytes()
    if not raw.startswith(_V3_MAGIC):
        return None, None
    try:
        plaintext, vault_key = decrypt_data_v3(raw, recovery_code=recovery_code)
        data = _migrate_vault(json.loads(plaintext))
        return _deserialize_vault(data), vault_key
    except ValueError:
        return None, None


def _resolve_token() -> str:
    tok = os.environ.get("PUSHKEY_LAUNCH_TOKEN")
    if not tok:
        tok = _gen_token()
        os.environ["PUSHKEY_LAUNCH_TOKEN"] = tok
    return tok


def _resolve_port() -> int:
    return int(os.environ.get("PUSHKEY_LOCAL_PORT", "0") or 0)


def create_app() -> FastAPI:
    app = FastAPI(title="Pushkey Local API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = _resolve_token()
    app.state.session = _Session()

    port = _resolve_port()
    allowed_origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"] if port else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or ["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def require_token(authorization: str = Header(default="")) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
        provided = authorization[7:].strip()
        if not secrets.compare_digest(provided, app.state.token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    def require_unlocked() -> _Session:
        sess: _Session = app.state.session
        if sess.locked:
            raise HTTPException(status.HTTP_423_LOCKED, "vault locked")
        sess.touch()
        return sess

    @app.middleware("http")
    async def origin_pin(request: Request, call_next):
        # Reject cross-origin browser requests outright. CLI/curl have no Origin and pass.
        origin = request.headers.get("origin")
        if origin and not (origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")):
            return _json_error(403, "forbidden origin")
        return await call_next(request)

    # ── routes ───────────────────────────────────────────────────────────────

    @app.get("/api/status")
    def get_status(_: None = Depends(require_token)):
        sess: _Session = app.state.session
        has_vault = _s.VAULT_FILE.exists()
        return {
            "locked": sess.locked,
            "has_vault": has_vault,
            "vault_schema": _s.VAULT_SCHEMA_VERSION,
            "key_count": 0 if sess.locked or not sess.vault else len(sess.vault),
            "autolock_seconds": sess.autolock_seconds,
            "idle_seconds": int(time.time() - sess.last_activity) if sess.last_activity else 0,
        }

    @app.post("/api/unlock")
    def post_unlock(body: UnlockBody = Body(default_factory=UnlockBody), _: None = Depends(require_token)):
        if not body.password and not body.recovery_code:
            raise HTTPException(400, "password or recovery_code required")
        sess: _Session = app.state.session
        try:
            if body.password:
                vault, vault_key = load_vault(body.password)
                secret = body.password
            else:
                vault, vault_key = _load_with_recovery(body.recovery_code or "")
                secret = body.recovery_code
        except ValueError as e:
            raise HTTPException(500, f"vault error: {e}")
        if vault is None:
            raise HTTPException(401, "invalid credentials")
        sess.unlock(vault, vault_key, secret)
        return {"locked": False, "key_count": len(vault)}

    @app.post("/api/lock")
    def post_lock(_: None = Depends(require_token)):
        app.state.session.lock()
        return {"locked": True}

    @app.get("/api/keys")
    def list_keys(sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        out = []
        for name, data in sess.vault.items():
            if name.startswith("_"):
                continue
            if not isinstance(data, dict):
                continue
            out.append({
                "name": name,
                "env": data.get("env", "all"),
                "rotated": data.get("rotated"),
                "added": data.get("added"),
                "provider": data.get("provider"),
                "dual_rotation": bool(data.get("dual_rotation")),
                "has_backup": bool(data.get("next_value")),
                "history_count": len(data.get("history", []) or []),
                "team_role": data.get("team_role"),
                "masked": _mask(data.get("value", "")),
            })
        return {"keys": out, "count": len(out)}

    @app.get("/api/keys/{name}")
    def reveal_key(name: str, sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        data = sess.vault[name]
        if not isinstance(data, dict):
            raise HTTPException(404, "key not found")
        return {
            "name": name,
            "value": data.get("value", ""),
            "env": data.get("env", "all"),
            "rotated": data.get("rotated"),
            "added": data.get("added"),
            "provider": data.get("provider"),
            "dual_rotation": bool(data.get("dual_rotation")),
            "next_value": data.get("next_value"),
            "next_added": data.get("next_added"),
            "history": data.get("history", []) or [],
        }

    return app


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


def _json_error(code: int, msg: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=code, content={"detail": msg})


app = create_app()


def main() -> None:
    import uvicorn
    port = _resolve_port() or 0
    token = app.state.token
    print(f"[pushkey] local API ready  token={token}  port={port or 'auto'}")
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

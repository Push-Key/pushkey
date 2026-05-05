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


class KeyCreate(BaseModel):
    name: str
    value: str
    provider: Optional[str] = None
    env: str = "dev"
    notes: str = ""
    overwrite: bool = False


class KeyUpdate(BaseModel):
    provider: Optional[str] = None
    env: Optional[str] = None
    notes: Optional[str] = None


class RotateBody(BaseModel):
    new_value: str


class BackupBody(BaseModel):
    backup_value: str


class ProjectCreate(BaseModel):
    path: str
    name: Optional[str] = None


class ProjectAssign(BaseModel):
    keys: list[str]


class InjectBody(BaseModel):
    keys: Optional[list[str]] = None
    env: str = "all"


class ProviderDetect(BaseModel):
    name: str
    value: str = ""


class AgentCreate(BaseModel):
    name: str
    scopes: list[str]


class InitBody(BaseModel):
    password: str
    recovery_code: Optional[str] = None


class AddRecoveryBody(BaseModel):
    password: str


class RekeyBody(BaseModel):
    recovery_code: str
    new_password: str


class ImportBody(BaseModel):
    blob_b64: str


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


def _gen_recovery_code() -> str:
    """PUSH-XXXX-XXXX-XXXX-XXXX (Crockford-style alphabet, no I/L/O/U)."""
    alphabet = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "PUSH-" + "-".join(parts)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


class _Session:
    """In-memory vault state. One process = one session."""
    def __init__(self) -> None:
        self.vault: Optional[dict] = None
        self.vault_key: Optional[bytes] = None
        self.password: Optional[str] = None
        self.auth_method: str = "none"  # 'password' | 'recovery' | 'agent_token'
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

    @property
    def can_write(self) -> bool:
        return (not self.locked) and self.auth_method == "password"

    def unlock(self, vault: dict, vault_key: Optional[bytes], password: str, *, method: str) -> None:
        self.vault = vault
        self.vault_key = vault_key
        self.password = password
        self.auth_method = method
        now = time.time()
        self.unlocked_at = now
        self.last_activity = now

    def touch(self) -> None:
        self.last_activity = time.time()

    def lock(self) -> None:
        self.vault = None
        self.vault_key = None
        self.password = None
        self.auth_method = "none"
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


def _static_dir() -> Optional[str]:
    """Resolve the bundled web-app/out/ directory if present (dev or PyInstaller)."""
    from pathlib import Path
    candidates = [
        Path(__file__).parent / "web-app" / "out",
        Path(getattr(__import__("sys"), "_MEIPASS", "")) / "web-app" / "out" if hasattr(__import__("sys"), "_MEIPASS") else None,
    ]
    for c in candidates:
        if c and c.is_dir() and (c / "index.html").exists():
            return str(c)
    return None


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
            "auth_method": sess.auth_method,
            "can_write": sess.can_write,
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
        method = "password" if body.password else "recovery"
        sess.unlock(vault, vault_key, secret, method=method)
        return {"locked": False, "key_count": len(vault), "can_write": sess.can_write, "auth_method": method}

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
            "projects": data.get("projects", []) or [],
            "notes": data.get("notes", ""),
        }

    # ── Phase 2: write ops ────────────────────────────────────────────────

    def require_writable(sess: _Session = Depends(require_unlocked)) -> _Session:
        if not sess.can_write:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "write requires master-password unlock")
        return sess

    def _save(sess: _Session) -> None:
        from pushkey_vault import save_vault as _save_vault
        _save_vault(sess.vault, sess.password, vault_key=sess.vault_key)

    def _now_date() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    @app.post("/api/keys", status_code=201)
    def create_key(body: KeyCreate, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        import pushkey_providers as _prov
        if body.name.startswith("_"):
            raise HTTPException(400, "key names cannot start with '_'")
        if body.name in sess.vault and not body.overwrite:
            raise HTTPException(409, f"key '{body.name}' exists; pass overwrite=true to replace")
        provider = body.provider or _prov.detect_provider(body.name, body.value) or "Unknown"
        now = _now_date()
        sess.vault[body.name] = {
            "value": body.value,
            "created": now,
            "rotated": now,
            "provider": provider,
            "env": body.env,
            "projects": [],
            "notes": body.notes,
        }
        _save(sess)
        return {"name": body.name, "provider": provider, "env": body.env}

    @app.patch("/api/keys/{name}")
    def update_key(name: str, body: KeyUpdate, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        entry = sess.vault[name]
        if body.provider is not None:
            entry["provider"] = body.provider
        if body.env is not None:
            entry["env"] = body.env
        if body.notes is not None:
            entry["notes"] = body.notes
        _save(sess)
        return {"name": name, "provider": entry.get("provider"), "env": entry.get("env"), "notes": entry.get("notes", "")}

    @app.delete("/api/keys/{name}", status_code=204)
    def delete_key(name: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        del sess.vault[name]
        _save(sess)

    @app.post("/api/keys/{name}/rotate")
    def rotate_key(name: str, body: RotateBody, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        entry = sess.vault[name]
        old_val = entry.get("value", "")
        entry.setdefault("history", []).insert(0, {"value": old_val, "retired": _now_date()})
        entry["history"] = entry["history"][:10]
        entry["value"] = body.new_value
        entry["rotated"] = _now_date()
        _save(sess)
        return {"name": name, "rotated": entry["rotated"], "history_count": len(entry["history"])}

    @app.post("/api/keys/{name}/backup")
    def set_backup(name: str, body: BackupBody, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        entry = sess.vault[name]
        entry["next_value"] = body.backup_value
        entry["next_added"] = _now_date()
        entry["dual_rotation"] = True
        _save(sess)
        import pushkey_providers as _prov
        prov_supports = _prov.provider_supports_multi_key(entry.get("provider", ""))
        return {"name": name, "next_added": entry["next_added"], "dual_rotation": True, "provider_supports_multi_key": prov_supports}

    @app.post("/api/keys/{name}/promote")
    def promote_backup(name: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        entry = sess.vault[name]
        if not entry.get("next_value"):
            raise HTTPException(400, "no backup key staged")
        old_val = entry.get("value", "")
        entry.setdefault("history", []).insert(0, {"value": old_val, "retired": _now_date()})
        entry["history"] = entry["history"][:10]
        entry["value"] = entry["next_value"]
        entry["rotated"] = _now_date()
        entry["next_value"] = None
        entry["next_added"] = None
        _save(sess)
        return {"name": name, "rotated": entry["rotated"]}

    # ── projects ──────────────────────────────────────────────────────────

    @app.get("/api/projects")
    def list_projects(sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        from pushkey_vault import load_config
        cfg = load_config()
        projects = cfg.get("projects", {})
        result = []
        for path, meta in projects.items():
            assigned = [n for n, m in sess.vault.items()
                        if isinstance(m, dict) and path in (m.get("projects") or [])]
            result.append({
                "path": path,
                "name": meta.get("name", path.split("/")[-1].split("\\")[-1]),
                "keys": assigned,
                "created": meta.get("created"),
            })
        return {"projects": result, "count": len(result)}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        from pushkey_vault import load_config, save_config
        cfg = load_config()
        cfg.setdefault("projects", {})
        if body.path in cfg["projects"]:
            raise HTTPException(409, "project exists")
        cfg["projects"][body.path] = {
            "name": body.name or body.path.rstrip("/\\").split("/")[-1].split("\\")[-1],
            "created": _now_date(),
        }
        save_config(cfg)
        return {"path": body.path, "name": cfg["projects"][body.path]["name"]}

    @app.delete("/api/projects", status_code=204)
    def delete_project(path: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        from pushkey_vault import load_config, save_config
        cfg = load_config()
        if path not in cfg.get("projects", {}):
            raise HTTPException(404, "project not found")
        del cfg["projects"][path]
        save_config(cfg)
        # cleanup assignments
        for entry in sess.vault.values():
            if isinstance(entry, dict):
                projs = entry.get("projects") or []
                if path in projs:
                    projs.remove(path)
                    entry["projects"] = projs
        _save(sess)

    @app.post("/api/projects/assign")
    def assign_keys(body: ProjectAssign, path: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        from pushkey_vault import load_config
        cfg = load_config()
        if path not in cfg.get("projects", {}):
            raise HTTPException(404, "project not found")
        missing = [k for k in body.keys if k not in sess.vault or not isinstance(sess.vault[k], dict)]
        if missing:
            raise HTTPException(400, f"keys not in vault: {missing}")
        for k in body.keys:
            projs = sess.vault[k].setdefault("projects", [])
            if path not in projs:
                projs.append(path)
        _save(sess)
        return {"path": path, "assigned": body.keys}

    @app.post("/api/projects/unassign")
    def unassign_keys(body: ProjectAssign, path: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        for k in body.keys:
            entry = sess.vault.get(k)
            if isinstance(entry, dict):
                projs = entry.get("projects") or []
                if path in projs:
                    projs.remove(path)
                    entry["projects"] = projs
        _save(sess)
        return {"path": path, "unassigned": body.keys}

    @app.post("/api/projects/inject")
    def inject_project(body: InjectBody, path: str, write: bool = True, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        from pathlib import Path
        from pushkey_vault import load_config
        cfg = load_config()
        if path not in cfg.get("projects", {}):
            raise HTTPException(404, "project not found")
        proj = Path(path)
        if not proj.is_dir():
            raise HTTPException(400, f"directory not found: {path}")

        if body.keys is None:
            keys = [n for n, m in sess.vault.items()
                    if isinstance(m, dict) and path in (m.get("projects") or [])]
        else:
            keys = body.keys
            missing = [k for k in keys if k not in sess.vault]
            if missing:
                raise HTTPException(400, f"keys not in vault: {missing}")

        def env_match(key_env: str) -> bool:
            return body.env == "all" or key_env == "all" or key_env == body.env
        keys = [k for k in keys if env_match(sess.vault[k].get("env", "all"))]

        env_path = proj / ".env"
        existing_lines: list[str] = []
        existing_keys: set[str] = set()
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                existing_lines.append(line)
                if "=" in line and not line.startswith("#"):
                    existing_keys.add(line.split("=", 1)[0].strip())

        new_lines = [f"{k}={sess.vault[k]['value']}" for k in keys if k not in existing_keys]
        skipped = [k for k in keys if k in existing_keys]

        if write:
            all_lines = existing_lines + new_lines
            env_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
            gitignore = proj / ".gitignore"
            content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
            if ".env" not in content.splitlines():
                with open(gitignore, "a", encoding="utf-8") as f:
                    f.write("\n.env\n")
        return {"injected": new_lines, "skipped_existing": skipped, "env_file": str(env_path), "wrote": write}

    # ── providers ─────────────────────────────────────────────────────────

    @app.get("/api/providers")
    def list_providers(_: None = Depends(require_token)):
        import pushkey_providers as _prov
        return {"providers": _prov.PROVIDERS}

    @app.post("/api/providers/detect")
    def detect_provider(body: ProviderDetect, _: None = Depends(require_token)):
        import pushkey_providers as _prov
        prov = _prov.detect_provider(body.name, body.value)
        return {"provider": prov, "multi_key": _prov.provider_supports_multi_key(prov) if prov else None}

    # ── agent tokens ──────────────────────────────────────────────────────

    @app.get("/api/agents")
    def list_agents(sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        import pushkey_agent_tokens as _at
        return {"tokens": _at.list_tokens()}

    @app.post("/api/agents", status_code=201)
    def create_agent(body: AgentCreate, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        import pushkey_agent_tokens as _at
        if sess.vault_key is None:
            raise HTTPException(400, "agent tokens require V3 vault — add a recovery code first")
        ok, val_or_err, token_id = _at.create_token(body.name, body.scopes, sess.vault_key)
        if not ok:
            raise HTTPException(403, val_or_err)
        return {"id": token_id, "token": val_or_err, "name": body.name, "scopes": body.scopes}

    @app.delete("/api/agents/{token_id}", status_code=204)
    def revoke_agent(token_id: str, sess: _Session = Depends(require_writable), _: None = Depends(require_token)):
        import pushkey_agent_tokens as _at
        if not _at.revoke_token(token_id):
            raise HTTPException(404, "token not found")

    # ── Phase 3: advanced ops ────────────────────────────────────────────

    @app.get("/api/health")
    def get_health(threshold_days: int = 90, sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        import pushkey_providers as _prov
        from datetime import datetime
        now = datetime.now()
        stale, healthy, unknown_provider, backup_missing = [], [], [], []
        score_total = 0
        for name, meta in sess.vault.items():
            if name.startswith("_") or not isinstance(meta, dict):
                continue
            rotated_str = meta.get("rotated") or meta.get("created", "")
            try:
                rotated = datetime.fromisoformat(rotated_str)
                age_days = (now - rotated).days
            except Exception:
                age_days = 9999
            status_str = _prov.health_status(meta)
            entry = {"name": name, "provider": meta.get("provider", "Unknown"),
                     "env": meta.get("env", "all"), "age_days": age_days, "status": status_str}
            if status_str == "critical" or age_days >= threshold_days:
                stale.append(entry)
            else:
                healthy.append(entry)
                score_total += 100 if status_str == "healthy" else 60
            if meta.get("provider") in ("Unknown", "", None):
                unknown_provider.append(name)
            if meta.get("dual_rotation") and not meta.get("next_value"):
                backup_missing.append(name)
        total_keys = len(healthy) + len(stale)
        score = int(score_total / max(total_keys, 1))
        return {
            "total": total_keys,
            "healthy": healthy,
            "stale": stale,
            "unknown_provider": unknown_provider,
            "backup_missing": backup_missing,
            "score": score,
            "threshold_days": threshold_days,
        }

    @app.get("/api/forecast")
    def get_forecast(window_days: int = 90, sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        import pushkey_providers as _prov
        from datetime import datetime, timedelta
        now = datetime.now()
        upcoming = []
        for name, meta in sess.vault.items():
            if name.startswith("_") or not isinstance(meta, dict):
                continue
            provider = meta.get("provider", "")
            interval = _prov.PROVIDERS.get(provider, {}).get("rotation_days", 90)
            rotated_str = meta.get("rotated") or meta.get("created", "")
            try:
                rotated = datetime.fromisoformat(rotated_str)
            except Exception:
                continue
            due = rotated + timedelta(days=interval)
            days_left = (due - now).days
            if days_left <= window_days:
                upcoming.append({
                    "name": name,
                    "provider": provider,
                    "env": meta.get("env", "all"),
                    "due_date": due.strftime("%Y-%m-%d"),
                    "days_left": days_left,
                    "overdue": days_left < 0,
                    "has_backup": bool(meta.get("next_value")),
                })
        upcoming.sort(key=lambda x: x["days_left"])
        return {"upcoming": upcoming, "count": len(upcoming), "window_days": window_days}

    @app.get("/api/lifecycle/{name}")
    def get_lifecycle(name: str, sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        import pushkey_providers as _prov
        from datetime import datetime, timedelta
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        entry = sess.vault[name]
        provider = entry.get("provider", "")
        interval = _prov.PROVIDERS.get(provider, {}).get("rotation_days", 90)
        rotated_str = entry.get("rotated") or entry.get("created", "")
        try:
            rotated = datetime.fromisoformat(rotated_str)
            age_days = (datetime.now() - rotated).days
            due = (rotated + timedelta(days=interval)).strftime("%Y-%m-%d")
        except Exception:
            age_days = None
            due = None
        return {
            "name": name,
            "provider": provider,
            "env": entry.get("env", "all"),
            "created": entry.get("created"),
            "rotated": entry.get("rotated"),
            "age_days": age_days,
            "rotation_interval_days": interval,
            "next_due_date": due,
            "status": _prov.health_status(entry),
            "dual_rotation": bool(entry.get("dual_rotation")),
            "next_value_present": bool(entry.get("next_value")),
            "next_added": entry.get("next_added"),
            "history": entry.get("history", []) or [],
            "projects": entry.get("projects", []) or [],
        }

    # ── audit ─────────────────────────────────────────────────────────────

    @app.get("/api/audit")
    def get_audit(limit: int = 200, sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        from pushkey_crypto import _log_decrypt_all
        lines = _log_decrypt_all()
        if limit > 0:
            lines = lines[-limit:]
        return {"events": lines, "count": len(lines)}

    @app.post("/api/audit/log")
    def post_audit(entry: dict = Body(...), sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        from pushkey_crypto import log_event
        msg = entry.get("message", "").strip()
        if not msg:
            raise HTTPException(400, "message required")
        log_event(f"[ui] {msg}")
        return {"logged": True}

    # ── init / recovery / rekey ──────────────────────────────────────────

    @app.post("/api/init")
    def init_vault(body: InitBody, _: None = Depends(require_token)):
        if _s.VAULT_FILE.exists():
            raise HTTPException(409, "vault already exists")
        if len(body.password) < 8:
            raise HTTPException(400, "password must be at least 8 chars")
        recovery = body.recovery_code or _gen_recovery_code()
        from pushkey_crypto import encrypt_data_v3
        import json as _json
        payload = {"_schema": _s.VAULT_SCHEMA_VERSION, "keys": {}}
        blob = encrypt_data_v3(_json.dumps(payload), body.password, recovery)
        _s.ensure_vault_dir()
        _s.VAULT_FILE.write_bytes(blob)
        try:
            os.chmod(_s.VAULT_FILE, 0o600)
        except Exception:
            pass
        return {"created": True, "recovery_code": recovery}

    @app.post("/api/recovery/add")
    def add_recovery(body: AddRecoveryBody, _: None = Depends(require_token)):
        if not _s.VAULT_FILE.exists():
            raise HTTPException(404, "no vault")
        from pushkey_crypto import add_recovery_key
        token = _s.VAULT_FILE.read_bytes()
        recovery = _gen_recovery_code()
        try:
            new_blob = add_recovery_key(token, body.password, recovery)
        except Exception:
            raise HTTPException(401, "wrong password")
        _s.VAULT_FILE.write_bytes(new_blob)
        return {"recovery_code": recovery}

    @app.post("/api/vault/rekey")
    def rekey(body: RekeyBody, _: None = Depends(require_token)):
        if not _s.VAULT_FILE.exists():
            raise HTTPException(404, "no vault")
        if len(body.new_password) < 8:
            raise HTTPException(400, "password must be at least 8 chars")
        from pushkey_crypto import rekey_vault
        token = _s.VAULT_FILE.read_bytes()
        try:
            new_blob = rekey_vault(token, body.recovery_code, body.new_password)
        except Exception:
            raise HTTPException(401, "invalid recovery code")
        _s.VAULT_FILE.write_bytes(new_blob)
        # Force re-unlock
        app.state.session.lock()
        return {"rekeyed": True}

    # ── backup export / import ───────────────────────────────────────────

    @app.post("/api/backup/export")
    def backup_export(sess: _Session = Depends(require_unlocked), _: None = Depends(require_token)):
        if not _s.VAULT_FILE.exists():
            raise HTTPException(404, "no vault")
        import base64
        blob = _s.VAULT_FILE.read_bytes()
        return {
            "format": "pushkey-vault-v3",
            "exported_at": _now_iso(),
            "size_bytes": len(blob),
            "blob_b64": base64.b64encode(blob).decode(),
        }

    @app.post("/api/backup/import")
    def backup_import(body: ImportBody, _: None = Depends(require_token)):
        import base64
        try:
            blob = base64.b64decode(body.blob_b64)
        except Exception:
            raise HTTPException(400, "invalid base64")
        from pushkey_crypto import _V3_MAGIC as _V3
        if not blob.startswith(_V3):
            raise HTTPException(400, "not a v3 vault")
        _s.ensure_vault_dir()
        _s.VAULT_FILE.write_bytes(blob)
        app.state.session.lock()
        return {"imported": True, "bytes": len(blob)}

    # ── cloud (status only — push/pull deferred) ─────────────────────────

    @app.get("/api/cloud/status")
    def cloud_status(_: None = Depends(require_token)):
        from pushkey_tiers import current_tier
        tier = current_tier()
        tier_meta = _s.TIERS.get(tier, {})
        return {
            "tier": tier,
            "cloud_sync_available": bool(tier_meta.get("cloud_sync")),
            "endpoint": _s.ACTIVATION_SERVER,
        }

    # ── Static frontend (bundled web-app/out) ─────────────────────────
    static = _static_dir()
    if static:
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=static, html=True), name="static")

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

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
import asyncio
import threading
import hashlib
import base64
import tempfile
import stat
import copy
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Literal
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import json

import pushkey_shared as _s
from pushkey_crypto import (
    _V3_MAGIC,
    _deserialize_vault,
    _migrate_vault,
    decrypt_data_v3,
    generate_recovery_code,
    VaultAuthenticationError,
    VaultFormatError,
    VaultIntegrityError,
)
from pushkey_env import mutate_env_file, sanitize_env_value
from pushkey_vault import (
    MAX_VAULT_BYTES,
    load_vault,
    load_vault_with_key,
    migrate_vault_to_v3,
    replace_v3_recovery_code,
    rekey_v3_password,
    save_vault,
)


AUTOLOCK_SECONDS_DEFAULT = 15 * 60
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
MAX_HEADER_BYTES = 32 * 1024
MAX_SINGLE_HEADER_BYTES = 8 * 1024
REQUEST_TIMEOUT_SECONDS = 15.0
SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 8
SERVER_IDLE_SECONDS = 60 * 60
LOOPBACK_HOST = "127.0.0.1"
LOCAL_API_VERSION = "1"
from pushkey_web._manifest import EXPECTED_MANIFEST_SHA256, WEB_APP_VERSION


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnlockBody(StrictBody):
    password: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    recovery_code: Optional[str] = Field(default=None, min_length=1, max_length=256)


class KeyCreate(StrictBody):
    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    value: str = Field(min_length=1, max_length=65536)
    provider: Optional[str] = Field(default=None, max_length=128)
    env: Literal["dev", "test", "staging", "prod", "all"] = "dev"
    notes: str = Field(default="", max_length=4096)
    overwrite: bool = False


class KeyUpdate(StrictBody):
    provider: Optional[str] = Field(default=None, max_length=128)
    env: Optional[Literal["dev", "test", "staging", "prod", "all"]] = None
    notes: Optional[str] = Field(default=None, max_length=4096)


class RotateBody(StrictBody):
    new_value: str = Field(min_length=1, max_length=65536)


class BackupBody(StrictBody):
    backup_value: str = Field(min_length=1, max_length=65536)


class ProjectCreate(StrictBody):
    path: str = Field(min_length=1, max_length=4096)
    name: Optional[str] = Field(default=None, max_length=256)


class ProjectAssign(StrictBody):
    keys: list[str] = Field(max_length=512)


class InjectBody(StrictBody):
    keys: Optional[list[str]] = Field(default=None, max_length=512)
    env: Literal["dev", "test", "staging", "prod", "all"] = "all"


class ProviderDetect(StrictBody):
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(default="", max_length=65536)


class AgentCreate(StrictBody):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[Literal["read", "write", "inject", "rotate"]] = Field(min_length=1, max_length=4)


class InitBody(StrictBody):
    password: str = Field(min_length=8, max_length=4096)
    recovery_code: Optional[str] = Field(default=None, max_length=256)


class AddRecoveryBody(StrictBody):
    password: str = Field(min_length=1, max_length=4096)


class RekeyBody(StrictBody):
    recovery_code: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=4096)


class ImportBody(StrictBody):
    blob_b64: str = Field(min_length=1, max_length=3 * 1024 * 1024)


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


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
        self.scopes: list[str] = []  # only meaningful when auth_method == 'agent_token'
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

    def unlock(
        self,
        vault: dict,
        vault_key: Optional[bytes],
        password: Optional[str],
        *,
        method: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        self.vault = vault
        self.vault_key = vault_key
        self.password = password
        self.auth_method = method
        self.scopes = scopes or []
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
        self.scopes = []
        self.unlocked_at = 0.0
        self.last_activity = 0.0


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
        Path(__file__).parent / "pushkey_web" / "out",
    ]
    try:
        from importlib.resources import files
        candidates.append(Path(str(files("pushkey_web").joinpath("out"))))
    except (ImportError, ModuleNotFoundError, TypeError):
        pass
    for c in candidates:
        if c and c.is_dir() and (c / "index.html").exists():
            return str(c)
    return None


def _verify_static_manifest(static: str) -> dict:
    """Fail closed unless every bundled frontend asset matches its SHA-256."""
    root = Path(static)
    manifest_path = root / "pushkey-integrity.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
            raise ValueError("manifest trust anchor mismatch")
        manifest = json.loads(manifest_bytes)
        if manifest.get("web_app_version") != WEB_APP_VERSION:
            raise ValueError("version mismatch")
        expected = manifest["files"]
        actual = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p.name != manifest_path.name
        }
        if actual != set(expected):
            raise ValueError("asset inventory mismatch")
        for relative, digest in expected.items():
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError("invalid digest")
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
                raise ValueError(f"asset digest mismatch: {relative}")
        return manifest
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("bundled web app integrity verification failed") from exc


def _canonical_project_path(raw: str, *, must_exist: bool = True) -> str:
    """Return a canonical absolute project directory, rejecting ambiguous paths."""
    if not raw or "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(400, "invalid project path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, "project path must be absolute")
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError):
        raise HTTPException(400, "invalid project path") from None
    if must_exist and not resolved.is_dir():
        raise HTTPException(400, "project directory not found")
    return str(resolved)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


def _project_identity(project: Path) -> tuple[int, int]:
    info = project.stat()
    return (info.st_dev, info.st_ino)


def _assert_project_target(
    project: Path, registered: str, target: Path, expected_identity: tuple[int, int]
) -> None:
    if _canonical_project_path(str(project)) != registered:
        raise HTTPException(409, "project path changed during write")
    if _is_link_or_reparse(project) or _is_link_or_reparse(target):
        raise HTTPException(400, "refusing link or reparse-point project target")
    if target.parent.resolve(strict=True) != Path(registered):
        raise HTTPException(400, "project target escapes registered directory")
    if _project_identity(project) != expected_identity:
        raise HTTPException(409, "project directory identity changed during write")


def _atomic_project_write(
    registered: str, filename: str, data: bytes, expected_identity: Optional[tuple[int, int]] = None
) -> None:
    """Write a fixed project file without following links or exposing partial data."""
    project = Path(registered)
    target = project / filename
    identity = expected_identity or _project_identity(project)
    _assert_project_target(project, registered, target, identity)
    fd, temporary = tempfile.mkstemp(prefix=f".{filename}.pushkey-", dir=project)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _assert_project_target(project, registered, target, identity)
        if _is_link_or_reparse(temp_path):
            raise HTTPException(409, "temporary project target changed")
        os.replace(temp_path, target)
        _assert_project_target(project, registered, target, identity)
        try:
            directory_fd = os.open(
                str(project),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp_path.unlink(missing_ok=True)


def _canonicalize_registered_projects(cfg: dict, vault: Optional[dict] = None) -> bool:
    """Migrate legacy project keys to canonical paths without creating new access."""
    projects = cfg.get("projects", {})
    if not isinstance(projects, dict):
        return False
    changed = False
    migrated: dict = {}
    replacements: dict[str, str] = {}
    for raw, meta in projects.items():
        try:
            canonical = _canonical_project_path(raw)
        except HTTPException:
            canonical = raw
        if canonical in migrated:
            raise HTTPException(409, "canonical project path collision")
        migrated[canonical] = meta
        if canonical != raw:
            replacements[raw] = canonical
            changed = True
    if changed:
        cfg["projects"] = migrated
        if vault:
            for entry in vault.values():
                if not isinstance(entry, dict):
                    continue
                assigned = entry.get("projects")
                if isinstance(assigned, list):
                    entry["projects"] = [replacements.get(item, item) for item in assigned]
    return changed


def _allowed_authorities(port: int) -> set[str]:
    if not port:
        # TestClient has no bound socket; explicit test authorities only.
        return {"testserver", "127.0.0.1:5173"}
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.started_at = time.monotonic()
    try:
        yield
    finally:
        app.state.session.lock()
        app.state.sessions.clear()
        app.state.bootstrap_token = None


def create_app() -> FastAPI:
    app = FastAPI(title="Pushkey Local API", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=_lifespan)
    app.state.bootstrap_token = _resolve_token()
    # Compatibility attribute for callers that inspect it; never log this value.
    app.state.token = app.state.bootstrap_token
    app.state.sessions: dict[str, dict[str, float]] = {}
    app.state.auth_lock = threading.RLock()
    app.state.project_lock = threading.RLock()
    app.state.session = _Session()
    app.state.last_http_activity = time.monotonic()
    app.state.csp = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "style-src-attr 'none'; frame-ancestors 'none'; base-uri 'none'"
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Never echo Pydantic's rejected input: it may contain a password/key.
        fields = [
            ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            for error in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"detail": "invalid request", "fields": fields})

    port = _resolve_port()
    allowed_origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"] if port else ["http://testserver"]
    allowed_authorities = _allowed_authorities(port)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or ["http://127.0.0.1", "http://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=0,
    )

    def require_token(authorization: str = Header(default="")) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
        provided = authorization[7:].strip()
        now = time.monotonic()
        with app.state.auth_lock:
            record = app.state.sessions.get(provided)
            if record and record["idle_expires"] > now and record["absolute_expires"] > now:
                record["idle_expires"] = min(now + SESSION_IDLE_SECONDS, record["absolute_expires"])
                return
            if record is not None:
                app.state.sessions.pop(provided, None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer")

    def require_unlocked() -> _Session:
        sess: _Session = app.state.session
        if sess.locked:
            raise HTTPException(status.HTTP_423_LOCKED, "vault locked")
        sess.touch()
        return sess

    def require_scope(scope: str):
        """Dependency factory gating an endpoint by agent-token scope.

        Password and recovery sessions are unaffected: read passes for either
        (matching require_unlocked's existing behavior), and write/inject both
        still require can_write (password-only), exactly like require_writable
        today -- an agent token is the only auth method this actually narrows.
        Mirrors pushkey_mcp.py's _require_scope so MCP, CLI, and the local API
        enforce the same scope-to-operation mapping.
        """
        def _check(sess: _Session = Depends(require_unlocked)) -> _Session:
            if sess.auth_method == "agent_token":
                if scope not in sess.scopes:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN, f"agent token missing required scope: {scope}"
                    )
                return sess
            if scope == "read":
                return sess
            if not sess.can_write:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "write requires master-password unlock")
            return sess
        return _check

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        raw_headers = request.scope.get("headers", ())
        if (
            sum(len(name) + len(value) for name, value in raw_headers) > MAX_HEADER_BYTES
            or any(len(name) + len(value) > MAX_SINGLE_HEADER_BYTES for name, value in raw_headers)
        ):
            return _json_error(431, "request headers too large")
        host = request.headers.get("host", "")
        if host not in allowed_authorities:
            return _json_error(400, "invalid host")
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            origin_authority = parsed.netloc
            if parsed.scheme != "http" or origin_authority not in allowed_authorities or parsed.path not in ("", "/"):
                return _json_error(403, "forbidden origin")
        if request.method not in {"GET", "HEAD", "OPTIONS", "POST", "PATCH", "DELETE"}:
            return _json_error(405, "method not allowed")
        content_length = request.headers.get("content-length")
        try:
            if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
                return _json_error(413, "request body too large")
        except ValueError:
            return _json_error(400, "invalid content-length")
        if request.method in {"POST", "PATCH"}:
            try:
                body = await asyncio.wait_for(request.body(), timeout=REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                return _json_error(408, "request body timed out")
            if len(body) > MAX_REQUEST_BODY_BYTES:
                return _json_error(413, "request body too large")
        try:
            response = await call_next(request)
        except Exception:
            raise
        if request.url.path != "/healthz":
            app.state.last_http_activity = time.monotonic()
        response.headers.update({
            "Cache-Control": "no-store",
            "Content-Security-Policy": app.state.csp,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "api_version": LOCAL_API_VERSION}

    @app.post("/api/bootstrap")
    def bootstrap(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer")
        provided = authorization[7:].strip()
        with app.state.auth_lock:
            expected = app.state.bootstrap_token
            if not expected or not secrets.compare_digest(provided, expected):
                raise HTTPException(401, "invalid or consumed bootstrap token")
            app.state.bootstrap_token = None
            app.state.token = None
            if len(app.state.sessions) >= MAX_SESSIONS:
                oldest = min(app.state.sessions, key=lambda token: app.state.sessions[token]["created"])
                app.state.sessions.pop(oldest, None)
            session_token = _gen_token()
            now = time.monotonic()
            app.state.sessions[session_token] = {
                "created": now,
                "idle_expires": now + SESSION_IDLE_SECONDS,
                "absolute_expires": now + SESSION_ABSOLUTE_SECONDS,
            }
        app.state.last_http_activity = now
        return {"token": session_token, "expires_in": SESSION_IDLE_SECONDS}

    @app.post("/api/logout")
    def logout(authorization: str = Header(default=""), _: None = Depends(require_token)):
        token = authorization[7:].strip()
        with app.state.auth_lock:
            app.state.sessions.pop(token, None)
            app.state.session.lock()
        return {"logged_out": True}

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
        if body.password and body.password.startswith("pk_agent_"):
            import pushkey_agent_tokens as _at
            vault_key, scopes, err = _at.authenticate_token(body.password)
            if vault_key is None:
                raise HTTPException(401, err or "invalid or expired agent token")
            vault, vk = load_vault_with_key(vault_key)
            if vault is None:
                raise HTTPException(
                    422, "agent token could not decrypt vault (stale after a master password change?)"
                )
            sess.unlock(vault, vk, None, method="agent_token", scopes=scopes)
            return {
                "locked": False,
                "key_count": len(vault),
                "can_write": sess.can_write,
                "auth_method": "agent_token",
                "scopes": scopes,
            }
        try:
            if body.password:
                vault, vault_key = load_vault(body.password)
                secret = body.password
            else:
                vault, vault_key = _load_with_recovery(body.recovery_code or "")
                secret = body.recovery_code
        except (ValueError, VaultAuthenticationError):
            raise HTTPException(401, "invalid credentials") from None
        except (VaultFormatError, VaultIntegrityError):
            raise HTTPException(422, "vault is corrupted or unsupported") from None
        if vault is None:
            raise HTTPException(401, "invalid credentials")
        method = "password" if body.password else "recovery"
        sess.unlock(vault, vault_key, secret, method=method)
        return {"locked": False, "key_count": len(vault), "can_write": sess.can_write, "auth_method": method}

    @app.post("/api/lock")
    def post_lock(_: None = Depends(require_token)):
        with app.state.auth_lock:
            app.state.session.lock()
            app.state.sessions.clear()
        return {"locked": True}

    @app.get("/api/keys")
    def list_keys(sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
    def reveal_key(name: str, sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
        # Re-import at call time (not the module-level `save_vault` binding) so
        # tests that monkeypatch pushkey_vault.save_vault directly still take
        # effect here. Agent-token sessions never hold the master password
        # (mirrors pushkey_mcp.py's _save_session_vault), so they write
        # through the raw vault-key path instead of the password-reencrypt path.
        import pushkey_vault as _pv
        if sess.password is not None:
            _pv.save_vault(sess.vault, sess.password, vault_key=sess.vault_key)
        else:
            _pv.save_vault_with_key(sess.vault, sess.vault_key)

    def _restore_bytes(path: Path, original: Optional[bytes]) -> None:
        if original is None:
            path.unlink(missing_ok=True)
            return
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.rollback-", dir=path.parent)
        tmp = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _persist_project_state(sess: _Session, mutate, *, save_when=lambda _result: True):
        """Apply a config/vault mutation, rolling our own writes back on failure.

        The vault file is deliberately never restored here. `save_vault` writes
        atomically (temp file + os.replace) and refuses to write when the
        on-disk revision moved out from under the in-memory session
        (VaultConflictError), so a failed `_save` never leaves a partial vault
        and never overwrote the disk. Restoring the pre-request vault snapshot
        would therefore only ever clobber a vault another process (CLI, MCP)
        committed while we held the in-process lock -- the cross-writer secret
        loss this transaction exists to prevent.
        """
        from pushkey_vault import load_config, save_config
        with app.state.project_lock:
            cfg = load_config()
            original_cfg = copy.deepcopy(cfg)
            original_vault = copy.deepcopy(sess.vault)
            cfg_bytes = _s.CONFIG_FILE.read_bytes() if _s.CONFIG_FILE.exists() else None
            config_written = False
            try:
                result = mutate(cfg, sess.vault)
                if save_when(result):
                    save_config(cfg)
                    config_written = True
                    _save(sess)
                return cfg, result
            except Exception:
                sess.vault.clear()
                sess.vault.update(original_vault)
                cfg.clear()
                cfg.update(original_cfg)
                # Only undo the config we actually wrote. `save_config` is also
                # atomic, and _save runs last, so if we never reached it there is
                # nothing on disk to undo.
                if config_written:
                    _restore_bytes(_s.CONFIG_FILE, cfg_bytes)
                raise

    def _now_date() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    @app.post("/api/keys", status_code=201)
    def create_key(body: KeyCreate, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
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
    def update_key(name: str, body: KeyUpdate, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
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
    def delete_key(name: str, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
        if name.startswith("_") or name not in sess.vault:
            raise HTTPException(404, "key not found")
        del sess.vault[name]
        _save(sess)

    @app.post("/api/keys/{name}/rotate")
    def rotate_key(name: str, body: RotateBody, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
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
    def set_backup(name: str, body: BackupBody, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
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
    def promote_backup(name: str, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
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
    def list_projects(sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
        from pushkey_vault import load_config, save_config
        vault_view = sess.vault
        if sess.can_write:
            cfg, _ = _persist_project_state(
                sess,
                lambda current_cfg, current_vault:
                    _canonicalize_registered_projects(current_cfg, current_vault),
                save_when=bool,
            )
        else:
            with app.state.project_lock:
                cfg = copy.deepcopy(load_config())
                vault_view = copy.deepcopy(sess.vault)
            _canonicalize_registered_projects(cfg, vault_view)
        projects = cfg.get("projects", {})
        result = []
        for path, meta in projects.items():
            assigned = [n for n, m in vault_view.items()
                        if isinstance(m, dict) and path in (m.get("projects") or [])]
            result.append({
                "path": path,
                "name": meta.get("name", path.split("/")[-1].split("\\")[-1]),
                "keys": assigned,
                "created": meta.get("created"),
            })
        return {"projects": result, "count": len(result)}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate, sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
        from pushkey_vault import load_config, save_config
        canonical = _canonical_project_path(body.path)
        def mutate_create(current_cfg, current_vault):
            _canonicalize_registered_projects(current_cfg, current_vault)
            current_cfg.setdefault("projects", {})
            if canonical in current_cfg["projects"]:
                raise HTTPException(409, "project exists")
            current_cfg["projects"][canonical] = {
                "name": body.name or Path(canonical).name,
                "created": _now_date(),
            }
        cfg, _ = _persist_project_state(sess, mutate_create)
        return {"path": canonical, "name": cfg["projects"][canonical]["name"]}

    @app.delete("/api/projects", status_code=204)
    def delete_project(path: str = Query(min_length=1, max_length=4096), sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
        from pushkey_vault import load_config, save_config
        path = _canonical_project_path(path)
        def mutate_delete(current_cfg, current_vault):
            _canonicalize_registered_projects(current_cfg, current_vault)
            if path not in current_cfg.get("projects", {}):
                raise HTTPException(404, "project not found")
            del current_cfg["projects"][path]
            for entry in current_vault.values():
                if isinstance(entry, dict):
                    projs = entry.get("projects") or []
                    if path in projs:
                        projs.remove(path)
                        entry["projects"] = projs
        _persist_project_state(sess, mutate_delete)

    @app.post("/api/projects/assign")
    def assign_keys(body: ProjectAssign, path: str = Query(min_length=1, max_length=4096), sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
        from pushkey_vault import load_config
        path = _canonical_project_path(path)
        def mutate_assign(current_cfg, current_vault):
            _canonicalize_registered_projects(current_cfg, current_vault)
            if path not in current_cfg.get("projects", {}):
                raise HTTPException(404, "project not found")
            missing = [k for k in body.keys if k not in current_vault or not isinstance(current_vault[k], dict)]
            if missing:
                raise HTTPException(400, f"keys not in vault: {missing}")
            for key in body.keys:
                projects = current_vault[key].setdefault("projects", [])
                if path not in projects:
                    projects.append(path)
        _persist_project_state(sess, mutate_assign)
        return {"path": path, "assigned": body.keys}

    @app.post("/api/projects/unassign")
    def unassign_keys(body: ProjectAssign, path: str = Query(min_length=1, max_length=4096), sess: _Session = Depends(require_scope("write")), _: None = Depends(require_token)):
        path = _canonical_project_path(path)
        from pushkey_vault import load_config
        def mutate_unassign(current_cfg, current_vault):
            _canonicalize_registered_projects(current_cfg, current_vault)
            if path not in current_cfg.get("projects", {}):
                raise HTTPException(404, "project not found")
            for key in body.keys:
                entry = current_vault.get(key)
                if isinstance(entry, dict):
                    projects = entry.get("projects") or []
                    if path in projects:
                        projects.remove(path)
                        entry["projects"] = projects
        _persist_project_state(sess, mutate_unassign)
        return {"path": path, "unassigned": body.keys}

    @app.post("/api/projects/inject")
    def inject_project(body: InjectBody, path: str = Query(min_length=1, max_length=4096), write: bool = True, sess: _Session = Depends(require_scope("inject")), _: None = Depends(require_token)):
        from pushkey_vault import load_config
        path = _canonical_project_path(path)
        cfg, _ = _persist_project_state(
            sess,
            lambda current_cfg, current_vault:
                _canonicalize_registered_projects(current_cfg, current_vault),
            save_when=bool,
        )
        if path not in cfg.get("projects", {}):
            raise HTTPException(404, "project not found")
        proj = Path(path)

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
        if env_path.is_symlink():
            raise HTTPException(400, "refusing to write through .env symlink")
        safe_entries = {
            k: {**sess.vault[k], "value": sanitize_env_value(sess.vault[k]["value"])}
            for k in keys
        }

        identity = _project_identity(proj)
        if write:
            gitignore = proj / ".gitignore"
            _assert_project_target(proj, path, env_path, identity)
            _assert_project_target(proj, path, gitignore, identity)

        def atomic_write(filename: str, data: bytes) -> None:
            _atomic_project_write(path, filename, data, identity)

        result = mutate_env_file(
            proj,
            safe_entries,
            key_names=keys,
            update_existing=False,
            write=write,
            atomic_write=atomic_write if write else None,
        )
        return {
            "injected": result.injected_names,
            "skipped_existing": result.skipped_existing,
            "env_file": result.env_file,
            "wrote": write,
        }

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
    def get_health(threshold_days: int = Query(default=90, ge=1, le=3650), sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
    def get_forecast(window_days: int = Query(default=90, ge=1, le=3650), sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
    def get_lifecycle(name: str, sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
    def get_audit(limit: int = Query(default=200, ge=1, le=1000), sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
        recovery = body.recovery_code or generate_recovery_code()
        save_vault({}, body.password, recovery_code=recovery)
        return {"created": True, "recovery_code": recovery}

    @app.post("/api/recovery/add")
    def add_recovery(body: AddRecoveryBody, _: None = Depends(require_token)):
        if not _s.VAULT_FILE.exists():
            raise HTTPException(404, "no vault")
        recovery = generate_recovery_code()
        try:
            raw = _s.VAULT_FILE.read_bytes()
            if raw.startswith(_V3_MAGIC):
                replace_v3_recovery_code(body.password, recovery)
            else:
                migrate_vault_to_v3(body.password, recovery)
        except VaultAuthenticationError:
            raise HTTPException(401, "wrong password")
        except (VaultFormatError, VaultIntegrityError):
            raise HTTPException(422, "vault cannot be upgraded")
        except OSError:
            raise HTTPException(500, "vault upgrade failed")
        return {"recovery_code": recovery}

    @app.post("/api/vault/rekey")
    def rekey(body: RekeyBody, _: None = Depends(require_token)):
        if not _s.VAULT_FILE.exists():
            raise HTTPException(404, "no vault")
        if len(body.new_password) < 8:
            raise HTTPException(400, "password must be at least 8 chars")
        try:
            rekey_v3_password(body.recovery_code, body.new_password)
        except VaultAuthenticationError:
            raise HTTPException(401, "invalid recovery code")
        except (VaultFormatError, VaultIntegrityError):
            raise HTTPException(422, "vault cannot be rekeyed")
        except OSError:
            raise HTTPException(500, "vault rekey failed")
        # Force re-unlock
        app.state.session.lock()
        return {"rekeyed": True}

    # ── backup export / import ───────────────────────────────────────────

    @app.post("/api/backup/export")
    def backup_export(sess: _Session = Depends(require_scope("read")), _: None = Depends(require_token)):
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
            blob = base64.b64decode(body.blob_b64, validate=True)
        except Exception:
            raise HTTPException(400, "invalid base64")
        from pushkey_crypto import _V3_MAGIC as _V3
        if not blob.startswith(_V3):
            raise HTTPException(400, "not a v3 vault")
        if len(blob) > MAX_VAULT_BYTES:
            raise HTTPException(413, "vault too large")
        if len(blob) < 200:
            raise HTTPException(400, "truncated v3 vault")
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
        manifest = _verify_static_manifest(static)
        script_hashes = " ".join(f"'sha256-{value}'" for value in manifest.get("csp", {}).get("scripts", []))
        style_hashes = " ".join(f"'sha256-{value}'" for value in manifest.get("csp", {}).get("styles", []))
        attr_hashes = " ".join(f"'sha256-{value}'" for value in manifest.get("csp", {}).get("style_attributes", []))
        app.state.csp = (
            f"default-src 'self'; script-src 'self' {script_hashes}; "
            f"style-src 'self' {style_hashes}; style-src-attr 'unsafe-hashes' {attr_hashes}; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
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


def run_server() -> None:
    import uvicorn
    port = _resolve_port() or 0
    if port and not (1 <= port <= 65535):
        raise SystemExit("invalid PUSHKEY_LOCAL_PORT")
    if LOOPBACK_HOST not in {"127.0.0.1", "::1"}:
        raise SystemExit("local API must bind to loopback")
    print(f"[pushkey] local API ready on {LOOPBACK_HOST}:{port or 'auto'}")
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        limit_concurrency=32,
        backlog=32,
        timeout_keep_alive=2,
        timeout_graceful_shutdown=5,
        h11_max_incomplete_event_size=MAX_HEADER_BYTES,
    )
    server = uvicorn.Server(config)
    try:
        parent_pid = int(os.environ.get("PUSHKEY_PARENT_PID", "0") or 0)
        if parent_pid < 0:
            raise ValueError
    except ValueError:
        parent_pid = 0

    def monitor_lifecycle() -> None:
        while not server.should_exit:
            time.sleep(2)
            idle = time.monotonic() - app.state.last_http_activity
            parent_gone = False
            if parent_pid:
                try:
                    os.kill(parent_pid, 0)
                except OSError:
                    parent_gone = True
            if parent_gone or idle > SERVER_IDLE_SECONDS:
                server.should_exit = True

    watcher = threading.Thread(target=monitor_lifecycle, name="pushkey-local-lifecycle", daemon=True)
    watcher.start()
    try:
        server.run()
    finally:
        app.state.session.lock()
        app.state.sessions.clear()
        app.state.bootstrap_token = None


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()

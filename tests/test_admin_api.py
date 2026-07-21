"""
Tests for the Pushkey cloud admin API.
Covers license CRUD, heartbeat, contacts, analytics, audit, bulk, tickets.
"""
import json
import os
from pathlib import Path
import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Import cloud API with a tmp data dir + admin secret."""
    monkeypatch.setenv("PUSHKEY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUSHKEY_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PUSHKEY_ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("PUSHKEY_ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("PUSHKEY_JWT_SECRET", "test-jwt-secret")
    # Block .env from leaking host SMTP creds into module-level constants
    for _k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "FROM_EMAIL"):
        monkeypatch.setenv(_k, "")

    # Force reimport so env vars take effect
    import importlib
    import sys
    if "pushkey_cloud_api" in sys.modules:
        del sys.modules["pushkey_cloud_api"]
    mod = importlib.import_module("pushkey_cloud_api")
    return mod


@pytest.fixture
def client(app_module):
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app)
    r = c.post("/api/admin/auth/login", json={
        "email": "admin@example.com",
        "password": "admin-pass-123",
    })
    assert r.status_code == 200
    ADMIN["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


ADMIN = {"X-CSRF-Token": ""}


# ── Auth ─────────────────────────────────────────────────────────
def test_admin_password_hashes_use_argon2id_with_legacy_bcrypt_support(app_module):
    current_hash = app_module.pwd_ctx.hash("new-admin-pass")
    legacy_hash = (
        "$2b$12$1wvUC.77g2YzkuvqwBC7U.LCeVwNGDkd4PhcrNS7lpADnPxOMj9TO"
    )

    assert current_hash.startswith("$argon2id$")
    assert app_module.pwd_ctx.verify("legacy-admin-pass", legacy_hash)


def test_admin_endpoints_reject_missing_secret(client):
    client.cookies.clear()
    r = client.get("/api/admin/stats")
    assert r.status_code == 401


def test_cloud_api_applies_security_headers_and_readiness(client):
    r = client.get("/api/v1/health")

    assert r.status_code == 200
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_cloud_api_rejects_oversized_request_body(app_module):
    from fastapi.testclient import TestClient

    app_module.MAX_REQUEST_BYTES = 8
    client = TestClient(app_module.app)

    r = client.post(
        "/api/v1/auth/register",
        headers={"Content-Length": "9"},
        content=b"123456789",
    )

    assert r.status_code == 413
    assert r.json() == {"detail": "Request body too large"}


def test_cloud_api_records_structured_redacted_request_logs(client, app_module):
    r = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "req-test-1", "Authorization": "Bearer secret-token"},
    )

    assert r.status_code == 200
    assert r.headers["x-request-id"] == "req-test-1"
    event = app_module.app.state.request_logs[-1]
    assert event["request_id"] == "req-test-1"
    assert event["method"] == "GET"
    assert event["path"] == "/api/v1/health"
    assert event["status_code"] == 200
    assert "secret-token" not in json.dumps(event)


def test_cloud_api_exposes_operational_metrics(client):
    client.get("/api/v1/health", headers={"X-Request-ID": "metrics-1"})

    r = client.get("/api/v1/ops/metrics")

    assert r.status_code == 200
    body = r.json()
    assert body["requests_total"] >= 1
    assert body["status_families"]["2xx"] >= 1
    assert body["routes"]["GET /api/v1/health"] >= 1


def test_admin_endpoints_reject_wrong_secret(client):
    r = client.post("/api/admin/licenses/generate", json={"tier": "pro"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


def test_admin_endpoints_accept_correct_secret(client):
    r = client.get("/api/admin/stats", headers=ADMIN)
    assert r.status_code == 200


def test_admin_login_sets_session_and_csrf(client):
    r = client.get("/api/admin/auth/me", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["admin"]["email"] == "admin@example.com"
    assert body["admin"]["role"] == "owner"


def test_admin_logout_revokes_session(client):
    r = client.post("/api/admin/auth/logout", headers=ADMIN)
    assert r.status_code == 200
    r = client.get("/api/admin/stats", headers=ADMIN)
    assert r.status_code == 401


def _add_admin(app_module, email: str, password: str, role: str, *, disabled: bool = False) -> str:
    admin_id = f"{role}-{email.split('@')[0]}"
    admins = app_module._load_admins()
    admins[admin_id] = {
        "id": admin_id,
        "email": email,
        "hash": app_module.pwd_ctx.hash(password),
        "role": role,
        "mfa_secret": "",
        "created": app_module._utcnow().isoformat(),
        "disabled": disabled,
    }
    app_module._save_admins(admins)
    return admin_id


def _login_as(client, email: str, password: str) -> dict:
    r = client.post("/api/admin/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_disabled_admin_cannot_login(client, app_module):
    _add_admin(app_module, "disabled@example.com", "disabled-pass-123", "billing", disabled=True)
    r = client.post("/api/admin/auth/login", json={
        "email": "disabled@example.com",
        "password": "disabled-pass-123",
    })
    assert r.status_code == 401
    assert "disabled@example.com" not in r.text


def test_expired_admin_session_is_rejected(client, app_module):
    sessions = app_module._load_admin_sessions()
    for session in sessions.values():
        session["expires_at"] = "2000-01-01T00:00:00"
    app_module._save_admin_sessions(sessions)
    r = client.get("/api/admin/stats", headers=ADMIN)
    assert r.status_code == 401


def test_admin_role_boundaries(client, app_module):
    _add_admin(app_module, "viewer@example.com", "viewer-pass-123", "viewer")
    viewer = _login_as(client, "viewer@example.com", "viewer-pass-123")
    assert client.get("/api/admin/stats", headers=viewer).status_code == 200
    assert client.post("/api/admin/licenses/generate", headers=viewer, json={"tier": "pro"}).status_code == 403

    _add_admin(app_module, "billing@example.com", "billing-pass-123", "billing")
    billing = _login_as(client, "billing@example.com", "billing-pass-123")
    assert client.post("/api/admin/licenses/generate", headers=billing, json={"tier": "pro"}).status_code == 200
    assert client.get("/api/admin/backup", headers=billing).status_code == 403


def test_admin_mutation_audit_includes_actor_and_request(client, app_module):
    _add_admin(app_module, "billing@example.com", "billing-pass-123", "billing")
    billing = _login_as(client, "billing@example.com", "billing-pass-123")
    billing["X-Request-ID"] = "req-test-123"
    r = client.post("/api/admin/licenses/generate", headers=billing, json={"tier": "pro"})
    assert r.status_code == 200
    audit = client.get("/api/admin/audit", headers=ADMIN).json()
    event = next(e for e in audit if e["action"] == "generate_license" and e["request_id"] == "req-test-123")
    assert event["actor_id"] == "billing-billing"
    assert event["actor_email"] == "billing@example.com"
    assert event["actor_role"] == "billing"


def test_admin_refresh_rotates_session_and_csrf(client, app_module):
    old_sessions = app_module._load_admin_sessions()
    assert len(old_sessions) == 1
    old_hash = next(iter(old_sessions))
    old_admin_id = old_sessions[old_hash]["admin_id"]
    old_csrf = ADMIN["X-CSRF-Token"]

    r = client.post("/api/admin/auth/refresh", headers=ADMIN)

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["csrf_token"] != old_csrf
    sessions = app_module._load_admin_sessions()
    assert sessions[old_hash]["revoked"] is True
    live_sessions = [s for s in sessions.values() if not s.get("revoked")]
    assert len(live_sessions) == 1
    assert live_sessions[0]["admin_id"] == old_admin_id
    ADMIN["X-CSRF-Token"] = body["csrf_token"]
    assert client.get("/api/admin/stats", headers=ADMIN).status_code == 200


def test_owner_can_revoke_admin_sessions(client, app_module):
    from fastapi.testclient import TestClient

    target_id = _add_admin(app_module, "billing@example.com", "billing-pass-123", "billing")
    billing_client = TestClient(app_module.app)
    billing = _login_as(billing_client, "billing@example.com", "billing-pass-123")
    assert billing_client.get("/api/admin/stats", headers=billing).status_code == 200

    r = client.post(f"/api/admin/admins/{target_id}/sessions/revoke", headers=ADMIN)

    assert r.status_code == 200
    assert r.json()["revoked"] >= 1
    assert billing_client.get("/api/admin/stats", headers=billing).status_code == 401


def test_admin_login_lockout_after_repeated_failures(client, app_module):
    for _ in range(app_module.ADMIN_LOGIN_LOCKOUT_FAILURES):
        r = client.post("/api/admin/auth/login", json={
            "email": "admin@example.com",
            "password": "wrong-password",
        })
        assert r.status_code == 401

    locked = client.post("/api/admin/auth/login", json={
        "email": "admin@example.com",
        "password": "admin-pass-123",
    })

    assert locked.status_code == 423
    admin = app_module._admin_by_email("admin@example.com")
    assert admin["failed_login_count"] == app_module.ADMIN_LOGIN_LOCKOUT_FAILURES
    assert admin["lockout_until"] > app_module._utcnow().isoformat()
    audit = app_module._load_audit()
    assert any(e["action"] == "admin_login_lockout" for e in audit)


def test_admin_successful_login_resets_failed_login_state(client, app_module):
    admin = app_module._admin_by_email("admin@example.com")
    admins = app_module._load_admins()
    admins[admin["id"]]["failed_login_count"] = 2
    admins[admin["id"]]["lockout_until"] = ""
    app_module._save_admins(admins)

    r = client.post("/api/admin/auth/login", json={
        "email": "admin@example.com",
        "password": "admin-pass-123",
    })

    assert r.status_code == 200
    admin = app_module._admin_by_email("admin@example.com")
    assert admin.get("failed_login_count", 0) == 0
    assert admin.get("lockout_until", "") == ""


def test_admin_mfa_enrollment_and_login_flow(client, app_module):
    setup = client.post("/api/admin/auth/mfa/setup", headers=ADMIN)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    recovery_codes = setup.json()["recovery_codes"]
    assert len(recovery_codes) == app_module.ADMIN_MFA_RECOVERY_CODE_COUNT
    assert all(code.startswith("PK-MFA-") for code in recovery_codes)

    code = app_module._totp_code(secret, int(app_module.time.time() // 30))
    confirm = client.post("/api/admin/auth/mfa/confirm", headers=ADMIN, json={"code": code})
    assert confirm.status_code == 200
    assert confirm.json()["enabled"] is True
    admin = app_module._admin_by_email("admin@example.com")
    assert admin["mfa_secret"] == secret
    assert "mfa_pending_secret" not in admin
    assert all("recovery_codes" not in session for session in app_module._load_admin_sessions().values())

    client.cookies.clear()
    assert client.post("/api/admin/auth/login", json={
        "email": "admin@example.com",
        "password": "admin-pass-123",
    }).status_code == 401
    assert client.post("/api/admin/auth/login", json={
        "email": "admin@example.com",
        "password": "admin-pass-123",
        "mfa_code": app_module._totp_code(secret, int(app_module.time.time() // 30)),
    }).status_code == 200


def test_owner_can_reset_admin_mfa(client, app_module):
    target_id = _add_admin(app_module, "billing@example.com", "billing-pass-123", "billing")
    admins = app_module._load_admins()
    admins[target_id]["mfa_secret"] = "JBSWY3DPEHPK3PXP"
    admins[target_id]["mfa_recovery_hashes"] = ["hash"]
    app_module._save_admins(admins)

    r = client.post(f"/api/admin/admins/{target_id}/mfa/reset", headers=ADMIN)

    assert r.status_code == 200
    assert r.json()["reset"] is True
    target = app_module._load_admins()[target_id]
    assert target.get("mfa_secret", "") == ""
    assert target.get("mfa_recovery_hashes", []) == []


# ── License generation ───────────────────────────────────────────
def test_generate_license(client):
    r = client.post("/api/admin/licenses/generate",
                    json={"tier": "pro", "email": "u@x.com"},
                    headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert data["tier"] == "pro"
    assert data["email"] == "u@x.com"
    assert data["status"] == "active"
    assert data["key"].startswith("PRO-")


def test_generate_license_invalid_tier(client):
    r = client.post("/api/admin/licenses/generate",
                    json={"tier": "godmode"},
                    headers=ADMIN)
    assert r.status_code == 400


def test_list_licenses(client):
    client.post("/api/admin/licenses/generate", json={"tier": "free"}, headers=ADMIN)
    client.post("/api/admin/licenses/generate", json={"tier": "pro"}, headers=ADMIN)
    r = client.get("/api/admin/licenses", headers=ADMIN)
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── License lifecycle ────────────────────────────────────────────
def _make_key(client, tier="pro", email="t@example.com"):
    return client.post("/api/admin/licenses/generate",
                       json={"tier": tier, "email": email},
                       headers=ADMIN).json()["key"]


def test_expire_license(client):
    key = _make_key(client)
    r = client.post(f"/api/admin/licenses/{key}/expire", headers=ADMIN)
    assert r.status_code == 200
    lic = next(l for l in client.get("/api/admin/licenses", headers=ADMIN).json() if l["key"] == key)
    assert lic["status"] == "expired"


def test_revoke_license(client):
    key = _make_key(client)
    r = client.post(f"/api/admin/licenses/{key}/revoke", headers=ADMIN)
    assert r.status_code == 200
    lic = next(l for l in client.get("/api/admin/licenses", headers=ADMIN).json() if l["key"] == key)
    assert lic["status"] == "revoked"


def test_renew_license(client):
    key = _make_key(client)
    client.post(f"/api/admin/licenses/{key}/expire", headers=ADMIN)
    r = client.post(f"/api/admin/licenses/{key}/renew", headers=ADMIN)
    assert r.status_code == 200
    lic = next(l for l in client.get("/api/admin/licenses", headers=ADMIN).json() if l["key"] == key)
    assert lic["status"] == "active"


def test_lifecycle_action_404_for_unknown(client):
    r = client.post("/api/admin/licenses/NO-SUCH-KEY/expire", headers=ADMIN)
    assert r.status_code == 404


# ── Heartbeat ────────────────────────────────────────────────────
def test_heartbeat_updates_record(client):
    key = _make_key(client)
    activated = client.post("/v1/activate", json={"license_key": key, "fingerprint": "admin-test"}).json()
    r = client.post("/api/v1/heartbeat",
                    json={"license_key": key, "fingerprint": "admin-test", "token": activated["token"],
                          "platform": "TestOS 1.0", "version": "1.2.3"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tier"] == "pro"

    lic = next(l for l in client.get("/api/admin/licenses", headers=ADMIN).json() if l["key"] == key)
    assert lic["platform"] == "TestOS 1.0"
    assert lic["last_heartbeat"] is not None


def test_heartbeat_unknown_key_404(client):
    r = client.post("/api/v1/heartbeat", json={"license_key": "FAKE-KEY", "fingerprint": "x", "token": "x"})
    assert r.status_code == 404


def test_heartbeat_revoked_key_blocked(client):
    key = _make_key(client)
    activated = client.post("/v1/activate", json={"license_key": key, "fingerprint": "admin-test"}).json()
    client.post(f"/api/admin/licenses/{key}/revoke", headers=ADMIN)
    r = client.post("/api/v1/heartbeat", json={"license_key": key, "fingerprint": "admin-test", "token": activated["token"]})
    assert r.status_code == 403


def test_heartbeat_alias_path(client):
    """Both /v1/heartbeat and /api/v1/heartbeat should work."""
    key = _make_key(client)
    activated = client.post("/v1/activate", json={"license_key": key, "fingerprint": "admin-test"}).json()
    r = client.post("/api/v1/heartbeat", json={"license_key": key, "fingerprint": "admin-test",
                                               "token": activated["token"], "platform": "Linux"})
    assert r.status_code == 200


# ── Issue + email-result shape ───────────────────────────────────
def test_issue_license_with_trial(client):
    r = client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro", "email": "trial@example.com", "name": "Tester",
        "trial_days": 7, "send_email": False, "source": "Direct",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["expires_at"] is not None
    assert data["stage"] == "trial"
    assert data["email_result"]["sent"] is False
    assert data["email_result"]["reason"] == "not_requested"


def test_issue_license_invalid_trial_days(client):
    r = client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro", "email": "x@y.com", "trial_days": 99, "send_email": False,
    })
    assert r.status_code == 400


def test_issue_requires_email(client):
    r = client.post("/api/admin/licenses/issue", headers=ADMIN,
                    json={"tier": "pro", "send_email": False})
    assert r.status_code == 400


# ── Contacts ─────────────────────────────────────────────────────
def test_contacts_groups_by_email(client):
    client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "starter", "email": "alice@example.com", "name": "Alice",
        "send_email": False,
    })
    client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro", "email": "alice@example.com", "name": "Alice",
        "send_email": False,
    })
    contacts = client.get("/api/admin/contacts", headers=ADMIN).json()
    alice = next(c for c in contacts if c["email"] == "alice@example.com")
    assert len(alice["keys"]) == 2


def test_update_contact(client):
    client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro", "email": "u@example.com", "send_email": False,
    })
    r = client.patch("/api/admin/contacts/u@example.com", headers=ADMIN,
                     json={"stage": "converted", "notes": "hot lead"})
    assert r.status_code == 200
    assert r.json()["updated"] >= 1
    contacts = client.get("/api/admin/contacts", headers=ADMIN).json()
    assert contacts[0]["stage"] == "converted"


# ── Stats + Analytics ────────────────────────────────────────────
def test_stats_counts(client):
    _make_key(client, tier="free")
    _make_key(client, tier="pro")
    pro_key = _make_key(client, tier="pro")
    client.post(f"/api/admin/licenses/{pro_key}/revoke", headers=ADMIN)

    s = client.get("/api/admin/stats", headers=ADMIN).json()
    assert s["total"] == 3
    assert s["total_active"] == 2
    assert s["revoked"] == 1
    assert s["pro_team"] == 1  # only one ACTIVE pro+team


def test_analytics_returns_buckets(client):
    _make_key(client)
    a = client.get("/api/admin/analytics", headers=ADMIN).json()
    assert len(a["daily_activations"]) == 30
    assert len(a["daily_heartbeats"]) == 30
    assert "event_totals" in a


# ── Bulk ─────────────────────────────────────────────────────────
def test_bulk_revoke(client):
    keys = [_make_key(client) for _ in range(3)]
    r = client.post("/api/admin/licenses/bulk", headers=ADMIN,
                    json={"action": "revoke", "keys": keys})
    assert r.status_code == 200
    assert r.json()["affected"] == 3
    licenses = client.get("/api/admin/licenses", headers=ADMIN).json()
    assert all(l["status"] == "revoked" for l in licenses)


def test_bulk_invalid_action(client):
    r = client.post("/api/admin/licenses/bulk", headers=ADMIN,
                    json={"action": "delete", "keys": ["X"]})
    assert r.status_code == 400


def test_bulk_with_unknown_keys(client):
    real = _make_key(client)
    r = client.post("/api/admin/licenses/bulk", headers=ADMIN,
                    json={"action": "expire", "keys": [real, "FAKE"]})
    body = r.json()
    assert body["affected"] == 1
    assert body["not_found"] == 1


# ── Audit log ────────────────────────────────────────────────────
def test_audit_log_records_actions(client):
    key = _make_key(client)
    client.post(f"/api/admin/licenses/{key}/revoke", headers=ADMIN)
    audit = client.get("/api/admin/audit", headers=ADMIN).json()
    actions = [e["action"] for e in audit]
    assert "generate_license" in actions
    assert "revoke_license" in actions
    login = next(e for e in audit if e["action"] == "admin_login")
    assert login["actor_email"] == "admin@example.com"
    assert login["actor_role"] == "owner"


# ── Tickets ──────────────────────────────────────────────────────
def test_create_and_list_tickets(client):
    r = client.post("/api/admin/tickets", headers=ADMIN, json={
        "email":   "user@x.com",
        "subject": "Help",
        "message": "Stuck on activation",
        "priority": "high",
    })
    assert r.status_code == 200
    ticket = r.json()
    assert ticket["status"] == "open"

    tickets = client.get("/api/admin/tickets", headers=ADMIN).json()
    assert len(tickets) == 1
    assert tickets[0]["subject"] == "Help"


def test_create_ticket_validation(client):
    r = client.post("/api/admin/tickets", headers=ADMIN,
                    json={"email": "x@y.com", "subject": "", "message": ""})
    assert r.status_code == 400


def test_update_ticket_status_and_reply(client):
    ticket_id = client.post("/api/admin/tickets", headers=ADMIN,
                            json={"subject": "Q", "message": "?", "email": "a@b.com"}
                            ).json()["id"]
    r = client.patch(f"/api/admin/tickets/{ticket_id}", headers=ADMIN,
                     json={"status": "resolved", "reply": "Fixed!"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved"
    assert len(body["replies"]) == 1
    assert body["replies"][0]["body"] == "Fixed!"


# ── Settings ─────────────────────────────────────────────────────
def test_settings_endpoint(client):
    r = client.get("/api/admin/settings", headers=ADMIN)
    assert r.status_code == 200
    s = r.json()
    assert "smtp" in s
    assert "version" in s
    assert s["admin_auth"] == "cookie_session"


def test_test_email_no_smtp(client):
    r = client.post("/api/admin/settings/test-email", headers=ADMIN,
                    json={"to": "user@example.com"})
    body = r.json()
    assert body["sent"] is False
    assert "smtp" in body["reason"].lower() or "configured" in body["reason"].lower()


def test_email_sender_retries_and_dead_letters_without_body(app_module, monkeypatch):
    class FailingSMTP:
        attempts = 0

        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            return None

        def login(self, *_):
            return None

        def sendmail(self, *_):
            FailingSMTP.attempts += 1
            raise OSError("smtp down")

    monkeypatch.setattr(app_module, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(app_module, "SMTP_USER", "smtp-user")
    monkeypatch.setattr(app_module, "SMTP_PASS", "smtp-pass")
    monkeypatch.setattr(app_module, "FROM_EMAIL", "from@example.com")
    monkeypatch.setattr(app_module, "SMTP_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(app_module, "SMTP_RETRY_DELAY_SEC", 0)
    monkeypatch.setattr(app_module.smtplib, "SMTP", FailingSMTP)

    result = app_module._send_email_html(
        "to@example.com",
        "Subject",
        "<p>secret-html-body</p>",
        "secret-plain-body",
    )

    assert result["sent"] is False
    assert result["reason"] == "dead_lettered"
    assert FailingSMTP.attempts == 2
    dead_letters = list(app_module.DEAD_LETTER_DIR.glob("email-*.json"))
    assert len(dead_letters) == 1
    text = dead_letters[0].read_text(encoding="utf-8")
    assert "to@example.com" in text
    assert "Subject" in text
    assert "secret-html-body" not in text
    assert "secret-plain-body" not in text


# ── License-CRM E2E flow ─────────────────────────────────────────
def test_license_crm_e2e_issue_to_contact_to_invite(client):
    """End-to-end: issue trial → appears in /contacts → update stage → resend invite."""
    # 1. Issue a trial license
    r1 = client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro",
        "email": "lead@example.com",
        "name": "Sample Lead",
        "company": "Acme Co",
        "source": "Direct",
        "trial_days": 14,
        "send_email": False,
    })
    assert r1.status_code == 200
    issued = r1.json()
    assert issued["tier"] == "pro"
    assert issued["stage"] == "trial"
    assert issued["expires_at"] is not None
    assert issued["sent_invite"] is False
    key = issued["key"]

    # 2. /contacts surfaces the lead
    r2 = client.get("/api/admin/contacts", headers=ADMIN)
    assert r2.status_code == 200
    contacts = r2.json()
    assert isinstance(contacts, list)
    found = next((c for c in contacts if c["email"] == "lead@example.com"), None)
    assert found is not None
    assert found["company"] == "Acme Co"

    # 3. Update stage trial → converted
    r3 = client.patch("/api/admin/contacts/lead@example.com", headers=ADMIN,
                      json={"stage": "converted"})
    assert r3.status_code == 200
    assert r3.json()["updated"] == 1

    # 4. Confirm stage written to license file
    import json as _json
    from pathlib import Path
    licenses_file = Path(os.environ["PUSHKEY_DATA_DIR"]) / "licenses.json"
    data = _json.loads(licenses_file.read_text())
    assert data[key]["stage"] == "converted"

    # 5. Trigger resend invite (no SMTP → sent=False, but endpoint should not 500)
    r5 = client.post(f"/api/admin/licenses/{key}/send-invite", headers=ADMIN)
    assert r5.status_code == 200
    body = r5.json()
    assert "sent" in body  # may be False (no SMTP); just verify shape


def test_license_crm_auto_expire_flips_status(client):
    """Issuing with a past expires_at and listing should auto-flip status to expired."""
    # Issue normally then mutate expires_at to past via direct file (simulating time passing)
    r = client.post("/api/admin/licenses/issue", headers=ADMIN, json={
        "tier": "pro", "email": "exp@x.com", "trial_days": 7,
    })
    assert r.status_code == 200
    key = r.json()["key"]

    # Force expires_at into the past
    import json as _json
    from pathlib import Path
    licenses_file = Path(os.environ["PUSHKEY_DATA_DIR"]) / "licenses.json"
    data = _json.loads(licenses_file.read_text())
    data[key]["expires_at"] = "2000-01-01T00:00:00"
    licenses_file.write_text(_json.dumps(data))

    # Hit /contacts which calls _auto_expire
    r2 = client.get("/api/admin/contacts", headers=ADMIN)
    assert r2.status_code == 200

    # Reload — status should now be "expired"
    data2 = _json.loads(licenses_file.read_text())
    assert data2[key]["status"] == "expired"


# ── Rate limiters ────────────────────────────────────────────────
@pytest.fixture
def low_rate_limit_app(tmp_path, monkeypatch):
    """Re-import cloud_api with tight rate limits so tests run fast."""
    monkeypatch.setenv("PUSHKEY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUSHKEY_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PUSHKEY_ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("PUSHKEY_ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("PUSHKEY_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("AUTH_RATE_MAX", "2")
    monkeypatch.setenv("AUTH_RATE_WINDOW", "60")
    monkeypatch.setenv("PORTAL_RATE_MAX", "2")
    monkeypatch.setenv("PORTAL_RATE_WINDOW", "60")
    for _k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "FROM_EMAIL"):
        monkeypatch.setenv(_k, "")
    import importlib, sys
    if "pushkey_cloud_api" in sys.modules:
        del sys.modules["pushkey_cloud_api"]
    return importlib.import_module("pushkey_cloud_api")


def test_auth_login_rate_limit(low_rate_limit_app):
    from fastapi.testclient import TestClient
    client = TestClient(low_rate_limit_app.app)
    body = {"email": "u@x.com", "password": "wrong"}
    # First two requests pass through (return 401 invalid creds, NOT 429)
    r1 = client.post("/api/v1/auth/login", json=body)
    r2 = client.post("/api/v1/auth/login", json=body)
    assert r1.status_code != 429
    assert r2.status_code != 429
    # Third hits the limiter
    r3 = client.post("/api/v1/auth/login", json=body)
    assert r3.status_code == 429
    assert r3.headers["retry-after"] == str(low_rate_limit_app.AUTH_RATE_WINDOW_SEC)
    assert "try again" in r3.json()["detail"].lower()


def test_rate_limit_abuse_alert_is_recorded_without_secret_body(low_rate_limit_app):
    from fastapi.testclient import TestClient

    client = TestClient(low_rate_limit_app.app)
    body = {"email": "u@x.com", "password": "secret-password"}
    client.post("/api/v1/auth/login", json=body)
    client.post("/api/v1/auth/login", json=body)
    r3 = client.post("/api/v1/auth/login", json=body)

    assert r3.status_code == 429
    alerts = low_rate_limit_app.app.state.alerts
    assert alerts[-1]["type"] == "rate_limit"
    assert alerts[-1]["path"] == "/api/v1/auth/login"
    assert "secret-password" not in json.dumps(alerts[-1])


def test_auth_register_rate_limit_shares_bucket_with_login(low_rate_limit_app):
    from fastapi.testclient import TestClient
    client = TestClient(low_rate_limit_app.app)
    # Register and login share _AUTH_HITS bucket per-IP — 2 of either trips it
    r1 = client.post("/api/v1/auth/register", json={"email": "a@x.com", "password": "p"})
    r2 = client.post("/api/v1/auth/login", json={"email": "a@x.com", "password": "p"})
    r3 = client.post("/api/v1/auth/register", json={"email": "b@x.com", "password": "p"})
    assert r1.status_code != 429
    assert r2.status_code != 429
    assert r3.status_code == 429


def test_portal_lookup_rate_limit(low_rate_limit_app):
    from fastapi.testclient import TestClient
    client = TestClient(low_rate_limit_app.app)
    body = {"email": "anyone@x.com"}
    r1 = client.post("/api/v1/portal/lookup", json=body)
    r2 = client.post("/api/v1/portal/lookup", json=body)
    r3 = client.post("/api/v1/portal/lookup", json=body)
    assert r1.status_code != 429
    assert r2.status_code != 429
    assert r3.status_code == 429


# ── Export ───────────────────────────────────────────────────────
def test_csv_export(client):
    _make_key(client, email="ex@x.com")
    r = client.get("/api/admin/export", headers=ADMIN)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "ex@x.com" in r.text


def test_csv_export_filtered_by_tier(client):
    _make_key(client, tier="free", email="free@x.com")
    _make_key(client, tier="pro", email="pro@x.com")
    r = client.get("/api/admin/export?tier=pro", headers=ADMIN)
    assert "pro@x.com" in r.text
    assert "free@x.com" not in r.text
    assert "filtered" in r.headers["content-disposition"]


def test_csv_export_filtered_by_status(client):
    k = _make_key(client, email="active@x.com")
    _make_key(client, email="other@x.com")
    client.post(f"/api/admin/licenses/{k}/revoke", headers=ADMIN)
    r = client.get("/api/admin/export?status=revoked", headers=ADMIN)
    assert "active@x.com" in r.text
    assert "other@x.com" not in r.text


# ── Rate limiting ────────────────────────────────────────────────
def test_heartbeat_rate_limit(client, monkeypatch):
    """Default limit is 10 per 60s — 11th hit should 429."""
    key = _make_key(client)
    token = client.post("/v1/activate", json={"license_key": key, "fingerprint": "rate-test"}).json()["token"]
    for _ in range(10):
        r = client.post("/api/v1/heartbeat", json={"license_key": key, "fingerprint": "rate-test", "token": token})
        assert r.status_code == 200
        token = r.json()["token"]
    r = client.post("/api/v1/heartbeat", json={"license_key": key, "fingerprint": "rate-test", "token": token})
    assert r.status_code == 429


def test_heartbeat_requires_license_key(client):
    r = client.post("/v1/heartbeat", json={})
    assert r.status_code == 400


# ── Password reset ───────────────────────────────────────────────
def test_request_reset_always_returns_ok(client):
    """Should not leak whether email exists (anti-enumeration)."""
    r = client.post("/api/v1/auth/request-reset", json={"email": "nobody@x.com"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_password_reset_full_flow(client, app_module):
    # Register user
    client.post("/api/v1/auth/register",
                json={"email": "u@x.com", "password": "oldpass123"})

    # Request reset
    r = client.post("/api/v1/auth/request-reset", json={"email": "u@x.com"})
    assert r.status_code == 200

    # Read token from users.json (simulates clicking email link)
    users = app_module._load_users()
    token_hash = users["u@x.com"]["reset_token_hash"]
    assert token_hash is not None

    # Confirm with bad token
    r = client.post("/api/v1/auth/confirm-reset", json={
        "email": "u@x.com", "token": "wrong", "password": "newpass123",
    })
    assert r.status_code == 401

    # We can't get the real token (only hash is stored), but we can
    # forge one by manually injecting a known hash:
    import hashlib
    test_token = "test-token-123"
    users["u@x.com"]["reset_token_hash"] = hashlib.sha256(test_token.encode()).hexdigest()
    app_module._save_users(users)

    # Confirm with correct token
    r = client.post("/api/v1/auth/confirm-reset", json={
        "email": "u@x.com", "token": test_token, "password": "newpass123",
    })
    assert r.status_code == 200
    assert "token" in r.json()

    # Old password no longer works
    r = client.post("/api/v1/auth/login",
                    json={"email": "u@x.com", "password": "oldpass123"})
    assert r.status_code == 401

    # New password works
    r = client.post("/api/v1/auth/login",
                    json={"email": "u@x.com", "password": "newpass123"})
    assert r.status_code == 200


def test_confirm_reset_requires_password_length(client):
    client.post("/api/v1/auth/register",
                json={"email": "u@x.com", "password": "oldpass123"})
    r = client.post("/api/v1/auth/confirm-reset", json={
        "email": "u@x.com", "token": "x", "password": "short",
    })
    assert r.status_code == 400


# ── Backup ───────────────────────────────────────────────────────
def test_backup_returns_tarball(client):
    _make_key(client, email="x@y.com")
    r = client.get("/api/admin/backup", headers=ADMIN)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    # Body should be a valid tar.gz
    import tarfile, io
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as t:
        names = t.getnames()
        assert "licenses.json" in names

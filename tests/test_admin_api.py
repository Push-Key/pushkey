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
    monkeypatch.setenv("PUSHKEY_ADMIN_SECRET", "test-secret")
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
    return TestClient(app_module.app)


ADMIN = {"X-Admin-Secret": "test-secret"}


# ── Auth ─────────────────────────────────────────────────────────
def test_admin_endpoints_reject_missing_secret(client):
    r = client.get("/api/admin/stats")
    assert r.status_code == 403


def test_admin_endpoints_reject_wrong_secret(client):
    r = client.get("/api/admin/stats", headers={"X-Admin-Secret": "wrong"})
    assert r.status_code == 403


def test_admin_endpoints_accept_correct_secret(client):
    r = client.get("/api/admin/stats", headers=ADMIN)
    assert r.status_code == 200


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
    r = client.post("/v1/heartbeat",
                    json={"license_key": key, "platform": "TestOS 1.0", "version": "1.2.3"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tier"] == "pro"

    lic = next(l for l in client.get("/api/admin/licenses", headers=ADMIN).json() if l["key"] == key)
    assert lic["platform"] == "TestOS 1.0"
    assert lic["last_heartbeat"] is not None


def test_heartbeat_unknown_key_404(client):
    r = client.post("/v1/heartbeat", json={"license_key": "FAKE-KEY"})
    assert r.status_code == 404


def test_heartbeat_revoked_key_blocked(client):
    key = _make_key(client)
    client.post(f"/api/admin/licenses/{key}/revoke", headers=ADMIN)
    r = client.post("/v1/heartbeat", json={"license_key": key})
    assert r.status_code == 403


def test_heartbeat_alias_path(client):
    """Both /v1/heartbeat and /api/v1/heartbeat should work."""
    key = _make_key(client)
    r = client.post("/api/v1/heartbeat", json={"license_key": key, "platform": "Linux"})
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
    assert s["admin_secret_set"] is True  # we set it via env


def test_test_email_no_smtp(client):
    r = client.post("/api/admin/settings/test-email", headers=ADMIN,
                    json={"to": "user@example.com"})
    body = r.json()
    assert body["sent"] is False
    assert "smtp" in body["reason"].lower() or "configured" in body["reason"].lower()


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
    for _ in range(10):
        r = client.post("/v1/heartbeat", json={"license_key": key})
        assert r.status_code == 200
    r = client.post("/v1/heartbeat", json={"license_key": key})
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

"""
Direct unit tests for pushkey_agent_tokens.

Conftest auto-fixture redirects all vault paths to tmp_path, so tokens
written here never touch the real ~/.pushkey directory.
"""
import secrets
import pytest

import pushkey_agent_tokens as at
import pushkey_shared as _s


def _fake_vault_key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def pro_tier(monkeypatch):
    """Force Pro tier so create_token is allowed."""
    import pushkey_tiers
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")
    return "pro"


@pytest.fixture
def free_tier(monkeypatch):
    import pushkey_tiers
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "free")
    return "free"


# ── create_token ─────────────────────────────────────────────────────────────

def test_create_token_happy_path(pro_tier):
    vk = _fake_vault_key()
    ok, value, tid = at.create_token("ci-build", ["read"], vk)
    assert ok is True
    assert value.startswith("pk_agent_")
    assert tid.startswith("at_")


def test_create_token_blocked_on_free_tier(free_tier):
    ok, msg, tid = at.create_token("name", ["read"], _fake_vault_key())
    assert ok is False
    assert "Pro" in msg
    assert tid == ""


def test_create_token_invalid_scope_rejected(pro_tier):
    ok, msg, _ = at.create_token("x", ["read", "evil"], _fake_vault_key())
    assert ok is False
    assert "Invalid scopes" in msg


def test_create_token_respects_pro_limit(pro_tier):
    # Pro tier max_agent_tokens = 1
    ok, _, _ = at.create_token("first", ["read"], _fake_vault_key())
    assert ok is True
    ok2, msg, _ = at.create_token("second", ["read"], _fake_vault_key())
    assert ok2 is False
    assert "limit reached" in msg.lower()


# ── list_tokens (no values, no wrapped keys) ────────────────────────────────

def test_list_tokens_omits_secrets(pro_tier):
    at.create_token("t1", ["read", "write"], _fake_vault_key())
    listed = at.list_tokens()
    assert len(listed) == 1
    t = listed[0]
    assert "wrapped_vault_key" not in t
    assert "token_hash" not in t
    assert t["name"] == "t1"
    assert t["scopes"] == ["read", "write"]


def test_list_tokens_empty_on_fresh_vault():
    assert at.list_tokens() == []


# ── revoke_token ─────────────────────────────────────────────────────────────

def test_revoke_token_removes_entry(pro_tier):
    _, _, tid = at.create_token("t1", ["read"], _fake_vault_key())
    assert at.revoke_token(tid) is True
    assert at.list_tokens() == []


def test_revoke_unknown_token_returns_false():
    assert at.revoke_token("at_does_not_exist") is False


# ── authenticate_token (round-trip vault key) ────────────────────────────────

def test_authenticate_returns_vault_key_and_scopes(pro_tier):
    vk = _fake_vault_key()
    _, value, _ = at.create_token("t1", ["read", "inject"], vk)
    unwrapped, scopes, err = at.authenticate_token(value)
    assert err == ""
    assert unwrapped == vk
    assert scopes == ["read", "inject"]


def test_authenticate_rejects_non_pk_agent_prefix():
    unwrapped, scopes, err = at.authenticate_token("not-an-agent-token")
    assert unwrapped is None
    assert scopes == []
    assert "not an agent token" in err


def test_authenticate_rejects_revoked_token(pro_tier):
    _, value, tid = at.create_token("t1", ["read"], _fake_vault_key())
    at.revoke_token(tid)
    unwrapped, _, err = at.authenticate_token(value)
    assert unwrapped is None
    assert "not found" in err.lower() or "revoked" in err.lower()


def test_authenticate_updates_last_used(pro_tier):
    _, value, tid = at.create_token("t1", ["read"], _fake_vault_key())
    assert at.list_tokens()[0]["last_used"] is None
    at.authenticate_token(value)
    assert at.list_tokens()[0]["last_used"] is not None


def test_authenticate_unknown_token_fails():
    fake = "pk_agent_" + secrets.token_hex(24)
    unwrapped, _, err = at.authenticate_token(fake)
    assert unwrapped is None
    assert "not found" in err.lower()

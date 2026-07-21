"""
Tests for pushkey_tiers.py — license loading, tier gates, offline grace.
"""
import json
from datetime import datetime, timedelta

import pytest
import io
import urllib.error
import pushkey_shared
import pushkey_tiers as tiers


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(pushkey_shared, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey_shared, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey_shared, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey_shared, "LICENSE_FILE", tmp_path / ".license")
    monkeypatch.setattr(pushkey_shared, "TOKEN_FILE", tmp_path / ".token")
    monkeypatch.setattr(pushkey_shared, "LOG_FILE", tmp_path / "pushkey.log")
    tiers._LICENSE_CACHE = None


# ── load_license ────────────────────────────────────────────────────────────

def test_load_license_defaults_free_when_no_file():
    lic = tiers.load_license()
    assert lic["tier"] == "free"


def test_load_license_returns_saved_data(tmp_path):
    data = {"tier": "pro", "license_key": "PRO-FAKE", "lifetime": True}
    tiers.save_license(data)
    tiers._LICENSE_CACHE = None
    lic = tiers.load_license()
    assert lic["tier"] == "pro"


def test_load_license_corrupt_file_falls_back_to_free(tmp_path):
    pushkey_shared.LICENSE_FILE.write_bytes(b"not-valid-ciphertext")
    tiers._LICENSE_CACHE = None
    lic = tiers.load_license()
    assert lic["tier"] == "free"


def test_load_license_expired_past_grace_returns_free():
    expired = (datetime.now() - timedelta(days=30)).isoformat()
    data = {"tier": "starter", "expires": expired}
    tiers.save_license(data)
    tiers._LICENSE_CACHE = None
    lic = tiers.load_license()
    assert lic["tier"] == "free"
    assert lic.get("_expired") is True


def test_load_license_within_grace_period_returns_tier():
    # Expired 1 day ago — still within 3-day grace
    just_expired = (datetime.now() - timedelta(days=1)).isoformat()
    data = {"tier": "starter", "expires": just_expired}
    tiers.save_license(data)
    tiers._LICENSE_CACHE = None
    lic = tiers.load_license()
    assert lic["tier"] == "starter"


def test_load_license_no_expiry_is_lifetime():
    data = {"tier": "pro", "expires": None, "lifetime": True}
    tiers.save_license(data)
    tiers._LICENSE_CACHE = None
    lic = tiers.load_license()
    assert lic["tier"] == "pro"


# ── current_tier / tier gates ───────────────────────────────────────────────

def test_current_tier_free_by_default():
    assert tiers.current_tier() == "free"


def test_current_tier_reflects_saved_license():
    tiers.save_license({"tier": "team"})
    tiers._LICENSE_CACHE = None
    assert tiers.current_tier() == "team"


def test_can_do_returns_false_for_gated_feature_on_free():
    assert tiers.can_do("cloud_sync") is False
    assert tiers.can_do("team_rbac") is False
    assert tiers.can_do("sso") is False


def test_can_do_returns_true_for_allowed_feature():
    tiers.save_license({"tier": "pro"})
    tiers._LICENSE_CACHE = None
    assert tiers.can_do("cloud_sync") is True
    assert tiers.can_do("ci_sync") is True


def test_within_limit_free_max_keys():
    assert tiers.within_limit("max_keys", 14) is True
    assert tiers.within_limit("max_keys", 15) is False


def test_within_limit_pro_unlimited_keys():
    tiers.save_license({"tier": "pro"})
    tiers._LICENSE_CACHE = None
    assert tiers.within_limit("max_keys", 9999) is True


# ── token / offline grace ────────────────────────────────────────────────────

def test_save_and_load_token_roundtrip():
    payload = {"token": "tok_abc", "tier": "pro", "refreshed_at": datetime.now().isoformat()}
    tiers.save_token(payload)
    loaded = tiers.load_token()
    assert loaded["token"] == "tok_abc"
    assert loaded["tier"] == "pro"


def test_load_token_returns_none_when_missing():
    assert tiers.load_token() is None


def test_load_token_corrupt_returns_none():
    pushkey_shared.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    pushkey_shared.TOKEN_FILE.write_bytes(b"garbage")
    assert tiers.load_token() is None


def test_maybe_heartbeat_skips_free_tier():
    # free tier — should return early without touching token or server
    tiers._LICENSE_CACHE = {"tier": "free"}
    tiers.maybe_heartbeat()  # must not raise
    assert tiers.load_token() is None


def test_maybe_heartbeat_skips_when_token_fresh(monkeypatch):
    tiers.save_license({"tier": "pro", "license_key": "PRO-FAKE"})
    tiers._LICENSE_CACHE = None
    recent = datetime.now().isoformat()
    tiers.save_token({"token": "t", "tier": "pro", "refreshed_at": recent})

    calls = []
    monkeypatch.setattr(tiers, "server_heartbeat", lambda k: calls.append(k) or {})
    tiers.maybe_heartbeat()
    assert calls == []  # skip — refreshed < 24h ago


def test_maybe_heartbeat_downgrades_on_server_failure_beyond_grace(monkeypatch):
    tiers.save_license({"tier": "pro", "license_key": "PRO-FAKE"})
    tiers._LICENSE_CACHE = None
    old_ts = (datetime.now() - timedelta(days=15)).isoformat()
    tiers.save_token({"token": "t", "tier": "pro", "refreshed_at": old_ts})

    monkeypatch.setattr(tiers, "server_heartbeat", lambda k: None)
    tiers.maybe_heartbeat()
    assert tiers._LICENSE_CACHE["tier"] == "free"
    assert tiers._LICENSE_CACHE.get("_server_unreachable") is True


def test_heartbeat_reconciles_authoritative_tier_and_expiry(monkeypatch):
    tiers.save_license({"tier": "pro", "license_key": "PRO-OPAQUE"})
    monkeypatch.setattr(
        tiers,
        "server_heartbeat",
        lambda key: {
            "ok": True,
            "tier": "starter",
            "status": "active",
            "expires_at": "2030-01-01T00:00:00",
            "token": "rotated",
        },
    )
    tiers.maybe_heartbeat()
    license_data = tiers.load_license()
    assert license_data["tier"] == "starter"
    assert license_data["expires"] == "2030-01-01T00:00:00"


def test_heartbeat_revocation_immediately_updates_effective_license(monkeypatch):
    tiers.save_license({"tier": "pro", "license_key": "PRO-OPAQUE"})
    monkeypatch.setattr(
        tiers,
        "server_heartbeat",
        lambda key: {
            "ok": False,
            "error": "License revoked",
            "status_code": 403,
        },
    )
    tiers.maybe_heartbeat()
    assert tiers.load_license()["tier"] == "free"
    assert tiers.load_license()["status"] == "revoked"


# ── generate + activate (offline path) ──────────────────────────────────────

def test_generate_license_key_valid_checksum():
    key = tiers.generate_license_key("pro")
    parts = key.split("-")
    payload_parts = parts[1:-1]
    checksum = parts[-1]
    import hashlib
    expected = hashlib.sha256("-".join(payload_parts).encode()).hexdigest()[:8].upper()
    assert checksum == expected


def test_activate_license_bad_format_returns_false():
    ok, msg = tiers.activate_license("NOTAKEY")
    assert ok is False
    assert "format" in msg.lower() or "invalid" in msg.lower()


def test_activate_license_defers_key_validation_to_server(monkeypatch):
    key = tiers.generate_license_key("pro")
    tampered = key[:-1] + ("X" if key[-1] != "X" else "Y")
    monkeypatch.setattr(
        tiers,
        "server_activate",
        lambda *a, **k: (False, "License not found", {"status_code": 404}),
    )
    ok, msg = tiers.activate_license(tampered)
    assert ok is False
    assert "not found" in msg.lower()


def test_activate_license_unknown_tier_code_returns_false():
    # Craft key with unknown tier prefix
    import hashlib
    payload = "XXXXXXXX"
    checksum = hashlib.sha256(payload.encode()).hexdigest()[:8].upper()
    ok, msg = tiers.activate_license(f"ZZZ-{payload}-{checksum}")
    assert ok is False


def test_activate_license_server_unreachable_returns_false(monkeypatch):
    monkeypatch.setattr(tiers, "server_activate", lambda *a, **k: (False, "Could not reach activation server. Check your internet connection.", {}))
    key = tiers.generate_license_key("pro")
    ok, msg = tiers.activate_license(key)
    assert ok is False
    assert "server" in msg.lower() or "reach" in msg.lower()


def test_server_post_preserves_http_error_detail(monkeypatch):
    error = urllib.error.HTTPError(
        "https://example.test/v1/activate",
        409,
        "Conflict",
        {},
        io.BytesIO(b'{"detail":"Device limit reached"}'),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    result = tiers._server_post("/v1/activate", {"license_key": "PRO-OPAQUE"})
    assert result["status_code"] == 409
    assert result["error"] == "Device limit reached"


def test_activate_license_uses_server_authoritative_entitlement(monkeypatch):
    key = tiers.generate_license_key("pro", expires="2099-01-01T00:00:00")
    monkeypatch.setattr(
        tiers,
        "server_activate",
        lambda *a, **k: (
            True,
            "",
            {
                "ok": True,
                "tier": "starter",
                "status": "active",
                "expires_at": "2030-01-01T00:00:00",
                "token": "signed-token",
                "devices_used": 1,
                "devices_max": 1,
            },
        ),
    )

    ok, _ = tiers.activate_license(key)

    assert ok is True
    license_data = tiers.load_license()
    assert license_data["tier"] == "starter"
    assert license_data["expires"] == "2030-01-01T00:00:00"
    assert tiers.load_token()["tier"] == "starter"


@pytest.mark.parametrize(
    "bad_field,bad_value",
    [
        ("tier", "unknown"),
        ("status", "revoked"),
        ("expires_at", "not-a-date"),
        ("token", ""),
    ],
)
def test_malformed_successful_heartbeat_preserves_known_good_state(
    monkeypatch, bad_field, bad_value
):
    original_license = {
        "tier": "pro", "license_key": "PRO-OPAQUE", "status": "active"
    }
    tiers.save_license(original_license)
    tiers.save_token({
        "token": "known-good",
        "tier": "pro",
        "refreshed_at": (datetime.now() - timedelta(days=2)).isoformat(),
    })
    response = {
        "ok": True,
        "tier": "starter",
        "status": "active",
        "expires_at": "2030-01-01T00:00:00",
        "token": "rotated",
    }
    response[bad_field] = bad_value
    monkeypatch.setattr(tiers, "server_heartbeat", lambda _key: response)

    tiers.maybe_heartbeat()

    assert tiers.load_license() == original_license
    assert tiers.load_token()["token"] == "known-good"


def test_heartbeat_token_write_failure_rolls_back_both_files(monkeypatch):
    original_license = {
        "tier": "pro", "license_key": "PRO-OPAQUE", "status": "active"
    }
    tiers.save_license(original_license)
    tiers.save_token({
        "token": "known-good",
        "tier": "pro",
        "refreshed_at": (datetime.now() - timedelta(days=2)).isoformat(),
    })
    old_license_bytes = pushkey_shared.LICENSE_FILE.read_bytes()
    old_token_bytes = pushkey_shared.TOKEN_FILE.read_bytes()
    monkeypatch.setattr(tiers, "server_heartbeat", lambda _key: {
        "ok": True,
        "tier": "starter",
        "status": "active",
        "expires_at": "2030-01-01T00:00:00",
        "token": "rotated",
    })
    monkeypatch.setattr(
        tiers, "save_token", lambda _data: (_ for _ in ()).throw(OSError("disk full"))
    )

    tiers.maybe_heartbeat()

    assert pushkey_shared.LICENSE_FILE.read_bytes() == old_license_bytes
    assert pushkey_shared.TOKEN_FILE.read_bytes() == old_token_bytes
    assert tiers.load_license() == original_license

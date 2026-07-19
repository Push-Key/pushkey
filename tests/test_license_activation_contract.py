"""Contract tests for the canonical cloud license/device API."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSHKEY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUSHKEY_ADMIN_SECRET", "test-secret")
    monkeypatch.setenv("PUSHKEY_JWT_SECRET", "test-jwt-secret")
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "FROM_EMAIL"):
        monkeypatch.setenv(name, "")

    import importlib
    import sys

    sys.modules.pop("pushkey_cloud_api", None)
    return importlib.import_module("pushkey_cloud_api")


@pytest.fixture
def client(app_module):
    from fastapi.testclient import TestClient

    return TestClient(app_module.app)


ADMIN = {"X-Admin-Secret": "test-secret"}


def _issue(client, tier="pro", **overrides):
    body = {"tier": tier, "email": "contract@example.com"}
    body.update(overrides)
    response = client.post(
        "/api/admin/licenses/issue",
        headers=ADMIN,
        json=body,
    )
    assert response.status_code == 200
    return response.json()["key"]


def _activation(key, fingerprint="device-a", **overrides):
    body = {
        "license_key": key,
        "fingerprint": fingerprint,
        "platform": "TestOS",
        "email": "ignored@example.com",
    }
    body.update(overrides)
    return body


def test_activate_heartbeat_deactivate_lifecycle(client):
    key = _issue(client, "pro")

    activated = client.post("/v1/activate", json=_activation(key))
    assert activated.status_code == 200
    assert activated.json()["ok"] is True
    assert activated.json()["tier"] == "pro"
    assert activated.json()["status"] == "active"
    assert activated.json()["devices_used"] == 1
    assert activated.json()["devices_max"] == 3
    assert activated.json()["token"]

    heartbeat = client.post(
        "/v1/heartbeat",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": activated.json()["token"],
            "platform": "TestOS 2",
            "version": "1.2.3",
            "agent_token_count": 1,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["ok"] is True
    assert heartbeat.json()["tier"] == "pro"
    assert heartbeat.json()["status"] == "active"
    assert heartbeat.json()["token"]

    deactivated = client.post(
        "/v1/deactivate",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": heartbeat.json()["token"],
        },
    )
    assert deactivated.status_code == 200
    assert deactivated.json() == {"ok": True}

    rejected = client.post(
        "/v1/heartbeat",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": heartbeat.json()["token"],
        },
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "device_unregistered"


def test_activation_ignores_client_supplied_entitlement(client):
    key = _issue(client, "starter")

    response = client.post(
        "/v1/activate",
        json=_activation(key, tier="enterprise", max_devices=None),
    )

    assert response.status_code == 200
    assert response.json()["tier"] == "starter"
    assert response.json()["devices_max"] == 1


def test_activation_enforces_server_device_limit(client):
    key = _issue(client, "starter")
    first = client.post("/v1/activate", json=_activation(key, "device-a"))
    assert first.status_code == 200

    second = client.post("/v1/activate", json=_activation(key, "device-b"))

    assert second.status_code == 409
    assert second.json()["detail"] == {
        "code": "device_limit_reached",
        "message": "Device limit reached (1 device for Starter plan).",
    }


def test_heartbeat_rejects_tampered_device_token(client):
    key = _issue(client, "pro")
    activated = client.post("/v1/activate", json=_activation(key)).json()
    token = activated["token"]
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")

    response = client.post(
        "/v1/heartbeat",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": tampered,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "token_expired"


def test_deactivate_requires_signed_device_token(client):
    key = _issue(client, "pro")
    client.post("/v1/activate", json=_activation(key))
    response = client.post(
        "/v1/deactivate",
        json={"license_key": key, "fingerprint": "device-a"},
    )
    assert response.status_code == 403


def test_concurrent_activation_cannot_exceed_device_limit(client):
    key = _issue(client, "starter")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda fingerprint: client.post(
                    "/v1/activate", json=_activation(key, fingerprint)
                ),
                ("device-a", "device-b"),
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_admin_revoke_cannot_lose_concurrent_activation(
    client, app_module, monkeypatch
):
    key = _issue(client, "pro")
    save_started = threading.Event()
    allow_save = threading.Event()
    original_save = app_module._save_licenses
    first = True

    def controlled_save(licenses):
        nonlocal first
        if first:
            first = False
            save_started.set()
            assert allow_save.wait(5)
        original_save(licenses)

    monkeypatch.setattr(app_module, "_save_licenses", controlled_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        activation = pool.submit(
            client.post, "/v1/activate", json=_activation(key)
        )
        assert save_started.wait(5)
        revocation = pool.submit(
            client.post, f"/api/admin/licenses/{key}/revoke", headers=ADMIN
        )
        allow_save.set()
        assert activation.result().status_code == 200
        assert revocation.result().status_code == 200

    entry = app_module._load_licenses()[key]
    assert entry["status"] == "revoked"
    assert "device-a" in entry["devices"]


def test_rate_limiter_is_bounded_and_keeps_active_entries(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "RATE_LIMIT_MAX_ENTRIES", 3)
    bucket = {}
    for key in ("a", "b", "c", "d"):
        assert app_module._rate_check(bucket, key, 10, 60)
    assert len(bucket) == 3
    assert "d" in bucket


def test_shared_proxy_uses_identity_and_global_limits(app_module):
    request = object()
    bucket = {}
    assert app_module._rate_check_request(bucket, "license-a", request, 1, 60)
    assert app_module._rate_check_request(bucket, "license-b", request, 1, 60)
    assert set(bucket) == {"identity:license-a", "identity:license-b", "global"}


def test_checked_openapi_documents_aliases_errors_and_expiry():
    spec = json.loads(
        (Path(__file__).parents[1] / "docs" / "cloud-license-v1.openapi.json").read_text()
    )
    for name in ("activate", "heartbeat", "deactivate"):
        assert f"/v1/{name}" in spec["paths"]
        assert f"/api/v1/{name}" in spec["paths"]
    assert "ErrorResponse" in spec["components"]["schemas"]
    heartbeat = spec["components"]["schemas"]["HeartbeatResponse"]
    assert heartbeat["properties"]["expires_at"]["format"] == "date-time"
    for path in ("/v1/activate", "/v1/heartbeat", "/v1/deactivate"):
        responses = spec["paths"][path]["post"]["responses"]
        assert "400" in responses
        assert "429" in responses


def test_activate_and_deactivate_are_rate_limited(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "RATE_LIMIT_MAX", 1)
    key = _issue(client, "pro")
    activated = client.post("/v1/activate", json=_activation(key))
    assert activated.status_code == 200
    assert client.post("/v1/activate", json=_activation(key)).status_code == 429

    payload = {
        "license_key": key,
        "fingerprint": "device-a",
        "token": activated.json()["token"],
    }
    assert client.post("/v1/deactivate", json=payload).status_code == 200
    assert client.post("/v1/deactivate", json=payload).status_code == 429


def test_admin_issued_key_activates_through_tiers_client(
    client, monkeypatch, tmp_path
):
    import pushkey_shared
    import pushkey_tiers

    key = _issue(client, "starter")
    monkeypatch.setattr(pushkey_shared, "LICENSE_FILE", tmp_path / ".license")
    monkeypatch.setattr(pushkey_shared, "TOKEN_FILE", tmp_path / ".token")
    monkeypatch.setattr(pushkey_shared, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey_tiers, "get_machine_fingerprint", lambda: "device-e2e")
    pushkey_tiers._LICENSE_CACHE = None

    def post_to_canonical(path, payload, timeout=8):
        response = client.post(path, json=payload)
        data = response.json()
        if response.status_code >= 400:
            return {
                "ok": False,
                "error": (data.get("detail") or {}).get("message", "rejected")
                if isinstance(data.get("detail"), dict)
                else data.get("detail", "rejected"),
                "status_code": response.status_code,
            }
        return data

    monkeypatch.setattr(pushkey_tiers, "_server_post", post_to_canonical)
    ok, _ = pushkey_tiers.activate_license(key)
    assert ok is True
    assert pushkey_tiers.load_license()["tier"] == "starter"


def test_activation_rejects_expired_license(client, app_module):
    key = _issue(client, "pro")
    licenses = app_module._load_licenses()
    licenses[key]["expires_at"] = (
        app_module._utcnow() - timedelta(seconds=1)
    ).isoformat()
    app_module._save_licenses(licenses)

    response = client.post("/v1/activate", json=_activation(key))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "license_expired"


def test_activation_reports_invalid_server_tier(client, app_module):
    key = _issue(client, "pro")
    app_module._mutate_licenses(
        lambda licenses: licenses[key].update({"tier": "not-a-tier"})
    )

    response = client.post("/v1/activate", json=_activation(key))

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "invalid_license_tier",
        "message": "License has invalid tier",
    }


def test_compatibility_aliases_match_v1_contract(client):
    key = _issue(client, "pro")

    activated = client.post("/api/v1/activate", json=_activation(key))
    assert activated.status_code == 200
    token = activated.json()["token"]

    heartbeat = client.post(
        "/api/v1/heartbeat",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": token,
        },
    )
    assert heartbeat.status_code == 200

    deactivated = client.post(
        "/api/v1/deactivate",
        json={
            "license_key": key,
            "fingerprint": "device-a",
            "token": heartbeat.json()["token"],
        },
    )
    assert deactivated.status_code == 200

import importlib
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSHKEY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUSHKEY_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PUSHKEY_ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("PUSHKEY_ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("PUSHKEY_JWT_SECRET", "test-jwt-secret")
    if "pushkey_cloud_api" in sys.modules:
        del sys.modules["pushkey_cloud_api"]
    return importlib.import_module("pushkey_cloud_api")


@pytest.fixture
def user_client(app_module):
    client = TestClient(app_module.app)
    assert client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    ).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_vault_put_rejects_stale_if_match_without_overwriting(user_client):
    client, auth = user_client
    first = client.put("/api/v1/vault", headers=auth, content=b"encrypted-v1")
    assert first.status_code == 200
    current = first.json()["etag"]
    second = client.put("/api/v1/vault", headers=auth, content=b"encrypted-v2")
    assert second.status_code == 200

    stale = client.put(
        "/api/v1/vault",
        headers={**auth, "If-Match": current},
        content=b"stale-overwrite",
    )

    assert stale.status_code == 409
    assert stale.json()["current_etag"] == second.json()["etag"]
    downloaded = client.get("/api/v1/vault", headers=auth)
    assert downloaded.content == b"encrypted-v2"


def test_vault_put_records_version_history_and_replays_idempotent_retry(user_client):
    client, auth = user_client
    first = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Idempotency-Key": "same-write"},
        content=b"encrypted-v1",
    )
    retry = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Idempotency-Key": "same-write"},
        content=b"different-body-ignored",
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()

    second = client.put("/api/v1/vault", headers=auth, content=b"encrypted-v2")
    assert second.status_code == 200

    history = client.get("/api/v1/vault/history", headers=auth)
    assert history.status_code == 200
    assert history.json()["versions"][0]["etag"] == first.json()["etag"]
    assert client.get("/api/v1/vault", headers=auth).content == b"encrypted-v2"


def test_account_export_and_delete_include_metadata_without_plaintext_vault(user_client):
    client, auth = user_client
    uploaded = client.put("/api/v1/vault", headers=auth, content=b"encrypted-only")
    assert uploaded.status_code == 200

    exported = client.get("/api/v1/account/export", headers=auth)
    assert exported.status_code == 200
    body = exported.json()
    assert body["account"]["email"] == "user@example.com"
    assert body["vault"]["exists"] is True
    assert body["vault"]["etag"] == uploaded.json()["etag"]
    assert "encrypted-only" not in exported.text

    deleted = client.delete("/api/v1/account", headers=auth)
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get("/api/v1/vault", headers=auth).status_code == 401


def test_user_tokens_include_standard_claims_and_unique_ids(app_module):
    token_a = app_module._create_token("user@example.com")
    token_b = app_module._create_token("user@example.com")

    payload = app_module.jwt.decode(
        token_a,
        app_module.SECRET_KEY,
        algorithms=[app_module.ALGORITHM],
        audience=app_module.TOKEN_AUDIENCE,
        issuer=app_module.TOKEN_ISSUER,
    )

    assert payload["sub"] == "user@example.com"
    assert payload["aud"] == app_module.TOKEN_AUDIENCE
    assert payload["iss"] == app_module.TOKEN_ISSUER
    assert payload["iat"] <= payload["exp"]
    assert payload["jti"]
    assert payload["jti"] != app_module.jwt.get_unverified_claims(token_b)["jti"]
    assert app_module.TOKEN_TTL_HOURS <= 1


def test_user_token_decode_accepts_previous_signing_key_during_rotation(app_module):
    token = app_module.jwt.encode(
        {
            "iss": app_module.TOKEN_ISSUER,
            "aud": app_module.TOKEN_AUDIENCE,
            "sub": "user@example.com",
            "iat": 1,
            "exp": 4102444800,
            "jti": "old-key-token",
        },
        "previous-secret",
        algorithm=app_module.ALGORITHM,
    )
    app_module.TOKEN_SIGNING_KEYS[:] = [app_module.SECRET_KEY, "previous-secret"]

    assert app_module._decode_token(token) == "user@example.com"


def test_concurrent_license_contact_and_vault_writes_do_not_crash(app_module):
    admin_client = TestClient(app_module.app)
    login = admin_client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert login.status_code == 200
    admin_headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    user_client = TestClient(app_module.app)
    assert user_client.post(
        "/api/v1/auth/register",
        json={"email": "concurrent@example.com", "password": "correct horse battery staple"},
    ).status_code == 200
    user_token = user_client.post(
        "/api/v1/auth/login",
        json={"email": "concurrent@example.com", "password": "correct horse battery staple"},
    ).json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}
    assert admin_client.post(
        "/api/admin/licenses/issue",
        headers=admin_headers,
        json={"tier": "pro", "email": "lead-1@example.com", "send_email": False},
    ).status_code == 200
    assert admin_client.post(
        "/api/admin/licenses/issue",
        headers=admin_headers,
        json={"tier": "pro", "email": "lead-2@example.com", "send_email": False},
    ).status_code == 200

    def write_license(index):
        return admin_client.post(
            "/api/admin/licenses/issue",
            headers=admin_headers,
            json={
                "tier": "pro",
                "email": f"lead-{index}@example.com",
                "send_email": False,
            },
        ).status_code

    def write_contact(index):
        return admin_client.patch(
            f"/api/admin/contacts/lead-{index}@example.com",
            headers=admin_headers,
            json={"stage": "qualified"},
        ).status_code

    def write_vault(index):
        return user_client.put(
            "/api/v1/vault",
            headers=user_headers,
            content=f"encrypted-{index}".encode(),
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(lambda fn: fn(), [
            lambda: write_license(3),
            lambda: write_license(4),
            lambda: write_contact(1),
            lambda: write_contact(2),
            lambda: write_vault(1),
            lambda: write_vault(2),
        ]))

    assert all(status in {200, 409} for status in statuses)
    assert admin_client.get("/api/admin/contacts", headers=admin_headers).status_code == 200
    assert user_client.get("/api/v1/vault", headers=user_headers).status_code == 200

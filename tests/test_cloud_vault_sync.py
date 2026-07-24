import hashlib
import importlib
import json
import os
import runpy
import sys
import sqlite3
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

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


def _vault_rows(app_module, email):
    user_key = hashlib.sha256(email.encode()).hexdigest()
    with sqlite3.connect(app_module.VAULT_STORE_DB) as conn:
        conn.row_factory = sqlite3.Row
        current = conn.execute(
            """
            SELECT revision_number, etag, size_bytes, updated_at
            FROM vault_current
            WHERE user_key = ?
            """,
            (user_key,),
        ).fetchone()
        history = conn.execute(
            """
            SELECT revision_number, etag, size_bytes, stored_at
            FROM vault_history
            WHERE user_key = ?
            ORDER BY revision_number ASC, id ASC
            """,
            (user_key,),
        ).fetchall()
    return current, history


def _transaction_rows(app_module, email):
    user_key = hashlib.sha256(email.encode()).hexdigest()
    with sqlite3.connect(app_module.VAULT_STORE_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT revision_number, object_key, etag, previous_etag, object_sha256,
                   size_bytes, idempotency_key, request_id, committed_at
            FROM vault_revision_transactions
            WHERE user_id = ?
            ORDER BY revision_number ASC, id ASC
            """,
            (user_key,),
        ).fetchall()
    return rows


def _snapshot_sqlite_files(db_path: Path, snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    # SQLite's -shm sidecar is shared-memory metadata and can be recreated on
    # restore. Copying it on Windows while the database is open can fail.
    for suffix in ("", "-wal"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            shutil.copy2(src, snapshot_dir / src.name)
    vault_object_dir = db_path.parent / "vault_objects"
    if vault_object_dir.exists():
        shutil.copytree(vault_object_dir, snapshot_dir / vault_object_dir.name)


def _restore_sqlite_files(db_path: Path, snapshot_dir: Path) -> None:
    for suffix in ("", "-wal"):
        src = snapshot_dir / (db_path.name + suffix)
        dst = Path(str(db_path) + suffix)
        if src.exists():
            shutil.copy2(src, dst)
        else:
            dst.unlink(missing_ok=True)
    snapshot_object_dir = snapshot_dir / "vault_objects"
    target_object_dir = db_path.parent / "vault_objects"
    if snapshot_object_dir.exists():
        shutil.rmtree(target_object_dir, ignore_errors=True)
        shutil.copytree(snapshot_object_dir, target_object_dir)
    else:
        shutil.rmtree(target_object_dir, ignore_errors=True)
    # Leave the -shm sidecar alone. SQLite recreates it on reconnect, and
    # trying to delete it on Windows while the database has been opened can
    # fail even after the test client is closed.


def test_vault_database_url_normalizes_postgres_scheme(app_module):
    assert (
        app_module._normalize_database_url("postgres://db.example/pushkey")
        == "postgresql+psycopg://db.example/pushkey"
    )
    assert (
        app_module._normalize_database_url("postgresql://db.example/pushkey")
        == "postgresql+psycopg://db.example/pushkey"
    )
    assert app_module._normalize_database_url("sqlite:///tmp/pushkey.sqlite") == "sqlite:///tmp/pushkey.sqlite"


def test_vault_store_prefers_explicit_postgres_metadata_url(tmp_path, monkeypatch, app_module):
    captured = {}

    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        dialect = FakeDialect()

    fake_engine = FakeEngine()

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_engine

    created_engines = []

    monkeypatch.setattr(app_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        app_module._VAULT_METADATA,
        "create_all",
        lambda engine: created_engines.append(engine),
    )

    store = app_module._VaultStore(
        tmp_path / "vaults.sqlite",
        tmp_path / "legacy",
        metadata_url="postgres://db.example/pushkey",
    )

    assert captured["url"] == "postgresql+psycopg://db.example/pushkey"
    assert captured["kwargs"]["poolclass"] is app_module.NullPool
    assert "connect_args" not in captured["kwargs"]
    assert created_engines == [fake_engine]
    assert store._dialect_name == "postgresql"


def test_vault_put_rejects_stale_if_match_without_overwriting(user_client, app_module):
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
    current, history = _vault_rows(app_module, "user@example.com")
    assert current["etag"] == second.json()["etag"]
    assert [row["etag"] for row in history] == [first.json()["etag"]]


def test_vault_put_records_version_history_and_replays_idempotent_retry(user_client, app_module):
    client, auth = user_client
    first = client.put(
        "/api/v1/vault",
        headers={
            **auth,
            "X-Idempotency-Key": "same-write",
            "X-Request-ID": "same-write-request",
        },
        content=b"encrypted-v1",
    )
    assert first.status_code == 200

    reloaded = importlib.reload(app_module)
    with TestClient(reloaded.app) as fresh_client:
        retry = fresh_client.put(
            "/api/v1/vault",
            headers={
                **auth,
                "X-Idempotency-Key": "same-write",
                "X-Request-ID": "same-write-request",
            },
            content=b"different-body-ignored",
        )
        assert retry.status_code == 200
        assert retry.json() == first.json()

        second = fresh_client.put(
            "/api/v1/vault",
            headers={**auth, "X-Request-ID": "same-write-request-2"},
            content=b"encrypted-v2",
        )
        assert second.status_code == 200

        history = fresh_client.get("/api/v1/vault/history", headers=auth)
        assert history.status_code == 200
        assert history.json()["versions"][0]["etag"] == first.json()["etag"]
        assert fresh_client.get("/api/v1/vault", headers=auth).content == b"encrypted-v2"

    current, history_rows = _vault_rows(reloaded, "user@example.com")
    transactions = _transaction_rows(reloaded, "user@example.com")
    assert current["etag"] == second.json()["etag"]
    assert [row["etag"] for row in history_rows] == [first.json()["etag"]]
    assert [row["object_sha256"] for row in transactions] == [
        hashlib.sha256(b"encrypted-v1").hexdigest(),
        hashlib.sha256(b"encrypted-v2").hexdigest(),
    ]
    assert transactions[0]["idempotency_key"] == "same-write"
    assert transactions[0]["request_id"] == "same-write-request"
    assert transactions[0]["previous_etag"] is None
    assert transactions[1]["idempotency_key"] is None
    assert transactions[1]["previous_etag"] == first.json()["etag"]
    assert len(list(reloaded.VAULT_OBJECTS_DIR.glob("*.blob"))) == 2
    assert not list(reloaded.DATA_DIR.rglob("*.enc"))


def test_vault_idempotency_persists_across_app_instances(tmp_path):
    first = _load_isolated_cloud_module("pushkey_cloud_api_vault_idem_a", tmp_path)
    second = _load_isolated_cloud_module("pushkey_cloud_api_vault_idem_b", tmp_path)

    with TestClient(first.app) as first_client, TestClient(second.app) as second_client:
        assert first_client.post(
            "/api/v1/auth/register",
            json={"email": "idem@example.com", "password": "correct horse battery staple"},
        ).status_code == 200

        first_login = first_client.post(
            "/api/v1/auth/login",
            json={"email": "idem@example.com", "password": "correct horse battery staple"},
        )
        assert first_login.status_code == 200
        first_auth = {"Authorization": f"Bearer {first_login.json()['token']}"}

        first_put = first_client.put(
            "/api/v1/vault",
            headers={
                **first_auth,
                "X-Idempotency-Key": "shared-idempotency-key",
                "X-Request-ID": "shared-idempotency-request-1",
            },
            content=b"encrypted-idempotent-v1",
        )
        assert first_put.status_code == 200

        second_login = second_client.post(
            "/api/v1/auth/login",
            json={"email": "idem@example.com", "password": "correct horse battery staple"},
        )
        assert second_login.status_code == 200
        second_auth = {"Authorization": f"Bearer {second_login.json()['token']}"}

        retry = second_client.put(
            "/api/v1/vault",
            headers={
                **second_auth,
                "X-Idempotency-Key": "shared-idempotency-key",
                "X-Request-ID": "shared-idempotency-request-2",
            },
            content=b"different-body-ignored",
        )

        assert retry.status_code == 200
        assert retry.json() == first_put.json()
        transactions = _transaction_rows(first, "idem@example.com")
        assert len(transactions) == 1
        assert transactions[0]["idempotency_key"] == "shared-idempotency-key"
        assert len(list(first.VAULT_OBJECTS_DIR.glob("*.blob"))) == 1


def test_account_export_and_delete_include_metadata_without_plaintext_vault(user_client, app_module):
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
    current, history = _vault_rows(app_module, "user@example.com")
    transactions = _transaction_rows(app_module, "user@example.com")
    assert current is None
    assert history == []
    assert transactions == []
    assert not list(app_module.VAULT_OBJECTS_DIR.glob("*.blob"))
    assert not list(app_module.DATA_DIR.rglob("*.enc"))


def test_vault_snapshot_restore_recovers_metadata_and_blob_together(
    user_client, app_module, tmp_path, monkeypatch
):
    client, auth = user_client
    first = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Request-ID": "restore-seed-1"},
        content=b"encrypted-v1",
    )
    assert first.status_code == 200
    second = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Request-ID": "restore-seed-2"},
        content=b"encrypted-v2",
    )
    assert second.status_code == 200

    snapshot_dir = tmp_path / "snapshot"
    _snapshot_sqlite_files(app_module.VAULT_STORE_DB, snapshot_dir)

    mutated = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Request-ID": "restore-mutate"},
        content=b"encrypted-v3",
    )
    assert mutated.status_code == 200

    # Release SQLite handles before swapping the snapshot back in on Windows.
    client.close()
    restore_dir = tmp_path / "restore"
    restore_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PUSHKEY_DATA_DIR", str(restore_dir))
    _restore_sqlite_files(restore_dir / app_module.VAULT_STORE_DB.name, snapshot_dir)
    reloaded = importlib.reload(app_module)
    with TestClient(reloaded.app) as fresh_client:
        login = fresh_client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        fresh_auth = {"Authorization": f"Bearer {login.json()['token']}"}

        downloaded = fresh_client.get("/api/v1/vault", headers=fresh_auth)
        assert downloaded.status_code == 200
        assert downloaded.content == b"encrypted-v2"
        meta = fresh_client.get("/api/v1/vault/meta", headers=fresh_auth)
        assert meta.status_code == 200
        assert meta.json()["etag"] == second.json()["etag"]

    current, history_rows = _vault_rows(reloaded, "user@example.com")
    transactions = _transaction_rows(reloaded, "user@example.com")
    assert current["etag"] == second.json()["etag"]
    assert [row["etag"] for row in history_rows] == [first.json()["etag"]]
    assert [row["object_sha256"] for row in transactions] == [
        hashlib.sha256(b"encrypted-v1").hexdigest(),
        hashlib.sha256(b"encrypted-v2").hexdigest(),
    ]
    assert [row["request_id"] for row in transactions] == ["restore-seed-1", "restore-seed-2"]
    assert len(list(reloaded.VAULT_OBJECTS_DIR.glob("*.blob"))) == 2


def test_vault_zero_knowledge_metadata_logs_and_exports_do_not_echo_blob(user_client, app_module):
    client, auth = user_client
    sentinel = b"plaintext-looking-secret=sk-test-do-not-log"
    uploaded = client.put(
        "/api/v1/vault",
        headers={**auth, "X-Request-ID": "zk-test-1"},
        content=sentinel,
    )
    assert uploaded.status_code == 200

    meta = client.get("/api/v1/vault/meta", headers=auth)
    history = client.get("/api/v1/vault/history", headers=auth)
    exported = client.get("/api/v1/account/export", headers=auth)
    metrics = client.get("/api/v1/ops/metrics")

    assert meta.status_code == 200
    assert history.status_code == 200
    assert exported.status_code == 200
    assert metrics.status_code == 200

    forbidden = sentinel.decode("ascii")
    assert forbidden not in uploaded.text
    assert forbidden not in meta.text
    assert forbidden not in history.text
    assert forbidden not in exported.text
    assert forbidden not in metrics.text
    assert forbidden not in json.dumps(list(app_module.app.state.request_logs))
    assert forbidden not in json.dumps(list(app_module.app.state.alerts))


def test_sync_cors_allows_conflict_and_idempotency_headers(app_module):
    client = TestClient(app_module.app)

    response = client.options(
        "/api/v1/vault",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": (
                "authorization,content-type,if-match,if-none-match,"
                "x-idempotency-key,x-request-id"
            ),
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "if-match" in allowed
    assert "if-none-match" in allowed
    assert "x-idempotency-key" in allowed


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


def _load_isolated_cloud_module(name: str, data_dir: Path):
    env = {
        "PUSHKEY_DATA_DIR": str(data_dir),
        "PUSHKEY_ADMIN_EMAIL": "admin@example.com",
        "PUSHKEY_ADMIN_PASSWORD": "admin-pass-123",
        "PUSHKEY_ADMIN_COOKIE_SECURE": "false",
        "PUSHKEY_JWT_SECRET": "shared-multi-instance-secret",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        module_globals = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pushkey_cloud_api.py"), run_name=name)
    return type("CloudApiModule", (), module_globals)


def test_shared_alpha_data_survives_independent_app_instances(tmp_path):
    first = _load_isolated_cloud_module("pushkey_cloud_api_instance_a", tmp_path)
    second = _load_isolated_cloud_module("pushkey_cloud_api_instance_b", tmp_path)
    first_client = TestClient(first.app)
    second_client = TestClient(second.app)

    registered = first_client.post(
        "/api/v1/auth/register",
        json={"email": "multi@example.com", "password": "correct horse battery staple"},
    )
    assert registered.status_code == 200
    first_token = registered.json()["token"]
    auth = {"Authorization": f"Bearer {first_token}"}

    uploaded = first_client.put("/api/v1/vault", headers=auth, content=b"encrypted-multi-instance-vault")
    assert uploaded.status_code == 200

    login_from_second = second_client.post(
        "/api/v1/auth/login",
        json={"email": "multi@example.com", "password": "correct horse battery staple"},
    )
    assert login_from_second.status_code == 200
    second_auth = {"Authorization": f"Bearer {login_from_second.json()['token']}"}

    assert second_client.get("/api/v1/vault", headers=second_auth).content == b"encrypted-multi-instance-vault"
    assert second_client.get("/api/v1/vault/meta", headers=auth).json()["etag"] == uploaded.json()["etag"]

    first_admin_login = first_client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert first_admin_login.status_code == 200
    admin_headers = {"X-CSRF-Token": first_admin_login.json()["csrf_token"]}
    issued = first_client.post(
        "/api/admin/licenses/issue",
        headers=admin_headers,
        json={"tier": "starter", "email": "buyer@example.com", "send_email": False},
    )
    assert issued.status_code == 200
    license_key = issued.json()["key"]

    activated = second_client.post(
        "/api/v1/activate",
        json={
            "license_key": license_key,
            "fingerprint": "shared-device",
            "platform": "windows",
            "version": "alpha",
        },
    )
    assert activated.status_code == 200

    logout = first_client.post("/api/admin/auth/logout", headers=admin_headers)
    assert logout.status_code == 200
    assert first_client.get("/api/admin/stats", headers=admin_headers).status_code == 401

"""Client-side cloud sync conflict handling.

The cloud server implements optimistic concurrency (If-Match -> 409 with the
current ETag), but that protection is only real if the shipped client actually
sends If-Match and refuses to clobber on conflict. These tests pin that the
client does both. The server half is covered by
test_vault_put_rejects_stale_if_match_without_overwriting.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

import pushkey


def _fake_http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://sync.example.invalid/api/v1/vault",
        code,
        "conflict",
        {},
        io.BytesIO(body),
    )


def test_cloud_push_sends_if_match_when_an_etag_is_known(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["if_match"] = request.get_header("If-match")
        return io.BytesIO(b'{"etag": "etag-2"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    etag = pushkey.cloud_push(
        "https://sync.example.invalid", "token", b"encrypted", if_match="etag-1"
    )

    assert etag == "etag-2"
    assert seen["if_match"] == "etag-1"


def test_cloud_push_first_push_sends_no_if_match(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["if_match"] = request.get_header("If-match")
        return io.BytesIO(b'{"etag": "etag-1"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pushkey.cloud_push("https://sync.example.invalid", "token", b"encrypted")

    assert seen["if_match"] is None


def test_cloud_push_raises_conflict_with_current_etag_on_409(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise _fake_http_error(409, b'{"detail": "conflict", "current_etag": "etag-remote"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(pushkey.CloudSyncConflict) as excinfo:
        pushkey.cloud_push(
            "https://sync.example.invalid", "token", b"encrypted", if_match="etag-stale"
        )

    assert excinfo.value.current_etag == "etag-remote"


def test_cloud_push_reraises_non_conflict_http_errors(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise _fake_http_error(500, b'{"detail": "boom"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        pushkey.cloud_push("https://sync.example.invalid", "token", b"encrypted")

"""Every outbound request must go through the http/https scheme guard.

urllib also understands `file:`, `ftp:`, and `data:`. Endpoints reach urlopen
from configuration -- PUSHKEY_SERVER, ACTIVATION_SERVER, PROVIDERS_REGISTRY_URL,
and provider entries in a user-editable providers.json -- so an unguarded call
could be pointed at `file:///etc/passwd` and have the contents read back, and in
the sync paths uploaded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import pushkey_shared


ROOT = Path(__file__).resolve().parents[1]

#: Modules that make outbound requests.
NETWORK_MODULES = (
    "pushkey.py",
    "pushkey_cli.py",
    "pushkey_providers.py",
    "pushkey_tiers.py",
)

DIRECT_URLOPEN = re.compile(r"urllib\.request\.urlopen\s*\(")


@pytest.mark.parametrize("module", NETWORK_MODULES)
def test_modules_never_call_urlopen_directly(module):
    source = (ROOT / module).read_text(encoding="utf-8")

    offenders = [
        line_number
        for line_number, line in enumerate(source.splitlines(), start=1)
        if DIRECT_URLOPEN.search(line)
    ]

    assert offenders == [], (
        f"{module} calls urllib.request.urlopen directly at line(s) {offenders}; "
        "use pushkey_shared.urlopen_checked so the scheme is validated"
    )


def test_only_pushkey_shared_holds_the_sanctioned_urlopen():
    source = (ROOT / "pushkey_shared.py").read_text(encoding="utf-8")

    assert len(DIRECT_URLOPEN.findall(source)) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://C:/Windows/win.ini",
        "ftp://example.com/secrets",
        "data:text/plain;base64,c2VjcmV0",
        "gopher://example.com",
    ],
)
def test_guard_refuses_non_http_schemes(url):
    with pytest.raises(pushkey_shared.UnsafeURLSchemeError):
        pushkey_shared.urlopen_checked(url, timeout=1)


def test_guard_refuses_a_scheme_less_url():
    with pytest.raises(pushkey_shared.UnsafeURLSchemeError):
        pushkey_shared.urlopen_checked("/etc/passwd", timeout=1)


def test_guard_checks_the_scheme_of_request_objects_too():
    import urllib.request

    request = urllib.request.Request("file:///etc/passwd")

    with pytest.raises(pushkey_shared.UnsafeURLSchemeError):
        pushkey_shared.urlopen_checked(request, timeout=1)


def test_guard_is_case_insensitive():
    with pytest.raises(pushkey_shared.UnsafeURLSchemeError):
        pushkey_shared.urlopen_checked("FILE:///etc/passwd", timeout=1)


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com"])
def test_guard_admits_http_and_https(url, monkeypatch):
    opened = {}

    def fake_urlopen(request, timeout=None):
        opened["url"] = request if isinstance(request, str) else request.full_url
        return "response"

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert pushkey_shared.urlopen_checked(url, timeout=5) == "response"
    assert opened["url"] == url

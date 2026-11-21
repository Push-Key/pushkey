"""Encrypted config storage must round-trip whatever the random nonce looks like."""
import json

import pytest

import pushkey_shared
import pushkey_vault


CONFIG = {"projects": {"C:/work/proj": {"name": "proj", "created": "2026-11-21"}}}


@pytest.mark.parametrize("prefix", [b"{", b" {", b"\n{"])
def test_encrypted_config_survives_a_nonce_that_looks_like_json(monkeypatch, prefix):
    # The 12-byte AES-GCM nonce is random, so roughly 1 save in 250 starts with
    # "{" (optionally after whitespace). load_config must still decrypt it rather
    # than mistake it for a legacy plaintext file and report no projects.
    real_token_bytes = pushkey_vault.secrets.token_bytes
    # A scoped context: monkeypatch.undo() would also undo conftest's path
    # isolation and point CONFIG_FILE back at the real ~/.pushkey.
    with monkeypatch.context() as patch:
        patch.setattr(
            pushkey_vault.secrets, "token_bytes", lambda n: (prefix + real_token_bytes(n))[:n]
        )
        pushkey_vault.save_config(CONFIG)
    assert pushkey_shared.CONFIG_FILE.read_bytes().lstrip()[:1] == b"{"  # the trap is armed

    assert pushkey_vault.load_config() == CONFIG


def test_legacy_plaintext_config_still_loads_and_is_re_encrypted():
    pushkey_shared.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(CONFIG).encode()
    pushkey_shared.CONFIG_FILE.write_bytes(original)

    assert pushkey_vault.load_config() == CONFIG

    migrated = pushkey_shared.CONFIG_FILE.read_bytes()
    assert migrated != original
    with pytest.raises(ValueError):
        json.loads(migrated)
    assert pushkey_vault.load_config() == CONFIG

"""
CLI agent-token auth: --token / PUSHKEY_AGENT_TOKEN / pk_agent_-prefixed
--password all unlock via a scoped token instead of the master password, and
_require_command_scope gates each subcommand the same way pushkey_mcp.py's
_require_scope gates MCP tools. Vault paths (including AGENT_TOKENS_FILE) are
isolated to tmp_path by the autouse fixture in tests/conftest.py.
"""
from argparse import Namespace

import pytest

import pushkey_agent_tokens as at
import pushkey_cli as cli
from pushkey_crypto import generate_recovery_code
from pushkey_vault import load_vault, save_vault


PASSWORD = "cli-agent-token-password"


@pytest.fixture
def licensed_tier(monkeypatch):
    # "team" (5 agent-token limit) rather than "pro" (1) so tests can mint
    # more than one token per vault without tripping the tier limit that
    # tests/test_agent_tokens.py already covers directly.
    import pushkey_tiers
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "team")


@pytest.fixture
def vault_key(licensed_tier):
    """Create a V3 vault with one key and return its raw vault_key."""
    recovery = generate_recovery_code()
    save_vault({"EXISTING_KEY": {
        "value": "sk-existing", "created": "2026-01-01", "rotated": None,
        "provider": None, "env": "all", "projects": [], "notes": "",
    }}, PASSWORD, recovery_code=recovery)
    _, vk = load_vault(PASSWORD)
    return vk


def _mint(vault_key, scopes, name="agent"):
    ok, token_value, token_id = at.create_token(name, scopes, vault_key)
    assert ok, token_value
    return token_value, token_id


# ── _open_vault: the three ways a token can be supplied ─────────────────────

def test_open_vault_with_token_arg(vault_key):
    token, _ = _mint(vault_key, ["read"])

    vault, password, vk, scopes = cli._open_vault(Namespace(token=token, password=None))

    assert "EXISTING_KEY" in vault
    assert password is None
    assert vk == vault_key
    assert scopes == ["read"]


def test_open_vault_with_env_var(monkeypatch, vault_key):
    token, _ = _mint(vault_key, ["write"])
    monkeypatch.setenv("PUSHKEY_AGENT_TOKEN", token)

    vault, password, vk, scopes = cli._open_vault(Namespace(token=None, password=None))

    assert password is None
    assert scopes == ["write"]


def test_open_vault_with_pk_agent_prefixed_password(vault_key):
    """cli --password pk_agent_... is treated as a token, mirroring MCP's
    unlock_vault(password) overload rather than requiring a separate flag."""
    token, _ = _mint(vault_key, ["inject"])

    vault, password, vk, scopes = cli._open_vault(Namespace(token=None, password=token))

    assert password is None
    assert scopes == ["inject"]


def test_open_vault_token_arg_takes_priority_over_master_env(monkeypatch, vault_key):
    monkeypatch.setenv("PUSHKEY_MASTER", "wrong-password-entirely")
    token, _ = _mint(vault_key, ["read"])

    vault, password, vk, scopes = cli._open_vault(Namespace(token=token, password=None))

    assert scopes == ["read"]


# ── _open_vault: rejection paths ─────────────────────────────────────────────

def test_open_vault_garbage_token_exits_auth(vault_key):
    with pytest.raises(SystemExit) as exc:
        cli._open_vault(Namespace(token="pk_agent_" + "0" * 48, password=None))
    assert exc.value.code == cli.EXIT_AUTH


def test_open_vault_revoked_token_exits_auth(vault_key):
    token, token_id = _mint(vault_key, ["read"])
    assert at.revoke_token(token_id)

    with pytest.raises(SystemExit) as exc:
        cli._open_vault(Namespace(token=token, password=None))
    assert exc.value.code == cli.EXIT_AUTH


def test_open_vault_expired_token_exits_auth(vault_key):
    token, token_id = _mint(vault_key, ["read"])
    tokens = at._load_raw()
    for t in tokens:
        if t["id"] == token_id:
            t["expires_at"] = "2000-01-01T00:00:00"
    at._save_raw(tokens)

    with pytest.raises(SystemExit) as exc:
        cli._open_vault(Namespace(token=token, password=None))
    assert exc.value.code == cli.EXIT_AUTH


def test_open_vault_token_after_password_change_exits_auth(vault_key):
    """A token wraps the vault key at mint time; rekeying the vault (new
    password, new key) must not leave stale tokens able to decrypt it."""
    token, _ = _mint(vault_key, ["read"])
    # Re-encrypt with a brand-new recovery code -> new V3 body/keys, same file.
    # Pass the currently-loaded VaultData (carries _pushkey_revision) so
    # save_vault's conflict check is satisfied like any real overwrite.
    loaded_vault, _ = load_vault(PASSWORD)
    new_recovery = generate_recovery_code()
    save_vault(loaded_vault, "a-totally-different-password", recovery_code=new_recovery)

    with pytest.raises(SystemExit) as exc:
        cli._open_vault(Namespace(token=token, password=None))
    assert exc.value.code == cli.EXIT_AUTH


# ── _require_command_scope ───────────────────────────────────────────────────

def test_require_command_scope_none_means_full_access():
    # Master-password sessions pass scopes=None; every command must be allowed.
    for command in cli._COMMAND_SCOPES:
        cli._require_command_scope(command, None)  # must not raise


@pytest.mark.parametrize("command,scope", sorted(cli._COMMAND_SCOPES.items()))
def test_require_command_scope_allows_matching_scope(command, scope):
    cli._require_command_scope(command, [scope])  # must not raise


@pytest.mark.parametrize("command,scope", sorted(cli._COMMAND_SCOPES.items()))
def test_require_command_scope_denies_missing_scope(command, scope):
    other = next(s for s in ("read", "write", "inject") if s != scope)
    with pytest.raises(SystemExit) as exc:
        cli._require_command_scope(command, [other])
    assert exc.value.code == cli.EXIT_AUTH


def test_require_command_scope_read_cannot_write_or_inject():
    for command in ("add", "rotate", "set-backup", "delete", "import"):
        with pytest.raises(SystemExit):
            cli._require_command_scope(command, ["read"])
    with pytest.raises(SystemExit):
        cli._require_command_scope("inject", ["read"])


def test_require_command_scope_write_cannot_inject():
    """write and inject are deliberately separate scopes (matching
    pushkey_agent_tokens.py's docstring and pushkey_mcp.py's tool gating) --
    a token minted for key rotation should not also be able to write .env
    files to arbitrary linked projects."""
    with pytest.raises(SystemExit):
        cli._require_command_scope("inject", ["write"])


# ── end-to-end through main() ────────────────────────────────────────────────

def test_main_end_to_end_write_scoped_token_can_add_and_read_scoped_cannot(
    monkeypatch, vault_key, capsys
):
    write_token, _ = _mint(vault_key, ["write"], name="writer")
    read_token, _ = _mint(vault_key, ["read"], name="reader")

    monkeypatch.setattr(cli.sys, "argv", ["pushkey", "--token", write_token, "add", "NEW_KEY", "sk-new"])
    cli.main()
    capsys.readouterr()

    vault, _ = load_vault(PASSWORD)
    assert "NEW_KEY" in vault
    assert vault["NEW_KEY"]["value"] == "sk-new"

    monkeypatch.setattr(
        cli.sys, "argv", ["pushkey", "--token", read_token, "add", "SHOULD_NOT_EXIST", "sk-nope"]
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == cli.EXIT_AUTH

    vault_after, _ = load_vault(PASSWORD)
    assert "SHOULD_NOT_EXIST" not in vault_after


def test_main_end_to_end_read_scoped_token_can_list(monkeypatch, vault_key, capsys):
    read_token, _ = _mint(vault_key, ["read"], name="reader")

    monkeypatch.setattr(cli.sys, "argv", ["pushkey", "--token", read_token, "list", "--json"])
    cli.main()

    out = capsys.readouterr().out
    assert "EXISTING_KEY" in out


def test_agent_token_write_never_touches_or_needs_master_password(monkeypatch, vault_key):
    """The whole point of token auth: the agent never sees, derives, or
    supplies the master password, yet the write is still fully readable by it
    afterward -- proving save_vault_with_key round-trips through the same V3
    body the password path uses."""
    write_token, _ = _mint(vault_key, ["write"], name="writer")

    monkeypatch.delenv("PUSHKEY_MASTER", raising=False)
    vault, password, vk, scopes = cli._open_vault(Namespace(token=write_token, password=None))
    assert password is None

    cli.cmd_add(Namespace(name="TOKEN_ADDED", value="sk-token", notes=None), vault, password, vk)

    reloaded, _ = load_vault(PASSWORD)
    assert reloaded["TOKEN_ADDED"]["value"] == "sk-token"

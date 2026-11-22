"""CLI and interactive shell: add-and-connect, the scope gate, and the stale-warning rotate.

Every test runs against a real V3 vault (so the vault key and recovery slot exist) and a
registered project folder `tmp_path / "acme-web"` (tmp_path itself is the vault directory).
Keys carry dummy values. Helpers below turn an unexpected exception into a failed
assertion, so a RED run never reports an error before an assertion.
"""
import hashlib
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

import pushkey_agent_tokens as at
import pushkey_cli as cli
import pushkey_connect as pc
import pushkey_connect_migrate
import pushkey_crypto
import pushkey_projectfs
import pushkey_shared
import pushkey_tiers
from pushkey_crypto import generate_recovery_code
from pushkey_vault import ConfigUnreadableError, load_config, load_vault, save_config, save_vault

PASSWORD = "cli-connect-password"
KEY = "SUPABASE_ANON_KEY"
VALUE = "sb_publishable_x"
OLD = "old-secret-value"


def _entry(**extra):
    entry = {
        "value": VALUE, "created": "2026-01-01", "rotated": None,
        "provider": "Supabase", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


class _World:
    """A V3 vault with EXISTING (a dummy secret) and one registered project folder."""

    def __init__(self, root):
        self.root = root
        self.folder = root / "acme-web"
        self.folder.mkdir()
        self.project, _ = pc.register_project(str(self.folder))
        save_vault(
            {"EXISTING": _entry(value=OLD, provider="Unknown")},
            PASSWORD, recovery_code=generate_recovery_code(),
        )
        self.vault, self.vault_key = load_vault(PASSWORD)

    def disk(self):
        loaded, _ = load_vault(PASSWORD)
        return loaded

    def refresh(self):
        self.vault, self.vault_key = load_vault(PASSWORD)

    def put(self, name, **extra):
        """Add a key straight to the vault file (a key that exists before the CLI runs)."""
        vault = self.disk()
        vault[name] = _entry(**extra)
        save_vault(vault, PASSWORD, vault_key=self.vault_key)
        self.refresh()

    def connect(self, name="EXISTING", **kw):
        args = {
            "key_name": name, "project": self.project, "actor": "test",
            "vault_key": self.vault_key, "password": PASSWORD, **kw,
        }
        return pc.connect(**args)

    def token(self, scopes):
        ok, value, _ = at.create_token("agent", list(scopes), self.vault_key)
        assert ok, value
        return value

    def read(self, relpath=".env", folder=None):
        path = (folder or self.folder) / relpath
        return path.read_text(encoding="utf-8") if path.exists() else None


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("PUSHKEY_MASTER", PASSWORD)
    monkeypatch.delenv("PUSHKEY_AGENT_TOKEN", raising=False)
    # One SHA-256 instead of Argon2id: nothing here is about the KDF.
    monkeypatch.setattr(
        pushkey_crypto, "_derive_key_argon2",
        lambda password, salt: hashlib.sha256(salt + password.encode()).digest(),
    )
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "team")
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: False)


@pytest.fixture
def world(tmp_path):
    return _World(tmp_path)


# -- helpers that keep a RED run on assertions ---------------------------------------


def _exit_code(call):
    """The SystemExit code of `call`, 0 when it returns, `repr(exc)` for any other exception."""
    try:
        call()
    except SystemExit as stop:
        return stop.code
    except Exception as exc:  # noqa: BLE001 - reported as a failed assertion by the caller
        return repr(exc)
    return 0


def _error_of(call):
    try:
        call()
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


def _main(monkeypatch, *argv, token=None):
    full = ["pushkey"]
    if token:
        full += ["--token", token]
    monkeypatch.setattr(cli.sys, "argv", [*full, *argv])
    return _exit_code(cli.main)


def _add_args(**kw):
    base = {"name": "MY_SECRET", "value": "s3cret-value", "notes": None, "project": None,
            "file": None, "as_var": None, "yes": False, "confirm": None}
    base.update(kw)
    return Namespace(**base)


def _shell(monkeypatch, lines, vault, password, vault_key, scopes=None):
    feed = iter(lines)
    monkeypatch.setattr(cli, "_setup_readline", lambda v, h: None)
    monkeypatch.setattr(cli, "_save_history", lambda rl, h: None)
    monkeypatch.setattr(cli, "_render_dashboard", lambda v: None)
    monkeypatch.setattr(cli, "_render_stale_warnings", lambda *a, **k: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": (_ for _ in ()).throw(EOFError()))
    return _error_of(lambda: cli._run_repl_session(vault, password, vault_key, scopes))


def _no_prompt(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the command prompted although the gate should have refused it")
    monkeypatch.setattr("builtins.input", refuse)
    monkeypatch.setattr(cli.getpass, "getpass", refuse)


# -- add ---------------------------------------------------------------------------------


def test_add_with_project_connects(world, capsys):
    args = _add_args(
        name="supabase_anon_key", value=VALUE, project=str(world.folder),
        file=".env.local", as_var="NEXT_PUBLIC_X", yes=True,
    )

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    out = capsys.readouterr().out
    assert code == 0
    assert "Save to acme-web -> dev -> .env.local as NEXT_PUBLIC_X" in out
    assert "Connected and written to .env.local" in out
    assert VALUE not in out
    assert "NEXT_PUBLIC_X=" + VALUE in (world.read(".env.local") or "")
    saved = world.disk().get(KEY) or {}
    assert [(c["file"], c["var"]) for c in saved.get("connections", [])] == [(".env.local", "NEXT_PUBLIC_X")]
    assert KEY in world.vault  # the session's copy is current


def test_add_without_project_saves_in_the_vault_only(world, capsys):
    code = _exit_code(lambda: cli.cmd_add(_add_args(), world.vault, PASSWORD, world.vault_key))

    out = capsys.readouterr().out
    assert code == 0
    assert "Saved in the vault" in out
    assert "Added MY_SECRET" in out
    assert world.disk().get("MY_SECRET", {}).get("value") == "s3cret-value"
    assert not (world.folder / ".env").exists()


def test_add_prompts_for_value_when_omitted(world, monkeypatch, capsys):
    prompts = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": prompts.append(prompt) or "typed-secret")

    code = _exit_code(lambda: cli.cmd_add(_add_args(value=None), world.vault, PASSWORD, world.vault_key))

    assert prompts == ["Value for MY_SECRET (hidden): "]
    assert code == 0
    assert world.disk().get("MY_SECRET", {}).get("value") == "typed-secret"
    assert "typed-secret" not in capsys.readouterr().out


def test_add_prompt_eof_aborts_without_saving(world, monkeypatch, capsys):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(cli.getpass, "getpass", eof)

    code = _exit_code(lambda: cli.cmd_add(_add_args(value=None), world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_ERROR
    assert "Aborted." in capsys.readouterr().err
    assert "MY_SECRET" not in world.disk()


def test_add_yes_does_not_confirm_a_public_prefix(world, capsys):
    args = _add_args(
        name="STRIPE_SECRET", value="whsec_dummy", project=str(world.folder),
        as_var="NEXT_PUBLIC_STRIPE", yes=True,
    )

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_USAGE
    assert "public_prefix" in capsys.readouterr().err
    assert "STRIPE_SECRET" not in world.disk()
    assert world.read() is None


def test_add_with_project_and_confirm_flag_succeeds(world, capsys):
    args = _add_args(
        name="STRIPE_SECRET", value="whsec_dummy", project=str(world.folder),
        as_var="NEXT_PUBLIC_STRIPE", yes=True, confirm=["public_prefix"],
    )

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert code == 0
    assert "Connected and written to .env" in capsys.readouterr().out
    assert "NEXT_PUBLIC_STRIPE=whsec_dummy" in (world.read() or "")


def test_add_asks_for_each_extra_confirmation_and_stops_on_no(world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    asked = []
    answers = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or next(answers))
    args = _add_args(
        name="STRIPE_SECRET", value="whsec_dummy", project=str(world.folder), as_var="NEXT_PUBLIC_STRIPE",
    )

    _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert asked == [
        "Confirm? [y/N] ",
        "This name is bundled into browser code. Continue? [y/N] ",
    ]
    assert "STRIPE_SECRET" not in world.disk()
    assert world.read() is None


def test_add_yes_still_asks_the_extra_confirmation_when_interactive(world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "y")
    args = _add_args(
        name="STRIPE_SECRET", value="whsec_dummy", project=str(world.folder), as_var="NEXT_PUBLIC_STRIPE", yes=True,
    )

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert asked == ["This name is bundled into browser code. Continue? [y/N] "]  # no plain Confirm?: --yes
    assert code == 0
    assert "NEXT_PUBLIC_STRIPE=whsec_dummy" in (world.read() or "")


def test_add_without_yes_cannot_confirm_when_not_interactive(world, capsys):
    args = _add_args(name="STRIPE_SECRET", value="whsec_dummy", project=str(world.folder))

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_USAGE
    assert "STRIPE_SECRET" not in world.disk()


def test_add_with_unregistered_project_refuses(world, tmp_path, capsys):
    other = tmp_path / "other-app"
    other.mkdir()
    args = _add_args(project=str(other), yes=True)

    code = _exit_code(lambda: cli.cmd_add(args, world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_USAGE
    assert "Register it first: pushkey project add" in capsys.readouterr().err
    assert "MY_SECRET" not in world.disk()


# -- connect, where, sync ---------------------------------------------------------------------


def test_connect_command_connects_and_writes(world, monkeypatch, capsys):
    code = _main(
        monkeypatch, "connect", "existing", "--project", str(world.folder),
        "--file", ".env.local", "--as", "APP_SECRET", "--yes",
    )

    assert code == 0
    assert "Connected and written to .env.local" in capsys.readouterr().out
    assert f"APP_SECRET={OLD}" in (world.read(".env.local") or "")
    assert [(c["file"], c["var"]) for c in world.disk()["EXISTING"]["connections"]] == [(".env.local", "APP_SECRET")]


def test_connect_command_refuses_unregistered_folder(world, tmp_path, capsys):
    other = tmp_path / "other-app"
    other.mkdir()
    args = Namespace(name="EXISTING", project=str(other), file=None, as_var=None, yes=True, confirm=None)

    code = _exit_code(lambda: cli.cmd_connect(args, world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_USAGE
    assert "Register it first: pushkey project add" in capsys.readouterr().err
    assert world.disk()["EXISTING"].get("connections") in ([], None)
    assert not (other / ".env").exists()


def test_connect_command_reports_a_file_it_could_not_write(world, monkeypatch, capsys):
    monkeypatch.setattr(pc, "_write_assignments", lambda project, file, values: pc._WriteOutcome("write_failed", {}, False))

    code = _main(monkeypatch, "connect", "EXISTING", "--project", str(world.folder), "--yes")

    out = capsys.readouterr().out
    assert code == 0  # the connection is saved; sync retries the file
    assert "Connected, not written: write_failed" in out
    assert len(world.disk()["EXISTING"]["connections"]) == 1


def test_where_lists_states(world, capsys):
    world.connect()
    world.connect(file=".env.local", var="OTHER_VAR", write=False)
    pc.commit(
        lambda v: pc.replace_value(v["EXISTING"], "rotated-value"),
        vault_key=world.vault_key, password=PASSWORD,
    )

    code = _exit_code(lambda: cli.cmd_where(Namespace(name="existing"), world.disk(), PASSWORD, world.vault_key))

    lines = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert ["acme-web", ".env", "EXISTING", "out_of_date"] in lines
    assert any(line[:3] == ["acme-web", ".env.local", "OTHER_VAR"] and line[3] in ("file_missing", "not_in_file") for line in lines)


def test_where_unknown_key_and_unconnected_key(world, capsys):
    code = _exit_code(lambda: cli.cmd_where(Namespace(name="NOPE"), world.vault, PASSWORD, world.vault_key))
    assert code == cli.EXIT_USAGE
    assert "NOPE" in capsys.readouterr().err

    code = _exit_code(lambda: cli.cmd_where(Namespace(name="EXISTING"), world.vault, PASSWORD, world.vault_key))
    assert code == 0
    assert "EXISTING is not connected to any project." in capsys.readouterr().out


def test_sync_command_rewrites_after_a_change(world, monkeypatch, capsys):
    world.connect()
    pc.commit(
        lambda v: pc.replace_value(v["EXISTING"], "rotated-value"),
        vault_key=world.vault_key, password=PASSWORD,
    )
    token = world.token(["inject"])

    code = _main(monkeypatch, "sync", "EXISTING", "--project", str(world.folder), token=token)

    assert code == 0
    assert "EXISTING=rotated-value" in (world.read() or "")
    assert "rotated-value" not in capsys.readouterr().out


# -- project ---------------------------------------------------------------------------------


def test_project_add_and_remove_commands(world, tmp_path, monkeypatch, capsys):
    other = tmp_path / "second-app"
    other.mkdir()

    added = _main(monkeypatch, "project", "add", str(other), "--name", "Second")
    registered = pc.registered_projects(load_config())
    assert added == 0
    assert [r.get("name") for p, r in registered.items() if p.endswith("second-app")] == ["Second"]

    world.connect()
    removed = _main(monkeypatch, "project", "remove", str(world.folder))
    assert removed == 0
    assert not any(p.endswith("acme-web") for p in pc.registered_projects(load_config()))
    assert world.disk()["EXISTING"].get("connections") in ([], None)


def test_project_add_reports_project_exists(world, monkeypatch, capsys):
    code = _main(monkeypatch, "project", "add", str(world.folder))

    assert code == cli.EXIT_USAGE
    assert "project_exists" in capsys.readouterr().err


def test_cli_token_cannot_add_project(world, tmp_path, monkeypatch, capsys):
    other = tmp_path / "second-app"
    other.mkdir()
    token = world.token(["read", "write", "inject"])

    code = _main(monkeypatch, "project", "add", str(other), token=token)

    assert code == cli.EXIT_AUTH
    assert "master-password" in capsys.readouterr().err
    assert not any(p.endswith("second-app") for p in pc.registered_projects(load_config()))


def test_cli_token_cannot_remove_project(world, monkeypatch, capsys):
    token = world.token(["read", "write", "inject"])

    code = _main(monkeypatch, "project", "remove", str(world.folder), token=token)

    assert code == cli.EXIT_AUTH
    assert any(p.endswith("acme-web") for p in pc.registered_projects(load_config()))


def test_cli_token_without_inject_cannot_add_with_project(world, monkeypatch, capsys):
    token = world.token(["write"])

    code = _main(
        monkeypatch, "add", "NEW_KEY", "dummy-value", "--project", str(world.folder), "--yes", token=token,
    )

    assert code == cli.EXIT_AUTH
    assert "NEW_KEY" not in world.disk()
    assert "inject" in capsys.readouterr().err


# -- the scope gate ----------------------------------------------------------------------------


def test_unmapped_command_fails_closed():
    assert all(isinstance(scope, tuple) for scope in cli._COMMAND_SCOPES.values())

    code = _exit_code(lambda: cli._require_command_scope("frobnicate", ["read", "write", "inject"]))
    assert code == cli.EXIT_AUTH

    assert _exit_code(lambda: cli._require_command_scope("frobnicate", None)) == 0  # master: never gated


@pytest.mark.parametrize(
    "command,scopes",
    [("connect", ["write"]), ("connect", ["inject"]), ("where", ["write"]), ("sync", ["read"])],
)
def test_new_commands_need_their_scopes(command, scopes):
    assert _exit_code(lambda: cli._require_command_scope(command, scopes)) == cli.EXIT_AUTH
    assert _exit_code(lambda: cli._require_command_scope(command, ["read", "write", "inject"])) == 0


def test_inject_all_needs_master_password(world, monkeypatch, capsys):
    token = world.token(["read", "write", "inject"])
    world.connect()

    code = _main(monkeypatch, "inject", "--project", str(world.folder), "--all", token=token)

    assert code == cli.EXIT_AUTH
    assert "master-password" in capsys.readouterr().err


def test_inject_all_connects_every_key_with_defaults(world, capsys):
    world.put("_meta", value="internal")
    world.put("NEXT_PUBLIC_SECRETISH", value="whsec_dummy")
    args = Namespace(project=str(world.folder), all=True)

    code = _exit_code(lambda: cli.cmd_inject(args, world.disk(), PASSWORD, world.vault_key))

    out = capsys.readouterr().out
    env = world.read() or ""
    assert code == 0
    assert f"EXISTING={OLD}" in env
    assert "_meta" not in env and "NEXT_PUBLIC_SECRETISH" not in env
    assert "NEXT_PUBLIC_SECRETISH" in out  # listed as skipped
    assert "Wrote 1 key(s) to" in out
    assert world.disk()["_meta"].get("connections") in ([], None)


def test_inject_uses_connections_only(world, capsys):
    world.put("ALLOWLISTED_ONLY", value="not-connected", projects=[world.project])
    world.connect()
    pc.commit(
        lambda v: pc.replace_value(v["EXISTING"], "rotated-value"),
        vault_key=world.vault_key, password=PASSWORD,
    )
    args = Namespace(project=str(world.folder), all=False)

    code = _exit_code(lambda: cli.cmd_inject(args, world.disk(), PASSWORD, world.vault_key))

    out = capsys.readouterr().out
    assert code == 0
    assert "EXISTING=rotated-value" in (world.read() or "")
    assert "ALLOWLISTED_ONLY" not in (world.read() or "")
    assert "Wrote 1 key(s) to" in out
    assert "rotated-value" not in out


def test_inject_without_connections_prints_a_hint(world, capsys):
    args = Namespace(project=str(world.folder), all=False)

    code = _exit_code(lambda: cli.cmd_inject(args, world.disk(), PASSWORD, world.vault_key))

    assert code == 0
    assert "No keys are connected to" in capsys.readouterr().out
    assert world.read() is None


def test_inject_of_an_unregistered_folder_refuses(world, tmp_path, capsys):
    other = tmp_path / "other-app"
    other.mkdir()

    code = _exit_code(lambda: cli.cmd_inject(Namespace(project=str(other), all=False), world.vault, PASSWORD, world.vault_key))

    assert code == cli.EXIT_USAGE
    assert "Register it first: pushkey project add" in capsys.readouterr().err


# -- rotate --------------------------------------------------------------------------------


def test_rotate_syncs_connected_files(world, capsys):
    world.connect()

    code = _exit_code(
        lambda: cli.cmd_rotate(Namespace(name="EXISTING", new_value="rotated-value"), world.vault, PASSWORD, world.vault_key)
    )

    assert code == 0
    assert "EXISTING=rotated-value" in (world.read() or "")
    disk = world.disk()["EXISTING"]
    assert disk["value"] == "rotated-value" and disk["rotation_count"] == 1
    assert disk["history"][0]["value"] == OLD
    assert "rotated-value" not in capsys.readouterr().out


def test_rotate_token_without_inject_lists_not_updated(world, monkeypatch, capsys):
    world.connect()
    token = world.token(["write"])

    code = _main(monkeypatch, "rotate", "EXISTING", "rotated-value", token=token)

    out = capsys.readouterr().out
    assert code == 0
    assert world.disk()["EXISTING"]["value"] == "rotated-value"
    assert f"EXISTING={OLD}" in (world.read() or "")  # the file was not touched
    assert "Not updated (token lacks inject): acme-web .env" in out


def test_rotate_token_with_inject_updates_the_file(world, monkeypatch, capsys):
    world.connect()
    token = world.token(["write", "inject"])

    code = _main(monkeypatch, "rotate", "EXISTING", "rotated-value", token=token)

    assert code == 0
    assert "EXISTING=rotated-value" in (world.read() or "")
    assert "Not updated" not in capsys.readouterr().out


def test_rotate_sync_failure_is_a_warning_not_an_error(world, monkeypatch, capsys):
    world.connect()

    def boom(**kw):
        raise ConfigUnreadableError("config_unreadable")

    monkeypatch.setattr(pc, "sync", boom)

    code = _exit_code(
        lambda: cli.cmd_rotate(Namespace(name="EXISTING", new_value="rotated-value"), world.vault, PASSWORD, world.vault_key)
    )

    assert code == 0
    assert world.disk()["EXISTING"]["value"] == "rotated-value"
    assert "config_unreadable" in capsys.readouterr().err


def test_stale_warning_rotate_saves_v3_vault(world, monkeypatch, capsys):
    world.put("STALE_KEY", value="old-value", created="2020-01-01")
    monkeypatch.setattr("builtins.input", lambda prompt="": "stale_key")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "new-value")

    error = _error_of(lambda: cli._render_stale_warnings(world.vault, PASSWORD, world.vault_key))

    assert error is None, repr(error)
    saved = world.disk()["STALE_KEY"]
    assert saved["value"] == "new-value" and saved["rotation_count"] == 1


def test_stale_warning_offers_no_rotation_to_a_read_only_token(world, monkeypatch, capsys):
    world.put("STALE_KEY", value="old-value", created="2020-01-01")
    _no_prompt(monkeypatch)

    error = _error_of(lambda: cli._render_stale_warnings(world.vault, None, world.vault_key, ["read"]))

    assert error is None, repr(error)
    assert "STALE_KEY" in capsys.readouterr().out
    assert world.disk()["STALE_KEY"]["value"] == "old-value"


# -- the shell ----------------------------------------------------------------------------------


def test_shell_read_token_cannot_add_key(world, monkeypatch, capsys):
    _no_prompt(monkeypatch)
    before = world.disk()

    result = _error_of(
        lambda: cli._handle_repl_command("add", [], world.vault, None, world.vault_key, None, scopes=["read"])
    )

    assert result is None
    assert "missing required scope 'write'" in capsys.readouterr().err
    assert world.disk() == before


def test_shell_numbered_alias_is_gated_too(world, monkeypatch, capsys):
    _no_prompt(monkeypatch)

    _error_of(lambda: cli._handle_repl_command("1", [], world.vault, None, world.vault_key, None, scopes=["read"]))

    assert "missing required scope 'write'" in capsys.readouterr().err


def test_shell_token_unmapped_command_refused(world, monkeypatch, capsys):
    _no_prompt(monkeypatch)
    every = ["read", "write", "inject"]

    for command in ("frobnicate", "agents"):
        returned = _error_of(
            lambda: cli._handle_repl_command(command, ["create", "x", "read"], world.vault, None, world.vault_key, "proc", scopes=every)
        )
        assert returned is None
    err = capsys.readouterr().err
    assert err.count("Error:") == 2
    assert "Unknown command" not in err


def test_shell_exit_help_and_app_stay_available_to_every_token(world, monkeypatch):
    monkeypatch.setattr(cli, "_print_help", lambda: None)

    assert cli._handle_repl_command("exit", [], world.vault, None, world.vault_key, "proc", scopes=[]) is False
    assert cli._handle_repl_command("help", [], world.vault, None, world.vault_key, "proc", scopes=[]) == "proc"


def test_shell_token_cannot_register_or_remove_projects(world, tmp_path, monkeypatch, capsys):
    other = tmp_path / "second-app"
    other.mkdir()
    every = ["read", "write", "inject"]

    _error_of(lambda: cli._handle_repl_command("project", ["add", str(other)], world.vault, None, world.vault_key, None, scopes=every))
    _error_of(lambda: cli._handle_repl_command("project", ["remove", str(world.folder)], world.vault, None, world.vault_key, None, scopes=every))

    assert "master-password" in capsys.readouterr().err
    registered = pc.registered_projects(load_config())
    assert any(p.endswith("acme-web") for p in registered)
    assert not any(p.endswith("second-app") for p in registered)


def test_shell_token_cannot_inject_all(world, monkeypatch, capsys):
    world.connect()
    pc.commit(
        lambda v: pc.replace_value(v["EXISTING"], "rotated-value"),
        vault_key=world.vault_key, password=PASSWORD,
    )

    _error_of(lambda: cli._handle_repl_command("inject", ["--all"], world.vault, None, world.vault_key, None, scopes=["inject"]))

    assert "master-password" in capsys.readouterr().err
    assert f"EXISTING={OLD}" in (world.read() or "")  # nothing was synced


def test_run_repl_session_passes_scopes_to_the_gate(world, monkeypatch, capsys):
    error = _shell(monkeypatch, ["add", "exit"], world.vault, None, world.vault_key, scopes=["read"])

    assert error is None, repr(error)
    assert "missing required scope 'write'" in capsys.readouterr().err


def test_shell_project_add_path_with_spaces(world, tmp_path, monkeypatch, capsys):
    spaced = tmp_path / "My Project"
    spaced.mkdir()

    error = _shell(monkeypatch, [f'project add "{spaced}"', "exit"], world.vault, PASSWORD, world.vault_key)

    assert error is None, repr(error)
    registered = pc.registered_projects(load_config())
    assert [p for p in registered if p.endswith("My Project")] == [
        pushkey_projectfs.canonical_project_path(str(spaced))
    ]


def test_shell_unbalanced_quote_prints_and_continues(world, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli, "_print_help", lambda: seen.append("help"))

    error = _shell(monkeypatch, ['project add "oops', "help", "exit"], world.vault, PASSWORD, world.vault_key)

    assert error is None, repr(error)
    assert "Could not parse that line" in capsys.readouterr().out
    assert seen == ["help"]  # the next line still ran


def test_split_shell_line_strips_quotes_and_keeps_backslashes():
    assert cli._split_shell_line('project add "a b" c') == ["project", "add", "a b", "c"]
    assert cli._split_shell_line("project add 'a b'") == ["project", "add", "a b"]
    if os.name == "nt":
        assert cli._split_shell_line(r'project add "C:\My Project\x" C:\a\b') == [
            "project", "add", r"C:\My Project\x", r"C:\a\b",
        ]
    with pytest.raises(ValueError):
        cli._split_shell_line('project add "oops')


def test_shell_project_assign_needs_a_registered_folder(world, tmp_path, capsys):
    other = tmp_path / "other-app"
    other.mkdir()

    error = _error_of(lambda: cli._repl_project_assign(world.vault, PASSWORD, str(other), ["EXISTING"], world.vault_key))

    assert error is None, repr(error)
    out = capsys.readouterr()
    assert "Register it first: pushkey project add" in out.out + out.err
    assert not any(p.endswith("other-app") for p in pc.registered_projects(load_config()))
    assert world.disk()["EXISTING"].get("connections") in ([], None)


def test_shell_project_assign_connects_without_writing(world, capsys):
    error = _error_of(lambda: cli._repl_project_assign(world.vault, PASSWORD, str(world.folder), ["EXISTING"], world.vault_key))

    assert error is None, repr(error)
    assert [c["var"] for c in world.disk()["EXISTING"]["connections"]] == ["EXISTING"]
    assert world.project in world.disk()["EXISTING"]["projects"]
    assert world.read() is None


def test_shell_rotate_token_without_inject_lists_not_updated(world, monkeypatch, capsys):
    world.connect()
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "rotated-value")

    error = _error_of(lambda: cli._repl_rotate(world.vault, None, "EXISTING", world.vault_key, ["write"]))

    assert error is None, repr(error)
    assert "Not updated (token lacks inject): acme-web .env" in capsys.readouterr().out
    assert f"EXISTING={OLD}" in (world.read() or "")
    assert world.disk()["EXISTING"]["value"] == "rotated-value"


def test_shell_rotate_syncs_for_a_master_session(world, monkeypatch, capsys):
    world.connect()
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "rotated-value")

    error = _error_of(lambda: cli._repl_rotate(world.vault, PASSWORD, "EXISTING", world.vault_key))

    assert error is None, repr(error)
    assert "EXISTING=rotated-value" in (world.read() or "")


def test_shell_inject_syncs_connections(world, monkeypatch, capsys):
    world.connect()
    pc.commit(
        lambda v: pc.replace_value(v["EXISTING"], "rotated-value"),
        vault_key=world.vault_key, password=PASSWORD,
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    error = _error_of(lambda: cli._repl_inject(world.disk(), PASSWORD, str(world.folder), world.vault_key))

    assert error is None, repr(error)
    assert "EXISTING=rotated-value" in (world.read() or "")


# -- credentials the core receives ---------------------------------------------------------------


@pytest.mark.parametrize("as_token", [False, True])
def test_core_calls_carry_the_right_credentials(world, monkeypatch, as_token):
    seen = []
    real_connect = pc.connect

    def spy(**kw):
        seen.append(kw)
        return real_connect(**kw)

    monkeypatch.setattr(pc, "connect", spy)
    password = None if as_token else PASSWORD  # PUSHKEY_MASTER is set either way

    args = Namespace(name="EXISTING", project=str(world.folder), file=None, as_var=None, yes=True, confirm=None)
    code = _exit_code(lambda: cli.cmd_connect(args, world.vault, password, world.vault_key))

    assert code == 0
    assert len(seen) == 1
    assert seen[0]["password"] == password
    assert seen[0]["vault_key"] == world.vault_key
    assert seen[0]["actor"] == ("cli agent-token" if as_token else "cli")
    assert seen[0]["target"] is world.vault


# -- unlock: migration and the notice --------------------------------------------------------------


def _unmigrated_config(folder, keys=()):
    save_config({"projects": {"desk": {
        "path": str(folder), "keys": list(keys), "added": "2026-01-02T03:04:05", "target_env": "all",
    }}})


def test_open_vault_master_migrates_and_prints_notice(world, capsys):
    _unmigrated_config(world.folder)

    vault, password, vault_key, scopes = cli._open_vault(Namespace(password=PASSWORD, token=None))

    captured = capsys.readouterr()
    migrated = load_config()
    assert migrated.get("connect_schema") == 1
    assert "desk" in captured.err
    assert "Dismiss with: pushkey project dismiss-notice" in captured.err
    assert captured.out == ""  # stdout stays clean for --json and $(pushkey get ...)
    assert (password, scopes) == (PASSWORD, None)


def test_open_vault_token_does_not_migrate(world, monkeypatch, capsys):
    config = load_config()
    config["projects"].pop(world.project, None)
    config["projects"]["desk"] = {"path": str(world.folder), "keys": [], "added": "2026-01-02T03:04:05"}
    config["connect_notice"] = {"every_key_projects": ["desk"], "env_skipped": []}
    save_config(config)
    token = world.token(["read"])
    calls = []
    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", lambda **kw: calls.append(kw))

    vault, password, vault_key, scopes = cli._open_vault(Namespace(password=None, token=token))

    captured = capsys.readouterr()
    assert calls == []
    assert "desk" in load_config()["projects"] and load_config().get("connect_schema") != 1
    assert "Dismiss with" not in captured.err + captured.out
    assert (password, scopes) == (None, ["read"])


def test_open_vault_unreadable_config_warns_and_continues(world, capsys):
    pushkey_shared.CONFIG_FILE.write_bytes(b"this is not a config")

    result = _error_of(lambda: cli._open_vault(Namespace(password=PASSWORD, token=None)))

    err = capsys.readouterr().err
    assert result is None, repr(result)
    warnings = [line for line in err.splitlines() if line.startswith("Warning: project store not migrated")]
    assert len(warnings) == 1 and "config_unreadable" in warnings[0]
    assert pushkey_shared.CONFIG_FILE.read_bytes() == b"this is not a config"


def test_project_dismiss_notice_command(world, monkeypatch, capsys):
    config = load_config()
    config["connect_notice"] = {"every_key_projects": ["desk"], "env_skipped": []}
    save_config(config)

    code = _main(monkeypatch, "project", "dismiss-notice")

    assert code == 0
    assert "connect_notice" not in load_config()


# -- the error map ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,exit_code",
    [
        (pc.ConnectError("migration_pending"), cli.EXIT_ERROR),
        (ConfigUnreadableError("config_unreadable"), cli.EXIT_IO),
        (ConfigUnreadableError("config_busy"), cli.EXIT_IO),
        (pc.ConnectError("project_not_registered"), cli.EXIT_USAGE),
        (pc.ConnectError("key_not_found"), cli.EXIT_USAGE),
        (pc.ConnectError("connection_not_found"), cli.EXIT_USAGE),
        (pc.ConnectError("invalid_var"), cli.EXIT_USAGE),
        (pc.ConnectError("key_exists"), cli.EXIT_USAGE),
        (pc.ConnectError("var_taken", {"key": "OTHER"}), cli.EXIT_USAGE),
        (pc.ConnectError("project_exists"), cli.EXIT_USAGE),
        (pc.ConnectError("project_limit"), cli.EXIT_USAGE),
        (pc.ConnectError("confirmation_required", {"needs": ["public_prefix"]}), cli.EXIT_USAGE),
        (pc.ConnectError("file_tracked_by_git"), cli.EXIT_IO),
        (pc.ConnectError("invalid_env_file"), cli.EXIT_IO),
        (pc.ConnectError("read_failed"), cli.EXIT_IO),
        (pc.ConnectError("backup_failed"), cli.EXIT_IO),
        (pc.ConnectError("vault_changed"), cli.EXIT_ERROR),
        (pc.ConnectError("vault_unavailable"), cli.EXIT_ERROR),
        (pc.ConnectError("something_new"), cli.EXIT_ERROR),
        (pushkey_projectfs.ProjectPathError(400, "project directory not found"), cli.EXIT_USAGE),
    ],
)
def test_connect_error_exit_codes(error, exit_code, capsys):
    code = _exit_code(lambda: cli._connect_error_exit(error))

    err = capsys.readouterr().err
    assert code == exit_code
    assert len([line for line in err.splitlines() if line.strip()]) == 1
    assert "Traceback" not in err


def test_connect_error_exit_messages_name_the_fix(capsys):
    _exit_code(lambda: cli._connect_error_exit(pc.ConnectError("migration_pending")))
    assert "Open Pushkey with your master password once to finish migrating projects." in capsys.readouterr().err

    _exit_code(lambda: cli._connect_error_exit(pc.ConnectError("project_not_registered")))
    assert "Register it first: pushkey project add" in capsys.readouterr().err

    _exit_code(lambda: cli._connect_error_exit(pc.ConnectError("something_new")))
    assert "something_new" in capsys.readouterr().err


def test_connect_refuses_a_file_git_tracks_with_the_sentence(world, monkeypatch, capsys):
    import subprocess
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    (world.folder / ".env").write_text("A=1\n", encoding="utf-8")
    subprocess.run([*git, "init"], cwd=world.folder, check=True, capture_output=True)
    subprocess.run([*git, "add", "-f", ".env"], cwd=world.folder, check=True, capture_output=True)
    subprocess.run([*git, "commit", "-m", "x"], cwd=world.folder, check=True, capture_output=True)

    code = _main(monkeypatch, "connect", "EXISTING", "--project", str(world.folder), "--yes")

    err = capsys.readouterr().err
    assert code == cli.EXIT_IO
    assert "this file is committed to git; Pushkey will not write secrets into it" in err
    assert world.disk()["EXISTING"].get("connections") in ([], None)


def test_connect_not_written_for_a_tracked_file_prints_the_sentence(world, monkeypatch, capsys):
    monkeypatch.setattr(
        pc, "_write_assignments",
        lambda project, file, values: pc._WriteOutcome("file_tracked_by_git", {}, False),
    )

    code = _main(monkeypatch, "connect", "EXISTING", "--project", str(world.folder), "--yes")

    out = capsys.readouterr().out
    assert code == 0
    assert "Connected, not written: file_tracked_by_git" in out
    assert "this file is committed to git; Pushkey will not write secrets into it" in out


def test_shell_project_assign_and_inject_need_their_scopes(world, monkeypatch, capsys):
    _no_prompt(monkeypatch)

    _error_of(lambda: cli._handle_repl_command(
        "project", ["assign", str(world.folder), "EXISTING"], world.vault, None, world.vault_key, None, scopes=["read", "inject"]))
    _error_of(lambda: cli._handle_repl_command(
        "project", ["inject", str(world.folder)], world.vault, None, world.vault_key, None, scopes=["read", "write"]))

    err = capsys.readouterr().err
    assert "missing required scope 'write'" in err
    assert "missing required scope 'inject'" in err
    assert world.disk()["EXISTING"].get("connections") in ([], None)


def test_shell_command_exit_does_not_end_the_shell(world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_desktop_app_candidates", lambda: [])
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    code = _exit_code(lambda: cli._handle_repl_command("desktop", [], world.vault, PASSWORD, world.vault_key, "proc"))

    assert code == 0  # no SystemExit escaped
    assert "Desktop app not found" in capsys.readouterr().err


def test_shell_delegated_command_errors_stay_in_the_shell(world, monkeypatch, capsys):
    error = _shell(monkeypatch, ["where NOPE", "where", "connect", "exit"], world.vault, PASSWORD, world.vault_key)

    assert error is None, repr(error)
    assert "key_not_found" in capsys.readouterr().err


def test_inject_reports_a_connection_it_could_not_write(world, monkeypatch, capsys):
    world.connect(write=False)
    monkeypatch.setattr(pc, "_write_assignments", lambda project, file, values: pc._WriteOutcome("write_failed", {}, False))
    args = Namespace(project=str(world.folder), all=False)

    code = _exit_code(lambda: cli.cmd_inject(args, world.disk(), PASSWORD, world.vault_key))

    out = capsys.readouterr().out
    assert code == cli.EXIT_IO
    assert "Not written: EXISTING" in out and "write_failed" in out

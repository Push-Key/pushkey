"""
CLI tests — call cmd_* functions directly with Namespace args.
Vault dir patched to tmp_path; password injected via PUSHKEY_MASTER env var.
"""
import json
import os
import subprocess
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest
import pushkey_shared
import pushkey_cli as cli
from pushkey_vault import save_vault
from pushkey_crypto import _V3_MAGIC, decrypt_data_v3


PASSWORD = "cli-test-password"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def patch_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("PUSHKEY_MASTER", PASSWORD)
    monkeypatch.setattr(pushkey_shared, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(pushkey_shared, "VAULT_FILE", tmp_path / "vault.enc")
    monkeypatch.setattr(pushkey_shared, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(pushkey_shared, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(pushkey_shared, "LOG_FILE", tmp_path / "pushkey.log")
    monkeypatch.setattr(pushkey_shared, "HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(pushkey_shared, "IMPORT_DIR", tmp_path / "import")
    monkeypatch.setattr(pushkey_shared, "LICENSE_FILE", tmp_path / ".license")
    monkeypatch.setattr(pushkey_shared, "TOKEN_FILE", tmp_path / ".token")
    pushkey_shared.ensure_vault_dir()


def _empty_vault():
    return {}


def _vault_with_key():
    return {
        "OPENAI_API_KEY": {
            "value": "sk-test123",
            "created": datetime.now().isoformat(),
            "rotated": None,
            "provider": "OpenAI",
            "env": "all",
            "projects": [],
            "notes": "",
            "rotation_count": 0,
        }
    }


def _subprocess_env(home: Path, password: str | None = PASSWORD) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    if password is None:
        env.pop("PUSHKEY_MASTER", None)
    else:
        env["PUSHKEY_MASTER"] = password
    return env


def test_cli_exit_code_constants_are_stable():
    assert cli.EXIT_OK == 0
    assert cli.EXIT_USAGE == 2
    assert cli.EXIT_AUTH == 10
    assert cli.EXIT_IO == 20
    assert cli.EXIT_CORRUPTION == 30
    assert cli.EXIT_NETWORK == 40
    assert cli.EXIT_INTERRUPTED == 130


def test_open_vault_wrong_password_uses_auth_exit(monkeypatch):
    monkeypatch.setattr(cli, "load_vault", lambda password: (None, None))

    with pytest.raises(SystemExit) as exc:
        cli._open_vault(Namespace(password="bad"))

    assert exc.value.code == cli.EXIT_AUTH


def test_cmd_init_noninteractive_creates_v3_without_printing_recovery(monkeypatch, capsys, tmp_path):
    answers = iter(["new-password", "new-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: False)

    recovery_file = tmp_path / "recovery.txt"
    cli._cmd_init(str(recovery_file))

    raw = pushkey_shared.VAULT_FILE.read_bytes()
    assert raw.startswith(_V3_MAGIC)
    output = capsys.readouterr().out
    recovery = recovery_file.read_text().strip()
    assert recovery not in output
    plaintext, _ = decrypt_data_v3(raw, recovery_code=recovery)
    assert json.loads(plaintext)["keys"] == {}


def test_cmd_init_interactive_requires_recovery_confirmation(monkeypatch):
    answers = iter(["new-password", "new-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    with pytest.raises(SystemExit):
        cli._cmd_init()

    assert not pushkey_shared.VAULT_FILE.exists()


def test_cmd_init_noninteractive_requires_recovery_file(monkeypatch, capsys):
    answers = iter(["new-password", "new-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli._cmd_init()
    assert exc.value.code == 2
    assert "PUSH-" not in capsys.readouterr().out
    assert not pushkey_shared.VAULT_FILE.exists()


def _seed_subprocess_vault(home: Path, password: str = "subproc-password") -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pushkey_vault import save_vault; "
            "save_vault({'OPENAI_API_KEY': {'value': 'sk-subproc', 'created': '2026-01-01', 'rotated': None, 'provider': 'OpenAI', 'env': 'all', 'projects': [], 'notes': '', 'rotation_count': 0}}, "
            "          'subproc-password')",
        ],
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=_subprocess_env(home, password=password),
        timeout=30,
    )
    assert completed.returncode == cli.EXIT_OK, completed.stderr


def test_subprocess_status_uses_isolated_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _seed_subprocess_vault(home)

    completed = subprocess.run(
        [sys.executable, "-m", "pushkey_cli", "status"],
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=_subprocess_env(home, password="subproc-password"),
        timeout=30,
    )

    assert completed.returncode == cli.EXIT_OK
    assert "1 key" in completed.stdout
    assert "sk-subproc" not in completed.stdout


def test_subprocess_add_and_list_use_isolated_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _seed_subprocess_vault(home)
    env = _subprocess_env(home, password="subproc-password")

    added = subprocess.run(
        [sys.executable, "-m", "pushkey_cli", "add", "STRIPE_KEY", "sk-stripe"],
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=env,
        timeout=30,
    )
    assert added.returncode == cli.EXIT_OK
    assert "Added STRIPE_KEY" in added.stdout
    assert "sk-stripe" not in added.stdout

    listed = subprocess.run(
        [sys.executable, "-m", "pushkey_cli", "list", "--json"],
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=env,
        timeout=30,
    )
    assert listed.returncode == cli.EXIT_OK
    rows = json.loads(listed.stdout)
    names = {row["name"] for row in rows}
    assert {"OPENAI_API_KEY", "STRIPE_KEY"} <= names
    assert "sk-subproc" not in listed.stdout
    assert "sk-stripe" not in listed.stdout


def test_v3_cli_mutations_preserve_recovery_unlock(tmp_path):
    from pushkey_crypto import generate_recovery_code, decrypt_data_v3
    recovery = generate_recovery_code()
    save_vault({}, PASSWORD, recovery_code=recovery)
    vault, vault_key = cli.load_vault(PASSWORD)

    cli.cmd_add(Namespace(name="A", value="one", notes=None), vault, PASSWORD, vault_key)
    cli.cmd_rotate(Namespace(name="A", new_value="two"), vault, PASSWORD, vault_key)
    cli.cmd_add(Namespace(name="B", value="three", notes=None), vault, PASSWORD, vault_key)
    cli.cmd_delete(Namespace(name="B", yes=True), vault, PASSWORD, vault_key)
    env_file = tmp_path / "input.env"
    env_file.write_text("C=four\n")
    cli.cmd_import(Namespace(file=str(env_file)), vault, PASSWORD, vault_key)

    raw = pushkey_shared.VAULT_FILE.read_bytes()
    plaintext, _ = decrypt_data_v3(raw, recovery_code=recovery)
    data = json.loads(plaintext)["keys"]
    assert data["A"]["value"] == "two"
    assert data["C"]["value"] == "four"
    assert "B" not in data


# ── add ──────────────────────────────────────────────────────────────────────

def test_cmd_add_new_key(capsys):
    vault = _empty_vault()
    args = Namespace(name="OPENAI_API_KEY", value="sk-abc", notes=None)
    cli.cmd_add(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "Added OPENAI_API_KEY" in out
    assert "OpenAI" in out
    assert "OPENAI_API_KEY" in vault
    assert vault["OPENAI_API_KEY"]["provider"] == "OpenAI"


def test_cmd_add_duplicate_exits():
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", value="sk-new", notes=None)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_add(args, vault, PASSWORD)
    assert exc.value.code == cli.EXIT_USAGE


def test_cmd_add_normalises_name_to_upper(capsys):
    vault = _empty_vault()
    args = Namespace(name="my_key", value="val123", notes=None)
    cli.cmd_add(args, vault, PASSWORD)
    assert "MY_KEY" in vault


def test_cmd_add_unknown_provider_no_suffix(capsys):
    vault = _empty_vault()
    args = Namespace(name="RANDOM_SECRET", value="xyzxyz", notes=None)
    cli.cmd_add(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "[" not in out  # no provider suffix


# ── get ──────────────────────────────────────────────────────────────────────

def test_cmd_get_prints_value(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", clip=False)
    cli.cmd_get(args, vault, PASSWORD)
    assert capsys.readouterr().out.strip() == "sk-test123"


def test_cmd_get_case_insensitive(capsys):
    vault = _vault_with_key()
    args = Namespace(name="openai_api_key", clip=False)
    cli.cmd_get(args, vault, PASSWORD)
    assert capsys.readouterr().out.strip() == "sk-test123"


def test_cmd_get_missing_exits():
    vault = _empty_vault()
    args = Namespace(name="MISSING_KEY", clip=False)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_get(args, vault, PASSWORD)
    assert exc.value.code == cli.EXIT_USAGE


# ── list ─────────────────────────────────────────────────────────────────────

def test_cmd_list_table_output(capsys):
    vault = _vault_with_key()
    args = Namespace(status=None, json=False)
    cli.cmd_list(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out
    assert "OpenAI" in out
    assert "healthy" in out


def test_cmd_list_json_output(capsys):
    vault = _vault_with_key()
    args = Namespace(status=None, json=True)
    cli.cmd_list(args, vault, PASSWORD)
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["name"] == "OPENAI_API_KEY"
    assert "status" in data[0]


def test_cmd_list_filter_critical_hides_healthy(capsys):
    vault = _vault_with_key()
    args = Namespace(status="critical", json=False)
    cli.cmd_list(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" not in out  # fresh key is healthy, filtered out


def test_cmd_list_empty_vault(capsys):
    vault = _empty_vault()
    args = Namespace(status=None, json=False)
    cli.cmd_list(args, vault, PASSWORD)
    assert "No keys" in capsys.readouterr().out


# ── rotate ───────────────────────────────────────────────────────────────────

def test_cmd_rotate_updates_value(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", new_value="sk-new-value")
    cli.cmd_rotate(args, vault, PASSWORD)
    assert vault["OPENAI_API_KEY"]["value"] == "sk-new-value"
    assert vault["OPENAI_API_KEY"]["rotated"] is not None
    assert vault["OPENAI_API_KEY"]["rotation_count"] == 1
    assert "Rotated OPENAI_API_KEY" in capsys.readouterr().out


def test_cmd_rotate_saves_history():
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", new_value="sk-v2")
    cli.cmd_rotate(args, vault, PASSWORD)
    assert vault["OPENAI_API_KEY"]["history"][0]["value"] == "sk-test123"


def test_cmd_rotate_missing_key_exits():
    vault = _empty_vault()
    args = Namespace(name="MISSING", new_value="x")
    with pytest.raises(SystemExit):
        cli.cmd_rotate(args, vault, PASSWORD)


# ── delete ───────────────────────────────────────────────────────────────────

def test_cmd_delete_with_yes_flag(capsys):
    vault = _vault_with_key()
    args = Namespace(name="OPENAI_API_KEY", yes=True)
    cli.cmd_delete(args, vault, PASSWORD)
    assert "OPENAI_API_KEY" not in vault
    assert "Deleted" in capsys.readouterr().out


def test_cmd_delete_missing_key_exits():
    vault = _empty_vault()
    args = Namespace(name="GHOST", yes=True)
    with pytest.raises(SystemExit):
        cli.cmd_delete(args, vault, PASSWORD)


# ── status ───────────────────────────────────────────────────────────────────

def test_cmd_status_shows_counts(capsys):
    vault = _vault_with_key()
    cli.cmd_status(Namespace(), vault, PASSWORD)
    out = capsys.readouterr().out
    assert "1 key" in out
    assert "healthy" in out


def test_cmd_status_empty_vault(capsys):
    cli.cmd_status(Namespace(), _empty_vault(), PASSWORD)
    out = capsys.readouterr().out
    assert "0 key" in out


# ── import ───────────────────────────────────────────────────────────────────

def test_cmd_import_env_file(tmp_path, capsys):
    env_file = tmp_path / "secrets.env"
    env_file.write_text("GITHUB_TOKEN=ghp_abc123\nSTRIPE_KEY=sk_live_xyz\n", encoding="utf-8")
    vault = _empty_vault()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    assert "GITHUB_TOKEN" in vault
    assert "STRIPE_KEY" in vault
    assert vault["GITHUB_TOKEN"]["provider"] == "GitHub"
    assert "Imported 2" in capsys.readouterr().out


def test_cmd_import_skips_existing(tmp_path, capsys):
    env_file = tmp_path / "more.env"
    env_file.write_text("OPENAI_API_KEY=sk-new\n", encoding="utf-8")
    vault = _vault_with_key()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    out = capsys.readouterr().out
    assert "Imported 0" in out
    assert "skipped 1" in out
    assert vault["OPENAI_API_KEY"]["value"] == "sk-test123"  # unchanged


def test_cmd_import_ignores_comments(tmp_path, capsys):
    env_file = tmp_path / "commented.env"
    env_file.write_text("# this is a comment\nREAL_KEY=realval\n", encoding="utf-8")
    vault = _empty_vault()
    args = Namespace(file=str(env_file))
    cli.cmd_import(args, vault, PASSWORD)
    assert "REAL_KEY" in vault
    assert "# THIS IS A COMMENT" not in vault


def test_cmd_import_missing_file_exits(tmp_path):
    vault = _empty_vault()
    args = Namespace(file=str(tmp_path / "nonexistent.env"))
    with pytest.raises(SystemExit) as exc:
        cli.cmd_import(args, vault, PASSWORD)
    assert exc.value.code == cli.EXIT_IO


def test_completion_bash_outputs_commands(capsys):
    cli.cmd_completion(Namespace(shell="bash"))
    out = capsys.readouterr().out
    assert "complete -F _pushkey_complete pushkey" in out
    assert "set-backup" in out
    assert "completion" in out


def test_completion_powershell_outputs_commands(capsys):
    cli.cmd_completion(Namespace(shell="powershell"))
    out = capsys.readouterr().out
    assert "Register-ArgumentCompleter" in out
    assert "'set-backup'" in out
    assert "'completion'" in out


# ── inject ───────────────────────────────────────────────────────────────────

def test_cmd_inject_all_flag_writes_env(tmp_path, capsys):
    project = tmp_path / "myproject"
    project.mkdir()
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=True)
    cli.cmd_inject(args, vault, PASSWORD)
    env_file = project / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "OPENAI_API_KEY=sk-test123" in content


def test_cmd_inject_adds_gitignore(tmp_path, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=True)
    cli.cmd_inject(args, vault, PASSWORD)
    gi = project / ".gitignore"
    assert gi.exists()
    assert ".env" in gi.read_text()


def test_cmd_inject_no_assignment_no_all_exits(tmp_path):
    project = tmp_path / "empty_proj"
    project.mkdir()
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=False)
    with pytest.raises(SystemExit):
        cli.cmd_inject(args, vault, PASSWORD)


def test_cmd_inject_updates_existing_env(tmp_path, capsys):
    project = tmp_path / "proj2"
    project.mkdir()
    env_file = project / ".env"
    env_file.write_text("OPENAI_API_KEY=old-value\nOTHER=keep\n", encoding="utf-8")
    vault = _vault_with_key()
    args = Namespace(project=str(project), all=True)
    cli.cmd_inject(args, vault, PASSWORD)
    content = env_file.read_text()
    assert "OPENAI_API_KEY=sk-test123" in content
    assert "OTHER=keep" in content
def test_frozen_app_launcher_reexecutes_binary(monkeypatch):
    import pushkey_cli as cli

    calls = {}

    class Process:
        def __init__(self, command, env):
            calls["command"] = command
            calls["env"] = env

        def kill(self):
            pass

    class Response:
        def close(self):
            pass

    monkeypatch.setattr(cli, "_port_in_use", lambda _port: False)
    monkeypatch.setattr(cli.subprocess, "Popen", Process)
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cli.sys, "frozen", True, raising=False)

    cli._cmd_app(blocking=False)

    assert calls["command"] == [cli.sys.executable, "--local-api-server"]
    assert calls["env"]["PUSHKEY_PARENT_PID"] == str(cli.os.getpid())


def test_cmd_set_backup_uses_getpass_and_does_not_print_secret(monkeypatch, capsys):
    vault = _vault_with_key()
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-backup-secret")

    cli.cmd_set_backup(Namespace(name="OPENAI_API_KEY"), vault, PASSWORD)

    out = capsys.readouterr().out
    assert vault["OPENAI_API_KEY"]["next_value"] == "sk-backup-secret"
    assert vault["OPENAI_API_KEY"]["next_added"] is not None
    assert vault["OPENAI_API_KEY"]["dual_rotation"] is True
    assert "Backup staged for OPENAI_API_KEY" in out
    assert "sk-backup-secret" not in out


def test_cmd_set_backup_missing_key_exits(monkeypatch):
    vault = _empty_vault()
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-backup-secret")

    with pytest.raises(SystemExit):
        cli.cmd_set_backup(Namespace(name="MISSING"), vault, PASSWORD)


def test_main_parser_accepts_set_backup(monkeypatch):
    opened = {"called": False}

    def fake_open_vault(args):
        opened["called"] = True
        assert args.command == "set-backup"
        assert args.name == "OPENAI_API_KEY"
        raise SystemExit(0)

    monkeypatch.setattr(cli.sys, "argv", ["pushkey", "set-backup", "OPENAI_API_KEY"])
    monkeypatch.setattr(cli, "_open_vault", fake_open_vault)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert opened["called"] is True

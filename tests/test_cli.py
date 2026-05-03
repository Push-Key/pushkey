"""
CLI tests — call cmd_* functions directly with Namespace args.
Vault dir patched to tmp_path; password injected via PUSHKEY_MASTER env var.
"""
import json
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest
import pushkey_shared
import pushkey_cli as cli
from pushkey_vault import save_vault


PASSWORD = "cli-test-password"


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
    with pytest.raises(SystemExit):
        cli.cmd_add(args, vault, PASSWORD)


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
    with pytest.raises(SystemExit):
        cli.cmd_get(args, vault, PASSWORD)


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
    assert "1 skipped" in out
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
    with pytest.raises(SystemExit):
        cli.cmd_import(args, vault, PASSWORD)


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

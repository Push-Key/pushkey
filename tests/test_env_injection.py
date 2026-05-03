from pathlib import Path

import pushkey


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_inject_env_file_merges_existing_and_quotes_values(tmp_path: Path):
    # Pre-existing .env with an extra unmanaged key should be preserved.
    (tmp_path / ".env").write_text("EXISTING=1\nOPENAI_API_KEY=old\n", encoding="utf-8", newline="\n")

    vault = {
        "OPENAI_API_KEY": {"value": "sk-new"},
        "FOO": {"value": "bar baz"},
    }

    pushkey.inject_env_file(tmp_path, vault)

    content = _read_text(tmp_path / ".env")
    assert "# Managed by Pushkey" in content
    assert "EXISTING=1" in content
    assert "OPENAI_API_KEY=sk-new" in content
    assert "FOO=\"bar baz\"" in content

    gitignore = _read_text(tmp_path / ".gitignore")
    assert "\n.env\n" in ("\n" + gitignore + "\n")


def test_inject_env_file_does_not_duplicate_gitignore_entry(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8", newline="\n")
    vault = {"A": {"value": "1"}}

    pushkey.inject_env_file(tmp_path, vault)
    pushkey.inject_env_file(tmp_path, vault)

    gitignore = _read_text(tmp_path / ".gitignore")
    assert gitignore.splitlines().count(".env") == 1


def test_inject_env_file_respects_key_filter(tmp_path: Path):
    vault = {"A": {"value": "1"}, "B": {"value": "2"}}

    pushkey.inject_env_file(tmp_path, vault, key_names=["B"])
    content = _read_text(tmp_path / ".env")

    assert "B=2" in content
    assert "A=1" not in content


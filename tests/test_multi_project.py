"""Test linking keys to multiple projects."""
import pytest
import json
from pathlib import Path

import pushkey


@pytest.fixture
def projects(tmp_path):
    """Create test project directories."""
    proj1 = tmp_path / "project1"
    proj2 = tmp_path / "project2"
    proj3 = tmp_path / "project3"

    proj1.mkdir()
    proj2.mkdir()
    proj3.mkdir()

    return {
        "project1": str(proj1),
        "project2": str(proj2),
        "project3": str(proj3),
    }


def test_link_key_to_multiple_projects(tmp_path, monkeypatch, projects):
    """One key can be linked to multiple projects."""
    monkeypatch.setattr(pushkey, "VAULT_DIR", tmp_path / "vault")
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "vault" / "config.json")
    (tmp_path / "vault").mkdir()

    config = {
        "projects": {
            "project1": {
                "path": projects["project1"],
                "keys": ["OPENAI_API_KEY"],
            },
            "project2": {
                "path": projects["project2"],
                "keys": ["OPENAI_API_KEY"],
            },
            "project3": {
                "path": projects["project3"],
                "keys": ["OPENAI_API_KEY"],
            },
        }
    }

    (tmp_path / "vault" / "config.json").write_text(json.dumps(config))
    loaded = pushkey.load_config()

    # All projects should reference the same key
    assert "OPENAI_API_KEY" in loaded["projects"]["project1"]["keys"]
    assert "OPENAI_API_KEY" in loaded["projects"]["project2"]["keys"]
    assert "OPENAI_API_KEY" in loaded["projects"]["project3"]["keys"]


def test_multiple_keys_to_single_project(tmp_path, monkeypatch, projects):
    """One project can use multiple keys."""
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    config = {
        "projects": {
            "project1": {
                "path": projects["project1"],
                "keys": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "STRIPE_KEY"],
            }
        }
    }

    (tmp_path / "config.json").write_text(json.dumps(config))
    loaded = pushkey.load_config()

    assert len(loaded["projects"]["project1"]["keys"]) == 3
    assert "OPENAI_API_KEY" in loaded["projects"]["project1"]["keys"]
    assert "ANTHROPIC_API_KEY" in loaded["projects"]["project1"]["keys"]
    assert "STRIPE_KEY" in loaded["projects"]["project1"]["keys"]


def test_unlink_key_from_project(tmp_path, monkeypatch, projects):
    """Remove a key from a project's assignment."""
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    config = {
        "projects": {
            "project1": {
                "path": projects["project1"],
                "keys": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            }
        }
    }

    (tmp_path / "config.json").write_text(json.dumps(config))

    # Unlink one key
    loaded = pushkey.load_config()
    loaded["projects"]["project1"]["keys"].remove("OPENAI_API_KEY")
    pushkey.save_config(loaded)

    # Verify
    reloaded = pushkey.load_config()
    assert len(reloaded["projects"]["project1"]["keys"]) == 1
    assert reloaded["projects"]["project1"]["keys"][0] == "ANTHROPIC_API_KEY"


def test_project_paths_validity(tmp_path, monkeypatch, projects):
    """Project paths in config should be valid directories."""
    monkeypatch.setattr(pushkey, "CONFIG_FILE", tmp_path / "config.json")

    config = {
        "projects": {
            "project1": {
                "path": projects["project1"],
                "keys": ["OPENAI_API_KEY"],
            }
        }
    }

    (tmp_path / "config.json").write_text(json.dumps(config))
    loaded = pushkey.load_config()

    proj_path = loaded["projects"]["project1"]["path"]
    assert Path(proj_path).exists()
    assert Path(proj_path).is_dir()

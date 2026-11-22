import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web-app" / "src"


def _read(relative: str) -> str:
    return (WEB_APP / relative).read_text(encoding="utf-8")


def test_local_web_shell_has_loading_locked_and_offline_states():
    page = _read("app/page.tsx")

    assert "Preparing secure local session" in page
    assert "Loading vault status" in page
    assert "Cannot reach Pushkey local API" in page
    assert "How to reopen it" in page
    assert "from the CLI to open a fresh local session" in page
    assert "one-time launch token" in page
    assert "Offline or locked" in page


def test_local_web_core_flows_have_empty_error_and_conflict_states():
    vault = _read("components/vault-tab.tsx")
    projects = _read("components/projects-tab.tsx")
    dashboard = _read("components/dashboard-tab.tsx")

    assert "Vault is empty." in vault
    assert "No projects registered." in projects
    assert "No rotations due in the next 30 days" in dashboard
    assert "conflict" in projects.lower()
    assert "ErrorBanner" in projects


def test_add_key_form_states_connect_copy():
    vault = _read("components/vault-tab.tsx")

    assert "Saved in the vault only" in vault
    assert "Save & connect" in vault
    assert "Connect to a project" in vault


def test_connect_error_texts_cover_every_code():
    api = _read("lib/api.ts")

    for code in (
        "file_tracked_by_git",
        "project_limit",
        "project_exists",
        "migration_pending",
        "config_unreadable",
        "config_busy",
        "var_taken",
    ):
        assert code in api
    assert "this file is committed to git; Pushkey will not write secrets into it" in api


def test_written_false_is_not_a_quiet_noop():
    vault = _read("components/vault-tab.tsx")
    projects = _read("components/projects-tab.tsx")

    for text in (vault, projects):
        assert "Not written" in text
        assert "results" in text


def test_inject_result_never_shows_a_failed_write_as_success():
    projects = _read("components/projects-tab.tsx")
    start = projects.index("function InjectResult")
    end = projects.index("// ── expanded project panel")
    result_view = projects[start:end]

    # The failed files sit in their own alert region, apart from the status region.
    assert 'role="alert"' in result_view
    assert result_view.index('role="status"') < result_view.index('role="alert"')

    # The success toast fires only when nothing failed; a failure gets an error toast.
    assert re.search(r"failures\.length\s*===\s*0[^;]*toast\.success\(\"\.env injected\"\)", projects, re.S)
    assert "toast.error(" in projects

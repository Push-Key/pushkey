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

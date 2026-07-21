from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web-app" / "src"


def test_sidebar_marks_active_tab_and_lock_action_for_keyboard_users():
    text = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "aria-current" in text
    assert "aria-label=\"Lock vault\"" in text
    assert "aria-label={`Open ${label}`}" in text


def test_vault_icon_actions_have_accessible_labels():
    text = (WEB_APP / "components" / "vault-tab.tsx").read_text(encoding="utf-8")

    for label in [
        "Reveal",
        "Copy",
        "Edit metadata",
        "Set backup",
        "Promote backup",
        "Rotate",
        "Delete",
    ]:
        assert f'aria-label="{label}' in text or f"aria-label={{`{label}" in text


def test_local_web_layout_has_responsive_mobile_structure():
    page = (WEB_APP / "app" / "page.tsx").read_text(encoding="utf-8")
    sidebar = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "flex-col md:flex-row" in page
    assert "w-full md:w-56" in sidebar

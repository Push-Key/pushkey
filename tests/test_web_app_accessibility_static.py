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


def test_projects_tab_exposes_state_and_live_region_announcements():
    text = (WEB_APP / "components" / "projects-tab.tsx").read_text(encoding="utf-8")

    for required in (
        "aria-expanded={expanded}",
        "aria-controls={panelId}",
        'role="region"',
        'role="status"',
        'role="alert"',
        "aria-label={`Unassign ",
        "aria-label={`Assign ",
        "aria-label={`Delete project ",
        "aria-label={`Inject environment file for ",
    ):
        assert required in text


def test_vault_tab_announces_errors_copy_status_and_disclosure_state():
    text = (WEB_APP / "components" / "vault-tab.tsx").read_text(encoding="utf-8")

    for required in (
        'role="alert"',
        'role="status"',
        "aria-pressed={!!revealed[k.name]}",
        "aria-expanded={rotateState[k.name] !== undefined}",
        "aria-expanded={backupState[k.name] !== undefined}",
        "aria-expanded={editState[k.name] !== undefined}",
        "aria-label={`New value for ${k.name}`}",
        "aria-label={`Backup value for ${k.name}`}",
        "aria-label={`Environment for ${k.name}`}",
    ):
        assert required in text


def test_health_tab_announces_loading_and_errors():
    text = (WEB_APP / "components" / "health-tab.tsx").read_text(encoding="utf-8")

    assert 'role="status"' in text
    assert 'role="alert"' in text


def test_toast_viewport_is_a_live_region():
    text = (WEB_APP / "lib" / "toast.tsx").read_text(encoding="utf-8")

    # A polite live region, not role="status": role="status" implies
    # aria-atomic="true", which re-announces every queued toast on each push.
    assert 'aria-live="polite"' in text
    assert 'aria-label="Notifications"' in text
    assert 'role="status"' not in text

    # aria-label is prohibited on a generic div (WCAG 4.1.2, axe
    # aria-prohibited-attr), so the container needs an explicit role that
    # supports naming. role="region" names it without changing the
    # aria-atomic="false" queueing behaviour above.
    assert 'role="region"' in text


def test_layout_provides_skip_link_to_main_content():
    layout = (WEB_APP / "app" / "layout.tsx").read_text(encoding="utf-8")
    page = (WEB_APP / "app" / "page.tsx").read_text(encoding="utf-8")

    assert 'href="#main-content"' in layout
    assert 'id="main-content"' in page


def test_sidebar_badges_have_screen_reader_context():
    text = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "stale keys</span>" in text
    assert "overdue rotations</span>" in text


def test_solid_fill_status_colors_use_the_aa_contrast_tokens():
    # #ef4444 as a *background* is 3.18:1 against --color-destructive-foreground
    # and 3.76:1 against white; Tailwind orange-500 is 2.8:1 against white. All
    # are below the WCAG 2.2 AA 4.5:1 minimum for normal text, so filled
    # surfaces must use the darker -strong tokens. --color-destructive itself is
    # still correct as foreground text on the dark background.
    css = (WEB_APP / "app" / "globals.css").read_text(encoding="utf-8")
    button = (WEB_APP / "components" / "ui" / "button.tsx").read_text(encoding="utf-8")
    sidebar = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "--color-destructive-strong:" in css
    assert "--color-warning-strong:" in css

    assert "bg-[var(--color-destructive-strong)]" in button
    assert "bg-[var(--color-destructive)] text-[var(--color-destructive-foreground)]" not in button

    assert "bg-[var(--color-destructive-strong)]" in sidebar
    assert "bg-[var(--color-warning-strong)]" in sidebar
    assert "bg-orange-500" not in sidebar


def test_sidebar_footer_meta_is_not_dimmed_below_the_contrast_minimum():
    # text-[var(--color-muted-foreground)]/70 renders as #656d75 on the card
    # background: 3.6:1, below the 4.5:1 minimum. Undimmed it is 6.15:1.
    sidebar = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "text-[var(--color-muted-foreground)]/70" not in sidebar


def test_local_web_layout_has_responsive_mobile_structure():
    page = (WEB_APP / "app" / "page.tsx").read_text(encoding="utf-8")
    sidebar = (WEB_APP / "components" / "sidebar.tsx").read_text(encoding="utf-8")

    assert "flex-col md:flex-row" in page
    assert "w-full md:w-56" in sidebar

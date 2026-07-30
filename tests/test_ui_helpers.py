from datetime import datetime, timedelta
from pathlib import Path
import pushkey


def test_log_line_age_days_parses_fresh():
    now = datetime.now()
    line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] OPENAI_KEY rotated"
    age = pushkey._log_line_age_days(line)
    assert 0 <= age < 0.01  # less than ~15 seconds


def test_log_line_age_days_parses_old():
    old = datetime.now() - timedelta(days=30)
    line = f"[{old.strftime('%Y-%m-%d %H:%M:%S')}] STRIPE_SK rotated"
    age = pushkey._log_line_age_days(line)
    assert 29.9 < age < 30.1


def test_log_line_age_days_bad_format_returns_inf():
    assert pushkey._log_line_age_days("no timestamp here") == float("inf")
    assert pushkey._log_line_age_days("") == float("inf")


def test_log_line_age_days_invalid_date_returns_inf():
    assert pushkey._log_line_age_days("[2024-99-01 00:00:00] bad date") == float("inf")


import types


def test_toggle_expand_opens_key():
    class FakeApp:
        _expanded_key = None
        _rotate_pending = False
        _rotate_result = None
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    app._toggle_expand = types.MethodType(pushkey.AppFrame._toggle_expand, app)
    app._toggle_expand("OPENAI_API_KEY")
    assert app._expanded_key == "OPENAI_API_KEY"
    assert app._rotate_pending is False
    assert app._render_called is True


def test_toggle_expand_closes_same_key():
    class FakeApp:
        _expanded_key = "OPENAI_API_KEY"
        _rotate_pending = True
        _rotate_result = "some_val"
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    app._toggle_expand = types.MethodType(pushkey.AppFrame._toggle_expand, app)
    app._toggle_expand("OPENAI_API_KEY")
    assert app._expanded_key is None
    assert app._rotate_pending is False
    assert app._rotate_result is None


def test_toggle_expand_switches_key():
    class FakeApp:
        _expanded_key = "KEY_A"
        _rotate_pending = True
        _rotate_result = "old"
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    app._toggle_expand = types.MethodType(pushkey.AppFrame._toggle_expand, app)
    app._toggle_expand("KEY_B")
    assert app._expanded_key == "KEY_B"
    assert app._rotate_pending is False
    assert app._rotate_result is None


def test_start_fresh_local_vault_renames_directory(tmp_path):
    vault_dir = tmp_path / ".pushkey"
    vault_dir.mkdir()
    (vault_dir / "vault.enc").write_text("secret", encoding="utf-8")
    now = datetime(2026, 7, 30, 16, 45, 12)

    backup_dir = pushkey._start_fresh_local_vault(vault_dir=vault_dir, now=now)

    assert backup_dir == tmp_path / ".pushkey-backup-20260730-164512"
    assert backup_dir.is_dir()
    assert (backup_dir / "vault.enc").read_text(encoding="utf-8") == "secret"
    assert not vault_dir.exists()


def test_start_fresh_local_vault_avoids_name_collisions(tmp_path):
    vault_dir = tmp_path / ".pushkey"
    vault_dir.mkdir()
    (vault_dir / "vault.enc").write_text("secret", encoding="utf-8")
    now = datetime(2026, 7, 30, 16, 45, 12)
    existing = tmp_path / ".pushkey-backup-20260730-164512"
    existing.mkdir()

    backup_dir = pushkey._start_fresh_local_vault(vault_dir=vault_dir, now=now)

    assert backup_dir == tmp_path / ".pushkey-backup-20260730-164512-2"
    assert backup_dir.is_dir()
    assert (backup_dir / "vault.enc").read_text(encoding="utf-8") == "secret"


def test_start_fresh_local_vault_requires_existing_directory(tmp_path):
    missing = tmp_path / ".pushkey"

    try:
        pushkey._start_fresh_local_vault(vault_dir=missing, now=datetime(2026, 7, 30, 16, 45, 12))
    except FileNotFoundError as exc:
        assert Path(exc.filename) == missing
    else:
        raise AssertionError("expected FileNotFoundError")


def test_login_card_layout_clamps_padding_on_small_windows():
    layout = pushkey._login_card_layout(800)

    assert layout["card_padx"] == 24
    assert layout["form_padx"] == 20
    assert layout["note_wraplength"] == 240


def test_login_card_layout_expands_for_large_windows():
    layout = pushkey._login_card_layout(1280)

    assert layout["card_padx"] == 240
    assert layout["form_padx"] == 36
    assert layout["note_wraplength"] == 320

from datetime import datetime, timedelta
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

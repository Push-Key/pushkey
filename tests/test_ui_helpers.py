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

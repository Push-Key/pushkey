from datetime import datetime, timedelta
import pytest
from pushkey_providers import (
    PROVIDERS,
    days_since,
    days_since_at,
    detect_provider,
    health_status,
    health_status_at,
)


def test_detect_by_name_pattern_openai():
    assert detect_provider("OPENAI_API_KEY") == "OpenAI"


def test_detect_by_name_pattern_anthropic():
    assert detect_provider("ANTHROPIC_API_KEY") == "Anthropic"


def test_detect_by_value_prefix_openai():
    assert detect_provider("MY_KEY", "sk-abc123") == "OpenAI"


def test_detect_anthropic_prefix_beats_openai():
    # sk-ant- is longer than sk-, so Anthropic must win
    assert detect_provider("MY_KEY", "sk-ant-abc123") == "Anthropic"


def test_detect_aws_by_value_prefix():
    assert detect_provider("MY_KEY", "AKIAabc123") == "AWS"


def test_detect_github_by_name():
    assert detect_provider("GH_TOKEN") == "GitHub"


def test_detect_stripe_by_value_prefix():
    assert detect_provider("PAYMENT_KEY", "sk_live_abc") == "Stripe"


def test_detect_unknown_returns_none():
    assert detect_provider("RANDOM_KEY", "xyz123") is None


def test_detect_gitlab_by_name():
    assert detect_provider("GITLAB_TOKEN") == "GitLab"


def test_days_since_none():
    assert days_since(None) == float("inf")


def test_days_since_today():
    assert days_since(datetime.now().isoformat()) == 0


def test_days_since_old():
    assert days_since("2020-01-01T00:00:00") > 1000


def test_days_since_invalid_string():
    assert days_since("not-a-date") == float("inf")


def test_days_since_aware_timestamp_remains_invalid_for_legacy_api():
    assert days_since("2026-01-10T12:00:00+00:00") == float("inf")


def test_health_status_aware_timestamp_uses_legacy_invalid_date_behavior():
    assert health_status({"created": "2026-01-10T12:00:00+00:00"}) == "critical"


def test_days_since_at_is_deterministic():
    now = datetime(2026, 1, 10, 12, 0, 0)
    assert days_since_at("2026-01-08T12:00:00", now) == 2


def test_health_status_healthy():
    info = {"created": datetime.now().isoformat(), "provider": None}
    assert health_status(info) == "healthy"


def test_health_status_critical():
    info = {"created": "2020-01-01T00:00:00", "provider": None}
    assert health_status(info) == "critical"


def test_health_status_warning():
    dt = (datetime.now() - timedelta(days=70)).isoformat()
    info = {"created": dt, "provider": None}
    assert health_status(info) == "warning"


def test_health_status_uses_provider_threshold():
    # HashiCorp Vault rotation_days=30, so 35 days old = critical
    dt = (datetime.now() - timedelta(days=35)).isoformat()
    info = {"created": dt, "provider": "HashiCorp Vault"}
    assert health_status(info) == "critical"


def test_health_status_supabase_longer_threshold():
    # Supabase rotation_days=180, so 100 days old = healthy
    dt = (datetime.now() - timedelta(days=100)).isoformat()
    info = {"created": dt, "provider": "Supabase"}
    assert health_status(info) == "healthy"


def test_health_status_at_uses_injected_time_and_provider_threshold():
    now = datetime(2026, 1, 10, 12, 0, 0)
    info = {"created": "2025-12-06T12:00:00", "provider": "HashiCorp Vault"}
    assert health_status_at(info, now) == "critical"


def test_providers_contains_openai():
    assert "OpenAI" in PROVIDERS
    assert PROVIDERS["OpenAI"]["url"] == "https://platform.openai.com/api-keys"


def test_providers_has_rotation_days():
    for name, data in PROVIDERS.items():
        assert "rotation_days" in data, f"{name} missing rotation_days"

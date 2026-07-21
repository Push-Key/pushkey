from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ops_readiness_documents_alpha_dashboard_targets_and_alert_routes():
    text = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8").lower()

    for target in (
        "auth",
        "sync",
        "activation",
        "storage",
        "email",
        "5xx",
        "rate-limit",
    ):
        assert target in text

    for route in (
        "primary operator",
        "secondary operator",
        "ops-primary@push-key.com",
        "ops-secondary@push-key.com",
    ):
        assert route in text


def test_ops_readiness_forbids_plaintext_secret_telemetry():
    text = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8").lower()

    assert "must not include plaintext secrets" in text
    assert "request bodies" in text
    assert "authorization headers" in text
    assert "encrypted vault blob contents" in text

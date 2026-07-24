from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
WEB_APP_SRC = ROOT / "web-app" / "src"


def test_alpha_public_site_has_no_analytics_scripts_or_claims():
    files = list(WEB_SRC.rglob("*.ts")) + list(WEB_SRC.rglob("*.tsx"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    forbidden = [
        "Google Analytics",
        "gtag",
        "plausible",
        "posthog",
        "segment",
        "Anonymous usage analytics",
    ]
    for token in forbidden:
        assert token not in combined


def test_local_web_app_has_no_analytics_or_persistent_secret_storage():
    files = list(WEB_APP_SRC.rglob("*.ts")) + list(WEB_APP_SRC.rglob("*.tsx"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "localStorage" not in combined
    assert "gtag" not in combined
    assert "posthog" not in combined
    assert "plausible" not in combined

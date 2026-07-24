from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web" / "src" / "app"


def test_web_has_release_metadata_routes_and_error_pages():
    layout = (WEB_APP / "layout.tsx").read_text(encoding="utf-8")

    assert "metadataBase" in layout
    assert "alternates" in layout
    assert "canonical" in layout
    assert "openGraph" in layout
    assert "twitter" in layout
    assert (WEB_APP / "sitemap.ts").exists()
    assert (WEB_APP / "robots.ts").exists()
    assert (WEB_APP / "not-found.tsx").exists()
    assert (WEB_APP / "error.tsx").exists()


def test_web_readme_is_pushkey_runbook_not_next_template():
    readme = (ROOT / "web" / "README.md").read_text(encoding="utf-8")

    assert "create-next-app" not in readme
    assert "Operator Runbook" in readme
    assert "NEXT_PUBLIC_ADMIN_API_URL" in readme
    assert "npm run build" in readme

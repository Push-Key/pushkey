from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_DIR = ROOT / "web" / "src" / "app" / "admin"


def test_alpha_admin_surfaces_do_not_expose_unimplemented_github_hub():
    admin_text = "\n".join(
        path.read_text(encoding="utf-8") for path in ADMIN_DIR.rglob("*.tsx")
    )

    assert "/admin/github" not in admin_text
    assert "coming soon" not in admin_text.lower()

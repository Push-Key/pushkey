from pathlib import Path

import pytest

from scripts.public_export import export_public_repo


def test_public_export_copies_allowlisted_files_and_skips_generated_or_secret_paths(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "README.md").write_text("public", encoding="utf-8")
    (source / ".env").write_text("SECRET=1", encoding="utf-8")
    (source / "dist").mkdir()
    (source / "dist" / "Pushkey.exe").write_text("generated", encoding="utf-8")
    (source / "docs").mkdir()
    (source / "docs" / "guide.md").write_text("docs", encoding="utf-8")
    (source / "docs" / "__pycache__").mkdir()
    (source / "docs" / "__pycache__" / "x.pyc").write_bytes(b"cached")

    destination = tmp_path / "public"

    copied = export_public_repo(source, destination)

    assert Path("README.md") in copied
    assert Path("docs/guide.md") in copied
    assert (destination / "README.md").read_text(encoding="utf-8") == "public"
    assert not (destination / ".env").exists()
    assert not (destination / "dist").exists()
    assert not (destination / "docs" / "__pycache__").exists()


def test_public_export_rejects_destination_inside_source(tmp_path):
    source = tmp_path / "src"
    source.mkdir()

    with pytest.raises(ValueError, match="outside the source checkout"):
        export_public_repo(source, source / "public")


def test_public_export_denies_every_dotenv_variant_but_keeps_templates(tmp_path):
    # Exact-name matching on ".env" let .env.local, .env.production,
    # .env.vercel.local, and .env.production.fetched through. Those hold live
    # credentials and sit beside the tracked .env.example, so the export copied
    # real JWTs into the public boundary.
    source = tmp_path / "src"
    (source / "web").mkdir(parents=True)
    for name in (
        ".env",
        ".env.local",
        ".env.production",
        ".env.vercel.local",
        ".env.production.fetched",
        ".env.development.local",
    ):
        (source / "web" / name).write_text("TOKEN=live-secret", encoding="utf-8")
    (source / "web" / ".env.example").write_text("TOKEN=", encoding="utf-8")
    (source / "web" / "page.tsx").write_text("public", encoding="utf-8")

    destination = tmp_path / "public"
    export_public_repo(source, destination)

    leaked = sorted(p.name for p in (destination / "web").glob(".env*") if p.name != ".env.example")
    assert leaked == [], f"dotenv files leaked into the public export: {leaked}"
    assert (destination / "web" / ".env.example").exists(), "templates should still publish"
    assert (destination / "web" / "page.tsx").exists()


def test_public_export_skips_frontend_build_output(tmp_path):
    # web/.next/prerender-manifest.json and .next/cache/.previewinfo carry real
    # previewModeSigningKey / previewModeEncryptionKey values.
    source = tmp_path / "src"
    (source / "web" / ".next" / "cache").mkdir(parents=True)
    (source / "web" / ".next" / "prerender-manifest.json").write_text(
        '{"previewModeSigningKey":"live"}', encoding="utf-8"
    )
    (source / "web" / ".next" / "cache" / ".previewinfo").write_text("live", encoding="utf-8")
    (source / "web-app" / "out").mkdir(parents=True)
    (source / "web-app" / "out" / "index.html").write_text("built", encoding="utf-8")
    (source / "web-app" / "test-results").mkdir(parents=True)
    (source / "web-app" / "test-results" / "trace.zip").write_bytes(b"trace")
    (source / "web" / "page.tsx").write_text("public", encoding="utf-8")

    destination = tmp_path / "public"
    export_public_repo(source, destination)

    assert not (destination / "web" / ".next").exists()
    assert not (destination / "web-app" / "out").exists()
    assert not (destination / "web-app" / "test-results").exists()
    assert (destination / "web" / "page.tsx").exists()

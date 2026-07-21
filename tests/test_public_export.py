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

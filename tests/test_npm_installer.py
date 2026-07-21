from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "npm" / "scripts" / "install.js"
SHIMS = [
    ROOT / "npm" / "bin" / "pushkey.js",
    ROOT / "npm" / "bin" / "cli.js",
]


def test_npm_installer_fails_nonzero_for_unsupported_or_failed_install():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "process.exit(0); // non-fatal" not in text
    assert "process.exit(0); // never block npm install" not in text
    assert "process.exit(1)" in text


def test_npm_installer_documents_architecture_and_checksum_policy():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "process.arch" in text
    assert "x64" in text
    assert "arm64" in text
    assert "sha256" in text.lower()
    assert ".sha256" in text


def test_npm_shims_prevent_self_resolution_loops():
    for shim in SHIMS:
        text = shim.read_text(encoding="utf-8")
        assert "realpathSync" in text
        assert "process.execPath" in text
        assert "bin !== __filename" not in text

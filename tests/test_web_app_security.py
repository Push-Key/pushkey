from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VAULT_TAB = ROOT / "web-app" / "src" / "components" / "vault-tab.tsx"


def test_vault_tab_revealed_secrets_auto_hide_after_ten_seconds():
    text = VAULT_TAB.read_text(encoding="utf-8")

    assert "REVEAL_TIMEOUT_MS = 10_000" in text
    assert "setTimeout(() => {" in text


def test_vault_tab_clears_clipboard_after_copy_timeout():
    text = VAULT_TAB.read_text(encoding="utf-8")

    assert "CLIPBOARD_CLEAR_TIMEOUT_MS = 30_000" in text
    assert 'navigator.clipboard.writeText("")' in text


def test_web_app_does_not_persist_or_log_secret_values():
    source_files = list((ROOT / "web-app" / "src").rglob("*.ts")) + list(
        (ROOT / "web-app" / "src").rglob("*.tsx")
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_files)

    assert "localStorage" not in combined
    assert "console.log" not in combined
    session_storage_users = [
        path.relative_to(ROOT).as_posix()
        for path in source_files
        if "sessionStorage" in path.read_text(encoding="utf-8")
    ]
    assert session_storage_users == ["web-app/src/lib/auth.ts"]

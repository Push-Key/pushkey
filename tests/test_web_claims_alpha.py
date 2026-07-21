from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
PUBLIC_PATHS = [
    WEB_SRC / "components",
    WEB_SRC / "app" / "portal",
    WEB_SRC / "app" / "privacy",
    WEB_SRC / "app" / "terms",
]

DEFERRED_ALPHA_CLAIMS = [
    "CI/CD sync",
    "Team RBAC",
    "Hardware MFA",
    "YubiKey",
    "SSO",
    "SAML",
    "Vault Key USB",
    "automatic secret detection alerts",
    "webhook-triggered PR scans",
]


def test_public_alpha_copy_does_not_claim_deferred_features_are_available():
    files = []
    for path in PUBLIC_PATHS:
        if path.is_file():
            files.append(path)
        else:
            files.extend(path.rglob("*.tsx"))
            files.extend(path.rglob("*.ts"))

    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    for claim in DEFERRED_ALPHA_CLAIMS:
        assert claim not in combined

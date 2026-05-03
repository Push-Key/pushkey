# Public Repo File List

These are the ONLY files that go into github.com/Push-Key/pushkey (the open-core repo).
Everything else stays in the private repo.

## ✅ Include (open core)

### Core CLI + Crypto
- pushkey_cli.py          — CLI entry point
- pushkey_crypto.py       — AES-256-GCM, Argon2id KDF, audit log
- pushkey_vault.py        — vault load/save
- pushkey_shared.py       — path constants (strip ACTIVATION_SERVER + LICENSE_FILE refs)
- pushkey_providers.py    — provider detection
- providers.json          — 32+ provider patterns

### Package / Install
- requirements.txt        — runtime deps (strip customtkinter, pystray, boto3, fido2)
- pyproject.toml          — pip package config (strip pushkey-gui entry point)
- npm/                    — npm wrapper package
- LICENSE
- README.md
- SECURITY.md
- CONTRIBUTING.md         — (create)
- .gitignore

### Tests (open core only)
- tests/conftest.py
- tests/test_vault_crypto.py
- tests/test_encryption_edge_cases.py
- tests/test_key_rotation.py
- tests/test_env_injection.py
- tests/test_multi_project.py
- tests/test_provider_detection.py
- tests/test_providers.py
- tests/test_cli.py

## ❌ Exclude (proprietary — private repo only)

- pushkey.py              — full desktop GUI
- pushkey_tiers.py        — license gates
- pushkey_cloud_api.py    — cloud sync backend
- pushkey_icons.py        — icon library (can open source later)
- build_exe.py            — PyInstaller build pipeline
- Pushkey.spec
- pushkey-cli.spec
- PushkeyDebug.spec
- server/                 — cloud backend
- web/                    — Next.js dashboard
- vscode-pushkey/         — VS Code extension (can open source later)
- browser-pushkey/        — Chrome extension (can open source later)
- dist/                   — build output
- build/                  — PyInstaller cache
- tests/test_tiers.py     — tests license-gated features
- tests/test_ui_helpers.py
- *.log
- .license
- .token

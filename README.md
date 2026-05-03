# 🔑 Pushkey

*The encrypted API key manager built for developers — secure vault, smart rotation, zero plaintext on disk.*

[![Version](https://img.shields.io/badge/version-2.1.0-cyan?style=flat-square)](https://github.com/ebothegreat/pushkey/releases)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-107%20passing-brightgreen?style=flat-square)](tests/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)](#installation)
[![Stars](https://img.shields.io/github/stars/ebothegreat/pushkey?style=flat-square)](https://github.com/ebothegreat/pushkey/stargazers)

Pushkey stores, rotates, and injects your API keys using AES-256-GCM encryption with Argon2id key derivation — the same primitives used in password managers you already trust. The vault never writes plaintext to disk. The cloud sync backend is zero-knowledge: even we can't read your keys.

---

## 📋 Table of Contents

- [Why Pushkey](#-why-pushkey)
- [Quick Start](#-quick-start)
- [CLI Reference](#-cli-reference)
- [Vault Format & Crypto](#-vault-format--crypto)
- [Features](#-features)
- [Tier Comparison](#-tier-comparison)
- [Security Controls](#-security-controls)
- [Architecture](#-architecture)
- [Tests](#-tests)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🤔 Why Pushkey

Most developers manage API keys in `.env` files, shell profiles, or their brain. That means:

- Keys committed to git by accident
- Keys shared over Slack in plaintext
- No idea when `sk-abc123` was last rotated
- No way to revoke one key without touching 6 projects

Pushkey fixes this. One encrypted vault. Every key has a rotation timestamp, a health status, and a provider tag. The CLI injects directly into `.env` — and always ensures `.gitignore` has `.env` before it does.

---

## ⚡ Quick Start

### Prerequisites

- Python 3.12+
- pip

### Install

```bash
pip install pushkey
```

Or from source:

```bash
git clone https://github.com/ebothegreat/pushkey.git
cd pushkey
pip install -r requirements.txt
```

### Initialize your vault

```bash
pushkey init
```

You'll be prompted to set a master password. A V3 vault is created at `~/.pushkey/vault.enc` with a recovery key slot — printed once, save it somewhere safe.

### Add your first key

```bash
pushkey add OPENAI_API_KEY sk-abc123
```

### Inject into a project

```bash
cd ~/my-project
pushkey inject
```

This writes your assigned keys to `.env` and ensures `.gitignore` contains `.env`.

### Run the GUI

```bash
python pushkey.py
```

---

## 💻 CLI Reference

```
  Commands:
    add        <NAME> [VALUE]     Store a new key  (--generate for random value)
    get        <NAME>             Print or copy a key  (--clip)
    list                          List all keys + health status
    rotate     <NAME> [VALUE]     Rotate to a new value  (--generate)
    delete     <NAME>             Remove a key
    status                        Vault health summary
    inject                        Write keys to .env  (--env prod|dev|staging)
    import     <FILE>             Bulk import from a .env file
    assign     <NAME> <PATH>      Assign key to a project  (--remove to unassign)
    info       <NAME>             Show full key metadata
    history    <NAME>             Show rotation history  (--reveal to unmask)
    note       <NAME> [TEXT]      Add or update a note on a key
    log                           Show audit log  (--limit N  --key NAME)
    passwd                        Change master password
    init                          Create a new vault (first-time setup)
    completion <bash|zsh|ps>      Print shell completion script

  Options:
    -p, --password  Master password  (or set PUSHKEY_MASTER env var)
    -h, --help      Show help for any command
```

**Common patterns:**

```bash
# Add a key with auto-detected provider
pushkey add STRIPE_SECRET_KEY sk_live_...

# Generate a random 32-byte key
pushkey add MY_SIGNING_SECRET --generate

# Copy to clipboard without printing
pushkey get OPENAI_API_KEY --clip

# Inject only prod keys into this project
pushkey inject --env prod

# Bulk import from an existing .env file
pushkey import .env.backup

# Shell completion (add to your ~/.bashrc)
pushkey completion bash >> ~/.bashrc
```

> [!TIP]
> Set `PUSHKEY_MASTER` in your shell profile to skip the password prompt in scripts. Use a separate service account password — never your personal master password.

---

## 🔐 Vault Format & Crypto

> This is the section we want the security community to audit. All crypto is in [`pushkey_crypto.py`](pushkey_crypto.py). See [SECURITY.md](SECURITY.md) for the full specification.

### V3 Vault (current)

```
┌─────────────────────────────────────────────────────────┐
│  Magic:      PK3\x00  (4 bytes)                         │
│  pw_salt:    32 bytes  — Argon2id salt for master pw    │
│  rec_salt:   32 bytes  — Argon2id salt for recovery key │
│  pw_nonce:   12 bytes  ┐                                │
│  pw_ct:      48 bytes  ┘ AES-256-GCM(vault_key, pw_key) │
│  rec_nonce:  12 bytes  ┐                                │
│  rec_ct:     48 bytes  ┘ AES-256-GCM(vault_key,rec_key) │
│  body_nonce: 12 bytes  ┐                                │
│  body_ct:    variable  ┘ AES-256-GCM(vault_key, JSON)   │
└─────────────────────────────────────────────────────────┘
```

**Two independent ways to unlock the vault:**
1. **Master password** → `Argon2id(pw, pw_salt)` → decrypt `vault_key` → decrypt body
2. **Recovery code** (`PUSH-XXXX-XXXX-XXXX-XXXX`, 80-bit entropy) → `Argon2id(code, rec_salt)` → decrypt `vault_key` → decrypt body

The `vault_key` is a random 256-bit key generated at vault creation. It never touches disk in plaintext. Both slots encrypt the same `vault_key`, so rotating your master password re-encrypts only the password slot — the recovery slot and vault body are untouched.

### Key Derivation

```python
# Argon2id (preferred — memory-hard, GPU-resistant)
Argon2id(secret=password, salt=salt, time=3, memory=64MB, parallelism=4, hash_len=32)

# PBKDF2-SHA256 fallback (if argon2-cffi not installed)
PBKDF2(password, salt, iterations=600_000)
```

### Vault Format History

| Version | Magic | Encryption | KDF | Recovery Key |
|---------|-------|-----------|-----|:------------:|
| V3 (current) | `PK3\x00` | AES-256-GCM | Argon2id | ✓ |
| V2 (legacy) | `PK2\x00` | AES-256-GCM | Argon2id | — |
| V1 (legacy) | *(none)* | Fernet/AES-128-CBC | PBKDF2 | — |

V2 and V1 vaults are auto-detected and auto-migrated on first open. No manual action needed.

> [!NOTE]
> The recovery code is shown exactly once at vault creation. Pushkey does not store it — not on disk, not in the cloud. Treat it like a seed phrase.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔒 **AES-256-GCM vault** | Authenticated encryption — any tampering invalidates the MAC |
| 🧠 **Argon2id KDF** | Memory-hard, GPU-resistant key derivation (64 MB, time=3) |
| 🔑 **Recovery key** | `PUSH-XXXX-XXXX-XXXX-XXXX` format, 80-bit entropy, independent unlock slot |
| 🔄 **Rotation tracking** | Per-key history with timestamps; health status (fresh / aging / critical) |
| 🏷️ **Provider detection** | Auto-tags 32+ providers (OpenAI, Stripe, AWS, GitHub, etc.) by key name/prefix |
| 💉 **`.env` injection** | Writes to `.env`, always adds `.env` to `.gitignore` first |
| 🗂️ **Multi-project** | Assign any key to multiple projects; inject per-project or by env tier |
| 🌍 **Env tiers** | Tag keys as `dev`, `staging`, `prod`, or `all`; inject only what you need |
| 📋 **Bulk import** | Drop `.env` files into `~/.pushkey/import/` and scan in one command |
| 🖥️ **Desktop GUI** | CustomTkinter GUI with dark/light themes, neon stat cards, rotation heatmap |
| 🔐 **MFA** | TOTP (Google Authenticator) + FIDO2/YubiKey (Enterprise) |
| ☁️ **Zero-knowledge sync** | AES-GCM ciphertext only — server never sees plaintext |
| 🕵️ **Git history scan** | Scans commit history for accidentally committed key patterns |
| 📊 **Encrypted audit log** | Per-entry AES-256-GCM binary log; deterministic replay of every operation |
| 🔧 **VS Code extension** | Decorates editors with key health status from `health.json` |
| 🌐 **Chrome extension** | Real-time key status in the browser via local health server (port 7654) |
| ⚡ **CI/CD sync** | Push secrets to GitHub Actions, Vercel, and Netlify (Pro+) |

---

## 💼 Tier Comparison

| Feature | Free | Starter | Pro | Team | Enterprise |
|---------|:----:|:-------:|:---:|:----:|:----------:|
| Keys | 15 | 50 | ∞ | ∞ | ∞ |
| Projects | 1 | 3 | ∞ | ∞ | ∞ |
| Devices | 1 | 1 | 3 | 5 | ∞ |
| Cloud sync | — | ✓ | ✓ | ✓ | ✓ |
| CI/CD sync | — | — | ✓ | ✓ | ✓ |
| Git scan | — | ✓ | ✓ | ✓ | ✓ |
| Team RBAC | — | — | — | ✓ | ✓ |
| TOTP MFA | ✓ | ✓ | ✓ | ✓ | ✓ |
| YubiKey MFA | — | — | — | — | ✓ |
| SSO (SAML/Okta/Azure AD) | — | — | — | — | ✓ |
| Dynamic secrets | — | — | — | — | ✓ |

[Get a license → pushkey.dev](https://pushkey.dev)

---

## 🛡️ Security Controls

| Control | Behavior |
|---------|----------|
| **Master password** | Never stored anywhere — vault is useless without it |
| **Vault key isolation** | Random 256-bit key encrypts the body; neither password nor recovery code touch data directly |
| **Atomic writes** | Vault saved to `.tmp` then `os.replace()` — no partial writes possible |
| **File permissions** | `vault.enc` and `.salt` written with `chmod 600` |
| **Rolling backups** | Last 3 vault backups kept at `~/.pushkey/vault_backup_*.enc` |
| **No plaintext on disk** | All vault data, config, and audit log are encrypted at rest |
| **`.gitignore` guard** | `inject` always adds `.env` to `.gitignore` before writing |
| **Zero-knowledge cloud** | Sync backend stores only ciphertext; server has no key material |

> [!WARNING]
> If you lose both your master password **and** your recovery code, your vault cannot be recovered by anyone — including us. Store your recovery code offline (paper, a separate password manager, or a safety deposit box).

---

## 🏗️ Architecture

```
~/.pushkey/
├── vault.enc              — AES-256-GCM encrypted vault (V3)
├── .salt                  — 32-byte random salt (chmod 600)
├── config.json            — AES-256-GCM encrypted project config
├── pushkey.log            — Encrypted binary audit log
├── health.json            — Public sidecar: health + timestamps (no secrets)
├── .license               — AES-GCM encrypted tier/license token
├── .mfa                   — Encrypted TOTP secret
├── .fido2                 — FIDO2 credential blob
└── import/                — Drop zone for bulk .env imports

pushkey/
├── pushkey.py             — Desktop GUI (CustomTkinter)
├── pushkey_cli.py         — Standalone CLI                  ← open core
├── pushkey_crypto.py      — Crypto primitives, KDF, log     ← open core
├── pushkey_vault.py       — Vault I/O (load/save/config)    ← open core
├── pushkey_shared.py      — Path constants, tier schema     ← open core
├── pushkey_providers.py   — Provider detection (32+)        ← open core
├── providers.json         — Provider pattern registry       ← open core
├── pushkey_icons.py       — 27 Lucide-style PIL icons
├── pushkey_tiers.py       — License gates + heartbeat
├── pushkey_cloud_api.py   — FastAPI zero-knowledge backend
├── vscode-pushkey/        — VS Code extension
├── browser-pushkey/       — Chrome/Edge MV3 extension
└── web/                   — Next.js admin dashboard
```

---

## 🧪 Tests

```bash
# Run all 107 tests
pytest

# Single module
pytest tests/test_vault_crypto.py -v

# With coverage
pytest --cov=. --cov-report=term-missing
```

| Test File | What It Covers |
|-----------|----------------|
| `test_vault_crypto.py` | Vault round-trip, V2/V3/legacy formats |
| `test_encryption_edge_cases.py` | Edge-case values, special characters |
| `test_key_rotation.py` | Rotation timestamps, history |
| `test_env_injection.py` | `.env` merge, gitignore dedup |
| `test_multi_project.py` | Project link/unlink |
| `test_provider_detection.py` | Provider pattern matching |
| `test_providers.py` | `pushkey_providers` module (20 tests) |
| `test_cli.py` | CLI commands (26 tests) |
| `test_tiers.py` | License, tier gates, heartbeat (23 tests) |
| `test_ui_helpers.py` | `_log_line_age_days` |

---

## 🤝 Contributing

Pull requests welcome. The highest-impact areas:

- **New providers** in `providers.json` — add a pattern entry and a test case
- **Security review** of `pushkey_crypto.py` — open an issue for any findings (see [SECURITY.md](SECURITY.md))
- **CLI improvements** — new commands, better error messages, platform testing
- **Shell completions** — improving bash/zsh/PowerShell completion coverage

```bash
git clone https://github.com/ebothegreat/pushkey.git
cd pushkey
pip install -r requirements-dev.txt
pytest   # confirm everything passes before opening a PR
```

> [!NOTE]
> PRs that touch `pushkey_tiers.py` or the cloud backend are outside the open-core contribution surface and will be closed.

---

## 📄 License

MIT © [Pushkey](https://pushkey.dev)

See [SECURITY.md](SECURITY.md) for the full vault format specification and responsible disclosure process.

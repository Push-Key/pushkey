# Pushkey

**Encrypted API key vault with direct `.env` injection into your projects.**

Pushkey is a desktop app that stores your API keys encrypted, tracks rotation health, links to provider dashboards, and automatically writes `.env` files directly into your project folders when keys change. No copy-paste, no exporting, no forgetting.

---

## Why Pushkey?

You have API keys scattered across text files, Slack messages, and browser tabs. You forget which projects use which keys. You don't know when you last rotated your OANDA token. When you do rotate, you have to manually update `.env` files in three different project folders.

Pushkey fixes all of that:

- **One vault** — All your keys in one encrypted place
- **Health tracking** — Green/yellow/red dots show which keys need rotation
- **Provider links** — One click opens the exact page to generate a new key
- **Direct injection** — When you update a key, Pushkey writes the new `.env` file directly into every linked project folder
- **Auto-gitignore** — Automatically adds `.env` to `.gitignore` so you never commit secrets

---

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Run Pushkey
python pushkey.py
```

First launch: create a master password. Every launch after: enter your password to unlock.

---

## How it works

### 1. Add your keys
Go to the **All Keys** tab. Paste in your API key with a name like `OPENAI_API_KEY`. Pushkey auto-detects the provider (OpenAI, Alpaca, OANDA, Stripe, etc.) and sets the rotation schedule.

### 2. Link your projects
Go to the **Projects** tab. Click "Browse" and point to your project folder (e.g., `~/projects/phase-omega`). Use "Assign keys" to pick which keys that project needs.

### 3. Auto-sync
When you add or rotate a key, Pushkey immediately writes the updated `.env` file into every linked project that uses that key. Your code stays the same:

```python
from dotenv import load_dotenv
import os

load_dotenv()
key = os.environ["OANDA_API_KEY"]  # always up to date
```

### 4. Rotate with confidence
The **Dashboard** tab shows key health at a glance. When a key turns yellow (60+ days) or red (90+ days), click the arrow button to open the provider's key management page directly. Paste the new key back into Pushkey — it saves the old one as backup, timestamps the rotation, and pushes to all projects.

---

## Supported providers

Pushkey auto-detects these providers from your key names and links to their dashboards:

| Provider | Dashboard URL | Category |
|----------|--------------|----------|
| OpenAI | platform.openai.com/api-keys | AI |
| Anthropic | console.anthropic.com/settings/keys | AI |
| Alpaca | app.alpaca.markets | Trading |
| OANDA | oanda.com/account/tpa/personal_token | Trading |
| Coinbase | coinbase.com/settings/api | Trading |
| Supabase | supabase.com/dashboard | Database |
| Stripe | dashboard.stripe.com/apikeys | Payment |
| AWS | console.aws.amazon.com/iam | Cloud |
| Vercel | vercel.com/account/tokens | Cloud |

Any key not matching a known provider works normally — it just won't have a direct dashboard link.

---

## Where are my keys stored?

```
~/.pushkey/
├── vault.enc    ← Your keys (AES-256 encrypted)
├── .salt        ← Encryption salt (do not delete)
└── config.json  ← Project paths and assignments (not sensitive)
```

- Encrypted with AES-256-GCM via PBKDF2 (200,000 iterations)
- File permissions set to owner-only (chmod 600)
- Nothing leaves your machine
- Master password is never stored

---

## Security

- **AES-256 encryption** via the `cryptography` library (falls back to basic obfuscation without it)
- **PBKDF2-HMAC-SHA256** key derivation with 200,000 iterations
- **Clipboard auto-clear** after 30 seconds when you copy a key
- **Auto-hide** revealed keys after 10 seconds
- **No network access** — Pushkey never phones home
- **`.gitignore` protection** — automatically adds `.env` to `.gitignore` in every linked project

---

## Requirements

- Python 3.8+
- `tkinter` (included with most Python installations)
- `cryptography` (required)

---

## Development

### Setup

```bash
# Clone the repo
git clone <repo>
cd pushkey

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dev dependencies
pip install -r requirements-dev.txt

# Install the package in editable mode (optional)
pip install -e .
```

### Testing

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_provider_detection.py

# Run with verbose output
pytest -v

# Tests use a repo-local temp directory (.pytest_tmp) for isolation
```

### Building a Windows executable

```bash
# Install build tools
pip install -r requirements-dev.txt

# Build the executable
python build_exe.py

# Executable will be in dist/Pushkey.exe
```

---

## License

MIT

# Contributing to Pushkey

Thanks for helping. The open-core contribution surface is:

- **`pushkey_cli.py`** — CLI commands, UX, shell completions
- **`pushkey_crypto.py`** — crypto primitives (security review especially welcome)
- **`pushkey_vault.py`** — vault I/O
- **`pushkey_providers.py`** — provider detection logic
- **`providers.json`** — provider pattern registry
- **`tests/`** — test coverage for the above

## What's not in scope

`pushkey_tiers.py`, `pushkey_cloud_api.py`, the desktop GUI, and the web dashboard are proprietary and not part of this repo. PRs touching those will be closed.

## How to contribute

```bash
git clone https://github.com/Push-Key/pushkey.git
cd pushkey
pip install -r requirements.txt
pip install pytest
pytest   # make sure everything passes first
```

### Adding a provider

1. Open `providers.json`
2. Add an entry following the existing pattern:
```json
{
  "name": "MyProvider",
  "patterns": ["MY_PROVIDER_", "MYPROVIDER_KEY"],
  "prefix": "mp_",
  "url": "https://myprovider.com/dashboard/api-keys"
}
```
3. Add a test case to `tests/test_provider_detection.py`
4. Open a PR — no issue needed for provider additions

### Security findings

Please do **not** open a public issue for security vulnerabilities. Email security@pushkey.dev instead. See [SECURITY.md](SECURITY.md) for the full disclosure process.

### PR checklist

- [ ] `pytest` passes with no failures
- [ ] New functionality has a test
- [ ] No changes to `pushkey_tiers.py` or anything not listed above

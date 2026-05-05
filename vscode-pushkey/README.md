# Pushkey — Key Health

VS Code gutter decorations for `.env` files. Shows API key rotation health from your local [Pushkey](https://github.com/Push-Key/pushkey) vault.

## What it does

Open any `.env` file. Each `KEY=value` line gets a colored gutter icon based on how stale the key is:

| Icon | Status | Meaning |
|------|--------|---------|
| Green | Healthy | Recently rotated |
| Amber | Warning | Approaching rotation window |
| Red | Critical | Overdue — rotate now |

No secrets ever read from `.env`. Status comes from `~/.pushkey/health.json`, a public sidecar Pushkey writes — no master password required.

## Requirements

- [Pushkey](https://github.com/Push-Key/pushkey) installed and at least one key tracked.
- `~/.pushkey/health.json` present (Pushkey writes it on every vault save).

## Commands

- **Pushkey: Refresh Key Health** — re-reads `health.json` and re-decorates the active editor.

## Privacy

This extension reads only `~/.pushkey/health.json`. It never opens `vault.enc`, never asks for a password, never sends data anywhere.

## License

MIT

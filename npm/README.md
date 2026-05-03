# pushkey (npm)

This is the npm distribution package for the [Pushkey CLI](https://github.com/Push-Key/pushkey).

## Install

```bash
npm install -g @pushkey/cli
```

or for one-off use:

```bash
npx @pushkey/cli list
```

## What it does

Downloads the correct pre-built binary for your platform (Windows/macOS/Linux) from GitHub Releases.
Falls back to `pip install pushkey` if no binary is available for your architecture.

## Usage

```bash
pushkey init                          # create encrypted vault
pushkey add OPENAI_API_KEY sk-...     # store a key
pushkey list                          # list all keys + health
pushkey inject                        # write to .env
pushkey --help                        # full command reference
```

Full docs: [github.com/Push-Key/pushkey](https://github.com/Push-Key/pushkey)

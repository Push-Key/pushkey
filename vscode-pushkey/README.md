# Pushkey Key Health

Status: beta/deferred until the package/store gates pass.

VS Code gutter decorations for `.env` files. It shows API key rotation health
from the local [Pushkey](https://github.com/Push-Key/pushkey) vault without
reading secret values.

## What It Does

Open an `.env` file. Each `KEY=value` line can receive a gutter icon based on
its Pushkey rotation status: healthy, warning, or critical.

## Requirements

- [Pushkey](https://github.com/Push-Key/pushkey) installed with at least one
  tracked key.
- `~/.pushkey/health.json` published by Pushkey.

## Health Contract

The extension accepts the strict version 1 health envelope and a temporary
legacy format only when it is current. It reads no more than 1 MiB, rejects
malformed or unsupported data, and clears decorations when health is missing,
invalid, older than 26 hours, or more than five minutes in the future. It
watches the Pushkey directory so atomic sidecar replacement and a directory
created after extension activation are handled safely.

## Privacy

This extension reads only `~/.pushkey/health.json`. It never opens `vault.enc`,
asks for a password, reads `.env` values, or sends data anywhere. The sidecar
contains local-sensitive metadata such as eligible key names and provider
identifiers; it never contains secret values.

## License

MIT

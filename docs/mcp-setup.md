# Pushkey MCP Setup

## Claude Code (stdio transport)

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pushkey": {
      "command": "python",
      "args": ["C:/Users/<YOU>/bots/pushkey/pushkey_mcp.py"],
      "env": {}
    }
  }
}
```

Replace `C:/Users/<YOU>/bots/pushkey/` with your actual path.

## VS Code Copilot (SSE transport)

Start the server in SSE mode:
```bash
python pushkey_mcp.py --port 8765
```

Add to `.vscode/mcp.json` in your workspace:
```json
{
  "servers": {
    "pushkey": {
      "type": "sse",
      "url": "http://localhost:8765/sse"
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `unlock_vault` | Unlock with master password (required first) |
| `lock_vault` | Clear session |
| `list_keys` | List all keys (no values); filter by env/provider/project |
| `get_key` | Get a key's value by name |
| `add_key` | Add a new key to the vault |
| `inject_env` | Write the keys connected to a registered project into its env file + add the file to `.gitignore` (scope: inject) |
| `check_health` | Report stale/expiring keys |
| `rotate_key` | Update a key's value + rotation date; rewrites every connected file when the session has the inject scope, else lists them as `not_synced` |
| `rotate_to_backup` | Promote the staged backup key (name only); syncs connected files like `rotate_key` |
| `set_backup_key` | Stage a backup key for dual rotation (Pro+) |
| `list_projects` | Show all projects and their assigned keys |
| `assign_key` | Connect a key to a registered project without writing its env file (scope: write) |
| `preview_connection` | Show what connecting a key to a project would do: the exact line, add/replace/none, `.gitignore` change, needed confirmations (scope: read; no value can be passed) |
| `connect_key` | Connect an existing key, by name, to a variable in a registered project's env file and write it (scopes: write and inject; the secret is never passed in) |
| `key_usage` | Where a key is connected and whether each file is up to date (scope: read) |

No connection tool returns a key value. `assign_key`, `inject_env` and `connect_key` only work on
a folder a person has added as a project in Pushkey; any other folder is refused with
`project_not_registered` (an agent never registers a project). A store that has not been migrated
yet answers `migration_pending` to agent-token sessions: open Pushkey once with the master
password. Unlocking with the master password runs that migration; unlocking with an agent token
never changes the vault or the project store.

## Typical workflow

1. `unlock_vault("my-master-password")`
2. `list_keys()` — see what's available
3. `get_key("OPENAI_API_KEY")` — retrieve value for use
4. `connect_key("OPENAI_API_KEY", "/path/to/project")` — connect a key to a registered project's `.env` (use `preview_connection` first to see the line it will write)
5. `inject_env("/path/to/project")` — rewrite every connected key in that project's `.env`
6. `check_health()` — find stale keys before deploying

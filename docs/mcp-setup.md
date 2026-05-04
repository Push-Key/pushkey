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
| `inject_env` | Write keys to project `.env` + add to `.gitignore` |
| `check_health` | Report stale/expiring keys |
| `rotate_key` | Update a key's value + rotation date |
| `list_projects` | Show all projects and their assigned keys |
| `assign_key` | Link a key to a project path |

## Typical workflow

1. `unlock_vault("my-master-password")`
2. `list_keys()` — see what's available
3. `get_key("OPENAI_API_KEY")` — retrieve value for use
4. `inject_env("/path/to/project", keys=["OPENAI_API_KEY", "STRIPE_KEY"])` — populate .env
5. `check_health()` — find stale keys before deploying

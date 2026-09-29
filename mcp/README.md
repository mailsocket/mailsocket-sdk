# mailsocket — MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes
[mailsocket](https://mailsocket.app) to AI coding agents as native tools, so an
agent can create a throwaway inbox and **block on the OTP or magic link**
without writing any polling code. It wraps the
[Python SDK](https://github.com/mailsocket/mailsocket-sdk/tree/main/python) —
no second HTTP client, no re-implemented polling.

## What it does

| Tool | What the agent gets |
| --- | --- |
| `create_inbox(label?)` | a fresh inbox `id` + `address` |
| `wait_for_otp(inbox_id, timeout?=60, min_confidence?=0)` | **the headline** — blocks (bounded, clamped to 120s requested deadline) and returns the OTP string + confidence + subject/from |
| `wait_for_link(inbox_id, timeout?=60)` | the extracted magic link (returned, *not* followed) |
| `list_inboxes(limit?, cursor?)` | one page of inboxes owned by the key (server default page size 25) + `next_cursor`/`has_more` |
| `list_messages(inbox_id, has_otp?, subject_contains?, sender?, limit?, cursor?)` | one page of messages, optionally filtered (server default page size 25) + `next_cursor`/`has_more` |
| `get_latest(inbox_id)` | the newest message, without blocking |
| `delete_inbox(inbox_id)` | remove an inbox when done |

Errors from the SDK (`AuthError` / `NotFound` / `RateLimited` / `WaitTimeout`)
are turned into clean MCP tool errors — no stack traces, and the API key is
never echoed back.

## Requirements

- Python 3.10+
- A mailsocket API key — from the [dashboard](https://dash.mailsocket.app) or
  `POST /api/v1/agents/register`.

## Install

No install needed with [uv](https://docs.astral.sh/uv/):

```bash
uvx mailsocket-mcp
```

Or install with pip:

```bash
pip install mailsocket-mcp
mailsocket-mcp
```

Either way, it reads `MAILSOCKET_API_KEY` (and optional
`MAILSOCKET_BASE_URL`) from the environment. If the key is missing it exits
with a clear message and status 2; the key is never logged.

## Register with an MCP client

### Claude Desktop / Cursor

Add this to your client's MCP config file — `claude_desktop_config.json` for
Claude Desktop, `~/.cursor/mcp.json` for Cursor:

```json
{
  "mcpServers": {
    "mailsocket": {
      "command": "uvx",
      "args": ["mailsocket-mcp"],
      "env": {
        "MAILSOCKET_API_KEY": "ms_live_..."
      }
    }
  }
}
```

### Claude Code CLI

```bash
claude mcp add mailsocket -e MAILSOCKET_API_KEY=ms_live_... -- uvx mailsocket-mcp
```

Any other MCP-compatible client works the same way: point it at the
`mailsocket-mcp` executable (or `uvx mailsocket-mcp`) over stdio and pass the
key through the environment.

## Env vars

| Variable | Required | Description |
| --- | --- | --- |
| `MAILSOCKET_API_KEY` | yes (secret) | Your mailsocket API key (`ms_live_...`). |
| `MAILSOCKET_BASE_URL` | no | Override the API base URL. Defaults to `https://dash.mailsocket.app/api/v1`. |

## Develop

```bash
pip install -e ".[dev]"
pytest
```

Tests are fully offline — the SDK client is faked, so nothing touches the live
API.

<!-- mcp-name: app.mailsocket/mailsocket-mcp -->

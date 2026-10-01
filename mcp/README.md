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
| `wait_for_otp(inbox_id, timeout?=60, min_confidence?=0, since?)` | **the headline** — blocks (bounded: requested deadline clamped to 120s locally, 55s on the remote server) and returns the OTP string + confidence + subject/from/id/received_at |
| `wait_for_link(inbox_id, timeout?=60, since?)` | the extracted magic link (returned, *not* followed) + subject/from/id/received_at |
| `list_inboxes(limit?, cursor?)` | one page of inboxes owned by the key (server default page size 25) + `next_cursor`/`has_more` |
| `list_messages(inbox_id, has_otp?, subject_contains?, sender?, limit?, cursor?)` | one page of messages, optionally filtered (server default page size 25) + `next_cursor`/`has_more` |
| `get_latest(inbox_id)` | the newest message, without blocking |
| `delete_inbox(inbox_id)` | remove an inbox when done |

Errors from the SDK (`AuthError` / `NotFound` / `RateLimited` / `WaitTimeout`)
are turned into clean MCP tool errors — no stack traces, and the API key is
never echoed back.

### Reusing an inbox

`create_inbox` needs no `since` — a fresh inbox only ever has new messages.
But if you reuse an existing inbox (e.g. to request a second OTP/link), pass
`since` to `wait_for_otp`/`wait_for_link`: otherwise the wait can match the
OLDEST retained message instead of the new one you just triggered. Pass
either the time right before you triggered the new email (ISO8601 or unix
seconds), or the `id` of the last message you saw (`msg_...`, meaning "only
messages after that one") — both tools return `id`/`received_at` on the
matched message so you can chain `since=<id>` into the next call on that same
inbox.

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

## Remote server (no install)

The same tools are hosted at **`https://mcp.mailsocket.app/mcp`** over
Streamable HTTP. Send your key on every request as a header:
`Authorization: Bearer ms_live_...`. Never put the key in the URL; a
`?api_key=` request is rejected.

### Claude Code CLI

```bash
claude mcp add --transport http mailsocket https://mcp.mailsocket.app/mcp \
  --header "Authorization: Bearer ms_live_..."
```

### Cursor (`~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "mailsocket": {
      "url": "https://mcp.mailsocket.app/mcp",
      "headers": { "Authorization": "Bearer ms_live_..." }
    }
  }
}
```

### VS Code (`.vscode/mcp.json`)

```json
{
  "servers": {
    "mailsocket": {
      "type": "http",
      "url": "https://mcp.mailsocket.app/mcp",
      "headers": { "Authorization": "Bearer ms_live_..." }
    }
  }
}
```

Any client that can set a custom HTTP header works the same way (OpenAI Agents
SDK, the n8n MCP Client node, your own code).

Things to know:

- **Claude.ai, Claude Desktop connectors and Smithery need OAuth**, which is
  planned but not available yet. Until then, use the local stdio server above
  in those clients (Claude Desktop), or use a header-capable client.
- On the remote server, `wait_for_otp` / `wait_for_link` wait at most **55s** per
  call, which keeps each response under proxy timeouts. On a timeout, call the
  tool again.
- The server is stateless: no session to keep, and every request is
  authenticated on its own. It has no key of its own and only acts with yours,
  under your normal API rate limits.
- Self-hosting: `mailsocket-mcp-http` runs the same server (see
  `mailsocket_mcp/remote.py` for its env vars).

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

Tests make no external or live-API requests. The SDK client is faked, and the
remote-transport tests talk to a local fake upstream on `127.0.0.1`.

## Changelog

- **0.2.3** — `wait_for_otp` / `wait_for_link` accept an optional `since` (ISO8601, unix seconds or a message id) so a reused inbox returns the NEW code; results include the message `id` and `received_at`.
- **0.2.2** — depends on `mailsocket>=0.1.3` (stricter `_seg` id validation in the underlying Python SDK).

<!-- mcp-name: app.mailsocket/mailsocket-mcp -->

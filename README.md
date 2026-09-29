# mailsocket SDKs & MCP server

[mailsocket](https://mailsocket.app) is an inbox API for OTP and magic-link
signup automation: email in, JSON out. `GET
/inboxes/{id}/messages/wait?require=otp` blocks and returns the OTP the
instant it arrives — no polling, no IMAP. Built for signup automation, E2E
tests, and AI agents.

This repo holds the official client packages.

| Package | Install | Docs |
| --- | --- | --- |
| Python | `pip install mailsocket` | [python/](python/) |
| TypeScript / Node | `npm i mailsocket-sdk` | [typescript/](typescript/) |
| MCP server (AI agents) | `uvx mailsocket-mcp` | [mcp/](mcp/) |

Full docs: [mailsocket.app](https://mailsocket.app) ·
[dash.mailsocket.app/docs/](https://dash.mailsocket.app/docs/)

## MCP config

Point any MCP-compatible client (Claude Desktop, Cursor, Claude Code) at the
`mailsocket-mcp` server over stdio:

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

See [mcp/README.md](mcp/README.md) for per-client config file locations and
the full tool list.

## Examples

[examples/playwright/](examples/playwright/) — a reference Playwright test
that fills a signup form with a mailsocket inbox address and blocks on the
wait endpoint until the OTP arrives.

## License

MIT — see [LICENSE](LICENSE).

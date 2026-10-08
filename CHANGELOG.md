# Changelog

All notable changes to the packages in this repo (`mailsocket` on PyPI,
`mailsocket-mcp` on PyPI, `mailsocket-sdk` on npm). Each package is versioned
independently; see the per-package sections below.

## mailsocket (PyPI, Python SDK)

### 0.3.0
- New `Client.send_test_code(inbox_id)`: puts one sample OTP email (a random
  6-digit code) straight into one of your inboxes, without going through the
  mail server. Limits: 5 per inbox and 20 per account per hour (429 with
  `retry_after`).
- README samples take `started = time.time()` before triggering the email and
  pass `since=started`, so a code that arrives before the wait starts is not
  missed.

### 0.2.0
- **Behaviour change:** `wait_for_otp`, `wait_for_link` and `wait` now default
  `since` to "omitted", so the server matches only mail that arrives after the
  call starts. Before, the default was `since=0`, which could return an older
  code already sitting in a reused inbox. Pass `since=0` to keep the old
  behaviour.
- Ships `py.typed`; `WaitResult` is a frozen dataclass.

### 0.1.3
- `_seg` now rejects an empty id or a bare `.`/`..` id with a
  `MailsocketError` (`code="invalid_id"`) before any request is made,
  matching the TypeScript SDK's contract.

### 0.1.2
- Internal polish release accompanying the Remote MCP phase 1 launch; no
  documented client-facing API change.

### 0.1.1
- Initial public release: synchronous `Client` (pure stdlib, `urllib`),
  `create_inbox` / `list_inboxes` / `get_inbox` / `delete_inbox` /
  `list_messages` / `get_latest` / `get_message`, and the `wait_for_otp` /
  `wait_for_link` / `wait` long-poll helpers returning a `WaitResult`.

### 0.1.0
- First publish.

## mailsocket-mcp (PyPI, MCP server)

### 0.4.0
- New tool `send_test_code` (stdio and hosted). Requires `mailsocket>=0.3.0`.
- 429 messages no longer end with a double period.

### 0.3.0
- Requires `mailsocket>=0.2.0`: `wait_for_otp` / `wait_for_link` match only
  mail that arrives after the call unless you pass `since`.
- Explicit `since=0` is passed through unchanged.


### 0.2.3
- `wait_for_otp` / `wait_for_link` accept an optional `since` (ISO8601, unix
  seconds or a message id) so a reused inbox returns the NEW code; results
  include the message `id` and `received_at`.

### 0.2.2
- Depends on `mailsocket>=0.1.3` (stricter `_seg` id validation in the
  underlying Python SDK).

### 0.2.1
- Access-log path redaction for `/mcp/...` routes.

### 0.2.0
- Remote MCP server (`mailsocket-mcp-http`) added alongside the existing
  local stdio server, exposing the same tools over Streamable HTTP at
  `https://mcp.mailsocket.app/mcp`.

### 0.1.1
- Initial public release: local stdio MCP server exposing `create_inbox`,
  `wait_for_otp`, `wait_for_link`, `list_inboxes`, `list_messages`,
  `get_latest`, `delete_inbox` as MCP tools, wrapping the Python SDK.

## mailsocket-sdk (npm, TypeScript SDK)

### 0.3.0
- New `client.sendTestCode(inboxId)` (ESM + CommonJS).
- README samples take `const started = Date.now() / 1000` before triggering the
  email and pass `{ since: started }`.

### 0.2.0
- **Behaviour change:** `since` is omitted by default (server uses the request
  start). Pass `since: 0` to include messages already in the inbox.


### 0.1.3
- Added a CommonJS build (`dist/cjs`) alongside ESM, so
  `require("mailsocket-sdk")` works. `instanceof` checks on the error
  classes work across the two builds, even when an app loads the package
  via both `import` and `require()`.

### 0.1.2
- Encodes ids in request paths and rejects `""` / `"."` / `".."` ids before
  any network call, matching the Python SDK's `_seg` contract.

### 0.1.1
- Integer `AbortSignal.timeout()` values (fractional ms previously threw
  `ERR_OUT_OF_RANGE`).

### 0.1.0
- Initial public release: `MailsocketClient` (zero runtime dependencies,
  global `fetch`, Node 18+, ESM), mirroring the Python SDK's surface
  (`createInbox`, `listInboxes`, `getInbox`, `deleteInbox`, `listMessages`,
  `getLatest`, `getMessage`, `waitForOtp`, `waitForLink`, `wait`).

---

Earlier 0.1.0/0.1.1-era entries above are reconstructed from release notes
in `docs/OPEN-WORK.md` and this repo's own per-package README "Changelog"
sections (which only documented each package's latest release at the time);
treat anything not already called out in a package's own `README.md` as
best-effort, not authoritative.

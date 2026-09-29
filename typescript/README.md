# mailsocket — TypeScript SDK

The official TypeScript client for the [mailsocket](https://mailsocket.app) v1 REST API.
Ephemeral email inboxes, message retrieval, and — the whole point — **wait for the OTP in one line**.

```ts
import { MailsocketClient } from "mailsocket-sdk";

const client = new MailsocketClient("ms_live_..."); // your API key from the dashboard
const inbox = await client.createInbox("signup");   // { id: "inbox_...", address: "..." }

// hand inbox.address to whatever form sends the code, then:
const { otp, confidence } = await client.waitForOtp(inbox.id); // waits up to 60s
console.log(otp);         // "123456"
console.log(confidence);  // 0.95
```

No polling loop. No regex over the email body. `waitForOtp` long-polls the server
(which already knows how to extract the code) and hands back a deterministic
result with a confidence score.

## Install

```bash
npm install mailsocket-sdk
```

Zero runtime dependencies — uses the global `fetch`. Node 18+, ESM. Ships TypeScript types.

## API

```ts
const client = new MailsocketClient(apiKey, { baseUrl: "https://dash.mailsocket.app/api/v1" });
```

| Method | Returns |
| --- | --- |
| `createInbox(label?)` | `Promise<Inbox>` |
| `listInboxes(limit?, cursor?)` | `Promise<Page<Inbox>>` — `.data` + `.nextCursor` / `.hasMore` |
| `getInbox(inboxId)` | `Promise<InboxDetail>` |
| `deleteInbox(inboxId)` | `Promise<void>` |
| `listMessages(inboxId, { hasOtp?, subjectContains?, sender?, ... })` | `Promise<Page<MessageSummary>>` — `sender` maps to the API's `from` filter |
| `getLatest(inboxId)` | `Promise<Message>` |
| `getMessage(messageId)` | `Promise<Message>` |

### The moat

```ts
const otpResult = await client.waitForOtp("inbox_abc123", { timeout: 60_000, minConfidence: 0, since: 0 });
const linkResult = await client.waitForLink("inbox_abc123", { timeout: 60_000, since: 0 });
const eitherResult = await client.wait("inbox_abc123", { timeout: 60_000, minConfidence: 0, since: 0 }); // otp OR link
```

All three return a `Promise<WaitResult>`. The options object shown above is
optional and its fields are the defaults — call with no second argument for
the common case.

| Method | Options (all optional) | Returns |
| --- | --- | --- |
| `waitForOtp(inboxId, options?)` | `timeout: 60000`, `minConfidence: 0`, `since: 0` | `Promise<WaitResult>` |
| `waitForLink(inboxId, options?)` | `timeout: 60000`, `since: 0` | `Promise<WaitResult>` |
| `wait(inboxId, options?)` | `timeout: 60000`, `minConfidence: 0`, `since: 0` | `Promise<WaitResult>` (otp OR link) |

`WaitResult` exposes `.otp`, `.confidence`, `.magicLink` (and `.link` as an alias),
plus the full `.message`. Semantics:

- Each HTTP call blocks server-side for up to 25s (`timeout` is clamped to `[1, 25]`);
  the SDK re-calls until the **overall** `timeout` (milliseconds, default 60 000) elapses.
- `200` → the matching message. `204` → nothing yet, re-call immediately.
- `429` → honours `Retry-After` and retries within the deadline. `404` → throws.
- On overall deadline → `WaitTimeout`.

## Errors

`MailsocketError` (base) with subclasses:

- `AuthError` — HTTP 401.
- `NotFound` — HTTP 404.
- `RateLimited` — HTTP 429, carries `.subcode` (`rate_limited`, `too_many_wait_requests`, `wait_capacity`) and `.retryAfter` (seconds).
- `WaitTimeout` — no matching message within the overall deadline.

## Develop

```bash
npm install
npm run build     # tsc -> dist/
npm test          # node:test against the built dist (mock fetch, no network)
```

Tests are fully offline — they install a scripted `fetch` mock, so nothing touches the live API.

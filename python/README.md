# mailsocket — Python SDK

The official Python client for the [mailsocket](https://mailsocket.app) v1 REST API.
Ephemeral email inboxes, message retrieval, and — the whole point — **wait for the OTP in one line**.

```python
from mailsocket import Client

client = Client("ms_live_...")            # your API key from the dashboard
inbox = client.create_inbox(label="signup")  # -> {"id": "inbox_...", "address": "..."}

# hand inbox["address"] to whatever form sends the code, then:
result = client.wait_for_otp(inbox["id"])     # blocks up to 60s
print(result.otp)         # "123456"
print(result.confidence)  # 0.95
```

No polling loop. No regex over the email body. `wait_for_otp` long-polls the
server (which already knows how to extract the code) and hands back a
deterministic result with a confidence score.

## Install

```bash
pip install mailsocket
```

Zero runtime dependencies — pure standard library (`urllib`). Python 3.9+.

## API

```python
client = Client(api_key, base_url="https://dash.mailsocket.app/api/v1")
```

| Method | Returns |
| --- | --- |
| `create_inbox(label=None)` | `dict` — the inbox (`id`, `address`, ...) |
| `list_inboxes(limit=None, cursor=None)` | `Page` — `.data` list + `.next_cursor` / `.has_more` |
| `get_inbox(inbox_id)` | `dict` — inbox plus `message_count_month`, `webhook_configured` |
| `delete_inbox(inbox_id)` | `None` |
| `list_messages(inbox_id, has_otp=None, subject_contains=None, sender=None, ...)` | `Page` — `sender` maps to the API's `from` filter |
| `get_latest(inbox_id)` | `dict` — newest message |
| `get_message(message_id)` | `dict` — full message |

### The moat

```python
result = client.wait_for_otp("inbox_abc123", timeout=60, min_confidence=0.0, since=0)
result = client.wait_for_link("inbox_abc123", timeout=60, since=0)
result = client.wait("inbox_abc123", timeout=60, min_confidence=0.0, since=0)  # otp OR link
```

All three return a `WaitResult` and take keyword-only arguments after
`inbox_id`. `timeout`/`min_confidence`/`since` shown above are the defaults —
call with no extra arguments for the common case.

| Method | Keyword args (all optional, keyword-only) | Returns |
| --- | --- | --- |
| `wait_for_otp(inbox_id, ...)` | `timeout=60`, `min_confidence=0.0`, `since=0` | `WaitResult` |
| `wait_for_link(inbox_id, ...)` | `timeout=60`, `since=0` | `WaitResult` |
| `wait(inbox_id, ...)` | `timeout=60`, `min_confidence=0.0`, `since=0` | `WaitResult` (otp OR link) |

`WaitResult` exposes `.otp`, `.confidence`, `.magic_link` (and `.link` as an
alias), plus the full `.message` dict. `str(result)` is the OTP (or the link).

Semantics:

- Each HTTP call blocks server-side for up to 25s (`timeout` is clamped to
  `[1, 25]`); the SDK re-calls until the **overall** `timeout` (seconds,
  default 60) elapses.
- `200` → the matching message. `204` → nothing yet, re-call immediately.
- `429` → honours `Retry-After` and retries within the deadline. `404` → raises.
- On overall deadline → `WaitTimeout`.

## Errors

`MailsocketError` (base) with subclasses:

- `AuthError` — HTTP 401 (bad/missing key).
- `NotFound` — HTTP 404.
- `RateLimited` — HTTP 429, carries `.subcode` (`rate_limited`,
  `too_many_wait_requests`, `wait_capacity`) and `.retry_after`.
- `WaitTimeout` — no matching message within the overall deadline.

## Develop

```bash
cd python
python -m pytest -q
```

Tests make no external or live-API requests. Most monkeypatch
`urllib.request.urlopen` with a scripted responder, and a few start a real local
`http.server` on `127.0.0.1` to check actual request behaviour, e.g. that an
invalid id never reaches the network.

## Changelog

- **0.1.3** — `_seg` now rejects an empty id or a bare `.`/`..` id with a `MailsocketError` (`code="invalid_id"`) before any request is made, matching the TypeScript SDK's contract.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  MailsocketClient,
  MailsocketError,
  AuthError,
  NotFound,
  RateLimited,
  WaitTimeout,
} from "../dist/index.js";

const BASE = "https://example.test/api/v1";
const API_KEY = "ms_live_test1234567890";

const OTP_MESSAGE = {
  id: "msg_123",
  inbox_id: "inbox_abc",
  from: "Acme <no-reply@acme.test>",
  to: ["user@in.inboxpipe.net"],
  cc: [],
  subject: "Your code",
  received_at: "2026-09-23T12:00:00Z",
  status: "parsed",
  otp: "123456",
  otp_confidence: 0.95,
  magic_link: null,
  links: [],
  detected_otp: "123456",
  envelope_from: "no-reply@acme.test",
  envelope_recipient: "user@in.inboxpipe.net",
  text: "Code: 123456",
  html: "<p>Code: 123456</p>",
};

const LINK_MESSAGE = {
  ...OTP_MESSAGE,
  id: "msg_456",
  otp: null,
  otp_confidence: null,
  magic_link: "https://example.test/go?token=abc",
  links: ["https://example.test/go?token=abc"],
};

/** Install a scripted fetch; returns the recorded (url, init) calls. */
function installFetch(responses) {
  const calls = [];
  const queue = responses.map((r) => ({ ...r }));
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    const next = queue.shift();
    if (!next) throw new Error("mock fetch: no more scripted responses");
    return {
      status: next.status,
      headers: new Headers(next.headers ?? {}),
      text: async () => next.body ?? "",
    };
  };
  return calls;
}

function client(overrides = {}) {
  return new MailsocketClient(API_KEY, { baseUrl: BASE, requestTimeoutMs: 0, ...overrides });
}

test("waitForOtp resolves with otp on first 200", async () => {
  const calls = installFetch([{ status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) }]);

  const result = await client().waitForOtp("inbox_abc");

  assert.equal(result.otp, "123456");
  assert.equal(result.confidence, 0.95);
  assert.equal(result.message.id, "msg_123");
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.includes("/messages/wait"));
  assert.ok(calls[0].url.includes("require=otp"));
});

test("waitForOtp defaults since=0 when omitted (parity with Python; catches a pre-existing OTP)", async () => {
  const calls = installFetch([{ status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) }]);

  await client().waitForOtp("inbox_abc");

  assert.equal(new URL(calls[0].url).searchParams.get("since"), "0");
});

test("waitForOtp forwards an explicit since instead of the default", async () => {
  const calls = installFetch([{ status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) }]);

  await client().waitForOtp("inbox_abc", { since: "msg_999" });

  assert.equal(new URL(calls[0].url).searchParams.get("since"), "msg_999");
});

test("waitForOtp keeps polling through 204s then returns", async () => {
  const calls = installFetch([
    { status: 204 },
    { status: 204 },
    { status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) },
  ]);

  const result = await client().waitForOtp("inbox_abc", { timeout: 60_000 });

  assert.equal(result.otp, "123456");
  assert.equal(calls.length, 3);
  for (const { url } of calls) {
    assert.ok(url.includes("timeout="));
    assert.ok(url.includes("require=otp"));
  }
});

test("waitForOtp respects overall timeout -> WaitTimeout", async () => {
  // A 204 means "the server blocked for `timeout` ms and found nothing".
  // Model that with an injectable clock: each 204 advances time by the
  // server-side timeout requested, so the overall client deadline (60s) is
  // eventually exhausted across multiple 25s-clamped calls.
  let now = 0;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    const timeout = Number(new URL(String(url)).searchParams.get("timeout"));
    now += timeout * 1000; // the server blocked this long
    return { status: 204, headers: new Headers({}), text: async () => "" };
  };

  await assert.rejects(
    client({ now: () => now }).waitForOtp("inbox_abc", { timeout: 60_000 }),
    WaitTimeout,
  );

  assert.ok(calls.length >= 3);
  // Server-side timeout stayed clamped to <= 25s on every call.
  for (const { url } of calls) {
    const timeout = Number(new URL(url).searchParams.get("timeout"));
    assert.ok(timeout <= 25, `timeout ${timeout} not clamped`);
  }
});

test("waitForOtp retries on 429 and returns otp", async () => {
  const calls = installFetch([
    {
      status: 429,
      headers: { "Retry-After": "0" },
      body: JSON.stringify({
        error: { code: "too_many_wait_requests", message: "Too many", fields: {} },
      }),
    },
    { status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) },
  ]);

  const result = await client().waitForOtp("inbox_abc", { timeout: 60_000 });

  assert.equal(result.otp, "123456");
  assert.equal(calls.length, 2);
});

test("429 on a non-wait endpoint raises RateLimited with subcode", async () => {
  installFetch([
    {
      status: 429,
      headers: { "Retry-After": "7" },
      body: JSON.stringify({
        error: { code: "rate_limited", message: "Rate limit exceeded.", fields: {} },
      }),
    },
  ]);

  await assert.rejects(client().listInboxes(), (err) => {
    assert.ok(err instanceof RateLimited);
    assert.equal(err.subcode, "rate_limited");
    assert.equal(err.retryAfter, 7);
    assert.equal(err.status, 429);
    return true;
  });
});

test("401 raises AuthError", async () => {
  installFetch([
    { status: 401, body: JSON.stringify({ error: { code: "authentication_required", message: "Auth required.", fields: {} } }) },
  ]);

  await assert.rejects(client().listInboxes(), AuthError);
});

test("404 raises NotFound", async () => {
  installFetch([
    { status: 404, body: JSON.stringify({ error: { code: "not_found", message: "Resource not found.", fields: {} } }) },
  ]);

  await assert.rejects(client().getInbox("inbox_missing"), NotFound);
});

test("waitForOtp 404 raises NotFound immediately", async () => {
  installFetch([
    { status: 404, body: JSON.stringify({ error: { code: "not_found", message: "Resource not found.", fields: {} } }) },
  ]);

  await assert.rejects(client().waitForOtp("inbox_missing", { timeout: 60_000 }), NotFound);
});

test("listMessages maps sender -> from filter and hasOtp", async () => {
  const calls = installFetch([
    {
      status: 200,
      body: JSON.stringify({ data: [OTP_MESSAGE], pagination: { next_cursor: null, has_more: false } }),
    },
  ]);

  const page = await client().listMessages("inbox_abc", {
    hasOtp: true,
    subjectContains: "code",
    sender: "acme.test",
  });

  assert.equal(page.hasMore, false);
  assert.equal(page.nextCursor, null);
  assert.equal(page.data.length, 1);
  assert.equal(page.data[0].id, "msg_123");

  const url = calls[0].url;
  assert.ok(url.includes("has_otp=true"));
  assert.ok(url.includes("subject_contains=code"));
  assert.ok(url.includes("from=acme.test")); // sender mapped to the API's `from`
});

test("from JSON key is preserved on message payloads", async () => {
  installFetch([{ status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) }]);

  const msg = await client().getMessage("msg_123");

  assert.equal(msg.from, "Acme <no-reply@acme.test>");
});

test("waitForLink returns link and require=link", async () => {
  const calls = installFetch([{ status: 200, body: JSON.stringify({ data: LINK_MESSAGE }) }]);

  const result = await client().waitForLink("inbox_abc");

  assert.equal(result.link, "https://example.test/go?token=abc");
  assert.equal(result.magicLink, result.link);
  assert.equal(result.otp, null);
  assert.ok(calls[0].url.includes("require=link"));
});

test("wait returns otp with require=any", async () => {
  const calls = installFetch([{ status: 200, body: JSON.stringify({ data: OTP_MESSAGE }) }]);

  const result = await client().wait("inbox_abc");

  assert.equal(result.otp, "123456");
  assert.ok(calls[0].url.includes("require=any"));
});

test("createInbox posts label and parses data", async () => {
  const inbox = {
    id: "inbox_new",
    label: "signup",
    address: "x@in.inboxpipe.net",
    is_enabled: true,
    created_at: "2026-09-23T12:00:00Z",
    updated_at: "2026-09-23T12:00:00Z",
  };
  const calls = installFetch([{ status: 201, body: JSON.stringify({ data: inbox }) }]);

  const result = await client().createInbox("signup");

  assert.equal(result.id, "inbox_new");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(JSON.parse(calls[0].init.body).label, "signup");
});

test("error classes inherit MailsocketError", () => {
  assert.ok(AuthError.prototype instanceof MailsocketError);
  assert.ok(NotFound.prototype instanceof MailsocketError);
  assert.ok(RateLimited.prototype instanceof MailsocketError);
  assert.ok(WaitTimeout.prototype instanceof MailsocketError);
});


test("network failure / socket abort is wrapped as MailsocketError (ocr HIGH)", async () => {
  // fetch rejecting (DNS/connection error, or AbortSignal.timeout firing) must
  // surface as a clean MailsocketError, never a raw DOMException/TypeError.
  globalThis.fetch = async () => {
    const e = new Error("The operation was aborted due to timeout");
    e.name = "TimeoutError";
    throw e;
  };
  await assert.rejects(
    client().getLatest("inbox_abc"),
    (err) => {
      assert.ok(err instanceof MailsocketError, "must be MailsocketError");
      assert.equal(err.code, "network_error");
      assert.match(err.message, /Network error/);
      assert.doesNotMatch(err.message, /\[object/);
      return true;
    },
  );
});

test("metadata consistency: 0.1.1 matches package.json/package-lock/USER_AGENT", async () => {
  const { readFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const path = await import("node:path");

  const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
  const expected = "0.1.1";

  const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
  assert.equal(pkg.version, expected);

  const lock = JSON.parse(readFileSync(path.join(root, "package-lock.json"), "utf8"));
  assert.equal(lock.version, expected);
  assert.equal(lock.packages[""].version, expected);

  const clientSrc = readFileSync(path.join(root, "src", "client.ts"), "utf8");
  assert.match(clientSrc, new RegExp(`mailsocket-typescript/${expected}`));
});

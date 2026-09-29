/**
 * Typed errors raised by the mailsocket TypeScript SDK.
 */

/** Base class for every error the SDK raises. */
export class MailsocketError extends Error {
  /** The server's error code (e.g. `not_found`, `rate_limited`). */
  readonly code?: string;
  /** The HTTP status code, when one triggered the error. */
  readonly status?: number;

  constructor(message: string, opts?: { code?: string; status?: number }) {
    super(message);
    this.name = new.target.name;
    this.code = opts?.code;
    this.status = opts?.status;
  }
}

/** The API key is missing or invalid (HTTP 401). */
export class AuthError extends MailsocketError {}

/** The requested resource does not exist or is not owned (HTTP 404). */
export class NotFound extends MailsocketError {}

/**
 * A rate limit was hit (HTTP 429).
 *
 * Carries `subcode` (the server error code: `rate_limited`,
 * `too_many_wait_requests` or `wait_capacity`) and `retryAfter` (seconds to
 * wait, from the `Retry-After` header, or `null`).
 */
export class RateLimited extends MailsocketError {
  readonly subcode?: string;
  /** Seconds to wait before retrying, from the `Retry-After` header. */
  readonly retryAfter?: number;

  constructor(
    message: string,
    opts?: { code?: string; subcode?: string; retryAfter?: number },
  ) {
    super(message, { code: opts?.code, status: 429 });
    this.subcode = opts?.subcode;
    this.retryAfter = opts?.retryAfter;
  }
}

/** No matching message arrived before the overall wait deadline. */
export class WaitTimeout extends MailsocketError {}

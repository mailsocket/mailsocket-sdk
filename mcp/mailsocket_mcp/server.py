"""mailsocket MCP server.

Wraps the official :mod:`mailsocket` Python SDK as MCP tools so an
AI coding agent can create a throwaway inbox and *block* on the OTP / magic
link without writing any polling code.

The server speaks MCP over stdio (JSON-RPC). It reads ``MAILSOCKET_API_KEY``
(and optional ``MAILSOCKET_BASE_URL``) from the environment; the key is never
logged and never echoed back in a tool error.
"""

from __future__ import annotations

import functools
import os
import re
from typing import Any, Callable
from urllib.parse import quote

import mcp.types as types
from mcp.server.mcpserver import MCPServer

from mailsocket import AuthError, Client, MailsocketError, NotFound, RateLimited, WaitTimeout

__all__ = ["server", "main", "MAX_WAIT_TIMEOUT", "MISSING_KEY_MESSAGE", "__version__"]

# Canonical version, re-exported as ``mailsocket_mcp.__version__`` (see
# __init__.py). Defined here, not in __init__.py, because __init__.py imports
# this module at package-load time and a circular self-import would break.
__version__ = "0.1.1"

# The headline wait is bounded: an agent can request up to 120s as the
# overall deadline (clamped), though transport overhead can push the actual
# call slightly past that.
DEFAULT_WAIT_TIMEOUT = 60.0
MAX_WAIT_TIMEOUT = 120.0
MIN_WAIT_TIMEOUT = 1.0

MISSING_KEY_MESSAGE = (
    "MAILSOCKET_API_KEY is not set. Export it before starting the server, e.g. "
    "`MAILSOCKET_API_KEY=ms_live_... mailsocket-mcp`."
)

server = MCPServer(
    name="mailsocket",
    title="mailsocket MCP server",
    description=(
        "Ephemeral email inboxes for AI agents: create an inbox, hand the "
        "address to any signup form, then block on the OTP or magic link."
    ),
    version=__version__,
)


# -- client construction -----------------------------------------------------


class _State:
    client: Client | None = None


def _build_client_from_env() -> Client:
    """Build an SDK client from the environment, failing clearly without a key."""
    api_key = os.environ.get("MAILSOCKET_API_KEY", "")
    if not api_key:
        raise RuntimeError(MISSING_KEY_MESSAGE)
    base_url = os.environ.get("MAILSOCKET_BASE_URL") or None
    if base_url:
        return Client(api_key, base_url=base_url)
    return Client(api_key)


def _get_client() -> Client:
    if _State.client is None:
        _State.client = _build_client_from_env()
    return _State.client


# -- error handling ----------------------------------------------------------


def _safe(text: str) -> str:
    """Redact the API key from any text so it can never leak into a tool error.

    Defense in depth against reformatted keys: redact the literal key, its
    URL-encoded form, AND any token sharing the ``ms_live_`` credential prefix,
    so an SDK/network error that url-encodes, wraps, or splits the key around
    still cannot surface a usable secret to the agent.
    """
    key = os.environ.get("MAILSOCKET_API_KEY", "")
    if key:
        text = text.replace(key, "***")
        encoded = quote(key, safe="")
        if encoded != key:
            text = text.replace(encoded, "***")
    # Belt and braces: scrub anything that looks like a live key, even if the
    # env value was reformatted beyond a literal/url-encoded match.
    text = re.sub(r"ms_live_[A-Za-z0-9_\-]{4,}", "***", text)
    return text.strip()


def _error_result(exc: BaseException) -> types.CallToolResult:
    """Turn an SDK exception into a clean MCP tool error (no traceback, no key)."""
    if isinstance(exc, AuthError):
        msg = "Authentication failed (HTTP 401): the API key was rejected. Check MAILSOCKET_API_KEY."
    elif isinstance(exc, WaitTimeout):
        msg = f"Timed out waiting for a matching message: {_safe(str(exc))}"
    elif isinstance(exc, NotFound):
        msg = f"Not found (HTTP 404): {_safe(str(exc))}"
    elif isinstance(exc, RateLimited):
        retry = f" Retry after {exc.retry_after:g}s." if exc.retry_after else ""
        msg = f"Rate limited (HTTP 429): {_safe(str(exc))}.{retry}"
    elif isinstance(exc, MailsocketError):
        msg = _safe(str(exc)) or exc.__class__.__name__
    else:
        msg = _safe(str(exc)) or exc.__class__.__name__
    return types.CallToolResult(
        is_error=True,
        content=[types.TextContent(type="text", text=msg)],
    )


def _guarded(fn: Callable) -> Callable:
    """Wrap a tool so SDK errors become clean MCP tool errors."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — any tool error must be scrubbed
            # Route EVERY exception (incl. unexpected KeyError/TypeError/ValueError)
            # through _error_result so the key is scrubbed and no raw traceback
            # ever reaches the agent. _error_result handles known SDK types
            # specially and falls back to a class-name-only message otherwise.
            return _error_result(exc)

    return wrapper


def _clamp_timeout(timeout: float) -> float:
    return max(MIN_WAIT_TIMEOUT, min(float(timeout), MAX_WAIT_TIMEOUT))


def _ctx(result, include: tuple[str, ...]) -> dict:
    """Pick subject/from context off a ``WaitResult`` message."""
    message = getattr(result, "message", None) or {}
    ctx: dict = {}
    for field in include:
        ctx[field] = message.get(field)
    return ctx


# -- tools -------------------------------------------------------------------


@server.tool(
    annotations=types.ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
@_guarded
def create_inbox(label: str | None = None) -> dict:
    """Create a new throwaway inbox and return its id and email address.

    Use this first, before any signup flow you want to automate. Hand the
    returned ``address`` to whatever form sends the verification email, then
    call ``wait_for_otp`` (or ``wait_for_link``) with the returned ``id`` to
    block until the code/link arrives — no polling loop needed.

    Side effects: creates a new inbox resource against the live mailsocket
    account tied to ``MAILSOCKET_API_KEY`` (counts against the account's
    inbox quota). Makes one network call to the mailsocket API
    (``openWorldHint``).
    """
    inbox = _get_client().create_inbox(label=label)
    return {"id": inbox.get("id"), "address": inbox.get("address")}


@server.tool(
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@_guarded
def wait_for_otp(
    inbox_id: str,
    timeout: float = DEFAULT_WAIT_TIMEOUT,
    min_confidence: float = 0.0,
) -> dict:
    """Block (bounded) until an OTP arrives in ``inbox_id`` and return it.

    This is the headline tool: use it right after triggering a signup/login
    email so you never have to write a polling loop or regex over an email
    body. Call it with the ``id`` returned by ``create_inbox``.

    ``timeout`` is requested in seconds but always clamped to [1, 120]: this
    is the requested overall wait deadline the SDK aims for, not a hard
    wall-clock ceiling on the call — the underlying HTTP transport adds a
    small amount of socket-level overhead on top of the clamped deadline
    (see the Python SDK's `WAIT_SOCKET_BUFFER`), so the call can return
    slightly after 120s in practice. ``min_confidence`` filters out
    low-confidence OTP extractions.

    Side effects: none beyond the long-poll HTTP call(s) needed to satisfy the
    wait (``openWorldHint`` — it talks to the live mailsocket API and blocks
    for up to ``timeout`` seconds). Returns the OTP string, a confidence
    score, and the subject/from of the matching message. Raises a clean tool
    error (``WaitTimeout``) if nothing matching arrives before the deadline.
    """
    result = _get_client().wait_for_otp(
        inbox_id,
        timeout=_clamp_timeout(timeout),
        min_confidence=min_confidence,
    )
    return {
        "otp": result.otp,
        "confidence": result.confidence,
        **_ctx(result, ("subject", "from")),
    }


@server.tool(
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@_guarded
def wait_for_link(
    inbox_id: str,
    timeout: float = DEFAULT_WAIT_TIMEOUT,
) -> dict:
    """Block (bounded) until a magic link arrives in ``inbox_id`` and return it.

    Use this instead of ``wait_for_otp`` when the target flow emails a
    clickable magic link rather than a numeric/alphanumeric code. The link is
    returned as text, NOT followed by this tool — fetch it yourself (e.g. via
    a headless browser or ``curl``) however your task needs.

    ``timeout`` is requested in seconds but always clamped to [1, 120]: this
    is the requested overall wait deadline the SDK aims for, not a hard
    wall-clock ceiling — the underlying HTTP transport adds a small amount of
    socket-level overhead on top of the clamped deadline, so the call can
    return slightly after 120s in practice.

    Side effects: none beyond the long-poll HTTP call(s) needed to satisfy the
    wait (``openWorldHint`` — it talks to the live mailsocket API and blocks
    for up to ``timeout`` seconds). Raises a clean tool error (``WaitTimeout``)
    if no link arrives before the deadline.
    """
    result = _get_client().wait_for_link(inbox_id, timeout=_clamp_timeout(timeout))
    return {
        "magic_link": result.magic_link,
        **_ctx(result, ("subject", "from")),
    }


@server.tool(
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@_guarded
def list_inboxes(limit: int | None = None, cursor: str | None = None) -> dict:
    """List inboxes owned by the API key, one page at a time.

    Use this to see what inboxes already exist (e.g. to reuse one instead of
    creating a new one, or to find an ``id`` to pass to the other tools) — it
    never creates, modifies or deletes anything. Returns one page (server
    default page size is 25 rows); pass ``cursor`` (from ``next_cursor`` in
    the previous response) to fetch the next page, or ``limit`` (1-100) to
    change the page size. This tool does NOT auto-fetch every page.

    Side effects: none; read-only. Makes one network call to the mailsocket
    API (``openWorldHint``).
    """
    page = _get_client().list_inboxes(limit=limit, cursor=cursor)
    return {
        "inboxes": list(page.data),
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@server.tool(
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@_guarded
def list_messages(
    inbox_id: str,
    has_otp: bool | None = None,
    subject_contains: str | None = None,
    sender: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """List messages in ``inbox_id``, one page at a time, optionally filtered.

    Use this to inspect what has already landed in an inbox without blocking
    — e.g. to debug why ``wait_for_otp``/``wait_for_link`` timed out, or to
    browse message history. Prefer ``wait_for_otp``/``wait_for_link`` when you
    just need to block until the next matching message arrives.

    ``has_otp`` keeps only messages with a detected OTP, ``subject_contains``
    does a case-insensitive substring match on the subject, and ``sender``
    matches the ``from`` address (maps to the API's ``from`` filter). Returns
    one page (server default page size is 25 rows); pass ``cursor`` (from
    ``next_cursor`` in the previous response) to fetch the next page, or
    ``limit`` (1-100) to change the page size. This tool does NOT auto-fetch
    every page.

    Side effects: none; read-only. Makes one network call to the mailsocket
    API (``openWorldHint``).
    """
    page = _get_client().list_messages(
        inbox_id,
        has_otp=has_otp,
        subject_contains=subject_contains,
        sender=sender,
        limit=limit,
        cursor=cursor,
    )
    return {
        "messages": list(page.data),
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@server.tool(
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@_guarded
def get_latest(inbox_id: str) -> dict:
    """Return the newest message in ``inbox_id`` (without blocking).

    Use this when you just want to peek at whatever has already arrived, with
    no waiting — for a blocking wait on the next OTP/link, use
    ``wait_for_otp``/``wait_for_link`` instead.

    Side effects: none; read-only. Makes one network call to the mailsocket
    API (``openWorldHint``).
    """
    return _get_client().get_latest(inbox_id)


@server.tool(
    annotations=types.ToolAnnotations(destructiveHint=True, openWorldHint=True),
)
@_guarded
def delete_inbox(inbox_id: str) -> dict:
    """Delete ``inbox_id`` and everything in it. Use when you are done with it.

    Call this as cleanup once a signup/login flow has finished and you no
    longer need the inbox or its messages — e.g. at the end of an automated
    test run.

    Side effects: DESTRUCTIVE and irreversible — permanently deletes the
    inbox and all of its stored messages (``destructiveHint``). Makes one
    network call to the mailsocket API (``openWorldHint``).
    """
    _get_client().delete_inbox(inbox_id)
    return {"deleted": inbox_id}


# -- entrypoint --------------------------------------------------------------


def main() -> None:
    """Console entry point: fail fast on a missing key, then serve MCP over stdio."""
    import sys

    try:
        _get_client()
    except RuntimeError as exc:  # missing MAILSOCKET_API_KEY
        print(_safe(str(exc)), file=sys.stderr)
        raise SystemExit(2)
    server.run()


if __name__ == "__main__":
    main()

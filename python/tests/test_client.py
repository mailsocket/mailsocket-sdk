"""Offline unit tests for the mailsocket Python SDK (mocked transport, no network)."""

import json

import pytest

import mailsocket
from mailsocket import AuthError, MailsocketError, NotFound, RateLimited, WaitTimeout
from mailsocket.client import Client, WaitResult

OTP_MESSAGE = {
    "id": "msg_123",
    "inbox_id": "inbox_abc",
    "from": "Acme <no-reply@acme.test>",
    "to": ["user@in.inboxpipe.net"],
    "cc": [],
    "subject": "Your code",
    "received_at": "2026-09-23T12:00:00Z",
    "status": "parsed",
    "otp": "123456",
    "otp_confidence": 0.95,
    "magic_link": None,
    "links": [],
    "detected_otp": "123456",
    "envelope_from": "no-reply@acme.test",
    "envelope_recipient": "user@in.inboxpipe.net",
    "text": "Code: 123456",
    "html": "<p>Code: 123456</p>",
}

LINK_MESSAGE = {
    **OTP_MESSAGE,
    "id": "msg_456",
    "otp": None,
    "otp_confidence": None,
    "magic_link": "https://example.test/go?token=abc",
    "links": ["https://example.test/go?token=abc"],
}


class FakeTransport:
    """A scripted urllib transport recorded by the SDK."""

    def __init__(self, responses):
        self.responses = list(responses)  # list of (status, headers, payload)
        self.calls = []  # list of (method, url) in call order

    def __call__(self, request, timeout=None):
        import io
        from urllib.error import HTTPError

        url = request.full_url
        self.calls.append((request.get_method(), url))
        status, headers, payload = self.responses.pop(0)
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""

        class _Resp:
            def __init__(self, status, headers, body):
                self.status = status
                self.headers = headers
                self._body = body

            def getcode(self):
                return self.status

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        if status >= 400:
            raise HTTPError(url, status, "http error", headers, io.BytesIO(body))
        return _Resp(status, headers, body)


def make_client(responses, **kwargs):
    transport = FakeTransport(responses)
    client = Client("ms_live_test1234567890", base_url="https://example.test/api/v1", **kwargs)
    return client, transport


@pytest.fixture
def client_factory(monkeypatch):
    def build(responses, **kwargs):
        client, transport = make_client(responses, **kwargs)
        return client, transport

    return build


def _monkeypatch_transport(monkeypatch, client, transport):
    monkeypatch.setattr("urllib.request.urlopen", transport)


def test_wait_for_otp_returns_on_first_200(monkeypatch):
    client, transport = make_client([(200, {}, {"data": OTP_MESSAGE})])
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.wait_for_otp("inbox_abc", timeout=60)

    assert isinstance(result, WaitResult)
    assert result.otp == "123456"
    assert result.confidence == 0.95
    assert str(result) == "123456"
    assert len(transport.calls) == 1


def test_wait_keeps_polling_through_204s_then_returns(monkeypatch):
    responses = [
        (204, {}, None),
        (204, {}, None),
        (200, {}, {"data": OTP_MESSAGE}),
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.wait_for_otp("inbox_abc", timeout=60)

    assert result.otp == "123456"
    assert len(transport.calls) == 3
    # server-side timeout stays clamped to <= 25s on every call
    for _, url in transport.calls:
        assert "timeout=" in url
        assert "require=otp" in url


def test_wait_respects_overall_timeout_raises_wait_timeout(monkeypatch):
    # A 204 means "the server blocked for `timeout` seconds and found nothing".
    # Model that with a controllable clock: each 204 advances time by the
    # server-side timeout requested, so the overall client deadline (60s) is
    # eventually exhausted across multiple 25s-clamped calls.
    import urllib.parse

    clock = [0.0]
    calls = []

    def fake_open(request, timeout=None):
        url = request.full_url
        calls.append(url)
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        server_timeout = float(qs["timeout"][0])
        clock[0] += server_timeout  # the server blocked this long

        class _Resp:
            def getcode(self):
                return 204

            def read(self):
                return b""

            @property
            def headers(self):
                return {}

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr(mailsocket.client, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(mailsocket.client, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))

    client = Client("ms_live_test1234567890", base_url="https://example.test/api/v1")

    with pytest.raises(WaitTimeout):
        client.wait_for_otp("inbox_abc", timeout=60)

    # Server-side timeout was clamped to 25 on every call but the last.
    requested = [
        float(urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)["timeout"][0]) for u in calls
    ]
    assert all(t <= 25 for t in requested)
    assert requested[-1] <= 25


def test_wait_429_parses_subcode_and_retries(monkeypatch):
    responses = [
        (
            429,
            {"Retry-After": "0"},
            {"error": {"code": "too_many_wait_requests", "message": "Too many", "fields": {}}},
        ),
        (200, {}, {"data": OTP_MESSAGE}),
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.wait_for_otp("inbox_abc", timeout=60)

    assert result.otp == "123456"
    assert len(transport.calls) == 2


def test_wait_429_raises_rate_limited_with_subcode_on_non_wait_endpoint(monkeypatch):
    responses = [
        (
            429,
            {"Retry-After": "7"},
            {"error": {"code": "rate_limited", "message": "Rate limit exceeded.", "fields": {}}},
        ),
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    with pytest.raises(RateLimited) as exc_info:
        client.list_inboxes()

    assert exc_info.value.subcode == "rate_limited"
    assert exc_info.value.retry_after == 7.0
    assert exc_info.value.status == 429


def test_401_raises_auth_error(monkeypatch):
    responses = [
        (401, {}, {"error": {"code": "authentication_required", "message": "Auth required.", "fields": {}}})
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    with pytest.raises(AuthError) as exc_info:
        client.list_inboxes()

    assert exc_info.value.code == "authentication_required"


def test_404_raises_not_found(monkeypatch):
    responses = [
        (404, {}, {"error": {"code": "not_found", "message": "Resource not found.", "fields": {}}})
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    with pytest.raises(NotFound):
        client.get_inbox("inbox_missing")


def test_wait_404_raises_not_found_immediately(monkeypatch):
    responses = [
        (404, {}, {"error": {"code": "not_found", "message": "Resource not found.", "fields": {}}})
    ]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    with pytest.raises(NotFound):
        client.wait_for_otp("inbox_missing", timeout=60)


def test_list_messages_maps_filter_params(monkeypatch):
    responses = [(200, {}, {"data": [OTP_MESSAGE], "pagination": {"next_cursor": None, "has_more": False}})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    page = client.list_messages("inbox_abc", has_otp=True, subject_contains="code", sender="acme.test")

    assert page.has_more is False
    assert page.next_cursor is None
    assert len(page) == 1
    assert page[0]["id"] == "msg_123"

    url = transport.calls[0][1]
    assert "has_otp=true" in url
    assert "subject_contains=code" in url
    assert "from=acme.test" in url  # sender is mapped to the API's `from` param


def test_from_json_key_handled_on_message_dict(monkeypatch):
    responses = [(200, {}, {"data": OTP_MESSAGE})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    msg = client.get_message("msg_123")

    assert msg["from"] == "Acme <no-reply@acme.test>"


def test_wait_for_link_returns_link(monkeypatch):
    responses = [(200, {}, {"data": LINK_MESSAGE})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.wait_for_link("inbox_abc", timeout=60)

    assert result.magic_link == "https://example.test/go?token=abc"
    assert result.link == result.magic_link
    assert result.otp is None
    _, url = transport.calls[0]
    assert "require=link" in url


def test_wait_any_returns_otp_or_link(monkeypatch):
    responses = [(200, {}, {"data": OTP_MESSAGE})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.wait("inbox_abc", timeout=60)

    assert result.otp == "123456"
    _, url = transport.calls[0]
    assert "require=any" in url


def test_create_inbox_sends_label_and_parses_data(monkeypatch):
    inbox = {
        "id": "inbox_new",
        "label": "signup",
        "address": "x@in.inboxpipe.net",
        "is_enabled": True,
        "created_at": "2026-09-23T12:00:00Z",
        "updated_at": "2026-09-23T12:00:00Z",
    }
    responses = [(201, {}, {"data": inbox})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    result = client.create_inbox(label="signup")

    assert result["id"] == "inbox_new"
    method, url = transport.calls[0]
    assert method == "POST"


def test_create_inbox_without_label_sends_empty_body(monkeypatch):
    inbox = {
        "id": "inbox_new",
        "label": "",
        "address": "x@in.inboxpipe.net",
        "is_enabled": True,
        "created_at": "2026-09-23T12:00:00Z",
        "updated_at": "2026-09-23T12:00:00Z",
    }
    responses = [(201, {}, {"data": inbox})]
    client, transport = make_client(responses)
    _monkeypatch_transport(monkeypatch, client, transport)

    client.create_inbox()

    assert len(transport.calls) == 1


def test_error_types_are_mailsocket_subclasses():
    assert issubclass(AuthError, MailsocketError)
    assert issubclass(NotFound, MailsocketError)
    assert issubclass(RateLimited, MailsocketError)
    assert issubclass(WaitTimeout, MailsocketError)


def test_version_exported():
    assert hasattr(mailsocket, "__version__")


def test_metadata_consistency_across_files():
    """0.1.1 must match everywhere: pyproject, __version__, user agent, and MCP sibling."""
    import re
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    expected = "0.1.1"

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == expected
    assert mailsocket.__version__ == expected

    client_src = (root / "mailsocket" / "client.py").read_text()
    match = re.search(r'"mailsocket-python/([^"]+)"', client_src)
    assert match, "User-Agent literal not found in client.py"
    assert match.group(1) == expected

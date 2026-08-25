"""
tests/test_client.py — Unit tests for WahaClient.

Uses pytest-httpx to intercept httpx calls without hitting a real WAHA instance.
All tests are async (pytest-asyncio handles the event loop).
"""

import json
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.client import WahaClient, WahaClientError

# ============================================================
# Helpers
# ============================================================


def make_client(httpx_mock: HTTPXMock) -> WahaClient:
    """
    Create a WahaClient backed by a real httpx.AsyncClient that
    pytest-httpx will intercept automatically.

    We pass the client directly to the constructor (bypassing from_env_sync)
    so tests don't need environment variables.

    Args:
        httpx_mock: The pytest-httpx fixture (intercepts all requests).

    Returns:
        A WahaClient ready for testing.
    """
    # pytest-httpx patches httpx.AsyncClient automatically when fixture is active
    http_client = httpx.AsyncClient()
    return WahaClient(
        base_url="http://waha-test:3000",
        api_key="test-key",
        session_name="test-session",
        http_client=http_client,
    )


# ============================================================
# send_message
# ============================================================


@pytest.mark.asyncio
async def test_send_message_returns_correct_id(httpx_mock: HTTPXMock) -> None:
    """send_message parses the WAHA response and returns the message ID."""
    httpx_mock.add_response(
        method="POST",
        url="http://waha-test:3000/api/sendText",
        json={"id": "msg-abc-123", "timestamp": 1700000000},
    )
    client = make_client(httpx_mock)

    result = await client.send_message(chat_id="628111@c.us", text="Hello, Gilang!")

    assert result.message_id == "msg-abc-123"
    assert result.timestamp == 1700000000


@pytest.mark.asyncio
async def test_send_message_with_reply_to(httpx_mock: HTTPXMock) -> None:
    """send_message includes reply_to in the request body when provided."""
    captured: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "msg-reply", "timestamp": 1700000001})

    httpx_mock.add_callback(capture, method="POST", url="http://waha-test:3000/api/sendText")
    client = make_client(httpx_mock)

    await client.send_message(
        chat_id="628111@c.us",
        text="Replying!",
        reply_to_message_id="original-msg-id",
    )

    body = json.loads(captured[0].content)
    assert body["reply_to"] == "original-msg-id"


@pytest.mark.asyncio
async def test_send_message_raises_on_server_error(httpx_mock: HTTPXMock) -> None:
    """send_message raises WahaClientError on non-2xx responses."""
    httpx_mock.add_response(
        method="POST",
        url="http://waha-test:3000/api/sendText",
        status_code=500,
        text="Internal Server Error",
    )
    client = make_client(httpx_mock)

    with pytest.raises(WahaClientError) as exc_info:
        await client.send_message(chat_id="628111@c.us", text="Hello")

    assert exc_info.value.status_code == 500
    assert "500" in str(exc_info.value)


# ============================================================
# send_media
# ============================================================


@pytest.mark.asyncio
async def test_send_media_returns_correct_id(httpx_mock: HTTPXMock) -> None:
    """send_media parses the WAHA response and returns the message ID."""
    httpx_mock.add_response(
        method="POST",
        url="http://waha-test:3000/api/sendFile",
        json={"id": "media-xyz-456", "timestamp": 1700000002},
    )
    client = make_client(httpx_mock)

    result = await client.send_media(
        chat_id="628222@c.us",
        media_url="https://example.com/invoice.pdf",
        caption="Here's the invoice!",
    )

    assert result.message_id == "media-xyz-456"


@pytest.mark.asyncio
async def test_send_media_without_caption(httpx_mock: HTTPXMock) -> None:
    """send_media omits the caption field when not provided."""
    captured: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "media-no-caption", "timestamp": 1700000003})

    httpx_mock.add_callback(capture, method="POST", url="http://waha-test:3000/api/sendFile")
    client = make_client(httpx_mock)

    await client.send_media(chat_id="628222@c.us", media_url="https://example.com/file.jpg")

    body = json.loads(captured[0].content)
    assert "caption" not in body


# ============================================================
# get_messages
# ============================================================


@pytest.mark.asyncio
async def test_get_messages_parses_text_messages(httpx_mock: HTTPXMock) -> None:
    """get_messages correctly parses text messages from the WAHA history response."""
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"http://waha-test:3000/api/.*messages"),
        json=[
            {"id": "m1", "from": "628111", "body": "Hey!", "timestamp": 1700000010},
            {"id": "m2", "from": "628222", "body": "What's up?", "timestamp": 1700000020},
        ],
    )
    client = make_client(httpx_mock)

    messages = await client.get_messages(chat_id="group-id@g.us", limit=2)

    assert len(messages) == 2
    assert messages[0].message_id == "m1"
    assert messages[0].text == "Hey!"
    assert messages[1].sender_phone == "628222"


@pytest.mark.asyncio
async def test_get_messages_parses_media_messages(httpx_mock: HTTPXMock) -> None:
    """get_messages extracts media_url from the nested media object."""
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"http://waha-test:3000/api/.*messages"),
        json=[
            {
                "id": "m3",
                "from": "628111",
                "body": None,
                "media": {"url": "https://cdn.example.com/photo.jpg"},
                "timestamp": 1700000030,
            }
        ],
    )
    client = make_client(httpx_mock)

    messages = await client.get_messages(chat_id="628111@c.us")

    assert messages[0].media_url == "https://cdn.example.com/photo.jpg"
    assert messages[0].text is None


@pytest.mark.asyncio
async def test_get_messages_returns_empty_list(httpx_mock: HTTPXMock) -> None:
    """get_messages returns an empty list when WAHA returns an empty array."""
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"http://waha-test:3000/api/.*messages"),
        json=[],
    )
    client = make_client(httpx_mock)

    messages = await client.get_messages(chat_id="628111@c.us")

    assert messages == []


# ============================================================
# is_reachable
# ============================================================


@pytest.mark.asyncio
async def test_is_reachable_returns_true_on_success(httpx_mock: HTTPXMock) -> None:
    """is_reachable returns True when WAHA sessions endpoint returns 2xx list."""
    httpx_mock.add_response(
        method="GET",
        url="http://waha-test:3000/api/sessions",
        json=[{"name": "default", "status": "WORKING"}],
    )
    client = make_client(httpx_mock)

    assert await client.is_reachable() is True


@pytest.mark.asyncio
async def test_is_reachable_returns_false_on_server_error(httpx_mock: HTTPXMock) -> None:
    """is_reachable returns False when WAHA sessions endpoint returns 5xx."""
    httpx_mock.add_response(
        method="GET",
        url="http://waha-test:3000/api/sessions",
        status_code=503,
    )
    client = make_client(httpx_mock)

    assert await client.is_reachable() is False


@pytest.mark.asyncio
async def test_is_reachable_returns_false_on_network_error(httpx_mock: HTTPXMock) -> None:
    """is_reachable returns False on network-level errors (host unreachable)."""
    httpx_mock.add_exception(
        httpx.ConnectError("Connection refused"),
        method="GET",
        url="http://waha-test:3000/api/sessions",
    )
    client = make_client(httpx_mock)

    assert await client.is_reachable() is False


@pytest.mark.asyncio
async def test_start_and_stop_typing(httpx_mock: HTTPXMock) -> None:
    """start_typing and stop_typing post to WAHA and return True on 2xx."""
    httpx_mock.add_response(
        method="POST",
        url="http://waha-test:3000/api/startTyping",
        json={"result": True},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="http://waha-test:3000/api/stopTyping",
        json={"result": True},
        status_code=201,
    )
    client = make_client(httpx_mock)

    assert await client.start_typing("12345@c.us") is True
    assert await client.stop_typing("12345@c.us") is True

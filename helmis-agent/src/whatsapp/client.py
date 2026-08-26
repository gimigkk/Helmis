"""
client.py — WAHA HTTP API client.

Single, typed wrapper around all WAHA REST calls.
Every tool in this package calls through this class — no raw HTTP elsewhere.

Two construction patterns:
  - WahaClient.from_env_sync(): for server startup (shared instance, synchronous)
  - WahaClient.from_env(): async context manager for test/one-shot use

Usage (server):
    client = WahaClient.from_env_sync()

Usage (tests / one-shot):
    async with WahaClient.from_env() as client:
        await client.send_message(chat_id, text)
"""

import base64
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from ..models import WahaHistoryMessage, WahaMessageResponse

log = logging.getLogger("helmis-client")


class WahaClientError(Exception):
    """Raised when the WAHA API returns an unexpected error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"WAHA API error {status_code}: {detail}")


def normalize_mime_type(raw_mime: str, url: str = "") -> str:
    """Normalize raw Content-Type and URL extensions to Gemini-supported MIME types."""
    mime = raw_mime.split(";")[0].strip().lower() if raw_mime else ""
    url_lower = url.lower()

    # Video mappings
    if "mp4" in mime or ".mp4" in url_lower or ".m4v" in url_lower:
        return "video/mp4"
    if "quicktime" in mime or "mov" in mime or ".mov" in url_lower:
        return "video/quicktime"
    if "webm" in mime or ".webm" in url_lower:
        return "video/webm"
    if "3gp" in mime or ".3gp" in url_lower or "3gpp" in mime or ".3gpp" in url_lower:
        return "video/3gpp"
    if "avi" in mime or ".avi" in url_lower:
        return "video/avi"
    if "mpeg" in mime or ".mpg" in url_lower or ".mpeg" in url_lower:
        return "video/mpeg"

    # Audio mappings
    if "ogg" in mime or "opus" in mime or ".ogg" in url_lower or ".opus" in url_lower:
        return "audio/ogg"
    if "mp3" in mime or ".mp3" in url_lower:
        return "audio/mp3"
    if "m4a" in mime or ".m4a" in url_lower or "aac" in mime or ".aac" in url_lower:
        return "audio/m4a"
    if "wav" in mime or ".wav" in url_lower:
        return "audio/wav"

    # Image mappings
    if "png" in mime or ".png" in url_lower:
        return "image/png"
    if "webp" in mime or ".webp" in url_lower:
        return "image/webp"
    if "jpeg" in mime or "jpg" in mime or ".jpeg" in url_lower or ".jpg" in url_lower:
        return "image/jpeg"
    if "heic" in mime or ".heic" in url_lower:
        return "image/heic"

    # Document mappings
    if "pdf" in mime or ".pdf" in url_lower:
        return "application/pdf"

    if mime and mime not in ("application/octet-stream", "binary/octet-stream"):
        return mime

    return "image/jpeg"


class WahaClient:
    """
    Async HTTP client for the WAHA REST API.

    All public methods are coroutines — call them with await.
    The underlying httpx.AsyncClient is created lazily on first use
    when constructed via from_env_sync(), allowing the instance to be
    shared safely across async contexts.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        session_name: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session_name = session_name
        self._headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
        # If no client provided, create one lazily (closed by GC / explicit close)
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    # ----------------------------------------------------------
    # Constructors
    # ----------------------------------------------------------

    @classmethod
    def from_env_sync(cls) -> "WahaClient":
        """
        Synchronous factory that reads from environment variables.
        Use this at server startup to create a shared instance.

        Required env vars:
            WAHA_BASE_URL  — e.g. http://waha:3000
            WAHA_API_KEY   — authentication key

        Optional:
            WAHA_SESSION_NAME — defaults to "helmis"

        Returns:
            A WahaClient with a lazily-initialised httpx client.
        """
        base_url = os.environ["WAHA_BASE_URL"]
        api_key = os.environ["WAHA_API_KEY"]
        session_name = os.environ.get("WAHA_SESSION_NAME", "helmis")
        return cls(base_url, api_key, session_name)

    @classmethod
    @asynccontextmanager
    async def from_env(cls) -> AsyncGenerator["WahaClient", None]:
        """
        Async context-manager factory for tests and one-shot scripts.
        Manages the httpx client lifecycle automatically.

        Example:
            async with WahaClient.from_env() as client:
                result = await client.send_message(...)
        """
        base_url = os.environ["WAHA_BASE_URL"]
        api_key = os.environ["WAHA_API_KEY"]
        session_name = os.environ.get("WAHA_SESSION_NAME", "helmis")

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http_client:
            yield cls(base_url, api_key, session_name, http_client)

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build a full WAHA API URL from a relative path."""
        return f"{self._base_url}{path}"

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """
        POST JSON to the WAHA API.

        Args:
            path: Relative API path (e.g. "/api/sendText").
            body: Request body to serialise as JSON.

        Returns:
            Parsed JSON response body.

        Raises:
            WahaClientError: If the response status is not 2xx.
        """
        response = await self._http.post(self._url(path), headers=self._headers, json=body)
        if not response.is_success:
            raise WahaClientError(response.status_code, response.text)
        result: dict[str, Any] = response.json()
        return result

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        GET from the WAHA API.

        Args:
            path: Relative API path.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body (any shape).

        Raises:
            WahaClientError: If the response status is not 2xx.
        """
        response = await self._http.get(self._url(path), headers=self._headers, params=params)
        if not response.is_success:
            raise WahaClientError(response.status_code, response.text)
        return response.json()

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> WahaMessageResponse:
        """
        Send a plain text message to a WhatsApp chat or DM.

        Args:
            chat_id: WhatsApp chat ID.
                     DM format:    "628xxxxxxxxxx@c.us"
                     Group format: "<group-id>@g.us"
            text: Message body text. WhatsApp does not render markdown.
            reply_to_message_id: If set, the reply quotes this message.

        Returns:
            WahaMessageResponse containing the sent message's ID and timestamp.

        Raises:
            WahaClientError: On API errors (4xx/5xx responses).
        """
        body: dict[str, Any] = {
            "session": self._session_name,
            "chatId": chat_id,
            "text": text,
        }
        if reply_to_message_id:
            body["reply_to"] = reply_to_message_id

        data = await self._post("/api/sendText", body)
        msg_id = str(data.get("id", "") if isinstance(data, dict) else data)
        ts = int(data.get("timestamp", 0) if isinstance(data, dict) else 0)
        return WahaMessageResponse(message_id=msg_id, timestamp=ts)

    async def send_media(
        self,
        chat_id: str,
        media_url: str,
        caption: str | None = None,
        reply_to_message_id: str | None = None,
        filename: str | None = None,
        mimetype: str | None = None,
    ) -> WahaMessageResponse:
        """
        Send a media file (image, document, audio, etc.) to a WhatsApp chat.

        Args:
            chat_id: WhatsApp chat ID.
            media_url: Publicly accessible URL or base64 data URI of the media file.
            caption: Optional text displayed below the media.
            reply_to_message_id: If set, the reply quotes this message.
            filename: Optional original filename displayed in WhatsApp document cards.
            mimetype: Optional MIME type of the file.

        Returns:
            WahaMessageResponse containing the sent message's ID and timestamp.

        Raises:
            WahaClientError: On API errors (4xx/5xx responses).
        """
        file_obj: dict[str, Any] = {"url": media_url}
        if filename:
            file_obj["filename"] = filename
        if mimetype:
            file_obj["mimetype"] = mimetype

        body: dict[str, Any] = {
            "session": self._session_name,
            "chatId": chat_id,
            "file": file_obj,
        }
        if caption:
            body["caption"] = caption
        if reply_to_message_id:
            body["reply_to"] = reply_to_message_id

        data = await self._post("/api/sendFile", body)
        msg_id = str(data.get("id", "") if isinstance(data, dict) else data)
        ts = int(data.get("timestamp", 0) if isinstance(data, dict) else 0)
        return WahaMessageResponse(message_id=msg_id, timestamp=ts)

    async def get_messages(
        self,
        chat_id: str,
        limit: int = 20,
    ) -> list[WahaHistoryMessage]:
        """
        Fetch recent message history from a WhatsApp chat.

        Args:
            chat_id: WhatsApp chat ID.
            limit: Number of recent messages to return (1–100).

        Returns:
            List of WahaHistoryMessage, ordered oldest-first.

        Raises:
            WahaClientError: On API errors (4xx/5xx responses).
        """
        try:
            data = await self._get(
                f"/api/{self._session_name}/chats/{chat_id}/messages", params={"limit": limit}
            )
        except Exception:
            data = await self._get(
                "/api/messages",
                params={"session": self._session_name, "chatId": chat_id, "limit": limit},
            )

        if not isinstance(data, list):
            return []

        messages: list[WahaHistoryMessage] = []
        bot_phone = (
            os.environ.get("BOT_PHONE", "")
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
        )
        gilang_phone = (
            os.environ.get("GILANG_PHONE", "")
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
        )
        bunga_phone = (
            os.environ.get("BUNGA_PHONE", "")
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
        )
        gilang_lid = os.environ.get("GILANG_LID", "").replace("@lid", "").strip()
        bunga_lid = os.environ.get("BUNGA_LID", "").replace("@lid", "").strip()

        for msg in data:
            if isinstance(msg, dict):
                body_text = (
                    msg.get("body")
                    or msg.get("caption")
                    or msg.get("_data", {}).get("Message", {}).get("conversation")
                )

                is_from_me = bool(
                    msg.get("fromMe") is True
                    or str(msg.get("id", "")).startswith("true_")
                )

                author_raw = str(
                    msg.get("author")
                    or msg.get("participant")
                    or msg.get("_data", {}).get("author")
                    or msg.get("from")
                    or ""
                )
                clean_author = (
                    author_raw.split("@")[0]
                    .split(":")[0]
                    .replace("+", "")
                    .replace(" ", "")
                    .replace("-", "")
                )
                notify_name = str(
                    msg.get("_data", {}).get("notifyName") or msg.get("notifyName") or ""
                )

                msg_sender: str = "Unknown"
                if is_from_me or (bool(bot_phone) and bot_phone in clean_author):
                    msg_sender = "Helmis"
                elif (
                    (bool(gilang_phone) and gilang_phone in clean_author)
                    or (bool(gilang_lid) and clean_author.startswith(gilang_lid))
                    or "gilang" in notify_name.lower()
                ):
                    msg_sender = "Gilang"
                elif (
                    (bool(bunga_phone) and bunga_phone in clean_author)
                    or (bool(bunga_lid) and clean_author.startswith(bunga_lid))
                    or "bunga" in notify_name.lower()
                ):
                    msg_sender = "Bunga"
                else:
                    if chat_id.endswith("@c.us"):
                        clean_chat = chat_id.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
                        if bool(gilang_phone) and gilang_phone in clean_chat:
                            msg_sender = "Gilang"
                        elif bool(bunga_phone) and bunga_phone in clean_chat:
                            msg_sender = "Bunga"
                        else:
                            msg_sender = "User"
                    else:
                        msg_sender = notify_name or "Participant"

                # Check for quoted messages in history
                quoted_text: str | None = None
                quoted_sender: str | None = None
                reply_to = msg.get("replyTo")
                if isinstance(reply_to, dict):
                    quoted_text = reply_to.get("body") or reply_to.get("caption")
                    q_part = str(reply_to.get("participant") or reply_to.get("from") or "")
                    q_from_me = bool(reply_to.get("fromMe", False))
                    if q_from_me:
                        quoted_sender = "Helmis"
                    elif (bool(gilang_phone) and gilang_phone in q_part) or (bool(gilang_lid) and q_part.startswith(gilang_lid)):
                        quoted_sender = "Gilang"
                    elif (bool(bunga_phone) and bunga_phone in q_part) or (bool(bunga_lid) and q_part.startswith(bunga_lid)):
                        quoted_sender = "Bunga"
                    else:
                        quoted_sender = "Pesan Sebelumnya"
                elif isinstance(msg.get("_data", {}).get("quotedMsg"), dict):
                    q_msg = msg["_data"]["quotedMsg"]
                    quoted_text = q_msg.get("body") or q_msg.get("caption")
                    q_part = str(msg["_data"].get("quotedParticipant") or "")
                    q_from_me = bool(q_msg.get("fromMe", False))
                    if q_from_me:
                        quoted_sender = "Helmis"
                    elif (bool(gilang_phone) and gilang_phone in q_part) or (bool(gilang_lid) and q_part.startswith(gilang_lid)):
                        quoted_sender = "Gilang"
                    elif (bool(bunga_phone) and bunga_phone in q_part) or (bool(bunga_lid) and q_part.startswith(bunga_lid)):
                        quoted_sender = "Bunga"
                    else:
                        quoted_sender = "Pesan Sebelumnya"

                formatted_text = body_text
                if quoted_text and body_text:
                    formatted_text = (
                        f'> [{quoted_sender or "Pesan Sebelumnya"}]: "{quoted_text.strip()}"\n\n{body_text}'
                    )
                elif quoted_text and not body_text:
                    formatted_text = (
                        f'> [{quoted_sender or "Pesan Sebelumnya"}]: "{quoted_text.strip()}"'
                    )

                messages.append(
                    WahaHistoryMessage(
                        message_id=str(msg.get("id", "")),
                        sender_phone=clean_author or str(msg.get("from", "")),
                        text=formatted_text,
                        media_url=msg.get("media", {}).get("url")
                        if isinstance(msg.get("media"), dict)
                        else None,
                        timestamp=int(msg.get("timestamp", 0)),
                        quoted_text=quoted_text,
                        quoted_sender=quoted_sender,
                        sender_name=msg_sender,
                        author=clean_author,
                        from_me=is_from_me,
                    )
                )
        return messages

    async def start_typing(self, chat_id: str) -> bool:
        """
        Send typing presence indicator to a WhatsApp chat.
        Shows 'typing...' in DM or '[Bot] is typing...' in groups.
        """
        body: dict[str, Any] = {
            "session": self._session_name,
            "chatId": chat_id,
        }
        try:
            response = await self._http.post(
                self._url("/api/startTyping"),
                headers=self._headers,
                json=body,
            )
            return response.status_code in (200, 201)
        except Exception:
            return False

    async def stop_typing(self, chat_id: str) -> bool:
        """
        Stop typing presence indicator in a WhatsApp chat.
        """
        body: dict[str, Any] = {
            "session": self._session_name,
            "chatId": chat_id,
        }
        try:
            response = await self._http.post(
                self._url("/api/stopTyping"),
                headers=self._headers,
                json=body,
            )
            return response.status_code in (200, 201)
        except Exception:
            return False

    async def download_media_base64(self, media_url: str) -> tuple[str, str] | None:
        """
        Download media from WAHA and return (mime_type, base64_data).
        Supports audio voice notes (OGG/Opus/MP3/AAC), images, and documents (PDF).
        """
        try:
            target_url = media_url
            if "localhost:3000" in target_url:
                target_url = target_url.replace("http://localhost:3000", self._base_url)

            response = await self._http.get(target_url, headers=self._headers, timeout=15.0)
            if response.status_code == 200:
                raw_mime = response.headers.get("content-type", "").lower()
                mime_type = normalize_mime_type(raw_mime, target_url)
                b64_data = base64.b64encode(response.content).decode("utf-8")
                return mime_type, b64_data
        except Exception as e:
            log.warning("Failed to download media %s: %s", media_url, e)
        return None

    async def is_reachable(self) -> bool:
        """
        Check if the WAHA server is up and responding.
        Supports both WAHA Core and Plus by checking /api/sessions.
        """
        try:
            res = await self._get("/api/sessions")
            return isinstance(res, list)
        except (WahaClientError, httpx.HTTPError, Exception):
            return False

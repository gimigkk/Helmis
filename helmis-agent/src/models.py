"""
models.py — All data shapes for the WAHA MCP server.

Single source of truth for every request/response structure.
All models are Pydantic v2 — validated on construction, typed throughout.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# ============================================================
# Identity
# ============================================================


class Person(StrEnum):
    """Known users of the Helmis system."""

    GILANG = "Gilang"
    BUNGA = "Bunga"
    UNKNOWN = "Unknown"


class ChatContext(StrEnum):
    """Whether the message came from a group chat or a private DM."""

    GROUP = "group"
    DM = "dm"


# ============================================================
# Incoming webhook payload from WAHA
# ============================================================


class IncomingMessage(BaseModel):
    """
    Normalised representation of an inbound WhatsApp message.

    WAHA sends a richer JSON payload; this captures only what
    Hermes needs to process a message intelligently.
    """

    message_id: str = Field(description="Unique WAHA message ID")
    sender_phone: str = Field(description="Sender's phone number (e.g. 628xxxxxxxxxx)")
    sender_name: Person = Field(description="Resolved display name of the sender")
    chat_id: str = Field(description="WhatsApp chat/group ID to reply to")
    chat_context: ChatContext = Field(description="Group chat or private DM")
    text: str | None = Field(default=None, description="Plain text body (if any)")
    media_url: str | None = Field(default=None, description="URL to attached media (if any)")
    media_mime: str | None = Field(default=None, description="MIME type of attached media")
    timestamp: int = Field(description="Unix timestamp of the message")
    quoted_text: str | None = Field(default=None, description="Quoted message text if this is a reply")
    quoted_sender: str | None = Field(default=None, description="Sender name of the quoted message")


# ============================================================
# Outgoing message shapes (inputs to MCP tools)
# ============================================================


class SendMessageInput(BaseModel):
    """Input schema for the waha_send_message tool."""

    chat_id: str = Field(
        description=(
            "WhatsApp chat ID to send to. "
            "For DMs: the recipient's phone number with @c.us suffix (e.g. 628xxxxxxxxxx@c.us). "
            "For the group chat: the group ID with @g.us suffix."
        )
    )
    text: str = Field(description="Message text to send. Markdown is NOT rendered by WhatsApp.")
    reply_to_message_id: str | None = Field(
        default=None,
        description="Optional: message ID to quote/reply to.",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty or whitespace-only")
        return v


class SendMediaInput(BaseModel):
    """Input schema for the waha_send_media tool."""

    chat_id: str = Field(description="WhatsApp chat ID to send to.")
    media_url: str = Field(description="Publicly accessible URL of the media file to send.")
    caption: str | None = Field(default=None, description="Optional caption shown below the media.")
    reply_to_message_id: str | None = Field(
        default=None,
        description="Optional: message ID to quote/reply to.",
    )


class GetMessagesInput(BaseModel):
    """Input schema for the waha_get_messages tool."""

    chat_id: str = Field(description="WhatsApp chat ID to fetch history from.")
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Number of recent messages to return (1-50, default 20).",
    )


# ============================================================
# WAHA REST API response shapes
# ============================================================


class WahaMessageResponse(BaseModel):
    """Response returned by WAHA after successfully sending a message."""

    message_id: str = Field(description="WAHA-assigned ID for the sent message.")
    timestamp: int = Field(description="Unix timestamp of when the message was sent.")


class WahaHistoryMessage(BaseModel):
    """A single message entry from WAHA chat history."""

    message_id: str
    sender_phone: str
    text: str | None
    media_url: str | None
    timestamp: int
    quoted_text: str | None = None
    quoted_sender: str | None = None


# ============================================================
# Health check
# ============================================================


class HealthResponse(BaseModel):
    """Response from the /health endpoint."""

    status: str = "ok"
    waha_reachable: bool

"""
src.whatsapp — WhatsApp & WAHA Integration Package.
"""

from .client import WahaClient
from .history import (
    build_multi_turn_contents,
    is_duplicate_message,
)
from .parser import (
    ALLOWED_CHATS,
    BOT_PHONE,
    BUNGA_LID,
    BUNGA_PHONE,
    GILANG_LID,
    GILANG_PHONE,
    TRIO_GROUP_JID,
    extract_media_filename,
    extract_quoted_info,
    resolve_sender_identity,
)
from .processor import (
    describe_intent_action,
    process_batched_turn,
    split_into_bubbles,
)
from .queue import ChatQueueManager, ChatQueueWorker, IncomingMessageEvent
from .search import search_web
from .transcribe import transcribe_audio_base64
from .webhook import create_webhook_app

__all__ = [
    "ALLOWED_CHATS",
    "BOT_PHONE",
    "BUNGA_LID",
    "BUNGA_PHONE",
    "ChatQueueManager",
    "ChatQueueWorker",
    "GILANG_LID",
    "GILANG_PHONE",
    "IncomingMessageEvent",
    "TRIO_GROUP_JID",
    "WahaClient",
    "build_multi_turn_contents",
    "create_webhook_app",
    "describe_intent_action",
    "extract_media_filename",
    "extract_quoted_info",
    "is_duplicate_message",
    "process_batched_turn",
    "resolve_sender_identity",
    "search_web",
    "split_into_bubbles",
    "transcribe_audio_base64",
]

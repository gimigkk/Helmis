"""
test_history.py — Tests for chat history chronological ordering and deduplication.
"""

from unittest.mock import MagicMock

from src import history


def test_message_deduplication() -> None:
    msg_id = "msg_12345"
    assert history.is_duplicate_message(msg_id) is False
    assert history.is_duplicate_message(msg_id) is True
    assert history.is_duplicate_message("msg_67890") is False


def test_build_multi_turn_contents_chronological() -> None:
    # Simulating WAHA descending order (newest first)
    m1 = MagicMock(
        message_id="false_user_1",
        text="remind me tomorrow",
        sender_phone="628111111111",
        timestamp=100,
        from_me=False,
    )
    m2 = MagicMock(
        message_id="true_bot_1",
        text="Sure! What time?",
        sender_phone="628333333333",
        timestamp=105,
        from_me=True,
    )
    m3 = MagicMock(
        message_id="false_user_2",
        text="6 sore",
        sender_phone="628111111111",
        timestamp=110,
        from_me=False,
    )

    waha_descending_messages = [m3, m2, m1]

    contents = history.build_multi_turn_contents(
        history_messages=waha_descending_messages,
        sender_name="Gilang",
        current_text="6 sore",
    )

    # First turn should be oldest user message
    assert contents[0]["role"] == "user"
    assert "remind me tomorrow" in contents[0]["parts"][0]["text"]

    # Second turn should be bot reply
    assert contents[1]["role"] == "model"
    assert "Sure! What time?" in contents[1]["parts"][0]["text"]

    # Final turn should be the current incoming turn
    assert contents[-1]["role"] == "user"
    assert "6 sore" in contents[-1]["parts"][0]["text"]

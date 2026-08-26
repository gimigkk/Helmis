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


def test_build_multi_turn_contents_multi_user_group() -> None:
    # Simulating Trio Helmis group chat with Bunga, Helmis, and Gilang
    m_bunga = MagicMock(
        message_id="msg_bunga_1",
        text="hari ini jadwal kuliah ak apa aja",
        sender_phone="628555555555",
        sender_name="Bunga",
        timestamp=200,
        from_me=False,
    )
    m_helmis = MagicMock(
        message_id="true_helmis_1",
        text="Jadwal kuliah kamu hari ini (Rabu): ...",
        sender_phone="628333333333",
        sender_name="Helmis",
        timestamp=205,
        from_me=True,
    )

    history_msgs = [m_bunga, m_helmis]

    # Gilang speaks next:
    contents = history.build_multi_turn_contents(
        history_messages=history_msgs,
        sender_name="Gilang",
        current_text="Anjay udh dimasukin jadwal km?",
    )

    # Turn 0 MUST be attributed to Bunga, NOT overwritten as Gilang
    assert contents[0]["role"] == "user"
    assert "[Bunga]: hari ini jadwal kuliah ak apa aja" in contents[0]["parts"][0]["text"]
    assert "[Gilang]: hari ini jadwal kuliah ak apa aja" not in contents[0]["parts"][0]["text"]

    # Turn 1 is Helmis (model)
    assert contents[1]["role"] == "model"
    assert "Jadwal kuliah kamu hari ini" in contents[1]["parts"][0]["text"]

    # Turn 2 is Gilang's current turn
    assert contents[2]["role"] == "user"
    assert "[Gilang]: Anjay udh dimasukin jadwal km?" in contents[2]["parts"][0]["text"]


"""Tests for explicit group admission policy (src/whatsapp/policy.py)."""

from src.whatsapp.policy import (
    clean_phone,
    decide_group_admission,
    extract_mentioned_ids,
    is_group_chat,
    is_valid_group_jid,
    mentions_bot,
    mentions_other_human,
)

BOT = "628111000000"
GILANG = "628222000000"
BUNGA = "628333000000"


class TestCleanPhone:
    def test_strips_formatting(self) -> None:
        assert clean_phone("+62 811-100-0000") == "628111000000"
        assert clean_phone("") == ""


class TestExtractMentionedIds:
    def test_all_engine_shapes(self) -> None:
        assert extract_mentioned_ids({"mentionedIds": ["a", "b"]}) == ["a", "b"]
        assert extract_mentioned_ids({"mentions": ["c"]}) == ["c"]
        assert extract_mentioned_ids({"mentionedJidList": ["d"]}) == ["d"]
        assert extract_mentioned_ids({"_data": {"mentionedJidList": ["e"]}}) == ["e"]
        assert extract_mentioned_ids({"_data": {"mentions": ["f"]}}) == ["f"]
        assert extract_mentioned_ids({"mentionedIds": "single"}) == ["single"]
        assert extract_mentioned_ids({}) == []

    def test_non_dict_data_ignored(self) -> None:
        assert extract_mentioned_ids({"_data": "junk", "mentions": ["x"]}) == ["x"]


class TestMentionsBot:
    def test_name_in_text(self) -> None:
        assert mentions_bot("helmis gimana", [], bot_phone=BOT) is True

    def test_mis_trigger_prefix(self) -> None:
        assert mentions_bot("mis kirim jadwal", [], bot_phone=BOT) is True
        assert mentions_bot("mis, tolong", [], bot_phone=BOT) is True
        assert mentions_bot("mis? apakah", [], bot_phone=BOT) is True

    def test_at_mention(self) -> None:
        assert mentions_bot("yo @helmis bantu", [], bot_phone=BOT) is True

    def test_phone_in_mentions(self) -> None:
        assert mentions_bot("halo bro", [f"{BOT}@c.us"], bot_phone=BOT) is True

    def test_quoting_bot(self) -> None:
        assert mentions_bot("ok", [], bot_phone=BOT, quoted_sender="Helmis") is True

    def test_no_mention(self) -> None:
        assert mentions_bot("halo gilang", [f"{GILANG}@c.us"], bot_phone=BOT) is False
        assert mentions_bot("misanthropi lucu", [], bot_phone=BOT) is False

    def test_mis_without_space_not_trigger(self) -> None:
        assert mentions_bot("mistis banget", [], bot_phone=BOT) is False


class TestMentionsOtherHuman:
    def test_at_bunga(self) -> None:
        assert (
            mentions_other_human("@bunga kamu kemana", [], owner_phone=GILANG, partner_phone=BUNGA, has_bot_mention=False)
            is True
        )

    def test_at_gilang(self) -> None:
        assert (
            mentions_other_human("@gilang bales dong", [], owner_phone=GILANG, partner_phone=BUNGA, has_bot_mention=False)
            is True
        )

    def test_phone_mention(self) -> None:
        assert (
            mentions_other_human("cek ini", [f"{BUNGA}@c.us"], owner_phone=GILANG, partner_phone=BUNGA, has_bot_mention=False)
            is True
        )

    def test_bot_mention_wins(self) -> None:
        # Bot mentioned AND other human mentioned -> bot answers (not ignored)
        assert (
            mentions_other_human("@bunga @helmis", [], owner_phone=GILANG, partner_phone=BUNGA, has_bot_mention=True)
            is False
        )

    def test_no_human_mention(self) -> None:
        assert (
            mentions_other_human("halo semua", [], owner_phone=GILANG, partner_phone=BUNGA, has_bot_mention=False)
            is False
        )


class TestDecideGroupAdmission:
    def test_bot_addressed_queues(self) -> None:
        decision = decide_group_admission(
            "helmis ingetin gw rapat",
            {},
            bot_phone=BOT,
            owner_phone=GILANG,
            partner_phone=BUNGA,
        )
        assert decision == "queued"

    def test_human_banter_ignored(self) -> None:
        decision = decide_group_admission(
            "@bunga jangan lupa bayar kosan",
            {},
            bot_phone=BOT,
            owner_phone=GILANG,
            partner_phone=BUNGA,
        )
        assert decision == "ignored_directed_to_other"

    def test_bot_and_human_mentioned_queues(self) -> None:
        decision = decide_group_admission(
            "@helmis @bunga tolong ingetin kita",
            {},
            bot_phone=BOT,
            owner_phone=GILANG,
            partner_phone=BUNGA,
        )
        assert decision == "queued"

    def test_casual_without_mentions_queues(self) -> None:
        # Bare group chat (not mentioning anyone) stays queued; allowlist +
        # identity resolution upstream already restrict who can talk.
        decision = decide_group_admission(
            "wkwkwk lucu banget",
            {},
            bot_phone=BOT,
            owner_phone=GILANG,
            partner_phone=BUNGA,
        )
        assert decision == "queued"

    def test_mention_payload_extraction(self) -> None:
        decision = decide_group_admission(
            "tolong catat ini",
            {"_data": {"mentionedJidList": [f"{BUNGA}@c.us"]}},
            bot_phone=BOT,
            owner_phone=GILANG,
            partner_phone=BUNGA,
        )
        assert decision == "ignored_directed_to_other"


class TestGroupJIDHelpers:
    def test_is_group_chat(self) -> None:
        assert is_group_chat("123@ g.us".replace(" ", "")) is True
        assert is_group_chat("628222000000@c.us") is False
        assert is_group_chat("") is False

    def test_is_valid_group_jid(self) -> None:
        assert is_valid_group_jid("12036302@g.us") is True
        assert is_valid_group_jid("628222000000@c.us") is False
        assert is_valid_group_jid("no-at-sign") is False

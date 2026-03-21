from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import roughcut.review.telegram_bot as telegram_bot
from roughcut.review.telegram_bot import (
    FinalReviewRerunPlan,
    TelegramFinalReviewClip,
    TelegramSubtitleLineCandidate,
    TelegramReviewThumbnail,
    TelegramReviewBotService,
    _build_content_profile_review_message,
    _build_final_review_clip_specs,
    _build_final_review_message,
    _build_final_review_reply_markup,
    _build_final_review_rerun_plan,
    _build_final_review_rerun_plans,
    _combine_final_review_rerun_plans,
    _build_pending_subtitle_candidates,
    _build_review_callback_data,
    _extract_review_reference,
    _extract_review_callback_reference,
    _extract_review_reference_from_message,
    _interpret_full_subtitle_review_reply,
    _interpret_content_profile_reply,
    _interpret_subtitle_review_reply,
    _split_review_message,
)


def test_extract_review_reference_reads_embedded_token():
    job_id = uuid.uuid4()

    result = _extract_review_reference(f"【RC:content_profile:{job_id}】\n请审核")

    assert result == ("content_profile", job_id)


def test_extract_review_reference_reads_reply_caption_token():
    job_id = uuid.uuid4()

    result = _extract_review_reference_from_message(
        {
            "text": "通过",
            "reply_to_message": {
                "caption": f"【RC:content_profile:{job_id}】\n参考缩略图 1/3",
            },
        }
    )

    assert result == ("content_profile", job_id)


def test_extract_review_callback_reference_reads_final_review_action():
    job_id = uuid.uuid4()

    result = _extract_review_callback_reference(_build_review_callback_data("final_review", job_id, "cover"))

    assert result == ("final_review", job_id, "cover")


def test_build_final_review_reply_markup_contains_expected_buttons():
    job_id = uuid.uuid4()

    markup = _build_final_review_reply_markup(job_id)
    button_texts = [button["text"] for row in markup["inline_keyboard"] for button in row]
    callback_values = [button["callback_data"] for row in markup["inline_keyboard"] for button in row]

    assert button_texts == ["成片通过", "只改封面", "只改BGM", "只改平台文案", "数字人口播重做"]
    assert callback_values[0] == f"RCB:final:{job_id}:approve"
    assert callback_values[-1] == f"RCB:final:{job_id}:avatar"


def test_split_review_message_preserves_all_lines():
    text = "\n".join(f"line {index}" for index in range(20))

    chunks = _split_review_message(text, limit=32)

    assert len(chunks) > 1
    assert "\n".join(chunks).replace("\n\n", "\n") == text


def test_build_pending_subtitle_candidates_only_includes_undecided_items():
    report = SimpleNamespace(
        items=[
            {
                "index": 1,
                "start": 0.0,
                "end": 1.5,
                "corrections": [
                    {"id": "a", "original": "原词", "suggested": "新词", "type": "term", "confidence": 0.9, "source": "glossary", "decision": None},
                    {"id": "b", "original": "旧词", "suggested": "新词2", "type": "term", "confidence": 0.7, "source": "glossary", "decision": "accepted"},
                ],
            },
            {
                "index": 2,
                "start": 1.6,
                "end": 3.0,
                "corrections": [
                    {"id": "c", "original": "错别字", "suggested": "正字", "type": "subtitle", "confidence": 0.8, "source": "memory", "decision": None},
                ],
            },
        ]
    )

    candidates = _build_pending_subtitle_candidates(report)

    assert [item.slot for item in candidates] == ["S1", "S2"]
    assert [item.correction_id for item in candidates] == ["a", "c"]
    assert candidates[0].start_sec == 0.0
    assert candidates[0].end_sec == 1.5


@pytest.mark.asyncio
async def test_interpret_subtitle_review_reply_accepts_all_without_model():
    candidates = [
        SimpleNamespace(correction_id="a"),
        SimpleNamespace(correction_id="b"),
    ]

    actions = await _interpret_subtitle_review_reply("全部通过", candidates)

    assert actions == [
        {"correction_id": "a", "action": "accepted"},
        {"correction_id": "b", "action": "accepted"},
    ]


@pytest.mark.asyncio
async def test_interpret_subtitle_review_reply_rejects_all_without_model():
    candidates = [
        SimpleNamespace(correction_id="a"),
        SimpleNamespace(correction_id="b"),
    ]

    actions = await _interpret_subtitle_review_reply("全部拒绝", candidates)

    assert actions == [
        {"correction_id": "a", "action": "rejected"},
        {"correction_id": "b", "action": "rejected"},
    ]


def test_interpret_full_subtitle_review_reply_parses_line_updates():
    lines = [
        TelegramSubtitleLineCandidate(
            slot="L1",
            subtitle_item_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            subtitle_index=0,
            text="鸿福工业",
        ),
        TelegramSubtitleLineCandidate(
            slot="L2",
            subtitle_item_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            subtitle_index=1,
            text="下一句",
        ),
    ]

    accept_all, actions = _interpret_full_subtitle_review_reply("L1改成 狐蝠工业，L2通过", lines)

    assert accept_all is False
    assert actions == [
        {
            "subtitle_item_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "action": "updated",
            "override_text": "狐蝠工业",
        },
        {
            "subtitle_item_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "action": "accepted",
        },
    ]


@pytest.mark.asyncio
async def test_interpret_content_profile_reply_maps_to_frontend_like_payload(monkeypatch):
    class FakeResponse:
        def as_json(self):
            return {
                "workflow_mode": "standard_edit",
                "enhancement_modes": ["ai_director", "unknown_mode"],
                "subject_brand": "Loop露普",
                "video_theme": "夜骑补光对比",
                "keywords": ["夜骑", "补光", "夜骑"],
                "correction_notes": "品牌和主题都改一下",
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(telegram_bot, "get_reasoning_provider", lambda: FakeProvider())
    review = SimpleNamespace(
        workflow_mode="standard_edit",
        enhancement_modes=["avatar_commentary"],
        draft={"subject_brand": "旧品牌"},
        final=None,
    )

    payload = await _interpret_content_profile_reply(review, "品牌改成 Loop露普，主题强调夜骑补光，并打开 AI 导演")

    assert payload["workflow_mode"] == "standard_edit"
    assert payload["enhancement_modes"] == ["ai_director"]
    assert payload["subject_brand"] == "Loop露普"
    assert payload["video_theme"] == "夜骑补光对比"
    assert payload["keywords"] == ["夜骑", "补光"]
    assert payload["correction_notes"] == "品牌和主题都改一下"


@pytest.mark.asyncio
async def test_handle_content_profile_reply_acknowledges_and_dispatches_subtitle_review(monkeypatch):
    service = TelegramReviewBotService()
    sent: list[str] = []
    notified: list[uuid.UUID] = []
    confirmed_payloads: list[dict[str, object]] = []
    job_id = uuid.uuid4()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    async def fake_get_content_profile(job_id_value, session):
        assert job_id_value == job_id
        return SimpleNamespace(
            review_step_status="pending",
            workflow_mode="standard_edit",
            enhancement_modes=[],
            draft={},
            final=None,
        )

    async def fake_confirm(job_id_value, body, session):
        assert job_id_value == job_id
        confirmed_payloads.append(body.model_dump(exclude_none=True))
        return SimpleNamespace()

    async def fake_generate_report(job_id_value, session):
        assert job_id_value == job_id
        return SimpleNamespace(
            items=[
                {
                    "index": 1,
                    "start": 0.0,
                    "end": 1.0,
                    "corrections": [
                        {
                            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "original": "鸿福",
                            "suggested": "狐蝠工业",
                            "type": "term",
                            "confidence": 0.82,
                            "source": "glossary",
                            "decision": None,
                        }
                    ],
                }
            ]
        )

    async def fake_notify_subtitle_review(job_id_value: uuid.UUID, *, force_full_review: bool = False) -> None:
        notified.append(job_id_value)
        assert force_full_review is False

    service._send_chat_text = fake_send_text
    service.notify_subtitle_review = fake_notify_subtitle_review

    monkeypatch.setattr(telegram_bot, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(telegram_bot, "get_content_profile", fake_get_content_profile)
    monkeypatch.setattr(telegram_bot, "confirm_content_profile", fake_confirm)
    monkeypatch.setattr(telegram_bot, "generate_report", fake_generate_report)
    monkeypatch.setattr(
        telegram_bot,
        "_interpret_content_profile_reply",
        AsyncMock(return_value={"correction_notes": "字幕还需要校对"}),
    )

    await service._handle_content_profile_reply(job_id, "通过 但是字幕还需要校对", reply_chat_id="123")

    assert sent[0] == f"已收到任务 {job_id} 的审核意见，正在处理，请稍候。"
    assert sent[1] == f"已确认任务 {job_id} 的内容摘要；检测到你还要校对字幕，我现在把 1 条待审字幕项发你。"
    assert notified == [job_id]
    assert confirmed_payloads == [{"correction_notes": "字幕还需要校对"}]


@pytest.mark.asyncio
async def test_handle_content_profile_reply_dispatches_full_subtitle_review_when_no_candidates(monkeypatch):
    service = TelegramReviewBotService()
    sent: list[str] = []
    notified: list[tuple[uuid.UUID, bool]] = []
    job_id = uuid.uuid4()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    async def fake_get_content_profile(job_id_value, session):
        assert job_id_value == job_id
        return SimpleNamespace(
            review_step_status="pending",
            workflow_mode="standard_edit",
            enhancement_modes=[],
            draft={},
            final=None,
        )

    async def fake_confirm(job_id_value, body, session):
        return SimpleNamespace()

    async def fake_generate_report(job_id_value, session):
        return SimpleNamespace(items=[])

    async def fake_notify_subtitle_review(job_id_value: uuid.UUID, *, force_full_review: bool = False) -> None:
        notified.append((job_id_value, force_full_review))

    service._send_chat_text = fake_send_text
    service.notify_subtitle_review = fake_notify_subtitle_review

    monkeypatch.setattr(telegram_bot, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(telegram_bot, "get_content_profile", fake_get_content_profile)
    monkeypatch.setattr(telegram_bot, "confirm_content_profile", fake_confirm)
    monkeypatch.setattr(telegram_bot, "generate_report", fake_generate_report)
    monkeypatch.setattr(
        telegram_bot,
        "_interpret_content_profile_reply",
        AsyncMock(return_value={"correction_notes": "字幕需要全量复核"}),
    )

    await service._handle_content_profile_reply(job_id, "通过 但是字幕还需要校对", reply_chat_id="123")

    assert sent[0] == f"已收到任务 {job_id} 的审核意见，正在处理，请稍候。"
    assert sent[1] == f"已确认任务 {job_id} 的内容摘要；自动字幕纠错没有产出候选，我现在改发全量字幕人工复核包。"
    assert notified == [(job_id, True)]

@pytest.mark.asyncio
async def test_handle_update_help_responds_without_chat_match(monkeypatch):
    service = TelegramReviewBotService()
    sent = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_remote_review_enabled=True,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)

    await service._handle_update(
        {
            "message": {
                "text": "/help",
                "chat": {"id": "999"},
            }
        }
    )

    assert sent, "help response should be sent even when chat id differs"
    assert "远程审核已启用" in sent[0]


@pytest.mark.asyncio
async def test_handle_update_whoami_returns_chat_id(monkeypatch):
    service = TelegramReviewBotService()
    sent = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)
    await service._handle_update(
        {
            "message": {
                "text": "/whoami",
                "chat": {"id": "999"},
            }
        }
    )

    assert sent == ["当前会话 Chat ID：999"]


@pytest.mark.asyncio
async def test_handle_update_without_reference_guides_reply_pattern(monkeypatch):
    service = TelegramReviewBotService()
    sent = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_remote_review_enabled=True,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)

    await service._handle_update(
        {
            "message": {
                "text": "通过",
                "chat": {"id": "123"},
            }
        }
    )

    assert sent
    assert "未识别到审核上下文" in sent[0]


@pytest.mark.asyncio
async def test_handle_update_freeform_request_routes_to_agent(monkeypatch):
    service = TelegramReviewBotService()
    sent = []
    routed = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    async def fake_handle_freeform(text: str, *, send_text) -> bool:
        routed.append(text)
        await send_text("已创建 agent 任务")
        return True

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    monkeypatch.setattr(telegram_bot, "handle_telegram_freeform_request", fake_handle_freeform)
    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)

    await service._handle_update(
        {
            "message": {
                "text": "请帮我优化 telegram agent 的错误链路",
                "chat": {"id": "123"},
            }
        }
    )

    assert routed == ["请帮我优化 telegram agent 的错误链路"]
    assert sent == ["已创建 agent 任务"]


@pytest.mark.asyncio
async def test_handle_update_voice_request_routes_to_agent(monkeypatch):
    service = TelegramReviewBotService()
    sent = []
    routed = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    async def fake_transcribe(message: dict, *, chat_id: str, settings) -> str:
        assert message["voice"]["file_id"] == "voice-file-1"
        assert chat_id == "123"
        return "请帮我优化 telegram agent 的错误链路"

    async def fake_handle_freeform(text: str, *, send_text) -> bool:
        routed.append(text)
        await send_text("已创建 agent 任务")
        return True

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    monkeypatch.setattr(service, "_transcribe_message_audio_text", fake_transcribe)
    monkeypatch.setattr(telegram_bot, "handle_telegram_freeform_request", fake_handle_freeform)
    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)

    await service._handle_update(
        {
            "message": {
                "voice": {"file_id": "voice-file-1", "mime_type": "audio/ogg"},
                "chat": {"id": "123"},
            }
        }
    )

    assert routed == ["请帮我优化 telegram agent 的错误链路"]
    assert sent == ["已创建 agent 任务"]


@pytest.mark.asyncio
async def test_handle_update_voice_command_maps_to_status(monkeypatch):
    service = TelegramReviewBotService()
    sent = []
    commands = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    async def fake_transcribe(_message: dict, *, chat_id: str, settings) -> str:
        assert chat_id == "123"
        return "查看状态"

    async def fake_handle_command(text: str, *, send_text) -> bool:
        commands.append(text)
        await send_text("服务状态：正常")
        return True

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    monkeypatch.setattr(service, "_transcribe_message_audio_text", fake_transcribe)
    monkeypatch.setattr(telegram_bot, "handle_telegram_command", fake_handle_command)
    service._send_chat_text = lambda text, *, chat_id: fake_send_text(text)

    await service._handle_update(
        {
            "message": {
                "voice": {"file_id": "voice-file-2", "mime_type": "audio/ogg"},
                "chat": {"id": "123"},
            }
        }
    )

    assert commands == ["/status"]
    assert sent == ["服务状态：正常"]


@pytest.mark.asyncio
async def test_handle_update_voice_reply_dispatches_review(monkeypatch):
    service = TelegramReviewBotService()
    job_id = uuid.uuid4()
    handled = []

    async def fake_transcribe(_message: dict, *, chat_id: str, settings) -> str:
        assert chat_id == "123"
        return "通过"

    async def fake_handle(job_id_value: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        handled.append((job_id_value, text, reply_chat_id))

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    monkeypatch.setattr(service, "_transcribe_message_audio_text", fake_transcribe)
    service._handle_content_profile_reply = fake_handle

    await service._handle_update(
        {
            "message": {
                "voice": {"file_id": "voice-file-3", "mime_type": "audio/ogg"},
                "chat": {"id": "123"},
                "reply_to_message": {
                    "caption": f"【RC:content_profile:{job_id}】\n请审核",
                },
            }
        }
    )

    assert handled == [(job_id, "通过", "123")]


def test_telegram_agent_enabled_without_chat_id():
    settings = SimpleNamespace(
        telegram_agent_enabled=True,
        telegram_remote_review_enabled=False,
        telegram_bot_token="token",
        telegram_bot_chat_id="",
    )

    assert telegram_bot._telegram_ready(settings) is True


def test_normalize_spoken_command_text_maps_common_aliases():
    assert telegram_bot._normalize_spoken_command_text("查看状态") == "/status"
    assert telegram_bot._normalize_spoken_command_text("最近任务") == "/jobs"
    assert telegram_bot._normalize_spoken_command_text("确认任务 abc-123") == "/confirm abc-123"
    assert telegram_bot._normalize_spoken_command_text("取消任务 task-99") == "/cancel task-99"


def test_build_content_profile_review_message_matches_frontend_sections():
    job_id = uuid.uuid4()
    review = SimpleNamespace(
        workflow_mode="standard_edit",
        enhancement_modes=["ai_effects", "ai_director"],
    )
    message = _build_content_profile_review_message(
        source_name="夜骑补光.mp4",
        job_id=job_id,
        review=review,
        draft={
            "copy_style": "trusted_expert",
            "subject_brand": "Loop露普",
            "subject_model": "SK05 Pro",
            "subject_type": "手电",
            "video_theme": "夜骑补光实测",
            "hook_line": "这颗补光真有必要吗",
            "visible_text": "夜骑 / 补光 / 实测",
            "summary": "对比不同档位和照射范围。",
            "engagement_question": "你会带主灯还是副灯？",
            "correction_notes": "突出续航和泛光差异",
            "supplemental_context": "面向夜骑 EDC 用户",
            "search_queries": ["夜骑补光", "手电实测"],
            "transcript_excerpt": "先看近距离泛光，再看远射。",
            "automation_review": {
                "score": 0.42,
                "threshold": 0.75,
                "review_reasons": ["关键信息需要人工确认"],
                "blocking_reasons": ["主题表述还不够准确"],
            },
        },
        packaging_assets={
            "intro": [{"id": "intro-1", "original_name": "片头A.mp4"}],
            "outro": [{"id": "outro-1", "original_name": "片尾A.mp4"}],
            "insert": [{"id": "insert-1", "original_name": "夜骑转场.mp4"}],
            "watermark": [{"id": "wm-1", "original_name": "品牌水印.png"}],
            "music": [{"id": "music-1", "original_name": "节奏感BGM.mp3"}],
        },
        packaging_config={
            "enabled": True,
            "intro_asset_id": "intro-1",
            "outro_asset_id": "outro-1",
            "insert_asset_ids": ["insert-1"],
            "watermark_asset_id": "wm-1",
            "music_asset_ids": ["music-1"],
            "subtitle_style": "bold_yellow_outline",
            "cover_style": "bold_review",
            "title_style": "tutorial_blueprint",
            "copy_style": "attention_grabbing",
            "smart_effect_style": "smart_effect_punch",
        },
        config=SimpleNamespace(
            avatar_presenter_id="",
            voice_provider="indextts2",
            voice_clone_api_base_url="http://127.0.0.1:49204",
            voice_clone_api_key_set=False,
            voice_clone_voice_id="",
        ),
        avatar_materials=SimpleNamespace(
            profiles=[
                SimpleNamespace(
                    display_name="店播数字人A",
                    capability_status={"preview": "ready"},
                )
            ]
        ),
    )

    assert f"Job ID：{job_id}" in message
    assert "核对配置：" in message
    assert "内容核对：" in message
    assert "增强模式素材检查：" in message
    assert "包装素材清单：" in message
    assert "风格模板清单：" in message
    assert "数字人解说" not in message
    assert "智能剪辑特效：已启用智能剪辑特效" in message
    assert "AI 导演重配音：当前走 IndexTTS2 accel 主实例，本地服务：http://127.0.0.1:49204" in message
    assert "片头：片头A.mp4" in message
    assert "转场 / 包装插片：夜骑转场.mp4" in message
    assert "字幕风格：粗黄描边" in message
    assert "封面模板：重磅测评" in message
    assert "标题模板：教程蓝图" in message
    assert "文案风格：专业可信" in message
    assert "智能剪辑特效：爆点冲击" in message
    assert "视频主题：夜骑补光实测" in message
    assert "关键词：夜骑补光，手电实测" in message
    assert "系统识别参考：" in message
    assert "审核原因：" in message


def test_build_content_profile_review_message_includes_avatar_check_when_enabled():
    message = _build_content_profile_review_message(
        source_name="avatar.mp4",
        job_id=uuid.uuid4(),
        review=SimpleNamespace(
            workflow_mode="standard_edit",
            enhancement_modes=["avatar_commentary"],
        ),
        draft={},
        packaging_assets={},
        packaging_config={"enabled": True},
        config=SimpleNamespace(
            avatar_presenter_id="",
            voice_provider="indextts2",
            voice_clone_api_base_url="http://127.0.0.1:49204",
            voice_clone_api_key_set=False,
            voice_clone_voice_id="",
        ),
        avatar_materials=SimpleNamespace(
            profiles=[
                SimpleNamespace(
                    display_name="店播数字人A",
                    capability_status={"preview": "ready"},
                )
            ]
        ),
    )

    assert "数字人解说：未显式绑定 avatar_presenter_id，但已有可用数字人档案：店播数字人A" in message


def test_build_content_profile_review_message_prefers_resolved_packaging_and_avatar_display_name():
    message = _build_content_profile_review_message(
        source_name="fas.mp4",
        job_id=uuid.uuid4(),
        review=SimpleNamespace(
            workflow_mode="standard_edit",
            enhancement_modes=["avatar_commentary"],
        ),
        draft={
            "subject_type": "手电",
            "video_theme": "户外实测",
        },
        packaging_assets={},
        packaging_config={"enabled": True},
        packaging_plan={
            "outro": {"asset_id": "outro-1", "original_name": "品牌片尾.mp4"},
            "music": {"asset_id": "music-1", "original_name": "战术BGM.mp3"},
            "subtitle_style": "bold_yellow_outline",
            "cover_style": "preset_default",
            "title_style": "preset_default",
            "copy_style": "attention_grabbing",
            "smart_effect_style": "smart_effect_rhythm",
        },
        config=SimpleNamespace(
            avatar_presenter_id=r"data\avatar_materials\profiles\FAS_b3622e31\presenter.mp4",
            voice_provider="indextts2",
            voice_clone_api_base_url="http://127.0.0.1:49204",
            voice_clone_api_key_set=False,
            voice_clone_voice_id="",
        ),
        avatar_materials=SimpleNamespace(
            profiles=[
                SimpleNamespace(
                    id="fas-profile",
                    display_name="FAS",
                    presenter_alias="FAS",
                    profile_dir=r"data\avatar_materials\profiles\FAS_b3622e31",
                    files=[
                        SimpleNamespace(
                            id="fas-file",
                            path=r"data\avatar_materials\profiles\FAS_b3622e31\presenter.mp4",
                            original_name="presenter.mp4",
                            stored_name="presenter.mp4",
                        )
                    ],
                    capability_status={"preview": "ready"},
                )
            ]
        ),
    )

    assert "片尾：品牌片尾.mp4" in message
    assert "音乐：战术BGM.mp3" in message
    assert "使用 FAS数字人的解说视频素材" in message


@pytest.mark.asyncio
async def test_send_review_message_sends_text_then_thumbnail_context(monkeypatch, tmp_path):
    service = TelegramReviewBotService()
    sent_text: list[str] = []
    sent_photos: list[tuple[str, str, str, int | None]] = []
    job_id = uuid.uuid4()
    photo_path = tmp_path / "thumb.jpg"
    photo_path.write_bytes(b"thumb")

    async def fake_send_text(text: str, *, reply_markup=None) -> int | None:
        sent_text.append(text)
        return 88

    async def fake_send_photo(
        path,
        *,
        chat_id: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        sent_photos.append((path.name, caption, chat_id, reply_to_message_id))
        return 99

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    service._send_text = fake_send_text
    service._send_chat_photo = fake_send_photo

    await service._send_review_message(
        "content_profile",
        job_id,
        "任务：缩略图校对",
        thumbnails=[
            TelegramReviewThumbnail(
                path=photo_path,
                caption=f"【RC:content_profile:{job_id}】\n参考缩略图 1/3",
            )
        ],
    )

    assert sent_text == [f"【RC:content_profile:{job_id}】\n任务：缩略图校对"]
    assert sent_photos == [("thumb.jpg", f"【RC:content_profile:{job_id}】\n参考缩略图 1/3", "123", 88)]


@pytest.mark.asyncio
async def test_send_review_message_sends_multiple_thumbnails_as_media_group(monkeypatch, tmp_path):
    service = TelegramReviewBotService()
    sent_text: list[str] = []
    sent_photo_groups: list[tuple[list[str], str, int | None]] = []
    sent_photos: list[str] = []
    job_id = uuid.uuid4()
    photo_paths = []
    for index in range(3):
        path = tmp_path / f"thumb-{index}.jpg"
        path.write_bytes(f"thumb-{index}".encode("utf-8"))
        photo_paths.append(path)

    async def fake_send_text(text: str, *, reply_markup=None) -> int | None:
        sent_text.append(text)
        return 88

    async def fake_send_photo_group(
        photos,
        *,
        chat_id: str,
        reply_to_message_id: int | None = None,
    ) -> list[int]:
        sent_photo_groups.append(([item.path.name for item in photos], chat_id, reply_to_message_id))
        return [91, 92, 93]

    async def fake_send_photo(*args, **kwargs) -> int | None:
        sent_photos.append("single")
        return 99

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )
    service._send_text = fake_send_text
    service._send_chat_photo_group = fake_send_photo_group
    service._send_chat_photo = fake_send_photo

    await service._send_review_message(
        "content_profile",
        job_id,
        "任务：缩略图校对",
        thumbnails=[
            TelegramReviewThumbnail(
                path=photo_paths[index],
                caption=f"【RC:content_profile:{job_id}】\n参考缩略图 {index + 1}/3",
            )
            for index in range(3)
        ],
    )

    assert sent_text == [f"【RC:content_profile:{job_id}】\n任务：缩略图校对"]
    assert sent_photo_groups == [([path.name for path in photo_paths], "123", 88)]
    assert sent_photos == []


def test_build_final_review_message_includes_summary_keywords_and_subtitle_hints():
    message = _build_final_review_message(
        source_name="final.mp4",
        job_id=uuid.uuid4(),
        workflow_mode="standard_edit",
        enhancement_modes=["avatar_commentary"],
        render_outputs={
            "packaged_mp4": r"E:\output\final.mp4",
            "plain_mp4": r"E:\output\plain.mp4",
            "cover": r"E:\output\cover.jpg",
        },
        content_profile={
            "summary": "这期重点看扁桶手电的便携性和泛光表现。",
            "search_queries": ["扁桶手电", "Olight 司令官2 Ultra"],
        },
        subtitle_report=SimpleNamespace(
            items=[
                {
                    "index": 3,
                    "start": 12.0,
                    "end": 14.0,
                    "text_raw": "这是 olight 的开箱",
                    "text_norm": "这是 olight 的开箱",
                    "text_final": "这是 olight 的开箱",
                    "corrections": [
                        {
                            "id": "corr-1",
                            "original": "olight",
                            "suggested": "Olight",
                            "type": "term",
                            "confidence": 0.64,
                            "source": "glossary",
                            "decision": None,
                        }
                    ],
                }
            ]
        ),
        rerun_context={
            "step_name": "render",
            "targets": ["cover", "music"],
            "feedback": "封面太弱，BGM 换掉",
        },
    )

    assert "默认发送 3 段压缩预览" in message
    assert "内容摘要：这期重点看扁桶手电的便携性和泛光表现。" in message
    assert "关键词：扁桶手电，Olight 司令官2 Ultra" in message
    assert "重跑说明：" in message
    assert "本次重跑目标：cover, music" in message
    assert "字幕复核提醒：" in message
    assert "原“olight” -> 建议“Olight”" in message
    assert "S1通过，S2改成 Olight" in message
    assert "只改封面" in message
    assert "只改平台文案" in message


@pytest.mark.asyncio
async def test_send_review_message_attaches_final_review_reply_markup(monkeypatch):
    service = TelegramReviewBotService()
    job_id = uuid.uuid4()
    sent_texts: list[tuple[str, dict[str, object] | None]] = []
    sent_videos: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )

    async def fake_send_text(text: str, *, reply_markup=None):
        sent_texts.append((text, reply_markup))
        return 99 if len(sent_texts) == 1 else 100

    async def fake_send_video(path, *, chat_id: str, caption: str = "", reply_to_message_id: int | None = None):
        sent_videos.append((caption, reply_to_message_id))
        return 101

    service._send_text = fake_send_text
    service._send_chat_video = fake_send_video

    await service._send_review_message(
        "final_review",
        job_id,
        "\n".join(f"line {index}" for index in range(800)),
        videos=[telegram_bot.TelegramReviewVideo(path=telegram_bot.Path(__file__), caption="预览 1")],
    )

    assert len(sent_texts) >= 2
    assert sent_texts[0][1] == _build_final_review_reply_markup(job_id)
    assert all(reply_markup is None for _, reply_markup in sent_texts[1:])
    assert sent_videos == [("预览 1", 99)]


def test_build_final_review_clip_specs_prefers_keyword_segment():
    clips = _build_final_review_clip_specs(
        duration_sec=60.0,
        subtitle_items=[
            {"index": 1, "start": 1.0, "end": 3.0, "text": "先看开头展示"},
            {"index": 2, "start": 24.0, "end": 28.0, "text": "这里重点讲扁桶手电的握持和亮度"},
            {"index": 3, "start": 50.0, "end": 55.0, "text": "最后总结值不值得买"},
        ],
        keywords=["扁桶手电", "亮度"],
    )

    assert len(clips) == 3
    assert any(clip.matched_keyword == "扁桶手电" for clip in clips)
    assert any("开头" in clip.label for clip in clips)
    assert all(0.0 <= clip.start_sec < 60.0 for clip in clips)
    assert all(isinstance(clip, TelegramFinalReviewClip) for clip in clips)


def test_build_final_review_rerun_plan_maps_common_feedback():
    cases = {
        "封面要重做，标题字太弱": ("render", "封面重出"),
        "数字人口播不自然，重跑数字人": ("avatar_commentary", "数字人解说重做"),
        "节奏太拖，前半段重剪": ("edit_plan", "剪辑结构重做"),
        "字幕有错别字": ("subtitle_postprocess", "字幕与术语修订"),
        "摘要和主题不准": ("content_profile", "内容摘要与文案定位调整"),
        "旁白文案要重写": ("ai_director", "AI 导演文案与配音重做"),
        "发布标题和话题标签重写": ("platform_package", "平台文案与发布文案重出"),
        "字幕样式太花了": ("render", "字幕样式重出"),
        "BGM 换掉": ("render", "背景音乐重出"),
    }

    for text, (trigger_step, label) in cases.items():
        plan = _build_final_review_rerun_plan(text)
        assert isinstance(plan, FinalReviewRerunPlan)
        assert plan.trigger_step == trigger_step
        assert plan.label == label
        assert plan.rerun_steps[0] == trigger_step


def test_combine_final_review_rerun_plans_prefers_earliest_step():
    plans = _build_final_review_rerun_plans("字幕和封面都要改，发布文案也重写")
    combined = _combine_final_review_rerun_plans(plans)

    assert combined is not None
    assert combined.trigger_step == "subtitle_postprocess"
    assert combined.rerun_steps[0] == "subtitle_postprocess"
    assert "字幕与术语修订" in combined.label
    assert "封面重出" in combined.label
    assert "平台文案与发布文案重出" in combined.label
    assert "cover" in combined.targets
    assert "publish_copy" in combined.targets


def test_build_final_review_rerun_plans_distinguishes_subtitle_style_from_subtitle_text():
    plans = _build_final_review_rerun_plans("字幕样式要换，但是字幕内容本身没问题")

    assert [plan.category for plan in plans] == ["subtitle_style"]
    assert plans[0].trigger_step == "render"
    assert plans[0].targets == ("subtitle_style",)


@pytest.mark.asyncio
async def test_build_final_review_videos_generates_compressed_previews(monkeypatch, tmp_path):
    packaged = tmp_path / "packaged.mp4"
    packaged.write_bytes(b"video")

    async def fake_probe(path):
        assert path == packaged
        return SimpleNamespace(
            duration=42.0,
            width=1080,
            height=1920,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=1024,
            format_name="mov,mp4",
            bit_rate=900000,
        )

    async def fake_preview(*, job_id, source_path, clip_index, start_sec, duration_sec):
        assert source_path == packaged
        preview = tmp_path / f"preview_{clip_index}.mp4"
        preview.write_bytes(b"preview")
        return preview

    monkeypatch.setattr(telegram_bot, "probe", fake_probe)
    monkeypatch.setattr(telegram_bot, "_ensure_final_review_preview", fake_preview)

    videos = await telegram_bot._build_final_review_videos(
        uuid.uuid4(),
        {"packaged_mp4": str(packaged)},
        content_profile={"search_queries": ["扁桶手电"]},
        subtitle_report=SimpleNamespace(
            items=[
                {"index": 1, "start": 2.0, "end": 4.0, "text_raw": "开头", "text_norm": "开头", "text_final": "开头", "corrections": []},
                {"index": 2, "start": 18.0, "end": 22.0, "text_raw": "重点讲扁桶手电", "text_norm": "重点讲扁桶手电", "text_final": "重点讲扁桶手电", "corrections": []},
                {"index": 3, "start": 34.0, "end": 38.0, "text_raw": "最后总结", "text_norm": "最后总结", "text_final": "最后总结", "corrections": []},
            ]
        ),
    )

    assert len(videos) == 3
    assert [item.path.name for item in videos] == ["preview_1.mp4", "preview_2.mp4", "preview_3.mp4"]
    assert all("预览" in item.caption for item in videos)
    assert all("packaged.mp4" not in item.caption for item in videos)


@pytest.mark.asyncio
async def test_handle_update_dispatches_final_review_callback(monkeypatch):
    service = TelegramReviewBotService()
    job_id = uuid.uuid4()
    handled: list[tuple[uuid.UUID, str, str]] = []
    answered: list[tuple[str, str]] = []

    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_remote_review_enabled=False,
            telegram_bot_chat_id="123",
            telegram_bot_token="token",
            telegram_bot_api_base_url="https://api.telegram.org",
        ),
    )

    async def fake_handle(job_id_value: uuid.UUID, text: str, *, reply_chat_id: str = ""):
        handled.append((job_id_value, text, reply_chat_id))

    async def fake_answer(callback_query_id: str, *, text: str = ""):
        answered.append((callback_query_id, text))

    service._handle_final_review_reply = fake_handle
    service._answer_callback_query = fake_answer

    await service._handle_update(
        {
            "callback_query": {
                "id": "cb-1",
                "data": _build_review_callback_data("final_review", job_id, "music"),
                "message": {"chat": {"id": "123"}},
            }
        }
    )

    assert answered == [("cb-1", "已接收 BGM 重出")]
    assert handled == [(job_id, "只改BGM", "123")]


@pytest.mark.asyncio
async def test_handle_final_review_reply_marks_step_done(db_engine):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final.mp4",
                source_name="final.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="final_review", status="pending"))
        await session.commit()

    await service._handle_final_review_reply(job_id, "通过", reply_chat_id="123")

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        step = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()

        assert job.status == "processing"
        assert step.status == "done"
        assert "成片已人工审核通过" in str((step.metadata_ or {}).get("detail") or "")

    assert sent == [f"已确认任务 {job_id} 的成片，系统继续后续流程。"]


@pytest.mark.asyncio
async def test_handle_final_review_reply_applies_subtitle_actions_and_stays_paused(db_engine, monkeypatch):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()
    applied_requests: list[list[tuple[str, str, str | None]]] = []

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    async def fake_apply_review(job_id_value, request, session):
        applied_requests.append(
            [
                (str(action.target_id), action.action, action.override_text)
                for action in request.actions
            ]
        )
        return {"applied": len(request.actions)}

    monkeypatch.setattr(telegram_bot, "_interpret_subtitle_review_reply", AsyncMock(return_value=[
        {"correction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "action": "accepted", "override_text": "Olight"},
    ]))
    import roughcut.api.jobs as jobs_api
    monkeypatch.setattr(jobs_api, "apply_review", fake_apply_review)
    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final.mp4",
                source_name="final.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="final_review", status="pending"))
        await session.commit()

    monkeypatch.setattr(
        telegram_bot,
        "generate_report",
        AsyncMock(
            return_value=SimpleNamespace(
                items=[
                    {
                        "index": 1,
                        "start": 2.0,
                        "end": 4.0,
                        "text_raw": "olight 开箱",
                        "text_norm": "olight 开箱",
                        "text_final": "olight 开箱",
                        "corrections": [
                            {
                                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                                "original": "olight",
                                "suggested": "Olight",
                                "type": "term",
                                "confidence": 0.7,
                                "source": "glossary",
                                "decision": None,
                            }
                        ],
                    }
                ]
            )
        ),
    )

    await service._handle_final_review_reply(job_id, "S1改成 Olight", reply_chat_id="123")

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        step = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()

        assert job.status == "needs_review"
        assert step.status == "pending"
        assert "已应用 1 条字幕审核意见" in str((step.metadata_ or {}).get("detail") or "")

    assert applied_requests == [[("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "accepted", "Olight")]]
    assert sent == [f"已应用任务 {job_id} 的 1 条字幕审核意见；当前成片仍保持暂停。确认无误后可直接回复“成片通过”继续。"]


@pytest.mark.asyncio
async def test_handle_subtitle_reply_applies_full_review_line_updates_without_candidates(db_engine):
    from roughcut.db.models import Job, SubtitleItem
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(
            SubtitleItem(
                id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                job_id=job_id,
                item_index=0,
                start_time=0.0,
                end_time=1.5,
                text_raw="鸿福工业",
                text_norm="鸿福工业",
                text_final="鸿福工业",
            )
        )
        await session.commit()

    await service._handle_subtitle_reply(job_id, "L1改成 狐蝠工业", reply_chat_id="123")

    async with get_session_factory()() as session:
        item = await session.get(SubtitleItem, uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
        assert item is not None
        assert item.text_final == "狐蝠工业"

    assert sent == [f"已应用任务 {job_id} 的 1 条全量字幕人工复核修改。"]


@pytest.mark.asyncio
async def test_handle_final_review_reply_applies_subtitle_actions_and_passes(db_engine, monkeypatch):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    async def fake_apply_review(job_id_value, request, session):
        return {"applied": len(request.actions)}

    monkeypatch.setattr(telegram_bot, "_interpret_subtitle_review_reply", AsyncMock(return_value=[
        {"correction_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "action": "accepted"},
    ]))
    import roughcut.api.jobs as jobs_api
    monkeypatch.setattr(jobs_api, "apply_review", fake_apply_review)
    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final.mp4",
                source_name="final.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="final_review", status="pending"))
        await session.commit()

    monkeypatch.setattr(
        telegram_bot,
        "generate_report",
        AsyncMock(
            return_value=SimpleNamespace(
                items=[
                    {
                        "index": 1,
                        "start": 2.0,
                        "end": 4.0,
                        "text_raw": "字幕",
                        "text_norm": "字幕",
                        "text_final": "字幕",
                        "corrections": [
                            {
                                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                                "original": "旧词",
                                "suggested": "新词",
                                "type": "term",
                                "confidence": 0.7,
                                "source": "glossary",
                                "decision": None,
                            }
                        ],
                    }
                ]
            )
        ),
    )

    await service._handle_final_review_reply(job_id, "S1通过，成片通过", reply_chat_id="123")

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        step = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()

        assert job.status == "processing"
        assert step.status == "done"

    assert sent == [f"已应用任务 {job_id} 的 1 条字幕审核意见，并确认成片通过，系统继续后续流程。"]


@pytest.mark.asyncio
async def test_handle_final_review_reply_triggers_structured_rerun(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final.mp4",
                source_name="final.mp4",
                status="needs_review",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            session.add(step)
        final_review_step = (
            await session.execute(
                telegram_bot.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "final_review",
                )
            )
        ).scalar_one()
        final_review_step.status = "pending"
        await session.commit()

    await service._handle_final_review_reply(job_id, "数字人口播不自然，重跑数字人", reply_chat_id="123")

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

        assert job.status == "processing"
        assert step_map["avatar_commentary"].status == "pending"
        assert step_map["edit_plan"].status == "pending"
        assert step_map["render"].status == "pending"
        assert step_map["final_review"].status == "pending"
        assert "人工成片审核要求重跑：数字人解说重做" in str((step_map["avatar_commentary"].metadata_ or {}).get("detail") or "")

    assert sent == [
        f"已记录任务 {job_id} 的成片修改意见，目标：avatar；并按“数字人解说重做”触发重跑：avatar_commentary -> edit_plan -> render -> final_review -> platform_package。"
    ]


@pytest.mark.asyncio
async def test_handle_final_review_reply_triggers_platform_package_only_rerun(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    service = TelegramReviewBotService()
    sent: list[str] = []
    job_id = uuid.uuid4()

    async def fake_send_text(text: str, *, chat_id: str) -> None:
        sent.append(text)

    service._send_chat_text = fake_send_text

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final.mp4",
                source_name="final.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            session.add(step)
        final_review_step = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()
        final_review_step.status = "pending"
        await session.commit()

    await service._handle_final_review_reply(job_id, "发布标题和话题标签重写一下", reply_chat_id="123")

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(
                telegram_bot.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

        assert job.status == "processing"
        assert step_map["platform_package"].status == "pending"
        assert step_map["render"].status == "done"
        assert step_map["final_review"].status == "pending"
        assert "平台文案与发布文案重出" in str((step_map["platform_package"].metadata_ or {}).get("detail") or "")

    assert sent == [
        f"已记录任务 {job_id} 的成片修改意见，目标：publish_copy, hashtags, platform_copy；并按“平台文案与发布文案重出”触发重跑：platform_package。"
    ]

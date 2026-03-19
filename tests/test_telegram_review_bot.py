from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import roughcut.review.telegram_bot as telegram_bot
from roughcut.review.telegram_bot import (
    TelegramReviewBotService,
    _build_content_profile_review_message,
    _build_pending_subtitle_candidates,
    _extract_review_reference,
    _interpret_content_profile_reply,
    _interpret_subtitle_review_reply,
    _split_review_message,
)


def test_extract_review_reference_reads_embedded_token():
    job_id = uuid.uuid4()

    result = _extract_review_reference(f"【RC:content_profile:{job_id}】\n请审核")

    assert result == ("content_profile", job_id)


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
                "corrections": [
                    {"id": "a", "original": "原词", "suggested": "新词", "type": "term", "confidence": 0.9, "source": "glossary", "decision": None},
                    {"id": "b", "original": "旧词", "suggested": "新词2", "type": "term", "confidence": 0.7, "source": "glossary", "decision": "accepted"},
                ],
            },
            {
                "index": 2,
                "corrections": [
                    {"id": "c", "original": "错别字", "suggested": "正字", "type": "subtitle", "confidence": 0.8, "source": "memory", "decision": None},
                ],
            },
        ]
    )

    candidates = _build_pending_subtitle_candidates(report)

    assert [item.slot for item in candidates] == ["S1", "S2"]
    assert [item.correction_id for item in candidates] == ["a", "c"]


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


def test_telegram_agent_enabled_without_chat_id():
    settings = SimpleNamespace(
        telegram_agent_enabled=True,
        telegram_remote_review_enabled=False,
        telegram_bot_token="token",
        telegram_bot_chat_id="",
    )

    assert telegram_bot._telegram_ready(settings) is True


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

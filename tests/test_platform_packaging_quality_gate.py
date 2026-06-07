from __future__ import annotations

import asyncio
import json

import pytest

from roughcut.review import platform_copy
from roughcut.review.platform_body_quality import assess_platform_body
from roughcut.packaging import library as packaging_library


def _valid_packaging() -> dict:
    platforms = {}
    for key, _label, _body_label, _tag_label in platform_copy.PLATFORM_ORDER:
        platforms[key] = {
            "titles": [
                "MOT 风灵音叉开箱先看声音细节",
                "MOT 风灵音叉上手后值不值",
                "MOT 风灵音叉这次做工怎么看",
            ],
            "description": "MOT 风灵音叉这次主要看开箱后的声音、握持和近景细节，上手那一下的质感比单看照片更直观。",
            "tags": ["MOT风灵音叉", "音叉推牌", "EDC开箱"],
        }
    return {
        "highlights": {
            "product": "MOT 风灵音叉",
            "video_type": "开箱上手",
            "strongest_selling_point": "声音、细节、做工",
            "strongest_emotion": "真实上手",
            "title_hook": "先看声音细节",
            "engagement_question": "你会怎么选？",
        },
        "platforms": platforms,
    }


def test_platform_packaging_quality_gate_accepts_specific_creator_copy() -> None:
    assessment = platform_copy._assess_platform_packaging_candidate(
        _valid_packaging(),
        content_profile={
            "subject_model": "MOT 风灵音叉",
            "subject_type": "音叉推牌",
            "video_theme": "开箱上手",
        },
        fact_sheet={"status": "unverified"},
    )

    assert assessment["publish_ready"] is True


def test_build_platform_claim_evidence_pack_keeps_creative_brief_out_of_hard_evidence() -> None:
    prompt_brief = platform_copy.build_packaging_prompt_brief(
        source_name="MAXACE 美杜莎4 顶配次顶配开箱.mp4",
        content_profile={
            "subject_brand": "MAXACE",
            "subject_model": "美杜莎4",
            "subject_type": "EDC跳刀",
            "summary": "这条摘要只是创作提示，不该当事实。",
            "hook_line": "开箱先看双版本差异",
            "visible_text": "MAXACE 美杜莎4",
        },
        subtitle_items=[{"text_final": "因为我之前没玩过直跳吧", "start_time": 0.0, "end_time": 1.0}],
    )

    evidence_pack = platform_copy._build_platform_claim_evidence_pack(
        source_name="MAXACE 美杜莎4 顶配次顶配开箱.mp4",
        prompt_brief=prompt_brief,
        fact_sheet={"verified_facts": [], "guardrail_summary": ""},
        subtitle_items=[{"text_final": "因为我之前没玩过直跳吧", "start_time": 0.0, "end_time": 1.0}],
        content_profile={"subject_brand": "MAXACE", "subject_model": "美杜莎4", "subject_type": "EDC跳刀"},
    )

    assert evidence_pack["source_hints"]["subject_type"] == "EDC跳刀"
    assert "summary" not in evidence_pack["source_hints"]
    assert evidence_pack["creative_brief"]["summary"] == "这条摘要只是创作提示，不该当事实。"
    prompt = platform_copy._build_claim_ledger_prompt(evidence_pack)
    assert "creative_brief 只是创作提示" in prompt


def test_claim_grounded_is_the_only_supported_claim_strategy_name() -> None:
    assert "claim_grounded" in packaging_library.COPY_STYLE_OPTIONS
    assert "m27_claim_grounded" not in packaging_library.COPY_STYLE_OPTIONS
    assert "m2_7_claim_grounded" not in packaging_library.COPY_STYLE_OPTIONS


@pytest.mark.asyncio
async def test_generate_platform_packaging_old_claim_style_name_no_longer_routes_to_claim_grounded(monkeypatch) -> None:
    async def fake_build_fact_sheet(**_kwargs):
        return {"status": "unverified", "verified_facts": []}

    async def fake_generate_with_repair(*_args, **_kwargs):
        return _valid_packaging(), []

    async def fake_claim_grounded(**_kwargs):
        raise AssertionError("old style name should not route to claim_grounded")

    monkeypatch.setattr(platform_copy, "build_packaging_fact_sheet", fake_build_fact_sheet)
    monkeypatch.setattr(platform_copy, "_generate_platform_packaging_with_repair", fake_generate_with_repair)
    monkeypatch.setattr(platform_copy, "_generate_claim_grounded_platform_packaging", fake_claim_grounded)

    result = await platform_copy.generate_platform_packaging(
        source_name="demo.mp4",
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        subtitle_items=[{"text_final": "开箱上手"}],
        copy_style="m27_claim_grounded",
        prompt_brief={"source_language": "zh", "transcript_excerpt": "开箱上手"},
    )

    assert "title_audit" in result


@pytest.mark.asyncio
async def test_generate_platform_packaging_with_repair_salvages_malformed_json(monkeypatch) -> None:
    valid_payload = {
        "highlights": {
            "product": "MOT 风灵音叉",
            "video_type": "开箱上手",
            "strongest_selling_point": "声音、细节、做工",
            "strongest_emotion": "真实上手",
            "title_hook": "先看声音细节",
            "engagement_question": "你会怎么选？",
        },
        "platforms": {
            "bilibili": {
                "titles": [
                    "MOT 风灵音叉开箱先看声音细节",
                    "MOT 风灵音叉上手后值不值",
                    "MOT 风灵音叉这次做工怎么看",
                ],
                "description": "MOT 风灵音叉这次主要看开箱后的声音、握持和近景细节，上手那一下的质感比单看照片更直观。",
                "tags": ["MOT风灵音叉", "音叉推牌", "EDC开箱"],
            }
        },
    }
    malformed_json = json.dumps(valid_payload, ensure_ascii=False).replace('"description"', '"description"', 1)[:-1]

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, temperature=0.3, max_tokens=4096, json_mode=False):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(malformed_json)
            return FakeResponse(json.dumps(valid_payload, ensure_ascii=False))

    provider = FakeProvider()
    monkeypatch.setattr(platform_copy, "get_reasoning_provider", lambda: provider)
    monkeypatch.setattr(platform_copy, "normalize_platform_packaging", lambda payload, **_kwargs: payload)
    monkeypatch.setattr(
        platform_copy,
        "_assess_platform_packaging_quality",
        lambda *args, **kwargs: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "repair_hints": [],
        },
    )

    payload, trace = await platform_copy._generate_platform_packaging_with_repair(
        "只返回 JSON。",
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        fact_sheet={"status": "unverified"},
        copy_style="attention_grabbing",
        author_profile=None,
        target_platforms=["bilibili"],
    )

    assert payload["platforms"]["bilibili"]["titles"][0] == "MOT 风灵音叉开箱先看声音细节"
    assert trace == [{"attempt": 1, "status": "ok", "issues": [], "warnings": [], "repair_hints": []}]
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_complete_json_with_same_model_repair_shares_one_timeout_budget(monkeypatch) -> None:
    valid_payload = {
        "highlights": {"product": "MOT 风灵音叉"},
        "platforms": {"bilibili": {"titles": ["A", "B", "C"], "description": "desc", "tags": ["t1", "t2"]}},
    }

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, temperature=0.3, max_tokens=4096, json_mode=False):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse("{")
            return FakeResponse(json.dumps(valid_payload, ensure_ascii=False))

    timeout_calls: list[int] = []
    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout=None):
        timeout_calls.append(int(timeout or 0))
        return await real_wait_for(awaitable, timeout=0.1)

    monkeypatch.setattr(platform_copy, "get_reasoning_provider", lambda: FakeProvider())
    monkeypatch.setattr(platform_copy.asyncio, "wait_for", fake_wait_for)

    payload = await platform_copy._complete_json_with_same_model_repair(
        [platform_copy.Message(role="user", content="只返回 JSON")],
        temperature=0.3,
        max_tokens=512,
        timeout=30,
        schema_hint='{"platforms":{"bilibili":{"titles":[""],"description":"","tags":[""]}}}',
    )

    assert payload["platforms"]["bilibili"]["titles"][0] == "A"
    assert len(timeout_calls) == 2
    assert timeout_calls[0] == 30
    assert timeout_calls[1] <= timeout_calls[0]


@pytest.mark.asyncio
async def test_generate_platform_packaging_with_repair_shares_one_timeout_budget_across_attempts(monkeypatch) -> None:
    captured_timeouts: list[int] = []

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter([0.0, 0.0, 20.0, 29.0])

        def time(self) -> float:
            return next(self._times)

    async def fake_complete(*_args, **kwargs):
        captured_timeouts.append(int(kwargs["timeout"]))
        raise asyncio.TimeoutError()

    monkeypatch.setattr(platform_copy, "_resolve_platform_packaging_generation_timeout", lambda: 30)
    monkeypatch.setattr(platform_copy.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_copy, "_complete_json_with_same_model_repair", fake_complete)

    with pytest.raises(RuntimeError, match="第 3 次文案包装生成超时（>1s）"):
        await platform_copy._generate_platform_packaging_with_repair(
            "只返回 JSON。",
            content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
            fact_sheet={"status": "unverified"},
            copy_style="attention_grabbing",
            author_profile=None,
            target_platforms=["bilibili"],
        )

    assert captured_timeouts == [30, 10, 1]


def test_resolve_platform_packaging_generation_timeout_uses_longer_window_for_minimax_m3(monkeypatch) -> None:
    monkeypatch.setattr(
        platform_copy,
        "get_settings",
        lambda: type("S", (), {"active_reasoning_provider": "minimax", "active_reasoning_model": "MiniMax-M3"})(),
    )

    assert platform_copy._resolve_platform_packaging_generation_timeout() == 90


def test_resolve_platform_packaging_generation_max_tokens_scales_by_target_count() -> None:
    assert platform_copy._resolve_platform_packaging_generation_max_tokens(["bilibili"]) == 1200
    assert platform_copy._resolve_platform_packaging_generation_max_tokens(["bilibili", "douyin"]) == 2400
    assert platform_copy._resolve_platform_packaging_generation_max_tokens(None) == 4000


@pytest.mark.asyncio
async def test_generate_platform_packaging_with_repair_reports_timeout_clearly(monkeypatch) -> None:
    class TimeoutProvider:
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise asyncio.TimeoutError()

    monkeypatch.setattr(platform_copy, "get_reasoning_provider", lambda: TimeoutProvider())
    monkeypatch.setattr(platform_copy, "get_settings", lambda: type("S", (), {"active_reasoning_provider": "minimax", "active_reasoning_model": "MiniMax-M3"})())

    with pytest.raises(RuntimeError, match="第 3 次文案包装生成超时（>90s）"):
        await platform_copy._generate_platform_packaging_with_repair(
            "只返回 JSON。",
            content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
            fact_sheet={"status": "unverified"},
            copy_style="attention_grabbing",
            author_profile=None,
            target_platforms=["bilibili"],
        )


@pytest.mark.asyncio
async def test_generate_platform_packaging_falls_back_to_deterministic_copy_on_runtime_failure(monkeypatch) -> None:
    async def fake_generate_single_platform_fast(*_args, **_kwargs):
        raise RuntimeError("第 1 次文案包装生成超时（>1s）")

    monkeypatch.setattr(platform_copy, "_generate_single_platform_packaging_fast", fake_generate_single_platform_fast)

    result = await platform_copy.generate_platform_packaging(
        source_name="MAXACE 美杜莎4 顶配次顶配开箱.mp4",
        content_profile={
            "subject_brand": "MAXACE",
            "subject_model": "美杜莎4",
            "subject_type": "EDC跳刀",
            "video_theme": "双版本开箱",
            "summary": "这次把顶配和次顶配放在一起开箱。",
        },
        subtitle_items=[{"text_final": "这次把顶配和次顶配放在一起开箱", "start_time": 0.0, "end_time": 1.0}],
        copy_style="attention_grabbing",
        prompt_brief={
            "source_language": "zh",
            "transcript_excerpt": "这次把顶配和次顶配放在一起开箱",
            "video_theme": "双版本开箱",
            "copy_brief": {
                "intent": "comparison_unboxing",
                "topic_subject": "MAXACE美杜莎4",
                "summary": "这次把顶配和次顶配放在一起开箱。",
                "question": "",
                "focus_points": ["版本差异", "外观细节", "上手感受"],
            },
        },
        fact_sheet={"status": "unverified", "verified_facts": []},
        target_platforms=["bilibili"],
    )

    bilibili = result["platforms"]["bilibili"]
    assert len(bilibili["titles"]) >= 3
    assert bilibili["description"]
    assert len(bilibili["tags"]) >= 2
    assert result["generation_repair_trace"][0]["status"] == "deterministic_fallback"


def test_platform_packaging_quality_gate_rejects_ai_fallback_copy() -> None:
    payload = _valid_packaging()
    payload["platforms"]["douyin"]["description"] = "这条视频主要围绕 MOT 风灵音叉展开，建议发布前人工核对具体型号与参数。"

    assessment = platform_copy._assess_platform_packaging_candidate(
        payload,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        fact_sheet={"status": "unverified"},
    )

    assert assessment["publish_ready"] is False
    assert any("抖音正文" in reason for reason in assessment["blocking_reasons"])
    assert any("兜底" in hint or "现场观察" in hint for hint in assessment["repair_hints"])


def test_platform_packaging_publishable_raises_on_low_quality_copy() -> None:
    payload = _valid_packaging()
    payload["platforms"]["xiaohongshu"]["titles"] = ["先看细节", "真实体验", "这条视频会怎么发"]
    normalized = platform_copy._normalize_generated_platform_packaging_strict(
        payload,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
    )

    with pytest.raises(RuntimeError, match="文案模型输出质量不达标"):
        platform_copy._assert_platform_packaging_publishable(
            normalized,
            content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
            fact_sheet={"status": "unverified"},
        )


def test_platform_packaging_hardening_does_not_replace_llm_copy() -> None:
    content_profile = {
        "subject_brand": "MOT",
        "subject_model": "风灵音叉推牌",
        "subject_type": "锆合金版本",
        "video_theme": "开箱上手",
    }
    raw = _valid_packaging()
    for key in raw["platforms"]:
        raw["platforms"][key]["titles"] = ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
        raw["platforms"][key]["description"] = "今天回到老本行，第一眼先看细节，建议发布前人工核对具体型号。"

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    hardened = platform_copy._harden_platform_packaging_for_publish(
        normalized,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    assert hardened["platforms"]["xiaohongshu"]["titles"] == ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
    assert all("第一" not in platform["description"] for platform in hardened["platforms"].values())
    assert any(
        platform_copy._assess_platform_packaging_quality(
            hardened,
            content_profile=content_profile,
            fact_sheet={"status": "unverified"},
        )["blocking_reasons"]
    )


def test_normalize_ignores_polluted_subject_anchor_without_synthesizing_copy() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本，建议发布前人工核对具体型号与参数。",
        "subject_type": "音叉推牌",
        "video_theme": "开箱上手",
    }
    raw = _valid_packaging()
    for key in raw["platforms"]:
        raw["platforms"][key]["titles"] = ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
        raw["platforms"][key]["description"] = "MOT 风灵音叉推牌这次主要看开箱、声音和近景细节，到手后的质感比较直观。"

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    assessment = platform_copy._assess_platform_packaging_quality(
        normalized,
        content_profile=content_profile,
        fact_sheet={"status": "unverified"},
    )

    assert not any("人工核对" in reason for reason in assessment["blocking_reasons"])
    assert normalized["platforms"]["xiaohongshu"]["titles"] == ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]


def test_normalize_keeps_bad_titles_for_quality_gate_instead_of_forcing_safe_titles() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本",
        "subject_type": "锆合金版本",
    }
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["titles"] = ["产品细节先看", "产品开箱体验", "产品到手记录"]
    raw["platforms"]["wechat_channels"]["titles"] = ["产品开箱体验", "产品细节总结", "产品到手记录"]

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )

    assert platform_copy._assess_platform_packaging_quality(
        normalized,
        content_profile=content_profile,
        fact_sheet={"status": "unverified"},
    )["blocking_reasons"]


def test_compact_product_label_truncates_model_before_generic_subject() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本",
        "subject_type": "产品",
    }

    label = platform_copy._compact_product_label(content_profile, label="视频号")

    assert "产品" not in label
    assert "MOT" in label


def test_strict_normalization_caps_titles_to_three() -> None:
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["titles"] = [
        "MOT 风灵音叉到手值不值",
        "MOT 风灵音叉声音细节实拍",
        "MOT 风灵音叉做工怎么选",
        "MOT 风灵音叉第四条不该保留",
        "MOT 风灵音叉第五条不该保留",
    ]

    normalized = platform_copy._normalize_generated_platform_packaging_strict(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
    )

    assert normalized["platforms"]["xiaohongshu"]["titles"] == [
        "MOT 风灵音叉到手值不值",
        "MOT 风灵音叉声音细节实拍",
        "MOT 风灵音叉做工怎么选",
    ]


def test_fact_guardrail_does_not_synthesize_replacement_copy() -> None:
    raw = _valid_packaging()
    raw["highlights"]["title_hook"] = "续航提升 100%"
    raw["platforms"]["xiaohongshu"]["titles"] = [
        "MOT 风灵音叉续航提升 100%",
        "MOT 风灵音叉价格贵一倍",
        "MOT 风灵音叉到手值不值",
    ]
    raw["platforms"]["xiaohongshu"]["description"] = "MOT 风灵音叉这次续航提升 100%，价格也贵一倍。"

    guarded = platform_copy._enforce_packaging_fact_guardrails(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified", "verified_facts": []},
    )

    assert guarded["highlights"]["title_hook"] == ""
    assert guarded["platforms"]["xiaohongshu"]["titles"] == ["MOT 风灵音叉到手值不值"]
    assert guarded["platforms"]["xiaohongshu"]["description"] == ""


def test_description_variation_gate_does_not_synthesize_replacements() -> None:
    raw = _valid_packaging()
    duplicate = "MOT 风灵音叉这次看声音、握持和近景细节，上手质感比单看照片更直观。"
    raw["platforms"]["xiaohongshu"]["description"] = duplicate
    raw["platforms"]["douyin"]["description"] = duplicate

    varied = platform_copy._enforce_platform_description_variation(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        author_profile=None,
    )

    assert varied["platforms"]["xiaohongshu"]["description"] == duplicate
    assert varied["platforms"]["douyin"]["description"] == duplicate


def test_body_quality_allows_first_impression_context() -> None:
    result = assess_platform_body(
        "xiaohongshu",
        "MOT 风灵音叉推牌锆合金版本到手，第一眼先看做工和外观，细节、手感和近景质感都按实拍来聊。",
        content_profile={"subject_model": "MOT 风灵音叉推牌锆合金版本"},
        fact_sheet={"status": "unverified"},
    )

    assert result["publish_ready"] is True
    assert not any("第一" in reason for reason in result["blocking_reasons"])


def test_body_quality_accepts_english_platform_anchor_tokens() -> None:
    result = assess_platform_body(
        "youtube",
        "A hands-on look at the MOT Fengling Zirconium Alloy version, focusing on build quality, version differences, and real handling impressions.",
        content_profile={"subject_model": "MOT 风灵音叉推牌 锆合金版本"},
        fact_sheet={"status": "unverified"},
    )

    assert result["publish_ready"] is True
    assert not any("主体锚点" in reason for reason in result["blocking_reasons"])
    assert not any("体验细节" in reason for reason in result["blocking_reasons"])


def test_source_language_instruction_blocks_implicit_youtube_translation() -> None:
    instruction = platform_copy._build_source_language_instruction("zh-CN")

    assert "所有平台" in instruction
    assert "YouTube" in instruction
    assert "不能" in instruction
    assert "英文" in instruction


def test_normalize_does_not_backfill_missing_description() -> None:
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["description"] = ""

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )

    assert normalized["platforms"]["xiaohongshu"]["description"] == ""


def test_normalize_preserves_platform_publication_metadata() -> None:
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"].update(
        {
            "cover_path": "D:/material/smart-copy/02-xiaohongshu-cover.jpg",
            "declaration": "原创声明",
            "collection_name": "FAS EDC 装备",
            "visibility_or_publish_mode": "draft",
            "scheduled_publish_at": "2026-06-01T21:00",
            "copy_material": {"source": "platform_packaging", "primary_title": "真实生成标题"},
        }
    )

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )

    xhs = normalized["platforms"]["xiaohongshu"]
    assert xhs["cover_path"] == "D:/material/smart-copy/02-xiaohongshu-cover.jpg"
    assert xhs["declaration"] == "原创声明"
    assert xhs["collection_name"] == "FAS EDC 装备"
    assert xhs["visibility_or_publish_mode"] == "draft"
    assert xhs["scheduled_publish_at"] == "2026-06-01T21:00"
    assert xhs["copy_material"]["primary_title"] == "真实生成标题"


def test_claim_grounded_untraced_spans_require_repair() -> None:
    draft = {
        "highlights": {"title_hook": {"text": "年前最后一抽三连跪", "claim_refs": []}},
        "platforms": {
            "bilibili": {
                "titles": [{"text": "NOC 盲盒三连跪", "claim_refs": []}],
                "description": [{"text": "最近 NOC 发售难度上升。", "claim_refs": ["c1"]}],
                "tags": [{"text": "NOC", "claim_refs": ["c2"]}],
            }
        },
    }

    issues = platform_copy._find_untraced_claim_grounded_spans(draft)
    locations = {item["location"] for item in issues}

    assert {"highlights.title_hook", "bilibili.titles[0]", "bilibili.titles"} <= locations
    assert "douyin" in locations


def test_claim_grounded_strip_claim_refs_preserves_existing_packaging_shape() -> None:
    draft = {
        "highlights": {
            "product": {"text": "NOC MT34", "claim_refs": ["c1"]},
            "video_type": {"text": "开箱记录", "claim_refs": ["c2"]},
            "title_hook": {"text": "NOC MT34 到手真难抢", "claim_refs": ["c1", "c3"]},
            "engagement_question": {"text": "你最近抢新品也觉得难吗？", "claim_refs": ["c3"]},
        },
        "platforms": {
            "bilibili": {
                "titles": [
                    {"text": "NOC MT34 到手：抢购难度上来了", "claim_refs": ["c1", "c3"]},
                    {"text": "年前最后一款 NOC 小玩具", "claim_refs": ["c1"]},
                    {"text": "NOC 发售体验记录", "claim_refs": ["c3"]},
                ],
                "description": [
                    {"text": "这次主要记录 NOC MT34 到手和发售难抢的体验。", "claim_refs": ["c1", "c3"]},
                    {"text": "不补参数，只聊视频里能确认的内容。", "claim_refs": ["c2"]},
                ],
                "tags": [{"text": "NOC", "claim_refs": ["c1"]}, {"text": "MT34", "claim_refs": ["c1"]}],
            }
        },
    }

    stripped = platform_copy._strip_claim_refs_from_packaging(draft)

    assert stripped["highlights"]["product"] == "NOC MT34"
    assert stripped["platforms"]["bilibili"]["titles"][0] == "NOC MT34 到手：抢购难度上来了"
    assert stripped["platforms"]["bilibili"]["description"] == (
        "这次主要记录 NOC MT34 到手和发售难抢的体验。\n"
        "不补参数，只聊视频里能确认的内容。"
    )
    assert stripped["platforms"]["bilibili"]["tags"] == ["NOC", "MT34"]


def test_claim_entailment_audit_normalization_forces_repair_when_unsupported_exists() -> None:
    audit = platform_copy._normalize_claim_entailment_audit(
        {
            "verdict": "pass",
            "unsupported": [
                {
                    "location": "douyin.titles[0]",
                    "unsupported_span": "三连跪",
                    "verdict": "unsupported",
                    "reason": "claim ledger only supports 抢购难度上升, not repeated failure.",
                    "allowed_repair": "改为“难抢”",
                }
            ],
        }
    )

    assert audit["verdict"] == "repair_required"
    assert platform_copy._claim_grounding_audit_passes(audit) is False
    assert audit["unsupported"][0]["unsupported_span"] == "三连跪"


def test_claim_ledger_normalization_keeps_disallowed_inferences() -> None:
    ledger = platform_copy._normalize_claim_ledger(
        {
            "claims": [
                {"claim_id": "c1", "claim": "作者收到了年前最后一款 NOC 小玩具", "evidence_ids": ["sub_1"]},
                {"claim_id": "c1", "claim": "作者认为抢购难度上升", "evidence_ids": ["sub_5"]},
            ],
            "disallowed_inferences": [{"claim": "这是盲盒", "reason": "证据未出现盲盒品类"}],
        }
    )

    assert [item["claim_id"] for item in ledger["claims"]] == ["c1", "c2"]
    assert ledger["disallowed_inferences"] == [{"claim": "这是盲盒", "reason": "证据未出现盲盒品类"}]


def test_claim_grounded_single_platform_normalizer_accepts_nested_chinese_fields() -> None:
    normalized = platform_copy._normalize_single_platform_claim_draft(
        "bilibili",
        {
            "result": {
                "bilibili": {
                    "标题": [
                        {"title": "NOC MT34 到手记录", "claim_refs": ["c1"]},
                        {"text": "年前最后一款 NOC 小玩具", "claim_refs": ["c1"]},
                        {"text": "NOC 发售难度上来了", "claim_refs": ["c2"]},
                    ],
                    "正文": [{"content": "这次记录 NOC MT34 到手和发售难度变化。", "claim_refs": ["c1", "c2"]}],
                    "话题": [{"tag": "NOC", "claim_refs": ["c1"]}, {"text": "MT34", "claim_refs": ["c1"]}],
                }
            }
        },
    )

    assert [item["text"] for item in normalized["titles"]] == [
        "NOC MT34 到手记录",
        "年前最后一款 NOC 小玩具",
        "NOC 发售难度上来了",
    ]
    assert normalized["description"][0]["text"] == "这次记录 NOC MT34 到手和发售难度变化。"
    assert [item["text"] for item in normalized["tags"]] == ["NOC", "MT34"]


def test_claim_ledger_is_merged_into_fact_sheet_for_guardrails() -> None:
    merged = platform_copy._merge_claim_ledger_into_fact_sheet(
        {"verified_facts": [], "guardrail_summary": "只用本地证据。"},
        {
            "claims": [
                {"claim_id": "c1", "claim": "作者收到了 NOC MT34", "evidence_ids": ["sub_1"]},
                {"claim_id": "c2", "claim": "作者认为发售难度上升", "evidence_ids": ["sub_5"]},
            ]
        },
    )

    facts = [item["fact"] for item in merged["verified_facts"]]
    assert facts == ["作者收到了 NOC MT34", "作者认为发售难度上升"]
    assert "claim ledger" in merged["guardrail_summary"]


def test_claim_ledger_semantic_invariants_reject_purchase_success_drift() -> None:
    issues = platform_copy._claim_ledger_semantic_invariant_issues(
        {
            "platforms": {
                "xiaohongshu": {
                    "titles": [{"text": "耗尽欧气才抢到的 NOC MT34", "claim_refs": ["c1", "c2"]}],
                    "description": [{"text": "最近这三次发售都太难了，抢先看 NOC MT34。", "claim_refs": ["c2"]}],
                    "tags": [{"text": "NOC", "claim_refs": ["c1"]}],
                }
            }
        },
        claim_ledger={
            "claims": [
                {"claim_id": "c1", "claim": "视频内容涉及 NOC MT34"},
                {"claim_id": "c2", "claim": "该产品的抢购环节存在一定难度"},
                {"claim_id": "c3", "claim": "该产品在视频发布前已通过某种方式获得"},
            ],
            "uncertain_claims": [{"claim": "具体是哪三次发售", "reason": "字幕未明确"}],
            "disallowed_inferences": [{"claim": "发售失败经历", "reason": "字幕未明确描述失败经历"}],
        },
    )

    reasons = "\n".join(item["reason"] for item in issues)
    assert "purchase_success" in reasons
    assert "release_count" in reasons
    assert "early_access" in reasons


def test_claim_ledger_semantic_invariants_allow_subjective_platform_expression() -> None:
    issues = platform_copy._claim_ledger_semantic_invariant_issues(
        {
            "platforms": {
                "xiaohongshu": {
                    "titles": [{"text": "NOC MT34 新品开箱，质感拉满手感绝了", "claim_refs": ["c1"]}],
                    "description": [{"text": "这次上手第一感觉很惊喜，主观体验很加分。", "claim_refs": ["c1"]}],
                    "tags": [{"text": "质感开箱", "claim_refs": ["c1"]}],
                }
            }
        },
        claim_ledger={
            "claims": [{"claim_id": "c1", "claim": "视频内容涉及 NOC MT34", "claim_type": "identity"}],
            "uncertain_claims": [],
            "disallowed_inferences": [{"claim": "产品具体参数", "reason": "证据未提供参数"}],
        },
    )

    assert issues == []


def test_unsupported_claim_grounded_highlights_are_removed() -> None:
    cleaned = platform_copy._remove_unsupported_claim_grounded_highlights(
        {
            "highlights": {
                "strongest_selling_point": {"text": "错过不再有，抢购难度爆表", "claim_refs": ["c1"]},
                "title_hook": {"text": "NOC MT34 到手了", "claim_refs": ["c1"]},
            },
            "platforms": {},
        },
        claim_ledger={"claims": [{"claim_id": "c1", "claim": "该产品的抢购环节存在一定难度"}]},
    )

    assert cleaned["highlights"]["strongest_selling_point"]["text"] == ""
    assert cleaned["highlights"]["title_hook"]["text"] == "NOC MT34 到手了"


def test_claim_text_extraction_accepts_reference_aliases() -> None:
    text, refs = platform_copy._extract_claim_text_and_refs({"text": "NOC MT34 到手", "claim_ids": ["c1", "c2"]})

    assert text == "NOC MT34 到手"
    assert refs == ["c1", "c2"]


def test_claim_grounded_title_anchor_is_added_from_subject_claim() -> None:
    anchored = platform_copy._enforce_claim_grounded_title_anchors(
        {
            "titles": [
                {"text": "终于到手了", "claim_refs": ["c2"]},
                {"text": "发售难度上来了", "claim_refs": ["c3"]},
                {"text": "NOC MT34 开箱记录", "claim_refs": ["c1"]},
            ],
            "description": [],
            "tags": [],
        },
        evidence_pack={"subject_identity": {"brand": "NOC", "model": "MT34"}},
        claim_ledger={"claims": [{"claim_id": "c1", "claim": "视频内容涉及 NOC 品牌 MT34 型号产品"}]},
    )

    assert anchored["titles"][0]["text"] == "NOC MT34 终于到手了"
    assert anchored["titles"][1]["text"] == "NOC MT34 发售难度上来了"
    assert "c1" in anchored["titles"][0]["claim_refs"]


def test_missing_claim_refs_are_backfilled_from_subject_claim() -> None:
    draft = platform_copy._backfill_missing_claim_refs_from_subject(
        {
            "titles": [{"text": "NOC MT34 开箱", "claim_refs": ["c2"]}],
            "description": [],
            "tags": [{"text": "折刀开箱", "claim_refs": []}],
        },
        evidence_pack={"subject_identity": {"brand": "NOC", "model": "MT34"}},
        claim_ledger={"claims": [{"claim_id": "c1", "claim": "视频中的EDC折刀品牌为NOC，型号为MT34"}]},
    )

    assert draft["titles"][0]["claim_refs"] == ["c2"]
    assert draft["tags"][0]["claim_refs"] == ["c1"]


def test_jsonish_loader_accepts_python_literal_object() -> None:
    payload = platform_copy._loads_jsonish_object("{'titles': [{'text': 'NOC MT34', 'claim_refs': ['c1']}]}")

    assert payload["titles"][0]["claim_refs"] == ["c1"]


def test_claim_grounded_title_count_is_completed_from_ledger_claims() -> None:
    completed = platform_copy._complete_claim_grounded_title_count(
        "bilibili",
        {"titles": [{"text": "NITECORE EDC17 开箱", "claim_refs": ["c1"]}], "description": [], "tags": []},
        evidence_pack={"subject_identity": {"brand": "NITECORE", "model": "EDC17"}},
        claim_ledger={
            "claims": [
                {"claim_id": "c1", "claim": "视频内容涉及 NITECORE EDC17"},
                {"claim_id": "c2", "claim": "EDC17 与 EDC37 有对比展示"},
                {"claim_id": "c3", "claim": "包装中出现电池和配件"},
            ]
        },
    )

    assert len(completed["titles"]) == 3
    assert completed["titles"][1]["claim_refs"]


def test_claim_grounded_draft_shape_coerces_platform_item_lists() -> None:
    coerced = platform_copy._coerce_claim_grounded_draft_shape(
        {
            "items": [
                {"platform": "B站", "titles": [{"text": "NOC MT34 开箱", "claim_refs": ["c1"]}]},
                {"platform": "小红书", "titles": [{"text": "NOC MT34 到手", "claim_refs": ["c1"]}]},
            ]
        },
        target_keys=["bilibili", "xiaohongshu"],
    )

    assert "bilibili" in coerced["platforms"]
    assert "xiaohongshu" in coerced["platforms"]


def test_claim_grounded_draft_text_count_detects_empty_repair() -> None:
    assert platform_copy._claim_grounded_draft_text_count({"platforms": {"bilibili": {"titles": []}}}) == 0
    assert (
        platform_copy._claim_grounded_draft_text_count(
            {"platforms": {"bilibili": {"titles": [{"text": "NOC MT34 开箱", "claim_refs": ["c1"]}]}}}
        )
        == 1
    )


def test_evidence_pack_adds_neutral_comparison_claim_from_source_name() -> None:
    ledger = platform_copy._augment_claim_ledger_with_evidence_pack_claims(
        {"claims": [{"claim_id": "c1", "claim": "视频内容涉及 EDC17", "claim_type": "identity"}]},
        evidence_pack={"source_name": "EDC17开箱以及和edc37的对比.mp4", "prompt_brief": {}},
    )

    assert ledger["claims"][-1]["claim_type"] == "comparison"
    assert "不得推出未支持的优劣结论" in ledger["claims"][-1]["allowed_usage"]

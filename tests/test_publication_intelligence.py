import pytest

from roughcut import publication_intelligence as intelligence


@pytest.mark.asyncio
async def test_generate_publication_scheme_does_not_invent_platform_collections(monkeypatch, tmp_path):
    async def _fake_research(targets):
        return {
            "content_key": intelligence._content_key(targets),
            "platform_slots": {"bilibili": [{"time": "19:30", "reason": "test slot"}]},
            "search_status": "fallback",
            "llm_status": "fallback",
        }

    async def _no_refine(scheme):
        return None

    async def _unavailable_inventory(**kwargs):
        return {"status": "unavailable", "source": "browser_agent_inventory", "platforms": {}}

    monkeypatch.setattr(intelligence, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(intelligence, "_research_time_strategy", _fake_research)
    monkeypatch.setattr(intelligence, "_probe_real_platform_inventory", _unavailable_inventory)
    monkeypatch.setattr(intelligence, "_refine_scheme_with_llm", _no_refine)
    monkeypatch.setattr(intelligence, "_next_local_datetime", lambda slot, day_offset=0: f"2026-05-22T{slot}")

    scheme = await intelligence.generate_publication_scheme(
        plan={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "targets": [
                {
                    "platform": "bilibili",
                    "platform_label": "B站",
                    "account_label": "FAS · Chrome",
                    "title": "EDC 装备评测",
                }
            ],
        },
        creator_profile={
            "id": "profile-1",
            "display_name": "FAS",
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "bilibili",
                            "account_label": "FAS · Chrome",
                            "credential_ref": "browser-agent:chrome:profile-1:bilibili",
                        }
                    ]
                }
            },
        },
        folder_path="D:/material",
        browser="chrome",
    )

    item = scheme["items"][0]
    assert item["collection_name"] == ""
    assert item["category"] == ""
    assert "collection_name" not in scheme["platform_options"]["bilibili"]
    assert "category" not in scheme["platform_options"]["bilibili"]
    assert scheme["probe"]["status"] == "login_reference_only"
    assert "尚未完成真实平台摸底" in item["probe_summary"]


@pytest.mark.asyncio
async def test_generate_publication_scheme_uses_real_inventory_only(monkeypatch, tmp_path):
    async def _fake_research(targets):
        return {
            "content_key": intelligence._content_key(targets),
            "platform_slots": {
                "bilibili": [{"time": "19:30", "reason": "test slot"}],
                "xiaohongshu": [{"time": "21:00", "reason": "test slot"}],
            },
            "search_status": "fallback",
            "llm_status": "fallback",
        }

    async def _fake_inventory(**kwargs):
        return {
            "status": "partial",
            "source": "browser_agent_inventory",
            "platforms": {
                "bilibili": {
                    "status": "partial",
                    "route": {"url": "https://member.bilibili.com/platform/upload/video/frame"},
                    "option_groups": [
                        {"key": "bilibili_sections", "label": "B站分区候选", "options": ["生活兴趣", "户外潮流", "生活/出行", "数码", "生活"]},
                        {"key": "collections", "label": "合集/系列", "options": ["MOT 风灵音叉推牌", "EDC 手电评测"]},
                    ],
                    "operation_steps": [{"label": "选择分区"}],
                },
                "xiaohongshu": {
                    "status": "partial",
                    "route": {"url": "https://creator.xiaohongshu.com/publish"},
                    "option_groups": [
                        {"key": "collections", "label": "加入合集", "options": ["FAS EDC 装备"]},
                        {"key": "declarations", "label": "原创声明", "options": ["原创声明", "内容包含营销广告"]},
                        {"key": "group_chats", "label": "选择群聊", "options": ["F.A.S EDC畅聊群"]},
                    ],
                    "operation_steps": [{"label": "展开内容设置"}],
                },
            },
        }

    async def _no_refine(scheme):
        return None

    monkeypatch.setattr(intelligence, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(intelligence, "_research_time_strategy", _fake_research)
    monkeypatch.setattr(intelligence, "_probe_real_platform_inventory", _fake_inventory)
    monkeypatch.setattr(intelligence, "_refine_scheme_with_llm", _no_refine)
    monkeypatch.setattr(intelligence, "_next_local_datetime", lambda slot, day_offset=0: f"2026-05-22T{slot}")

    scheme = await intelligence.generate_publication_scheme(
        plan={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "targets": [
                {"platform": "bilibili", "platform_label": "B站", "title": "EDC 户外手电评测"},
                {"platform": "xiaohongshu", "platform_label": "小红书", "title": "EDC 户外手电评测"},
            ],
        },
        creator_profile={"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        folder_path="D:/material",
        browser="chrome",
        force_probe=True,
    )

    bilibili = next(item for item in scheme["items"] if item["platform"] == "bilibili")
    xiaohongshu = next(item for item in scheme["items"] if item["platform"] == "xiaohongshu")
    assert bilibili["category"] == "生活兴趣/户外潮流"
    assert bilibili["collection_name"] == "MOT 风灵音叉推牌"
    assert scheme["platform_options"]["bilibili"]["category"] == "生活兴趣/户外潮流"
    assert scheme["platform_options"]["bilibili"]["platform_specific_overrides"]["category_selection_plan"][
        "category_path"
    ] == ["生活兴趣", "户外潮流"]
    assert xiaohongshu["collection_name"] == "FAS EDC 装备"
    assert xiaohongshu["selected_options"]["selected_declarations"] == ["原创声明"]
    assert xiaohongshu["selected_options"]["selected_group_chat"] == "F.A.S EDC畅聊群"
    assert scheme["platform_options"]["xiaohongshu"]["platform_specific_overrides"]["selected_group_chat"] == "F.A.S EDC畅聊群"


def test_choose_bilibili_category_falls_back_to_travel_when_current_api_lacks_old_outdoor_label():
    category = intelligence._choose_real_category(
        {"category_options": ["生活/出行", "科技/数码", "生活/手工"]},
        {"platform": "bilibili", "title": "MOT EDC 户外随身装备评测"},
    )

    assert category == "生活/出行"


def test_fas_bilibili_edc_toy_unboxing_prefers_outdoor_trend_category():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    category = intelligence._choose_real_category(
        {"category_options": ["生活兴趣", "时尚美妆", "家装房产", "户外潮流", "健身"]},
        {"platform": "bilibili", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert category == "生活兴趣/户外潮流"


def test_fas_bilibili_edc_toy_unboxing_uses_user_confirmed_outdoor_trend_when_api_only_has_parent_section():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    category = intelligence._choose_real_category(
        {
            "category_options": ["生活兴趣", "生活/出行", "生活/手工", "科技/数码"],
            "option_groups": [
                {
                    "key": "bilibili_api_sections",
                    "label": "B站真实分区接口",
                    "options": ["生活/出行", "生活/手工", "科技/数码"],
                }
            ],
        },
        {"platform": "bilibili", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert category == "生活兴趣/户外潮流"


def test_fas_edc_toy_unboxing_prefers_fas_collection_when_real_option_exists():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    collection = intelligence._choose_real_collection_name(
        {
            "account_label": "FAS · Chrome",
            "collection_suggestions": ["新品开箱", "EDC潮玩桌搭", "EDC刀光火工具集"],
        },
        {"platform": "xiaohongshu", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert collection == "EDC潮玩桌搭"


def test_selectable_collection_catalog_takes_priority_over_noisy_form_text():
    capability = intelligence._normalize_inventory_platform_options(
        {
            "status": "partial",
            "option_groups": [
                {
                    "key": "collections",
                    "label": "合集/栏目/播放列表",
                    "options": [
                        "将以下所有视频加入合集",
                        "加入合集",
                        "选择合集",
                        "请选择合集",
                        "MOT 风灵音叉推牌 锆合金版本",
                        "添加视频",
                        "添加分P",
                        "更换视频",
                        "基本设置一键填写",
                    ],
                },
                {
                    "key": "bilibili_season_catalog",
                    "label": "B站合集管理真实目录",
                    "options": ["FAS新品", "EDC刀光火工具集", "EDC潮玩桌搭", "机能户外装备"],
                    "values": [
                        {"id": 7549188, "name": "EDC潮玩桌搭", "selectable": True, "source": "bilibili_x2_creative_web_seasons"},
                    ],
                },
            ],
        }
    )
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    plan = intelligence._build_collection_management_plan(
        capability,
        {"platform": "bilibili", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert capability["collection_suggestions"][0] == "EDC潮玩桌搭"
    assert plan["status"] == "select_existing"
    assert plan["selected_collection_name"] == "EDC潮玩桌搭"


def test_edc_toy_collection_rule_is_scoped_to_fas_creator_account():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-2", "display_name": "Other Creator", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "Other Creator", "targets": []},
    )
    collection = intelligence._choose_real_collection_name(
        {
            "account_label": "Other Creator · Chrome",
            "collection_suggestions": ["新品开箱", "EDC潮玩桌搭", "EDC刀光火工具集"],
        },
        {"platform": "xiaohongshu", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert collection == "新品开箱"


def test_repair_scheme_restores_fas_edc_toy_collection_after_llm_drift():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    repaired = intelligence._repair_scheme(
        {
            "publication_policy": policy,
            "items": [
                {
                    "platform": "xiaohongshu",
                    "platform_label": "小红书",
                    "account_label": "FAS · Chrome",
                    "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
                    "collection_name": "新品开箱",
                    "available_collections": ["新品开箱", "EDC潮玩桌搭"],
                    "scheduled_publish_at": "2026-05-22T21:00",
                    "visibility_or_publish_mode": "scheduled",
                }
            ],
        },
        fallback={"platform_options": {}, "items": []},
    )

    assert repaired["items"][0]["collection_name"] == "EDC潮玩桌搭"
    assert repaired["platform_options"]["xiaohongshu"]["collection_name"] == "EDC潮玩桌搭"


def test_repair_scheme_restores_fas_bilibili_category_after_llm_drift():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    repaired = intelligence._repair_scheme(
        {
            "publication_policy": policy,
            "items": [
                {
                    "platform": "bilibili",
                    "platform_label": "B站",
                    "account_label": "FAS · Chrome",
                    "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
                    "category": "生活兴趣",
                    "available_categories": ["生活兴趣", "户外潮流", "科技数码"],
                    "scheduled_publish_at": "2026-05-22T19:30",
                    "visibility_or_publish_mode": "scheduled",
                }
            ],
        },
        fallback={"platform_options": {}, "items": []},
    )

    assert repaired["items"][0]["category"] == "生活兴趣/户外潮流"
    assert repaired["platform_options"]["bilibili"]["category"] == "生活兴趣/户外潮流"
    assert repaired["platform_options"]["bilibili"]["platform_specific_overrides"]["category_selection_plan"][
        "category_path"
    ] == ["生活兴趣", "户外潮流"]


def test_creator_profile_publication_policy_uses_same_framework_for_other_accounts():
    policy = intelligence._publication_policy_for_creator(
        {
            "id": "profile-custom",
            "display_name": "桌搭账号",
            "creator_profile": {
                "publishing": {
                    "publication_rules": [
                        {
                            "type": "preferred_collection",
                            "platforms": ["xiaohongshu"],
                            "content_keywords_all": ["键盘", "桌搭"],
                            "preferred_collection_name": "机械键盘桌搭",
                        }
                    ]
                }
            },
        },
        {"creator_profile_name": "桌搭账号", "targets": []},
    )
    collection = intelligence._choose_real_collection_name(
        {"collection_suggestions": ["日常记录", "机械键盘桌搭"]},
        {"platform": "xiaohongshu", "title": "新键盘桌搭开箱"},
        publication_policy=policy,
    )

    assert collection == "机械键盘桌搭"


def test_fas_kuaishou_empty_collection_requires_post_publish_association():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    target = {"platform": "kuaishou", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"}
    plan = intelligence._build_collection_management_plan(
        {
            "collection_suggestions": ["FAS新品"],
            "collection_catalog": [
                {
                    "name": "EDC潮玩桌搭",
                    "status": "未公开展示：有效剧集数不足",
                    "selectable": False,
                    "video_count": 0,
                },
                {"name": "FAS新品", "selectable": True, "video_count": 41},
            ],
        },
        target,
        publication_policy=policy,
    )
    collection = intelligence._choose_real_collection_name(
        {"collection_suggestions": ["FAS新品"]},
        target,
        publication_policy=policy,
    )

    assert collection == ""
    assert plan["kind"] == "collection"
    assert plan["status"] == "exists_but_not_selectable_on_publish_form"
    assert plan["target_collection_name"] == "EDC潮玩桌搭"
    assert plan["post_publish_association_required"] is True
    assert plan["create_required"] is False


def test_youtube_uses_playlist_semantics_for_unified_collection_policy():
    policy = intelligence._publication_policy_for_creator(
        {"id": "profile-1", "display_name": "FAS", "creator_profile": {"publishing": {}}},
        {"creator_profile_name": "FAS", "targets": []},
    )
    plan = intelligence._build_collection_management_plan(
        {"collection_suggestions": ["EDC潮玩桌搭", "Product Reviews"]},
        {"platform": "youtube", "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱"},
        publication_policy=policy,
    )

    assert plan["kind"] == "playlist"
    assert plan["status"] == "select_existing"
    assert plan["selected_collection_name"] == "EDC潮玩桌搭"


def test_xiaohongshu_topic_plan_requires_suggestion_selection():
    selected = intelligence._select_platform_specific_options(
        {
            "option_groups": [
                {
                    "key": "topics",
                    "label": "话题",
                    "options": ["EDC", "潮玩", "桌搭"],
                }
            ]
        },
        {
            "platform": "xiaohongshu",
            "title": "MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
            "tags": ["EDC", "潮玩", "桌搭"],
        },
    )

    assert selected["topic_selection_plan"]["mode"] == "search_and_select_platform_topic_suggestions"
    assert selected["topic_selection_plan"]["selection_required"] is True
    assert selected["topic_selection_plan"]["requested_topics"] == ["EDC", "潮玩", "桌搭"]


def test_build_scheme_carries_actual_generated_material_fields():
    scheme = intelligence._build_scheme_from_record(
        plan={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "targets": [
                {
                    "platform": "xiaohongshu",
                    "platform_label": "小红书",
                    "title": "真实生成标题",
                    "titles": ["真实生成标题", "备选标题"],
                    "body": "真实生成正文",
                    "tags": ["EDC", "潮玩"],
                    "cover_path": "D:/material/smart-copy/xhs-cover.jpg",
                    "full_copy": "真实生成标题\n\n真实生成正文",
                    "copy_material": {"source": "platform_packaging", "primary_title": "真实生成标题"},
                }
            ],
        },
        record={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "publication_policy": intelligence._empty_publication_policy(),
            "time_strategy": {"platform_slots": {"xiaohongshu": [{"time": "21:00", "reason": "test"}]}},
            "platforms": {"xiaohongshu": {"supports_scheduled_publish": True}},
        },
        folder_path="D:/material",
        browser="chrome",
    )

    item = scheme["items"][0]
    assert item["title"] == "真实生成标题"
    assert item["body"] == "真实生成正文"
    assert item["tags"] == ["EDC", "潮玩"]
    assert item["cover_path"] == "D:/material/smart-copy/xhs-cover.jpg"
    assert item["copy_material"]["primary_title"] == "真实生成标题"


def test_build_scheme_marks_live_publish_preflight_blocked_when_required_surfaces_missing():
    scheme = intelligence._build_scheme_from_record(
        plan={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "targets": [
                {
                    "platform": "kuaishou",
                    "platform_label": "快手",
                    "title": "真实生成标题",
                    "body": "真实生成正文",
                    "tags": ["EDC"],
                }
            ],
        },
        record={
            "creator_profile_id": "profile-1",
            "creator_profile_name": "FAS",
            "publication_policy": intelligence._empty_publication_policy(),
            "time_strategy": {"platform_slots": {"kuaishou": [{"time": "20:00", "reason": "test"}]}},
            "platforms": {
                "kuaishou": {
                    "supports_scheduled_publish": True,
                    "coverage": {
                        "required_surfaces": ["cover", "visibility", "schedule"],
                        "missing_required_surfaces": ["cover", "visibility", "schedule"],
                    },
                    "evidence": {
                        "by_surface": [
                            {"key": "collection", "confidence": "strong"},
                        ]
                    },
                }
            },
        },
        folder_path="D:/material",
        browser="chrome",
    )

    preflight = scheme["items"][0]["live_publish_preflight"]
    assert preflight["status"] == "blocked"
    assert preflight["missing_required_surfaces"] == ["cover", "visibility", "schedule"]
    assert scheme["platform_options"]["kuaishou"]["live_publish_preflight"] == preflight
    assert scheme["platform_options"]["kuaishou"]["platform_specific_overrides"]["live_publish_preflight"] == preflight


@pytest.mark.asyncio
async def test_modify_publication_scheme_rule_fallback_scopes_platform_clauses(monkeypatch):
    async def _no_llm(*args, **kwargs):
        return None

    monkeypatch.setattr(intelligence, "_modify_scheme_with_llm", _no_llm)
    monkeypatch.setattr(intelligence, "_next_local_datetime", lambda slot, day_offset=0: f"2026-05-22T{slot}")
    scheme = {
        "status": "ready",
        "platform_options": {
            "bilibili": {
                "scheduled_publish_at": "2026-05-22T19:30",
                "collection_name": "数码装备",
                "visibility_or_publish_mode": "scheduled",
            },
            "youtube": {
                "scheduled_publish_at": "2026-05-22T20:00",
                "collection_name": "Product Reviews",
                "visibility_or_publish_mode": "scheduled",
            },
            "xiaohongshu": {
                "scheduled_publish_at": "2026-05-22T21:00",
                "collection_name": "桌面与随身装备",
                "visibility_or_publish_mode": "scheduled",
            },
        },
        "items": [
            {"platform": "bilibili", "platform_label": "B站", "scheduled_publish_at": "2026-05-22T19:30", "collection_name": "数码装备", "visibility_or_publish_mode": "scheduled"},
            {"platform": "youtube", "platform_label": "YouTube", "scheduled_publish_at": "2026-05-22T20:00", "collection_name": "Product Reviews", "visibility_or_publish_mode": "scheduled"},
            {"platform": "xiaohongshu", "platform_label": "小红书", "scheduled_publish_at": "2026-05-22T21:00", "collection_name": "桌面与随身装备", "visibility_or_publish_mode": "scheduled"},
        ],
    }

    result = await intelligence.modify_publication_scheme(
        scheme=scheme,
        instruction="B站放到 EDC装备评测合集，YouTube 改成今晚 21:30，小红书只建草稿。",
    )

    options = result["platform_options"]
    assert options["bilibili"]["collection_name"] == "EDC装备评测合集"
    assert options["bilibili"]["scheduled_publish_at"] == "2026-05-22T19:30"
    assert options["youtube"]["scheduled_publish_at"] == "2026-05-22T21:30"
    assert options["youtube"]["visibility_or_publish_mode"] == "scheduled"
    assert options["xiaohongshu"]["visibility_or_publish_mode"] == "draft"
    assert options["xiaohongshu"]["scheduled_publish_at"] == "2026-05-22T21:00"

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.config import get_settings
from roughcut.publication_probe import BROWSER_AGENT_INVENTORY_CONTRACT, probe_browser_agent_publication_inventory
from roughcut.publication_platform_matrix import platform_supports_scheduled_publish
from roughcut.publication import normalize_publication_platform, platform_label

CACHE_PATH = Path("data/runtime/publication_intelligence/cache.json")
LEGACY_CACHE_PATH = Path("data/publication_intelligence/cache.json")
CACHE_VERSION = "publication-intelligence-v2"
_CACHE_LOCK = RLock()

DEFAULT_TIME_SLOTS: dict[str, str] = {
    "douyin": "20:30",
    "xiaohongshu": "21:00",
    "bilibili": "19:30",
    "kuaishou": "20:00",
    "wechat-channels": "12:30",
    "toutiao": "11:30",
    "youtube": "20:00",
    "x": "09:30",
}

PROBE_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}

EDC_TOY_COLLECTION_NAME = "EDC潮玩桌搭"
PUBLICATION_POLICY_VERSION = "account-publication-policy-v1"

BUILTIN_CREATOR_PUBLICATION_POLICIES: list[dict[str, Any]] = [
    {
        "id": "fas-default-publication-policy",
        "source": "builtin_fas",
        "creator_match": ["FAS", "F.A.S", "FAS机神圣殿"],
        "rules": [
            {
                "id": "fas-edc-toy-unboxing-collection",
                "type": "preferred_collection",
                "platforms": ["*"],
                "content_pattern": "edc_toy_unboxing",
                "preferred_collection_name": EDC_TOY_COLLECTION_NAME,
                "requires_real_option": True,
            },
            {
                "id": "fas-bilibili-edc-toy-unboxing-category",
                "type": "preferred_category",
                "platforms": ["bilibili"],
                "content_pattern": "edc_toy_unboxing",
                "preferred_category_name": "生活兴趣/户外潮流",
                "preferred_category_path": ["生活兴趣", "户外潮流"],
                "legacy_api_fallback_category": "生活/出行",
                "requires_real_option": False,
                "source_note": "FAS 账号真实 B站投稿页已人工确认页面分区为 生活兴趣 -> 户外潮流；旧接口分区只作为兜底参考。",
            }
        ],
    }
]

PLATFORM_FIELD_HINTS: dict[str, dict[str, Any]] = {
    "douyin": {
        "visibility_modes": ["scheduled", "draft", "private"],
        "required_fields": ["标题", "视频", "简介", "话题"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("douyin"),
        "option_notes": "尚未取得真实合集/栏目列表；发布前必须由 browser-agent 做页面验证。",
    },
    "xiaohongshu": {
        "visibility_modes": ["scheduled", "draft"],
        "required_fields": ["标题", "正文", "话题", "封面"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("xiaohongshu"),
        "option_notes": "尚未取得真实专辑/合集列表；发布前必须由 browser-agent 做页面验证。",
    },
    "bilibili": {
        "visibility_modes": ["scheduled", "draft", "private"],
        "required_fields": ["标题", "分区", "简介", "标签", "合集"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("bilibili"),
        "option_notes": "尚未取得真实分区、合集/系列列表；发布前必须由 browser-agent 做页面验证。",
    },
    "kuaishou": {
        "visibility_modes": ["scheduled", "draft", "private"],
        "required_fields": ["标题", "视频", "简介"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("kuaishou"),
        "option_notes": "尚未取得真实合集入口数据；发布前必须由 browser-agent 做页面验证。",
    },
    "wechat-channels": {
        "visibility_modes": ["scheduled", "draft"],
        "required_fields": ["描述", "视频", "封面"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("wechat-channels"),
        "option_notes": "尚未取得真实活动/合集入口数据；发布前必须由 browser-agent 做页面验证。",
    },
    "toutiao": {
        "visibility_modes": ["scheduled", "draft"],
        "required_fields": ["标题", "分类", "简介", "标签"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("toutiao"),
        "option_notes": "尚未取得真实分类/合集数据；发布前必须由 browser-agent 做页面验证。",
    },
    "youtube": {
        "visibility_modes": ["scheduled", "draft", "private", "unlisted"],
        "required_fields": ["title", "description", "tags", "visibility", "playlist"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("youtube"),
        "option_notes": "尚未取得真实 playlist 列表；发布前必须由 browser-agent 做页面验证。",
    },
    "x": {
        "visibility_modes": ["scheduled", "draft"],
        "required_fields": ["post text", "media"],
        "supports_scheduled_publish": platform_supports_scheduled_publish("x"),
        "option_notes": "尚未取得真实发布选项；发布前必须由 browser-agent 做页面验证。",
    },
}


async def generate_publication_scheme(
    *,
    plan: dict[str, Any],
    creator_profile: dict[str, Any] | None,
    folder_path: str,
    browser: str | None = None,
    force_probe: bool = False,
) -> dict[str, Any]:
    targets = [target for target in plan.get("targets") or [] if isinstance(target, dict)]
    browser_id = _normalize_browser(browser)
    profile_id = str((creator_profile or {}).get("id") or plan.get("creator_profile_id") or "").strip()
    cache = _load_cache()
    cache_key = _cache_key(profile_id, browser_id)
    record = cache.get(cache_key) if isinstance(cache.get(cache_key), dict) else {}

    target_platforms = [platform for platform in (_normalize_platform(target.get("platform")) for target in targets) if platform]
    missing_probe = [
        platform
        for platform in target_platforms
        if platform not in (record.get("platforms") or {}) or not _platform_record_has_real_inventory((record.get("platforms") or {}).get(platform))
    ]
    if force_probe or missing_probe:
        record = await _merge_probe_record(
            record,
            targets=targets,
            browser=browser_id,
            creator_profile=creator_profile,
            plan=plan,
            folder_path=folder_path,
            draft_upload_probe=force_probe,
        )

    content_key = _content_key(targets)
    time_strategy = record.get("time_strategy") if isinstance(record.get("time_strategy"), dict) else {}
    if force_probe or time_strategy.get("content_key") != content_key:
        time_strategy = await _research_time_strategy(targets)
        record["time_strategy"] = time_strategy
    record["publication_policy"] = _publication_policy_for_creator(creator_profile, plan)

    record.update(
        {
            "version": CACHE_VERSION,
            "creator_profile_id": profile_id,
            "creator_profile_name": str((creator_profile or {}).get("display_name") or plan.get("creator_profile_name") or ""),
            "browser": browser_id,
            "updated_at": _now_iso(),
        }
    )
    cache[cache_key] = record
    _save_cache(cache)

    scheme = _build_scheme_from_record(
        plan=plan,
        record=record,
        folder_path=folder_path,
        browser=browser_id,
    )
    refined = await _refine_scheme_with_llm(scheme)
    if refined:
        return refined
    return scheme


async def modify_publication_scheme(*, scheme: dict[str, Any], instruction: str) -> dict[str, Any]:
    base = deepcopy(scheme) if isinstance(scheme, dict) else {}
    instruction_text = str(instruction or "").strip()
    if not instruction_text:
        return base
    llm_result = await _modify_scheme_with_llm(base, instruction_text)
    if llm_result:
        return llm_result
    return _modify_scheme_with_rules(base, instruction_text)


def _empty_publication_policy() -> dict[str, Any]:
    return {"version": PUBLICATION_POLICY_VERSION, "source": "none", "rules": []}


def _publication_policy_for_creator(creator_profile: dict[str, Any] | None, plan: dict[str, Any] | None) -> dict[str, Any]:
    profile = creator_profile if isinstance(creator_profile, dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    rules: list[dict[str, Any]] = []
    sources: list[str] = []

    profile_rules = _publication_rules_from_creator_profile(profile)
    if profile_rules:
        rules.extend(profile_rules)
        sources.append("creator_profile")

    context_text = _creator_policy_context_text(profile, plan)
    for preset in BUILTIN_CREATOR_PUBLICATION_POLICIES:
        if not _creator_policy_matches(preset, context_text):
            continue
        normalized = _normalize_publication_rules(preset.get("rules"), source=str(preset.get("source") or preset.get("id") or "builtin"))
        if normalized:
            rules.extend(normalized)
            sources.append(str(preset.get("source") or preset.get("id") or "builtin"))

    if not rules:
        return _empty_publication_policy()
    return {
        "version": PUBLICATION_POLICY_VERSION,
        "source": "+".join(dict.fromkeys(sources)) or "creator_profile",
        "rules": rules,
    }


def _publication_rules_from_creator_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    containers = [
        publishing.get("publication_policy"),
        publishing.get("publication_rules"),
        publishing.get("account_publication_policy"),
        publishing.get("account_publication_rules"),
    ]
    rules: list[dict[str, Any]] = []
    for container in containers:
        raw_rules = container.get("rules") if isinstance(container, dict) else container
        rules.extend(_normalize_publication_rules(raw_rules, source="creator_profile"))
    return rules


def _normalize_publication_rules(raw_rules: Any, *, source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(raw_rules, dict):
        iterable = [raw_rules]
    elif isinstance(raw_rules, list):
        iterable = raw_rules
    else:
        iterable = []
    for index, raw in enumerate(iterable):
        if not isinstance(raw, dict):
            continue
        rule_type = str(raw.get("type") or raw.get("action") or "preferred_collection").strip()
        preferred_collection = str(raw.get("preferred_collection_name") or raw.get("preferred_collection") or raw.get("collection_name") or "").strip()
        preferred_category = str(raw.get("preferred_category_name") or raw.get("preferred_category") or raw.get("category") or "").strip()
        if rule_type not in {"preferred_collection", "preferred_category"}:
            continue
        if rule_type == "preferred_collection" and not preferred_collection:
            continue
        if rule_type == "preferred_category" and not preferred_category:
            continue
        platforms = _normalize_rule_platforms(raw.get("platforms") or raw.get("platform") or "*")
        rule = {
            "id": str(raw.get("id") or f"{source}-rule-{index + 1}"),
            "source": source,
            "type": rule_type,
            "platforms": platforms,
            "content_pattern": str(raw.get("content_pattern") or raw.get("content_type") or "").strip(),
            "content_keywords_any": _clean_string_list(raw.get("content_keywords_any") or raw.get("keywords_any") or raw.get("keywords")),
            "content_keywords_all": _clean_string_list(raw.get("content_keywords_all") or raw.get("keywords_all")),
            "requires_real_option": bool(raw.get("requires_real_option", True)),
        }
        if preferred_collection:
            rule["preferred_collection_name"] = preferred_collection
        if preferred_category:
            rule["preferred_category_name"] = preferred_category
        category_path = _clean_string_list(raw.get("preferred_category_path") or raw.get("category_path"))
        if category_path:
            rule["preferred_category_path"] = category_path
        fallback_category = str(raw.get("legacy_api_fallback_category") or raw.get("fallback_category") or "").strip()
        if fallback_category:
            rule["legacy_api_fallback_category"] = fallback_category
        normalized.append(rule)
    return normalized


def _normalize_rule_platforms(value: Any) -> list[str]:
    if value == "*":
        return ["*"]
    raw_values = value if isinstance(value, list) else [value]
    platforms = [_normalize_platform(item) for item in raw_values]
    cleaned = [platform for platform in platforms if platform]
    return cleaned or ["*"]


def _creator_policy_context_text(profile: dict[str, Any], plan: dict[str, Any]) -> str:
    values = [
        profile.get("id"),
        profile.get("display_name"),
        profile.get("presenter_alias"),
        plan.get("creator_profile_id"),
        plan.get("creator_profile_name"),
    ]
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    for credential in publishing.get("platform_credentials") or []:
        if isinstance(credential, dict):
            values.extend([credential.get("account_label"), credential.get("credential_ref")])
    for target in plan.get("targets") or []:
        if isinstance(target, dict):
            values.extend([target.get("account_label"), target.get("creator_profile_name")])
    return " ".join(str(value or "") for value in values)


def _creator_policy_matches(policy: dict[str, Any], context_text: str) -> bool:
    normalized_context = context_text.casefold()
    for pattern in policy.get("creator_match") or []:
        text = str(pattern or "").strip()
        if text and text.casefold() in normalized_context:
            return True
    return False


def _build_scheme_from_record(*, plan: dict[str, Any], record: dict[str, Any], folder_path: str, browser: str) -> dict[str, Any]:
    time_strategy = record.get("time_strategy") if isinstance(record.get("time_strategy"), dict) else {}
    platform_slots = time_strategy.get("platform_slots") if isinstance(time_strategy.get("platform_slots"), dict) else {}
    platform_capabilities = record.get("platforms") if isinstance(record.get("platforms"), dict) else {}
    publication_policy = record.get("publication_policy") if isinstance(record.get("publication_policy"), dict) else _empty_publication_policy()
    targets = [target for target in plan.get("targets") or [] if isinstance(target, dict)]
    platform_options: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    base_day_offsets: dict[str, int] = {}

    for index, target in enumerate(targets):
        platform = _normalize_platform(target.get("platform"))
        if not platform:
            continue
        capability = platform_capabilities.get(platform) if isinstance(platform_capabilities.get(platform), dict) else {}
        default_slot = DEFAULT_TIME_SLOTS.get(platform, "20:00")
        slots = platform_slots.get(platform) if isinstance(platform_slots.get(platform), list) else []
        first_slot = slots[0] if slots and isinstance(slots[0], dict) else {}
        slot = _normalize_time_slot(first_slot.get("time") or default_slot)
        base_day_offsets[slot] = base_day_offsets.get(slot, 0)
        scheduled_at = _next_local_datetime(slot, day_offset=base_day_offsets[slot] // 3)
        base_day_offsets[slot] += 1

        collection_management = _build_collection_management_plan(
            capability,
            target,
            publication_policy=publication_policy,
        )
        collection_name = _choose_real_collection_name(capability, target, publication_policy=publication_policy)
        if collection_management.get("status") != "select_existing":
            collection_name = ""
        category = _choose_real_category(capability, target, publication_policy=publication_policy)
        effective_scheduled_publish = _capability_supports_effective_scheduled_publish(capability)
        visibility = "scheduled" if effective_scheduled_publish else "draft"
        option = {
            "visibility_or_publish_mode": visibility,
        }
        if effective_scheduled_publish:
            option["scheduled_publish_at"] = scheduled_at
        if collection_name:
            option["collection_name"] = collection_name
        if category:
            option["category"] = category
        selected_options = _select_platform_specific_options(capability, target)
        category_selection_plan = _build_category_selection_plan(
            capability,
            target,
            category,
            publication_policy=publication_policy,
        )
        if category_selection_plan:
            selected_options["category_selection_plan"] = category_selection_plan
        selected_options["collection_management"] = collection_management
        live_publish_preflight = _build_live_publish_preflight(capability, supports_scheduled_publish=effective_scheduled_publish)
        selected_options["live_publish_preflight"] = live_publish_preflight
        option["live_publish_preflight"] = live_publish_preflight
        if selected_options:
            option["platform_specific_overrides"] = selected_options
        platform_options[platform] = option
        items.append(
            {
                "platform": platform,
                "platform_label": str(target.get("platform_label") or platform_label(platform)),
                "account_label": str(target.get("account_label") or ""),
                "creator_profile_name": str(plan.get("creator_profile_name") or record.get("creator_profile_name") or ""),
                "title": str(target.get("title") or ""),
                "titles": [str(value).strip() for value in (target.get("titles") or []) if str(value).strip()][:3],
                "body": str(target.get("body") or target.get("description") or ""),
                "tags": [str(value).strip().lstrip("#") for value in (target.get("tags") or []) if str(value).strip()],
                "cover_path": str(target.get("cover_path") or ""),
                "full_copy": str(target.get("full_copy") or ""),
                "copy_material": target.get("copy_material") if isinstance(target.get("copy_material"), dict) else {},
                "scheduled_publish_at": scheduled_at if effective_scheduled_publish else "",
                "collection_name": collection_name,
                "collection_management": collection_management,
                "category": category,
                "visibility_or_publish_mode": visibility,
                "rationale": str(first_slot.get("reason") or _default_slot_reason(platform, slot)),
                "probe_summary": _capability_summary(capability),
                "validation_status": "publish_time_light_validation",
                "required_fields": list(capability.get("required_fields") or []),
                "available_collections": list(capability.get("collection_suggestions") or [])[:6],
                "collection_catalog": list(capability.get("collection_catalog") or [])[:20],
                "available_categories": list(capability.get("category_options") or [])[:8],
                "declaration_options": list(capability.get("declaration_options") or [])[:12],
                "group_chat_options": list(capability.get("group_chat_options") or [])[:8],
                "selected_options": selected_options,
                "field_groups": list(capability.get("field_groups") or [])[:12],
                "option_groups": list(capability.get("option_groups") or [])[:12],
                "probe_coverage": capability.get("coverage") if isinstance(capability.get("coverage"), dict) else {},
                "live_publish_preflight": live_publish_preflight,
                "operation_steps": list(capability.get("operation_steps") or [])[:20],
                "platform_warnings": list(capability.get("platform_warnings") or [])[:8],
                "route": capability.get("route") if isinstance(capability.get("route"), dict) else {},
            }
        )

    return {
        "status": "ready" if items else "blocked",
        "folder_path": folder_path,
        "browser": browser,
        "creator_profile_id": str(plan.get("creator_profile_id") or record.get("creator_profile_id") or ""),
        "creator_profile_name": str(plan.get("creator_profile_name") or record.get("creator_profile_name") or ""),
        "generated_at": _now_iso(),
        "cache_version": CACHE_VERSION,
        "probe": {
            "status": _probe_record_status(record),
            "probed_at": record.get("probed_at"),
            "browser": browser,
            "note": _probe_record_note(record),
        },
        "research": time_strategy,
        "publication_policy": publication_policy,
        "platform_options": platform_options,
        "items": items,
        "notes": [
            "方案已转换为发布接口可执行的 platform_options。",
            "没有真实来源的合集/栏目/分类不会自动填写；必须先完成真实平台摸底或在修改方案中明确指定。",
            "发布时 browser-agent 仍会验证页面和字段是否发生变化。",
        ],
    }


async def _merge_probe_record(
    record: dict[str, Any],
    *,
    targets: list[dict[str, Any]],
    browser: str,
    creator_profile: dict[str, Any] | None,
    plan: dict[str, Any] | None = None,
    folder_path: str = "",
    draft_upload_probe: bool = False,
) -> dict[str, Any]:
    next_record = deepcopy(record) if isinstance(record, dict) else {}
    platforms = next_record.get("platforms") if isinstance(next_record.get("platforms"), dict) else {}
    credentials = _creator_credentials(creator_profile)
    account_by_platform = {
        _normalize_platform(item.get("platform")): str(item.get("account_label") or item.get("credential_ref") or "")
        for item in credentials
    }
    metadata_by_platform = _creator_platform_metadata(creator_profile, credentials)
    target_platforms = [platform for platform in (_normalize_platform(target.get("platform")) for target in targets) if platform]
    inventory = await _probe_real_platform_inventory(
        targets=targets,
        creator_profile=creator_profile,
        browser=browser,
        platforms=target_platforms,
        plan=plan,
        folder_path=folder_path,
        draft_upload_probe=draft_upload_probe,
    )
    inventory_by_platform = inventory.get("platforms") if isinstance(inventory.get("platforms"), dict) else {}
    for target in targets:
        platform = _normalize_platform(target.get("platform"))
        if not platform:
            continue
        field_hints = deepcopy(PLATFORM_FIELD_HINTS.get(platform) or {})
        real_metadata = metadata_by_platform.get(platform, {})
        real_inventory = _normalize_inventory_platform_options(inventory_by_platform.get(platform))
        capability = {
            **field_hints,
            **real_metadata,
            **real_inventory,
        }
        has_real_options = _platform_record_has_real_inventory(capability)
        capability.update(
            {
                "platform": platform,
                "platform_label": str(target.get("platform_label") or platform_label(platform)),
                "account_label": account_by_platform.get(platform) or str(target.get("account_label") or ""),
                "creator_profile_name": str((creator_profile or {}).get("display_name") or (plan or {}).get("creator_profile_name") or ""),
                "browser": browser,
                "source": real_inventory.get("source") or ("creator_profile_platform_metadata" if has_real_options else "login_reference_only"),
                "last_probe_at": _now_iso(),
                "validation_policy": "publish_time_light_validation",
                "has_real_platform_options": has_real_options,
            }
        )
        previous = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        if previous.get("source") in {"cached_first_probe", "browser_session_capability_cache"}:
            previous = {}
        platforms[platform] = {**previous, **capability}
        platforms[platform]["last_probe_at"] = _now_iso()
    next_record["platforms"] = platforms
    next_record["probed_at"] = _now_iso()
    has_any_real_options = any(
        isinstance(item, dict) and item.get("has_real_platform_options")
        for item in platforms.values()
    )
    next_record["probe_source"] = inventory.get("source") or ("creator_profile_platform_metadata" if has_any_real_options else "login_reference_only")
    next_record["probe_contract"] = BROWSER_AGENT_INVENTORY_CONTRACT
    next_record["probe_status"] = inventory.get("status")
    if inventory.get("message"):
        next_record["probe_message"] = inventory.get("message")
    return next_record


async def _research_time_strategy(targets: list[dict[str, Any]]) -> dict[str, Any]:
    content_summary = _summarize_content(targets)
    platforms = [_normalize_platform(target.get("platform")) for target in targets]
    platforms = [platform for platform in platforms if platform]
    queries = [
        f"2026 {content_summary['topic']} 视频 最佳发布时间 数据",
        "短视频 平台 最佳发布时间 数据 抖音 小红书 B站",
        "YouTube tech video best time to publish 2026 data",
    ]
    evidence: list[dict[str, str]] = []
    search_errors: list[str] = []
    try:
        provider = get_search_provider()
        for query in queries:
            try:
                results = await provider.search(query, max_results=3)
            except Exception as exc:
                search_errors.append(f"{query}: {exc}")
                continue
            for result in results:
                evidence.append(
                    {
                        "query": query,
                        "title": str(result.title or "")[:180],
                        "url": str(result.url or "")[:300],
                        "snippet": str(result.snippet or "")[:500],
                    }
                )
                if len(evidence) >= 8:
                    break
            if len(evidence) >= 8:
                break
    except Exception as exc:
        search_errors.append(str(exc))

    fallback_slots = {
        platform: [{"time": DEFAULT_TIME_SLOTS.get(platform, "20:00"), "reason": _default_slot_reason(platform, DEFAULT_TIME_SLOTS.get(platform, "20:00"))}]
        for platform in platforms
    }
    strategy = {
        "content_key": _content_key(targets),
        "content_type": content_summary["content_type"],
        "topic": content_summary["topic"],
        "generated_at": _now_iso(),
        "queries": queries,
        "evidence": evidence,
        "search_status": "ok" if evidence else "fallback",
        "search_errors": search_errors[:3],
        "platform_slots": fallback_slots,
        "summary": "按内容主题、平台用户活跃时段和现有发布经验生成。联网检索不可用时使用内置保守时段。",
    }
    llm_slots = await _summarize_time_strategy_with_llm(strategy)
    if llm_slots:
        strategy["platform_slots"] = _merge_platform_slots(fallback_slots, llm_slots, platforms)
        strategy["summary"] = "已结合联网检索摘要和 LLM 判断生成发布时间策略。"
        strategy["llm_status"] = "ok"
    else:
        strategy["llm_status"] = "fallback"
    return strategy


async def _summarize_time_strategy_with_llm(strategy: dict[str, Any]) -> dict[str, Any] | None:
    if not strategy.get("evidence"):
        return None
    prompt = {
        "task": "根据视频主题、平台和检索证据，给出各平台建议发布时间。",
        "schema": {
            "platform_slots": {
                "platform": [{"time": "HH:MM", "reason": "一句话说明"}],
            }
        },
        "strategy": strategy,
    }
    try:
        response = await get_reasoning_provider().complete(
            [
                Message(role="system", content="你是中文内容发布运营策略助手，只输出 JSON，不要输出解释。"),
                Message(role="user", content=json.dumps(prompt, ensure_ascii=False)),
            ],
            temperature=0.2,
            max_tokens=1800,
            json_mode=True,
        )
        payload = json.loads(extract_json_text(response.content))
    except Exception:
        return None
    slots = payload.get("platform_slots") if isinstance(payload, dict) else None
    return slots if isinstance(slots, dict) else None


async def _refine_scheme_with_llm(scheme: dict[str, Any]) -> dict[str, Any] | None:
    if (scheme.get("research") or {}).get("llm_status") != "ok":
        return None
    prompt = {
        "task": "检查并微调发布方案。必须保留全部平台；只允许修改时间、合集名、分类、可见性、rationale。",
        "scheme": scheme,
    }
    try:
        response = await get_reasoning_provider().complete(
            [
                Message(role="system", content="你是发布运营负责人，只输出完整 JSON 方案。"),
                Message(role="user", content=json.dumps(prompt, ensure_ascii=False)),
            ],
            temperature=0.15,
            max_tokens=3500,
            json_mode=True,
        )
        payload = json.loads(extract_json_text(response.content))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    return _repair_scheme(payload, fallback=scheme)


async def _modify_scheme_with_llm(scheme: dict[str, Any], instruction: str) -> dict[str, Any] | None:
    prompt = {
        "task": "根据用户修改意见更新发布方案。必须保留原 JSON 结构和所有未被要求修改的平台。",
        "instruction": instruction,
        "scheme": scheme,
    }
    try:
        response = await get_reasoning_provider().complete(
            [
                Message(role="system", content="你是发布方案编辑器，只输出完整 JSON 方案。"),
                Message(role="user", content=json.dumps(prompt, ensure_ascii=False)),
            ],
            temperature=0.2,
            max_tokens=3500,
            json_mode=True,
        )
        payload = json.loads(extract_json_text(response.content))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    payload["modified_at"] = _now_iso()
    payload["last_instruction"] = instruction
    return _repair_scheme(payload, fallback=scheme)


def _modify_scheme_with_rules(scheme: dict[str, Any], instruction: str) -> dict[str, Any]:
    next_scheme = deepcopy(scheme)
    platform_items = [item for item in next_scheme.get("items") or [] if isinstance(item, dict)]
    clauses = [clause.strip() for clause in re.split(r"[，,。；;\n]+", instruction) if clause.strip()]
    explicit_clause_seen = any(
        _platform_mentioned(str(item.get("platform") or ""), clause)
        for clause in clauses
        for item in platform_items
    )
    for clause in clauses or [instruction]:
        mentioned_platforms = [
            str(item.get("platform") or "")
            for item in platform_items
            if _platform_mentioned(str(item.get("platform") or ""), clause)
        ]
        if not mentioned_platforms and explicit_clause_seen:
            continue
        target_platforms = mentioned_platforms or [str(item.get("platform") or "") for item in platform_items]
        patch = _rule_patch_from_instruction_clause(clause)
        if not patch:
            continue
        for item in platform_items:
            if str(item.get("platform") or "") not in target_platforms:
                continue
            item.update(patch)
            item["rationale"] = f"按用户修改意见调整：{clause[:80]}"
    next_scheme["modified_at"] = _now_iso()
    next_scheme["last_instruction"] = instruction
    return _repair_scheme(next_scheme, fallback=scheme)


def _rule_patch_from_instruction_clause(clause: str) -> dict[str, str]:
    lowered = clause.lower()
    patch: dict[str, str] = {}
    time_match = re.search(r"(\d{1,2})[:：点](\d{1,2})?", clause)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        patch["scheduled_publish_at"] = _next_local_datetime(f"{hour:02d}:{minute:02d}")
    if "草稿" in clause or "draft" in lowered:
        patch["visibility_or_publish_mode"] = "draft"
    elif "私密" in clause or "仅自己" in clause or "private" in lowered:
        patch["visibility_or_publish_mode"] = "private"
    elif "预约" in clause or "定时" in clause or "scheduled" in lowered:
        patch["visibility_or_publish_mode"] = "scheduled"
    collection_name = _extract_collection_name(clause)
    if collection_name:
        patch["collection_name"] = collection_name
    if "分类" in clause or "分区" in clause:
        category = _extract_named_value(clause, ["分类", "分区"])
        if category:
            patch["category"] = category
    return patch


def _repair_scheme(payload: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in payload.get("items") or [] if isinstance(item, dict) and _normalize_platform(item.get("platform"))]
    fallback_options = fallback.get("platform_options") if isinstance(fallback.get("platform_options"), dict) else {}
    publication_policy = (
        payload.get("publication_policy")
        if isinstance(payload.get("publication_policy"), dict)
        else fallback.get("publication_policy")
        if isinstance(fallback.get("publication_policy"), dict)
        else _empty_publication_policy()
    )
    fallback_items = {
        _normalize_platform(item.get("platform")): item
        for item in (fallback.get("items") or [])
        if isinstance(item, dict) and _normalize_platform(item.get("platform"))
    }
    platform_options: dict[str, dict[str, Any]] = {}
    for item in items:
        platform = _normalize_platform(item.get("platform"))
        assert platform is not None
        item["platform"] = platform
        fallback_item = fallback_items.get(platform) if isinstance(fallback_items.get(platform), dict) else {}
        repaired_collection = _repair_policy_collection_choice(item, fallback_item, publication_policy)
        if repaired_collection:
            item["collection_name"] = repaired_collection
        collection_management = item.get("collection_management") if isinstance(item.get("collection_management"), dict) else fallback_item.get("collection_management")
        if isinstance(collection_management, dict):
            item["collection_management"] = collection_management
            if collection_management.get("status") != "select_existing":
                item["collection_name"] = ""
        repaired_category = _repair_policy_category_choice(item, fallback_item, publication_policy)
        if repaired_category:
            item["category"] = repaired_category
        option = deepcopy(fallback_options.get(platform) or {})
        for source_key, target_key in (
            ("scheduled_publish_at", "scheduled_publish_at"),
            ("collection_id", "collection_id"),
            ("collection_name", "collection_name"),
            ("category", "category"),
            ("visibility_or_publish_mode", "visibility_or_publish_mode"),
        ):
            value = str(item.get(source_key) or "").strip()
            if value:
                option[target_key] = value
        if isinstance(collection_management, dict):
            merged_overrides = dict(option.get("platform_specific_overrides") or {})
            merged_overrides["collection_management"] = collection_management
            option["platform_specific_overrides"] = merged_overrides
        category_selection_plan = _build_category_selection_plan(
            {"category_options": item.get("available_categories") or fallback_item.get("available_categories") or []},
            item,
            str(item.get("category") or ""),
            publication_policy=publication_policy,
        )
        if category_selection_plan:
            merged_overrides = dict(option.get("platform_specific_overrides") or {})
            merged_overrides["category_selection_plan"] = category_selection_plan
            option["platform_specific_overrides"] = merged_overrides
        selected_options = item.get("selected_options")
        if isinstance(selected_options, dict):
            merged_overrides = dict(option.get("platform_specific_overrides") or {})
            merged_overrides.update(selected_options)
            option["platform_specific_overrides"] = merged_overrides
        platform_overrides = item.get("platform_specific_overrides")
        if isinstance(platform_overrides, dict):
            merged_overrides = dict(option.get("platform_specific_overrides") or {})
            merged_overrides.update(platform_overrides)
            option["platform_specific_overrides"] = merged_overrides
        platform_options[platform] = option
    payload["items"] = items
    payload["platform_options"] = platform_options
    payload["publication_policy"] = publication_policy
    payload.setdefault("generated_at", fallback.get("generated_at") or _now_iso())
    payload.setdefault("status", "ready" if items else "blocked")
    return payload


def _repair_policy_collection_choice(item: dict[str, Any], fallback_item: dict[str, Any], publication_policy: dict[str, Any]) -> str:
    merged = {**fallback_item, **item}
    target = {
        "platform": merged.get("platform"),
        "title": merged.get("title"),
        "body": merged.get("body"),
        "summary": merged.get("summary"),
        "tags": merged.get("tags"),
        "account_label": merged.get("account_label"),
        "creator_profile_name": merged.get("creator_profile_name"),
    }
    available = _merge_unique_strings(
        item.get("available_collections"),
        [str(value).strip() for value in (fallback_item.get("available_collections") or []) if str(value).strip()],
    )
    if available:
        return _choose_collection_by_policy(publication_policy, available, target)
    existing = str(fallback_item.get("collection_name") or "").strip()
    if not existing:
        return ""
    return _choose_collection_by_policy(publication_policy, [existing], target)


def _repair_policy_category_choice(item: dict[str, Any], fallback_item: dict[str, Any], publication_policy: dict[str, Any]) -> str:
    merged = {**fallback_item, **item}
    target = {
        "platform": merged.get("platform"),
        "title": merged.get("title"),
        "body": merged.get("body"),
        "summary": merged.get("summary"),
        "tags": merged.get("tags"),
        "account_label": merged.get("account_label"),
        "creator_profile_name": merged.get("creator_profile_name"),
    }
    available = _merge_unique_strings(
        item.get("available_categories"),
        [str(value).strip() for value in (fallback_item.get("available_categories") or []) if str(value).strip()],
    )
    if available:
        return _choose_category_by_policy(publication_policy, available, target)
    existing = str(fallback_item.get("category") or "").strip()
    if not existing:
        return ""
    return _choose_category_by_policy(publication_policy, [existing], target)


def _load_cache() -> dict[str, Any]:
    with _CACHE_LOCK:
        for path in _cache_path_candidates():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("version") == CACHE_VERSION and isinstance(payload.get("records"), dict):
                return payload["records"]
        return {}


def _save_cache(records: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps({"version": CACHE_VERSION, "records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _cache_path_candidates() -> list[Path]:
    candidates: list[Path] = []
    for path in (CACHE_PATH, LEGACY_CACHE_PATH):
        if path in candidates:
            continue
        candidates.append(path)
    return candidates


def build_cached_publication_scheme(
    *,
    creator_profile_id: str,
    creator_profile_name: str,
    folder_path: str,
    browser: str,
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    records = _load_cache()
    cache_key = _cache_key(str(creator_profile_id or "").strip(), _normalize_browser(browser))
    record = records.get(cache_key) if isinstance(records.get(cache_key), dict) else None
    if not isinstance(record, dict):
        return {
            "status": "blocked",
            "blocked_reasons": [f"未找到 {cache_key} 的 publication intelligence 缓存。"],
            "platform_options": {},
            "items": [],
        }
    plan = {
        "creator_profile_id": str(creator_profile_id or "").strip(),
        "creator_profile_name": str(creator_profile_name or "").strip(),
        "targets": [target for target in targets if isinstance(target, dict)],
    }
    return _build_scheme_from_record(
        plan=plan,
        record=record,
        folder_path=folder_path,
        browser=_normalize_browser(browser),
    )


def _cache_key(profile_id: str, browser: str) -> str:
    return f"{profile_id or 'default'}::{browser or 'browser-agent'}"


def _normalize_browser(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"edge", "chrome", "firefox", "browser-agent"} else "browser-agent"


def _normalize_platform(value: Any) -> str | None:
    return normalize_publication_platform(value)


def _creator_credentials(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    creator_profile = profile.get("creator_profile") if isinstance(profile, dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile, dict) else {}
    credentials = publishing.get("platform_credentials") if isinstance(publishing, dict) else []
    if not isinstance(credentials, list):
        return []
    return [item for item in credentials if isinstance(item, dict)]


async def _probe_real_platform_inventory(
    *,
    targets: list[dict[str, Any]],
    creator_profile: dict[str, Any] | None,
    browser: str,
    platforms: list[str],
    plan: dict[str, Any] | None = None,
    folder_path: str = "",
    draft_upload_probe: bool = False,
) -> dict[str, Any]:
    if not platforms:
        return {"status": "skipped", "source": "empty_platforms", "platforms": {}}
    settings = get_settings()
    content_sample = _content_sample_for_probe(targets, plan=plan, folder_path=folder_path)
    result = await probe_browser_agent_publication_inventory(
        base_url=str(getattr(settings, "publication_browser_agent_base_url", "") or ""),
        auth_token=str(getattr(settings, "publication_browser_agent_auth_token", "") or ""),
        browser=browser,
        creator_profile_id=str((creator_profile or {}).get("id") or ""),
        platforms=platforms,
        content_sample=content_sample,
        mode="inventory_with_draft_upload_no_publish" if draft_upload_probe else "inventory_only_no_publish",
        request_timeout_sec=max(10, int(getattr(settings, "publication_browser_agent_timeout_sec", 60) or 60)),
    )
    result["source"] = "browser_agent_inventory"
    return result


def _content_sample_for_probe(targets: list[dict[str, Any]], *, plan: dict[str, Any] | None = None, folder_path: str = "") -> dict[str, Any]:
    first = next((target for target in targets if isinstance(target, dict)), {})
    media_path, media_path_source = _resolve_probe_media_path(plan=plan, folder_path=folder_path)
    return {
        "title": str(first.get("title") or ""),
        "body": str(first.get("body") or "")[:1200],
        "tags": [str(item) for item in (first.get("tags") or []) if str(item).strip()][:20],
        "media_path": media_path,
        "media_path_source": media_path_source,
        "folder_path": str(folder_path or ""),
        "platform_titles": {
            str(target.get("platform") or ""): str(target.get("title") or "")
            for target in targets
            if isinstance(target, dict) and target.get("platform")
        },
    }


def _resolve_probe_media_path(*, plan: dict[str, Any] | None = None, folder_path: str = "") -> tuple[str, str]:
    explicit_media_path = str((plan or {}).get("media_path") or "").strip()
    if explicit_media_path:
        return explicit_media_path, "plan_media_path"

    folder = Path(str(folder_path or "").strip())
    if not folder.is_dir():
        return "", "missing"

    video_candidates: list[Path] = []
    try:
        video_candidates = [
            item
            for item in folder.iterdir()
            if item.is_file() and item.suffix.lower() in PROBE_VIDEO_SUFFIXES
        ]
    except OSError:
        return "", "missing"

    if not video_candidates:
        return "", "missing"

    primary_video = sorted(
        video_candidates,
        key=lambda item: (-_probe_media_file_size(item), item.name.lower()),
    )[0]
    return str(primary_video), "folder_primary_video"


def _probe_media_file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _normalize_inventory_platform_options(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    status = str(value.get("status") or "").strip().lower()
    normalized: dict[str, Any] = {
        "inventory_status": status or "unknown",
        "inventory_message": str(value.get("message") or "").strip(),
        "route": value.get("route") if isinstance(value.get("route"), dict) else {},
        "field_groups": [item for item in (value.get("field_groups") or []) if isinstance(item, dict)],
        "option_groups": [item for item in (value.get("option_groups") or []) if isinstance(item, dict)],
        "coverage": value.get("coverage") if isinstance(value.get("coverage"), dict) else {},
        "evidence": value.get("evidence") if isinstance(value.get("evidence"), dict) else {},
        "framework_inventory": value.get("framework_inventory") if isinstance(value.get("framework_inventory"), dict) else {},
        "operation_steps": [item for item in (value.get("operation_steps") or []) if isinstance(item, dict)],
        "platform_warnings": [str(item).strip() for item in (value.get("warnings") or []) if str(item).strip()],
        "source": "browser_agent_inventory" if status in {"ok", "completed", "ready", "partial"} else "",
    }
    option_groups = normalized["option_groups"]
    collections = _options_from_groups(option_groups, {"collection", "collections", "playlist", "playlists", "album", "albums", "合集", "栏目", "专辑"})
    collection_catalog = _merge_collection_catalog(
        _normalize_collection_catalog(value, fallback_names=collections),
        _collection_catalog_from_option_groups(option_groups),
    )
    real_selectable_catalog_names = [
        str(entry.get("name") or "").strip()
        for entry in collection_catalog
        if (
            isinstance(entry, dict)
            and entry.get("selectable")
            and str(entry.get("name") or "").strip()
            and str(entry.get("source") or "").strip() != "publish_form"
        )
    ]
    form_selectable_catalog_names = [
        str(entry.get("name") or "").strip()
        for entry in collection_catalog
        if (
            isinstance(entry, dict)
            and entry.get("selectable")
            and str(entry.get("name") or "").strip()
            and str(entry.get("source") or "").strip() == "publish_form"
        )
    ]
    selectable_catalog_names = _merge_unique_strings(real_selectable_catalog_names, form_selectable_catalog_names)
    if selectable_catalog_names:
        collections = _merge_unique_strings(selectable_catalog_names, collections)
    categories = _options_from_groups(option_groups, {"category", "categories", "section", "sections", "partition", "分区", "分类"})
    declarations = _options_from_groups(option_groups, {"declaration", "declarations", "statement", "statements", "声明", "原创声明", "内容类型声明"})
    group_chats = _options_from_groups(option_groups, {"group", "groups", "chat", "chats", "群聊"})
    if collections:
        normalized["collection_suggestions"] = collections
        normalized["real_collection_source"] = "browser_agent_inventory"
    if collection_catalog:
        normalized["collection_catalog"] = collection_catalog
    if categories:
        normalized["category_options"] = categories
        normalized["real_category_source"] = "browser_agent_inventory"
    if declarations:
        normalized["declaration_options"] = declarations
    if group_chats:
        normalized["group_chat_options"] = group_chats
    return normalized


def _options_from_groups(groups: list[dict[str, Any]], keys: set[str]) -> list[str]:
    options: list[str] = []
    normalized_keys = {key.casefold() for key in keys}
    for group in groups:
        group_key = str(group.get("key") or group.get("id") or group.get("name") or group.get("label") or group.get("title") or "").strip()
        if not group_key:
            continue
        if re.search(r"catalog|目录", group_key, re.IGNORECASE):
            continue
        haystack = group_key.casefold()
        if not any(key in haystack for key in normalized_keys):
            continue
        options.extend(_clean_option_names(group.get("options")))
        options.extend(_clean_option_names(group.get("values")))
    return _merge_unique_strings([], options)


def _collection_catalog_from_option_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    key_terms = {
        "collection",
        "collections",
        "playlist",
        "playlists",
        "album",
        "albums",
        "season",
        "seasons",
        "series",
        "catalog",
        "合集",
        "栏目",
        "专辑",
        "目录",
    }
    normalized_terms = {term.casefold() for term in key_terms}
    for group in groups:
        group_key = str(group.get("key") or group.get("label") or group.get("title") or "").strip().casefold()
        if not any(term in group_key for term in normalized_terms):
            continue
        values = group.get("values")
        if isinstance(values, list):
            entries.extend(_normalize_collection_catalog({"collection_catalog": values}))
    return _merge_collection_catalog([], entries)


def _platform_record_has_real_inventory(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("has_real_platform_options"):
        return True
    return bool(
        value.get("collection_suggestions")
        or value.get("collection_catalog")
        or value.get("category_options")
        or value.get("declaration_options")
        or value.get("group_chat_options")
        or _has_strong_inventory_evidence(value.get("evidence"))
        or (str(value.get("inventory_status") or "").lower() in {"ok", "completed", "ready", "partial"} and value.get("option_groups"))
    )


def _has_strong_inventory_evidence(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    surfaces = value.get("by_surface")
    if not isinstance(surfaces, list):
        return False
    return any(isinstance(item, dict) and str(item.get("confidence") or "") == "strong" for item in surfaces)


def _creator_platform_metadata(profile: dict[str, Any] | None, credentials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    creator_profile = profile.get("creator_profile") if isinstance(profile, dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile, dict) else {}
    metadata: dict[str, dict[str, Any]] = {}
    for container_key in ("platform_catalog", "platform_metadata", "platform_capabilities", "publication_platforms"):
        raw_container = publishing.get(container_key) if isinstance(publishing, dict) else None
        if isinstance(raw_container, dict):
            for raw_platform, raw_value in raw_container.items():
                platform = _normalize_platform(raw_platform)
                if platform and isinstance(raw_value, dict):
                    metadata[platform] = _merge_real_platform_metadata(metadata.get(platform, {}), raw_value)
        elif isinstance(raw_container, list):
            for raw_value in raw_container:
                if not isinstance(raw_value, dict):
                    continue
                platform = _normalize_platform(raw_value.get("platform") or raw_value.get("key"))
                if platform:
                    metadata[platform] = _merge_real_platform_metadata(metadata.get(platform, {}), raw_value)
    for credential in credentials:
        platform = _normalize_platform(credential.get("platform"))
        if not platform:
            continue
        metadata[platform] = _merge_real_platform_metadata(metadata.get(platform, {}), credential)
    return metadata


def _merge_real_platform_metadata(current: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    collections = _extract_option_names(raw, ("collections", "collection_options", "collection_suggestions", "playlists", "playlist_options", "albums"))
    collection_catalog = _normalize_collection_catalog(raw, fallback_names=collections)
    categories = _extract_option_names(raw, ("categories", "category_options", "category_suggestions", "sections", "section_options"))
    visibility_modes = _extract_option_names(raw, ("visibility_modes", "publish_modes"))
    if collections:
        merged["collection_suggestions"] = _merge_unique_strings(merged.get("collection_suggestions"), collections)
        merged["real_collection_source"] = "creator_profile"
    if collection_catalog:
        merged["collection_catalog"] = _merge_collection_catalog(merged.get("collection_catalog"), collection_catalog)
    if categories:
        merged["category_options"] = _merge_unique_strings(merged.get("category_options"), categories)
        merged["real_category_source"] = "creator_profile"
    if visibility_modes:
        merged["visibility_modes"] = _merge_unique_strings(merged.get("visibility_modes"), visibility_modes)
    if "supports_scheduled_publish" in raw:
        merged["supports_scheduled_publish"] = bool(raw.get("supports_scheduled_publish"))
    if raw.get("required_fields"):
        merged["required_fields"] = _merge_unique_strings(merged.get("required_fields"), _clean_string_list(raw.get("required_fields")))
    return merged


def _extract_option_names(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for key in keys:
        names.extend(_clean_option_names(raw.get(key)))
    return _merge_unique_strings([], names)


def _clean_option_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、;\n]+", value) if item.strip()]
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("name") or item.get("title") or item.get("label") or item.get("text") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                names.append(text)
        return names
    return []


def _normalize_collection_catalog(raw: dict[str, Any], *, fallback_names: list[str] | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key in ("collection_catalog", "collections", "collection_options", "collection_suggestions", "playlist_catalog", "playlists", "playlist_options", "albums"):
        value = raw.get(key)
        if isinstance(value, list):
            for item in value:
                entry = _normalize_collection_catalog_entry(item)
                if entry:
                    entries.append(entry)
        elif isinstance(value, dict):
            for item in value.values():
                entry = _normalize_collection_catalog_entry(item)
                if entry:
                    entries.append(entry)
    for name in fallback_names or []:
        entry = _normalize_collection_catalog_entry({"name": name, "selectable": True, "source": "publish_form"})
        if entry:
            entries.append(entry)
    return _merge_collection_catalog([], entries)


def _normalize_collection_catalog_entry(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        name = str(value.get("name") or value.get("title") or value.get("label") or value.get("text") or "").strip()
        raw_status = str(value.get("status") or value.get("state") or "").strip()
        raw_selectable = value.get("selectable")
        video_count = value.get("video_count", value.get("count", value.get("item_count", value.get("works_count"))))
        source = str(value.get("source") or "").strip()
        note = str(value.get("note") or value.get("message") or value.get("reason") or "").strip()
    else:
        name = str(value or "").strip()
        raw_status = ""
        raw_selectable = None
        video_count = None
        source = ""
        note = ""
    if not name:
        return {}
    status_text = " ".join(part for part in (raw_status, note, name) if part)
    selectable = bool(raw_selectable) if raw_selectable is not None else not bool(
        re.search(r"未公开展示|有效剧集数不足|不可选|不能选择|empty|unselectable|insufficient", status_text, re.IGNORECASE)
    )
    try:
        normalized_count: int | None = int(video_count) if video_count is not None and str(video_count).strip() != "" else None
    except (TypeError, ValueError):
        normalized_count = None
    status = raw_status or ("selectable" if selectable else "exists_but_unselectable")
    return {
        "name": name,
        "status": status,
        "selectable": selectable,
        "video_count": normalized_count,
        "source": source or ("publish_form" if selectable else "account_catalog"),
        "note": note,
    }


def _merge_collection_catalog(left: Any, right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in [*([item for item in left if isinstance(item, dict)] if isinstance(left, list) else []), *right]:
        normalized = _normalize_collection_catalog_entry(entry)
        if not normalized:
            continue
        key = _normalize_collection_match_key(normalized["name"])
        existing = merged.get(key, {})
        existing_source = str(existing.get("source") or "")
        normalized_source = str(normalized.get("source") or "")
        if existing and existing_source == "publish_form" and normalized_source and normalized_source != "publish_form":
            selectable = bool(normalized.get("selectable"))
        elif existing and normalized_source == "publish_form" and existing_source and existing_source != "publish_form":
            selectable = bool(existing.get("selectable"))
        else:
            selectable = bool(existing.get("selectable")) or bool(normalized.get("selectable"))
        merged[key] = {
            **existing,
            **{key_name: value for key_name, value in normalized.items() if value not in ("", None)},
            "selectable": selectable,
        }
    return list(merged.values())[:50]


def _clean_string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in (value if isinstance(value, list) else []) if str(item).strip()]


def _merge_unique_strings(left: Any, right: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in [*(_clean_option_names(left) if not isinstance(left, list) else _clean_string_list(left)), *right]:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:30]


def _content_key(targets: list[dict[str, Any]]) -> str:
    text = " ".join(str(target.get("title") or "") + " " + str(target.get("body") or "") for target in targets)
    compact = re.sub(r"\s+", " ", text).strip().lower()
    return compact[:240]


def _summarize_content(targets: list[dict[str, Any]]) -> dict[str, str]:
    text = _content_key(targets)
    topic = "数码装备评测"
    content_type = "review"
    if re.search(r"edc|手电|装备|gear|flashlight", text, re.IGNORECASE):
        topic = "EDC 数码装备评测"
    if re.search(r"开箱|新品|unbox", text, re.IGNORECASE):
        content_type = "unboxing_review"
    return {"topic": topic, "content_type": content_type}


def _merge_platform_slots(fallback: dict[str, Any], llm_slots: dict[str, Any], platforms: list[str]) -> dict[str, Any]:
    merged = deepcopy(fallback)
    for raw_platform, slots in llm_slots.items():
        platform = _normalize_platform(raw_platform)
        if not platform or platform not in platforms or not isinstance(slots, list):
            continue
        normalized_slots = []
        for slot in slots[:3]:
            if not isinstance(slot, dict):
                continue
            time = _normalize_time_slot(slot.get("time"))
            if not time:
                continue
            normalized_slots.append({"time": time, "reason": str(slot.get("reason") or _default_slot_reason(platform, time))[:160]})
        if normalized_slots:
            merged[platform] = normalized_slots
    return merged


def _normalize_time_slot(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"(\d{1,2})[:：](\d{1,2})", text) or re.search(r"(\d{1,2})点(?:(\d{1,2})分?)?", text)
    if not match:
        return "20:00"
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2) or 0)))
    return f"{hour:02d}:{minute:02d}"


def _next_local_datetime(slot: str, *, day_offset: int = 0) -> str:
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    hour, minute = [int(part) for part in _normalize_time_slot(slot).split(":", 1)]
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    if scheduled <= now + timedelta(minutes=30):
        scheduled += timedelta(days=1)
    return scheduled.strftime("%Y-%m-%dT%H:%M")


def _choose_real_collection_name(
    capability: dict[str, Any],
    target: dict[str, Any],
    *,
    publication_policy: dict[str, Any] | None = None,
) -> str:
    suggestions = [str(item).strip() for item in capability.get("collection_suggestions") or [] if str(item).strip()]
    if not suggestions:
        return ""
    policy_collection = _choose_collection_by_policy(publication_policy, suggestions, target)
    if policy_collection:
        return policy_collection
    if _preferred_collection_name_by_policy(publication_policy, target):
        return ""
    title = str(target.get("title") or "")
    if re.search(r"edc|手电|装备|gear|flashlight", title, re.IGNORECASE):
        return suggestions[0]
    return suggestions[1] if len(suggestions) > 1 else suggestions[0]


def _build_collection_management_plan(
    capability: dict[str, Any],
    target: dict[str, Any],
    *,
    publication_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    platform = _normalize_platform(target.get("platform")) or ""
    kind = _platform_collection_kind(platform)
    if kind == "none":
        return {
            "kind": "none",
            "status": "not_supported",
            "target_collection_name": "",
            "selected_collection_name": "",
            "create_required": False,
            "post_publish_association_required": False,
            "reason": f"{platform_label(platform)} 当前没有合集/播放列表发布入口。",
        }
    suggestions = [str(item).strip() for item in capability.get("collection_suggestions") or [] if str(item).strip()]
    catalog = [item for item in (capability.get("collection_catalog") or []) if isinstance(item, dict)]
    preferred = _preferred_collection_name_by_policy(publication_policy, target)
    selected = _choose_collection_by_policy(publication_policy, suggestions, target) if preferred else ""
    if not preferred:
        selected = _choose_real_collection_name(capability, target, publication_policy=publication_policy)
        preferred = selected
    if not preferred and suggestions:
        preferred = suggestions[0]
        selected = suggestions[0]
    if selected:
        return {
            "kind": kind,
            "status": "select_existing",
            "target_collection_name": preferred,
            "selected_collection_name": selected,
            "create_required": False,
            "post_publish_association_required": False,
            "reason": f"发布页可直接选择已有{_collection_kind_label(kind)}。",
        }
    matched_catalog = _find_collection_catalog_entry(catalog, preferred)
    if matched_catalog:
        selectable = bool(matched_catalog.get("selectable"))
        return {
            "kind": kind,
            "status": "exists_but_not_selectable_on_publish_form" if not selectable else "exists_in_catalog_not_on_form",
            "target_collection_name": str(matched_catalog.get("name") or preferred),
            "selected_collection_name": "",
            "create_required": False,
            "post_publish_association_required": True,
            "reason": f"账号目录里已有{_collection_kind_label(kind)}，但当前发布页没有可选入口；发布后需要走平台的合集管理/播放列表管理关联。",
            "catalog_entry": matched_catalog,
        }
    if preferred:
        return {
            "kind": kind,
            "status": "needs_create",
            "target_collection_name": preferred,
            "selected_collection_name": "",
            "create_required": True,
            "post_publish_association_required": True,
            "reason": f"当前账号没有读到目标{_collection_kind_label(kind)}，需要先创建并保存到账号目录，后续同类型视频复用同名{_collection_kind_label(kind)}。",
        }
    return {
        "kind": kind,
        "status": "not_configured",
        "target_collection_name": "",
        "selected_collection_name": "",
        "create_required": False,
        "post_publish_association_required": False,
        "reason": "没有账号规则或平台真实数据指向可用合集。不会自动编造合集名。",
    }


def _platform_collection_kind(platform: str) -> str:
    if platform == "youtube":
        return "playlist"
    if platform == "x":
        return "none"
    return "collection"


def _collection_kind_label(kind: str) -> str:
    return "播放列表" if kind == "playlist" else "合集"


def _preferred_collection_name_by_policy(publication_policy: dict[str, Any] | None, target: dict[str, Any]) -> str:
    policy = publication_policy if isinstance(publication_policy, dict) else {}
    platform = _normalize_platform(target.get("platform")) or ""
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "preferred_collection":
            continue
        if not _publication_rule_applies_to_platform(rule, platform):
            continue
        if not _publication_rule_applies_to_content(rule, target):
            continue
        preferred_name = str(rule.get("preferred_collection_name") or "").strip()
        if preferred_name:
            return preferred_name
    return ""


def _find_collection_catalog_entry(catalog: list[dict[str, Any]], preferred_name: str) -> dict[str, Any]:
    if not preferred_name:
        return {}
    normalized_preferred = _normalize_collection_match_key(preferred_name)
    for entry in catalog:
        name = str(entry.get("name") or "").strip()
        if name and _normalize_collection_match_key(name) == normalized_preferred:
            return dict(entry)
    for entry in catalog:
        name = str(entry.get("name") or "").strip()
        if name and normalized_preferred in _normalize_collection_match_key(name):
            return dict(entry)
    return {}


def _choose_collection_by_policy(publication_policy: dict[str, Any] | None, suggestions: list[str], target: dict[str, Any]) -> str:
    policy = publication_policy if isinstance(publication_policy, dict) else {}
    platform = _normalize_platform(target.get("platform")) or ""
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "preferred_collection":
            continue
        if not _publication_rule_applies_to_platform(rule, platform):
            continue
        if not _publication_rule_applies_to_content(rule, target):
            continue
        preferred_name = str(rule.get("preferred_collection_name") or "").strip()
        if not preferred_name:
            continue
        matched = _find_collection_option(suggestions, preferred_name)
        if matched:
            return matched
        if not rule.get("requires_real_option", True):
            return preferred_name
    return ""


def _publication_rule_applies_to_platform(rule: dict[str, Any], platform: str) -> bool:
    platforms = [str(item or "") for item in (rule.get("platforms") or ["*"])]
    return "*" in platforms or platform in platforms


def _publication_rule_applies_to_content(rule: dict[str, Any], target: dict[str, Any]) -> bool:
    pattern = str(rule.get("content_pattern") or "").strip()
    if pattern == "edc_toy_unboxing" and not _is_edc_toy_unboxing_content(target):
        return False
    text = _target_content_text(target).casefold()
    keywords_all = [item.casefold() for item in _clean_string_list(rule.get("content_keywords_all"))]
    keywords_any = [item.casefold() for item in _clean_string_list(rule.get("content_keywords_any"))]
    if keywords_all and not all(keyword in text for keyword in keywords_all):
        return False
    if keywords_any and not any(keyword in text for keyword in keywords_any):
        return False
    return True


def _is_edc_toy_unboxing_content(target: dict[str, Any]) -> bool:
    text = _target_content_text(target)
    lowered = text.casefold()
    has_edc = bool(re.search(r"edc|随身装备|随身玩具|随身把玩", lowered, re.IGNORECASE))
    has_toy_or_unbox = bool(re.search(r"玩具|潮玩|把玩|推牌|音叉|开箱|上手|unbox|fidget|toy", lowered, re.IGNORECASE))
    return has_edc and has_toy_or_unbox


def _target_content_text(target: dict[str, Any]) -> str:
    return " ".join(
        [
            str(target.get("title") or ""),
            str(target.get("body") or ""),
            str(target.get("summary") or ""),
            " ".join(str(item) for item in (target.get("tags") or []) if str(item).strip()),
        ]
    )


def _find_collection_option(options: list[str], preferred_name: str) -> str:
    normalized_preferred = _normalize_collection_match_key(preferred_name)
    for option in options:
        if _normalize_collection_match_key(option) == normalized_preferred:
            return option
    for option in options:
        if normalized_preferred in _normalize_collection_match_key(option):
            return option
    return ""


def _normalize_collection_match_key(value: str) -> str:
    return re.sub(r"[\s\-_/·・.。:：|｜]+", "", str(value or "").casefold())


def _choose_real_category(
    capability: dict[str, Any],
    target: dict[str, Any],
    *,
    publication_policy: dict[str, Any] | None = None,
) -> str:
    categories = [str(item).strip() for item in capability.get("category_options") or [] if str(item).strip()]
    if not categories:
        return ""
    policy_category = _choose_category_by_policy(publication_policy, categories, target)
    if policy_category:
        return policy_category
    title = str(target.get("title") or "")
    platform = _normalize_platform(target.get("platform")) or ""
    if platform == "bilibili" and re.search(r"edc|户外|装备|手电|gear|flashlight", title, re.IGNORECASE):
        for preferred in ("户外潮流", "户外", "生活/出行", "出行", "数码"):
            matched = next((item for item in categories if preferred in item), "")
            if matched:
                if preferred == "户外潮流" and any("生活兴趣" in item for item in categories):
                    return "生活兴趣/户外潮流"
                return matched
    if re.search(r"youtube", str(target.get("platform") or ""), re.IGNORECASE):
        return categories[0]
    if re.search(r"数码|手电|edc|gear|flashlight", title, re.IGNORECASE):
        return categories[0]
    return categories[1] if len(categories) > 1 else categories[0]


def _choose_category_by_policy(publication_policy: dict[str, Any] | None, categories: list[str], target: dict[str, Any]) -> str:
    policy = publication_policy if isinstance(publication_policy, dict) else {}
    platform = _normalize_platform(target.get("platform")) or ""
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "preferred_category":
            continue
        if not _publication_rule_applies_to_platform(rule, platform):
            continue
        if not _publication_rule_applies_to_content(rule, target):
            continue
        preferred_name = str(rule.get("preferred_category_name") or "").strip()
        if not preferred_name:
            continue
        matched = _find_collection_option(categories, preferred_name)
        if matched:
            return matched
        category_path = [str(item).strip() for item in (rule.get("preferred_category_path") or []) if str(item).strip()]
        if category_path:
            display = "/".join(category_path)
            matched = _find_collection_option(categories, display) or _find_collection_option(categories, category_path[-1])
            if matched:
                return display
            if not rule.get("requires_real_option", True):
                return display
        if not rule.get("requires_real_option", True):
            return preferred_name
    return ""


def _build_category_selection_plan(
    capability: dict[str, Any],
    target: dict[str, Any],
    category: str,
    *,
    publication_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    platform = _normalize_platform(target.get("platform")) or ""
    if platform != "bilibili" or not category:
        return {}
    policy = publication_policy if isinstance(publication_policy, dict) else {}
    categories = [str(item).strip() for item in capability.get("category_options") or [] if str(item).strip()]
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "preferred_category":
            continue
        if not _publication_rule_applies_to_platform(rule, platform):
            continue
        if not _publication_rule_applies_to_content(rule, target):
            continue
        path = [str(item).strip() for item in (rule.get("preferred_category_path") or []) if str(item).strip()]
        if path:
            return {
                "platform": "bilibili",
                "mode": "hierarchical_page_selection",
                "category_path": path,
                "category_display": "/".join(path),
                "legacy_api_fallback": str(rule.get("legacy_api_fallback_category") or "").strip(),
                "visible_category_options": categories[:40],
                "source": str(rule.get("source") or ""),
                "note": "B站页面分区与旧接口分区不完全一致；正式发布应按页面层级选择 category_path，接口兜底只用于无法展开页面时提示人工处理。",
            }
    if "/" in category:
        return {
            "platform": "bilibili",
            "mode": "path_text_selection",
            "category_path": [part for part in category.split("/") if part],
            "category_display": category,
            "legacy_api_fallback": "",
            "visible_category_options": categories[:40],
            "source": "scheme_category",
        }
    return {}


def _select_platform_specific_options(capability: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    declarations = [str(item).strip() for item in capability.get("declaration_options") or [] if str(item).strip()]
    group_chats = [str(item).strip() for item in capability.get("group_chat_options") or [] if str(item).strip()]
    field_groups = [item for item in capability.get("field_groups") or [] if isinstance(item, dict)]
    option_groups = [item for item in capability.get("option_groups") or [] if isinstance(item, dict)]
    operation_steps = [item for item in capability.get("operation_steps") or [] if isinstance(item, dict)]
    title = str(target.get("title") or "")
    body = str(target.get("body") or "")
    content_text = f"{title} {body}"
    platform = _normalize_platform(target.get("platform")) or ""
    tags = [str(item).strip().lstrip("#") for item in (target.get("tags") or []) if str(item).strip()]

    if declarations:
        selected_declarations = _recommend_declarations(declarations, content_text)
        selected["declaration_options"] = declarations
        selected["selected_declarations"] = selected_declarations
        if platform == "youtube" and any(re.search(r"儿童|coppa|kids", option, re.IGNORECASE) for option in declarations):
            selected["made_for_kids"] = False
            selected["made_for_kids_rationale"] = "内容主题为 EDC/装备评测，不面向儿童；该结论只在 YouTube 页面真实出现儿童/COPPA声明入口时写入。"
    if group_chats:
        selected["group_chat_options"] = group_chats
        selected["selected_group_chat"] = _recommend_group_chat(group_chats, content_text)
    topic_plan = _build_topic_selection_plan(platform, tags, option_groups)
    if topic_plan:
        selected["topic_selection_plan"] = topic_plan
    if field_groups:
        selected["field_groups"] = field_groups[:12]
    if option_groups:
        selected["option_groups"] = option_groups[:12]
    if operation_steps:
        selected["operation_steps"] = operation_steps[:20]
    if capability.get("platform_warnings"):
        selected["platform_warnings"] = list(capability.get("platform_warnings") or [])[:8]
    if selected:
        selected["decision_policy"] = "only_choose_from_browser_agent_inventory"
    return selected


def _build_topic_selection_plan(platform: str, tags: list[str], option_groups: list[dict[str, Any]]) -> dict[str, Any]:
    if not tags:
        return {}
    if platform == "xiaohongshu":
        mode = "search_and_select_platform_topic_suggestions"
        note = "小红书话题必须在话题搜索/推荐结果中逐个选择，不能只把 #文本 写进正文。"
    elif platform in {"douyin", "kuaishou", "bilibili"}:
        mode = "prefer_platform_topic_suggestions_then_fallback_to_tag_input"
        note = "优先选择平台推荐/搜索到的真实话题项；没有匹配时才回退为普通标签输入。"
    else:
        return {}
    visible_topics = _options_from_groups(option_groups, {"topic", "topics", "话题", "标签", "hashtag", "hashtags"})
    return {
        "mode": mode,
        "requested_topics": tags[:10],
        "visible_topic_options": visible_topics[:20],
        "selection_required": platform == "xiaohongshu",
        "note": note,
    }


def _recommend_declarations(options: list[str], content_text: str) -> list[str]:
    lowered = content_text.casefold()
    selected: list[str] = []
    for option in options:
        option_lower = option.casefold()
        if any(token in option_lower for token in ("原创", "original")):
            selected.append(option)
            continue
        if "ai" in option_lower and re.search(r"ai|合成|生成", lowered, re.IGNORECASE):
            selected.append(option)
            continue
        if any(token in option_lower for token in ("营销", "广告", "commercial", "promotion")) and re.search(
            r"广告|推广|赞助|合作|promotion|sponsor", lowered, re.IGNORECASE
        ):
            selected.append(option)
    return selected[:6]


def _recommend_group_chat(options: list[str], content_text: str) -> str:
    if not options:
        return ""
    lowered = content_text.casefold()
    for option in options:
        if re.search(r"edc|装备|手电|gear|flashlight", lowered, re.IGNORECASE) and re.search(r"edc|装备|手电|gear", option, re.IGNORECASE):
            return option
    return options[0]


def _capability_summary(capability: dict[str, Any]) -> str:
    collections = "、".join([str(item) for item in capability.get("collection_suggestions") or []][:3])
    categories = "、".join([str(item) for item in capability.get("category_options") or []][:3])
    if capability.get("has_real_platform_options"):
        return f"真实平台数据：栏目/合集候选：{collections or '未读取到'}；分类候选：{categories or '未读取到'}。{capability.get('option_notes') or ''}"
    return "尚未完成真实平台摸底：当前只有登录会话引用，没有读取到平台已有合集/栏目/分类。不会自动填写这些字段。"


def _surface_keys(items: Any) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            value = str(item.get("key") or item.get("label") or "").strip()
        else:
            value = str(item).strip()
        if value:
            normalized.append(value)
    return normalized


def _capability_supports_effective_scheduled_publish(capability: dict[str, Any]) -> bool:
    if not capability.get("supports_scheduled_publish"):
        return False
    coverage = capability.get("coverage") if isinstance(capability.get("coverage"), dict) else {}
    missing_keys = set(_surface_keys(coverage.get("missing_required_surfaces")))
    if "schedule" in missing_keys:
        return False
    for surface in coverage.get("required_surfaces") or []:
        if not isinstance(surface, dict):
            continue
        if str(surface.get("key") or "").strip() != "schedule":
            continue
        if str(surface.get("status") or "").strip().lower() == "missing":
            return False
    return True


def _build_live_publish_preflight(
    capability: dict[str, Any],
    *,
    supports_scheduled_publish: bool | None = None,
) -> dict[str, Any]:
    coverage = capability.get("coverage") if isinstance(capability.get("coverage"), dict) else {}
    evidence = capability.get("evidence") if isinstance(capability.get("evidence"), dict) else {}
    required = _surface_keys(coverage.get("required_surfaces"))
    missing = _surface_keys(coverage.get("missing_required_surfaces"))
    effective_scheduled_publish = (
        _capability_supports_effective_scheduled_publish(capability)
        if supports_scheduled_publish is None
        else bool(supports_scheduled_publish)
    )
    if not effective_scheduled_publish:
        required = [item for item in required if item != "schedule"]
        missing = [item for item in missing if item != "schedule"]
    weak: list[str] = []
    by_surface = evidence.get("by_surface") if isinstance(evidence.get("by_surface"), list) else []
    for item in by_surface:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key and str(item.get("confidence") or "").strip().lower() == "weak":
            weak.append(key)
    status = "blocked" if missing else "ready"
    summary = "可进入正式发布执行器。"
    if missing:
        summary = "缺少发布页关键参数面：" + "、".join(missing[:8])
    elif weak:
        summary = "关键参数面已采到，但部分证据较弱：" + "、".join(weak[:8])
    return {
        "status": status,
        "policy": "block_final_publish_when_required_surface_missing",
        "required_surfaces": required,
        "missing_required_surfaces": missing,
        "weak_surfaces": weak,
        "summary": summary,
    }


def _probe_record_status(record: dict[str, Any]) -> str:
    platforms = record.get("platforms") if isinstance(record.get("platforms"), dict) else {}
    if any(isinstance(item, dict) and item.get("has_real_platform_options") for item in platforms.values()):
        return "real_options_cached"
    if record.get("probed_at"):
        return "login_reference_only"
    return "not_started"


def _probe_record_note(record: dict[str, Any]) -> str:
    if _probe_record_status(record) == "real_options_cached":
        return "已读取到真实平台选项并缓存；正式发布前仍会做页面/字段轻量验证。"
    if record.get("probed_at"):
        return "只确认了登录会话引用；尚未读取真实合集/栏目/分类，不能把默认候选当作平台数据。"
    return "尚未摸底平台页面。"


def _default_slot_reason(platform: str, slot: str) -> str:
    label = platform_label(platform)
    if platform in {"douyin", "xiaohongshu", "kuaishou", "bilibili", "youtube"}:
        return f"{label} 建议在 {slot} 覆盖晚间内容消费高峰。"
    if platform in {"wechat-channels", "toutiao"}:
        return f"{label} 建议在 {slot} 覆盖午间/资讯浏览时段。"
    return f"{label} 建议在 {slot} 覆盖工作日前后浏览时段。"


def _platform_mentioned(platform: str, text: str) -> bool:
    label = platform_label(platform)
    aliases = {
        "bilibili": ["b站", "哔哩", "bilibili"],
        "xiaohongshu": ["小红书", "rednote"],
        "douyin": ["抖音"],
        "kuaishou": ["快手"],
        "wechat-channels": ["视频号", "微信视频号"],
        "toutiao": ["头条"],
        "youtube": ["youtube", "油管"],
        "x": ["x", "twitter"],
    }
    lowered = text.lower()
    return label in text or any(alias.lower() in lowered for alias in aliases.get(platform, []))


def _extract_named_value(text: str, keywords: list[str]) -> str:
    for keyword in keywords:
        match = re.search(rf"{re.escape(keyword)}[：:为叫到放进]*\s*([A-Za-z0-9_\-\u4e00-\u9fff ]{{2,30}})", text)
        if match:
            value = re.split(r"[，,。；;]", match.group(1).strip())[0].strip()
            if value:
                return value[:30]
    return ""


def _extract_collection_name(text: str) -> str:
    move_match = re.search(r"(?:放到|放进|加入|归到)\s*([^，,。；;]{2,40}?)(合集|栏目|专辑)", text)
    if move_match:
        return f"{move_match.group(1).strip()}{move_match.group(2)}"[:40]
    return _extract_named_value(text, ["合集", "栏目", "专辑"])


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

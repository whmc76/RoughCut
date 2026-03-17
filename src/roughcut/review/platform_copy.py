from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.reasoning.base import Message

PLATFORM_ORDER = [
    ("bilibili", "B站", "简介", "标签"),
    ("xiaohongshu", "小红书", "正文", "话题"),
    ("douyin", "抖音", "简介", "标签"),
    ("kuaishou", "快手", "简介", "标签"),
    ("wechat_channels", "视频号", "简介", "标签"),
]


def build_transcript_for_packaging(subtitle_items: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    total = 0
    for item in subtitle_items:
        text = (item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        line = f"[{item.get('start_time', 0):.1f}-{item.get('end_time', 0):.1f}] {text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


async def build_packaging_fact_sheet(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = content_profile or {}
    if not _has_specific_subject_identity(profile):
        return {
            "status": "skipped",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "主体信息不明确，禁止写任何具体参数、升级倍率、发布时间或价格差异。",
        }

    evidence = [
        item for item in (profile.get("evidence") or [])
        if isinstance(item, dict) and (item.get("url") or item.get("title") or item.get("snippet"))
    ]
    if len(evidence) < 2:
        evidence.extend(
            await _search_packaging_evidence(
                source_name=source_name,
                content_profile=profile,
                subtitle_items=subtitle_items,
            )
        )
    evidence = _dedupe_evidence(evidence)
    if not evidence:
        return {
            "status": "unverified",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "未找到可核验来源，禁止写流明、毫瓦、射程、容量、功率、价格、发布时间和升级倍率。",
        }

    preferred_evidence = _prefer_official_evidence(
        evidence,
        brand=str(profile.get("subject_brand") or ""),
        model=str(profile.get("subject_model") or ""),
    )
    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在做短视频发布前的参数核验。"
            "只能根据下面给出的搜索证据，提炼已经被证据直接支持的事实。"
            "不要补全、不要猜测、不要根据常识扩写。"
            "数字参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率只有在证据里明确出现时才能写。"
            "如果证据不足，就返回空 verified_facts。"
            "输出 JSON："
            '{"verified_facts":[{"fact":"","source_url":"","source_title":""}],"official_sources":[{"title":"","url":""}],"guardrail_summary":""}'
            f"\n视频主体：{json.dumps({'brand': profile.get('subject_brand'), 'model': profile.get('subject_model'), 'subject_type': profile.get('subject_type')}, ensure_ascii=False)}"
            f"\n搜索证据：{json.dumps(preferred_evidence[:8], ensure_ascii=False)}"
        )
        response = await provider.complete(
            [
                Message(role="system", content="你是严格的事实核验助手，只输出 JSON。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=900,
            json_mode=True,
        )
        raw = response.as_json()
    except Exception:
        raw = {}

    fact_sheet = _normalize_fact_sheet(
        raw,
        fallback_evidence=preferred_evidence,
    )
    if not fact_sheet["verified_facts"]:
        fact_sheet["status"] = "unverified"
        fact_sheet["guardrail_summary"] = (
            fact_sheet.get("guardrail_summary")
            or "证据里没有足够明确的参数支持，禁止写参数、倍率和上市状态。"
        )
    else:
        fact_sheet["status"] = "verified"
    return fact_sheet


async def generate_platform_packaging(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    copy_style: str = "attention_grabbing",
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = get_reasoning_provider()
    transcript_text = build_transcript_for_packaging(subtitle_items)
    fact_sheet = await build_packaging_fact_sheet(
        source_name=source_name,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
    )
    fact_guardrail_text = _build_fact_guardrail_text(fact_sheet)
    author_prompt_text = _build_author_prompt_text(author_profile)
    prompt = (
        "你是多平台视频包装官，负责把字幕整理成适合不同平台发布的标题、简介和标签。"
        "内容默认按 EDC、刀具、工具、桌搭、开箱、收藏类创作者口吻处理。"
        "要求：\n"
        "1. 输出真实自然，不要像硬广，不编造事实。\n"
        "2. 刀具、EDC、工具相关内容必须保守合规，避免危险导向表述。\n"
        "3. 每个平台必须提供 5 个标题、1 段简介/正文、1 组标签，且五个平台的简介/正文不能只是轻微同义改写。\n"
        "4. 标题要有角度差异：爆点型、稳妥型、提问型、情绪型、结论型。\n"
        "5. 标签必须贴合产品、品类、场景、风格、视频类型。\n"
        "6. 不要输出空字段。\n"
        "7. 参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率，只能写在“已核验事实”里出现过的信息。\n"
        "8. 如果没有核验证据，改写成保守表达，只写到手体验、外观、做工、上手感受，不写具体参数。\n\n"
        "9. 如果给了作者信息，只能按平台策略选择最合适的 0 到 3 个字段自然带出，不要所有平台重复同一段自我介绍。\n"
        "10. 平台简介策略必须明显区分：\n"
        "- B站：先给核心判断，再说这期重点拆什么，可自然带作者专业身份或长期关注方向。\n"
        "- 小红书：像真实分享笔记，带一点作者人设、审美/使用偏好、到手感受。\n"
        "- 抖音：一句结果 + 一句记忆点，可带极短作者身份锚点，节奏要快。\n"
        "- 快手：像当面讲实话，直给、不绕，可带接地气的人设表达。\n"
        "- 视频号：稳妥可信，偏总结式，可带作者职业/内容定位增强可信度。\n\n"
        f"本次统一文案风格：{_copy_style_instruction(copy_style)}\n\n"
        f"{fact_guardrail_text}\n\n"
        f"{author_prompt_text}\n\n"
        "默认平台偏置：\n"
        f"- B站：{_platform_bias_instruction('B站')}\n"
        f"- 小红书：{_platform_bias_instruction('小红书')}\n"
        f"- 抖音：{_platform_bias_instruction('抖音')}\n"
        f"- 快手：{_platform_bias_instruction('快手')}\n"
        f"- 视频号：{_platform_bias_instruction('视频号')}\n\n"
        "请输出 JSON，格式如下：\n"
        "{"
        "\"highlights\":{"
        "\"product\":\"\",\"video_type\":\"\",\"strongest_selling_point\":\"\","
        "\"strongest_emotion\":\"\",\"title_hook\":\"\",\"engagement_question\":\"\""
        "},"
        "\"platforms\":{"
        "\"bilibili\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"xiaohongshu\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"douyin\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"kuaishou\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"wechat_channels\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]}"
        "}"
        "}\n\n"
        f"视频已知信息：{json.dumps(content_profile or {}, ensure_ascii=False)}\n"
        f"源文件名：{source_name}\n"
        f"字幕全文：\n{transcript_text}"
    )
    response = await provider.complete(
        [
            Message(
                role="system",
                content=(
                    "你是严谨的中文多平台视频包装策划。"
                    "优先输出真实玩家口吻、平台化表达、自然互动问题和合规标签。"
                ),
            ),
            Message(role="user", content=prompt),
        ],
        temperature=0.35,
        max_tokens=3200,
        json_mode=True,
    )
    packaging = normalize_platform_packaging(
        response.as_json(),
        content_profile=content_profile,
        copy_style=copy_style,
        fact_sheet=fact_sheet,
        author_profile=author_profile,
    )
    packaging["fact_sheet"] = fact_sheet
    return packaging


def normalize_platform_packaging(
    raw: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str = "attention_grabbing",
    fact_sheet: dict[str, Any] | None = None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    highlights = raw.get("highlights") if isinstance(raw.get("highlights"), dict) else {}
    normalized: dict[str, Any] = {
        "highlights": {
            "product": _normalize_highlight_product(highlights.get("product"), content_profile),
            "video_type": str(highlights.get("video_type") or _fallback_video_type(content_profile)).strip(),
            "strongest_selling_point": str(highlights.get("strongest_selling_point") or "").strip(),
            "strongest_emotion": str(highlights.get("strongest_emotion") or "").strip(),
            "title_hook": str(highlights.get("title_hook") or "").strip(),
            "engagement_question": str(highlights.get("engagement_question") or _fallback_question(content_profile)).strip(),
        },
        "platforms": {},
    }

    raw_platforms = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else {}
    for key, label, _, _ in PLATFORM_ORDER:
        platform_raw = raw_platforms.get(key) if isinstance(raw_platforms.get(key), dict) else {}
        titles = _normalize_titles(platform_raw.get("titles"), label=label, content_profile=content_profile, copy_style=copy_style)
        description = _normalize_platform_description(
            platform_raw.get("description"),
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
            author_profile=author_profile,
        )
        tags = _normalize_tags(platform_raw.get("tags"), content_profile=content_profile)
        normalized["platforms"][key] = {
            "titles": titles,
            "description": description,
            "tags": tags,
        }

    guarded = _enforce_packaging_fact_guardrails(
        normalized,
        content_profile=content_profile,
        copy_style=copy_style,
        fact_sheet=fact_sheet,
        author_profile=author_profile,
    )
    return _enforce_platform_description_variation(
        guarded,
        content_profile=content_profile,
        copy_style=copy_style,
        author_profile=author_profile,
    )


def render_platform_packaging_markdown(packaging: dict[str, Any]) -> str:
    highlights = packaging.get("highlights") or {}
    lines = [
        "# 视频爆点提炼",
        f"- 产品：{highlights.get('product', '')}",
        f"- 视频类型：{highlights.get('video_type', '')}",
        f"- 最强卖点：{highlights.get('strongest_selling_point', '')}",
        f"- 最强情绪点：{highlights.get('strongest_emotion', '')}",
        f"- 最适合标题的钩子：{highlights.get('title_hook', '')}",
        f"- 最适合评论区的问题：{highlights.get('engagement_question', '')}",
        "",
    ]

    platforms = packaging.get("platforms") or {}
    for key, label, body_label, tag_label in PLATFORM_ORDER:
        platform = platforms.get(key) or {}
        lines.append(f"# {label}")
        lines.append("## 标题")
        for idx, title in enumerate(platform.get("titles") or [], start=1):
            lines.append(f"{idx}. {title}")
        lines.append("")
        lines.append(f"## {body_label}")
        lines.append(platform.get("description") or "")
        lines.append("")
        lines.append(f"## {tag_label}")
        lines.append(" ".join(_hashify_tags(platform.get("tags") or [])))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_platform_packaging_markdown(output_path: Path, packaging: dict[str, Any]) -> Path:
    output_path.write_text(render_platform_packaging_markdown(packaging), encoding="utf-8")
    return output_path


async def _search_packaging_evidence(
    *,
    source_name: str,
    content_profile: dict[str, Any],
    subtitle_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    try:
        provider = get_search_provider()
    except Exception:
        return []

    transcript_text = build_transcript_for_packaging(subtitle_items, max_chars=1400)
    queries = _build_packaging_fact_queries(
        source_name=source_name,
        content_profile=content_profile,
        transcript_text=transcript_text,
    )
    results: list[dict[str, str]] = []
    for query in queries[:4]:
        try:
            items = await provider.search(query, max_results=4)
        except Exception:
            continue
        for item in items:
            results.append(
                {
                    "query": query,
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                }
            )
    return results


def _build_packaging_fact_queries(
    *,
    source_name: str,
    content_profile: dict[str, Any],
    transcript_text: str,
) -> list[str]:
    brand = str(content_profile.get("subject_brand") or "").strip()
    model = str(content_profile.get("subject_model") or "").strip()
    subject_type = str(content_profile.get("subject_type") or "").strip()
    queries: list[str] = []
    for item in content_profile.get("search_queries") or []:
        text = str(item).strip()
        if text:
            queries.append(text)
    if brand and model:
        queries.extend(
            [
                f"{brand} {model} 官方 参数",
                f"{brand} {model} 官网",
                f"{brand} {model} official specs",
            ]
        )
    if brand and model and subject_type:
        queries.append(f"{brand} {model} {subject_type} 官方")
    if not queries:
        stem = Path(source_name).stem
        if stem:
            queries.append(stem)
    if transcript_text and brand and model:
        queries.append(f"{brand} {model} 开箱")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in evidence:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        key = url or f"{title}|{snippet}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "query": str(item.get("query") or "").strip(),
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )
    return deduped


def _prefer_official_evidence(
    evidence: list[dict[str, str]],
    *,
    brand: str,
    model: str,
) -> list[dict[str, str]]:
    official = [item for item in evidence if _looks_officialish_source(item, brand=brand, model=model)]
    return official or evidence


def _looks_officialish_source(item: dict[str, str], *, brand: str, model: str) -> bool:
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    host = (urlparse(url).netloc or "").lower()
    merged = f"{title} {snippet} {host}".lower()
    if any(token in merged for token in (" official", "官网", "官方", "spec", "参数")):
        return True
    tokens = []
    for raw in (brand, model):
        normalized = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
        if len(normalized) >= 4:
            tokens.append(normalized)
    host_compact = re.sub(r"[^a-z0-9]+", "", host)
    return any(token in host_compact for token in tokens)


def _normalize_fact_sheet(raw: dict[str, Any], *, fallback_evidence: list[dict[str, str]]) -> dict[str, Any]:
    verified_facts: list[dict[str, str]] = []
    for item in raw.get("verified_facts") or []:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        source_title = str(item.get("source_title") or "").strip()
        if not fact:
            continue
        verified_facts.append(
            {
                "fact": fact,
                "source_url": source_url,
                "source_title": source_title,
            }
        )
    official_sources: list[dict[str, str]] = []
    for item in raw.get("official_sources") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if title or url:
            official_sources.append({"title": title, "url": url})
    if not official_sources:
        for item in fallback_evidence[:4]:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if title or url:
                official_sources.append({"title": title, "url": url})
    return {
        "status": "verified" if verified_facts else "unverified",
        "verified_facts": verified_facts,
        "official_sources": official_sources,
        "guardrail_summary": str(raw.get("guardrail_summary") or "").strip(),
    }


def _build_fact_guardrail_text(fact_sheet: dict[str, Any] | None) -> str:
    sheet = fact_sheet or {}
    facts = [str(item.get("fact") or "").strip() for item in sheet.get("verified_facts") or [] if str(item.get("fact") or "").strip()]
    sources = [str(item.get("url") or "").strip() for item in sheet.get("official_sources") or [] if str(item.get("url") or "").strip()]
    if not facts:
        return (
            "已核验事实：无。\n"
            "写作约束：禁止写具体参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率；"
            "只能写到手体验、外观、做工、手感、使用场景。"
        )
    source_text = "\n".join(f"- {item}" for item in sources[:4]) or "- 无"
    fact_text = "\n".join(f"- {item}" for item in facts[:8])
    return (
        "已核验事实（只能使用以下已核验信息）：\n"
        f"{fact_text}\n"
        "优先来源：\n"
        f"{source_text}"
    )


def _enforce_packaging_fact_guardrails(
    packaging: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    fact_sheet: dict[str, Any] | None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sheet = fact_sheet or {}
    verified_blob = "\n".join(str(item.get("fact") or "") for item in sheet.get("verified_facts") or [])
    guarded = {
        "highlights": dict(packaging.get("highlights") or {}),
        "platforms": {key: dict(value or {}) for key, value in (packaging.get("platforms") or {}).items()},
    }
    if sheet:
        guarded["fact_sheet"] = sheet

    highlights = guarded["highlights"]
    if _contains_unverified_claim(str(highlights.get("strongest_selling_point") or ""), verified_blob):
        highlights["strongest_selling_point"] = ""
    if _contains_unverified_claim(str(highlights.get("title_hook") or ""), verified_blob):
        highlights["title_hook"] = str((content_profile or {}).get("hook_line") or "").strip()
    if not _contains_confirmed_product_anchor(str(highlights.get("title_hook") or ""), content_profile):
        highlights["title_hook"] = _build_confirmed_title_hook(content_profile)

    for key, label, _, _ in PLATFORM_ORDER:
        platform = guarded["platforms"].get(key) or {}
        fallback_titles = build_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style)
        titles = list(platform.get("titles") or [])
        guarded_titles: list[str] = []
        for idx, title in enumerate(titles[:5]):
            replacement = fallback_titles[idx]
            if _contains_unverified_claim(title, verified_blob) or not _contains_confirmed_product_anchor(title, content_profile):
                guarded_titles.append(replacement)
            else:
                guarded_titles.append(title)
        platform["titles"] = guarded_titles + fallback_titles[len(guarded_titles):5]
        description = str(platform.get("description") or "").strip()
        if _contains_unverified_claim(description, verified_blob):
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
        guarded["platforms"][key] = platform
    return guarded


def _contains_unverified_claim(text: str, verified_blob: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if not _looks_like_fact_sensitive_claim(normalized):
        return False
    if not verified_blob.strip():
        return True
    normalized_blob = verified_blob.lower()
    lower_text = normalized.lower()
    numeric_tokens = re.findall(r"\d+(?:\.\d+)?", normalized)
    if numeric_tokens and any(token not in normalized_blob for token in numeric_tokens):
        return True
    risk_terms = [
        "翻倍",
        "提升",
        "增加",
        "发布",
        "首发",
        "闲鱼",
        "价格",
        "贵",
        "便宜",
        "一代",
        "二代",
    ]
    for term in risk_terms:
        if term in lower_text and term not in normalized_blob:
            return True
    return False


def _looks_like_fact_sensitive_claim(text: str) -> bool:
    lower_text = str(text or "").lower()
    if re.search(r"\d", lower_text):
        return True
    keywords = (
        "流明",
        "lm",
        "毫瓦",
        "mw",
        "mwh",
        "mah",
        "功率",
        "射程",
        "续航",
        "容量",
        "价格",
        "未发布",
        "发布",
        "闲鱼",
        "翻倍",
        "升级",
        "提升",
        "增加",
        "一代",
        "二代",
        "对比",
        "比一代",
        "比上一代",
        "多花",
    )
    return any(token in lower_text for token in keywords)


def _normalize_titles(value: Any, *, label: str, content_profile: dict[str, Any] | None, copy_style: str) -> list[str]:
    titles = [str(item).strip() for item in (value or []) if str(item).strip()]
    if len(titles) >= 5:
        return titles[:5]

    fallback = build_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style)
    seen: set[str] = set()
    merged: list[str] = []
    for title in titles + fallback:
        if title not in seen:
            seen.add(title)
            merged.append(title)
        if len(merged) >= 5:
            break
    return merged


def _normalize_tags(value: Any, content_profile: dict[str, Any] | None) -> list[str]:
    tags = [str(item).strip().lstrip("#") for item in (value or []) if str(item).strip()]
    if tags:
        return tags

    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    subject = _specific_subject_type(content_profile)
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    fallback = [brand, subject, theme]
    if _profile_mentions_edc(content_profile):
        fallback.append("EDC")
    fallback.extend(["开箱", "上手体验", "玩家分享"])
    return _dedupe_non_empty(fallback)[:8]


def _normalize_platform_description(
    value: Any,
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    author_profile: dict[str, Any] | None,
) -> str:
    description = str(value or "").strip()
    if not description:
        return build_fallback_description(
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
            author_profile=author_profile,
        )
    return _inject_author_context_into_description(label, description, author_profile)


def _enforce_platform_description_variation(
    packaging: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    author_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    platforms = packaging.get("platforms")
    if not isinstance(platforms, dict):
        return packaging

    seen_descriptions: list[str] = []
    for key, label, _, _ in PLATFORM_ORDER:
        platform = platforms.get(key)
        if not isinstance(platform, dict):
            continue
        description = str(platform.get("description") or "").strip()
        if not description:
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
            description = str(platform.get("description") or "").strip()
        if any(_description_similarity(description, item) >= 0.82 for item in seen_descriptions):
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
            description = str(platform.get("description") or "").strip()
        seen_descriptions.append(description)
    return packaging


def _description_similarity(left: str, right: str) -> float:
    left_normalized = re.sub(r"[\W_]+", "", str(left or "").lower())
    right_normalized = re.sub(r"[\W_]+", "", str(right or "").lower())
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(a=left_normalized, b=right_normalized).ratio()


def _inject_author_context_into_description(
    label: str,
    description: str,
    author_profile: dict[str, Any] | None,
) -> str:
    text = str(description or "").strip()
    if not text:
        return text
    author_sentence = _build_author_sentence(label, author_profile)
    if not author_sentence:
        return text
    if _description_has_author_anchor(text, author_profile):
        return text
    return _insert_sentence_before_question(text, author_sentence)


def _description_has_author_anchor(text: str, author_profile: dict[str, Any] | None) -> bool:
    normalized = _normalize_anchor_text(text)
    anchors = [
        _normalize_anchor_text(_author_public_name(author_profile)),
        _normalize_anchor_text(_author_identity(author_profile)),
        _normalize_anchor_text(_author_focus(author_profile)),
    ]
    return any(anchor and anchor in normalized for anchor in anchors)


def _insert_sentence_before_question(text: str, sentence: str) -> str:
    base = str(text or "").strip()
    author_sentence = str(sentence or "").strip().rstrip("。！？!?")
    if not base or not author_sentence:
        return base
    match = re.search(r"[^。！？!?]*[？?]\s*$", base)
    if not match:
        return f"{base.rstrip('。！？!?')}。{author_sentence}。"
    question = base[match.start():]
    leading = base[:match.start()].rstrip("。！？!? ")
    return f"{leading}。{author_sentence}{question}"


def _build_author_prompt_text(author_profile: dict[str, Any] | None) -> str:
    author_context = _author_context(author_profile)
    if not author_context:
        return "可用作者信息：无。"
    strategy = _author_description_strategy(author_profile)
    return (
        "可用作者信息（按平台策略择优引用，不要堆砌，不要所有平台重复同一段）：\n"
        f"{json.dumps(author_context, ensure_ascii=False)}"
        + (f"\n作者补充策略：{strategy}" if strategy else "")
    )


def _author_context(author_profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    business = creator_profile.get("business") if isinstance(creator_profile.get("business"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    expertise = positioning.get("expertise") if isinstance(positioning.get("expertise"), list) else personal.get("expertise") if isinstance(personal.get("expertise"), list) else []
    context = {
        "display_name": str(profile.get("display_name") or "").strip() or None,
        "presenter_alias": str(profile.get("presenter_alias") or "").strip() or None,
        "public_name": str(identity.get("public_name") or personal.get("public_name") or "").strip() or None,
        "real_name": str(identity.get("real_name") or personal.get("real_name") or "").strip() or None,
        "title": str(identity.get("title") or personal.get("title") or "").strip() or None,
        "organization": str(identity.get("organization") or personal.get("organization") or "").strip() or None,
        "location": str(identity.get("location") or personal.get("location") or "").strip() or None,
        "bio": str(identity.get("bio") or personal.get("bio") or "").strip() or None,
        "expertise": [str(item).strip() for item in expertise if str(item).strip()][:6],
        "experience": str(personal.get("experience") or "").strip() or None,
        "achievements": str(personal.get("achievements") or "").strip() or None,
        "creator_focus": str(positioning.get("creator_focus") or personal.get("creator_focus") or "").strip() or None,
        "audience": str(positioning.get("audience") or personal.get("audience") or "").strip() or None,
        "style": str(positioning.get("style") or personal.get("style") or "").strip() or None,
        "primary_platform": str(publishing.get("primary_platform") or "").strip() or None,
        "active_platforms": [str(item).strip() for item in (publishing.get("active_platforms") or []) if str(item).strip()][:6],
        "signature": str(publishing.get("signature") or "").strip() or None,
        "contact": str(business.get("contact") or personal.get("contact") or "").strip() or None,
        "collaboration_notes": str(business.get("collaboration_notes") or "").strip() or None,
        "availability": str(business.get("availability") or "").strip() or None,
        "extra_notes": str(creator_profile.get("archive_notes") or personal.get("extra_notes") or "").strip() or None,
    }
    return {key: value for key, value in context.items() if value not in (None, "", [])}


def _build_author_sentence(label: str, author_profile: dict[str, Any] | None) -> str:
    name = _author_public_name(author_profile)
    if not name:
        return ""
    identity = _author_identity(author_profile)
    focus = _author_focus(author_profile)
    style = _author_style(author_profile)
    primary_platform = _author_primary_platform(author_profile)
    if label == "B站":
        if identity and focus:
            return f"我是{name}，{identity}，长期关注{focus}"
        if focus:
            return f"我是{name}，长期关注{focus}"
        if identity:
            return f"我是{name}，{identity}"
        return f"我是{name}"
    if label == "小红书":
        if focus and style:
            return f"我是{name}，平时主要分享{focus}，会更在意{style}"
        if focus:
            return f"我是{name}，平时主要分享{focus}"
        if style:
            return f"我是{name}，这次会更在意{style}"
        return f"我是{name}"
    if label == "抖音":
        if focus:
            return f"我是{name}，平时就盯{focus}"
        return f"我是{name}"
    if label == "快手":
        if focus:
            return f"我是{name}，平时就爱折腾{focus}"
        return f"我是{name}"
    if label == "视频号":
        if identity and primary_platform:
            return f"我是{name}，{identity}，主内容阵地在{primary_platform}"
        if identity and focus:
            return f"我是{name}，{identity}，长期关注{focus}"
        if primary_platform:
            return f"我是{name}，主内容阵地在{primary_platform}"
        return f"我是{name}"
    if identity and focus:
        return f"我是{name}，{identity}，长期关注{focus}"
    if identity:
        return f"我是{name}，{identity}"
    if focus:
        return f"我是{name}，长期关注{focus}"
    return f"我是{name}"


def _author_public_name(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    return (
        str(identity.get("public_name") or "").strip()
        or str(personal.get("public_name") or "").strip()
        or str(profile.get("presenter_alias") or "").strip()
        or str(profile.get("display_name") or "").strip()
    )


def _author_identity(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity_profile = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    title = str(identity_profile.get("title") or personal.get("title") or "").strip()
    organization = str(identity_profile.get("organization") or personal.get("organization") or "").strip()
    experience = str(personal.get("experience") or "").strip()
    achievements = str(personal.get("achievements") or "").strip()
    if organization and title:
        return f"{organization}{title}"
    if title:
        return title
    if organization:
        return organization
    if experience:
        return experience
    if achievements and len(achievements) <= 20:
        return achievements
    return ""


def _author_focus(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    creator_focus = str(positioning.get("creator_focus") or personal.get("creator_focus") or "").strip()
    if creator_focus:
        return creator_focus
    expertise = positioning.get("expertise") if isinstance(positioning.get("expertise"), list) else personal.get("expertise")
    if isinstance(expertise, list):
        topics = [str(item).strip() for item in expertise if str(item).strip()]
        if topics:
            return "、".join(topics[:3])
    bio = str(identity.get("bio") or personal.get("bio") or "").strip()
    if bio and len(bio) <= 24:
        return bio
    return ""


def _author_style(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    return (
        str(positioning.get("style") or personal.get("style") or "").strip()
        or str(positioning.get("audience") or personal.get("audience") or "").strip()
        or str(creator_profile.get("archive_notes") or personal.get("extra_notes") or "").strip()
    )


def _author_primary_platform(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("primary_platform") or "").strip()


def _author_default_call_to_action(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("default_call_to_action") or "").strip()


def _author_description_strategy(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("description_strategy") or "").strip()


def build_fallback_titles(*, label: str, content_profile: dict[str, Any] | None, copy_style: str = "attention_grabbing") -> list[str]:
    if not _has_specific_subject_identity(content_profile):
        return _build_neutral_fallback_titles(label=label, copy_style=copy_style)

    product = _preferred_product_label(content_profile) or "这款产品"
    subject = _preferred_subject_label(content_profile) or "产品"
    hook = _build_confirmed_title_hook(content_profile)
    headline_hook = _copy_style_headline_hook(copy_style, hook=hook, brand=product, subject=subject)

    if label == "B站":
        return [
            f"{product}：{headline_hook}",
            f"{product}{_copy_style_bilibili_angle(copy_style)}",
            f"{product}上手体验，{_copy_style_explainer(copy_style)}",
            f"{_copy_style_waiting_angle(copy_style, subject)}",
            f"{product}{_copy_style_record_angle(copy_style)}",
        ]
    if label == "小红书":
        return [
            _copy_style_xhs_title(copy_style, brand=product, subject=subject),
            f"{product}{_copy_style_texture_angle(copy_style)}",
            _copy_style_waiting_angle(copy_style, subject),
            f"玩家向{subject}开箱，{_copy_style_detail_angle(copy_style)}",
            f"{product}到手分享，{_copy_style_judgement_angle(copy_style)}",
        ]
    if label == "抖音":
        return [
            f"{product}{_copy_style_short_burst(copy_style)}",
            _copy_style_waiting_angle(copy_style, subject),
            f"{product}{_copy_style_judgement_angle(copy_style)}",
            f"{_copy_style_unboxing_burst(copy_style)}",
            f"{subject}到手先看{_copy_style_detail_focus(copy_style)}",
        ]
    if label == "快手":
        return [
            f"给你们看个真东西：{product}",
            _copy_style_waiting_angle(copy_style, subject),
            f"{product}{_copy_style_judgement_angle(copy_style)}",
            f"这次开箱我{_copy_style_explainer(copy_style)}",
            f"{subject}{_copy_style_truth_angle(copy_style)}",
        ]
    return [
        f"{product}{_copy_style_record_angle(copy_style)}",
        f"{product}到手体验",
        f"这把{subject}{_copy_style_judgement_angle(copy_style)}",
        f"{product}{_copy_style_detail_angle(copy_style)}",
        f"{subject}开箱与上手记录",
    ]


def build_fallback_description(
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str = "attention_grabbing",
    author_profile: dict[str, Any] | None = None,
) -> str:
    question = _fallback_question_with_author(content_profile, author_profile)
    if not _has_specific_subject_identity(content_profile):
        if label == "小红书":
            description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、外观细节和真实上手感受。不硬写产品名，只聊这次到手后最值得分享的那几个瞬间。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "抖音":
            description = f"{_copy_style_opening(copy_style)}这条就先把重点打出来：开箱细节、真实体验、值不值得继续看，都压在这一条里。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "快手":
            description = f"{_copy_style_opening(copy_style)}这期不瞎补产品信息，直接看开箱细节、做工表现和真实上手感受，能看懂的地方我都给你摆明白。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "视频号":
            description = f"{_copy_style_opening(copy_style)}这次分享一条开箱上手视频，重点放在外观细节、质感和真实体验，方便你快速判断值不值得继续关注。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、细节表现和真实上手感受，不编产品名，只说视频里能确认的内容和最值得讨论的重点。{question}"
        return _inject_author_context_into_description(label, description, author_profile)

    product = _preferred_product_label(content_profile) or "这款产品"
    if label == "小红书":
        description = f"{_copy_style_opening(copy_style)}{product}终于到手，重点看外观、细节和上手感受。不是硬广，更像一次有质感的真实开箱分享。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "抖音":
        description = f"{_copy_style_opening(copy_style)}这次就看{product}到底值不值，最狠的细节和真实体验都压进这一条里了。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "快手":
        description = f"{_copy_style_opening(copy_style)}给大家看个真东西，这次开箱的是{product}，值不值、细节咋样，我就按实话给你讲。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "视频号":
        description = f"{_copy_style_opening(copy_style)}这次分享一条{product}开箱视频，重点看细节、质感和真实上手体验，方便快速做判断。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    description = f"{_copy_style_opening(copy_style)}这次开箱的是{product}，视频里把到手细节、上手感受和核心判断都说清楚了。{question}"
    return _inject_author_context_into_description(label, description, author_profile)


def _fallback_product(content_profile: dict[str, Any] | None) -> str:
    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject = _specific_subject_type(content_profile)
    return " ".join(part for part in (brand, model or subject) if part).strip()


def _preferred_product_label(content_profile: dict[str, Any] | None) -> str:
    return _fallback_product(content_profile)


def _preferred_subject_label(content_profile: dict[str, Any] | None) -> str:
    profile = content_profile or {}
    return (
        str(profile.get("subject_model") or "").strip()
        or _specific_subject_type(profile)
        or str(profile.get("subject_type") or "").strip()
        or "产品"
    )


def _normalize_highlight_product(value: Any, content_profile: dict[str, Any] | None) -> str:
    if not _has_specific_subject_identity(content_profile):
        return ""
    return str(value or _fallback_product(content_profile)).strip()


def _fallback_video_type(content_profile: dict[str, Any] | None) -> str:
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    return theme or "开箱体验"


def _fallback_question(content_profile: dict[str, Any] | None) -> str:
    question = str((content_profile or {}).get("engagement_question") or "").strip()
    return question or "你觉得这次到手值不值？"


def _fallback_question_with_author(
    content_profile: dict[str, Any] | None,
    author_profile: dict[str, Any] | None,
) -> str:
    return _author_default_call_to_action(author_profile) or _fallback_question(content_profile)


def _has_specific_subject_identity(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile or {}
    if str(profile.get("subject_brand") or "").strip():
        return True
    if str(profile.get("subject_model") or "").strip():
        return True
    return bool(_specific_subject_type(profile))


def _specific_subject_type(content_profile: dict[str, Any] | None) -> str:
    subject = str((content_profile or {}).get("subject_type") or "").strip()
    if not subject:
        return ""
    generic_subjects = {
        "开箱",
        "开箱产品",
        "产品",
        "工具",
        "东西",
        "玩意",
        "单品",
        "EDC",
        "刀具",
        "装备",
        "物件",
    }
    normalized = subject.replace(" ", "")
    if normalized in generic_subjects or normalized.startswith("开箱"):
        return ""
    return subject


def _profile_mentions_edc(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile or {}
    fields = (
        profile.get("subject_type"),
        profile.get("video_theme"),
        profile.get("summary"),
    )
    return any("EDC" in str(value or "").upper() for value in fields)


def _build_neutral_fallback_titles(*, label: str, copy_style: str = "attention_grabbing") -> list[str]:
    if label == "B站":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱重点看哪些细节",
            "到手先别下结论，先看做工和外观",
            "这次上手体验到底怎么样",
            "不开脑补，只聊视频里能确认的内容",
            "这期开箱值不值得继续深挖",
        ]
    if label == "小红书":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看外观和细节",
            "到手第一眼先看做工表现",
            "不瞎补产品名，只聊这次上手感受",
            "这期开箱的质感和细节我先拍给你看",
            "先把细节看清，再聊值不值",
        ]
    if label == "抖音":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看细节",
            "到手先看做工表现",
            "不先下结论，先上手",
            "这次开箱重点都在这里",
            "先把外观和手感看清",
        ]
    if label == "快手":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看真细节",
            "不瞎补名字，先看上手表现",
            "到手先把做工看明白",
            "这次开箱我只说能确认的",
            "先看细节，再聊值不值",
        ]
    return [
        f"{_copy_style_neutral_hook(copy_style)}这期开箱先看细节",
        "到手先看外观和做工",
        "这次上手体验到底怎么样",
        "不编产品名，只聊真实表现",
        "先把重点细节看清楚",
    ]


def _dedupe_non_empty(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _build_confirmed_title_hook(content_profile: dict[str, Any] | None) -> str:
    hook = str((content_profile or {}).get("hook_line") or "").strip()
    if hook and _contains_confirmed_product_anchor(hook, content_profile):
        return hook
    return "这次重点看哪些细节"


def _contains_confirmed_product_anchor(text: str, content_profile: dict[str, Any] | None) -> bool:
    anchors = _build_confirmed_identity_anchors(content_profile)
    required = [anchor for anchor in (anchors.get("model"), anchors.get("brand")) if anchor]
    if not required:
        return True
    normalized = _normalize_anchor_text(text)
    return required[0] in normalized


def _build_confirmed_identity_anchors(content_profile: dict[str, Any] | None) -> dict[str, str]:
    profile = content_profile or {}
    return {
        "brand": _primary_anchor_token(str(profile.get("subject_brand") or "")),
        "model": _primary_anchor_token(str(profile.get("subject_model") or "")),
    }


def _primary_anchor_token(text: str) -> str:
    normalized = _normalize_anchor_text(text)
    if not normalized:
        return ""
    alpha_numeric = re.findall(r"[a-z0-9]+", normalized)
    for token in alpha_numeric:
        if len(token) >= 3 and not token.isdigit():
            return token
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    if cjk_runs:
        return max(cjk_runs, key=len)
    return normalized if len(normalized) >= 2 else ""


def _normalize_anchor_text(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").lower())


def _hashify_tags(tags: list[str]) -> list[str]:
    return [item if item.startswith("#") else f"#{item}" for item in tags if item]


def _copy_style_instruction(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "吸引眼球：允许强爆点、强情绪、强反差，但不编造事实。",
        "balanced": "平衡稳妥：有吸引力，但不过度浮夸，优先清晰和自然。",
        "premium_editorial": "高级编辑感：克制、干净、像杂志编辑或品牌文案。",
        "trusted_expert": "专业可信：更像经验分享和专家拆解，少营销腔。",
        "playful_meme": "轻松玩梗：允许更口语、更俏皮、更有网感。",
        "emotional_story": "情绪叙事：更强调经历、等待、惊喜、落差和感受。",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _platform_bias_instruction(label: str) -> str:
    mapping = {
        "B站": "信息密度更高，强调拆解、讲清逻辑、适合教程和深度说明。",
        "小红书": "更重质感、分享感和情绪共鸣，像真体验笔记。",
        "抖音": "更短更快更有爆点，先给结果和记忆点。",
        "快手": "更接地气、更直给，像当面把真实体验讲明白。",
        "视频号": "更稳妥可信，适合快速概括重点和结论。",
    }
    return mapping.get(label, "按平台用户习惯自动调整语气和信息密度。")


def _copy_style_headline_hook(copy_style: str, *, hook: str, brand: str, subject: str) -> str:
    if copy_style == "balanced":
        return hook or f"{subject}这次重点说清楚"
    if copy_style == "premium_editorial":
        return f"{subject}这次很值得看"
    if copy_style == "trusted_expert":
        return f"{subject}关键差异讲明白"
    if copy_style == "playful_meme":
        return f"{subject}这次真有点狠"
    if copy_style == "emotional_story":
        return f"{subject}这次真的等很久"
    return hook or f"{brand}{subject}这次太狠了"


def _copy_style_bilibili_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "到底强得有多离谱",
        "balanced": "到底值不值得看",
        "premium_editorial": "这次有哪些细节变化",
        "trusted_expert": "核心差异一次讲清",
        "playful_meme": "这次是不是有点太猛",
        "emotional_story": "等了这么久到底值不值",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_explainer(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "优缺点一次说透",
        "balanced": "优缺点一次说清",
        "premium_editorial": "细节变化慢慢拆开",
        "trusted_expert": "核心逻辑讲明白",
        "playful_meme": "爽点和坑点都掰开说",
        "emotional_story": "我为什么会被它打动都说清楚",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_waiting_angle(copy_style: str, subject: str) -> str:
    mapping = {
        "attention_grabbing": f"等了很久才到手，这把{subject}太狠了",
        "balanced": f"等了很久才到手，这把{subject}怎么样",
        "premium_editorial": f"这把{subject}到手后，第一眼细节很加分",
        "trusted_expert": f"这把{subject}到手后，先看几个关键点",
        "playful_meme": f"这把{subject}我真等麻了",
        "emotional_story": f"等了很久，这把{subject}终于到手了",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_record_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "开箱+真实暴击体验",
        "balanced": "开箱+真实体验记录",
        "premium_editorial": "到手观察与细节记录",
        "trusted_expert": "实测记录与判断",
        "playful_meme": "开箱实录，真的有点顶",
        "emotional_story": "到手后的第一天记录",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_texture_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "摆上桌直接杀疯了",
        "balanced": "摆上桌，质感一下就出来了",
        "premium_editorial": "摆上桌，整体气质立刻出来了",
        "trusted_expert": "摆上桌，几个关键细节很清楚",
        "playful_meme": "摆上桌真的太会了",
        "emotional_story": "摆上桌那一刻真的有点感动",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_detail_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "细节党真的会看上头",
        "balanced": "细节控真的会看很久",
        "premium_editorial": "细节质感会让人慢慢看很久",
        "trusted_expert": "几个细节位都值得放大看",
        "playful_meme": "细节党直接爽飞",
        "emotional_story": "细节越看越容易上头",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_judgement_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "到底香不香",
        "balanced": "值不值我直说",
        "premium_editorial": "到底值不值得收藏",
        "trusted_expert": "到底值不值得入手",
        "playful_meme": "到底顶不顶",
        "emotional_story": "到底值不值我这段等待",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_short_burst(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "直接炸场",
        "balanced": "终于到手",
        "premium_editorial": "很值得看",
        "trusted_expert": "先看关键差异",
        "playful_meme": "真的有点狠",
        "emotional_story": "终于轮到我了",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_unboxing_burst(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "这次开箱直接上头",
        "balanced": "这次开箱有点上头",
        "premium_editorial": "这次开箱的质感很在线",
        "trusted_expert": "这次开箱先看几个重点",
        "playful_meme": "这次开箱真的有梗",
        "emotional_story": "这次开箱真有点感慨",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_detail_focus(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "最狠细节",
        "balanced": "细节",
        "premium_editorial": "关键细节",
        "trusted_expert": "核心细节",
        "playful_meme": "爽点细节",
        "emotional_story": "最打动人的细节",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_truth_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "值不值我直接摊牌",
        "balanced": "值不值，咱实话实说",
        "premium_editorial": "到底值不值得慢慢看",
        "trusted_expert": "到底值不值得入手",
        "playful_meme": "到底顶不顶，咱不装了",
        "emotional_story": "值不值，这次我想认真聊聊",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_opening(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "先说结论，",
        "balanced": "",
        "premium_editorial": "如果只看重点，",
        "trusted_expert": "先把核心判断放前面，",
        "playful_meme": "先别急着划走，",
        "emotional_story": "说实话，",
    }
    return mapping.get(copy_style, "")


def _copy_style_neutral_hook(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "先说重点，",
        "balanced": "",
        "premium_editorial": "如果只看重点，",
        "trusted_expert": "先看核心信息，",
        "playful_meme": "先别滑走，",
        "emotional_story": "先从感受说起，",
    }
    return mapping.get(copy_style, "")


def _copy_style_xhs_title(copy_style: str, *, brand: str, subject: str) -> str:
    merged = brand
    normalized_brand = _normalize_anchor_text(brand)
    normalized_subject = _normalize_anchor_text(subject)
    if subject and normalized_subject and normalized_subject not in normalized_brand:
        merged = f"{brand}{subject}"
    mapping = {
        "attention_grabbing": f"{merged}终于到手，细节直接封神",
        "balanced": f"这把{subject}终于到手，细节真的很顶",
        "premium_editorial": f"{merged}到手后，气质一下就出来了",
        "trusted_expert": f"{merged}到手后，先看这几个关键点",
        "playful_meme": f"{merged}到手后真的有点离谱",
        "emotional_story": f"{merged}终于到手，这次真的等很久",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])

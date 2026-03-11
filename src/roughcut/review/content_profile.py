from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from roughcut.edit.presets import WorkflowPreset, get_workflow_preset, select_preset
from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import Message, extract_json_text


def build_transcript_excerpt(subtitle_items: list[dict], *, max_items: int = 36, max_chars: int = 1400) -> str:
    lines: list[str] = []
    total = 0
    for item in subtitle_items[:max_items]:
        text = item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""
        if not text:
            continue
        line = f"[{item.get('start_time', 0):.1f}-{item.get('end_time', 0):.1f}] {text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


def apply_glossary_terms(text: str, glossary_terms: list[dict[str, Any]]) -> str:
    result = text
    for term in glossary_terms:
        correct_form = (term.get("correct_form") or "").strip()
        if not correct_form:
            continue
        for wrong_form in term.get("wrong_forms") or []:
            if wrong_form and wrong_form != correct_form:
                result = re.sub(re.escape(wrong_form), correct_form, result, flags=re.IGNORECASE)
    return result


def build_cover_title(profile: dict[str, Any], preset: WorkflowPreset) -> dict[str, str]:
    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    model = _clean_line(profile.get("subject_model") or profile.get("model") or "")
    subject_type = _clean_line(profile.get("subject_type") or "")
    theme = _clean_line(profile.get("video_theme") or "")
    hook = _clean_line(profile.get("hook_line") or "")
    visible_text = str(profile.get("visible_text") or "").strip()

    top = _pick_cover_top(brand=brand, subject_type=subject_type, visible_text=visible_text, preset=preset)
    main = _pick_cover_main(
        brand=brand,
        model=model,
        subject_type=subject_type,
        theme=theme,
        visible_text=visible_text,
        preset=preset,
    )

    if not hook or _is_generic_cover_line(hook):
        if preset.name == "unboxing_limited":
            hook = "限定细节值不值"
        elif preset.name == "unboxing_upgrade":
            hook = "这次升级够不够狠"
        elif preset.name == "edc_tactical":
            hook = "做工结构直接看"
        else:
            hook = preset.cover_accent

    return {
        "top": top[:14],
        "main": main[:18],
        "bottom": hook[:18],
    }


async def infer_content_profile(
    *,
    source_path: Path,
    source_name: str,
    subtitle_items: list[dict],
    channel_profile: str | None,
    include_research: bool = True,
) -> dict[str, Any]:
    transcript_excerpt = build_transcript_excerpt(subtitle_items)
    initial_profile = _fallback_profile(
        source_name=source_name,
        channel_profile=channel_profile,
        transcript_excerpt=transcript_excerpt,
    )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = _extract_reference_frames(source_path, Path(tmpdir), count=3)
            if frame_paths:
                prompt = (
                    "你在分析一条中文短视频。视频可能是开箱评测、录屏教学、vlog、口播观点、游戏高光或美食探店。"
                    "请结合图片和口播字幕，判断视频主体是什么。"
                    "如果画面里有产品、软件界面、店招、包装、盒体、logo、英文单词、型号字样，都优先识别。"
                    "尽量给出品牌、型号/版本、主体类型、视频主题，以及适合的剪辑预设。"
                    "如果不确定，不要乱编，留空即可。\n\n"
                    "输出 JSON："
                    '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
                    '"preset_name":"","hook_line":"","visible_text":"","search_queries":[]}'
                    "\n要求：preset_name 只能从 unboxing_default、unboxing_limited、unboxing_upgrade、edc_tactical、screen_tutorial、vlog_daily、talking_head_commentary、gameplay_highlight、food_explore 中选择。"
                    "\nsearch_queries 提供 2-3 个适合联网搜索验证的查询词。"
                    f"\n源文件名：{source_name}\n字幕节选：\n{transcript_excerpt}"
                )
                content = await complete_with_images(prompt, frame_paths, max_tokens=500, json_mode=True)
                candidate = json.loads(extract_json_text(content))
                initial_profile.update({k: v for k, v in candidate.items() if v})
    except Exception:
        pass

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在分析中文短视频的口播内容。视频可能是开箱评测、录屏教学、vlog、口播观点、游戏高光或美食探店。"
            "请根据文件名、字幕节选和已有视觉判断，补全视频主体的品牌、型号/版本、主体类型、视频主题，并给出适合联网验证的搜索词。"
            "如果不确定，请留空，不要乱编。"
            "\n输出 JSON："
            '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
            '"preset_name":"","hook_line":"","visible_text":"","search_queries":[]}'
            f"\n已有判断：{json.dumps(initial_profile, ensure_ascii=False)}"
            f"\n源文件名：{source_name}\n字幕节选：\n{transcript_excerpt}"
        )
        response = await provider.complete(
            [
                Message(role="system", content="你是中文短视频内容策划助手。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=500,
            json_mode=True,
        )
        candidate = response.as_json()
        initial_profile.update({k: v for k, v in candidate.items() if v})
    except Exception:
        pass

    return await enrich_content_profile(
        profile=initial_profile,
        source_name=source_name,
        channel_profile=channel_profile,
        transcript_excerpt=transcript_excerpt,
        include_research=include_research,
    )


async def apply_content_profile_feedback(
    *,
    draft_profile: dict[str, Any],
    source_name: str,
    channel_profile: str | None,
    user_feedback: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(draft_profile or {})
    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
    ):
        value = user_feedback.get(key)
        if value:
            merged[key] = str(value).strip()

    if user_feedback.get("keywords"):
        merged["search_queries"] = [str(item).strip() for item in user_feedback["keywords"] if str(item).strip()]
    if user_feedback.get("summary"):
        merged["summary"] = str(user_feedback["summary"]).strip()
    if user_feedback.get("engagement_question"):
        merged["engagement_question"] = str(user_feedback["engagement_question"]).strip()
    if user_feedback.get("correction_notes"):
        merged["correction_notes"] = str(user_feedback["correction_notes"]).strip()
    if user_feedback.get("supplemental_context"):
        merged["supplemental_context"] = str(user_feedback["supplemental_context"]).strip()

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在整理一条中文短视频的人工确认摘要。请结合模型草稿和用户修正，"
            "输出一个后续可直接用于搜索、字幕修正和剪辑规划的确认版摘要。"
            "用户修正优先级最高，不要忽略用户手动填写的信息。\n"
            "输出 JSON："
            '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
            '"hook_line":"","visible_text":"","summary":"","engagement_question":"","search_queries":[]}'
            f"\n模型草稿：{json.dumps(draft_profile or {}, ensure_ascii=False)}"
            f"\n用户修正：{json.dumps(user_feedback, ensure_ascii=False)}"
            f"\n源文件名：{source_name}"
        )
        response = await provider.complete(
            [
                Message(role="system", content="你是严谨的中文视频内容摘要整理助手。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=700,
            json_mode=True,
        )
        normalized = response.as_json()
        merged.update({k: v for k, v in normalized.items() if v})
    except Exception:
        pass

    transcript_excerpt = str(merged.get("transcript_excerpt") or "")
    return await enrich_content_profile(
        profile=merged,
        source_name=source_name,
        channel_profile=channel_profile,
        transcript_excerpt=transcript_excerpt,
        include_research=False,
    )


async def enrich_content_profile(
    *,
    profile: dict[str, Any],
    source_name: str,
    channel_profile: str | None,
    transcript_excerpt: str,
    include_research: bool = True,
) -> dict[str, Any]:
    enriched = dict(profile or {})

    preset = select_preset(
        channel_profile=channel_profile or enriched.get("preset_name"),
        subject_model=str(enriched.get("subject_model", "")),
        subject_type=str(enriched.get("subject_type", "")),
        transcript_hint=transcript_excerpt,
    )
    enriched["preset_name"] = preset.name
    enriched["preset"] = preset.to_dict()
    enriched["transcript_excerpt"] = transcript_excerpt

    if include_research:
        evidence = await _search_evidence(enriched, source_name)
        if evidence:
            enriched["evidence"] = evidence
            try:
                provider = get_reasoning_provider()
                prompt = (
                    "你在做短视频字幕与封面前置研究。请根据已有判断和搜索证据，"
                    "确认视频主体的品牌、型号/版本、主体类型、视频主题，并生成适合做封面的三段标题。"
                    "优先给出品牌名、系列名或主体名，不要输出泛化标题如“产品开箱与上手体验”。"
                    "如果证据不足，不要编造，保留已有可信信息。\n\n"
                    "输出 JSON："
                    '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
                    '"hook_line":"","visible_text":"","summary":"","engagement_question":"",'
                    '"cover_title":{"top":"","main":"","bottom":""}}'
                    f"\n已有判断：{json.dumps(enriched, ensure_ascii=False)}"
                    f"\n搜索证据：{json.dumps(evidence, ensure_ascii=False)}"
                )
                response = await provider.complete(
                    [
                        Message(role="system", content="你是中文短视频内容策划与字幕审校助手。"),
                        Message(role="user", content=prompt),
                    ],
                    temperature=0.1,
                    max_tokens=700,
                    json_mode=True,
                )
                refined = response.as_json()
                enriched.update({k: v for k, v in refined.items() if v})
            except Exception:
                pass

    cover_title = enriched.get("cover_title")
    if not isinstance(cover_title, dict) or not _cover_title_is_usable(cover_title):
        cover_title = build_cover_title(enriched, preset)
    else:
        cover_title = {
            "top": _clean_line(cover_title.get("top") or "")[:14],
            "main": _clean_line(cover_title.get("main") or "")[:18],
            "bottom": _clean_line(cover_title.get("bottom") or "")[:18],
        }
    enriched["cover_title"] = cover_title
    if not enriched.get("summary"):
        enriched["summary"] = _build_profile_summary(enriched)
    if not enriched.get("engagement_question"):
        enriched["engagement_question"] = "你觉得这次到手值不值？"
    return enriched


async def polish_subtitle_items(
    subtitle_items,
    *,
    content_profile: dict[str, Any],
    glossary_terms: list[dict[str, Any]],
    chunk_size: int = 28,
) -> int:
    provider = None
    try:
        provider = get_reasoning_provider()
    except Exception:
        provider = None

    polished_count = 0
    preset = get_workflow_preset(content_profile.get("preset_name"))
    evidence = content_profile.get("evidence") or []
    evidence_text = "\n".join(
        f"- {item.get('title', '')}: {item.get('snippet', '')}" for item in evidence[:6]
    )
    glossary_text = "\n".join(
        f"- {term.get('correct_form')}: 错写可能包括 {', '.join(term.get('wrong_forms') or [])}"
        for term in glossary_terms[:30]
    )

    for start in range(0, len(subtitle_items), chunk_size):
        chunk = subtitle_items[start:start + chunk_size]

        if provider is not None:
            try:
                payload_items = [
                    {
                        "index": item.item_index,
                        "start_time": item.start_time,
                        "end_time": item.end_time,
                        "text": item.text_final or item.text_norm or item.text_raw,
                    }
                    for item in chunk
                ]
                prompt = (
                    "你在精修中文短视频字幕。请根据视频主体、主题和搜索证据，"
                    "把 ASR 错字、品牌型号错写和不顺口的地方修好。"
                    "要求：\n"
                    "1. 不要改变原意，不要凭空添加没说过的参数。\n"
                    "2. 保持口语感，压缩废词，让字幕更适合烧录。\n"
                    "3. 单条尽量简洁，避免超过 22 个汉字。\n"
                    "4. 优先保证品牌、型号、版本名正确。\n"
                    "5. 输出 JSON：{\"items\":[{\"index\":1,\"text_final\":\"...\"}]}\n\n"
                    f"视频主体：{json.dumps(content_profile, ensure_ascii=False)}\n"
                    f"预设要求：{preset.subtitle_goal}；风格：{preset.subtitle_tone}\n"
                    f"词表：\n{glossary_text}\n"
                    f"搜索证据：\n{evidence_text}\n"
                    f"待处理字幕：{json.dumps(payload_items, ensure_ascii=False)}"
                )
                response = await provider.complete(
                    [
                        Message(role="system", content="你是严谨的中文短视频字幕审校助手。"),
                        Message(role="user", content=prompt),
                    ],
                    temperature=0.1,
                    max_tokens=1600,
                    json_mode=True,
                )
                data = response.as_json()
                updates = {
                    int(item["index"]): str(item["text_final"]).strip()
                    for item in data.get("items", [])
                    if item.get("text_final")
                }
                for item in chunk:
                    polished = updates.get(item.item_index)
                    if polished:
                        polished = _cleanup_polished_text(polished)
                        polished = apply_glossary_terms(polished, glossary_terms)
                        item.text_final = polished
                        polished_count += 1
                        continue
                    item.text_final = _fallback_polish_text(
                        item.text_norm or item.text_raw,
                        glossary_terms=glossary_terms,
                    )
                    polished_count += 1
                continue
            except Exception:
                pass

        for item in chunk:
            item.text_final = _fallback_polish_text(
                item.text_norm or item.text_raw,
                glossary_terms=glossary_terms,
            )
            polished_count += 1

    return polished_count


async def _search_evidence(profile: dict[str, Any], source_name: str) -> list[dict[str, str]]:
    queries = _build_search_queries(profile, source_name)
    if not queries:
        return []
    try:
        provider = get_search_provider()
    except Exception:
        return []

    evidence: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for query in queries[:3]:
        try:
            results = await provider.search(query, max_results=3)
        except Exception:
            continue
        for item in results:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            evidence.append(
                {
                    "query": query,
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                }
            )
    return evidence


def _build_search_queries(profile: dict[str, Any], source_name: str) -> list[str]:
    queries: list[str] = []
    for value in profile.get("search_queries") or []:
        if value:
            queries.append(str(value))

    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    subject_type = str(profile.get("subject_type") or "").strip()
    source_stem = Path(source_name).stem

    if brand and model:
        queries.append(f"{brand} {model}")
        queries.append(f"{brand} {model} 开箱")
    if brand and subject_type:
        queries.append(f"{brand} {subject_type}")
    if source_stem:
        queries.append(source_stem)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _extract_reference_frames(source_path: Path, tmpdir: Path, *, count: int) -> list[Path]:
    import subprocess

    duration = _probe_duration(source_path)
    if duration <= 0:
        return []

    frames: list[Path] = []
    for i in range(count):
        seek = duration * (i + 1) / (count + 1)
        out = tmpdir / f"profile_{i:02d}.jpg"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{seek:.2f}",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-update",
                "1",
                "-q:v",
                "3",
                "-vf",
                "scale=960:-2",
                str(out),
            ],
            capture_output=True,
            timeout=20,
        )
        if result.returncode == 0 and out.exists():
            frames.append(out)
    return frames


def _probe_duration(source_path: Path) -> float:
    import subprocess

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(source_path)],
        capture_output=True,
        timeout=10,
    )
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return 0.0
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def _fallback_profile(
    *,
    source_name: str,
    channel_profile: str | None,
    transcript_excerpt: str,
) -> dict[str, Any]:
    preset = select_preset(
        channel_profile=channel_profile,
        transcript_hint=transcript_excerpt,
    )
    subject_type = _default_subject_type_for_preset(preset)
    video_theme = _default_video_theme_for_preset(preset)
    engagement_question = _default_engagement_question(preset)
    return {
        "subject_brand": "",
        "subject_model": Path(source_name).stem,
        "subject_type": subject_type,
        "video_theme": video_theme,
        "preset_name": preset.name,
        "preset": preset.to_dict(),
        "hook_line": preset.cover_accent,
        "summary": _build_profile_summary(
            {
                "subject_brand": "",
                "subject_model": Path(source_name).stem,
                "subject_type": subject_type,
                "video_theme": video_theme,
                "preset_name": preset.name,
            }
        ),
        "engagement_question": engagement_question,
        "cover_title": build_cover_title(
            {
                "subject_brand": "",
                "subject_model": Path(source_name).stem,
                "subject_type": subject_type,
                "video_theme": video_theme,
                "hook_line": preset.cover_accent,
            },
            preset,
        ),
    }


def _fallback_polish_text(text: str, *, glossary_terms: list[dict[str, Any]]) -> str:
    polished = apply_glossary_terms(text.strip(), glossary_terms)
    polished = re.sub(r"(。){2,}", "。", polished)
    polished = re.sub(r"(，){2,}", "，", polished)
    return polished


def _cleanup_polished_text(text: str) -> str:
    text = re.sub(r"\s+", "", text.strip())
    text = text.replace("「", "“").replace("」", "”")
    text = re.sub(r"[!！]{2,}", "！", text)
    text = re.sub(r"[?？]{2,}", "？", text)
    return text


def _clean_line(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).strip("，。！？：:;；、")


def _looks_like_camera_stem(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(r"(img|dsc|mvimg|pxl|cimg|vid)[-_]?\d+", normalized)
        or re.fullmatch(r"\d{8}[_-].+", normalized)
    )


def _cover_title_is_usable(cover_title: dict[str, Any]) -> bool:
    main = _clean_line(cover_title.get("main") or "")
    return bool(main and not _is_generic_cover_line(main))


def _is_generic_cover_line(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return True
    generic_fragments = (
        "产品开箱",
        "上手体验",
        "开箱体验",
        "产品体验",
        "实拍体验",
        "简单开箱",
        "工具钳具体型号未知",
        "具体型号未知",
    )
    return any(fragment in normalized for fragment in generic_fragments)


def _pick_cover_top(*, brand: str, subject_type: str, visible_text: str, preset: WorkflowPreset) -> str:
    compact_brand = _compact_brand_name(brand, visible_text=visible_text)
    if compact_brand:
        return compact_brand
    if subject_type:
        return subject_type[:14]
    if preset.name == "screen_tutorial":
        return "教程"
    if preset.name == "vlog_daily":
        return "VLOG"
    if preset.name == "talking_head_commentary":
        return "观点"
    if preset.name == "gameplay_highlight":
        return "高能"
    if preset.name == "food_explore":
        return "探店"
    return "开箱"


def _pick_cover_main(
    *,
    brand: str,
    model: str,
    subject_type: str,
    theme: str,
    visible_text: str,
    preset: WorkflowPreset,
) -> str:
    candidate_model = _clean_line(model)
    if candidate_model and not _looks_like_camera_stem(candidate_model) and not _is_generic_cover_line(candidate_model):
        return candidate_model

    compact_brand = _compact_brand_name(brand, visible_text=visible_text)
    if compact_brand and subject_type:
        return f"{compact_brand}{subject_type}"[:18]

    if subject_type:
        if "工具钳" in subject_type:
            return "高价工具钳开箱"
        return subject_type[:18]

    if theme and not _is_generic_cover_line(theme):
        return theme[:18]

    return preset.label[:18]


def _compact_brand_name(brand: str, *, visible_text: str) -> str:
    value = _clean_line(brand)
    if not value:
        return _pick_visible_brand(visible_text)

    english_match = re.search(r"[A-Za-z][A-Za-z0-9 .+-]{1,20}", value)
    if english_match:
        return english_match.group(0).strip().upper()[:14]

    if "（" in value and "）" in value:
        outside = value.split("（", 1)[0].strip()
        if outside:
            return outside[:14]
    return value[:14]


def _pick_visible_brand(visible_text: str) -> str:
    match = re.search(r"[A-Za-z][A-Za-z0-9+-]{2,20}", visible_text or "")
    if not match:
        return ""
    return match.group(0).strip().upper()[:14]


def _build_profile_summary(profile: dict[str, Any]) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    preset_name = str(profile.get("preset_name") or "").strip()
    subject_type = str(profile.get("subject_type") or _default_subject_type_by_name(preset_name)).strip()
    theme = str(profile.get("video_theme") or _default_video_theme_by_name(preset_name)).strip()
    parts = [part for part in (brand, model or subject_type) if part]
    product = " ".join(parts).strip() or subject_type
    if preset_name == "screen_tutorial":
        return f"这条视频主要围绕{product}的操作演示展开，内容方向偏{theme}，重点是步骤清晰、术语准确，方便后续剪成可跟做的教程。"
    if preset_name == "vlog_daily":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是保留生活感、场景切换和真实情绪。"
    if preset_name == "talking_head_commentary":
        return f"这条视频主要围绕{product}展开表达，内容方向偏{theme}，重点是观点钩子、论点节奏和结论清晰。"
    if preset_name == "gameplay_highlight":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是高能操作、关键节点和结果反馈。"
    if preset_name == "food_explore":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是店名菜名、口感描述和是否值得去。"
    return f"这条视频主要围绕{product}展开，内容方向偏{theme}，适合后续做搜索校验、字幕纠错和剪辑包装。"


def _default_subject_type_for_preset(preset: WorkflowPreset) -> str:
    return _default_subject_type_by_name(preset.name)


def _default_subject_type_by_name(preset_name: str) -> str:
    mapping = {
        "screen_tutorial": "录屏教学",
        "vlog_daily": "Vlog日常",
        "talking_head_commentary": "口播观点",
        "gameplay_highlight": "游戏实况",
        "food_explore": "探店试吃",
    }
    return mapping.get(preset_name, "开箱产品")


def _default_video_theme_for_preset(preset: WorkflowPreset) -> str:
    return _default_video_theme_by_name(preset.name)


def _default_video_theme_by_name(preset_name: str) -> str:
    mapping = {
        "screen_tutorial": "软件流程演示与步骤讲解",
        "vlog_daily": "日常记录与生活分享",
        "talking_head_commentary": "观点表达与信息拆解",
        "gameplay_highlight": "高能操作与对局复盘",
        "food_explore": "探店试吃与性价比判断",
    }
    return mapping.get(preset_name, "产品开箱与上手体验")


def _default_engagement_question(preset: WorkflowPreset) -> str:
    mapping = {
        "screen_tutorial": "这套流程你会直接照着做吗？",
        "vlog_daily": "你最想看我下次拍哪种日常？",
        "talking_head_commentary": "这件事你同意这个判断吗？",
        "gameplay_highlight": "这波操作你会怎么打？",
        "food_explore": "这家店你会专门去吃一次吗？",
    }
    return mapping.get(preset.name, "你觉得这次到手值不值？")

from __future__ import annotations

import re
from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message

_DEFAULT_TARGET_LANGUAGE = "en"
_DEFAULT_TARGET_LANGUAGE_MODE = "auto"
_DEFAULT_PREFERRED_UI_LANGUAGE = "zh-CN"
_CHUNK_SIZE = 24


async def translate_subtitle_items(
    subtitle_items: list[dict[str, Any]],
    *,
    target_language: str | None = None,
    target_language_mode: str = _DEFAULT_TARGET_LANGUAGE_MODE,
    preferred_ui_language: str = _DEFAULT_PREFERRED_UI_LANGUAGE,
) -> dict[str, Any]:
    provider = get_reasoning_provider()
    normalized_mode = normalize_translation_target_mode(target_language_mode)
    source_language = detect_subtitle_language(subtitle_items)
    resolved_target_language = resolve_translation_target_language(
        source_language=source_language,
        target_language=target_language,
        target_language_mode=normalized_mode,
        preferred_ui_language=preferred_ui_language,
    )
    translated_items: list[dict[str, Any]] = []

    for chunk in _chunk_items(subtitle_items, _CHUNK_SIZE):
        translated_items.extend(
            await _translate_subtitle_chunk(
                provider=provider,
                subtitle_items=chunk,
                target_language=resolved_target_language,
            )
        )

    translated_items.sort(key=lambda item: int(item.get("index", 0)))
    return {
        "target_language": resolved_target_language,
        "target_language_mode": normalized_mode,
        "source_language": source_language,
        "item_count": len(translated_items),
        "items": translated_items,
    }


async def _translate_subtitle_chunk(
    *,
    provider,
    subtitle_items: list[dict[str, Any]],
    target_language: str,
) -> list[dict[str, Any]]:
    prompt_items = [
        {
            "index": int(item.get("index", 0)),
            "text": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip(),
        }
        for item in subtitle_items
        if str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
    ]
    if not prompt_items:
        return []

    prompt = (
        "你是严谨的字幕翻译。把下面这组已经校对过的中文字幕翻译成目标语言。"
        "要求：忠实原意、表达自然、适合字幕阅读、保留品牌/型号/术语，不要解释，不要扩写。"
        f"\n目标语言：{target_language}"
        "\n输出 JSON：{\"items\":[{\"index\":0,\"translated_text\":\"...\"}]}"
        f"\n字幕：{prompt_items}"
    )
    response = await provider.complete(
        [
            Message(role="system", content="你是专业的视频字幕翻译，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=2200,
        json_mode=True,
    )
    payload = response.as_json()
    translated_map: dict[int, str] = {}
    for item in list(payload.get("items") or []) if isinstance(payload, dict) else []:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = str(item.get("translated_text") or "").strip()
        if text:
            translated_map[index] = text

    translated_items: list[dict[str, Any]] = []
    for subtitle in subtitle_items:
        text_source = str(subtitle.get("text_final") or subtitle.get("text_norm") or subtitle.get("text_raw") or "").strip()
        if not text_source:
            continue
        index = int(subtitle.get("index", 0))
        translated_text = translated_map.get(index)
        if not translated_text:
            translated_text = await _translate_single_subtitle(
                provider=provider,
                text=text_source,
                target_language=target_language,
            )
        translated_items.append(
            {
                "index": index,
                "start_time": subtitle.get("start_time"),
                "end_time": subtitle.get("end_time"),
                "text_source": text_source,
                "text_translated": translated_text,
                "target_language": target_language,
            }
        )
    return translated_items


async def _translate_single_subtitle(
    *,
    provider,
    text: str,
    target_language: str,
) -> str:
    prompt = (
        "把这条已经校对过的中文字幕翻译成目标语言，保持简洁自然，保留品牌型号和术语。"
        f"\n目标语言：{target_language}"
        '\n输出 JSON：{"translation":"..."}'
        f"\n原文：{text}"
    )
    response = await provider.complete(
        [
            Message(role="system", content="你是专业的视频字幕翻译，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=400,
        json_mode=True,
    )
    payload = response.as_json()
    if isinstance(payload, dict):
        translation = str(payload.get("translation") or "").strip()
        if translation:
            return translation
    raise ValueError("Subtitle translation did not return a usable translation")


def _chunk_items(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        return [items]
    return [items[index:index + size] for index in range(0, len(items), size)]


def normalize_translation_target_mode(value: str | None) -> str:
    normalized = str(value or _DEFAULT_TARGET_LANGUAGE_MODE).strip().lower() or _DEFAULT_TARGET_LANGUAGE_MODE
    return normalized if normalized in {"auto", "manual"} else _DEFAULT_TARGET_LANGUAGE_MODE


def detect_subtitle_language(subtitle_items: list[dict[str, Any]]) -> str:
    text = "\n".join(
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items
    ).strip()
    if not text:
        return "zh-CN"

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    japanese_count = len(re.findall(r"[\u3040-\u30ff]", text))
    korean_count = len(re.findall(r"[\uac00-\ud7af]", text))

    if cjk_count >= max(6, latin_count):
        return "zh-CN"
    if japanese_count > max(2, cjk_count // 2):
        return "ja-JP"
    if korean_count > max(2, cjk_count // 2):
        return "ko-KR"
    return "en-US"


def resolve_translation_target_language(
    *,
    source_language: str,
    target_language: str | None,
    target_language_mode: str,
    preferred_ui_language: str,
) -> str:
    normalized_mode = normalize_translation_target_mode(target_language_mode)
    manual_target = str(target_language or "").strip()
    if normalized_mode == "manual" and manual_target:
        return manual_target

    source_family = _language_family(source_language)
    ui_family = _language_family(preferred_ui_language or _DEFAULT_PREFERRED_UI_LANGUAGE)

    if source_family == ui_family:
        return _DEFAULT_TARGET_LANGUAGE
    return str(preferred_ui_language or _DEFAULT_PREFERRED_UI_LANGUAGE).strip() or _DEFAULT_PREFERRED_UI_LANGUAGE


def languages_equivalent(source_language: str | None, target_language: str | None) -> bool:
    source_family = _language_family(source_language)
    target_family = _language_family(target_language)
    return bool(source_family) and source_family == target_family


def _language_family(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("ja"):
        return "ja"
    if normalized.startswith("ko"):
        return "ko"
    return normalized.split("-", 1)[0] if normalized else "zh"

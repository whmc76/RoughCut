from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message

_VALID_CATEGORY_SCOPES = {"food", "flashlight", "knife", "bag", "tools", "other", "unknown"}


async def infer_transcription_context_prior(
    *,
    source_name: str,
    source_context: dict[str, Any] | None = None,
    workflow_template: str | None = None,
    timeout_sec: float = 25.0,
) -> dict[str, Any]:
    context = _build_prior_context(
        source_name=source_name,
        source_context=source_context,
        workflow_template=workflow_template,
    )
    if not _has_informative_prior_context(context):
        return {}

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            provider = get_reasoning_provider()
            response = await _complete_with_provider_timeout(
                provider,
                [
                    Message(role="system", content="你是中文短视频转写热词前置判断器，只输出 JSON。"),
                    Message(role="user", content=_build_prior_prompt(context)),
                ],
                temperature=0.1,
                max_tokens=700,
                json_mode=True,
                timeout_sec=max(5.0, float(timeout_sec or 25.0)),
            )
            payload = response.as_json()
            normalized = normalize_transcription_context_prior(payload)
            _merge_deterministic_context_hotwords(normalized, context)
            normalized["status"] = "ok"
            normalized["model"] = str(getattr(response, "model", "") or "")
            normalized["attempt_count"] = attempt + 1
            return normalized
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(0.5)

    if last_error is not None:
        return {
            "status": "failed",
            "error": _format_prior_error(last_error),
            "attempt_count": 2,
        }
    return {}


def _merge_deterministic_context_hotwords(prior: dict[str, Any], context: dict[str, Any]) -> None:
    existing = _normalize_string_list(prior.get("allowed_hotwords"), limit=12)
    blocked = {item.casefold() for item in _normalize_string_list(prior.get("blocked_hotwords"), limit=24)}
    for term in _extract_deterministic_context_hotwords(context):
        key = term.casefold()
        if key in blocked or any(item.casefold() == key for item in existing):
            continue
        existing.append(term)
        if len(existing) >= 12:
            break
    prior["allowed_hotwords"] = existing[:12]


def _extract_deterministic_context_hotwords(context: dict[str, Any]) -> list[str]:
    text_parts: list[str] = []
    for key in ("source_name", "video_description", "manual_video_summary"):
        value = _clean_text(context.get(key), limit=500)
        if value:
            text_parts.append(value)
    resolved_feedback = context.get("resolved_feedback") if isinstance(context.get("resolved_feedback"), dict) else {}
    for value in resolved_feedback.values():
        if isinstance(value, (list, tuple, set)):
            text_parts.extend(_clean_text(item, limit=120) for item in value if _clean_text(item, limit=120))
        else:
            cleaned = _clean_text(value, limit=240)
            if cleaned:
                text_parts.append(cleaned)
    blob = " ".join(text_parts)
    if not blob:
        return []
    compact = re.sub(r"\s+", "", blob)
    compact = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", compact)
    terms: list[str] = []

    def add(value: Any) -> None:
        text = _clean_text(value, limit=64).strip(" _-|，,。.!！?？()（）[]【】")
        if not text:
            return
        if re.fullmatch(r"IMG[_-]?\d+", text, re.I):
            return
        if text.upper() in {"IMG", "MOV", "MP4", "M4V"}:
            return
        if text.casefold() not in {item.casefold() for item in terms}:
            terms.append(text)

    for value in _extract_labeled_context_terms(blob):
        add(value)
        for alias in _derive_context_term_aliases(value):
            add(alias)
    for pattern in (
        r"[A-Za-z]{2,12}",
        r"EDC[一-龥A-Za-z0-9]{0,8}",
        r"[一-龥A-Za-z0-9]{1,12}折刀",
        r"[一-龥A-Za-z0-9]{1,12}开箱",
        r"[一-龥A-Za-z0-9]{1,12}版",
        r"[一-龥A-Za-z0-9]{1,12}限量",
        r"[一-龥]{1,8}[0-9一二三四五六七八九十]{1,4}",
    ):
        for match in re.finditer(pattern, compact, flags=re.I):
            add(match.group(0))
    return terms[:12]


def _extract_labeled_context_terms(text: str) -> list[str]:
    terms: list[str] = []
    label_pattern = r"(?:品牌|牌子|类型|品类|类别|产品名|商品名|型号|版本|版型|款式|材质|系列|名称)"
    pattern = re.compile(
        rf"{label_pattern}\s*[:：=]\s*([^；;，,。.!！?？\n\r|/]+)",
        flags=re.I,
    )
    for match in pattern.finditer(str(text or "")):
        value = _clean_text(match.group(1), limit=64)
        value = value.strip(" _-|，,。.!！?？()（）[]【】")
        if value and value.casefold() not in {item.casefold() for item in terms}:
            terms.append(value)
    return terms[:16]


def _derive_context_term_aliases(value: Any) -> list[str]:
    text = _clean_text(value, limit=64).strip(" _-|，,。.!！?？()（）[]【】")
    if not text:
        return []
    aliases: list[str] = []

    def add(alias: str) -> None:
        normalized = _clean_text(alias, limit=64).strip(" _-|，,。.!！?？()（）[]【】")
        if normalized and normalized != text and normalized.casefold() not in {item.casefold() for item in aliases}:
            aliases.append(normalized)

    if len(text) >= 3 and text.endswith(("版", "款", "型")):
        add(text[:-1])
    compact = re.sub(r"\s+", "", text)
    if compact != text:
        add(compact)
    return aliases[:4]


async def _complete_with_provider_timeout(
    provider: object,
    messages: list[Message],
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    timeout_sec: float,
) -> Any:
    completion = provider.complete(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
    if bool(getattr(provider, "_bridge_mode", False)):
        return await completion
    return await asyncio.wait_for(completion, timeout=timeout_sec)


def normalize_transcription_context_prior(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    category_scope = _normalize_category_scope(data.get("category_scope") or data.get("subject_domain"))
    raw_subject_domain = _normalize_subject_domain(data.get("subject_domain"))
    subject_domain = category_scope if category_scope not in {"", "unknown", "other"} else raw_subject_domain
    allowed_hotwords = _normalize_string_list(data.get("allowed_hotwords") or data.get("allowed_terms"), limit=12)
    blocked_hotwords = _normalize_string_list(data.get("blocked_hotwords") or data.get("blocked_terms"), limit=24)
    uncertainties = _normalize_string_list(data.get("uncertainties"), limit=8)
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "subject_summary": _clean_text(data.get("subject_summary") or data.get("summary"), limit=160),
        "subject_domain": subject_domain,
        "category_scope": category_scope,
        "allowed_hotwords": allowed_hotwords,
        "blocked_hotwords": blocked_hotwords,
        "uncertainties": uncertainties,
        "confidence": round(confidence, 3),
    }


def _build_prior_context(
    *,
    source_name: str,
    source_context: dict[str, Any] | None,
    workflow_template: str | None,
) -> dict[str, Any]:
    context = dict(source_context or {}) if isinstance(source_context, dict) else {}
    resolved_feedback = context.get("resolved_feedback") if isinstance(context.get("resolved_feedback"), dict) else {}
    return {
        "source_name": str(source_name or "").strip(),
        "workflow_template": str(workflow_template or "").strip(),
        "video_description": _clean_text(context.get("video_description"), limit=500),
        "manual_video_summary": _clean_text(context.get("manual_video_summary"), limit=500),
        "resolved_feedback": {
            key: resolved_feedback.get(key)
            for key in (
                "subject_brand",
                "subject_model",
                "subject_type",
                "video_theme",
                "summary",
                "keywords",
                "search_queries",
                "correction_notes",
                "supplemental_context",
            )
            if resolved_feedback.get(key)
        },
    }


def _has_informative_prior_context(context: dict[str, Any]) -> bool:
    return any(
        str(context.get(key) or "").strip()
        for key in ("source_name", "video_description", "manual_video_summary")
    ) or bool(context.get("resolved_feedback"))


def _build_prior_prompt(context: dict[str, Any]) -> str:
    return (
        "你需要在 ASR 转写前，仅根据源文件名、视频说明、人工填写的信息判断这期视频可能在说什么。"
        "不要参考历史热词、工作流模板热词或同类视频例句；workflow_template 只能作为弱背景。"
        "allowed_hotwords 只能放当前上下文中直接出现或高度等价的品牌、型号、产品名、成分、类别词；"
        "blocked_hotwords 放那些看起来会误导 ASR 的题材词，例如标题像零食但含有 EDC 风格命名时，应屏蔽折刀/刀具等无强证据词。"
        "如果证据不足就留空，不要猜。"
        "category_scope 只能是 food/flashlight/knife/bag/tools/other/unknown。"
        "输出 JSON："
        '{"subject_summary":"","subject_domain":"","category_scope":"unknown","allowed_hotwords":[],"blocked_hotwords":[],"uncertainties":[],"confidence":0.0}'
        f"\n当前上下文：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _normalize_string_list(value: Any, *, limit: int) -> list[str]:
    raw_items = value if isinstance(value, (list, tuple, set)) else [value]
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item, limit=64)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_category_scope(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _VALID_CATEGORY_SCOPES:
        return text
    aliases = {
        "snack": "food",
        "candy": "food",
        "light": "flashlight",
        "torch": "flashlight",
        "edc_knife": "knife",
        "knife": "knife",
        "tool": "tools",
    }
    return aliases.get(text, "")


def _normalize_subject_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"unknown", "other"}:
        return ""
    return _normalize_category_scope(text) or text[:48]


def _clean_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _format_prior_error(exc: Exception) -> str:
    message = " ".join(str(exc or "").strip().split()) or type(exc).__name__
    return f"{type(exc).__name__}: {message[:200]}"

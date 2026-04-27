from __future__ import annotations

import asyncio
import json
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
            response = await asyncio.wait_for(
                provider.complete(
                    [
                        Message(role="system", content="你是中文短视频转写热词前置判断器，只输出 JSON。"),
                        Message(role="user", content=_build_prior_prompt(context)),
                    ],
                    temperature=0.1,
                    max_tokens=700,
                    json_mode=True,
                ),
                timeout=max(5.0, float(timeout_sec or 25.0)),
            )
            payload = response.as_json()
            normalized = normalize_transcription_context_prior(payload)
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

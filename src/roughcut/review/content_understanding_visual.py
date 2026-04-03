from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text


async def infer_visual_semantic_evidence(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    mode = str((visual_capability or {}).get("mode") or "").strip()
    if mode == "native_multimodal":
        return await _infer_with_native_multimodal(frame_paths, capabilities)
    if mode in {"mcp", "visual_mcp"}:
        return await _infer_with_visual_mcp(frame_paths, capabilities)
    return _build_visual_semantic_stub(
        frame_paths=frame_paths,
        capabilities=capabilities,
        mode=mode or "unavailable",
        status="unavailable",
        failure_reason="visual_capability_unavailable",
    )


async def _infer_with_native_multimodal(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    normalized_frame_paths = _normalize_frame_paths(frame_paths)
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    provider = str((visual_capability or {}).get("provider") or "").strip()
    prompt = _build_native_multimodal_prompt()
    try:
        content = await complete_with_images(
            prompt,
            normalized_frame_paths,
            max_tokens=700,
            temperature=0.0,
            json_mode=True,
        )
        payload = _load_json_payload(content)
        if not isinstance(payload, dict) or not payload:
            raise ValueError("visual understanding payload was not a JSON object")
        return _build_visual_semantic_response(
            payload=payload,
            frame_paths=normalized_frame_paths,
            provider=provider,
            mode="native_multimodal",
            status="ready",
            failure_reason="",
        )
    except Exception:
        return _build_visual_semantic_stub(
            frame_paths=normalized_frame_paths,
            capabilities=capabilities,
            mode="native_multimodal",
            status="degraded",
            failure_reason="visual_parse_failed",
        )


async def _infer_with_visual_mcp(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    return _build_visual_semantic_stub(
        frame_paths=frame_paths,
        capabilities=capabilities,
        mode="mcp",
        status="stubbed",
        failure_reason="visual_mcp_not_implemented",
    )


def _build_visual_semantic_stub(
    *,
    frame_paths: list[Path] | list[str],
    capabilities: dict[str, Any],
    mode: str,
    status: str = "unavailable",
    failure_reason: str = "",
) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    provider = str((visual_capability or {}).get("provider") or "").strip()
    return _build_empty_visual_semantic_structure(
        provider=provider,
        mode=mode,
        frame_paths=frame_paths,
        status=status,
        failure_reason=failure_reason,
    )


def _build_visual_semantic_response(
    *,
    payload: dict[str, Any],
    frame_paths: list[Path],
    provider: str,
    mode: str,
    status: str,
    failure_reason: str,
) -> dict[str, Any]:
    result = _build_empty_visual_semantic_structure(
        provider=provider,
        mode=mode,
        frame_paths=frame_paths,
        status=status,
        failure_reason=failure_reason,
    )
    result["provider"] = _normalize_text(payload.get("provider")) or result["provider"]
    result["mode"] = _normalize_text(payload.get("mode")) or result["mode"]
    result["frame_paths"] = _normalize_frame_path_strings(payload.get("frame_paths")) or result["frame_paths"]
    result["object_categories"] = _normalize_text_list(payload.get("object_categories"))
    result["visible_brands"] = _normalize_text_list(payload.get("visible_brands"))
    result["visible_models"] = _normalize_text_list(payload.get("visible_models"))
    result["subject_candidates"] = _normalize_text_list(payload.get("subject_candidates"))
    result["interaction_type"] = _normalize_text(payload.get("interaction_type"))
    result["scene_context"] = _normalize_text(payload.get("scene_context"))
    result["evidence_notes"] = _normalize_text_list(payload.get("evidence_notes"))
    frame_level_findings = payload.get("frame_level_findings")
    if isinstance(frame_level_findings, list):
        result["frame_level_findings"] = frame_level_findings
    return result


def _build_empty_visual_semantic_structure(
    *,
    provider: str,
    mode: str,
    frame_paths: list[Path] | list[str],
    status: str,
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "mode": mode,
        "status": status,
        "failure_reason": failure_reason,
        "frame_paths": _normalize_frame_path_strings(frame_paths),
        "object_categories": [],
        "visible_brands": [],
        "visible_models": [],
        "subject_candidates": [],
        "interaction_type": "",
        "scene_context": "",
        "evidence_notes": [],
        "frame_level_findings": [],
    }


def _build_native_multimodal_prompt() -> str:
    return (
        "你是通用的视频画面语义抽取器。请只根据输入的多帧图像判断，不要依赖字幕、外部知识或任务预设。"
        "核心目标是识别画面中的主体物体、操作行为、可见品牌/型号和场景语义。"
        "要特别区分主体和背景，不要把海报、包装、桌垫、装饰、文字贴纸或其他背景物误判为主体。"
        "如果多帧里主体一致，合并成同一个判断；如果不同帧出现不同主体，保留最有证据的候选并在 findings 里说明。"
        "请输出严格 JSON，对象必须包含这些字段："
        "provider, mode, frame_paths, object_categories, visible_brands, visible_models, subject_candidates, "
        "interaction_type, scene_context, evidence_notes, frame_level_findings。"
        "字段要求："
        "provider 和 mode 由你回填为当前视觉理解结果；frame_paths 直接回填输入帧路径字符串数组；"
        "object_categories, visible_brands, visible_models, subject_candidates, evidence_notes 必须是字符串数组；"
        "interaction_type 和 scene_context 必须是字符串；"
        "frame_level_findings 是可选数组，每项用于记录单帧观察，尽量包含 frame、finding、evidence。"
        "不要输出 Markdown，不要输出代码块，不要输出解释。"
    )


def _load_json_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(extract_json_text(text))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_frame_paths(frame_paths: list[Path] | list[str]) -> list[Path]:
    normalized: list[Path] = []
    for path in list(frame_paths or []):
        text = str(path).strip()
        if not text:
            continue
        normalized.append(Path(text))
    return normalized


def _normalize_frame_path_strings(frame_paths: Any) -> list[str]:
    if not isinstance(frame_paths, list):
        return []
    normalized: list[str] = []
    for path in frame_paths:
        text = str(path).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        text = _normalize_text(value)
        if not text:
            return []
        return [item for item in _split_text_candidates(text) if item]
    normalized: list[str] = []
    for item in value:
        text = _normalize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _split_text_candidates(text: str) -> list[str]:
    candidates = []
    for piece in text.replace("，", ",").replace("；", ",").replace("、", ",").replace("\n", ",").split(","):
        cleaned = piece.strip()
        if cleaned:
            candidates.append(cleaned)
    return candidates

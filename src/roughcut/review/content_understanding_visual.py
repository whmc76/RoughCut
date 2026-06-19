from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.providers.zhipu_vision_mcp import ZhipuVisionMCPError, analyze_images_with_mcp, analyze_video_with_mcp


async def infer_visual_semantic_evidence(
    frame_paths: list[Path] | list[str],
    capabilities: dict[str, Any],
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    mode = str((visual_capability or {}).get("mode") or "").strip()
    if mode == "native_multimodal":
        return await _infer_with_native_multimodal(frame_paths, capabilities)
    if mode == "llm_mcp_vision":
        return await _infer_with_llm_mcp_vision(frame_paths, capabilities, source_path=source_path)
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
    model = str((visual_capability or {}).get("model") or "").strip()
    prompt = _build_native_multimodal_prompt()
    try:
        content = await complete_with_images(
            prompt,
            normalized_frame_paths,
            max_tokens=700,
            temperature=0.0,
            json_mode=True,
            preferred_provider=provider or None,
            preferred_model=model or None,
        )
        payload = _load_json_payload(content)
        if not isinstance(payload, dict) or not payload:
            raise ValueError("visual understanding payload was not a JSON object")
        return _build_visual_semantic_response(
            payload=payload,
            frame_paths=normalized_frame_paths,
            provider=provider,
            model=model,
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


async def _infer_with_llm_mcp_vision(
    frame_paths: list[Path] | list[str],
    capabilities: dict[str, Any],
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    normalized_frame_paths = _normalize_frame_paths(frame_paths)
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    provider = str((visual_capability or {}).get("provider") or "").strip()
    model = str((visual_capability or {}).get("model") or "").strip()
    prompt = _build_mcp_vision_prompt()
    video_path = _normalize_optional_path(source_path)
    if video_path is not None:
        try:
            video_result = await analyze_video_with_mcp(
                video_path,
                prompt=_build_mcp_video_prompt(),
                timeout_sec=180,
            )
            payload = _load_json_payload(video_result.content)
            if isinstance(payload, dict) and payload:
                return _build_visual_semantic_response(
                    payload=payload,
                    frame_paths=normalized_frame_paths,
                    provider=provider,
                    model=model,
                    mode="llm_mcp_vision",
                    status="ready",
                    failure_reason="",
                )
        except ZhipuVisionMCPError:
            pass
        except Exception:
            pass
    try:
        frame_results = await analyze_images_with_mcp(
            _sample_frame_paths(normalized_frame_paths),
            prompt=prompt,
            timeout_sec=90,
        )
        payload = _merge_mcp_visual_payloads(frame_results)
        if not payload:
            raise ValueError("vision mcp returned an empty payload")
        return _build_visual_semantic_response(
            payload=payload,
            frame_paths=normalized_frame_paths,
            provider=provider,
            model=model,
            mode="llm_mcp_vision",
            status="ready",
            failure_reason="",
        )
    except ZhipuVisionMCPError:
        return _build_visual_semantic_stub(
            frame_paths=normalized_frame_paths,
            capabilities=capabilities,
            mode="llm_mcp_vision",
            status="degraded",
            failure_reason="vision_mcp_unavailable",
        )
    except Exception:
        return _build_visual_semantic_stub(
            frame_paths=normalized_frame_paths,
            capabilities=capabilities,
            mode="llm_mcp_vision",
            status="degraded",
            failure_reason="visual_parse_failed",
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
    model = str((visual_capability or {}).get("model") or "").strip()
    return _build_empty_visual_semantic_structure(
        provider=provider,
        model=model,
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
    model: str,
    mode: str,
    status: str,
    failure_reason: str,
) -> dict[str, Any]:
    result = _build_empty_visual_semantic_structure(
        provider=provider,
        model=model,
        mode=mode,
        frame_paths=frame_paths,
        status=status,
        failure_reason=failure_reason,
    )
    result["provider"] = _normalize_text(payload.get("provider")) or result["provider"]
    result["model"] = _normalize_text(payload.get("model")) or result["model"]
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
        result["frame_level_findings"] = _normalize_frame_level_findings(frame_level_findings)
    result["timeline_events"] = _normalize_visual_timeline_events(
        payload.get("timeline_events"),
        frame_level_findings=result["frame_level_findings"],
    )
    return result


def _build_empty_visual_semantic_structure(
    *,
    provider: str,
    model: str,
    mode: str,
    frame_paths: list[Path] | list[str],
    status: str,
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
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
        "timeline_events": [],
    }


def _build_native_multimodal_prompt() -> str:
    return (
        "你是通用的视频画面语义抽取器。请只根据输入的多帧图像判断，不要依赖字幕、外部知识或任务预设。"
        "核心目标是识别画面中的主体物体、操作行为、可见品牌/型号和场景语义。"
        "要特别区分主体和背景，不要把海报、包装、桌垫、装饰、文字贴纸或其他背景物误判为主体。"
        "object_categories 和 subject_candidates 要尽量给出最接近真实产品的具体类别，例如 backpack、flashlight、folding_knife、utility_knife、multitool、hard_case，"
        "不要在看得出来时只写 tool、gear、accessory 这类过泛词。"
        "如果多帧里主体一致，合并成同一个判断；如果不同帧出现不同主体，保留最有证据的候选并在 findings 里说明。"
        "必须特别识别失手掉落、麦克风/设备脱落、弯腰捡起、整理收音设备、暂停重来、走出画面处理事故等废片动作。"
        "请输出严格 JSON，对象必须包含这些字段："
        "provider, mode, frame_paths, object_categories, visible_brands, visible_models, subject_candidates, "
        "interaction_type, scene_context, evidence_notes, frame_level_findings, timeline_events。"
        "字段要求："
        "provider 和 mode 由你回填为当前视觉理解结果；frame_paths 直接回填输入帧路径字符串数组；"
        "object_categories, visible_brands, visible_models, subject_candidates, evidence_notes 必须是字符串数组；"
        "interaction_type 和 scene_context 必须是字符串；"
        "frame_level_findings 是可选数组，每项用于记录单帧观察，尽量包含 frame、finding、evidence。"
        "timeline_events 是可选数组，每项尽量包含 start_sec, end_sec, role, keep_priority, summary, evidence。"
        "废片动作必须输出 role 为 junk 或 retake、keep_priority 为 drop 的 timeline_event，不要把这类事故当正常展示。"
        "不要输出 Markdown，不要输出代码块，不要输出解释。"
    )


def _build_mcp_vision_prompt() -> str:
    return (
        "请只根据当前这张图片做视觉理解，不要依赖字幕、文件名、外部知识或任务预设。"
        "必须特别识别失手掉落、麦克风/设备脱落、弯腰捡起、整理收音设备、暂停重来、走出画面处理事故等废片动作。"
        "请输出严格 JSON，对象必须包含这些字段："
        "object_categories, visible_brands, visible_models, subject_candidates, "
        "interaction_type, scene_context, evidence_notes, frame_level_findings, timeline_events。"
        "字段要求："
        "object_categories, visible_brands, visible_models, subject_candidates, evidence_notes 必须是字符串数组；"
        "interaction_type 和 scene_context 必须是字符串；"
        "frame_level_findings 是数组，每项尽量包含 finding 和 evidence；"
        "timeline_events 是数组，每项尽量包含 start_sec, end_sec, role, keep_priority, summary, evidence；"
        "废片动作必须输出 role 为 junk 或 retake、keep_priority 为 drop 的 timeline_event，不要把这类事故当正常展示；"
        "主体识别要尽量具体，不要只写 tool、gear、item 这类过泛词；"
        "不要输出 Markdown，不要输出代码块，不要输出解释。"
    )


def _build_mcp_video_prompt() -> str:
    return (
        "请只根据这条视频做视觉理解，不要依赖文件名、外部知识或任务预设。"
        "核心任务不是发布文案，而是为自动剪辑提供可执行的时间轴事件。"
        "请识别主体产品、展示动作、关键演示段，也必须识别废片动作："
        "失手掉落、麦克风/设备脱落、弯腰捡起、整理收音设备、暂停重来、走出画面处理事故、明显 NG。"
        "废片动作必须输出 role 为 junk 或 retake、keep_priority 为 drop 的 timeline_event。"
        "正常产品展示可输出 demo/detail_showcase/comparison/high。"
        "请输出严格 JSON，对象必须包含这些字段："
        "object_categories, visible_brands, visible_models, subject_candidates, interaction_type, scene_context, "
        "evidence_notes, frame_level_findings, timeline_events。"
        "timeline_events 是数组，每项必须尽量包含 start_sec, end_sec, role, keep_priority, summary, evidence, confidence。"
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


def _merge_mcp_visual_payloads(frame_results: list[Any]) -> dict[str, Any]:
    merged = {
        "object_categories": [],
        "visible_brands": [],
        "visible_models": [],
        "subject_candidates": [],
        "interaction_type": "",
        "scene_context": "",
        "evidence_notes": [],
        "frame_level_findings": [],
        "timeline_events": [],
    }
    for item in list(frame_results or []):
        payload = _load_json_payload(getattr(item, "content", ""))
        if not payload:
            continue
        _extend_unique(merged["object_categories"], _normalize_text_list(payload.get("object_categories")))
        _extend_unique(merged["visible_brands"], _normalize_text_list(payload.get("visible_brands")))
        _extend_unique(merged["visible_models"], _normalize_text_list(payload.get("visible_models")))
        _extend_unique(merged["subject_candidates"], _normalize_text_list(payload.get("subject_candidates")))
        _extend_unique(merged["evidence_notes"], _normalize_text_list(payload.get("evidence_notes")))
        _extend_visual_timeline_events(
            merged["timeline_events"],
            _normalize_visual_timeline_events(
                payload.get("timeline_events"),
                frame_level_findings=payload.get("frame_level_findings"),
                default_frame_path=str(getattr(item, "image_path", "") or ""),
            ),
        )
        interaction_type = _normalize_text(payload.get("interaction_type"))
        scene_context = _normalize_text(payload.get("scene_context"))
        if interaction_type and not merged["interaction_type"]:
            merged["interaction_type"] = interaction_type
        if scene_context and not merged["scene_context"]:
            merged["scene_context"] = scene_context
        frame_findings = payload.get("frame_level_findings")
        if isinstance(frame_findings, list):
            for finding in frame_findings:
                if not isinstance(finding, dict):
                    continue
                entry = dict(finding)
                entry.setdefault("frame", str(getattr(item, "image_path", "") or ""))
                timestamp = _frame_timestamp_from_path(entry.get("frame"))
                if timestamp is not None and entry.get("timestamp_sec") is None:
                    entry["timestamp_sec"] = round(timestamp, 3)
                merged["frame_level_findings"].append(entry)
        elif any((interaction_type, scene_context)):
            merged["frame_level_findings"].append(
                {
                    "frame": str(getattr(item, "image_path", "") or ""),
                    "finding": interaction_type or scene_context,
                    "evidence": ", ".join(_normalize_text_list(payload.get("object_categories"))[:3]),
                }
            )
    return merged if any(merged.values()) else {}


def _sample_frame_paths(frame_paths: list[Path], *, max_count: int = 8) -> list[Path]:
    if len(frame_paths) <= max_count:
        return list(frame_paths)
    targeted = [path for path in frame_paths if Path(path).stem.startswith("target_")]
    if targeted:
        selected = list(targeted[:max_count])
        remaining_budget = max_count - len(selected)
        if remaining_budget <= 0:
            return selected
        background = [path for path in frame_paths if path not in selected]
        selected.extend(_evenly_sample_paths(background, max_count=remaining_budget))
        return selected[:max_count]
    return _evenly_sample_paths(frame_paths, max_count=max_count)


def _evenly_sample_paths(frame_paths: list[Path], *, max_count: int) -> list[Path]:
    if len(frame_paths) <= max_count:
        return list(frame_paths)
    indices = {
        round(index * (len(frame_paths) - 1) / max(max_count - 1, 1))
        for index in range(max_count)
    }
    sampled: list[Path] = []
    for index in sorted(indices):
        sampled.append(frame_paths[index])
    return sampled[:max_count]


def _normalize_frame_level_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        timestamp = _coerce_float(entry.get("timestamp_sec") or entry.get("time_sec") or entry.get("start_sec"))
        if timestamp is None:
            timestamp = _frame_timestamp_from_path(entry.get("frame") or entry.get("image_path"))
        if timestamp is not None:
            entry["timestamp_sec"] = round(timestamp, 3)
        findings.append(entry)
    return findings


def _normalize_visual_timeline_events(
    value: Any,
    *,
    frame_level_findings: Any = None,
    default_frame_path: str = "",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            event = _normalize_visual_timeline_event(item, default_frame_path=default_frame_path)
            if event:
                events.append(event)
    for finding in _normalize_frame_level_findings(frame_level_findings):
        derived = _visual_timeline_event_from_finding(finding, default_frame_path=default_frame_path)
        if derived:
            events.append(derived)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for event in sorted(events, key=lambda item: (float(item.get("start", 0.0) or 0.0), str(item.get("role") or ""))):
        key = (int(round(float(event.get("start", 0.0) or 0.0))), str(event.get("role") or ""))
        if key in seen:
            continue
        deduped.append(event)
        seen.add(key)
    return deduped[:16]


def _normalize_visual_timeline_event(item: dict[str, Any], *, default_frame_path: str = "") -> dict[str, Any] | None:
    start = _coerce_float(item.get("start_sec") or item.get("start") or item.get("time_sec") or item.get("timestamp_sec"))
    end = _coerce_float(item.get("end_sec") or item.get("end"))
    frame_path = str(item.get("frame") or item.get("image_path") or default_frame_path or "").strip()
    if start is None:
        start = _frame_timestamp_from_path(frame_path)
    if start is None:
        return None
    role = _normalize_visual_event_role(item)
    keep_priority = _normalize_visual_event_priority(item, role=role)
    if end is None or end <= start:
        end = start + _default_visual_event_duration(role)
    summary = _normalize_text(item.get("summary") or item.get("finding") or item.get("label") or item.get("event"))
    evidence = _normalize_text(item.get("evidence") or item.get("reason"))
    if not role and not summary and not evidence:
        return None
    padded_start = max(0.0, start - (0.8 if keep_priority == "drop" else 0.0))
    padded_end = max(start + 0.6, end + (1.2 if keep_priority == "drop" else 0.0))
    return {
        "start": round(padded_start, 3),
        "end": round(padded_end, 3),
        "duration_sec": round(max(0.6, padded_end - padded_start), 3),
        "role": role or "body",
        "keep_priority": keep_priority,
        "summary": summary[:120],
        "reason_tags": _visual_event_reason_tags(summary, evidence, role=role, keep_priority=keep_priority),
        "confidence": round(_coerce_float(item.get("confidence")) or (0.72 if keep_priority == "drop" else 0.52), 3),
        "source": "visual_timeline_event",
        "evidence": evidence[:180],
        "frame": frame_path,
    }


def _visual_timeline_event_from_finding(item: dict[str, Any], *, default_frame_path: str = "") -> dict[str, Any] | None:
    summary = _normalize_text(item.get("summary") or item.get("finding") or item.get("label"))
    evidence = _normalize_text(item.get("evidence") or item.get("reason"))
    role = _role_from_visual_event_text(f"{summary} {evidence}")
    if not role:
        return None
    payload = dict(item)
    payload["summary"] = summary
    payload["evidence"] = evidence
    payload["role"] = role
    payload["keep_priority"] = "drop" if role in {"junk", "retake"} else "high"
    return _normalize_visual_timeline_event(payload, default_frame_path=default_frame_path)


def _role_from_visual_event_text(text: str) -> str:
    normalized = _normalize_text(text).lower().replace(" ", "")
    if not normalized:
        return ""
    if any(token in normalized for token in ("没有弯腰", "未弯腰", "没有掉落", "未掉落", "nobending", "nodrop", "standingupright")):
        return ""
    if any(token in normalized for token in ("麦克风掉", "麦克风脱落", "收音掉", "话筒掉", "micdrop", "microphonedrop")):
        return "junk"
    if any(token in normalized for token in ("掉落", "脱落", "失手", "捡起", "拾起", "弯腰捡", "走开处理", "整理设备", "调整麦克风", "重来")):
        return "junk"
    if any(token in normalized for token in ("暂停", "卡壳", "口误", "重新说")):
        return "retake"
    if any(token in normalized for token in ("对比", "差异")):
        return "comparison"
    if any(token in normalized for token in ("演示", "展示", "上手", "细节", "特写")):
        return "demo"
    return ""


def _normalize_visual_event_role(item: dict[str, Any]) -> str:
    explicit = _normalize_text(item.get("role") or item.get("type") or item.get("label")).lower()
    text_role = _role_from_visual_event_text(
        " ".join(
            _normalize_text(item.get(key))
            for key in ("summary", "finding", "event", "evidence", "reason")
            if _normalize_text(item.get(key))
        )
    )
    if explicit in {"junk", "retake", "demo", "detail_showcase", "comparison", "hook", "cta", "transition", "body"}:
        if explicit in {"junk", "retake"} and text_role not in {"junk", "retake"}:
            return text_role or ""
        return explicit
    return text_role


def _normalize_visual_event_priority(item: dict[str, Any], *, role: str) -> str:
    explicit = _normalize_text(item.get("keep_priority") or item.get("priority")).lower()
    if explicit == "drop" and role not in {"junk", "retake"}:
        return "medium"
    if explicit in {"drop", "low", "medium", "high"}:
        return explicit
    if role in {"junk", "retake"}:
        return "drop"
    if role in {"demo", "detail_showcase", "comparison", "hook", "cta"}:
        return "high"
    return "medium"


def _visual_event_reason_tags(summary: str, evidence: str, *, role: str, keep_priority: str) -> list[str]:
    tags = [tag for tag in (role, "visual_event") if tag]
    if keep_priority == "drop":
        tags.append("visual_drop_candidate")
    if _role_from_visual_event_text(f"{summary} {evidence}") in {"junk", "retake"}:
        tags.append("accidental_action")
    return tags[:6]


def _default_visual_event_duration(role: str) -> float:
    if role in {"junk", "retake"}:
        return 4.5
    return 3.4


def _extend_visual_timeline_events(target: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    existing = {
        (int(round(float(item.get("start", 0.0) or 0.0))), str(item.get("role") or ""))
        for item in target
    }
    for item in events:
        key = (int(round(float(item.get("start", 0.0) or 0.0))), str(item.get("role") or ""))
        if key in existing:
            continue
        target.append(item)
        existing.add(key)


def _frame_timestamp_from_path(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"_t(?P<seconds>\d+(?:p\d+)?)", Path(text).stem)
    if not match:
        return None
    try:
        return float(match.group("seconds").replace("p", "."))
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_frame_paths(frame_paths: list[Path] | list[str]) -> list[Path]:
    normalized: list[Path] = []
    for path in list(frame_paths or []):
        text = str(path).strip()
        if not text:
            continue
        normalized.append(Path(text))
    return normalized


def _normalize_optional_path(value: Path | str | None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text)


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


def _extend_unique(target: list[str], items: list[str]) -> None:
    existing = {item.casefold() for item in target}
    for item in items:
        key = item.casefold()
        if not key or key in existing:
            continue
        target.append(item)
        existing.add(key)

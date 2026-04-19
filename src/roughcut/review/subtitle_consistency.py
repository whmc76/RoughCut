from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from roughcut.review.subtitle_quality import build_subtitle_quality_report

ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT = "subtitle_consistency_report"

_BAD_TERM_REASON_MAP: dict[str, tuple[re.Pattern[str], str, str]] = {
    "unboxing_misheard": (re.compile(r"开枪"), "subtitle_vs_filename", "字幕里仍有“开枪”等明显开箱误识别"),
    "mt34_misheard": (re.compile(r"MP三四|MP34|MP\s*三四"), "subtitle_vs_filename", "字幕里的 MT34 型号仍有误写"),
    "noc_misheard": (re.compile(r"NZ家|\bNZ\b"), "subtitle_vs_filename", "字幕里的 NOC 品牌仍有误写"),
    "trim_misheard": (re.compile(r"四顶配"), "subtitle_vs_filename", "字幕里的次顶配版本仍有误写"),
    "edc17_numeric": (re.compile(r"幺7|幺七"), "subtitle_vs_filename", "字幕里的 EDC17 数字仍有误写"),
    "flashlight_model_knifedrift": (
        re.compile(r"(?:折刀帕|刀)(?:幺七|幺7|一七|17|二三|23|三七|37)|EDC(?:17|23|37)折刀(?:帕)?|EDC17刀(?:幺七|幺7|一七|17)|EDC23刀(?:二三|23)|EDC37刀(?:三七|37)"),
        "subtitle_vs_filename",
        "字幕把 EDC17/23/37 手电型号误写成折刀语义",
    ),
}


def _subtitle_text(item: Mapping[str, Any]) -> str:
    for key in ("text_final", "text_norm", "text_raw", "text"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _correction_attr(correction: Any, key: str) -> Any:
    if isinstance(correction, Mapping):
        return correction.get(key)
    return getattr(correction, key, None)


def _conflict_entry(*, kind: str, detail: str, resolved: bool = False, confidence: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "detail": detail,
        "resolved": resolved,
    }
    if confidence is not None:
        payload["confidence"] = confidence
    return payload


def build_subtitle_consistency_report(
    *,
    subtitle_items: Sequence[Mapping[str, Any]],
    corrections: Iterable[Any] = (),
    source_name: str = "",
    content_profile: Mapping[str, Any] | None = None,
    subtitle_quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    texts = [_subtitle_text(item) for item in subtitle_items]
    joined_text = "\n".join(texts)
    quality_report = (
        dict(subtitle_quality_report)
        if isinstance(subtitle_quality_report, Mapping)
        else build_subtitle_quality_report(
            subtitle_items=subtitle_items,
            source_name=source_name,
            content_profile=content_profile,
        )
    )

    conflicts: dict[str, list[dict[str, Any]]] = {
        "subtitle_vs_filename": [],
        "subtitle_vs_ocr": [],
        "subtitle_vs_summary": [],
        "group_context_conflicts": [],
    }
    blocking_reasons: list[str] = []
    warning_reasons: list[str] = []

    pending_count = 0
    auto_applied_count = 0
    resolved_count = 0
    for correction in corrections:
        original_span = str(_correction_attr(correction, "original_span") or "").strip()
        suggested_span = str(_correction_attr(correction, "suggested_span") or "").strip()
        auto_applied = bool(_correction_attr(correction, "auto_applied"))
        human_decision = str(_correction_attr(correction, "human_decision") or "").strip().lower()
        try:
            confidence = float(_correction_attr(correction, "confidence"))
        except (TypeError, ValueError):
            confidence = None
        resolved = auto_applied or human_decision == "accepted"
        if auto_applied:
            auto_applied_count += 1
        if resolved:
            resolved_count += 1
        else:
            pending_count += 1
        conflicts["subtitle_vs_filename"].append(
            _conflict_entry(
                kind="term_patch",
                detail=f"{original_span} -> {suggested_span}",
                resolved=resolved,
                confidence=confidence,
            )
        )

    for _code, (pattern, scope, message) in _BAD_TERM_REASON_MAP.items():
        if pattern.search(joined_text):
            conflicts[scope].append(_conflict_entry(kind="hotword_residual", detail=message))

    if pending_count > 0:
        blocking_reasons.append(f"词级术语候选待人工确认 {pending_count} 处")
    elif auto_applied_count > 0:
        warning_reasons.append(f"已应用词级纠偏 {auto_applied_count} 处")

    quality_blocking_reasons = [
        str(item).strip()
        for item in (quality_report.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    for reason in quality_blocking_reasons:
        detail = f"字幕质量门禁：{reason}"
        conflicts["subtitle_vs_summary"].append(_conflict_entry(kind="quality_gate", detail=detail))
        if detail not in blocking_reasons:
            blocking_reasons.append(detail)

    metrics = quality_report.get("metrics") if isinstance(quality_report.get("metrics"), Mapping) else {}
    semantic_bad_term_total = int(metrics.get("semantic_bad_term_total") or 0)
    lexical_bad_term_total = int(metrics.get("lexical_bad_term_total") or 0)
    if semantic_bad_term_total > 0:
        detail = f"检测到语义污染 {semantic_bad_term_total} 处，只允许人工复核，不做自动语义纠正"
        conflicts["subtitle_vs_summary"].append(_conflict_entry(kind="semantic_contamination", detail=detail))
        if detail not in blocking_reasons:
            blocking_reasons.append(detail)
    if lexical_bad_term_total > 0:
        detail = f"检测到可词级纠偏残留 {lexical_bad_term_total} 处"
        conflicts["subtitle_vs_summary"].append(_conflict_entry(kind="lexical_residual", detail=detail))
        if pending_count == 0 and detail not in warning_reasons:
            warning_reasons.append(detail)
    if bool(metrics.get("identity_missing")):
        detail = "字幕与文件名/主体线索未形成稳定一致"
        conflicts["subtitle_vs_filename"].append(_conflict_entry(kind="identity_missing", detail=detail))
        if detail not in warning_reasons:
            warning_reasons.append(detail)

    score = 100.0
    score -= float(pending_count * 9)
    score -= float(auto_applied_count * 2)
    score -= float(len(quality_blocking_reasons) * 6)
    score -= float(sum(1 for _, (pattern, _, _) in _BAD_TERM_REASON_MAP.items() if pattern.search(joined_text)) * 4)
    score = max(0.0, round(score, 2))

    return {
        "source_name": source_name,
        "score": score,
        "blocking": bool(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "conflicts": conflicts,
        "metrics": {
            "subtitle_count": len(texts),
            "pending_patch_count": pending_count,
            "resolved_patch_count": resolved_count,
            "auto_applied_patch_count": auto_applied_count,
            "quality_blocking_reason_count": len(quality_blocking_reasons),
            "lexical_bad_term_total": lexical_bad_term_total,
            "semantic_bad_term_total": semantic_bad_term_total,
        },
    }

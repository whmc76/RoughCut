from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
from roughcut.media.variant_timeline_bundle import resolve_effective_variant_timeline_bundle
from roughcut.review.content_profile import (
    _has_ingestible_product_subject_conflict,
    _is_generic_engagement_question,
    _is_generic_profile_summary,
    _is_generic_subject_type,
    _is_specific_video_theme,
)

QUALITY_ARTIFACT_TYPE = "quality_assessment"

_AUTO_FIX_STEP_PRIORITY = ("subtitle_postprocess", "glossary_review", "content_profile", "render")
_STEP_RERUN_CHAINS: dict[str, tuple[str, ...]] = {
    "subtitle_postprocess": (
        "subtitle_postprocess",
        "glossary_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
    "glossary_review": (
        "glossary_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
    "content_profile": ("content_profile", "ai_director", "avatar_commentary", "edit_plan", "render", "final_review", "platform_package"),
    "render": ("render", "final_review", "platform_package"),
}
_COMPARISON_KEYWORDS = (
    "对比",
    "一代",
    "二代",
    "三代",
    "升级",
    "区别",
    "差异",
    "新旧",
    "实测",
)
_DETAIL_KEYWORDS = (
    "亮度",
    "续航",
    "功率",
    "容量",
    "重量",
    "尺寸",
    "模式",
    "参数",
    "教程",
    "步骤",
    "节点",
    "联名",
    "uv版",
    "pro",
    "max",
)
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z]{1,8}\d{1,6}[A-Za-z0-9\u4e00-\u9fff-]{0,8}", re.IGNORECASE)
_NUMERIC_DETAIL_RE = re.compile(
    r"\d+(?:\.\d+)?(?:代|档|倍|lm|mah|w|v|mm|cm|g|kg|分钟|小时|秒|元|版)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class QualityIssue:
    code: str
    message: str
    penalty: float
    auto_fix_step: str | None = None
    blocking: bool = False


def assess_job_quality(
    *,
    job: Job,
    steps: Sequence[JobStep],
    artifacts: Sequence[Artifact],
    subtitle_items: Sequence[SubtitleItem] | None = None,
    corrections: Sequence[SubtitleCorrection] | None = None,
    completion_candidate: bool = False,
) -> dict[str, Any]:
    score = 100.0
    issues: list[QualityIssue] = []
    step_total = len(steps)
    completed_steps = sum(1 for step in steps if step.status in {"done", "skipped"})
    step_completion_ratio = (completed_steps / step_total) if step_total else 0.0
    effective_status = "done" if completion_candidate else str(job.status or "pending")

    profile_artifact = _latest_artifact(
        artifacts,
        "content_profile_final",
        "content_profile",
        "content_profile_draft",
    )
    render_artifact = _latest_artifact(artifacts, "render_outputs")
    variant_bundle_artifact = _latest_artifact(artifacts, "variant_timeline_bundle")
    profile = profile_artifact.data_json if profile_artifact and isinstance(profile_artifact.data_json, dict) else {}
    render_outputs = render_artifact.data_json if render_artifact and isinstance(render_artifact.data_json, dict) else {}
    variant_bundle = (
        variant_bundle_artifact.data_json
        if variant_bundle_artifact and isinstance(variant_bundle_artifact.data_json, dict)
        else {}
    )
    variant_bundle = resolve_effective_variant_timeline_bundle(variant_bundle, render_outputs=render_outputs) or {}
    corrections = list(corrections or [])
    subtitle_items = list(subtitle_items or [])
    subtitle_text = _build_subtitle_text(subtitle_items)
    profile_text = _build_profile_text(profile)

    if not subtitle_items:
        issues.append(
            QualityIssue("missing_subtitles", "缺少可评估字幕，无法判断字幕质量", 30.0, auto_fix_step="subtitle_postprocess")
        )

    if not profile:
        issues.append(QualityIssue("missing_content_profile", "缺少内容画像结果", 30.0, auto_fix_step="content_profile"))
    else:
        review_mode = str(profile.get("review_mode") or "").strip().lower()
        automation = profile.get("automation_review") if isinstance(profile.get("automation_review"), dict) else {}
        automation_score = _safe_float(automation.get("score"))
        if automation_score is not None and automation_score < 0.75:
            issues.append(
                QualityIssue(
                    "low_profile_confidence",
                    f"内容画像自动确认置信度偏低（{automation_score:.2f}）",
                    8.0,
                    auto_fix_step="content_profile",
                )
            )
        if review_mode not in {"auto_confirmed", "manual_confirmed", ""} and profile_artifact and profile_artifact.artifact_type != "content_profile_final":
            issues.append(
                QualityIssue("profile_unconfirmed", "内容画像仍处于未确认状态", 12.0, auto_fix_step="content_profile")
            )

        subject_type = str(profile.get("subject_type") or "").strip()
        video_theme = str(profile.get("video_theme") or "").strip()
        summary = str(profile.get("summary") or "").strip()
        question = str(profile.get("engagement_question") or "").strip()
        preset_name = str(profile.get("workflow_template") or profile.get("preset_name") or "").strip()

        if _is_generic_subject_type(subject_type):
            issues.append(
                QualityIssue("generic_subject_type", "主体识别过于泛化", 14.0, auto_fix_step="content_profile")
            )
        if not _is_specific_video_theme(video_theme, preset_name=preset_name):
            issues.append(
                QualityIssue("generic_video_theme", "视频主题不够具体", 10.0, auto_fix_step="content_profile")
            )
        if not summary or _is_generic_profile_summary(summary):
            issues.append(
                QualityIssue("generic_summary", "摘要过于笼统，缺少有效信息", 18.0, auto_fix_step="content_profile")
            )
        elif len(_normalize_text(summary)) < 14:
            issues.append(
                QualityIssue("thin_summary", "摘要信息量偏薄", 8.0, auto_fix_step="content_profile")
            )
        if _is_generic_engagement_question(question):
            issues.append(
                QualityIssue("generic_question", "互动问题过于套路化", 7.0, auto_fix_step="content_profile")
            )

        detail_cues = _extract_detail_cues(subtitle_text)
        detail_coverage = sum(1 for cue in detail_cues if _contains_normalized(profile_text, cue))
        comparison_signals = sum(1 for keyword in _COMPARISON_KEYWORDS if keyword in subtitle_text)
        profile_has_comparison = any(keyword in profile_text for keyword in _COMPARISON_KEYWORDS)

        if detail_cues and detail_coverage == 0:
            issues.append(
                QualityIssue(
                    "detail_blind",
                    "没有抓住字幕里的真实细节线索",
                    18.0,
                    auto_fix_step="content_profile",
                )
            )
        elif len(detail_cues) >= 3 and detail_coverage < min(2, len(detail_cues)):
            issues.append(
                QualityIssue(
                    "detail_coverage_low",
                    "识别到了主题，但细节覆盖仍然不足",
                    10.0,
                    auto_fix_step="content_profile",
                )
            )

        if comparison_signals >= 2 and not profile_has_comparison:
            issues.append(
                QualityIssue(
                    "comparison_blind",
                    "字幕里存在明显对比信息，但画像没有体现",
                    12.0,
                    auto_fix_step="content_profile",
                )
            )

        if _has_ingestible_product_subject_conflict(
            profile=profile,
            subtitle_items=[_subtitle_item_to_dict(item) for item in subtitle_items],
            transcript_excerpt=str(profile.get("transcript_excerpt") or ""),
        ):
            issues.append(
                QualityIssue(
                    "subject_conflict",
                    "字幕主体与内容画像主体冲突，疑似把入口产品误识别成装备/工具类",
                    22.0,
                    auto_fix_step="content_profile",
                    blocking=True,
                )
            )

    pending_corrections = sum(1 for item in corrections if item.human_decision not in {"accepted", "rejected"})
    if pending_corrections > 0:
        penalty = min(12.0, 4.0 + pending_corrections * 1.5)
        issues.append(
            QualityIssue(
                "pending_subtitle_corrections",
                f"仍有 {pending_corrections} 条字幕/术语纠错未处理",
                penalty,
            )
        )

    sync_check = _resolve_packaged_variant_subtitle_sync_check(variant_bundle) or _resolve_subtitle_sync_check(
        render_outputs
    )
    if sync_check and sync_check.get("status") == "warning":
        warning_codes = [str(code) for code in sync_check.get("warning_codes") or [] if str(code).strip()]
        issues.append(
            QualityIssue(
                "subtitle_sync_issue",
                str(sync_check.get("message") or "成片字幕时间轴与视频明显错位"),
                18.0 if "subtitle_out_of_bounds" in warning_codes else 10.0,
                auto_fix_step="render",
            )
        )

    for issue in issues:
        score -= issue.penalty

    score = max(0.0, min(100.0, round(score, 1)))
    grade = _grade_for_score(score)
    recommended_rerun_steps = _pick_recommended_rerun_steps(issues)
    recommended_rerun_step = recommended_rerun_steps[0] if recommended_rerun_steps else None
    issue_codes = [issue.code for issue in issues]

    return {
        "score": score,
        "grade": grade,
        "status": effective_status,
        "step_completion_ratio": round(step_completion_ratio, 3),
        "issue_codes": issue_codes,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "penalty": issue.penalty,
                "auto_fix_step": issue.auto_fix_step,
                "blocking": issue.blocking,
            }
            for issue in issues
        ],
        "recommended_rerun_step": recommended_rerun_step,
        "recommended_rerun_steps": recommended_rerun_steps,
        "auto_fixable": bool(recommended_rerun_step) and not any(issue.blocking for issue in issues),
        "signals": {
            "subtitle_detail_cues": _extract_detail_cues(subtitle_text),
            "profile_detail_coverage": sum(
                1 for cue in _extract_detail_cues(subtitle_text) if _contains_normalized(profile_text, cue)
            ),
            "pending_subtitle_corrections": pending_corrections,
            "profile_artifact_type": profile_artifact.artifact_type if profile_artifact else None,
            "subtitle_item_count": len(subtitle_items),
            "effective_status": effective_status,
            "step_completion_ratio": round(step_completion_ratio, 3),
            "subtitle_sync": sync_check,
        },
    }


def _latest_artifact(artifacts: Sequence[Artifact], *artifact_types: str) -> Artifact | None:
    type_priority = {name: index for index, name in enumerate(artifact_types)}
    candidates = [artifact for artifact in artifacts if artifact.artifact_type in type_priority]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda artifact: (
            -type_priority.get(artifact.artifact_type, 999),
            artifact.created_at,
            str(artifact.id),
        ),
    )


def _build_subtitle_text(items: Sequence[SubtitleItem]) -> str:
    parts: list[str] = []
    for item in items:
        text = str(item.text_final or item.text_norm or item.text_raw or "").strip()
        if text:
            parts.append(text)
    return _normalize_text(" ".join(parts))


def _subtitle_item_to_dict(item: SubtitleItem) -> dict[str, Any]:
    return {
        "item_index": int(item.item_index or 0),
        "start_time": float(item.start_time or 0.0),
        "end_time": float(item.end_time or 0.0),
        "text_raw": str(item.text_raw or ""),
        "text_norm": str(item.text_norm or ""),
        "text_final": str(item.text_final or ""),
    }


def _build_profile_text(profile: dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(profile.get(key) or "").strip()
            for key in (
                "subject_brand",
                "subject_model",
                "subject_type",
                "video_theme",
                "hook_line",
                "summary",
                "engagement_question",
                "cover_title",
            )
        )
    )


def _extract_detail_cues(text: str) -> list[str]:
    if not text:
        return []
    cues: list[str] = []
    seen: set[str] = set()

    for raw in _MODEL_TOKEN_RE.findall(text):
        cue = _normalize_text(raw)
        if len(cue) >= 4 and cue not in seen:
            seen.add(cue)
            cues.append(cue)

    for raw in _NUMERIC_DETAIL_RE.findall(text):
        cue = _normalize_text(raw)
        if cue and cue not in seen:
            seen.add(cue)
            cues.append(cue)

    for keyword in (*_COMPARISON_KEYWORDS, *_DETAIL_KEYWORDS):
        cue = _normalize_text(keyword)
        if cue in text and cue not in seen:
            seen.add(cue)
            cues.append(cue)

    return cues[:10]


def _contains_normalized(text: str, cue: str) -> bool:
    normalized_cue = _normalize_text(cue)
    return bool(normalized_cue and normalized_cue in _normalize_text(text))


def _normalize_text(text: str) -> str:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    return compact.casefold()


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_recommended_rerun_steps(issues: Sequence[QualityIssue]) -> list[str]:
    candidate_steps = {issue.auto_fix_step for issue in issues if issue.auto_fix_step}
    rerun_steps: list[str] = []
    for step_name in _AUTO_FIX_STEP_PRIORITY:
        if step_name not in candidate_steps:
            continue
        for chain_step in _STEP_RERUN_CHAINS.get(step_name, (step_name,)):
            if chain_step not in rerun_steps:
                rerun_steps.append(chain_step)
    return rerun_steps


def _grade_for_score(score: float) -> str:
    if score >= 90.0:
        return "A"
    if score >= 75.0:
        return "B"
    if score >= 60.0:
        return "C"
    return "D"


def _resolve_packaged_variant_subtitle_sync_check(variant_bundle: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(variant_bundle, dict):
        return None
    variants = variant_bundle.get("variants")
    if not isinstance(variants, dict):
        return None
    packaged_variant = variants.get("packaged")
    if not isinstance(packaged_variant, dict):
        return None
    quality_checks = packaged_variant.get("quality_checks")
    if not isinstance(quality_checks, dict):
        return None
    subtitle_sync = quality_checks.get("subtitle_sync")
    if isinstance(subtitle_sync, dict):
        return subtitle_sync
    return None


def _resolve_subtitle_sync_check(render_outputs: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(render_outputs, dict):
        return None
    quality_checks = render_outputs.get("quality_checks")
    if isinstance(quality_checks, dict):
        subtitle_sync = quality_checks.get("subtitle_sync")
        if isinstance(subtitle_sync, dict):
            return subtitle_sync

    packaged_mp4 = str(render_outputs.get("packaged_mp4") or "").strip()
    packaged_srt = str(render_outputs.get("packaged_srt") or "").strip()
    if not packaged_mp4 or not packaged_srt:
        return None
    return _compute_subtitle_sync_check(Path(packaged_mp4), Path(packaged_srt))


def _compute_subtitle_sync_check(video_path: Path, subtitle_path: Path) -> dict[str, Any] | None:
    if not video_path.exists() or not subtitle_path.exists():
        return None
    video_duration = _probe_media_duration(video_path)
    subtitle_ranges = _parse_srt_ranges(subtitle_path)
    if video_duration <= 0 or not subtitle_ranges:
        return None

    first_start = subtitle_ranges[0][0]
    last_end = subtitle_ranges[-1][1]
    out_of_bounds_count = sum(1 for start, end in subtitle_ranges if start < -0.05 or end > video_duration + 0.35 or end < start)
    leading_gap = max(0.0, first_start)
    trailing_gap = max(0.0, video_duration - last_end)
    duration_gap = abs(video_duration - last_end)

    warning_codes: list[str] = []
    if out_of_bounds_count > 0:
        warning_codes.append("subtitle_out_of_bounds")
    if trailing_gap > max(2.0, video_duration * 0.12):
        warning_codes.append("subtitle_trailing_gap_large")
    if leading_gap > max(2.5, video_duration * 0.15):
        warning_codes.append("subtitle_leading_gap_large")
    if duration_gap > max(2.5, video_duration * 0.15):
        warning_codes.append("subtitle_duration_gap_large")

    status = "warning" if warning_codes else "ok"
    message = (
        "成片字幕存在越界或明显首尾错位"
        if warning_codes
        else "成片字幕时间轴与视频时长基本匹配"
    )
    return {
        "status": status,
        "message": message,
        "video_duration_sec": round(video_duration, 3),
        "subtitle_first_start_sec": round(first_start, 3),
        "subtitle_last_end_sec": round(last_end, 3),
        "leading_gap_sec": round(leading_gap, 3),
        "trailing_gap_sec": round(trailing_gap, 3),
        "duration_gap_sec": round(duration_gap, 3),
        "subtitle_out_of_bounds_count": out_of_bounds_count,
        "warning_codes": warning_codes,
    }


def _probe_media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return 0.0
    try:
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return 0.0
    try:
        return float(payload.get("format", {}).get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parse_srt_ranges(path: Path) -> list[tuple[float, float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    ranges: list[tuple[float, float]] = []
    for line in text.splitlines():
        if "-->" not in line:
            continue
        start_text, end_text = [part.strip() for part in line.split("-->", 1)]
        start_sec = _parse_srt_timestamp(start_text)
        end_sec = _parse_srt_timestamp(end_text)
        if start_sec is None or end_sec is None:
            continue
        ranges.append((start_sec, end_sec))
    return ranges


def _parse_srt_timestamp(value: str) -> float | None:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.:](\d{3})", value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0

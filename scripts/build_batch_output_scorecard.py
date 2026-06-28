from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from roughcut.db.models import Artifact, Timeline
from roughcut.db.session import get_session_factory
from roughcut.edit.cut_analysis import cut_analysis_effective_applied_cuts
from roughcut.edit.packaging_timeline import packaging_timeline_editing_accents
from roughcut.media.variant_timeline_bundle import (
    variant_cut_analysis_summary,
    resolve_effective_variant_timeline_bundle,
    variant_llm_cut_review,
    variant_refine_decision_summary,
    variant_subtitle_timeline_issues,
    variant_timeline_diagnostics,
)
from roughcut.pipeline.quality import (
    collect_editing_risk_gate_signals,
    collect_editing_risk_gate_signals_from_inputs,
)
from roughcut.pipeline.render_diagnostics import classify_render_or_avatar_reason_category
from roughcut.publication_platform_matrix import (
    normalize_publication_platform_name,
    platform_manual_handoff_only,
    platform_soft_verification_fields,
)
from roughcut.publication_packaging import publication_packaging_entry_publish_ready
from scripts.run_fullchain_batch import _normalize_render_diagnostics_for_reporting


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a detailed output scorecard from a full-chain batch report.")
    parser.add_argument("--batch-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def _score_to_grade(score: float | None) -> str:
    if score is None:
        return "N/A"
    if score >= 90.0:
        return "A"
    if score >= 80.0:
        return "B"
    if score >= 70.0:
        return "C"
    if score >= 60.0:
        return "D"
    return "E"


def _round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, float(value))), 1)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    numbers = [float(item) for item in values if item is not None]
    if not numbers:
        return None
    return _round_score(sum(numbers) / len(numbers))


def _live_readiness_summary(batch_report: dict[str, Any]) -> dict[str, Any] | None:
    payload = batch_report.get("live_readiness") if isinstance(batch_report.get("live_readiness"), dict) else {}
    if not payload:
        return None
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed_checks = sorted(
        str(name).strip()
        for name, check in checks.items()
        if str(name).strip() and isinstance(check, dict) and not bool(check.get("passed"))
    )
    summary = {
        "gate_passed": bool(payload.get("gate_passed")),
        "status": str(payload.get("status") or "").strip() or None,
        "failed_checks": failed_checks,
    }
    render_check = checks.get("render_end_state_stability") if isinstance(checks.get("render_end_state_stability"), dict) else {}
    if render_check:
        summary["render_end_state_stability"] = {
            key: render_check.get(key)
            for key in (
                "failed_render_job_count",
                "strategy_validation_evaluated_job_count",
                "strategy_validation_blocking_job_count",
                "strategy_validation_blocking_job_ids",
                "strategy_validation_blocking_reasons",
                "strategy_validation_strategy_types",
                "strategy_validation_review_gates",
            )
            if render_check.get(key) not in (None, "", [])
        }
    return summary


def _score_from_status(status: str | None, *, pass_score: float = 100.0, warn_score: float = 75.0) -> float:
    normalized = str(status or "").strip().lower()
    if normalized == "pass":
        return pass_score
    if normalized == "warn":
        return warn_score
    return 0.0


def _file_exists(raw_path: str | None) -> bool:
    value = str(raw_path or "").strip()
    return bool(value) and Path(value).exists()


def _normalize_packaging_platforms(packaging: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_platforms = packaging.get("platforms")
    if isinstance(raw_platforms, dict):
        return {
            normalize_publication_platform_name(platform): dict(payload)
            for platform, payload in raw_platforms.items()
            if isinstance(payload, dict)
        }
    if isinstance(raw_platforms, list):
        normalized: dict[str, dict[str, Any]] = {}
        for payload in raw_platforms:
            if not isinstance(payload, dict):
                continue
            platform = normalize_publication_platform_name(payload.get("platform") or payload.get("platform_name"))
            if not platform:
                continue
            normalized[platform] = dict(payload)
        return normalized
    return {}


def _platform_packaging_title(payload: dict[str, Any]) -> str:
    titles = list(payload.get("titles") or []) if isinstance(payload.get("titles"), list) else []
    if titles:
        return str(titles[0] or "").strip()
    copy_material = payload.get("copy_material") if isinstance(payload.get("copy_material"), dict) else {}
    return str(copy_material.get("primary_title") or "").strip()


def _platform_packaging_body(payload: dict[str, Any]) -> str:
    description = str(payload.get("description") or "").strip()
    if description:
        return description
    copy_material = payload.get("copy_material") if isinstance(payload.get("copy_material"), dict) else {}
    return str(copy_material.get("body") or "").strip()


def _summarize_variant_score(name: str, media_path: str | None, quality_check: dict[str, Any] | None) -> dict[str, Any]:
    if not media_path:
        return {
            "name": name,
            "score": None,
            "grade": "N/A",
            "status": "not_generated",
            "reasons": [f"{name} 版本未产出"],
            "path": "",
        }

    reasons: list[str] = []
    score = 100.0 if _file_exists(media_path) else 20.0
    if _file_exists(media_path):
        reasons.append("文件已生成")
    else:
        reasons.append("文件路径存在但未在磁盘发现")

    check = quality_check if isinstance(quality_check, dict) else {}
    sync_status = str(check.get("status") or "").strip().lower()
    warning_codes = [str(code).strip() for code in list(check.get("warning_codes") or []) if str(code).strip()]
    if sync_status == "ok":
        reasons.append("字幕同步质检通过")
    elif sync_status == "warning":
        score -= 18.0
        reasons.append("字幕同步质检存在 warning")
    elif check:
        score -= 10.0
        reasons.append("存在质检信息但状态不明确")
    else:
        score -= 6.0
        reasons.append("缺少字幕同步质检结果")

    if warning_codes:
        severe_codes = {
            "subtitle_out_of_bounds",
            "subtitle_timestamp_disorder",
            "subtitle_overlap_detected",
            "subtitle_invalid_range",
            "subtitle_short_flash_detected",
            "subtitle_burst_density_detected",
            "subtitle_local_gap_unstable",
        }
        severe_count = len([code for code in warning_codes if code in severe_codes])
        score -= min(45.0, 10.0 * severe_count + 4.0 * (len(warning_codes) - severe_count))
        reasons.append("warning_codes=" + ", ".join(warning_codes))

    effective_gap = _safe_float(check.get("effective_duration_gap_sec"))
    if effective_gap is not None and effective_gap > 1.0:
        score -= min(12.0, effective_gap * 4.0)
        reasons.append(f"有效时长偏差 {effective_gap:.2f}s")

    score = _round_score(score)
    return {
        "name": name,
        "score": score,
        "grade": _score_to_grade(score),
        "status": "done" if _file_exists(media_path) else "missing",
        "reasons": reasons,
        "path": media_path,
    }


def _build_version_scores(render_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(render_outputs, dict):
        return []
    variant_quality_checks = (
        render_outputs.get("quality_checks")
        if isinstance(render_outputs.get("quality_checks"), dict)
        else {}
    )
    variant_specs = (
        ("packaged", "packaged_mp4", "subtitle_sync"),
        ("plain", "plain_mp4", "plain_subtitle_sync"),
        ("avatar", "avatar_mp4", "avatar_subtitle_sync"),
        ("ai_effect", "ai_effect_mp4", "ai_effect_subtitle_sync"),
    )
    return [
        _summarize_variant_score(
            variant_name,
            str(render_outputs.get(media_path_key) or "").strip(),
            variant_quality_checks.get(quality_check_key),
        )
        for variant_name, media_path_key, quality_check_key in variant_specs
    ]


def _score_platform_package(packaging: dict[str, Any], publish_path: str | None) -> dict[str, Any]:
    if not packaging and not publish_path:
        return {
            "score": None,
            "grade": "N/A",
            "status": "not_generated",
            "summary": "未发现多平台包装产物",
            "platform_scores": [],
        }

    platforms = _normalize_packaging_platforms(packaging)
    title_audit = packaging.get("title_audit") if isinstance(packaging.get("title_audit"), dict) else {}
    platform_audits = title_audit.get("platforms") if isinstance(title_audit.get("platforms"), dict) else {}
    platform_scores: list[dict[str, Any]] = []
    per_platform_values: list[float] = []
    ready_count = 0
    manual_handoff_count = 0
    blocked_count = 0
    for platform_name, payload in platforms.items():
        normalized_platform = normalize_publication_platform_name(platform_name)
        audit = platform_audits.get(platform_name) if isinstance(platform_audits.get(platform_name), dict) else {}
        if not audit and isinstance(platform_audits.get(normalized_platform), dict):
            audit = platform_audits.get(normalized_platform)
        summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
        warning_count = int(summary.get("warning_count") or 0)
        error_count = int(summary.get("error_count") or 0)
        titles = list(payload.get("titles") or []) if isinstance(payload, dict) else []
        tags = list(payload.get("tags") or []) if isinstance(payload, dict) else []
        title = _platform_packaging_title(payload) if isinstance(payload, dict) else ""
        description = _platform_packaging_body(payload) if isinstance(payload, dict) else ""
        live_publish_preflight = payload.get("live_publish_preflight") if isinstance(payload.get("live_publish_preflight"), dict) else {}
        preflight_status = str(live_publish_preflight.get("status") or "").strip().lower()
        blocking_reasons = list(live_publish_preflight.get("blocking_reasons") or [])
        manual_handoff = bool(payload.get("manual_handoff_only")) or platform_manual_handoff_only(normalized_platform)
        soft_fields = platform_soft_verification_fields(normalized_platform)

        if manual_handoff:
            score = 100.0
            platform_status = "manual_handoff"
            manual_handoff_count += 1
        else:
            platform_ready = publication_packaging_entry_publish_ready(payload)
            score = 100.0
            if not title:
                score -= 35.0
            if not description:
                score -= 20.0
            if "tags" not in soft_fields and not tags:
                score -= 15.0
            if preflight_status and preflight_status not in {"ready", "pass", "verified"}:
                score -= min(40.0, max(1, len(blocking_reasons)) * 10.0)
            if blocking_reasons:
                score -= min(20.0, len(blocking_reasons) * 5.0)
            platform_status = "ready" if platform_ready else "blocked"
            if platform_status == "ready":
                ready_count += 1
            else:
                blocked_count += 1
        score -= min(30.0, warning_count * 3.0)
        score -= min(50.0, error_count * 12.0)
        score = _round_score(score)
        per_platform_values.append(score)
        platform_scores.append(
            {
                "platform": normalized_platform,
                "score": score,
                "grade": _score_to_grade(score),
                "status": platform_status,
                "title_count": len(titles) if titles else (1 if title else 0),
                "tag_count": len(tags),
                "warning_count": warning_count,
                "error_count": error_count,
                "blocking_reason_count": len(blocking_reasons),
            }
        )

    score = _mean(per_platform_values) if per_platform_values else (100.0 if _file_exists(publish_path) else 60.0)
    summary = f"已生成 {len(platforms)} 个平台包装版本"
    if manual_handoff_count:
        summary += f"，人工接管 {manual_handoff_count} 个"
    if ready_count or blocked_count:
        summary += f"，预发布就绪 {ready_count} 个，阻断 {blocked_count} 个"
    if title_audit:
        overall = title_audit.get("summary") if isinstance(title_audit.get("summary"), dict) else {}
        summary += f"，标题审核 warning={int(overall.get('warning_count') or 0)} error={int(overall.get('error_count') or 0)}"
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": "done" if _file_exists(publish_path) else "generated_without_file_check",
        "summary": summary,
        "platform_scores": platform_scores,
        "publish_path": publish_path or "",
        "manual_handoff_count": manual_handoff_count,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
    }


def _score_avatar(
    avatar_plan: dict[str, Any],
    render_outputs: dict[str, Any],
    render_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = render_diagnostics if isinstance(render_diagnostics, dict) else {}
    runtime_avatar_result = (
        diagnostics.get("avatar_result")
        if isinstance(diagnostics.get("avatar_result"), dict)
        else {}
    )
    render_step = (
        diagnostics.get("render_step")
        if isinstance(diagnostics.get("render_step"), dict)
        else {}
    )
    render_avatar_result = (
        render_outputs.get("avatar_result")
        if isinstance(render_outputs.get("avatar_result"), dict)
        else {}
    )
    avatar_result = runtime_avatar_result or render_avatar_result
    weak_missing_avatar_reason = str(avatar_result.get("reason") or "").strip().lower() if isinstance(avatar_result, dict) else ""
    if weak_missing_avatar_reason in {"missing_avatar_render", "missing_avatar_video", "missing_avatar_output"}:
        render_step_status = str(render_step.get("status") or "").strip().lower()
        render_step_reason = str(render_step.get("reason") or "").strip()
        if render_step_status == "failed" and render_step_reason:
            avatar_result = {}
    if not avatar_result:
        render_step_status = str(render_step.get("status") or "").strip().lower()
        render_step_reason = str(render_step.get("reason") or "").strip()
        if render_step_status == "failed" and render_step_reason:
            avatar_result = {
                "status": "blocked",
                "reason": render_step_reason,
                "detail": str(render_step.get("detail") or render_step.get("error") or "").strip(),
            }
        elif render_step_status and render_step_status != "done":
            avatar_result = {"status": render_step_status}
    if not avatar_plan and not avatar_result:
        return {
            "score": None,
            "grade": "N/A",
            "status": "not_enabled",
            "summary": "未启用数字人模块",
        }

    status = str(avatar_result.get("status") or "").strip().lower()
    integration_mode = str(avatar_result.get("integration_mode") or avatar_plan.get("integration_mode") or "").strip()
    render_status = str(((avatar_plan.get("render_execution") or {}).get("status")) or "").strip().lower()
    segments = list(avatar_plan.get("segments") or []) if isinstance(avatar_plan, dict) else []
    reasons: list[str] = []
    score = 100.0
    reason = str(avatar_result.get("reason") or "").strip()
    reason_category = str(avatar_result.get("reason_category") or "").strip()
    if not reason_category:
        reason_category = classify_render_or_avatar_reason_category(reason) or ""

    if status == "skipped" and reason_category == "not_configured":
        return {
            "score": None,
            "grade": "N/A",
            "status": "not_configured",
            "summary": (
                f"avatar_result=skipped:{reason}({reason_category})"
                if reason
                else "avatar_result=skipped:not_configured"
            ),
            "provider": str(avatar_plan.get("provider") or ""),
            "voice_provider": str(avatar_plan.get("voice_provider") or ""),
        }

    if status == "done":
        reasons.append("数字人版本已写入")
    elif status:
        score -= 35.0
        if reason:
            if reason_category:
                reasons.append(f"avatar_result={status}:{reason}({reason_category})")
            else:
                reasons.append(f"avatar_result={status}:{reason}")
        else:
            reasons.append(f"avatar_result={status}")
    else:
        score -= 45.0
        reasons.append("缺少 avatar_result")

    if integration_mode:
        reasons.append(f"集成模式 {integration_mode}")
    if render_status in {"deferred_to_render", "done"}:
        reasons.append(f"render_execution={render_status}")
    elif render_status:
        score -= 10.0
        reasons.append(f"render_execution={render_status}")

    if segments:
        reasons.append(f"口播分段 {len(segments)} 条")
    else:
        score -= 8.0
        reasons.append("未生成独立口播分段，当前为全轨透传/弱插入模式")

    score = _round_score(score)
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": status or "unknown",
        "summary": "；".join(reasons),
        "provider": str(avatar_plan.get("provider") or ""),
        "voice_provider": str(avatar_plan.get("voice_provider") or ""),
    }


def _score_tts(avatar_plan: dict[str, Any]) -> dict[str, Any]:
    dubbing = avatar_plan.get("dubbing_execution") if isinstance(avatar_plan.get("dubbing_execution"), dict) else {}
    if not dubbing:
        return {
            "score": None,
            "grade": "N/A",
            "status": "not_available",
            "summary": "未发现 TTS / dubbing 执行信息",
        }

    status = str(dubbing.get("status") or "").strip().lower()
    provider = str(dubbing.get("provider") or "").strip()
    reason = str(dubbing.get("reason") or "").strip()
    if status == "done":
        score = 100.0
        summary = "TTS / 配音执行成功"
    elif status == "skipped" and reason == "full_track_audio_passthrough":
        score = None
        summary = "本次数字人采用全轨音频透传，未触发独立 TTS 合成"
    elif status == "failed":
        score = 0.0
        summary = "TTS / 配音执行失败"
    elif status:
        score = 60.0
        summary = f"TTS / 配音状态 {status}"
    else:
        score = None
        summary = "TTS / 配音状态未知"
    return {
        "score": _round_score(score),
        "grade": _score_to_grade(_round_score(score)),
        "status": status or "unknown",
        "summary": summary,
        "provider": provider,
    }


def _score_ai_effects(render_plan: dict[str, Any], render_outputs: dict[str, Any], variant_bundle: dict[str, Any]) -> dict[str, Any]:
    ai_effect_path = str(render_outputs.get("ai_effect_mp4") or "").strip()
    packaged_variant = (
        ((variant_bundle.get("variants") or {}).get("packaged") or {})
        if isinstance(variant_bundle, dict)
        else {}
    )
    overlay_events = (packaged_variant.get("overlay_events") or {}) if isinstance(packaged_variant, dict) else {}
    packaged_overlays = list(overlay_events.get("emphasis_overlays") or [])
    packaged_sounds = list(overlay_events.get("sound_effects") or [])
    editing_accents = packaging_timeline_editing_accents(render_plan)
    transitions = (editing_accents.get("transitions") or {}) if isinstance(editing_accents, dict) else {}
    transition_indexes = list(transitions.get("boundary_indexes") or []) if isinstance(transitions, dict) else []

    if not ai_effect_path:
        return {
            "score": 0.0,
            "grade": _score_to_grade(0.0),
            "status": "missing",
            "summary": "AI 特效版本未生成",
        }

    score = 82.0 if _file_exists(ai_effect_path) else 30.0
    if packaged_overlays:
        score += min(10.0, len(packaged_overlays) * 3.0)
    if packaged_sounds:
        score += min(8.0, len(packaged_sounds) * 2.0)
    if transition_indexes:
        score += min(6.0, len(transition_indexes) * 2.0)
    score = _round_score(score)
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": "done" if _file_exists(ai_effect_path) else "missing_file",
        "summary": (
            f"AI 特效版本已生成，强调字幕 {len(packaged_overlays)} 处，音效 {len(packaged_sounds)} 处，"
            f"转场 {len(transition_indexes)} 处"
        ),
        "path": ai_effect_path,
    }


def _score_subtitle_effects(render_plan: dict[str, Any]) -> dict[str, Any]:
    subtitles = render_plan.get("subtitles") if isinstance(render_plan.get("subtitles"), dict) else {}
    motion_style = str(subtitles.get("motion_style") or "motion_static")
    section_profiles = list(subtitles.get("section_profiles") or [])
    choreography = subtitles.get("choreography_summary") if isinstance(subtitles.get("choreography_summary"), dict) else {}
    hero_profile_count = int(choreography.get("hero_profile_count") or 0)
    cta_profile_count = int(choreography.get("cta_profile_count") or 0)

    score = 72.0
    if motion_style != "motion_static":
        score += 12.0
    if len(section_profiles) >= 2:
        score += 8.0
    if hero_profile_count > 0:
        score += 5.0
    if cta_profile_count > 0:
        score += 3.0
    score = _round_score(score)
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": "done",
        "summary": (
            f"主字幕动效 {motion_style}，section_profiles={len(section_profiles)}，"
            f"hero={hero_profile_count}，cta={cta_profile_count}"
        ),
        "motion_style": motion_style,
    }


def _score_viewing_experience(
    *,
    job: dict[str, Any],
    render_outputs: dict[str, Any],
    subtitle_quality: dict[str, Any],
    render_plan: dict[str, Any],
    variant_bundle: dict[str, Any] | None,
    version_scores: list[dict[str, Any]],
    editing_risk_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Score viewer-facing polish separately from delivery/blocking quality gates."""

    components: list[dict[str, Any]] = []

    subtitle_metrics = subtitle_quality.get("metrics") if isinstance(subtitle_quality.get("metrics"), dict) else {}
    subtitle_timeline_issues = variant_subtitle_timeline_issues(resolve_effective_variant_timeline_bundle(variant_bundle) or {})
    subtitle_warning_count = len(list(subtitle_quality.get("warning_reasons") or []))
    subtitle_blocking_count = len(list(subtitle_quality.get("blocking_reasons") or []))
    short_fragment_count = int(subtitle_metrics.get("short_fragment_count") or 0)
    generic_word_split_count = int(subtitle_metrics.get("generic_word_split_count") or 0)
    filler_count = int(subtitle_metrics.get("filler_count") or 0)
    low_signal_count = int(subtitle_metrics.get("low_signal_count") or 0)
    subtitle_reasons: list[str] = []
    subtitle_score = 100.0
    quality_checks = render_outputs.get("quality_checks") if isinstance(render_outputs.get("quality_checks"), dict) else {}
    subtitle_sync_warning_codes = [
        str(code).strip()
        for payload in quality_checks.values()
        if isinstance(payload, dict)
        for code in list(payload.get("warning_codes") or [])
        if str(code).strip()
    ]
    severe_sync_codes = {
        "subtitle_short_flash_detected",
        "subtitle_burst_density_detected",
        "subtitle_local_gap_unstable",
        "subtitle_out_of_bounds",
        "subtitle_timestamp_disorder",
        "subtitle_overlap_detected",
        "subtitle_invalid_range",
    }.intersection(subtitle_sync_warning_codes)
    if subtitle_blocking_count:
        subtitle_score -= min(55.0, 24.0 * subtitle_blocking_count)
        subtitle_reasons.append(f"字幕阻断项 {subtitle_blocking_count} 个")
    if severe_sync_codes:
        subtitle_score -= min(45.0, 16.0 + 8.0 * len(severe_sync_codes))
        subtitle_reasons.append("字幕时间结构异常: " + ", ".join(sorted(severe_sync_codes)))
    final_alignment = quality_checks.get("final_render_subtitle_asr_alignment")
    if not isinstance(final_alignment, dict):
        subtitle_score -= 42.0
        subtitle_reasons.append("缺少最终成片音频 Qwen3 字幕校准审计")
    elif not bool(final_alignment.get("gate_pass")):
        audit = final_alignment.get("audit") if isinstance(final_alignment.get("audit"), dict) else {}
        bad_drift_count = int(audit.get("bad_drift_count") or 0)
        unmatched_count = int(audit.get("unmatched_count") or 0)
        avg_start = audit.get("avg_abs_start_drift_sec")
        avg_end = audit.get("avg_abs_end_drift_sec")
        subtitle_score -= min(72.0, 38.0 + bad_drift_count * 2.0 + unmatched_count * 3.0)
        subtitle_reasons.append(
            "最终成片音频 Qwen3 字幕校准失败"
            + f": bad_drift={bad_drift_count}, unmatched={unmatched_count}, avg_start={avg_start}, avg_end={avg_end}"
        )
    else:
        audit = final_alignment.get("audit") if isinstance(final_alignment.get("audit"), dict) else {}
        subtitle_reasons.append(
            "最终成片音频 Qwen3 字幕校准通过"
            + f": matched={int(audit.get('matched_count') or 0)}/{int(audit.get('event_count') or 0)}"
        )
    if subtitle_timeline_issues:
        subtitle_score -= min(30.0, 14.0 + len(subtitle_timeline_issues) * 4.0)
        subtitle_reasons.append(f"字幕时间线校验异常 {len(subtitle_timeline_issues)} 个")
    if subtitle_warning_count:
        subtitle_score -= min(18.0, 5.0 * subtitle_warning_count)
        subtitle_reasons.append(f"字幕 warning {subtitle_warning_count} 个")
    if short_fragment_count > 2:
        subtitle_score -= min(12.0, (short_fragment_count - 2) * 2.0)
        subtitle_reasons.append(f"短碎句 {short_fragment_count} 条")
    if generic_word_split_count:
        subtitle_score -= min(14.0, generic_word_split_count * 4.0)
        subtitle_reasons.append(f"普通词跨字幕截断 {generic_word_split_count} 处")
    if filler_count or low_signal_count:
        subtitle_score -= min(10.0, filler_count * 1.5 + low_signal_count * 2.0)
        subtitle_reasons.append(f"低信息/语气词字幕 {filler_count + low_signal_count} 条")
    if not subtitle_reasons or not any(
        not str(reason).startswith("最终成片音频 Qwen3")
        for reason in subtitle_reasons
    ):
        subtitle_reasons.append("字幕读感干净，无明显碎片/截断")
    components.append(
        {
            "name": "subtitle_readability",
            "score": _round_score(subtitle_score),
            "grade": _score_to_grade(_round_score(subtitle_score)),
            "reasons": subtitle_reasons,
        }
    )

    diagnostics = variant_timeline_diagnostics(resolve_effective_variant_timeline_bundle(variant_bundle) or {})
    cut_summary = diagnostics.get("cut_analysis_summary") if isinstance(diagnostics.get("cut_analysis_summary"), dict) else {}
    refine_summary = diagnostics.get("refine_decision_summary") if isinstance(diagnostics.get("refine_decision_summary"), dict) else {}
    keep_ratio = _safe_float(job.get("keep_ratio")) or 0.0
    accepted_cut_count = _effective_applied_cut_count(
        accepted_cut_count=int(cut_summary.get("accepted_cut_count") or 0),
        refine_decision_summary=refine_summary,
    )
    advisory_high_risk_count = int((editing_risk_metrics or {}).get("high_risk_cut_count") or 0) - int(
        (diagnostics or {}).get("blocking_high_risk_cut_count") or 0
    )
    pacing_score = 100.0
    pacing_reasons: list[str] = []
    if keep_ratio <= 0:
        pacing_score -= 28.0
        pacing_reasons.append("缺少有效保留比，无法判断节奏")
    elif keep_ratio > 0.92:
        pacing_score -= min(18.0, (keep_ratio - 0.92) * 150.0)
        pacing_reasons.append(f"保留比偏高 {keep_ratio:.1%}，可能偏拖")
    elif keep_ratio < 0.45:
        pacing_score -= min(18.0, (0.45 - keep_ratio) * 120.0)
        pacing_reasons.append(f"保留比偏低 {keep_ratio:.1%}，可能跳切过猛")
    else:
        pacing_reasons.append(f"保留比 {keep_ratio:.1%}，节奏区间合理")
    if bool((editing_risk_metrics or {}).get("blocking_high_risk_cuts")):
        pacing_score -= 30.0
        pacing_reasons.append("存在阻断级高风险 cut")
    if advisory_high_risk_count > 0:
        pacing_score -= min(10.0, advisory_high_risk_count * 1.0)
        pacing_reasons.append(f"静音边界建议抽检 {advisory_high_risk_count} 处")
    if accepted_cut_count <= 0 and _safe_float(job.get("output_duration_sec")) and float(job.get("output_duration_sec") or 0.0) > 180.0:
        pacing_score -= 8.0
        pacing_reasons.append("长视频几乎无有效剪切，需人工确认节奏")
    elif accepted_cut_count > 0:
        pacing_reasons.append(f"有效剪切 {accepted_cut_count} 处")
    components.append(
        {
            "name": "pacing_and_cut_flow",
            "score": _round_score(pacing_score),
            "grade": _score_to_grade(_round_score(pacing_score)),
            "reasons": pacing_reasons,
        }
    )

    subtitles_plan = render_plan.get("subtitles") if isinstance(render_plan.get("subtitles"), dict) else {}
    section_profiles = list(subtitles_plan.get("section_profiles") or [])
    editing_accents = packaging_timeline_editing_accents(render_plan)
    effect_policy = editing_accents.get("effect_policy") if isinstance(editing_accents.get("effect_policy"), dict) else {}
    overlays = list(editing_accents.get("emphasis_overlays") or [])
    sounds = list(editing_accents.get("sound_effects") or [])
    transitions = editing_accents.get("transitions") if isinstance(editing_accents.get("transitions"), dict) else {}
    transition_count = len(list(transitions.get("boundary_indexes") or []))
    duration = _safe_float(job.get("output_duration_sec")) or 0.0
    density_base = max(1.0, duration / 60.0)
    visual_score = 100.0
    visual_reasons: list[str] = []
    if not section_profiles:
        visual_score -= 12.0
        visual_reasons.append("缺少分段字幕样式编排")
    else:
        visual_reasons.append(f"字幕分段样式 {len(section_profiles)} 段")
    if effect_policy and not bool(effect_policy.get("preserve_color")):
        visual_score -= 12.0
        visual_reasons.append("包装效果未声明保色")
    if len(overlays) > max(3.0, density_base * 1.2):
        visual_score -= min(12.0, (len(overlays) - density_base) * 1.5)
        visual_reasons.append(f"强调字幕密度偏高 {len(overlays)} 处")
    elif overlays:
        visual_reasons.append(f"强调字幕 {len(overlays)} 处")
    if len(sounds) > max(3.0, density_base * 1.2):
        visual_score -= min(10.0, (len(sounds) - density_base) * 1.2)
        visual_reasons.append(f"音效点缀密度偏高 {len(sounds)} 处")
    elif sounds:
        visual_reasons.append(f"轻量音效 {len(sounds)} 处")
    if transition_count > max(6.0, density_base * 2.0):
        visual_score -= min(8.0, transition_count - density_base * 2.0)
        visual_reasons.append(f"转场密度偏高 {transition_count} 处")
    elif transition_count:
        visual_reasons.append(f"转场 {transition_count} 处")
    if not visual_reasons:
        visual_reasons.append("包装信息不足，无法判断视觉观感")
    components.append(
        {
            "name": "visual_polish_and_restraint",
            "score": _round_score(visual_score),
            "grade": _score_to_grade(_round_score(visual_score)),
            "reasons": visual_reasons,
        }
    )

    delivery_score = 100.0
    delivery_reasons: list[str] = []
    packaged_path = str(render_outputs.get("packaged_mp4") or render_outputs.get("plain_mp4") or job.get("output_path") or "").strip()
    if not packaged_path:
        delivery_score -= 45.0
        delivery_reasons.append("缺少主成片路径")
    elif not _file_exists(packaged_path):
        delivery_score -= 35.0
        delivery_reasons.append("主成片文件不存在")
    else:
        delivery_reasons.append("主成片文件可访问")
    generated_versions = [
        item
        for item in version_scores
        if str(item.get("status") or "").strip().lower() in {"done", "missing_file", "missing"}
        and item.get("score") is not None
    ]
    weak_versions = [
        item
        for item in generated_versions
        if _safe_float(item.get("score")) is not None and float(item.get("score") or 0.0) < 80.0
    ]
    if weak_versions:
        delivery_score -= min(16.0, len(weak_versions) * 4.0)
        delivery_reasons.append("存在版本质检偏弱: " + ", ".join(str(item.get("name") or "") for item in weak_versions))
    sync_warnings = [
        name
        for name, payload in quality_checks.items()
        if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "warning"
    ]
    final_alignment = quality_checks.get("final_render_subtitle_asr_alignment")
    if not isinstance(final_alignment, dict):
        delivery_score -= 28.0
        delivery_reasons.append("缺少最终成片音频 Qwen3 字幕审计")
    elif not bool(final_alignment.get("gate_pass")):
        delivery_score -= 42.0
        delivery_reasons.append("最终成片音频 Qwen3 字幕审计未通过")
    if sync_warnings:
        delivery_score -= min(18.0, len(sync_warnings) * 6.0)
        delivery_reasons.append("字幕同步 warning: " + ", ".join(sync_warnings))
    if not sync_warnings and quality_checks:
        delivery_reasons.append("主版本字幕同步稳定")
    components.append(
        {
            "name": "delivery_stability",
            "score": _round_score(delivery_score),
            "grade": _score_to_grade(_round_score(delivery_score)),
            "reasons": delivery_reasons,
        }
    )

    weights = {
        "subtitle_readability": 0.30,
        "pacing_and_cut_flow": 0.30,
        "visual_polish_and_restraint": 0.25,
        "delivery_stability": 0.15,
    }
    score = _round_score(
        sum(float(component["score"]) * weights.get(str(component.get("name")), 0.0) for component in components)
    )
    weak_components = [component for component in components if float(component.get("score") or 0.0) < 90.0]
    summary_parts = [
        f"{component['name']}={component.get('score')}"
        for component in components
    ]
    if weak_components:
        summary_parts.append(
            "重点关注 "
            + " / ".join(
                f"{component['name']}:{'; '.join(component.get('reasons') or [])}"
                for component in weak_components[:2]
            )
        )
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": "pass" if score is not None and score >= 90.0 else "warn" if score is not None and score >= 75.0 else "fail",
        "summary": "；".join(summary_parts),
        "components": components,
    }


def _score_editing(job: dict[str, Any], editorial: dict[str, Any], render_plan: dict[str, Any]) -> dict[str, Any]:
    return _score_editing_from_legacy_editorial(job, editorial, render_plan)


def _score_editing_from_inputs(
    *,
    keep_ratio: float,
    accepted_cut_count: int,
    llm_reviewed: bool,
    llm_error: str,
    llm_candidate_count: int,
    boundary_indexes: list[Any],
    issue_codes: list[str],
    refine_mode: str = "",
    refine_candidate_total: int = 0,
) -> dict[str, Any]:
    score = 82.0
    if keep_ratio > 0:
        score += 10.0
    if 0.35 <= keep_ratio <= 0.8:
        score += 8.0
    if accepted_cut_count:
        score += min(8.0, accepted_cut_count)
    if llm_reviewed and llm_candidate_count > 0:
        score += 6.0
    elif llm_error:
        score -= 12.0
    elif llm_candidate_count > 0:
        score -= 6.0
    if boundary_indexes:
        score += min(6.0, len(boundary_indexes) * 2.0)
    if "edit_plan_llm_cut_review_timeout" in issue_codes:
        score -= 8.0
    if "subtitle_sync_issue" in issue_codes:
        score -= 10.0
    score = _round_score(score)
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "status": "done",
        "summary": (
            f"保留比 {keep_ratio:.1%}，accepted_cuts={accepted_cut_count}，"
            f"llm_cut_review={'yes' if llm_reviewed else 'not_required' if llm_candidate_count <= 0 else 'no'}，"
            f"transition_boundaries={len(boundary_indexes)}"
            + (f"，refine_mode={refine_mode}" if refine_mode else "")
            + (f"，refine_candidates={refine_candidate_total}" if refine_candidate_total else "")
            + (f"，llm_error={llm_error}" if llm_error else "")
            + (f"，llm_candidates={llm_candidate_count}" if llm_candidate_count else "")
        ),
    }


def _effective_applied_cut_count(
    *,
    accepted_cut_count: int,
    refine_decision_summary: dict[str, Any] | None = None,
) -> int:
    summary = refine_decision_summary if isinstance(refine_decision_summary, dict) else {}
    refine_auto_apply_cut_count = int(
        summary.get("rule_auto_apply_cut_count") or 0
    ) + int(summary.get("multimodal_auto_apply_cut_count") or 0)
    return max(int(accepted_cut_count or 0), refine_auto_apply_cut_count)


def _score_editing_from_legacy_editorial(
    job: dict[str, Any],
    editorial: dict[str, Any],
    render_plan: dict[str, Any],
) -> dict[str, Any]:
    analysis = editorial.get("analysis") if isinstance(editorial.get("analysis"), dict) else {}
    keep_ratio = _safe_float(job.get("keep_ratio")) or 0.0
    accepted_cuts = list(analysis.get("accepted_cuts") or [])
    llm_cut_review = analysis.get("llm_cut_review") if isinstance(analysis.get("llm_cut_review"), dict) else {}
    llm_reviewed = bool(llm_cut_review.get("reviewed"))
    llm_error = str(llm_cut_review.get("error") or "").strip()
    llm_candidate_count = int(llm_cut_review.get("candidate_count") or 0)
    transitions = ((packaging_timeline_editing_accents(render_plan).get("transitions")) or {}) if isinstance(render_plan, dict) else {}
    boundary_indexes = list(transitions.get("boundary_indexes") or []) if isinstance(transitions, dict) else []
    issue_codes = [str(code).strip() for code in list(job.get("quality_issue_codes") or []) if str(code).strip()]
    return _score_editing_from_inputs(
        keep_ratio=keep_ratio,
        accepted_cut_count=len(accepted_cuts),
        llm_reviewed=llm_reviewed,
        llm_error=llm_error,
        llm_candidate_count=llm_candidate_count,
        boundary_indexes=boundary_indexes,
        issue_codes=issue_codes,
    )


def _editing_risk_metrics_from_legacy_inputs(
    job: dict[str, Any],
    editorial: dict[str, Any],
    cut_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis = editorial.get("analysis") if isinstance(editorial.get("analysis"), dict) else {}
    llm_cut_review = analysis.get("llm_cut_review") if isinstance(analysis.get("llm_cut_review"), dict) else {}
    accepted_cuts = cut_analysis_effective_applied_cuts(cut_analysis) or [
        dict(item) for item in list(analysis.get("accepted_cuts") or []) if isinstance(item, dict)
    ]
    multimodal_trim_review_summary = (
        dict(cut_analysis.get("multimodal_trim_review_summary") or {}) if isinstance(cut_analysis, dict) else {}
    )
    high_risk_cut_count = sum(
        1 for item in accepted_cuts if float(item.get("boundary_keep_energy", 0.0) or 0.0) >= 1.0
    )
    editing_risk_gate = collect_editing_risk_gate_signals_from_inputs(
        high_risk_cut_count=high_risk_cut_count,
        llm_cut_review=llm_cut_review,
        multimodal_trim_review_summary=multimodal_trim_review_summary,
        refine_decision_summary={
            "candidate_manual_confirm": int((cut_analysis or {}).get("manual_confirm_candidate_count") or 0),
        },
    )
    live_stage_validations = [dict(item) for item in list(job.get("live_stage_validations") or []) if isinstance(item, dict)]
    render_stage = next(
        (item for item in live_stage_validations if str(item.get("stage") or "").strip().lower() == "render"),
        {},
    )
    render_stage_status = str(render_stage.get("status") or "").strip().lower()
    if str(job.get("status") or "").strip().lower() == "partial" and render_stage_status == "skipped":
        source_reason = "pre_render_stop_without_variant_bundle"
    elif render_stage_status == "failed":
        source_reason = "render_failed_before_variant_bundle"
    else:
        source_reason = "variant_bundle_unavailable"
    return {
        "source": "legacy_editorial_cut_analysis",
        "source_reason": source_reason,
        "high_risk_cut_count": high_risk_cut_count,
        "auto_apply_candidate_count": int((cut_analysis or {}).get("auto_apply_candidate_count") or 0),
        "manual_confirm_count": int((cut_analysis or {}).get("manual_confirm_candidate_count") or 0),
        "multimodal_pending_count": int(multimodal_trim_review_summary.get("pending_count") or 0),
        "llm_reviewed": bool(llm_cut_review.get("reviewed")),
        "llm_error": str(editing_risk_gate.get("llm_cut_review_error") or "").strip(),
        "llm_provider_degraded": bool(editing_risk_gate.get("llm_cut_review_provider_degraded")),
        "blocking_high_risk_cuts": bool(editing_risk_gate.get("blocking_high_risk_cuts")),
        "blocking_manual_confirm_heavy": bool(editing_risk_gate.get("blocking_manual_confirm_heavy")),
    }


def _score_editing_with_variant_bundle(
    job: dict[str, Any],
    editorial: dict[str, Any],
    render_plan: dict[str, Any],
    variant_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved_bundle = resolve_effective_variant_timeline_bundle(variant_bundle) or {}
    if not resolved_bundle:
        return _score_editing(job, editorial, render_plan)

    cut_analysis_summary = variant_cut_analysis_summary(resolved_bundle)
    refine_decision_summary = variant_refine_decision_summary(resolved_bundle)
    llm_cut_review = variant_llm_cut_review(resolved_bundle)
    keep_ratio = _safe_float(job.get("keep_ratio")) or 0.0
    accepted_cut_count = _effective_applied_cut_count(
        accepted_cut_count=int(cut_analysis_summary.get("accepted_cut_count") or 0),
        refine_decision_summary=refine_decision_summary,
    )
    llm_reviewed = bool(llm_cut_review.get("reviewed"))
    llm_error = str(llm_cut_review.get("error") or "").strip()
    llm_candidate_count = int(llm_cut_review.get("candidate_count") or 0)
    transitions = ((packaging_timeline_editing_accents(render_plan).get("transitions")) or {}) if isinstance(render_plan, dict) else {}
    boundary_indexes = list(transitions.get("boundary_indexes") or []) if isinstance(transitions, dict) else []
    issue_codes = [str(code).strip() for code in list(job.get("quality_issue_codes") or []) if str(code).strip()]
    refine_mode = str(refine_decision_summary.get("mode") or "").strip()
    refine_candidate_total = int(refine_decision_summary.get("candidate_total") or 0)
    return _score_editing_from_inputs(
        keep_ratio=keep_ratio,
        accepted_cut_count=accepted_cut_count,
        llm_reviewed=llm_reviewed,
        llm_error=llm_error,
        llm_candidate_count=llm_candidate_count,
        boundary_indexes=boundary_indexes,
        issue_codes=issue_codes,
        refine_mode=refine_mode,
        refine_candidate_total=refine_candidate_total,
    )


def _editing_risk_metrics(
    job: dict[str, Any],
    editorial: dict[str, Any],
    cut_analysis: dict[str, Any] | None,
    variant_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved_bundle = resolve_effective_variant_timeline_bundle(variant_bundle) or {}
    if not resolved_bundle:
        return _editing_risk_metrics_from_legacy_inputs(job, editorial, cut_analysis)
    refine_decision_summary = variant_refine_decision_summary(resolved_bundle)
    editing_risk_gate = collect_editing_risk_gate_signals(resolved_bundle)
    llm_cut_review = dict(editing_risk_gate.get("llm_cut_review") or {})
    high_risk_cut_count = int(editing_risk_gate.get("high_risk_cut_count") or 0)
    auto_apply_candidate_count = int(
        refine_decision_summary.get("candidate_auto_apply")
        or (variant_cut_analysis_summary(resolved_bundle).get("auto_apply_candidate_count") or 0)
    )
    manual_confirm_count = int(editing_risk_gate.get("refine_manual_confirm") or 0)
    multimodal_pending_count = int(editing_risk_gate.get("multimodal_pending_count") or 0)
    llm_reviewed = bool(llm_cut_review.get("reviewed"))
    llm_error = str(editing_risk_gate.get("llm_cut_review_error") or "").strip()
    return {
        "source": "variant_timeline_bundle",
        "source_reason": "variant_bundle_available",
        "high_risk_cut_count": high_risk_cut_count,
        "auto_apply_candidate_count": auto_apply_candidate_count,
        "manual_confirm_count": manual_confirm_count,
        "multimodal_pending_count": multimodal_pending_count,
        "llm_reviewed": llm_reviewed,
        "llm_error": llm_error,
        "llm_provider_degraded": bool(editing_risk_gate.get("llm_cut_review_provider_degraded")),
        "blocking_high_risk_cuts": bool(editing_risk_gate.get("blocking_high_risk_cuts")),
        "blocking_manual_confirm_heavy": bool(editing_risk_gate.get("blocking_manual_confirm_heavy")),
    }


def _build_stage_scores(job: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(job.get("live_stage_validations") or []):
        if not isinstance(item, dict):
            continue
        score = _score_from_status(str(item.get("status") or ""))
        rows.append(
            {
                "stage": str(item.get("stage") or ""),
                "status": str(item.get("status") or ""),
                "score": score,
                "grade": _score_to_grade(score),
                "summary": str(item.get("summary") or ""),
                "issue_codes": [str(code) for code in list(item.get("issue_codes") or []) if str(code).strip()],
            }
        )
    return rows


def _merge_runtime_render_diagnostics(
    batch_render_diagnostics: dict[str, Any] | None,
    runtime_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(batch_render_diagnostics or {}) if isinstance(batch_render_diagnostics, dict) else {}
    runtime = runtime_payload if isinstance(runtime_payload, dict) else {}
    for key in ("avatar_result", "cover_result"):
        value = runtime.get(key)
        if isinstance(value, dict) and value:
            merged[key] = dict(value)
    return _normalize_render_diagnostics_for_reporting(merged)


def _job_stopped_before_render(job: dict[str, Any]) -> bool:
    live_stage_scores = [dict(item) for item in list(job.get("live_stage_scores") or []) if isinstance(item, dict)]
    render_stage = next(
        (item for item in live_stage_scores if str(item.get("stage") or "").strip().lower() == "render"),
        {},
    )
    return str(render_stage.get("status") or "").strip().lower() == "skipped"


async def _load_job_runtime(job_id: str) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
        artifacts = artifact_result.scalars().all()

        timeline_result = await session.execute(
            select(Timeline).where(Timeline.job_id == job_id).order_by(Timeline.created_at.asc(), Timeline.id.asc())
        )
        timelines = timeline_result.scalars().all()

    latest_artifacts: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        latest_artifacts[str(artifact.artifact_type)] = {
            "data_json": dict(artifact.data_json) if isinstance(artifact.data_json, dict) else {},
            "storage_path": str(artifact.storage_path or "").strip(),
        }

    timeline_map: dict[str, dict[str, Any]] = {}
    for timeline in timelines:
        if isinstance(timeline.data_json, dict):
            timeline_map[str(timeline.timeline_type)] = dict(timeline.data_json)
    return {"artifacts": latest_artifacts, "timelines": timeline_map}


async def build_scorecard(batch_report: dict[str, Any]) -> dict[str, Any]:
    jobs = [dict(item) for item in list(batch_report.get("jobs") or []) if isinstance(item, dict)]
    scorecard_jobs: list[dict[str, Any]] = []

    for job in jobs:
        runtime = await _load_job_runtime(str(job.get("job_id") or ""))
        artifacts = runtime["artifacts"]
        timelines = runtime["timelines"]

        render_outputs = (artifacts.get("render_outputs") or {}).get("data_json") or {}
        render_runtime_diagnostics = (artifacts.get("render_runtime_diagnostics") or {}).get("data_json") or {}
        avatar_plan = (artifacts.get("avatar_commentary_plan") or {}).get("data_json") or {}
        packaging = (artifacts.get("platform_packaging_md") or {}).get("data_json") or {}
        subtitle_quality = (artifacts.get("subtitle_quality_report") or {}).get("data_json") or {}
        variant_bundle = (artifacts.get("variant_timeline_bundle") or {}).get("data_json") or {}
        resolved_variant_bundle = resolve_effective_variant_timeline_bundle(variant_bundle) or {}
        subtitle_timeline_issues = variant_subtitle_timeline_issues(resolved_variant_bundle)
        cut_analysis = (artifacts.get("cut_analysis") or {}).get("data_json") or {}
        editorial = timelines.get("editorial") or {}
        render_plan = timelines.get("render_plan") or {}

        quality_score = _safe_float(job.get("quality_score"))
        overall_video_quality = {
            "score": _round_score(quality_score),
            "grade": _score_to_grade(_round_score(quality_score)),
            "status": str(job.get("status") or ""),
            "summary": f"batch 总体质量分 {quality_score:.1f}" if quality_score is not None else "缺少 batch 总体质量分",
        }

        subtitle_score = _round_score(_safe_float(subtitle_quality.get("score")))
        if subtitle_score is not None and subtitle_timeline_issues:
            subtitle_score = _round_score(max(0.0, subtitle_score - min(35.0, 14.0 + len(subtitle_timeline_issues) * 5.0)))
        subtitle_warning_count = len(subtitle_quality.get("warning_reasons") or []) + len(subtitle_timeline_issues)
        subtitle_quality_section = {
            "score": subtitle_score,
            "grade": _score_to_grade(subtitle_score),
            "status": "warning" if subtitle_timeline_issues else ("done" if subtitle_quality else "missing"),
            "summary": (
                f"字幕质检分 {subtitle_score:.1f}，warning={subtitle_warning_count}，"
                f"blocking={len(subtitle_quality.get('blocking_reasons') or [])}"
            )
            if subtitle_quality
            else "缺少 subtitle_quality_report",
            "timeline_issues": subtitle_timeline_issues,
        }

        version_scores = _build_version_scores(render_outputs)

        packaging_score = _score_platform_package(
            packaging,
            str((artifacts.get("platform_packaging_md") or {}).get("storage_path") or "").strip() or str(job.get("platform_doc") or "").strip(),
        )
        normalized_render_diagnostics = _merge_runtime_render_diagnostics(
            job.get("render_diagnostics") if isinstance(job.get("render_diagnostics"), dict) else None,
            render_runtime_diagnostics if isinstance(render_runtime_diagnostics, dict) else None,
        )
        avatar_score = _score_avatar(
            avatar_plan,
            render_outputs,
            normalized_render_diagnostics,
        )
        tts_score = _score_tts(avatar_plan)
        ai_effects_score = _score_ai_effects(render_plan, render_outputs, variant_bundle)
        subtitle_effects_score = _score_subtitle_effects(render_plan)
        editing_score = _score_editing_with_variant_bundle(job, editorial, render_plan, variant_bundle)
        editing_risk_metrics = _editing_risk_metrics(job, editorial, cut_analysis, variant_bundle)
        viewing_experience = _score_viewing_experience(
            job=job,
            render_outputs=render_outputs,
            subtitle_quality=subtitle_quality,
            render_plan=render_plan,
            variant_bundle=variant_bundle,
            version_scores=version_scores,
            editing_risk_metrics=editing_risk_metrics,
        )
        live_stage_scores = _build_stage_scores(job)

        scorecard_jobs.append(
            {
                "job_id": job.get("job_id"),
                "source_name": job.get("source_name"),
                "output_path": job.get("output_path"),
                "overall_video_quality": overall_video_quality,
                "viewing_experience": viewing_experience,
                "version_scores": version_scores,
                "subtitle_quality": subtitle_quality_section,
                "multi_platform_package": packaging_score,
                "avatar": avatar_score,
                "tts": tts_score,
                "ai_effects": ai_effects_score,
                "subtitle_effects": subtitle_effects_score,
                "editing": editing_score,
                "editing_risk_metrics": editing_risk_metrics,
                "live_stage_scores": live_stage_scores,
            }
        )

    stage_names: list[str] = []
    for job in scorecard_jobs:
        for row in job["live_stage_scores"]:
            stage_name = str(row.get("stage") or "")
            if stage_name and stage_name not in stage_names:
                stage_names.append(stage_name)

    aggregate_stage_scores: list[dict[str, Any]] = []
    for stage_name in stage_names:
        values = [
            _safe_float(row.get("score"))
            for job in scorecard_jobs
            for row in job["live_stage_scores"]
            if row.get("stage") == stage_name
        ]
        score = _mean(values)
        aggregate_stage_scores.append(
            {
                "stage": stage_name,
                "score": score,
                "grade": _score_to_grade(score),
                "job_count": len([item for item in values if item is not None]),
            }
        )

    dimension_names = [
        "overall_video_quality",
        "viewing_experience",
        "subtitle_quality",
        "multi_platform_package",
        "avatar",
        "tts",
        "ai_effects",
        "subtitle_effects",
        "editing",
    ]
    aggregate_dimensions: list[dict[str, Any]] = []
    for name in dimension_names:
        score = _mean([_safe_float((job.get(name) or {}).get("score")) for job in scorecard_jobs])
        aggregate_dimensions.append({"dimension": name, "score": score, "grade": _score_to_grade(score)})

    aggregate_risk_metrics = {
        "high_risk_cut_count": sum(int((job.get("editing_risk_metrics") or {}).get("high_risk_cut_count") or 0) for job in scorecard_jobs),
        "auto_apply_candidate_count": sum(int((job.get("editing_risk_metrics") or {}).get("auto_apply_candidate_count") or 0) for job in scorecard_jobs),
        "manual_confirm_count": sum(int((job.get("editing_risk_metrics") or {}).get("manual_confirm_count") or 0) for job in scorecard_jobs),
        "multimodal_pending_count": sum(int((job.get("editing_risk_metrics") or {}).get("multimodal_pending_count") or 0) for job in scorecard_jobs),
        "llm_reviewed_job_count": sum(1 for job in scorecard_jobs if bool((job.get("editing_risk_metrics") or {}).get("llm_reviewed"))),
        "llm_provider_degraded_job_count": sum(
            1 for job in scorecard_jobs if bool((job.get("editing_risk_metrics") or {}).get("llm_provider_degraded"))
        ),
        "blocking_high_risk_job_count": sum(1 for job in scorecard_jobs if bool((job.get("editing_risk_metrics") or {}).get("blocking_high_risk_cuts"))),
        "blocking_manual_confirm_job_count": sum(
            1 for job in scorecard_jobs if bool((job.get("editing_risk_metrics") or {}).get("blocking_manual_confirm_heavy"))
        ),
        "variant_bundle_job_count": sum(
            1 for job in scorecard_jobs if str((job.get("editing_risk_metrics") or {}).get("source") or "").strip() == "variant_timeline_bundle"
        ),
        "legacy_risk_job_count": sum(
            1
            for job in scorecard_jobs
            if str((job.get("editing_risk_metrics") or {}).get("source") or "").strip() == "legacy_editorial_cut_analysis"
        ),
    }

    return {
        "created_at": batch_report.get("created_at"),
        "batch_report": "",
        "job_count": len(scorecard_jobs),
        "jobs": scorecard_jobs,
        "aggregate_stage_scores": aggregate_stage_scores,
        "aggregate_dimension_scores": aggregate_dimensions,
        "aggregate_risk_metrics": aggregate_risk_metrics,
        "live_readiness": _live_readiness_summary(batch_report),
    }


def render_markdown(scorecard: dict[str, Any], batch_report_path: Path) -> str:
    jobs = [dict(item) for item in list(scorecard.get("jobs") or []) if isinstance(item, dict)]
    pre_render_only = bool(jobs) and all(_job_stopped_before_render(job) for job in jobs)
    live_readiness = scorecard.get("live_readiness") if isinstance(scorecard.get("live_readiness"), dict) else {}
    focus_failures = bool(live_readiness.get("failed_checks")) or any(str(job.get("output_path") or "").strip() == "" for job in jobs)

    def _visible_aggregate_stage_items() -> list[dict[str, Any]]:
        items = [dict(item) for item in list(scorecard.get("aggregate_stage_scores") or []) if isinstance(item, dict)]
        if pre_render_only:
            items = [
                item
                for item in items
                if str(item.get("stage") or "").strip() not in {"render", "final_review", "platform_package"}
            ]
        if focus_failures:
            failure_items = [item for item in items if str(item.get("grade") or "").strip() != "A"]
            if failure_items:
                return failure_items
        return items

    def _render_editing_risk_line(job: dict[str, Any]) -> str:
        payload = job.get("editing_risk_metrics") if isinstance(job.get("editing_risk_metrics"), dict) else {}
        parts = [
            f"source={payload.get('source')}",
            f"high_risk_cut_count={payload.get('high_risk_cut_count')}",
            f"manual_confirm_count={payload.get('manual_confirm_count')}",
            f"multimodal_pending_count={payload.get('multimodal_pending_count')}",
            f"blocking_high_risk_cuts={str(bool(payload.get('blocking_high_risk_cuts'))).lower()}",
            f"blocking_manual_confirm_heavy={str(bool(payload.get('blocking_manual_confirm_heavy'))).lower()}",
        ]
        if bool(payload.get("llm_provider_degraded")):
            parts.append("llm_provider_degraded=true")
        return "- editing_risk_metrics: " + ", ".join(parts)

    def _visible_job_render_sections(job: dict[str, Any], *, job_pre_render_only: bool) -> list[str]:
        if job_pre_render_only:
            return []
        sections = [
            ("multi_platform_package", job.get("multi_platform_package") or {}),
            ("avatar", job.get("avatar") or {}),
            ("tts", job.get("tts") or {}),
            ("ai_effects", job.get("ai_effects") or {}),
        ]
        lines_out: list[str] = []
        for name, payload in sections:
            status = str(payload.get("status") or "").strip().lower()
            if focus_failures and status in {"not_generated", "skipped", "missing"}:
                continue
            lines_out.append(f"- {name}: {payload.get('score')} ({payload.get('grade')}) | {payload.get('summary')}")
        visible_versions = [
            dict(item)
            for item in list(job.get("version_scores") or [])
            if isinstance(item, dict)
            and (not focus_failures or str(item.get("status") or "").strip().lower() not in {"not_generated", "skipped"})
        ]
        if visible_versions:
            lines_out.append("- version_scores:")
            for item in visible_versions:
                lines_out.append(
                    f"  - {item['name']}: {item.get('score')} ({item.get('grade')}) | {' / '.join(item.get('reasons') or [])}"
                )
        return lines_out

    def _visible_live_stage_items(job: dict[str, Any], *, job_pre_render_only: bool) -> list[dict[str, Any]]:
        items = [dict(item) for item in list(job.get("live_stage_scores") or []) if isinstance(item, dict)]
        if job_pre_render_only:
            items = [
                item
                for item in items
                if str(item.get("stage") or "").strip() not in {"render", "final_review", "platform_package"}
            ]
        if focus_failures:
            failure_items = [item for item in items if str(item.get("status") or "").strip().lower() != "pass"]
            if failure_items:
                return failure_items
        return items

    lines = [
        "# Detailed Output Scorecard",
        "",
        f"- batch_report: {batch_report_path}",
        f"- created_at: {scorecard.get('created_at') or ''}",
        f"- job_count: {scorecard.get('job_count') or 0}",
        "",
        "## Aggregate Dimensions",
        "",
    ]
    hidden_dimensions = {"multi_platform_package", "avatar", "tts", "ai_effects"} if pre_render_only else set()
    if focus_failures:
        hidden_dimensions.update({"multi_platform_package", "tts", "ai_effects"})
    for item in list(scorecard.get("aggregate_dimension_scores") or []):
        if str(item.get("dimension") or "").strip() in hidden_dimensions:
            continue
        lines.append(f"- {item['dimension']}: {item.get('score')} ({item.get('grade')})")
    risk_metrics = scorecard.get("aggregate_risk_metrics") if isinstance(scorecard.get("aggregate_risk_metrics"), dict) else {}
    if risk_metrics:
        lines.extend(["", "## Aggregate Risk Metrics", ""])
        risk_lines = [
            f"- high_risk_cut_count: {risk_metrics.get('high_risk_cut_count')}",
            f"- manual_confirm_count: {risk_metrics.get('manual_confirm_count')}",
            f"- multimodal_pending_count: {risk_metrics.get('multimodal_pending_count')}",
            f"- blocking_high_risk_job_count: {risk_metrics.get('blocking_high_risk_job_count')}",
            f"- blocking_manual_confirm_job_count: {risk_metrics.get('blocking_manual_confirm_job_count')}",
        ]
        if int(risk_metrics.get("llm_provider_degraded_job_count") or 0) > 0:
            risk_lines.append(f"- llm_provider_degraded_job_count: {risk_metrics.get('llm_provider_degraded_job_count')}")
        lines.extend(risk_lines)
    if live_readiness:
        lines.extend(
            [
                "",
                "## Live Readiness",
                "",
                f"- gate_passed: {str(bool(live_readiness.get('gate_passed'))).lower()}",
                f"- status: {live_readiness.get('status') or ''}",
                f"- failed_checks: {', '.join(live_readiness.get('failed_checks') or []) or '-'}",
            ]
        )
        render_end_state = (
            live_readiness.get("render_end_state_stability")
            if isinstance(live_readiness.get("render_end_state_stability"), dict)
            else {}
        )
        if render_end_state:
            lines.append(f"- render_failed_jobs: {render_end_state.get('failed_render_job_count') or 0}")
            lines.append(
                "- strategy_validation_blocking_jobs: "
                f"{render_end_state.get('strategy_validation_blocking_job_count') or 0}"
            )
            for label, key in (
                ("strategy_validation_blocking_reasons", "strategy_validation_blocking_reasons"),
                ("strategy_validation_strategy_types", "strategy_validation_strategy_types"),
                ("strategy_validation_review_gates", "strategy_validation_review_gates"),
            ):
                counts = render_end_state.get(key) if isinstance(render_end_state.get(key), dict) else {}
                if counts:
                    rendered = ", ".join(
                        f"{name}={count}"
                        for name, count in sorted(counts.items())
                        if str(name).strip()
                    )
                    lines.append(f"- {label}: {rendered}")
    lines.extend(["", "## Aggregate Stages", ""])
    for item in _visible_aggregate_stage_items():
        lines.append(f"- {item['stage']}: {item.get('score')} ({item.get('grade')})")

    for job in jobs:
        job_pre_render_only = _job_stopped_before_render(job)
        viewing_experience = job.get("viewing_experience") if isinstance(job.get("viewing_experience"), dict) else {}
        lines.extend(
            [
                "",
                f"## {job.get('source_name') or ''}",
                "",
                f"- output_path: {job.get('output_path') or ''}",
                f"- overall_video_quality: {job['overall_video_quality'].get('score')} ({job['overall_video_quality'].get('grade')}) | {job['overall_video_quality'].get('summary')}",
                f"- viewing_experience: {viewing_experience.get('score')} ({viewing_experience.get('grade')}) | {viewing_experience.get('summary')}",
                f"- subtitle_quality: {job['subtitle_quality'].get('score')} ({job['subtitle_quality'].get('grade')}) | {job['subtitle_quality'].get('summary')}",
                f"- subtitle_effects: {job['subtitle_effects'].get('score')} ({job['subtitle_effects'].get('grade')}) | {job['subtitle_effects'].get('summary')}",
                f"- editing: {job['editing'].get('score')} ({job['editing'].get('grade')}) | {job['editing'].get('summary')}",
                _render_editing_risk_line(job),
            ]
        )
        lines.extend(_visible_job_render_sections(job, job_pre_render_only=job_pre_render_only))
        lines.append("- live_stage_scores:")
        for item in _visible_live_stage_items(job, job_pre_render_only=job_pre_render_only):
            lines.append(
                f"  - {item['stage']}: {item.get('score')} ({item.get('grade')}) | {item.get('status')} | {item.get('summary')}"
            )

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    batch_report_path = args.batch_report.resolve()
    batch_report = json.loads(batch_report_path.read_text(encoding="utf-8"))
    scorecard = asyncio.run(build_scorecard(batch_report))
    scorecard["batch_report"] = str(batch_report_path)

    output_json = args.output_json or batch_report_path.with_name("detailed_output_scorecard.json")
    output_md = args.output_md or batch_report_path.with_name("detailed_output_scorecard.md")

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(scorecard, batch_report_path), encoding="utf-8")

    print(
        json.dumps(
            {
                "job_count": scorecard.get("job_count"),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

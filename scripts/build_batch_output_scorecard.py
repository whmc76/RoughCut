from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.db.models import Artifact, Timeline
from roughcut.db.session import get_session_factory
from roughcut.media.variant_timeline_bundle import (
    variant_cut_analysis_summary,
    resolve_effective_variant_timeline_bundle,
    variant_llm_cut_review,
    variant_refine_decision_summary,
    variant_timeline_diagnostics,
)
from roughcut.publication_platform_matrix import (
    normalize_publication_platform_name,
    platform_manual_handoff_only,
    platform_soft_verification_fields,
)
from roughcut.publication_packaging import publication_packaging_entry_publish_ready


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
        score -= min(20.0, 4.0 * len(warning_codes))
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


def _score_avatar(avatar_plan: dict[str, Any], render_outputs: dict[str, Any]) -> dict[str, Any]:
    if not avatar_plan and not render_outputs.get("avatar_result"):
        return {
            "score": None,
            "grade": "N/A",
            "status": "not_enabled",
            "summary": "未启用数字人模块",
        }

    avatar_result = render_outputs.get("avatar_result") if isinstance(render_outputs.get("avatar_result"), dict) else {}
    status = str(avatar_result.get("status") or "").strip().lower()
    integration_mode = str(avatar_result.get("integration_mode") or avatar_plan.get("integration_mode") or "").strip()
    render_status = str(((avatar_plan.get("render_execution") or {}).get("status")) or "").strip().lower()
    segments = list(avatar_plan.get("segments") or []) if isinstance(avatar_plan, dict) else []
    reasons: list[str] = []
    score = 100.0

    if status == "done":
        reasons.append("数字人版本已写入")
    elif status:
        score -= 35.0
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
    editing_accents = render_plan.get("editing_accents") if isinstance(render_plan.get("editing_accents"), dict) else {}
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
    score = 70.0
    if keep_ratio > 0:
        score += 10.0
    if 0.35 <= keep_ratio <= 0.8:
        score += 8.0
    if accepted_cut_count:
        score += min(8.0, accepted_cut_count)
    if llm_reviewed:
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
            f"llm_cut_review={'yes' if llm_reviewed else 'no'}，"
            f"transition_boundaries={len(boundary_indexes)}"
            + (f"，refine_mode={refine_mode}" if refine_mode else "")
            + (f"，refine_candidates={refine_candidate_total}" if refine_candidate_total else "")
            + (f"，llm_error={llm_error}" if llm_error else "")
            + (f"，llm_candidates={llm_candidate_count}" if llm_candidate_count else "")
        ),
    }


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
    transitions = (((render_plan.get("editing_accents") or {}).get("transitions")) or {}) if isinstance(render_plan, dict) else {}
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


def _score_editing_with_variant_bundle(
    job: dict[str, Any],
    editorial: dict[str, Any],
    render_plan: dict[str, Any],
    variant_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved_bundle = resolve_effective_variant_timeline_bundle(variant_bundle) or {}
    if not resolved_bundle:
        return _score_editing(job, editorial, render_plan)

    diagnostics = variant_timeline_diagnostics(resolved_bundle)
    cut_analysis_summary = variant_cut_analysis_summary(resolved_bundle)
    refine_decision_summary = variant_refine_decision_summary(resolved_bundle)
    llm_cut_review = variant_llm_cut_review(resolved_bundle)
    keep_ratio = _safe_float(job.get("keep_ratio")) or 0.0
    accepted_cut_count = int(cut_analysis_summary.get("accepted_cut_count") or 0)
    llm_reviewed = bool(llm_cut_review.get("reviewed"))
    llm_error = str(llm_cut_review.get("error") or "").strip()
    llm_candidate_count = int(llm_cut_review.get("candidate_count") or 0)
    transitions = (((render_plan.get("editing_accents") or {}).get("transitions")) or {}) if isinstance(render_plan, dict) else {}
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
        avatar_plan = (artifacts.get("avatar_commentary_plan") or {}).get("data_json") or {}
        packaging = (artifacts.get("platform_packaging_md") or {}).get("data_json") or {}
        subtitle_quality = (artifacts.get("subtitle_quality_report") or {}).get("data_json") or {}
        variant_bundle = (artifacts.get("variant_timeline_bundle") or {}).get("data_json") or {}
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
        subtitle_quality_section = {
            "score": subtitle_score,
            "grade": _score_to_grade(subtitle_score),
            "status": "done" if subtitle_quality else "missing",
            "summary": (
                f"字幕质检分 {subtitle_score:.1f}，warning={len(subtitle_quality.get('warning_reasons') or [])}，"
                f"blocking={len(subtitle_quality.get('blocking_reasons') or [])}"
            )
            if subtitle_quality
            else "缺少 subtitle_quality_report",
        }

        variant_quality_checks = render_outputs.get("quality_checks") if isinstance(render_outputs.get("quality_checks"), dict) else {}
        version_scores = [
            _summarize_variant_score("packaged", str(render_outputs.get("packaged_mp4") or "").strip(), variant_quality_checks.get("subtitle_sync")),
            _summarize_variant_score("plain", str(render_outputs.get("plain_mp4") or "").strip(), variant_quality_checks.get("plain_subtitle_sync")),
            _summarize_variant_score("avatar", str(render_outputs.get("avatar_mp4") or "").strip(), variant_quality_checks.get("avatar_subtitle_sync")),
            _summarize_variant_score("ai_effect", str(render_outputs.get("ai_effect_mp4") or "").strip(), variant_quality_checks.get("ai_effect_subtitle_sync")),
        ]

        packaging_score = _score_platform_package(
            packaging,
            str((artifacts.get("platform_packaging_md") or {}).get("storage_path") or "").strip() or str(job.get("platform_doc") or "").strip(),
        )
        avatar_score = _score_avatar(avatar_plan, render_outputs)
        tts_score = _score_tts(avatar_plan)
        ai_effects_score = _score_ai_effects(render_plan, render_outputs, variant_bundle)
        subtitle_effects_score = _score_subtitle_effects(render_plan)
        editing_score = _score_editing_with_variant_bundle(job, editorial, render_plan, variant_bundle)
        live_stage_scores = _build_stage_scores(job)

        scorecard_jobs.append(
            {
                "job_id": job.get("job_id"),
                "source_name": job.get("source_name"),
                "output_path": job.get("output_path"),
                "overall_video_quality": overall_video_quality,
                "version_scores": version_scores,
                "subtitle_quality": subtitle_quality_section,
                "multi_platform_package": packaging_score,
                "avatar": avatar_score,
                "tts": tts_score,
                "ai_effects": ai_effects_score,
                "subtitle_effects": subtitle_effects_score,
                "editing": editing_score,
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

    return {
        "created_at": batch_report.get("created_at"),
        "batch_report": "",
        "job_count": len(scorecard_jobs),
        "jobs": scorecard_jobs,
        "aggregate_stage_scores": aggregate_stage_scores,
        "aggregate_dimension_scores": aggregate_dimensions,
    }


def render_markdown(scorecard: dict[str, Any], batch_report_path: Path) -> str:
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
    for item in list(scorecard.get("aggregate_dimension_scores") or []):
        lines.append(f"- {item['dimension']}: {item.get('score')} ({item.get('grade')})")
    lines.extend(["", "## Aggregate Stages", ""])
    for item in list(scorecard.get("aggregate_stage_scores") or []):
        lines.append(f"- {item['stage']}: {item.get('score')} ({item.get('grade')})")

    for job in list(scorecard.get("jobs") or []):
        lines.extend(
            [
                "",
                f"## {job.get('source_name') or ''}",
                "",
                f"- output_path: {job.get('output_path') or ''}",
                f"- overall_video_quality: {job['overall_video_quality'].get('score')} ({job['overall_video_quality'].get('grade')}) | {job['overall_video_quality'].get('summary')}",
                f"- subtitle_quality: {job['subtitle_quality'].get('score')} ({job['subtitle_quality'].get('grade')}) | {job['subtitle_quality'].get('summary')}",
                f"- multi_platform_package: {job['multi_platform_package'].get('score')} ({job['multi_platform_package'].get('grade')}) | {job['multi_platform_package'].get('summary')}",
                f"- avatar: {job['avatar'].get('score')} ({job['avatar'].get('grade')}) | {job['avatar'].get('summary')}",
                f"- tts: {job['tts'].get('score')} ({job['tts'].get('grade')}) | {job['tts'].get('summary')}",
                f"- ai_effects: {job['ai_effects'].get('score')} ({job['ai_effects'].get('grade')}) | {job['ai_effects'].get('summary')}",
                f"- subtitle_effects: {job['subtitle_effects'].get('score')} ({job['subtitle_effects'].get('grade')}) | {job['subtitle_effects'].get('summary')}",
                f"- editing: {job['editing'].get('score')} ({job['editing'].get('grade')}) | {job['editing'].get('summary')}",
                "- version_scores:",
            ]
        )
        for item in list(job.get("version_scores") or []):
            lines.append(
                f"  - {item['name']}: {item.get('score')} ({item.get('grade')}) | {' / '.join(item.get('reasons') or [])}"
            )
        lines.append("- live_stage_scores:")
        for item in list(job.get("live_stage_scores") or []):
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

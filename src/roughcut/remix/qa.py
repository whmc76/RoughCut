from __future__ import annotations

from typing import Any

from roughcut.remix.alignment import TTS_ALIGNMENT_SOURCE
from roughcut.remix.caption_packager import SUPPORTED_CAPTION_STYLE_PROFILES
from roughcut.remix.contracts import GateIssue, GateResult, merge_gate_results
from roughcut.remix.hyperframes import HYPERFRAMES_ENGINE, HYPERFRAMES_PLAN_SCHEMA


def evaluate_episode_report(
    report: dict[str, Any],
    *,
    min_duration_sec: float = 120.0,
    max_duration_sec: float = 180.0,
    min_tts_asr_coverage: float = 0.90,
    min_source_asr_anchors: int = 3,
    min_subtitle_events: int = 35,
    min_theme_banners: int = 3,
    min_keyword_stickers: int = 3,
    min_emphasis_keywords: int = 3,
    min_motion_effects: int = 12,
    min_hyperframes_effects: int = 12,
    min_packaging_audio_cues: int = 6,
    min_review_frames: int = 5,
) -> GateResult:
    checks = [
        _duration_gate(report, min_duration_sec=min_duration_sec, max_duration_sec=max_duration_sec),
        _tts_voice_signature_gate(report),
        _subtitle_source_gate(report),
        _tts_asr_gate(report, min_coverage=min_tts_asr_coverage),
        _source_asr_gate(report, min_anchors=min_source_asr_anchors),
        _original_audio_reference_gate(report),
        _scene_index_gate(report),
        _subtitle_event_gate(report, min_events=min_subtitle_events),
        _subtitle_text_coverage_gate(report),
        _subtitle_timing_alignment_gate(report),
        _caption_packaging_gate(
            report,
            min_theme_banners=min_theme_banners,
            min_keyword_stickers=min_keyword_stickers,
            min_emphasis_keywords=min_emphasis_keywords,
            min_motion_effects=min_motion_effects,
            min_hyperframes_effects=min_hyperframes_effects,
            min_packaging_audio_cues=min_packaging_audio_cues,
        ),
        _review_frames_gate(report, min_review_frames=min_review_frames),
        _media_presence_gate(report),
    ]
    return merge_gate_results(*checks)


def _duration_gate(report: dict[str, Any], *, min_duration_sec: float, max_duration_sec: float) -> GateResult:
    duration = _float(report.get("output_duration_sec"))
    if duration <= 0:
        return GateResult(
            status="fail",
            issues=(
                GateIssue(
                    code="remix_output_duration_invalid",
                    severity="error",
                    message="Final remix duration is invalid.",
                    evidence={"duration_sec": round(duration, 3)},
                ),
            ),
            metrics={"output_duration_sec": round(duration, 3)},
        )
    if min_duration_sec <= duration <= max_duration_sec:
        return GateResult(status="pass", metrics={"output_duration_sec": round(duration, 3)})
    return GateResult(
        status="warn",
        issues=(
            GateIssue(
                code="remix_output_duration_out_of_range",
                severity="warn",
                message="Final remix duration is outside the 2-3 minute target range; preserve the source script unless the user explicitly approves rewriting.",
                evidence={"duration_sec": round(duration, 3), "min_duration_sec": min_duration_sec, "max_duration_sec": max_duration_sec},
            ),
        ),
        metrics={"output_duration_sec": round(duration, 3)},
    )


def _tts_voice_signature_gate(report: dict[str, Any]) -> GateResult:
    metadata_path = str(report.get("tts_request_metadata_path") or "").strip()
    provider = str(report.get("tts_provider") or "").strip()
    mode = str(report.get("tts_mode") or "").strip()
    reference_path = str(report.get("tts_reference_history_path") or "").strip()
    prompt_text = str(report.get("tts_prompt_text") or "")
    voice_signature = str(report.get("tts_voice_signature") or "").strip()
    issues: list[GateIssue] = []
    if not metadata_path:
        issues.append(
            GateIssue(
                code="remix_tts_request_metadata_missing",
                severity="error",
                message="TTS request metadata is required to prove the narration voice identity.",
            )
        )
    if not provider:
        issues.append(
            GateIssue(
                code="remix_tts_provider_missing",
                severity="error",
                message="TTS provider must be recorded in the episode report.",
            )
        )
    if not mode:
        issues.append(
            GateIssue(
                code="remix_tts_mode_missing",
                severity="error",
                message="TTS mode must be recorded in the episode report.",
            )
        )
    if provider == "moss_tts_local":
        if mode not in {"moss_voice_clone", "moss_direct_tts"}:
            issues.append(
                GateIssue(
                    code="remix_tts_moss_mode_invalid",
                    severity="error",
                    message="MOSS TTS remix samples must use voice clone when a reference voice exists, or direct TTS without reference audio.",
                    evidence={"tts_provider": provider, "tts_mode": mode, "expected": "moss_voice_clone|moss_direct_tts"},
                )
            )
        if mode == "moss_voice_clone" and not reference_path:
            issues.append(
                GateIssue(
                    code="remix_tts_reference_missing",
                    severity="error",
                    message="MOSS voice clone samples must record the reference history path.",
                )
            )
        if mode == "moss_voice_clone" and not prompt_text.strip():
            issues.append(
                GateIssue(
                    code="remix_tts_prompt_missing",
                    severity="error",
                    message="MOSS voice clone samples must record the prompt text matching the reference audio.",
                )
            )
    if not voice_signature:
        issues.append(
            GateIssue(
                code="remix_tts_voice_signature_missing",
                severity="error",
                message="TTS voice signature is required to prevent stale or wrong-voice narration cache reuse.",
            )
        )
    return GateResult(
        status="fail" if issues else "pass",
        issues=tuple(issues),
        metrics={
            "tts_request_metadata_path": metadata_path,
            "tts_provider": provider,
            "tts_mode": mode,
            "tts_reference_history_path": reference_path,
            "tts_voice_signature": voice_signature,
        },
    )


def _subtitle_source_gate(report: dict[str, Any]) -> GateResult:
    source = str(report.get("subtitle_alignment_source") or "")
    if source == TTS_ALIGNMENT_SOURCE:
        return GateResult(status="pass", metrics={"subtitle_alignment_source": source})
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_subtitle_alignment_source_invalid",
                severity="error",
                message="Subtitle timestamps must come from Qwen3 TTS-ASR forced alignment.",
                evidence={"subtitle_alignment_source": source, "expected": TTS_ALIGNMENT_SOURCE},
            ),
        ),
        metrics={"subtitle_alignment_source": source},
    )


def _tts_asr_gate(report: dict[str, Any], *, min_coverage: float) -> GateResult:
    coverage = _float(report.get("tts_asr_coverage"))
    status_text = str(report.get("tts_asr_status") or "")
    if status_text == "done" and coverage >= min_coverage:
        return GateResult(status="pass", metrics={"tts_asr_coverage": round(coverage, 4), "tts_asr_status": status_text})
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_tts_asr_quality_gate_failed",
                severity="error",
                message="TTS-ASR status or canonical coverage failed the hard gate.",
                evidence={"tts_asr_status": status_text, "tts_asr_coverage": round(coverage, 4), "min_coverage": min_coverage},
            ),
        ),
        metrics={"tts_asr_coverage": round(coverage, 4), "tts_asr_status": status_text},
    )


def _source_asr_gate(report: dict[str, Any], *, min_anchors: int) -> GateResult:
    anchors = int(_float(report.get("source_asr_anchor_count")))
    status_text = str(report.get("source_asr_status") or "")
    if status_text == "done" and anchors >= min_anchors:
        return GateResult(status="pass", metrics={"source_asr_anchor_count": anchors, "source_asr_status": status_text})
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_source_asr_quality_gate_failed",
                severity="error",
                message="Source-ASR status or usable anchor count failed the hard gate.",
                evidence={"source_asr_status": status_text, "source_asr_anchor_count": anchors, "min_anchors": min_anchors},
            ),
        ),
        metrics={"source_asr_anchor_count": anchors, "source_asr_status": status_text},
    )


def _original_audio_reference_gate(report: dict[str, Any]) -> GateResult:
    intent_count = int(_float(report.get("original_audio_reference_intent_count", 0)))
    insert_count = int(_float(report.get("original_audio_insert_count", 0)))
    insert_total = _float(report.get("original_audio_insert_total_duration_sec", 0.0))
    evidence_path = str(report.get("original_audio_insertions_path") or "").strip()
    intent_source = str(report.get("original_audio_intent_source") or "").strip()
    llm_reviewed = bool(report.get("original_audio_intent_llm_reviewed"))
    mapping_source = str(report.get("original_audio_source_mapping_source") or "").strip()
    mapping_reviewed = bool(report.get("original_audio_source_mapping_llm_reviewed"))
    mapping_path = str(report.get("original_audio_source_mapping_path") or "").strip()
    visual_bridge_count = int(_float(report.get("original_audio_visual_bridge_count", 0)))
    intent_decision = str(report.get("original_audio_intent_decision") or "").strip()
    intent_confidence = _float(report.get("original_audio_intent_confidence", 0.0))
    if intent_source != "llm_script_intent" or not llm_reviewed or intent_decision not in {"insert_original_audio", "no_insert"}:
        return GateResult(
            status="fail",
            issues=(
                GateIssue(
                    code="remix_original_audio_intent_not_reviewed",
                    severity="error",
                    message="Original-audio bridge intent must be reviewed by the LLM script-understanding gate before QA can pass.",
                    evidence={
                        "original_audio_intent_source": intent_source,
                        "original_audio_intent_decision": intent_decision,
                        "original_audio_intent_confidence": round(intent_confidence, 3),
                        "original_audio_intent_llm_reviewed": llm_reviewed,
                        "original_audio_reference_intent_count": intent_count,
                        "original_audio_insert_count": insert_count,
                    },
                ),
            ),
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    if intent_count <= 0:
        return GateResult(
            status="pass",
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    has_required_insertions = insert_count >= intent_count and insert_total >= 1.5 * intent_count and bool(evidence_path)
    if has_required_insertions and (mapping_source != "llm_source_asr_mapping" or not mapping_reviewed or not mapping_path):
        return GateResult(
            status="fail",
            issues=(
                GateIssue(
                    code="remix_original_audio_source_mapping_not_reviewed",
                    severity="error",
                    message="Original-audio bridge source timing must be selected by an LLM over source-video ASR evidence.",
                    evidence={
                        "original_audio_source_mapping_source": mapping_source,
                        "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                        "original_audio_source_mapping_path": mapping_path,
                        "original_audio_insert_count": insert_count,
                    },
                ),
            ),
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_insertions_path": evidence_path,
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    if has_required_insertions and visual_bridge_count < insert_count:
        return GateResult(
            status="fail",
            issues=(
                GateIssue(
                    code="remix_original_audio_visual_bridge_missing",
                    severity="error",
                    message="Every original-audio bridge must replace the montage with the corresponding source-video segment.",
                    evidence={
                        "original_audio_insert_count": insert_count,
                        "original_audio_visual_bridge_count": visual_bridge_count,
                    },
                ),
            ),
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_insertions_path": evidence_path,
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    if has_required_insertions and insert_total < 6.0 * max(1, insert_count):
        return GateResult(
            status="fail",
            issues=(
                GateIssue(
                    code="remix_original_audio_bridge_too_short",
                    severity="error",
                    message="Original-footage context bridges must be long enough to carry a complete small scene, not only a clipped line.",
                    evidence={
                        "original_audio_insert_count": insert_count,
                        "original_audio_insert_total_duration_sec": round(insert_total, 3),
                        "min_total_duration_sec": round(6.0 * max(1, insert_count), 3),
                    },
                ),
            ),
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_insertions_path": evidence_path,
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    if (
        intent_source == "llm_script_intent"
        and llm_reviewed
        and has_required_insertions
    ):
        return GateResult(
            status="pass",
            metrics={
                "original_audio_intent_source": intent_source,
                "original_audio_intent_decision": intent_decision,
                "original_audio_intent_confidence": round(intent_confidence, 3),
                "original_audio_intent_llm_reviewed": llm_reviewed,
                "original_audio_reference_intent_count": intent_count,
                "original_audio_insert_count": insert_count,
                "original_audio_insert_total_duration_sec": round(insert_total, 3),
                "original_audio_insertions_path": evidence_path,
                "original_audio_source_mapping_source": mapping_source,
                "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
                "original_audio_source_mapping_path": mapping_path,
                "original_audio_visual_bridge_count": visual_bridge_count,
            },
        )
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_original_audio_reference_missing",
                severity="error",
                message="LLM-detected source-footage context intent requires an original audio/video context bridge.",
                evidence={
                    "original_audio_reference_intent_count": intent_count,
                    "original_audio_insert_count": insert_count,
                    "original_audio_insert_total_duration_sec": round(insert_total, 3),
                    "original_audio_insertions_path": evidence_path,
                    "original_audio_intent_source": intent_source,
                    "original_audio_intent_decision": intent_decision,
                    "original_audio_intent_confidence": round(intent_confidence, 3),
                    "original_audio_intent_llm_reviewed": llm_reviewed,
                },
            ),
        ),
        metrics={
            "original_audio_intent_source": intent_source,
            "original_audio_intent_decision": intent_decision,
            "original_audio_intent_confidence": round(intent_confidence, 3),
            "original_audio_intent_llm_reviewed": llm_reviewed,
            "original_audio_reference_intent_count": intent_count,
            "original_audio_insert_count": insert_count,
            "original_audio_insert_total_duration_sec": round(insert_total, 3),
            "original_audio_insertions_path": evidence_path,
            "original_audio_source_mapping_source": mapping_source,
            "original_audio_source_mapping_llm_reviewed": mapping_reviewed,
            "original_audio_source_mapping_path": mapping_path,
            "original_audio_visual_bridge_count": visual_bridge_count,
        },
    )


def _subtitle_event_gate(report: dict[str, Any], *, min_events: int) -> GateResult:
    subtitle_events = int(_float(report.get("subtitle_event_count", report.get("dialogue_count", report.get("caption_event_count", 0)))))
    packaging_events = int(_float(report.get("packaging_event_count", 0)))
    total_events = subtitle_events + packaging_events
    if total_events >= min_events:
        return GateResult(status="pass", metrics={"subtitle_event_count": subtitle_events, "packaging_event_count": packaging_events})
    return GateResult(
        status="warn",
        issues=(
            GateIssue(
                code="remix_subtitle_event_count_low",
                severity="warn",
                message="Subtitle/packaging event count is below the target for a 2-3 minute remix.",
                evidence={"total_events": total_events, "min_events": min_events},
            ),
        ),
        metrics={"subtitle_event_count": subtitle_events, "packaging_event_count": packaging_events},
    )


def _subtitle_text_coverage_gate(report: dict[str, Any]) -> GateResult:
    coverage = _float(report.get("subtitle_text_coverage", 0.0))
    if coverage >= 0.999:
        return GateResult(status="pass", metrics={"subtitle_text_coverage": round(coverage, 4)})
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_subtitle_text_incomplete",
                severity="error",
                message="Rendered subtitle text must preserve every visible character from the script chunks.",
                evidence={"subtitle_text_coverage": round(coverage, 4), "min_coverage": 1.0},
            ),
        ),
        metrics={"subtitle_text_coverage": round(coverage, 4)},
    )


def _subtitle_timing_alignment_gate(report: dict[str, Any]) -> GateResult:
    status_text = str(report.get("subtitle_timing_alignment_status") or "").strip()
    unmatched = int(_float(report.get("subtitle_timing_unmatched_count", 0)))
    bad_drift = int(_float(report.get("subtitle_timing_bad_drift_count", 0)))
    max_start = _float(report.get("subtitle_timing_max_abs_start_drift_sec", 0.0))
    max_end = _float(report.get("subtitle_timing_max_abs_end_drift_sec", 0.0))
    audit_path = str(report.get("subtitle_timing_audit_path") or "").strip()
    if status_text == "pass" and unmatched == 0 and bad_drift == 0 and audit_path:
        return GateResult(
            status="pass",
            metrics={
                "subtitle_timing_alignment_status": status_text,
                "subtitle_timing_unmatched_count": unmatched,
                "subtitle_timing_bad_drift_count": bad_drift,
                "subtitle_timing_max_abs_start_drift_sec": round(max_start, 3),
                "subtitle_timing_max_abs_end_drift_sec": round(max_end, 3),
                "subtitle_timing_audit_path": audit_path,
            },
        )
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_subtitle_timing_asr_audit_failed",
                severity="error",
                message="Subtitle cue timestamps must pass ASR-token timing audit.",
                evidence={
                    "subtitle_timing_alignment_status": status_text,
                    "subtitle_timing_unmatched_count": unmatched,
                    "subtitle_timing_bad_drift_count": bad_drift,
                    "subtitle_timing_max_abs_start_drift_sec": round(max_start, 3),
                    "subtitle_timing_max_abs_end_drift_sec": round(max_end, 3),
                    "subtitle_timing_audit_path": audit_path,
                },
            ),
        ),
        metrics={
            "subtitle_timing_alignment_status": status_text,
            "subtitle_timing_unmatched_count": unmatched,
            "subtitle_timing_bad_drift_count": bad_drift,
            "subtitle_timing_max_abs_start_drift_sec": round(max_start, 3),
            "subtitle_timing_max_abs_end_drift_sec": round(max_end, 3),
            "subtitle_timing_audit_path": audit_path,
        },
    )


def _scene_index_gate(report: dict[str, Any]) -> GateResult:
    scene_path = str(report.get("scene_index_path") or "").strip()
    scene_count = int(_float(report.get("scene_count", 0)))
    status_text = str(report.get("scene_index_status") or "").strip()
    if scene_path and scene_count > 0 and status_text == "detected":
        return GateResult(status="pass", metrics={"scene_index_status": status_text, "scene_count": scene_count})
    if scene_path and scene_count > 0:
        return GateResult(
            status="warn",
            issues=(
                GateIssue(
                    code="remix_scene_index_fallback",
                    severity="warn",
                    message="Scene index exists but did not come from real shot-boundary detection.",
                    evidence={"scene_index_status": status_text, "scene_count": scene_count, "scene_index_path": scene_path},
                ),
            ),
            metrics={"scene_index_status": status_text, "scene_count": scene_count},
        )
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_scene_index_missing",
                severity="error",
                message="Scene index is required for script-footage remix clip positioning evidence.",
                evidence={"scene_index_status": status_text, "scene_count": scene_count, "scene_index_path": scene_path},
            ),
        ),
        metrics={"scene_index_status": status_text, "scene_count": scene_count},
    )


def _caption_packaging_gate(
    report: dict[str, Any],
    *,
    min_theme_banners: int,
    min_keyword_stickers: int,
    min_emphasis_keywords: int,
    min_motion_effects: int,
    min_hyperframes_effects: int,
    min_packaging_audio_cues: int,
) -> GateResult:
    theme_banners = int(_float(report.get("theme_banner_count", 0)))
    keyword_stickers = int(_float(report.get("keyword_sticker_count", 0)))
    watermark_events = int(_float(report.get("watermark_event_count", 0)))
    subtitle_events = int(_float(report.get("subtitle_event_count", 0)))
    packaging_events = int(_float(report.get("packaging_event_count", 0)))
    total_events = subtitle_events + packaging_events
    emphasis_keywords = int(_float(report.get("emphasis_keyword_count", 0)))
    motion_effects = int(_float(report.get("motion_effect_count", 0)))
    animated_subtitles = int(_float(report.get("animated_subtitle_event_count", 0)))
    animated_packaging = int(_float(report.get("animated_packaging_event_count", 0)))
    audio_cues = int(_float(report.get("packaging_audio_cue_count", report.get("audio_cue_count", 0))))
    max_lines = int(_float(report.get("max_subtitle_lines_per_event", 0)))
    max_line_chars = int(_float(report.get("max_subtitle_line_chars", 0)))
    style_profile = str(report.get("subtitle_style_profile") or "").strip()
    packaging_framework = str(report.get("packaging_framework") or "").strip()
    hyperframes_enabled = bool(report.get("hyperframes_enabled"))
    hyperframes_plan_schema = str(report.get("hyperframes_plan_schema") or "").strip()
    hyperframes_element_count = int(_float(report.get("hyperframes_element_count", 0)))
    hyperframes_effect_count = int(_float(report.get("hyperframes_effect_count", 0)))
    caption_path = str(report.get("caption_package_path") or "").strip()
    semantic_source = str(report.get("semantic_packaging_source") or "").strip()
    semantic_llm_reviewed = bool(report.get("semantic_packaging_llm_reviewed"))
    source_bridge_count = int(_float(report.get("source_bridge_count", 0)))
    original_audio_insert_count = int(_float(report.get("original_audio_insert_count", 0)))
    issues: list[GateIssue] = []
    if not caption_path:
        issues.append(
            GateIssue(
                code="remix_caption_package_missing",
                severity="error",
                message="Caption package metadata is required for reusable subtitle packaging evidence.",
            )
        )
    if theme_banners < min_theme_banners:
        issues.append(
            GateIssue(
                code="remix_theme_banner_count_low",
                severity="error",
                message="Caption packaging must include enough theme banner events.",
                evidence={"theme_banner_count": theme_banners, "min_theme_banners": min_theme_banners},
            )
        )
    if keyword_stickers < min_keyword_stickers:
        issues.append(
            GateIssue(
                code="remix_keyword_sticker_count_low",
                severity="error",
                message="Caption packaging must include enough keyword sticker events.",
                evidence={"keyword_sticker_count": keyword_stickers, "min_keyword_stickers": min_keyword_stickers},
            )
        )
    if watermark_events < 1:
        issues.append(
            GateIssue(
                code="remix_watermark_missing",
                severity="error",
                message="Caption packaging must include a persistent self watermark.",
                evidence={"watermark_event_count": watermark_events},
            )
        )
    if style_profile not in SUPPORTED_CAPTION_STYLE_PROFILES:
        issues.append(
            GateIssue(
                code="remix_caption_style_profile_invalid",
                severity="error",
                message="Caption packaging must use a supported creator-bound subtitle style profile.",
                evidence={
                    "subtitle_style_profile": style_profile,
                    "expected": sorted(SUPPORTED_CAPTION_STYLE_PROFILES),
                },
            )
        )
    if packaging_framework != HYPERFRAMES_ENGINE or not hyperframes_enabled or hyperframes_plan_schema != HYPERFRAMES_PLAN_SCHEMA:
        issues.append(
            GateIssue(
                code="remix_hyperframes_plan_missing",
                severity="error",
                message="Caption and packaging effects must be based on a Hyperframes packaging plan.",
                evidence={
                    "packaging_framework": packaging_framework,
                    "hyperframes_enabled": hyperframes_enabled,
                    "hyperframes_plan_schema": hyperframes_plan_schema,
                    "expected_framework": HYPERFRAMES_ENGINE,
                    "expected_schema": HYPERFRAMES_PLAN_SCHEMA,
                },
            )
        )
    if semantic_source != "llm_script_packaging" or not semantic_llm_reviewed:
        issues.append(
            GateIssue(
                code="remix_semantic_packaging_not_llm_reviewed",
                severity="error",
                message="Caption packaging decisions must come from an LLM-reviewed script semantic packaging plan.",
                evidence={
                    "semantic_packaging_source": semantic_source,
                    "semantic_packaging_llm_reviewed": semantic_llm_reviewed,
                    "expected_source": "llm_script_packaging",
                },
            )
        )
    if hyperframes_element_count < total_events or hyperframes_effect_count < min_hyperframes_effects:
        issues.append(
            GateIssue(
                code="remix_hyperframes_effects_low",
                severity="error",
                message="Hyperframes plan must cover subtitle/packaging events and include enough motion/effect keyframes.",
                evidence={
                    "hyperframes_element_count": hyperframes_element_count,
                    "required_element_count": total_events,
                    "hyperframes_effect_count": hyperframes_effect_count,
                    "min_hyperframes_effects": min_hyperframes_effects,
                },
            )
        )
    if max_lines > 2 or max_lines <= 0:
        issues.append(
            GateIssue(
                code="remix_subtitle_lines_out_of_bounds",
                severity="error",
                message="Caption subtitles must be split into at most two visible lines per event.",
                evidence={"max_subtitle_lines_per_event": max_lines, "max_allowed": 2},
            )
        )
    if max_line_chars > 18 or max_line_chars <= 0:
        issues.append(
            GateIssue(
                code="remix_subtitle_line_width_out_of_bounds",
                severity="error",
                message="Caption subtitles must keep each visible line within the readable width budget.",
                evidence={"max_subtitle_line_chars": max_line_chars, "max_allowed": 18},
            )
        )
    if emphasis_keywords < min_emphasis_keywords:
        issues.append(
            GateIssue(
                code="remix_emphasis_keyword_count_low",
                severity="error",
                message="Caption packaging must include enough inline emphasis keyword effects.",
                evidence={"emphasis_keyword_count": emphasis_keywords, "min_emphasis_keywords": min_emphasis_keywords},
            )
        )
    if motion_effects < min_motion_effects or animated_subtitles <= 0 or animated_packaging < min_theme_banners + min_keyword_stickers:
        issues.append(
            GateIssue(
                code="remix_caption_motion_effects_low",
                severity="error",
                message="Caption packaging must include visible motion effects for subtitles and packaging overlays.",
                evidence={
                    "motion_effect_count": motion_effects,
                    "min_motion_effects": min_motion_effects,
                    "animated_subtitle_event_count": animated_subtitles,
                    "animated_packaging_event_count": animated_packaging,
                },
            )
        )
    if audio_cues < min_packaging_audio_cues:
        issues.append(
            GateIssue(
                code="remix_packaging_audio_cues_low",
                severity="error",
                message="Jianying-style packaging must include audible cue sounds for key overlays.",
                evidence={
                    "packaging_audio_cue_count": audio_cues,
                    "min_packaging_audio_cues": min_packaging_audio_cues,
                },
            )
        )
    if original_audio_insert_count > 0 and source_bridge_count < original_audio_insert_count:
        issues.append(
            GateIssue(
                code="remix_original_audio_bridge_visual_missing",
                severity="error",
                message="Every inserted original-audio bridge must have visible caption/Hyperframes evidence.",
                evidence={
                    "original_audio_insert_count": original_audio_insert_count,
                    "source_bridge_count": source_bridge_count,
                },
            )
        )
    return GateResult(
        status="fail" if issues else "pass",
        issues=tuple(issues),
        metrics={
            "caption_package_path": caption_path,
            "subtitle_style_profile": style_profile,
            "packaging_framework": packaging_framework,
            "hyperframes_enabled": hyperframes_enabled,
            "hyperframes_plan_schema": hyperframes_plan_schema,
            "semantic_packaging_source": semantic_source,
            "semantic_packaging_llm_reviewed": semantic_llm_reviewed,
            "hyperframes_element_count": hyperframes_element_count,
            "hyperframes_effect_count": hyperframes_effect_count,
            "max_subtitle_lines_per_event": max_lines,
            "max_subtitle_line_chars": max_line_chars,
            "theme_banner_count": theme_banners,
            "keyword_sticker_count": keyword_stickers,
            "watermark_event_count": watermark_events,
            "emphasis_keyword_count": emphasis_keywords,
            "motion_effect_count": motion_effects,
            "animated_subtitle_event_count": animated_subtitles,
            "animated_packaging_event_count": animated_packaging,
            "packaging_audio_cue_count": audio_cues,
            "source_bridge_count": source_bridge_count,
        },
    )


def _review_frames_gate(report: dict[str, Any], *, min_review_frames: int) -> GateResult:
    review_count = int(_float(report.get("review_frame_count", 0)))
    manifest_path = str(report.get("review_frames_manifest_path") or "").strip()
    if manifest_path and review_count >= min_review_frames:
        return GateResult(
            status="pass",
            metrics={"review_frames_manifest_path": manifest_path, "review_frame_count": review_count},
        )
    return GateResult(
        status="fail",
        issues=(
            GateIssue(
                code="remix_review_frames_missing",
                severity="error",
                message="Review frames are required to verify crop, logo removal, and subtitle packaging visually.",
                evidence={
                    "review_frames_manifest_path": manifest_path,
                    "review_frame_count": review_count,
                    "min_review_frames": min_review_frames,
                },
            ),
        ),
        metrics={"review_frames_manifest_path": manifest_path, "review_frame_count": review_count},
    )


def _media_presence_gate(report: dict[str, Any]) -> GateResult:
    issues: list[GateIssue] = []
    for field in ("output_path", "narration_path", "subtitle_path"):
        if not str(report.get(field) or "").strip():
            issues.append(
                GateIssue(
                    code=f"remix_missing_{field}",
                    severity="error",
                    message=f"Required report field `{field}` is missing.",
                )
            )
    return GateResult(status="fail" if issues else "pass", issues=tuple(issues))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

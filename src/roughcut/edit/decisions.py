from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from roughcut.edit.low_signal_text import (
    PUNCTUATION_PATTERN,
    compact_subtitle_text as _compact_subtitle_text,
    has_normal_language_signal as _has_normal_language_signal,
    has_visual_showcase_signal as _has_visual_showcase_signal,
    is_low_signal_subtitle_text as _is_low_signal_subtitle_text,
    is_nonsemantic_repetition_text as _is_nonsemantic_repetition_text,
    looks_like_noise_subtitle as _looks_like_noise_subtitle,
    subtitle_signal_score as _subtitle_signal_score,
)
from roughcut.edit.local_highlight_candidates import build_local_highlight_candidates
from roughcut.edit.local_multi_material_candidates import build_local_multi_material_candidates
from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill
from roughcut.edit.strategy_profile import build_strategy_profile_payload, infer_strategy_type
from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_rule_text,
    subtitle_semantic_preview_text,
)
from roughcut.edit.timeline_contract import audit_edit_decision_contract
from roughcut.media.scene import SceneBoundary
from roughcut.media.silence import SilenceSegment
from roughcut.media.subtitle_spans import (
    build_subtitle_span_alignment,
    drop_redundant_synthetic_word_payloads,
    subtitle_display_units,
)
from roughcut.review.video_understanding import normalize_video_understanding_segment_hints


FILLER_WORDS = [
    "那个", "这个", "嗯", "啊", "呃", "就是说", "然后就", "对吧对吧",
    "就是那个", "这个嘛", "我觉得那个",
]

FILLER_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in sorted(FILLER_WORDS, key=len, reverse=True)) + r")",
    re.UNICODE,
)
HESITATION_FILLER_WORDS = ("呃呃", "嗯嗯", "嗯", "呃", "额")
_SILENCE_WORD_BOUNDARY_GUARD_SEC = 0.08
_RESTART_CUE_TERMS = (
    "滚",
    "滚开",
    "别吵",
    "别说话",
    "别闹",
    "走开",
    "别打扰",
    "不要打扰",
    "重来",
    "重讲",
    "重新讲",
    "重新说",
    "重说",
    "再来一遍",
    "再讲一遍",
    "再说一遍",
    "说错了",
    "讲错了",
    "口误",
    "嘴瓢",
    "卡壳",
    "前面不算",
    "刚才不对",
)
_RESTART_SHORT_CUES = frozenset({"滚", "滚开", "别吵", "别闹", "走开", "重来", "重讲", "重说", "重新", "再来", "再说", "口误", "说错", "讲错"})
_RESTART_PREFIX_TERMS = (
    "滚",
    "滚开",
    "别吵",
    "别说话",
    "别闹",
    "走开",
    "别打扰",
    "不要打扰",
    "等一下",
    "等会",
    "等会儿",
    "不好意思",
    "前面不算",
    "刚才不对",
    "口误",
    "口误了",
    "说错了",
    "讲错了",
    "重来",
    "重讲",
    "重说",
    "重新讲",
    "重新说",
    "再来一遍",
    "再讲一遍",
    "再说一遍",
)
_ROLLBACK_INSTRUCTION_TERMS = (
    "把刚才这段剪掉",
    "刚才这段剪掉",
    "刚才那段剪掉",
    "把前面这段剪掉",
    "前面这段剪掉",
    "刚才这段删掉",
    "前面这段删掉",
    "刚才这段不要",
    "前面这段不要",
    "刚才不要",
    "前面不要",
    "刚才不算",
    "前面不算",
    "这段不算",
    "这段剪掉",
    "这段删掉",
    "这条不要",
    "这一条不要",
    "这遍不要",
    "这一遍不要",
)
_ROLLBACK_REFERENCE_TERMS = ("刚才", "刚刚", "前面", "之前", "这段", "那段", "上一段", "这条", "这一条", "这遍", "这一遍")
_ROLLBACK_DELETE_TERMS = ("剪掉", "删掉", "不要", "不算", "作废")
_ROLLBACK_ASR_VARIANT_RE = re.compile(r"(?:本来)?就是(?:减|剪)(?:6|六)(?:啊|呀|吧|所以|$)", re.UNICODE)
_ROLLBACK_LOOKBACK_MAX_SEC = 24.0
_ROLLBACK_LOOKBACK_MAX_GAP_SEC = 3.2
_ROLLBACK_MIN_CUT_SEC = 1.5
_MULTIMODAL_POSITIVE_ROLES = frozenset({"hook", "cta", "comparison", "detail_showcase", "demo", "body"})
_MULTIMODAL_NEGATIVE_ROLES = frozenset({"retake", "junk"})
_TERMINAL_PUNCTUATION_CHARS = "。！？!?…~"
_INCOMPLETE_TAIL_SUFFIXES = (
    "的",
    "了",
    "是",
    "在",
    "把",
    "跟",
    "和",
    "给",
    "就",
    "又",
    "还",
    "更",
    "最",
    "很",
    "再",
    "并",
    "但",
    "而",
    "如果",
    "因为",
    "所以",
    "然后",
    "而且",
    "或者",
    "以及",
    "就是",
)
_CONTINUATION_HEAD_PREFIXES = (
    "然后",
    "所以",
    "但是",
    "不过",
    "而且",
    "以及",
    "另外",
    "再",
    "那",
    "就是",
    "其实",
    "因为",
)
_MICRO_KEEP_NO_SUBTITLE_MAX_SEC = 0.75
_MICRO_KEEP_BRIDGE_MAX_SEC = 0.6
_KEEP_TRIM_PAD_BEFORE_SEC = 0.18
_KEEP_TRIM_PAD_AFTER_SEC = 0.24
_KEEP_TRIM_PAD_BEFORE_STRONG_SEC = 0.24
_KEEP_TRIM_PAD_AFTER_STRONG_SEC = 0.32
_KEEP_EDGE_TRIM_MAX_SEC = 0.35
_KEEP_EDGE_TRIM_MAX_STRONG_SEC = 0.55
_STRONG_SUBTITLE_SIGNAL_SCORE = 2.0
_SHORT_KEEP_AUDIO_SAFE_SEC = 1.4
_SHORT_SUBTITLE_SPAN_SEC = 0.7
_SHORT_SUBTITLE_PAD_BEFORE_BONUS_SEC = 0.06
_SHORT_SUBTITLE_PAD_AFTER_BONUS_SEC = 0.08
_KEEP_CONTINUATION_PAD_BEFORE_BONUS_SEC = 0.08
_KEEP_INCOMPLETE_PAD_AFTER_BONUS_SEC = 0.18
_RETAKE_MAX_GAP_SEC = 4.5
_RETAKE_MAX_WINDOW_ITEMS = 4
_RETAKE_MIN_PREFIX_LEN = 4
_RETAKE_MAX_FRAGMENT_CHARS = 24
_MAX_REPEATED_SPEECH_COPY_GAP_SEC = 0.45
_SHOWCASE_CONTEXT_MAX_GAP_SEC = 0.55
_SHOWCASE_CONTEXT_APPRECIATION_MAX_GAP_SEC = 1.2
_VISUAL_SHOWCASE_GAP_MIN_SEC = 0.45
_VISUAL_SHOWCASE_GAP_MAX_SEC = 8.0
_VISUAL_SHOWCASE_LONG_GAP_MIN_SEC = 3.2
_LONG_INVALID_NO_DIALOGUE_MIN_SEC = 1.2
_SILENCE_CUT_SCORE_THRESHOLD = 0.32
_SILENCE_DURATION_SCORE_BASE = 0.22
_SILENCE_DURATION_SCORE_PER_SEC = 0.35
_SILENCE_DURATION_SCORE_MAX = 0.55
_SUBTITLE_TEXT_SILENCE_PROTECTION_MAX_SEC = 18.0
_SUBTITLE_TEXT_SILENCE_PROTECTION_MIN_COVERAGE = 0.82
_SYNTHETIC_WORD_ALIGNMENT_SOURCES = {
    "canonical_realign",
    "synthetic",
    "segment_only",
    "provider_missing",
    "roughcut_synthesized",
}
_SCENE_SNAP_TOLERANCE_SEC = 0.24
_MIN_CUT_DURATION_SEC = 0.08
_MIN_PARTIAL_SUBTITLE_CUT_DURATION_SEC = 0.18
_TRANSCRIPT_EVIDENCE_WINDOW_SEC = 0.45
_TRIM_INTENSITY_PROFILES = {
    "tight": {
        "pad_multiplier": 0.72,
        "max_edge_trim_multiplier": 1.15,
        "micro_keep_no_subtitle_max_sec": 0.92,
        "micro_keep_bridge_max_sec": 0.75,
        "short_keep_audio_safe_sec": 1.15,
    },
    "balanced": {
        "pad_multiplier": 1.0,
        "max_edge_trim_multiplier": 1.0,
        "micro_keep_no_subtitle_max_sec": _MICRO_KEEP_NO_SUBTITLE_MAX_SEC,
        "micro_keep_bridge_max_sec": _MICRO_KEEP_BRIDGE_MAX_SEC,
        "short_keep_audio_safe_sec": _SHORT_KEEP_AUDIO_SAFE_SEC,
    },
    "preserve": {
        "pad_multiplier": 1.38,
        "max_edge_trim_multiplier": 0.72,
        "micro_keep_no_subtitle_max_sec": 0.42,
        "micro_keep_bridge_max_sec": 0.34,
        "short_keep_audio_safe_sec": 1.95,
    },
}

_CREATIVE_PREFERENCE_LABELS = {
    "comparison_focus": "突出差异对比",
    "detail_focus": "突出细节做工",
    "closeup_focus": "突出近景特写",
    "practical_demo": "突出上手实测",
    "workflow_breakdown": "突出流程拆解",
    "fast_paced": "节奏偏快",
    "conclusion_first": "先给结论",
}


@dataclass
class EditSegment:
    start: float
    end: float
    type: str
    reason: str = ""


@dataclass
class CutCandidate:
    start: float
    end: float
    reason: str
    score: float = 1.0
    hard: bool = False
    signals: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "reason": self.reason,
            "score": round(self.score, 4),
            "hard": self.hard,
            "signals": list(self.signals),
        }
        if self.evidence:
            payload["evidence"] = dict(self.evidence)
        return payload


@dataclass
class EditRangeEvidence:
    start: float
    end: float
    duration_sec: float
    subtitle_count: int = 0
    transcript_count: int = 0
    transcript_coverage: float = 0.0
    scene_boundary_count: int = 0
    section_role: str = ""
    broll_allowed: bool = False
    visual_showcase_score: float = 0.0
    language_score: float = 0.0
    retake_score: float = 0.0
    protection_score: float = 0.0
    removal_score: float = 0.0
    multimodal_role: str = ""
    multimodal_keep_priority: str = ""
    multimodal_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    previous_text: str = ""
    next_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration_sec": round(self.duration_sec, 3),
            "subtitle_count": self.subtitle_count,
            "transcript_count": self.transcript_count,
            "transcript_coverage": round(self.transcript_coverage, 3),
            "scene_boundary_count": self.scene_boundary_count,
            "section_role": self.section_role,
            "broll_allowed": self.broll_allowed,
            "visual_showcase_score": round(self.visual_showcase_score, 3),
            "language_score": round(self.language_score, 3),
            "retake_score": round(self.retake_score, 3),
            "protection_score": round(self.protection_score, 3),
            "removal_score": round(self.removal_score, 3),
            "multimodal_role": self.multimodal_role,
            "multimodal_keep_priority": self.multimodal_keep_priority,
            "multimodal_score": round(self.multimodal_score, 3),
            "tags": list(dict.fromkeys(self.tags)),
        }
        if self.previous_text:
            payload["previous_text"] = self.previous_text[:48]
        if self.next_text:
            payload["next_text"] = self.next_text[:48]
        return payload


@dataclass
class EditDecision:
    source: str
    segments: list[EditSegment] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "version": 2,
            "source": self.source,
            "segments": [
                {"start": s.start, "end": s.end, "type": s.type, "reason": s.reason}
                for s in self.segments
            ],
        }
        if self.analysis:
            payload["analysis"] = self.analysis
        return payload


def build_edit_decision(
    source_path: str,
    duration: float,
    silence_segments: list[SilenceSegment],
    subtitle_items: list[dict] | None = None,
    content_profile: dict | None = None,
    *,
    transcript_segments: list[dict] | None = None,
    scene_boundaries: list[SceneBoundary | dict[str, Any] | float] | None = None,
    editing_skill: dict[str, Any] | None = None,
    timeline_analysis: dict[str, Any] | None = None,
    min_silence_to_cut: float = 0.5,
    cut_fillers: bool = True,
) -> EditDecision:
    resolved_skill = editing_skill or resolve_editing_skill(
        workflow_template=str((content_profile or {}).get("workflow_template") or ""),
        content_profile=content_profile,
    )
    resolved_skill = apply_review_focus_overrides(
        resolved_skill,
        review_focus=(editing_skill or {}).get("review_focus"),
    )
    resolved_strategy_profile = build_strategy_profile_payload(
        strategy_type=infer_strategy_type(
            workflow_template=str((content_profile or {}).get("workflow_template") or ""),
            content_profile=content_profile,
        )
    )
    effective_min_silence_to_cut = max(0.12, float(resolved_skill.get("silence_floor_sec", min_silence_to_cut) or min_silence_to_cut))
    normalized_subtitles = _normalize_subtitle_items(subtitle_items or [])
    normalized_transcript = _normalize_transcript_segments(transcript_segments or [])
    enriched_subtitles = _enrich_subtitle_items_with_transcript_evidence(
        normalized_subtitles,
        normalized_transcript,
    )
    scene_points = _normalize_scene_points(scene_boundaries or [])

    candidates: list[CutCandidate] = []
    timeline_analysis = (
        dict(timeline_analysis)
        if isinstance(timeline_analysis, dict)
        else infer_timeline_analysis(
            enriched_subtitles,
            content_profile=content_profile,
            duration=duration,
            editing_skill=resolved_skill,
        )
    )
    candidates.extend(
        _build_silence_cut_candidates(
            silence_segments,
            subtitle_items=enriched_subtitles,
            transcript_segments=normalized_transcript,
            content_profile=content_profile,
            scene_points=scene_points,
            min_silence_to_cut=effective_min_silence_to_cut,
            editing_skill=resolved_skill,
            timeline_analysis=timeline_analysis,
        )
    )
    manual_editor_rule_candidates: list[CutCandidate] = []
    if cut_fillers and enriched_subtitles:
        manual_editor_rule_candidates.extend(
            _build_subtitle_cut_candidates(
                enriched_subtitles,
                content_profile=content_profile,
                transcript_segments=normalized_transcript,
            )
        )
        manual_editor_rule_candidates.extend(
            _build_hard_cut_candidates(
                [
                    *_collect_restart_retake_cuts(enriched_subtitles, content_profile=content_profile),
                    *_collect_restart_cue_cuts(enriched_subtitles, content_profile=content_profile),
                ]
            )
        )
        manual_editor_rule_candidates.extend(
            _collect_rollback_instruction_cuts(enriched_subtitles, content_profile=content_profile)
        )

    merged_cuts = _merge_cut_intervals(
        [(candidate.start, candidate.end, candidate.reason) for candidate in candidates]
    )
    base_segments = _build_segments_from_cuts(duration=duration, merged_cuts=merged_cuts)
    if subtitle_items is not None:
        pacing_rule_preview = _refine_segments_for_pacing(
            base_segments,
            subtitle_items=enriched_subtitles,
            transcript_segments=normalized_transcript,
            content_profile=content_profile,
            duration=duration,
            timeline_analysis=timeline_analysis,
            scene_points=scene_points,
        )
        manual_editor_rule_candidates.extend(
            _collect_pacing_rule_candidates(
                base_segments,
                pacing_rule_preview,
            )
        )
    segments = _merge_adjacent_segments(base_segments)
    keep_energy_segments = _build_keep_energy_segments_analysis(
        segments,
        subtitle_items=enriched_subtitles,
        timeline_analysis=timeline_analysis,
        content_profile=content_profile,
    )
    accepted_cuts = _annotate_cut_candidates_with_keep_energy(
        candidates,
        keep_energy_segments=keep_energy_segments,
    )
    source_timeline_contract = build_source_timeline_contract_analysis(
        duration=duration,
        edit_segments=segments,
        transcript_segments=normalized_transcript,
        subtitle_items=enriched_subtitles,
        silence_segments=silence_segments,
    )
    return EditDecision(
        source=source_path,
        segments=segments,
        analysis={
            "decision_methodology": {
                "version": "multisignal_v1",
                "signals": [
                    "vad_silence",
                    "subtitle_semantics",
                    "transcript_overlap",
                    "scene_boundaries",
                    "section_role",
                    "manual_editor_rule_candidates",
                ],
                "principle": "auto-apply only VAD-backed source cuts; text and pacing rules are marked for the manual full-transcript stage",
            },
            "candidate_count": len(candidates),
            "scene_boundary_count": len(scene_points),
            "transcript_segment_count": len(normalized_transcript),
            "effective_min_silence_to_cut": round(effective_min_silence_to_cut, 3),
            "strategy_type": str(resolved_strategy_profile.get("strategy_type") or ""),
            "strategy_profile": resolved_strategy_profile,
            "silence_segments": [
                {
                    "start": round(max(0.0, silence.start), 3),
                    "end": round(max(0.0, silence.end), 3),
                    "duration_sec": round(max(0.0, silence.end - silence.start), 3),
                    "source": "audio_vad",
                }
                for silence in silence_segments
                if silence.end > silence.start + 0.08
            ],
            "review_focus": str(resolved_skill.get("review_focus") or ""),
            "accepted_cuts": accepted_cuts,
            "manual_editor_rule_candidates": [
                {
                    **candidate.to_dict(),
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                }
                for candidate in manual_editor_rule_candidates
            ],
            "manual_editor_rule_candidate_count": len(manual_editor_rule_candidates),
            "cut_evidence_summary": _summarize_cut_evidence(accepted_cuts),
            "keep_energy_segments": keep_energy_segments,
            "keep_energy_summary": _summarize_keep_energy_segments(keep_energy_segments),
            "source_timeline_contract": source_timeline_contract,
            "automatic_gate": build_automatic_gate_analysis(source_timeline_contract),
            **timeline_analysis,
        },
    )


def build_source_timeline_contract_analysis(
    *,
    duration: float,
    edit_segments: list[EditSegment],
    transcript_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    silence_segments: list[SilenceSegment],
) -> dict[str, Any]:
    return audit_edit_decision_contract(
        duration=duration,
        edit_segments=edit_segments,
        transcript_segments=transcript_segments,
        subtitle_items=subtitle_items,
        silence_segments=silence_segments,
    )


def build_automatic_gate_analysis(source_timeline_contract: dict[str, Any]) -> dict[str, Any]:
    blocking = bool(source_timeline_contract.get("blocking"))
    return {
        "blocking": blocking,
        "blocking_reasons": ["source_timeline_contract_blocking"] if blocking else [],
    }


def refresh_source_timeline_contract_analysis(
    decision: EditDecision,
    *,
    duration: float,
    transcript_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    silence_segments: list[SilenceSegment],
) -> dict[str, Any]:
    if not hasattr(decision, "analysis") or not isinstance(getattr(decision, "analysis", None), dict):
        decision.analysis = {}
    source_timeline_contract = build_source_timeline_contract_analysis(
        duration=duration,
        edit_segments=decision.segments,
        transcript_segments=transcript_segments,
        subtitle_items=subtitle_items,
        silence_segments=silence_segments,
    )
    decision.analysis["source_timeline_contract"] = source_timeline_contract
    decision.analysis["automatic_gate"] = build_automatic_gate_analysis(source_timeline_contract)
    return source_timeline_contract


def infer_timeline_analysis(
    subtitle_items: list[dict[str, Any]] | None,
    *,
    content_profile: dict | None = None,
    duration: float | None = None,
    editing_skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_subtitle_items(list(subtitle_items or []))
    resolved_skill = editing_skill or resolve_editing_skill(
        workflow_template=str((content_profile or {}).get("workflow_template") or ""),
        content_profile=content_profile,
    )
    resolved_skill = apply_review_focus_overrides(
        resolved_skill,
        review_focus=(editing_skill or {}).get("review_focus"),
    )
    resolved_strategy_profile = build_strategy_profile_payload(
        strategy_type=infer_strategy_type(
            workflow_template=str((content_profile or {}).get("workflow_template") or ""),
            content_profile=content_profile,
        )
    )
    total_duration = float(duration or 0.0)
    if total_duration <= 0.0 and normalized:
        total_duration = max(float(item.get("end_time", 0.0) or 0.0) for item in normalized)
    if not normalized:
        return {
            "hook_end_sec": 0.0,
            "cta_start_sec": None,
            "semantic_sections": [],
            "section_directives": [],
            "section_actions": [],
            "editing_skill": resolved_skill,
            "strategy_type": str(resolved_strategy_profile.get("strategy_type") or ""),
            "strategy_profile": resolved_strategy_profile,
            "emphasis_candidates": [],
            "highlight_candidates": [],
            "multi_material_candidates": [],
        }

    annotated = []
    for index, item in enumerate(normalized):
        text = _semantic_subtitle_text(item)
        role = _classify_semantic_role(
            item,
            index=index,
            total_items=len(normalized),
            total_duration=total_duration,
        )
        annotated.append(
            {
                "index": index,
                "start_time": float(item.get("start_time", 0.0) or 0.0),
                "end_time": float(item.get("end_time", 0.0) or 0.0),
                "text": text,
                "role": role,
                "signal": round(_subtitle_signal_score(text, content_profile=content_profile), 3),
            }
        )

    sections = _merge_semantic_sections(annotated)
    multimodal_segment_hints = _build_multimodal_segment_hints(
        content_profile=content_profile,
        duration=total_duration,
    )
    hook_end_sec = 0.0
    for section in sections:
        if section["role"] == "hook":
            hook_end_sec = max(hook_end_sec, float(section["end_sec"]))
    if hook_end_sec <= 0.0:
        hook_end_sec = min(total_duration, float(normalized[min(1, len(normalized) - 1)].get("end_time", 0.0) or 0.0))

    cta_candidates = [section for section in sections if section["role"] == "cta"]
    cta_start_sec = float(cta_candidates[0]["start_sec"]) if cta_candidates else None

    emphasis_candidates = _build_emphasis_candidates(annotated)
    highlight_candidates = build_local_highlight_candidates(
        annotated_items=annotated,
        sections=sections,
        emphasis_candidates=emphasis_candidates,
        multimodal_segment_hints=multimodal_segment_hints,
        content_profile=content_profile,
        editing_skill=resolved_skill,
        duration=total_duration,
    )
    multi_material_candidates = build_local_multi_material_candidates(
        content_profile=content_profile,
        local_asset_inventory={
            "has_primary_video": True,
            "auxiliary_video_count": max(0, len(list((content_profile or {}).get("merged_source_names") or [])) - 1),
        },
    )
    return {
        "hook_end_sec": round(hook_end_sec, 3),
        "cta_start_sec": round(cta_start_sec, 3) if cta_start_sec is not None else None,
        "semantic_sections": sections,
        "section_directives": _build_section_directives(
            sections,
            editing_skill=resolved_skill,
            multimodal_segment_hints=multimodal_segment_hints,
        ),
        "section_actions": _build_section_actions(
            sections,
            editing_skill=resolved_skill,
            multimodal_segment_hints=multimodal_segment_hints,
        ),
        "editing_skill": resolved_skill,
        "strategy_type": str(resolved_strategy_profile.get("strategy_type") or ""),
        "strategy_profile": resolved_strategy_profile,
        "emphasis_candidates": emphasis_candidates,
        "highlight_candidates": highlight_candidates,
        "multi_material_candidates": multi_material_candidates,
        "multimodal_segment_hints": multimodal_segment_hints,
    }


def _build_silence_cut_candidates(
    silence_segments: list[SilenceSegment],
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    scene_points: list[float],
    min_silence_to_cut: float,
    editing_skill: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None,
) -> list[CutCandidate]:
    candidates: list[CutCandidate] = []
    for silence in silence_segments:
        for cuttable_silence in _cuttable_silence_ranges(
            silence,
            subtitle_items=subtitle_items,
            transcript_segments=transcript_segments,
            content_profile=content_profile,
        ):
            if cuttable_silence.duration < min_silence_to_cut:
                continue
            candidate = _score_silence_cut(
                cuttable_silence,
                subtitle_items=subtitle_items,
                transcript_segments=transcript_segments,
                content_profile=content_profile,
                scene_points=scene_points,
                min_silence_to_cut=min_silence_to_cut,
                editing_skill=editing_skill,
                timeline_analysis=timeline_analysis,
            )
            if candidate.score >= _SILENCE_CUT_SCORE_THRESHOLD and candidate.end - candidate.start >= _MIN_CUT_DURATION_SEC:
                candidates.append(candidate)
    return candidates


def _cuttable_silence_ranges(
    silence: SilenceSegment,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
) -> list[SilenceSegment]:
    word_ranges = _meaningful_trusted_word_ranges_for_silence(
        silence,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
        content_profile=content_profile,
    )
    if not word_ranges:
        return [silence]
    bounded_ranges: list[SilenceSegment] = []
    first = word_ranges[0]
    leading_end = min(silence.end, first["start"] - _SILENCE_WORD_BOUNDARY_GUARD_SEC)
    if leading_end > silence.start + _MIN_CUT_DURATION_SEC:
        bounded_ranges.append(SilenceSegment(start=round(silence.start, 3), end=round(leading_end, 3)))
    for index in range(1, len(word_ranges)):
        previous = word_ranges[index - 1]
        next_item = word_ranges[index]
        start = max(silence.start, previous["end"] + _SILENCE_WORD_BOUNDARY_GUARD_SEC)
        end = min(silence.end, next_item["start"] - _SILENCE_WORD_BOUNDARY_GUARD_SEC)
        if end > start + _MIN_CUT_DURATION_SEC:
            bounded_ranges.append(SilenceSegment(start=round(start, 3), end=round(end, 3)))
    last = word_ranges[-1]
    trailing_start = max(silence.start, last["end"] + _SILENCE_WORD_BOUNDARY_GUARD_SEC)
    if silence.end > trailing_start + _MIN_CUT_DURATION_SEC:
        bounded_ranges.append(SilenceSegment(start=round(trailing_start, 3), end=round(silence.end, 3)))
    return bounded_ranges


def _meaningful_trusted_word_ranges_for_silence(
    silence: SilenceSegment,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []
    for item in _overlapping_subtitle_items(silence.start, silence.end, subtitle_items):
        ranges.extend(_trusted_word_ranges_from_payload(item, content_profile=content_profile, transcript_word=False))
    for item in _overlapping_transcript_segments(silence.start, silence.end, transcript_segments):
        ranges.extend(_trusted_word_ranges_from_payload(item, content_profile=content_profile, transcript_word=True))
    ranges.sort(key=lambda item: (item["start"], item["end"]))
    merged: list[dict[str, float]] = []
    for item in ranges:
        previous = merged[-1] if merged else None
        if previous and item["start"] <= previous["end"] + 0.02:
            previous["end"] = max(previous["end"], item["end"])
            continue
        merged.append(dict(item))
    return merged


def _trusted_word_ranges_from_payload(
    item: dict[str, Any],
    *,
    content_profile: dict | None,
    transcript_word: bool,
) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []
    for word in drop_redundant_synthetic_word_payloads(list(item.get("words") or item.get("words_json") or [])):
        if not isinstance(word, dict):
            continue
        word_text = str(word.get("word") or word.get("raw_text") or "").strip()
        if not _word_text_has_timing_boundary(word_text, content_profile=content_profile):
            continue
        start = _optional_float(word.get("start"))
        end = _optional_float(word.get("end"))
        if start is None or end is None or end <= start:
            continue
        if transcript_word and not _transcript_word_timing_is_trusted(word):
            continue
        ranges.append({"start": round(start, 3), "end": round(end, 3)})
    return ranges


def _word_text_has_timing_boundary(text: str, *, content_profile: dict | None) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if _looks_like_noise_subtitle(compact):
        return False
    if _is_restart_cue_text(compact):
        return False
    if _is_nonsemantic_repetition_text(compact, content_profile=content_profile):
        return False
    return True


def _score_silence_cut(
    silence: SilenceSegment,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    scene_points: list[float],
    min_silence_to_cut: float,
    editing_skill: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None,
) -> CutCandidate:
    skill_score_bias = float((editing_skill or {}).get("silence_score_bias", 0.0) or 0.0)
    continuation_guard_penalty = float((editing_skill or {}).get("continuation_guard_penalty", 0.35) or 0.35)
    score = min(
        _SILENCE_DURATION_SCORE_MAX,
        _SILENCE_DURATION_SCORE_BASE + max(0.0, silence.duration - min_silence_to_cut) * _SILENCE_DURATION_SCORE_PER_SEC,
    )
    score += skill_score_bias
    signals = [f"silence_duration={silence.duration:.2f}s"]
    previous_item = _find_previous_subtitle(silence.start, subtitle_items)
    next_item = _find_next_subtitle(silence.end, subtitle_items)
    overlaps = _overlapping_subtitle_items(silence.start, silence.end, subtitle_items)
    protected_subtitle_text_overlap = _range_has_protected_subtitle_text_overlap(
        silence.start,
        silence.end,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
    )
    protected_speech_overlap = _range_has_protected_speech_evidence(
        silence.start,
        silence.end,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
        content_profile=content_profile,
    )
    synthetic_timing_overlap = _range_has_synthetic_transcript_word_overlap(
        silence.start,
        silence.end,
        transcript_segments=transcript_segments,
    )
    trusted_word_overlap = _range_has_trusted_transcript_word_overlap(
        silence.start,
        silence.end,
        transcript_segments=transcript_segments,
    )
    range_evidence = _build_range_evidence(
        silence.start,
        silence.end,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
        content_profile=content_profile,
        timeline_analysis=timeline_analysis,
        scene_points=scene_points,
        previous_item=previous_item,
        next_item=next_item,
    )

    if not overlaps:
        score += 0.10
        signals.append("clean_gap")
    if previous_item is not None and _is_low_signal_subtitle_text(_semantic_subtitle_text(previous_item), content_profile=content_profile):
        score += 0.16
        signals.append("prev_low_signal")
    if next_item is not None and _is_low_signal_subtitle_text(_semantic_subtitle_text(next_item), content_profile=content_profile):
        score += 0.12
        signals.append("next_low_signal")
    if previous_item is not None and _is_restart_cue_text(_semantic_subtitle_text(previous_item)):
        score += 0.18
        signals.append("restart_cue_prev")
    if next_item is not None and _is_restart_cue_text(_semantic_subtitle_text(next_item)):
        score += 0.18
        signals.append("restart_cue_next")
    if _looks_like_sentence_continuation(previous_item, next_item):
        score -= continuation_guard_penalty
        signals.append(f"continuation_guard={continuation_guard_penalty:.2f}")
    if _looks_like_semantic_bridge(previous_item, next_item, content_profile=content_profile):
        score -= 0.08
        signals.append("semantic_bridge")
    if range_evidence.visual_showcase_score >= 0.74:
        protection_penalty = min(0.62, 0.32 + range_evidence.protection_score * 0.24)
        score -= protection_penalty
        signals.append(f"visual_showcase_gap={range_evidence.visual_showcase_score:.2f}")
    elif (
        transcript_segments
        and not _overlapping_transcript_segments(silence.start, silence.end, transcript_segments)
        and silence.duration >= _LONG_INVALID_NO_DIALOGUE_MIN_SEC
    ):
        score += 0.16
        signals.append("long_invalid_gap")

    previous_speaker = str((previous_item or {}).get("dominant_speaker") or "").strip()
    next_speaker = str((next_item or {}).get("dominant_speaker") or "").strip()
    if previous_speaker and next_speaker:
        if previous_speaker == next_speaker:
            score -= 0.08
            signals.append("same_speaker")
        else:
            score += 0.14
            signals.append("speaker_change")

    confidence_penalty = _silence_confidence_penalty(
        silence,
        previous_item=previous_item,
        next_item=next_item,
        transcript_segments=transcript_segments,
    )
    if confidence_penalty:
        score += confidence_penalty
        signals.append(f"confidence_guard={confidence_penalty:.2f}")

    focus_guard_penalty, focus_guard_signal = _review_focus_boundary_penalty(
        silence,
        timeline_analysis=timeline_analysis,
        editing_skill=editing_skill,
    )
    if focus_guard_penalty > 0:
        score -= focus_guard_penalty
        signals.append(f"{focus_guard_signal}={focus_guard_penalty:.2f}")

    if range_evidence.protection_score >= 0.72:
        score -= min(0.38, range_evidence.protection_score * 0.18)
        signals.append(f"evidence_protect={range_evidence.protection_score:.2f}")
    if range_evidence.removal_score >= 0.72:
        score += min(0.22, range_evidence.removal_score * 0.14)
        signals.append(f"evidence_remove={range_evidence.removal_score:.2f}")
    if protected_subtitle_text_overlap:
        score = min(score - 0.72, _SILENCE_CUT_SCORE_THRESHOLD - 0.01)
        signals.append("protected_subtitle_text_overlap")
    elif protected_speech_overlap and synthetic_timing_overlap and not trusted_word_overlap:
        vad_gap_bonus = min(0.16, 0.09 + max(0.0, silence.duration - min_silence_to_cut) * 0.05)
        score += vad_gap_bonus
        signals.append(f"vad_gap_over_synthetic_timing={vad_gap_bonus:.2f}")
    elif protected_speech_overlap:
        score = min(score - 0.55, _SILENCE_CUT_SCORE_THRESHOLD - 0.01)
        signals.append("protected_speech_overlap")
    signals.extend(f"evidence:{tag}" for tag in range_evidence.tags[:5])

    cut_start = silence.start
    cut_end = silence.end
    snapped_start = _snap_edge(cut_start, scene_points, tolerance=_SCENE_SNAP_TOLERANCE_SEC, lower_bound=0.0, upper_bound=cut_end - _MIN_CUT_DURATION_SEC)
    if snapped_start is not None:
        cut_start = snapped_start
        score += 0.06
        signals.append("scene_snap_start")
    snapped_end = _snap_edge(cut_end, scene_points, tolerance=_SCENE_SNAP_TOLERANCE_SEC, lower_bound=cut_start + _MIN_CUT_DURATION_SEC, upper_bound=max(cut_end, cut_start + _MIN_CUT_DURATION_SEC))
    if snapped_end is not None:
        cut_end = snapped_end
        score += 0.06
        signals.append("scene_snap_end")

    return CutCandidate(
        start=max(0.0, cut_start),
        end=max(max(0.0, cut_start), cut_end),
        reason="silence",
        score=max(0.0, score),
        signals=signals,
        evidence=range_evidence.to_dict(),
    )


def _build_range_evidence(
    start_time: float,
    end_time: float,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None,
    scene_points: list[float],
    previous_item: dict[str, Any] | None = None,
    next_item: dict[str, Any] | None = None,
) -> EditRangeEvidence:
    start = max(0.0, float(start_time or 0.0))
    end = max(start, float(end_time or start))
    duration = max(0.0, end - start)
    subtitle_overlaps = _overlapping_subtitle_items(start, end, subtitle_items)
    transcript_overlaps = _overlapping_transcript_segments(start, end, transcript_segments)
    previous_item = previous_item if previous_item is not None else _find_previous_subtitle(start, subtitle_items)
    next_item = next_item if next_item is not None else _find_next_subtitle(end, subtitle_items)
    action = _contextual_section_action_for_range(start, end, timeline_analysis=timeline_analysis)
    section_role = str((action or {}).get("role") or "").strip().lower()
    broll_allowed = bool((action or {}).get("broll_allowed"))
    scene_hits = sum(1 for point in scene_points if start - 0.12 <= point <= end + 0.12)
    transcript_overlap_sec = sum(_range_overlap_seconds(start, end, item.get("start"), item.get("end")) for item in transcript_overlaps)
    transcript_coverage = min(1.0, transcript_overlap_sec / duration) if duration > 0 else 0.0
    previous_text = _semantic_subtitle_text(previous_item)
    next_text = _semantic_subtitle_text(next_item)
    overlap_texts = [_semantic_subtitle_text(item) for item in subtitle_overlaps]
    context_texts = [text for text in [previous_text, *overlap_texts, next_text] if text]
    tags: list[str] = []
    multimodal_signal = _summarize_multimodal_signal_for_range(
        start,
        end,
        multimodal_segment_hints=(timeline_analysis or {}).get("multimodal_segment_hints"),
    )
    multimodal_role = str((multimodal_signal.get("roles") or [""])[0] or "")
    multimodal_keep_priority = str(multimodal_signal.get("keep_priority") or "")

    visual_score = 0.0
    if any(_has_visual_showcase_signal(text, content_profile=content_profile) for text in context_texts):
        visual_score += 0.46
        tags.append("visual_context")
    if broll_allowed:
        visual_score += 0.16
        tags.append("broll_allowed")
    if section_role == "detail":
        visual_score += 0.18
        tags.append("detail_section")
    elif section_role == "body":
        visual_score += 0.1
        tags.append("body_section")
    if scene_hits:
        visual_score += min(0.3, 0.14 + scene_hits * 0.06)
        tags.append("scene_activity")
    if _VISUAL_SHOWCASE_GAP_MIN_SEC <= duration <= _VISUAL_SHOWCASE_GAP_MAX_SEC:
        visual_score += 0.08
    if _editing_skill_has_creative_tag(timeline_analysis, {"detail_focus", "closeup_focus", "practical_demo", "workflow_breakdown"}):
        visual_score += 0.12
        tags.append("creative_visual_priority")
    positive_multimodal = float(multimodal_signal.get("positive_score", 0.0) or 0.0)
    negative_multimodal = float(multimodal_signal.get("negative_score", 0.0) or 0.0)
    if positive_multimodal > 0.0:
        visual_score += min(0.24, positive_multimodal * 0.16)
        tags.append(f"multimodal_keep_{multimodal_keep_priority or 'signal'}")
    if negative_multimodal > 0.0:
        visual_score -= min(0.18, negative_multimodal * 0.1)
        tags.append("multimodal_drop_signal")

    language_scores = [
        _subtitle_signal_score(text, content_profile=content_profile)
        for text in context_texts
        if _has_normal_language_signal(text, content_profile=content_profile)
    ]
    language_score = min(1.4, max(language_scores, default=0.0) / 2.2)
    if language_score > 0:
        tags.append("language_signal")
    if subtitle_overlaps and max(
        (_subtitle_signal_score(text, content_profile=content_profile) for text in overlap_texts),
        default=0.0,
    ) >= _STRONG_SUBTITLE_SIGNAL_SCORE:
        language_score = max(language_score, 0.82)
        tags.append("strong_subtitle")

    retake_score = 0.0
    if any(_is_restart_cue_text(text) for text in context_texts):
        retake_score += 0.72
        tags.append("restart_cue_context")
    if any(_looks_like_incomplete_tail(text) for text in overlap_texts):
        retake_score += 0.16
        tags.append("incomplete_overlap")
    if transcript_overlaps and transcript_coverage < 0.18 and not subtitle_overlaps:
        tags.append("weak_transcript_coverage")
    if negative_multimodal > 0.0 and multimodal_role in _MULTIMODAL_NEGATIVE_ROLES:
        retake_score += min(0.34, negative_multimodal * 0.2)
        tags.append(f"multimodal_role_{multimodal_role}")

    protection_score = visual_score * 0.72 + language_score * 0.46
    if transcript_coverage >= 0.25:
        protection_score += 0.18
        tags.append("transcript_present")
    if section_role in {"hook", "cta"}:
        protection_score += 0.12
        tags.append(f"{section_role}_guard")
    if positive_multimodal > 0.0:
        protection_score += min(0.34, positive_multimodal * 0.18)

    removal_score = 0.0
    if not subtitle_overlaps and transcript_coverage <= 0.05:
        removal_score += 0.28
        tags.append("no_dialogue_inside")
    if duration >= _LONG_INVALID_NO_DIALOGUE_MIN_SEC:
        removal_score += min(0.28, 0.08 + duration * 0.035)
    if retake_score:
        removal_score += min(0.48, retake_score * 0.42)
    if visual_score >= 0.74:
        removal_score -= min(0.34, visual_score * 0.24)
    if language_score >= 0.72:
        removal_score -= 0.18
    if negative_multimodal > 0.0:
        removal_score += min(0.38, negative_multimodal * 0.24)
    if positive_multimodal > 0.0:
        removal_score -= min(0.24, positive_multimodal * 0.16)

    return EditRangeEvidence(
        start=start,
        end=end,
        duration_sec=duration,
        subtitle_count=len(subtitle_overlaps),
        transcript_count=len(transcript_overlaps),
        transcript_coverage=max(0.0, transcript_coverage),
        scene_boundary_count=scene_hits,
        section_role=section_role,
        broll_allowed=broll_allowed,
        visual_showcase_score=max(0.0, min(1.4, visual_score)),
        language_score=max(0.0, min(1.4, language_score)),
        retake_score=max(0.0, min(1.4, retake_score)),
        protection_score=max(0.0, min(1.6, protection_score)),
        removal_score=max(0.0, min(1.6, removal_score)),
        multimodal_role=multimodal_role,
        multimodal_keep_priority=multimodal_keep_priority,
        multimodal_score=max(-1.6, min(1.6, float(multimodal_signal.get("score", 0.0) or 0.0))),
        tags=list(dict.fromkeys(tags)),
        previous_text=previous_text,
        next_text=next_text,
    )


def _build_subtitle_cut_candidates(
    subtitle_items: list[dict[str, Any]],
    *,
    content_profile: dict | None,
    transcript_segments: list[dict[str, Any]] | None = None,
) -> list[CutCandidate]:
    candidates: list[CutCandidate] = []
    for item in subtitle_items:
        text = _semantic_subtitle_text(item)
        compact = _compact_subtitle_text(text)
        if _looks_like_noise_subtitle(compact):
            _append_subtitle_rule_candidate(
                candidates,
                start=float(item["start_time"]),
                end=float(item["end_time"]),
                reason="noise_subtitle",
                signals=["noise_subtitle"],
                transcript_segments=transcript_segments,
                content_profile=content_profile,
            )
            continue
        if FILLER_PATTERN.search(text):
            clean = PUNCTUATION_PATTERN.sub("", FILLER_PATTERN.sub("", text).strip())
            if not clean:
                _append_subtitle_rule_candidate(
                    candidates,
                    start=float(item["start_time"]),
                    end=float(item["end_time"]),
                    reason="filler_word",
                    signals=["pure_filler"],
                    transcript_segments=transcript_segments,
                    content_profile=content_profile,
                )
        for start, end, phrase in _subtitle_hesitation_filler_ranges(item, text):
            _append_subtitle_rule_candidate(
                candidates,
                start=start,
                end=end,
                reason="filler_word",
                signals=["partial_filler", f"token:{phrase}"],
                transcript_segments=transcript_segments,
                content_profile=content_profile,
            )
        for start, end, unit in _subtitle_repeated_speech_ranges(item, text, content_profile=content_profile):
            _append_subtitle_rule_candidate(
                candidates,
                start=start,
                end=end,
                reason="repeated_speech",
                signals=["partial_repeated_speech", f"unit:{unit}"],
                transcript_segments=transcript_segments,
                content_profile=content_profile,
            )
    return candidates


def _append_subtitle_rule_candidate(
    candidates: list[CutCandidate],
    *,
    start: float,
    end: float,
    reason: str,
    signals: list[str],
    transcript_segments: list[dict[str, Any]] | None,
    content_profile: dict | None,
) -> None:
    if end <= start:
        return
    allowed, audit_signal = _subtitle_rule_cut_allowed_by_transcript(
        start,
        end,
        reason=reason,
        signals=signals,
        transcript_segments=transcript_segments or [],
        content_profile=content_profile,
    )
    if not allowed:
        return
    candidate_signals = list(signals)
    if audit_signal:
        candidate_signals.append(audit_signal)
    candidates.append(
        CutCandidate(
            start=start,
            end=end,
            reason=reason,
            hard=True,
            signals=candidate_signals,
        )
    )


def _subtitle_rule_cut_allowed_by_transcript(
    start: float,
    end: float,
    *,
    reason: str,
    signals: list[str],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
) -> tuple[bool, str]:
    if not transcript_segments:
        return True, "subtitle_rule_no_transcript_guard"
    overlapping_words: list[str] = []
    for segment in _overlapping_transcript_segments(start, end, transcript_segments):
        words = [word for word in list(segment.get("words") or []) if isinstance(word, dict)]
        if not words:
            if _range_overlap_seconds(start, end, segment.get("start"), segment.get("end")) > 0.0:
                return False, "blocked_by_segment_transcript"
            continue
        for word in words:
            if not _transcript_word_timing_is_trusted(word):
                continue
            word_overlap = _range_overlap_seconds(start, end, word.get("start"), word.get("end"))
            word_start = _optional_float(word.get("start"))
            word_end = _optional_float(word.get("end"))
            word_duration = max(0.0, (word_end or 0.0) - (word_start or 0.0))
            if word_overlap < min(0.04, max(0.012, word_duration * 0.2)):
                continue
            word_text = _compact_subtitle_text(str(word.get("word") or word.get("raw_text") or ""))
            if not word_text:
                continue
            overlapping_words.append(word_text)

    if not overlapping_words:
        return True, "subtitle_rule_no_trusted_word_overlap"
    if reason == "filler_word":
        return (
            all(_transcript_word_is_explicit_filler(word) for word in overlapping_words),
            "subtitle_rule_confirmed_by_transcript_filler",
        )
    if reason == "repeated_speech":
        repeated_units = {
            _compact_subtitle_text(signal.split(":", 1)[1])
            for signal in signals
            if str(signal).startswith("unit:")
        }
        return (
            bool(repeated_units)
            and all(any(word == unit or word in unit or unit in word for unit in repeated_units) for word in overlapping_words)
            and not any(
                _subtitle_has_protected_speech_text(word, content_profile=content_profile)
                and not any(word == unit or word in unit or unit in word for unit in repeated_units)
                for word in overlapping_words
            ),
            "subtitle_rule_confirmed_by_transcript_repetition",
        )
    if reason == "noise_subtitle":
        return (
            all(_looks_like_noise_subtitle(word) for word in overlapping_words),
            "subtitle_rule_confirmed_by_transcript_noise",
        )
    return False, "blocked_by_unverified_subtitle_rule"


def _transcript_word_is_explicit_filler(word_text: str) -> bool:
    compact = _compact_subtitle_text(word_text)
    if not compact:
        return True
    if compact in {_compact_subtitle_text(item) for item in HESITATION_FILLER_WORDS}:
        return True
    stripped = _compact_subtitle_text(FILLER_PATTERN.sub("", compact))
    return not stripped


def _subtitle_hesitation_filler_ranges(item: dict[str, Any], text: str) -> list[tuple[float, float, str]]:
    ranges: list[tuple[float, float, str]] = []
    for filler in HESITATION_FILLER_WORDS:
        for start_char, end_char in _subtitle_text_match_char_ranges(text, filler):
            if start_char != 0:
                continue
            timed_range = _subtitle_char_range_to_time(item, start_char, end_char)
            if timed_range is None:
                continue
            start, end = timed_range
            if end >= start + _MIN_PARTIAL_SUBTITLE_CUT_DURATION_SEC:
                ranges.append((start, end, filler))
    return _dedupe_subtitle_rule_ranges(ranges)


def _subtitle_repeated_speech_ranges(
    item: dict[str, Any],
    text: str,
    *,
    content_profile: dict | None,
) -> list[tuple[float, float, str]]:
    ranges: list[tuple[float, float, str]] = []
    for match in re.finditer(r"([\u4e00-\u9fff]{1,3})([\s，,、]*)\1", text):
        separator = match.group(2) or ""
        keep_first = match.group(1) or ""
        if len(keep_first) <= 1 and not separator.strip() and not re.search(r"[，,、]", separator):
            continue
        match_index = match.start()
        first_start_char = len(text[:match_index])
        first_end_char = first_start_char + len(keep_first)
        remove_start_char = first_end_char + len(separator)
        remove_end_char = remove_start_char + len(keep_first)
        first_timed_range = _subtitle_char_range_to_time(item, first_start_char, first_end_char)
        remove_timed_range = _subtitle_char_range_to_time(item, remove_start_char, remove_end_char)
        if first_timed_range is None or remove_timed_range is None:
            continue
        if remove_timed_range[0] - first_timed_range[1] > _MAX_REPEATED_SPEECH_COPY_GAP_SEC:
            continue
        start, end = remove_timed_range
        if end >= start + _MIN_PARTIAL_SUBTITLE_CUT_DURATION_SEC:
            ranges.append((start, end, keep_first))
    return _dedupe_subtitle_rule_ranges(ranges)


def _subtitle_text_match_char_ranges(text: str, needle: str) -> list[tuple[int, int]]:
    if not text or not needle:
        return []
    ranges: list[tuple[int, int]] = []
    search_from = 0
    while search_from < len(text):
        match_index = text.find(needle, search_from)
        if match_index < 0:
            break
        ranges.append((len(text[:match_index]), len(text[:match_index]) + len(needle)))
        search_from = match_index + len(needle)
    return ranges


def _subtitle_char_range_to_time(item: dict[str, Any], start_char: int, end_char: int) -> tuple[float, float] | None:
    text = _semantic_subtitle_text(item)
    if not text:
        return None
    alignment = build_subtitle_span_alignment(item)
    if alignment.matched_ratio < 0.98:
        return None
    unit_char_indexes = [
        index
        for index, char in enumerate(text)
        if char in subtitle_display_units(char)
    ]
    if not unit_char_indexes or len(alignment.units) != len(unit_char_indexes):
        return None
    clamped_start = min(max(0, start_char), len(text))
    clamped_end = min(max(clamped_start, end_char), len(text))
    selected_units = [
        alignment.units[unit_index]
        for unit_index, char_index in enumerate(unit_char_indexes)
        if clamped_start <= char_index < clamped_end
    ]
    if not selected_units:
        return None
    start = min(float(unit.start) for unit in selected_units)
    end = max(float(unit.end) for unit in selected_units)
    if end <= start:
        return None
    return round(start, 3), round(end, 3)


def _dedupe_subtitle_rule_ranges(ranges: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    deduped: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for start, end, label in sorted(ranges, key=lambda item: (round(item[0], 3), -round(item[1] - item[0], 3))):
        key = (round(start, 3), round(end, 3), label)
        if key in seen:
            continue
        if any(min(end, kept_end) - max(start, kept_start) > 0.001 for kept_start, kept_end, _kept_label in deduped):
            continue
        seen.add(key)
        deduped.append((round(start, 3), round(end, 3), label))
    return deduped


def _build_hard_cut_candidates(cuts: list[tuple[float, float, str]]) -> list[CutCandidate]:
    return [
        CutCandidate(start=start, end=end, reason=reason, hard=True, signals=["hard_rule"])
        for start, end, reason in cuts
        if end > start
    ]


def _classify_semantic_role(
    item: dict[str, Any],
    *,
    index: int,
    total_items: int,
    total_duration: float,
) -> str:
    text = _semantic_subtitle_text(item)
    start_time = float(item.get("start_time", 0.0) or 0.0)
    end_time = float(item.get("end_time", 0.0) or 0.0)
    cta_keywords = ("点赞", "关注", "收藏", "评论", "下期", "下次", "记得", "转发", "关注我")
    detail_keywords = ("参数", "细节", "纹理", "材质", "质感", "效果", "体验", "对比", "测试", "上手", "展示", "演示", "操作", "区别", "优点", "缺点")
    hook_keywords = ("先说", "先看", "直接", "今天", "这次", "先给", "先抛", "先讲", "结论")

    if any(keyword in text for keyword in cta_keywords):
        return "cta"
    if total_duration > 0 and start_time >= total_duration * 0.78 and index >= max(0, total_items - 2):
        return "cta"
    if index <= 1 or end_time <= min(8.5, max(4.5, total_duration * 0.3 if total_duration > 0 else 8.5)):
        if any(keyword in text for keyword in hook_keywords) or index == 0:
            return "hook"
    if any(keyword in text for keyword in detail_keywords):
        return "detail"
    return "body"


def _merge_semantic_sections(annotated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not annotated:
        return []
    sections: list[dict[str, Any]] = []
    current = {
        "role": annotated[0]["role"],
        "start_sec": annotated[0]["start_time"],
        "end_sec": annotated[0]["end_time"],
        "summary": annotated[0]["text"][:24],
        "item_indexes": [annotated[0]["index"]],
    }
    for item in annotated[1:]:
        if item["role"] == current["role"]:
            current["end_sec"] = item["end_time"]
            current["item_indexes"].append(item["index"])
            if len(str(current["summary"])) < 12:
                current["summary"] = str(current["summary"]) + " / " + item["text"][:12]
            continue
        sections.append(
            {
                "role": current["role"],
                "start_sec": round(float(current["start_sec"]), 3),
                "end_sec": round(float(current["end_sec"]), 3),
                "summary": str(current["summary"])[:48],
                "item_indexes": list(current["item_indexes"]),
            }
        )
        current = {
            "role": item["role"],
            "start_sec": item["start_time"],
            "end_sec": item["end_time"],
            "summary": item["text"][:24],
            "item_indexes": [item["index"]],
        }
    sections.append(
        {
            "role": current["role"],
            "start_sec": round(float(current["start_sec"]), 3),
            "end_sec": round(float(current["end_sec"]), 3),
            "summary": str(current["summary"])[:48],
            "item_indexes": list(current["item_indexes"]),
        }
    )
    return sections


def _build_emphasis_candidates(annotated: list[dict[str, Any]], *, max_count: int = 6) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in annotated:
        score = float(item["signal"])
        text = str(item["text"] or "")
        if any(keyword in text for keyword in ("注意", "重点", "关键", "直接", "一定", "参数", "对比")):
            score += 1.2
        if any(ch.isdigit() for ch in text):
            score += 0.8
        if item["role"] == "hook":
            score += 0.7
        if score <= 0.8:
            continue
        ranked.append(
            (
                score,
                {
                    "text": text[:18],
                    "start_time": round(float(item["start_time"]), 3),
                    "end_time": round(float(item["end_time"]), 3),
                    "role": item["role"],
                    "score": round(score, 3),
                },
            )
        )
    chosen: list[dict[str, Any]] = []
    for _score, candidate in sorted(ranked, key=lambda item: (-item[0], float(item[1]["start_time"]))):
        if any(abs(float(candidate["start_time"]) - float(existing["start_time"])) < 1.6 for existing in chosen):
            continue
        chosen.append(candidate)
        if len(chosen) >= max_count:
            break
    return chosen


def _build_section_directives(
    sections: list[dict[str, Any]],
    *,
    editing_skill: dict[str, Any] | None = None,
    multimodal_segment_hints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    section_policy = dict((editing_skill or {}).get("section_policy") or {})
    creative_tags = _editing_skill_creative_preferences(editing_skill)
    directives: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        role = str(section.get("role") or "")
        policy = dict(section_policy.get(role) or {})
        overlay_weight = float(policy.get("overlay_weight", 0.0) or 0.0)
        music_entry_allowed = bool(policy.get("music_entry_allowed", role != "cta"))
        insert_allowed = bool(policy.get("insert_allowed", role in {"detail", "body"}))
        preference_labels, rationale = _section_creative_preference_annotation(role=role, creative_tags=creative_tags)
        multimodal_signal = _summarize_multimodal_signal_for_range(
            float(section.get("start_sec") or 0.0),
            float(section.get("end_sec") or 0.0),
            multimodal_segment_hints=multimodal_segment_hints,
        )
        overlay_weight += float(multimodal_signal.get("overlay_bonus", 0.0) or 0.0)
        directives.append(
            {
                "index": index,
                "role": role,
                "start_sec": round(float(section.get("start_sec") or 0.0), 3),
                "end_sec": round(float(section.get("end_sec") or 0.0), 3),
                "overlay_weight": round(overlay_weight, 3),
                "music_entry_allowed": music_entry_allowed,
                "music_entry_bonus": round(float(policy.get("music_entry_bonus", 0.0) or 0.0), 3),
                "insert_allowed": insert_allowed,
                "insert_priority": round(float(policy.get("insert_priority", 0.0) or 0.0), 3),
                "creative_preferences": preference_labels,
                "creative_rationale": rationale,
                "multimodal_roles": list(multimodal_signal.get("roles") or []),
                "multimodal_keep_priority": str(multimodal_signal.get("keep_priority") or ""),
                "multimodal_signal": round(float(multimodal_signal.get("score", 0.0) or 0.0), 3),
            }
        )
    return directives


def _build_section_actions(
    sections: list[dict[str, Any]],
    *,
    editing_skill: dict[str, Any] | None = None,
    multimodal_segment_hints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    section_policy = dict((editing_skill or {}).get("section_policy") or {})
    creative_tags = _editing_skill_creative_preferences(editing_skill)
    actions: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        role = str(section.get("role") or "")
        start_sec = round(float(section.get("start_sec") or 0.0), 3)
        end_sec = round(float(section.get("end_sec") or 0.0), 3)
        duration_sec = max(0.0, end_sec - start_sec)
        policy = dict(section_policy.get(role) or {})
        anchor_bias = min(1.0, max(0.0, float(policy.get("broll_anchor_bias", 0.5) or 0.5)))
        preference_labels, rationale = _section_creative_preference_annotation(role=role, creative_tags=creative_tags)
        multimodal_signal = _summarize_multimodal_signal_for_range(
            start_sec,
            end_sec,
            multimodal_segment_hints=multimodal_segment_hints,
        )
        trim_intensity = str(policy.get("trim_intensity") or "balanced")
        if bool(multimodal_signal.get("preserve_trim")) and trim_intensity == "balanced":
            trim_intensity = "preserve"
        actions.append(
            {
                "index": index,
                "role": role,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": round(duration_sec, 3),
                "trim_intensity": trim_intensity,
                "packaging_intent": str(policy.get("packaging_intent") or f"{role}_support"),
                "transition_boost": round(
                    float(policy.get("transition_boost", 0.0) or 0.0)
                    + float(multimodal_signal.get("transition_bonus", 0.0) or 0.0),
                    3,
                ),
                "transition_anchor_sec": start_sec,
                "broll_allowed": bool(policy.get("broll_allowed", False)),
                "broll_anchor_sec": round(start_sec + duration_sec * anchor_bias, 3),
                "action_priority": round(
                    float(policy.get("insert_priority", 0.0) or 0.0)
                    + float(multimodal_signal.get("action_bonus", 0.0) or 0.0),
                    3,
                ),
                "creative_preferences": preference_labels,
                "creative_rationale": rationale,
                "multimodal_roles": list(multimodal_signal.get("roles") or []),
                "multimodal_keep_priority": str(multimodal_signal.get("keep_priority") or ""),
                "multimodal_signal": round(float(multimodal_signal.get("score", 0.0) or 0.0), 3),
            }
        )
    return actions


def _editing_skill_creative_preferences(editing_skill: dict[str, Any] | None) -> set[str]:
    return {
        str(item or "").strip()
        for item in (editing_skill or {}).get("creative_preferences") or []
        if str(item or "").strip()
    }


def _editing_skill_has_creative_tag(
    timeline_analysis: dict[str, Any] | None,
    tags: set[str],
) -> bool:
    if not tags:
        return False
    skill = (timeline_analysis or {}).get("editing_skill")
    if not isinstance(skill, dict):
        return False
    return bool(_editing_skill_creative_preferences(skill) & tags)


def _build_multimodal_segment_hints(
    *,
    content_profile: dict | None,
    duration: float | None,
) -> list[dict[str, Any]]:
    video_understanding = ((content_profile or {}).get("video_understanding") or {})
    if not isinstance(video_understanding, dict):
        return []
    return normalize_video_understanding_segment_hints(video_understanding, duration=duration)


def _video_understanding_hints_for_range(
    start_time: float,
    end_time: float,
    *,
    multimodal_segment_hints: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for hint in list(multimodal_segment_hints or []):
        if not isinstance(hint, dict):
            continue
        hint_start = float(hint.get("start", 0.0) or 0.0)
        hint_end = float(hint.get("end", hint_start) or hint_start)
        if hint_end <= start_time or hint_start >= end_time:
            continue
        matched.append(hint)
    return matched


def _priority_rank(value: str) -> int:
    return {"drop": 0, "low": 1, "medium": 2, "high": 3}.get(str(value or "").strip().lower(), -1)


def _priority_weight(value: str) -> float:
    return {
        "drop": 0.95,
        "low": 0.22,
        "medium": 0.52,
        "high": 0.88,
    }.get(str(value or "").strip().lower(), 0.0)


def _multimodal_overlap_strength(
    start_time: float,
    end_time: float,
    *,
    hint: dict[str, Any],
) -> float:
    overlap = max(
        0.0,
        min(end_time, float(hint.get("end", 0.0) or 0.0)) - max(start_time, float(hint.get("start", 0.0) or 0.0)),
    )
    if overlap <= 0.0:
        return 0.0
    range_duration = max(0.6, end_time - start_time)
    hint_duration = max(0.6, float(hint.get("duration_sec", 0.0) or 0.0))
    confidence = max(0.24, float(hint.get("confidence", 0.0) or 0.0))
    return min(1.2, overlap / min(range_duration, hint_duration) * confidence)


def _summarize_multimodal_signal_for_range(
    start_time: float,
    end_time: float,
    *,
    multimodal_segment_hints: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    matched = _video_understanding_hints_for_range(
        start_time,
        end_time,
        multimodal_segment_hints=multimodal_segment_hints,
    )
    if not matched:
        return {
            "roles": [],
            "keep_priority": "",
            "score": 0.0,
            "positive_score": 0.0,
            "negative_score": 0.0,
            "overlay_bonus": 0.0,
            "action_bonus": 0.0,
            "transition_bonus": 0.0,
            "preserve_trim": False,
        }

    positive_score = 0.0
    negative_score = 0.0
    strongest_positive = ("", "", 0.0)
    strongest_negative = ("", "", 0.0)
    roles: list[str] = []
    for hint in matched:
        role = str(hint.get("role") or "").strip().lower()
        keep_priority = str(hint.get("keep_priority") or "").strip().lower()
        strength = _multimodal_overlap_strength(start_time, end_time, hint=hint)
        weighted = strength * _priority_weight(keep_priority or "medium")
        if role and role not in roles:
            roles.append(role)
        if keep_priority == "drop" or role in _MULTIMODAL_NEGATIVE_ROLES:
            negative_score += weighted
            if weighted > strongest_negative[2]:
                strongest_negative = (role, keep_priority, weighted)
            continue
        if role in _MULTIMODAL_POSITIVE_ROLES:
            role_bonus = 1.0
            if role in {"comparison", "detail_showcase", "demo"}:
                role_bonus = 1.18
            elif role in {"hook", "cta"}:
                role_bonus = 1.1
            weighted *= role_bonus
        positive_score += weighted
        if weighted > strongest_positive[2]:
            strongest_positive = (role, keep_priority, weighted)

    dominant_priority = ""
    if strongest_positive[2] >= strongest_negative[2]:
        dominant_priority = strongest_positive[1]
    elif strongest_negative[2] > 0:
        dominant_priority = strongest_negative[1] or "drop"
    net_score = positive_score - negative_score
    strongest_role = strongest_positive[0] if strongest_positive[2] >= strongest_negative[2] else strongest_negative[0]
    overlay_bonus = 0.0
    action_bonus = 0.0
    transition_bonus = 0.0
    preserve_trim = False
    if positive_score > 0:
        overlay_bonus += min(0.22, positive_score * 0.12)
        action_bonus += min(0.26, positive_score * 0.14)
        transition_bonus += min(0.18, positive_score * 0.1)
        preserve_trim = positive_score >= 0.42 and strongest_role in {"comparison", "detail_showcase", "demo", "hook", "cta"}
    if negative_score > 0:
        overlay_bonus -= min(0.12, negative_score * 0.08)
        action_bonus -= min(0.18, negative_score * 0.1)
        transition_bonus -= min(0.12, negative_score * 0.08)
    return {
        "roles": roles[:4],
        "keep_priority": dominant_priority,
        "score": round(net_score, 3),
        "positive_score": round(positive_score, 3),
        "negative_score": round(negative_score, 3),
        "overlay_bonus": round(overlay_bonus, 3),
        "action_bonus": round(action_bonus, 3),
        "transition_bonus": round(transition_bonus, 3),
        "preserve_trim": preserve_trim,
    }


def _section_creative_preference_annotation(*, role: str, creative_tags: set[str]) -> tuple[list[str], str]:
    if not creative_tags:
        return [], ""
    normalized_role = str(role or "").strip().lower()
    labels = [_CREATIVE_PREFERENCE_LABELS.get(tag, tag) for tag in sorted(creative_tags)]
    reasons: list[str] = []
    if normalized_role == "hook":
        if "conclusion_first" in creative_tags:
            reasons.append("开头优先前置结论")
        if "fast_paced" in creative_tags:
            reasons.append("开头节奏收紧，尽快给重点")
        if "comparison_focus" in creative_tags:
            reasons.append("开头先抛出关键差异")
    elif normalized_role == "detail":
        if "detail_focus" in creative_tags or "closeup_focus" in creative_tags:
            reasons.append("细节段优先保留近景和做工镜头")
        if "comparison_focus" in creative_tags:
            reasons.append("细节段优先承载版本差异")
        if "practical_demo" in creative_tags:
            reasons.append("细节段优先承载上手实测")
    elif normalized_role == "body":
        if "workflow_breakdown" in creative_tags:
            reasons.append("主体段优先保留流程拆解")
        if "comparison_focus" in creative_tags:
            reasons.append("主体段优先展开取舍逻辑")
        if "practical_demo" in creative_tags:
            reasons.append("主体段优先保留实际使用场景")
    elif normalized_role == "cta" and "conclusion_first" in creative_tags:
        reasons.append("结尾延续结论式收口")
    return labels, "；".join(reasons)


def _normalize_subtitle_items(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in subtitle_items:
        start_time = _as_float(item.get("start_time"))
        end_time = _as_float(item.get("end_time"))
        if end_time <= start_time:
            continue
        normalized.append(
            {
                **dict(item),
                "start_time": start_time,
                "end_time": end_time,
                "text_raw": subtitle_raw_rule_text(item),
                "text_norm": subtitle_canonical_rule_text(item),
                "text_final": subtitle_display_rule_text(item),
            }
        )
    normalized.sort(key=lambda item: (item["start_time"], item["end_time"]))
    return normalized


def _normalize_transcript_segments(transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(transcript_segments):
        payload = dict(item) if isinstance(item, dict) else {
            "index": getattr(item, "index", index),
            "start": getattr(item, "start", getattr(item, "start_time", 0.0)),
            "end": getattr(item, "end", getattr(item, "end_time", 0.0)),
            "text": getattr(item, "text", ""),
            "speaker": getattr(item, "speaker", None),
            "words": getattr(item, "words", getattr(item, "words_json", [])),
            "confidence": getattr(item, "confidence", None),
            "logprob": getattr(item, "logprob", None),
            "alignment": getattr(item, "alignment", None),
        }
        start = _as_float(payload.get("start"), fallback=_as_float(payload.get("start_time")))
        end = _as_float(payload.get("end"), fallback=_as_float(payload.get("end_time")))
        if end <= start:
            continue
        words: list[dict[str, Any]] = []
        for word in drop_redundant_synthetic_word_payloads(list(payload.get("words") or payload.get("words_json") or [])):
            if isinstance(word, dict):
                word_start = _as_float(word.get("start"))
                word_end = _as_float(word.get("end"), fallback=word_start)
                words.append(
                    {
                        "word": str(word.get("word") or word.get("raw_text") or ""),
                        "start": word_start,
                        "end": word_end,
                        "confidence": _optional_float(word.get("confidence")),
                        "logprob": _optional_float(word.get("logprob")),
                        "alignment": word.get("alignment"),
                        "raw_payload": word.get("raw_payload"),
                    }
                )
        normalized.append(
            {
                "index": int(payload.get("index", index) or index),
                "start": start,
                "end": end,
                "text": str(payload.get("text") or payload.get("raw_text") or ""),
                "speaker": str(payload.get("speaker") or "").strip() or None,
                "confidence": _optional_float(payload.get("confidence")),
                "logprob": _optional_float(payload.get("logprob")),
                "alignment": payload.get("alignment"),
                "words": words,
            }
        )
    normalized.sort(key=lambda item: (item["start"], item["end"]))
    return normalized


def _normalize_scene_points(scene_boundaries: list[SceneBoundary | dict[str, Any] | float]) -> list[float]:
    points: list[float] = []
    for boundary in scene_boundaries:
        if isinstance(boundary, (int, float)):
            if float(boundary) >= 0:
                points.append(float(boundary))
            continue
        if isinstance(boundary, dict):
            for key in ("start", "end"):
                value = _optional_float(boundary.get(key))
                if value is not None and value >= 0:
                    points.append(value)
            continue
        for key in ("start", "end"):
            value = _optional_float(getattr(boundary, key, None))
            if value is not None and value >= 0:
                points.append(value)
    return sorted({round(point, 3) for point in points})


def _enrich_subtitle_items_with_transcript_evidence(
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in subtitle_items:
        item_start = float(item["start_time"])
        item_end = float(item["end_time"])
        item_duration = max(0.0, item_end - item_start)
        overlaps = _overlapping_transcript_segments(item_start, item_end, transcript_segments)
        confidence_values: list[float] = []
        logprob_values: list[float] = []
        speaker_labels: list[str] = []
        transcript_texts: list[str] = []
        has_alignment = False
        word_count = 0
        for segment in overlaps:
            segment_text = _transcript_text_for_subtitle_window(
                segment,
                start_time=item_start,
                end_time=item_end,
                max_window_duration=max(item_duration, 0.001),
            )
            if segment_text:
                transcript_texts.append(segment_text)
            if segment.get("confidence") is not None:
                confidence_values.append(float(segment["confidence"]))
            if segment.get("logprob") is not None:
                logprob_values.append(float(segment["logprob"]))
            speaker = str(segment.get("speaker") or "").strip()
            if speaker:
                speaker_labels.append(speaker)
            if segment.get("alignment") is not None:
                has_alignment = True
            words = list(segment.get("words") or [])
            word_count += len(words)
            for word in words:
                if word.get("confidence") is not None:
                    confidence_values.append(float(word["confidence"]))
                if word.get("logprob") is not None:
                    logprob_values.append(float(word["logprob"]))
                if word.get("alignment") is not None:
                    has_alignment = True
        enriched.append(
            {
                **item,
                "avg_confidence": _mean(confidence_values),
                "avg_logprob": _mean(logprob_values),
                "dominant_speaker": _dominant_label(speaker_labels),
                "speaker_labels": sorted(set(speaker_labels)),
                "has_speaker_change": len(set(speaker_labels)) > 1,
                "alignment_supported": has_alignment,
                "transcript_text": " ".join(transcript_texts).strip(),
                "transcript_texts": transcript_texts,
                "word_count": word_count,
            }
        )
    return enriched


def _transcript_text_for_subtitle_window(
    segment: dict[str, Any],
    *,
    start_time: float,
    end_time: float,
    max_window_duration: float,
) -> str:
    words = [word for word in list(segment.get("words") or []) if isinstance(word, dict)]
    clipped_words: list[str] = []
    for word in words:
        word_start = _optional_float(word.get("start"))
        word_end = _optional_float(word.get("end"))
        if word_start is None:
            continue
        if word_end is None:
            word_end = word_start
        if word_end <= word_start:
            continue
        word_overlap = _range_overlap_seconds(start_time, end_time, word_start, word_end)
        word_duration = max(0.001, word_end - word_start)
        if word_overlap < min(0.04, max(0.012, word_duration * 0.2)):
            continue
        text = str(word.get("word") or word.get("raw_text") or "").strip()
        if text:
            clipped_words.append(text)
    if clipped_words:
        return "".join(clipped_words).strip()

    segment_start = _as_float(segment.get("start"))
    segment_end = _as_float(segment.get("end"), fallback=segment_start)
    segment_duration = max(0.0, segment_end - segment_start)
    if segment_duration > max(8.0, max_window_duration * 3.0):
        return ""
    overlap = _range_overlap_seconds(start_time, end_time, segment_start, segment_end)
    if overlap <= 0.0 or overlap < min(max_window_duration, segment_duration) * 0.5:
        return ""
    return str(segment.get("text") or "").strip()


def _merge_cut_intervals(cuts: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    cuts.sort(key=lambda x: x[0])
    merged_cuts: list[tuple[float, float, str]] = []
    for cut in cuts:
        if merged_cuts and cut[0] <= merged_cuts[-1][1]:
            prev = merged_cuts[-1]
            merged_reason = prev[2] if _cut_reason_priority(prev[2]) >= _cut_reason_priority(cut[2]) else cut[2]
            merged_cuts[-1] = (prev[0], max(prev[1], cut[1]), merged_reason)
        else:
            merged_cuts.append(cut)
    return merged_cuts


def _build_segments_from_cuts(*, duration: float, merged_cuts: list[tuple[float, float, str]]) -> list[EditSegment]:
    segments: list[EditSegment] = []
    cursor = 0.0
    for cut_start, cut_end, reason in merged_cuts:
        if cursor < cut_start:
            segments.append(EditSegment(start=cursor, end=cut_start, type="keep"))
        segments.append(EditSegment(start=cut_start, end=cut_end, type="remove", reason=reason))
        cursor = cut_end
    if cursor < duration:
        segments.append(EditSegment(start=cursor, end=duration, type="keep"))
    return segments


_PACING_RULE_CANDIDATE_REASONS = {
    "timing_trim",
    "micro_keep",
    "micro_keep_bridge",
    "long_non_dialogue",
    "gap_fill",
}


def _collect_pacing_rule_candidates(
    base_segments: list[EditSegment],
    refined_segments: list[EditSegment],
) -> list[CutCandidate]:
    base_removes = [
        segment
        for segment in base_segments
        if segment.type == "remove" and segment.end > segment.start
    ]
    candidates: list[CutCandidate] = []
    for segment in refined_segments:
        if segment.type != "remove" or segment.reason not in _PACING_RULE_CANDIDATE_REASONS:
            continue
        if segment.end <= segment.start + 0.08:
            continue
        if any(_same_cut_interval(segment, applied) for applied in base_removes):
            continue
        candidates.append(
            CutCandidate(
                start=segment.start,
                end=segment.end,
                reason=segment.reason,
                score=0.65,
                hard=False,
                signals=["pacing_rule_candidate"],
                evidence={"candidate_origin": "pacing_refinement_preview"},
            )
        )
    return candidates


def _same_cut_interval(left: EditSegment, right: EditSegment) -> bool:
    return abs(left.start - right.start) <= 0.001 and abs(left.end - right.end) <= 0.001


def _refine_segments_for_pacing(
    segments: list[EditSegment],
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    duration: float,
    timeline_analysis: dict[str, Any] | None = None,
    scene_points: list[float] | None = None,
) -> list[EditSegment]:
    refined: list[EditSegment] = []
    for segment in segments:
        if segment.type != "keep":
            refined.append(segment)
            continue

        seg_duration = max(0.0, segment.end - segment.start)
        trim_profile = _resolve_trim_profile_for_segment(segment, timeline_analysis=timeline_analysis)
        overlaps = _overlapping_subtitle_items(segment.start, segment.end, subtitle_items)
        if not overlaps:
            transcript_overlaps = _overlapping_transcript_segments(segment.start, segment.end, transcript_segments)
            previous_item = _find_previous_subtitle(segment.start, subtitle_items)
            next_item = _find_next_subtitle(segment.end, subtitle_items)
            range_evidence = _build_range_evidence(
                segment.start,
                segment.end,
                subtitle_items=subtitle_items,
                transcript_segments=transcript_segments,
                content_profile=content_profile,
                timeline_analysis=timeline_analysis,
                scene_points=scene_points or [],
                previous_item=previous_item,
                next_item=next_item,
            )
            if transcript_overlaps:
                refined.append(segment)
                continue
            if range_evidence.protection_score >= 0.62:
                refined.append(segment)
                continue
            if seg_duration <= float(trim_profile["micro_keep_no_subtitle_max_sec"]):
                refined.append(EditSegment(start=segment.start, end=segment.end, type="remove", reason="micro_keep"))
            elif _should_remove_long_non_dialogue_keep(
                segment,
                subtitle_items=subtitle_items,
                transcript_segments=transcript_segments,
                content_profile=content_profile,
                timeline_analysis=timeline_analysis,
                scene_points=scene_points or [],
            ):
                refined.append(EditSegment(start=segment.start, end=segment.end, type="remove", reason="long_non_dialogue"))
            else:
                refined.append(segment)
            continue

        keep_energy = _resolve_keep_energy_for_segment(
            segment,
            overlaps=overlaps,
            timeline_analysis=timeline_analysis,
            content_profile=content_profile,
        )
        max_signal = max(_subtitle_signal_score(_semantic_subtitle_text(item), content_profile=content_profile) for item in overlaps)
        overlap_start = min(float(item.get("start_time", 0.0) or 0.0) for item in overlaps)
        overlap_end = max(float(item.get("end_time", 0.0) or 0.0) for item in overlaps)
        overlap_duration = max(0.0, overlap_end - overlap_start)
        pad_before = _KEEP_TRIM_PAD_BEFORE_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_TRIM_PAD_BEFORE_SEC
        pad_after = _KEEP_TRIM_PAD_AFTER_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_TRIM_PAD_AFTER_SEC
        max_edge_trim = _KEEP_EDGE_TRIM_MAX_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_EDGE_TRIM_MAX_SEC
        pad_before *= float(trim_profile["pad_multiplier"])
        pad_after *= float(trim_profile["pad_multiplier"])
        max_edge_trim *= float(trim_profile["max_edge_trim_multiplier"])
        pad_before += min(0.14, keep_energy * 0.05)
        pad_after += min(0.18, keep_energy * 0.06)
        max_edge_trim *= max(0.5, 1.0 - min(0.42, keep_energy * 0.16))
        if overlap_duration <= _SHORT_SUBTITLE_SPAN_SEC:
            pad_before += _SHORT_SUBTITLE_PAD_BEFORE_BONUS_SEC
            pad_after += _SHORT_SUBTITLE_PAD_AFTER_BONUS_SEC
        first_overlap = min(overlaps, key=lambda item: float(item.get("start_time", 0.0) or 0.0))
        last_overlap = max(overlaps, key=lambda item: float(item.get("end_time", 0.0) or 0.0))
        if _looks_like_continuation_head(_semantic_subtitle_text(first_overlap)):
            pad_before += _KEEP_CONTINUATION_PAD_BEFORE_BONUS_SEC
        if _looks_like_incomplete_tail(_semantic_subtitle_text(last_overlap)):
            pad_after += _KEEP_INCOMPLETE_PAD_AFTER_BONUS_SEC

        short_keep_audio_safe_sec = float(trim_profile["short_keep_audio_safe_sec"]) + min(0.55, keep_energy * 0.24)
        if seg_duration <= short_keep_audio_safe_sec:
            refined.append(segment)
            continue

        desired_start = max(segment.start, overlap_start - pad_before)
        desired_end = min(segment.end, overlap_end + pad_after)
        trimmed_start = segment.start + min(max(0.0, desired_start - segment.start), max_edge_trim)
        trimmed_end = segment.end - min(max(0.0, segment.end - desired_end), max_edge_trim)
        if trimmed_end <= trimmed_start + 0.08:
            trimmed_start = segment.start
            trimmed_end = segment.end

        if trimmed_start - segment.start >= 0.08:
            refined.append(EditSegment(start=segment.start, end=trimmed_start, type="remove", reason="timing_trim"))
        refined.append(EditSegment(start=trimmed_start, end=trimmed_end, type="keep"))
        if segment.end - trimmed_end >= 0.08:
            refined.append(EditSegment(start=trimmed_end, end=segment.end, type="remove", reason="timing_trim"))

    refined = _merge_adjacent_segments(refined)
    collapsed: list[EditSegment] = []
    for index, segment in enumerate(refined):
        if segment.type != "keep":
            collapsed.append(segment)
            continue
        seg_duration = max(0.0, segment.end - segment.start)
        overlaps = _overlapping_subtitle_items(segment.start, segment.end, subtitle_items)
        max_signal = max(
            (_subtitle_signal_score(_semantic_subtitle_text(item), content_profile=content_profile) for item in overlaps),
            default=0.0,
        )
        keep_energy = _resolve_keep_energy_for_segment(
            segment,
            overlaps=overlaps,
            timeline_analysis=timeline_analysis,
            content_profile=content_profile,
        )
        surrounded_by_removes = (
            index > 0
            and index < len(refined) - 1
            and refined[index - 1].type == "remove"
            and refined[index + 1].type == "remove"
        )
        trim_profile = _resolve_trim_profile_for_segment(segment, timeline_analysis=timeline_analysis)
        if (
            surrounded_by_removes
            and seg_duration <= float(trim_profile["micro_keep_bridge_max_sec"])
            and max_signal < _STRONG_SUBTITLE_SIGNAL_SCORE
            and keep_energy < 0.82
            and not _range_has_protected_speech_evidence(
                segment.start,
                segment.end,
                subtitle_items=subtitle_items,
                transcript_segments=transcript_segments,
                content_profile=content_profile,
            )
            and not any(
                _has_normal_language_signal(_semantic_subtitle_text(item), content_profile=content_profile)
                for item in overlaps
            )
        ):
            collapsed.append(EditSegment(start=segment.start, end=segment.end, type="remove", reason="micro_keep_bridge"))
            continue
        collapsed.append(segment)

    merged = _merge_adjacent_segments(collapsed)
    if merged and merged[0].start > 0:
        merged.insert(0, EditSegment(start=0.0, end=merged[0].start, type="remove", reason="gap_fill"))
    if merged and merged[-1].end < duration:
        merged.append(EditSegment(start=merged[-1].end, end=duration, type="remove", reason="gap_fill"))
    return _merge_adjacent_segments(merged)


def _resolve_keep_energy_for_segment(
    segment: EditSegment,
    *,
    overlaps: list[dict[str, Any]],
    timeline_analysis: dict[str, Any] | None = None,
    content_profile: dict | None = None,
) -> float:
    energy = 0.0
    midpoint = segment.start + max(0.0, segment.end - segment.start) * 0.5
    trim_intensity = "balanced"
    max_signal = max(
        (_subtitle_signal_score(_semantic_subtitle_text(item), content_profile=content_profile) for item in overlaps),
        default=0.0,
    )
    if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE:
        energy += 0.82 + min(0.42, (max_signal - _STRONG_SUBTITLE_SIGNAL_SCORE) * 0.22)
    elif max_signal >= 1.0:
        energy += 0.34 + min(0.22, (max_signal - 1.0) * 0.18)
    elif overlaps:
        energy += 0.12

    emphasis_candidates = list((timeline_analysis or {}).get("emphasis_candidates") or [])
    for candidate in emphasis_candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_start = float(candidate.get("start_time", 0.0) or 0.0)
        if abs(candidate_start - midpoint) <= 0.65:
            energy += 0.24
            break

    for action in list((timeline_analysis or {}).get("section_actions") or []):
        if not isinstance(action, dict):
            continue
        start_sec = float(action.get("start_sec", 0.0) or 0.0)
        end_sec = float(action.get("end_sec", start_sec) or start_sec)
        if not (start_sec - 1e-6 <= midpoint <= end_sec + 1e-6):
            continue
        role = str(action.get("role") or "").strip().lower()
        packaging_intent = str(action.get("packaging_intent") or "").strip().lower()
        trim_intensity = str(action.get("trim_intensity") or "balanced")
        energy += {
            "hook": 0.38,
            "detail": 0.24,
            "body": 0.12,
            "cta": 0.16,
        }.get(role, 0.0)
        energy += min(0.22, max(0.0, float(action.get("transition_boost", 0.0) or 0.0)) * 0.28)
        if packaging_intent in {"hook_focus", "detail_support"}:
            energy += 0.12
        elif packaging_intent == "cta_protect":
            energy += 0.08
        focus_bonus = float(((timeline_analysis or {}).get("editing_skill") or {}).get("focus_keep_energy_bonus", {}).get(role, 0.0) or 0.0)
        if focus_bonus > 0:
            energy += focus_bonus
        break

    multimodal_signal = _summarize_multimodal_signal_for_range(
        segment.start,
        segment.end,
        multimodal_segment_hints=(timeline_analysis or {}).get("multimodal_segment_hints"),
    )
    positive_multimodal = float(multimodal_signal.get("positive_score", 0.0) or 0.0)
    negative_multimodal = float(multimodal_signal.get("negative_score", 0.0) or 0.0)
    if positive_multimodal > 0.0:
        energy += min(0.42, positive_multimodal * 0.22)
    if negative_multimodal > 0.0:
        energy -= min(0.48, negative_multimodal * 0.28)

    energy *= {
        "tight": 0.52,
        "balanced": 1.0,
        "preserve": 1.18,
    }.get(trim_intensity, 1.0)
    return max(0.0, min(2.4, energy))


def _review_focus_boundary_penalty(
    silence: SilenceSegment,
    *,
    timeline_analysis: dict[str, Any] | None,
    editing_skill: dict[str, Any] | None,
) -> tuple[float, str]:
    focus_cut_guard = dict((editing_skill or {}).get("focus_cut_guard") or {})
    if not focus_cut_guard:
        return 0.0, ""
    midpoint = silence.start + max(0.0, silence.end - silence.start) * 0.5
    action = _section_action_for_time(midpoint, timeline_analysis=timeline_analysis)
    role = str((action or {}).get("role") or "").strip().lower()
    if not role:
        return 0.0, ""
    penalty = float(focus_cut_guard.get(role, 0.0) or 0.0)
    if penalty <= 0:
        return 0.0, ""
    return penalty, f"review_focus_{role}_guard"


def _build_keep_energy_segments_analysis(
    segments: list[EditSegment],
    *,
    subtitle_items: list[dict[str, Any]],
    timeline_analysis: dict[str, Any] | None = None,
    content_profile: dict | None = None,
) -> list[dict[str, Any]]:
    analysis: list[dict[str, Any]] = []
    for segment in segments:
        if segment.type != "keep":
            continue
        overlaps = _overlapping_subtitle_items(segment.start, segment.end, subtitle_items)
        if not overlaps:
            continue
        midpoint = segment.start + max(0.0, segment.end - segment.start) * 0.5
        keep_energy = _resolve_keep_energy_for_segment(
            segment,
            overlaps=overlaps,
            timeline_analysis=timeline_analysis,
            content_profile=content_profile,
        )
        section_action = _section_action_for_time(midpoint, timeline_analysis=timeline_analysis)
        max_signal = max(
            (_subtitle_signal_score(_semantic_subtitle_text(item), content_profile=content_profile) for item in overlaps),
            default=0.0,
        )
        emphasis_count = sum(
            1
            for candidate in list((timeline_analysis or {}).get("emphasis_candidates") or [])
            if isinstance(candidate, dict) and abs(float(candidate.get("start_time", 0.0) or 0.0) - midpoint) <= 0.65
        )
        analysis.append(
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "duration_sec": round(max(0.0, segment.end - segment.start), 3),
                "keep_energy": round(keep_energy, 3),
                "max_signal": round(max_signal, 3),
                "subtitle_count": len(overlaps),
                "section_role": str((section_action or {}).get("role") or ""),
                "trim_intensity": str((section_action or {}).get("trim_intensity") or "balanced"),
                "packaging_intent": str((section_action or {}).get("packaging_intent") or ""),
                "emphasis_hits": emphasis_count,
                "multimodal_roles": list(((section_action or {}).get("multimodal_roles") or []))[:4],
                "multimodal_keep_priority": str((section_action or {}).get("multimodal_keep_priority") or ""),
                "multimodal_signal": round(float((section_action or {}).get("multimodal_signal", 0.0) or 0.0), 3),
            }
        )
    return analysis


def _annotate_cut_candidates_with_keep_energy(
    candidates: list[CutCandidate],
    *,
    keep_energy_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for candidate in candidates:
        payload = candidate.to_dict()
        previous_keep = None
        next_keep = None
        for segment in keep_energy_segments:
            seg_end = float(segment.get("end", 0.0) or 0.0)
            seg_start = float(segment.get("start", 0.0) or 0.0)
            if seg_end <= candidate.start + 1e-6:
                previous_keep = segment
                continue
            if seg_start >= candidate.end - 1e-6:
                next_keep = segment
                break
        if previous_keep is not None:
            payload["left_keep_energy"] = round(float(previous_keep.get("keep_energy", 0.0) or 0.0), 3)
            payload["left_keep_role"] = str(previous_keep.get("section_role") or "")
        if next_keep is not None:
            payload["right_keep_energy"] = round(float(next_keep.get("keep_energy", 0.0) or 0.0), 3)
            payload["right_keep_role"] = str(next_keep.get("section_role") or "")
        payload["boundary_keep_energy"] = round(
            max(
                float((previous_keep or {}).get("keep_energy", 0.0) or 0.0),
                float((next_keep or {}).get("keep_energy", 0.0) or 0.0),
            ),
            3,
        )
        annotated.append(payload)
    return annotated


def _summarize_cut_evidence(accepted_cuts: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_items = [
        dict(item.get("evidence") or {})
        for item in accepted_cuts
        if isinstance(item, dict) and isinstance(item.get("evidence"), dict)
    ]
    if not evidence_items:
        return {
            "evidence_cut_count": 0,
            "protected_visual_cut_count": 0,
            "high_removal_evidence_count": 0,
            "high_protection_evidence_count": 0,
            "top_tags": [],
        }
    tag_counts: dict[str, int] = {}
    for evidence in evidence_items:
        for tag in evidence.get("tags") or []:
            label = str(tag or "").strip()
            if label:
                tag_counts[label] = tag_counts.get(label, 0) + 1
    return {
        "evidence_cut_count": len(evidence_items),
        "protected_visual_cut_count": sum(
            1
            for evidence in evidence_items
            if float(evidence.get("visual_showcase_score", 0.0) or 0.0) >= 0.74
        ),
        "high_removal_evidence_count": sum(
            1
            for evidence in evidence_items
            if float(evidence.get("removal_score", 0.0) or 0.0) >= 0.72
        ),
        "high_protection_evidence_count": sum(
            1
            for evidence in evidence_items
            if float(evidence.get("protection_score", 0.0) or 0.0) >= 0.72
        ),
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ],
    }


def _summarize_keep_energy_segments(keep_energy_segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not keep_energy_segments:
        return {
            "count": 0,
            "high_energy_count": 0,
            "max_keep_energy": 0.0,
            "avg_keep_energy": 0.0,
        }
    energies = [float(segment.get("keep_energy", 0.0) or 0.0) for segment in keep_energy_segments]
    return {
        "count": len(keep_energy_segments),
        "high_energy_count": sum(1 for energy in energies if energy >= 1.0),
        "max_keep_energy": round(max(energies), 3),
        "avg_keep_energy": round(sum(energies) / len(energies), 3),
    }


def _section_action_for_time(
    time_sec: float,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for action in list((timeline_analysis or {}).get("section_actions") or []):
        if not isinstance(action, dict):
            continue
        start_sec = float(action.get("start_sec", 0.0) or 0.0)
        end_sec = float(action.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return action
    return None


def _contextual_section_action_for_range(
    start_time: float,
    end_time: float,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    midpoint = start_time + max(0.0, end_time - start_time) * 0.5
    direct = _section_action_for_time(midpoint, timeline_analysis=timeline_analysis)
    if direct is not None:
        return direct

    touching: list[tuple[int, float, float, dict[str, Any]]] = []
    for action in list((timeline_analysis or {}).get("section_actions") or []):
        if not isinstance(action, dict):
            continue
        action_start = float(action.get("start_sec", 0.0) or 0.0)
        action_end = float(action.get("end_sec", action_start) or action_start)
        boundary_distance = min(abs(action_end - start_time), abs(action_start - end_time))
        if boundary_distance > 0.18:
            continue
        touching.append(
            (
                0 if bool(action.get("broll_allowed")) else 1,
                boundary_distance,
                abs(midpoint - (action_start + action_end) * 0.5),
                action,
            )
        )
    if not touching:
        return None
    touching.sort(key=lambda item: (item[0], item[1], item[2]))
    return touching[0][3]


def _resolve_trim_profile_for_segment(
    segment: EditSegment,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, float]:
    trim_intensity = "balanced"
    midpoint = segment.start + max(0.0, segment.end - segment.start) * 0.5
    for action in list((timeline_analysis or {}).get("section_actions") or []):
        if not isinstance(action, dict):
            continue
        start_sec = float(action.get("start_sec", 0.0) or 0.0)
        end_sec = float(action.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= midpoint <= end_sec + 1e-6:
            trim_intensity = str(action.get("trim_intensity") or "balanced")
            break
    return dict(_TRIM_INTENSITY_PROFILES.get(trim_intensity, _TRIM_INTENSITY_PROFILES["balanced"]))


def _merge_adjacent_segments(segments: list[EditSegment]) -> list[EditSegment]:
    ordered = sorted(
        (segment for segment in segments if segment.end > segment.start),
        key=lambda segment: (segment.start, segment.end),
    )
    merged: list[EditSegment] = []
    for segment in ordered:
        if not merged:
            merged.append(segment)
            continue
        previous = merged[-1]
        same_type = previous.type == segment.type
        touching = segment.start <= previous.end + 1e-6
        if same_type and touching:
            merged[-1] = EditSegment(
                start=previous.start,
                end=max(previous.end, segment.end),
                type=previous.type,
                reason=previous.reason or segment.reason,
            )
            continue
        merged.append(segment)
    return merged


def _overlapping_subtitle_items(start_time: float, end_time: float, subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in subtitle_items:
        item_start = float(item.get("start_time", 0.0) or 0.0)
        item_end = float(item.get("end_time", 0.0) or 0.0)
        if min(end_time, item_end) - max(start_time, item_start) > 0.0:
            overlaps.append(item)
    return overlaps


def _overlapping_transcript_segments(start_time: float, end_time: float, transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in transcript_segments:
        item_start = float(item.get("start", 0.0) or 0.0)
        item_end = float(item.get("end", 0.0) or 0.0)
        if min(end_time, item_end) - max(start_time, item_start) > 0.0:
            overlaps.append(item)
    return overlaps


def _range_has_protected_speech_evidence(
    start_time: float,
    end_time: float,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
) -> bool:
    for item in _overlapping_subtitle_items(start_time, end_time, subtitle_items):
        if not _subtitle_overlap_has_protected_text_coverage(item, start_time=start_time, end_time=end_time):
            continue
        if _subtitle_has_protected_speech_text(_semantic_subtitle_text(item), content_profile=content_profile):
            return True
    for segment in _overlapping_transcript_segments(start_time, end_time, transcript_segments):
        if _transcript_segment_has_protected_speech(segment, start_time=start_time, end_time=end_time, content_profile=content_profile):
            return True
    return False


def _range_has_protected_subtitle_text_overlap(
    start_time: float,
    end_time: float,
    *,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict | None,
) -> bool:
    for item in _overlapping_subtitle_items(start_time, end_time, subtitle_items):
        if not _subtitle_overlap_has_protected_text_coverage(item, start_time=start_time, end_time=end_time):
            continue
        if _subtitle_has_protected_speech_text(_semantic_subtitle_text(item), content_profile=content_profile):
            return True
    return False


def _subtitle_overlap_has_protected_text_coverage(
    item: dict[str, Any],
    *,
    start_time: float,
    end_time: float,
) -> bool:
    try:
        item_start = float(item.get("start_time", 0.0) or 0.0)
        item_end = float(item.get("end_time", item_start) or item_start)
    except (TypeError, ValueError):
        return False
    item_duration = max(0.0, item_end - item_start)
    if item_duration > _SUBTITLE_TEXT_SILENCE_PROTECTION_MAX_SEC:
        return False
    overlap = min(end_time, item_end) - max(start_time, item_start)
    if overlap <= 0.001:
        return False
    coverage = overlap / max(0.001, item_duration)
    return coverage >= _SUBTITLE_TEXT_SILENCE_PROTECTION_MIN_COVERAGE or overlap >= item_duration - 0.08


def _subtitle_has_protected_speech_text(text: str, *, content_profile: dict | None) -> bool:
    compact = _compact_subtitle_text(text)
    if len(compact) < 3:
        return False
    if _subtitle_text_is_explicit_removal(compact, content_profile=content_profile):
        return False
    return True


def _subtitle_text_is_explicit_removal(text: str, *, content_profile: dict | None) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return True
    filler_stripped = _compact_subtitle_text(FILLER_PATTERN.sub("", compact))
    if not filler_stripped:
        return True
    if _looks_like_noise_subtitle(compact):
        return True
    if _is_restart_cue_text(compact):
        return True
    if _is_nonsemantic_repetition_text(compact, content_profile=content_profile):
        return True
    return False


def _transcript_segment_has_protected_speech(
    segment: dict[str, Any],
    *,
    start_time: float,
    end_time: float,
    content_profile: dict | None,
) -> bool:
    has_trusted_word_timing = False
    for word in list(segment.get("words") or []):
        word_text = str(word.get("word") or word.get("raw_text") or "").strip()
        if not word_text:
            continue
        if _transcript_word_timing_is_trusted(word):
            has_trusted_word_timing = True
        if _range_overlap_seconds(start_time, end_time, word.get("start"), word.get("end")) <= 0.0:
            continue
        if _subtitle_has_protected_speech_text(word_text, content_profile=content_profile):
            return True
    if has_trusted_word_timing:
        return False
    text = str(segment.get("text") or "").strip()
    return _subtitle_has_protected_speech_text(text, content_profile=content_profile)


def _range_has_synthetic_transcript_word_overlap(
    start_time: float,
    end_time: float,
    *,
    transcript_segments: list[dict[str, Any]],
) -> bool:
    return _range_has_transcript_word_overlap(
        start_time,
        end_time,
        transcript_segments=transcript_segments,
        trusted=False,
    )


def _range_has_trusted_transcript_word_overlap(
    start_time: float,
    end_time: float,
    *,
    transcript_segments: list[dict[str, Any]],
) -> bool:
    return _range_has_transcript_word_overlap(
        start_time,
        end_time,
        transcript_segments=transcript_segments,
        trusted=True,
    )


def _range_has_transcript_word_overlap(
    start_time: float,
    end_time: float,
    *,
    transcript_segments: list[dict[str, Any]],
    trusted: bool,
) -> bool:
    for segment in _overlapping_transcript_segments(start_time, end_time, transcript_segments):
        for word in list(segment.get("words") or []):
            if _range_overlap_seconds(start_time, end_time, word.get("start"), word.get("end")) <= 0.0:
                continue
            if _transcript_word_timing_is_trusted(word) == trusted:
                return True
    return False


def _transcript_word_timing_is_trusted(word: dict[str, Any]) -> bool:
    start = _optional_float(word.get("start"))
    end = _optional_float(word.get("end"))
    if start is None or end is None or end <= start:
        return False
    return _transcript_word_alignment_source(word) not in _SYNTHETIC_WORD_ALIGNMENT_SOURCES


def _transcript_word_alignment_source(word: dict[str, Any]) -> str:
    alignment = word.get("alignment")
    if isinstance(alignment, dict):
        source = str(alignment.get("source") or "").strip().lower()
        if source:
            return source
        roughcut = alignment.get("_roughcut")
        if isinstance(roughcut, dict):
            source = str(roughcut.get("source") or "").strip().lower()
            if source:
                return source
    raw_payload = word.get("raw_payload")
    if isinstance(raw_payload, dict):
        for key in ("source", "_roughcut_source"):
            source = str(raw_payload.get(key) or "").strip().lower()
            if source:
                return source
    return ""


def _range_overlap_seconds(start_time: float, end_time: float, item_start: Any, item_end: Any) -> float:
    start = _as_float(item_start)
    end = _as_float(item_end, fallback=start)
    return max(0.0, min(float(end_time), end) - max(float(start_time), start))


def _find_previous_subtitle(time_point: float, subtitle_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    previous: dict[str, Any] | None = None
    for item in subtitle_items:
        if float(item.get("end_time", 0.0) or 0.0) <= time_point + 1e-6:
            previous = item
            continue
        break
    return previous


def _find_next_subtitle(time_point: float, subtitle_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in subtitle_items:
        if float(item.get("start_time", 0.0) or 0.0) >= time_point - 1e-6:
            return item
    return None


def _subtitle_text(item: dict) -> str:
    return subtitle_semantic_preview_text(item)


def _semantic_subtitle_text(item: dict[str, Any] | None) -> str:
    return subtitle_semantic_preview_text(item)


def _looks_like_incomplete_tail(text: str) -> bool:
    raw = str(text or "").strip()
    compact = _compact_subtitle_text(raw)
    if len(compact) < _RETAKE_MIN_PREFIX_LEN:
        return False
    if raw and raw[-1] in _TERMINAL_PUNCTUATION_CHARS:
        return False
    if any(compact.endswith(token) for token in _INCOMPLETE_TAIL_SUFFIXES):
        return True
    return len(compact) <= 10 and compact[-1] in {"的", "了", "是", "在", "把", "跟", "和", "给", "就", "又", "更", "最", "很"}


def _looks_like_continuation_head(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    return any(compact.startswith(prefix) for prefix in _CONTINUATION_HEAD_PREFIXES)


def _looks_like_sentence_continuation(
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
) -> bool:
    if previous_item is None or next_item is None:
        return False
    previous_text = _semantic_subtitle_text(previous_item)
    next_text = _semantic_subtitle_text(next_item)
    if _looks_like_incomplete_tail(previous_text):
        return True
    if _looks_like_continuation_head(next_text):
        return True
    compact_previous = _compact_subtitle_text(previous_text)
    compact_next = _compact_subtitle_text(next_text)
    return bool(
        compact_previous
        and compact_next
        and compact_previous[-1] not in _TERMINAL_PUNCTUATION_CHARS
        and compact_next[:1] in {"而", "但", "并", "就", "也"}
    )


def _looks_like_semantic_bridge(
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    *,
    content_profile: dict | None,
) -> bool:
    if previous_item is None or next_item is None:
        return False
    previous_text = _semantic_subtitle_text(previous_item)
    next_text = _semantic_subtitle_text(next_item)
    return (
        _subtitle_signal_score(previous_text, content_profile=content_profile) >= _STRONG_SUBTITLE_SIGNAL_SCORE
        and _subtitle_signal_score(next_text, content_profile=content_profile) >= _STRONG_SUBTITLE_SIGNAL_SCORE
    )


def _collect_restart_retake_cuts(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[tuple[float, float, str]]:
    ordered = sorted(
        subtitle_items,
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
        ),
    )
    cuts: list[tuple[float, float, str]] = []
    for start_index, item in enumerate(ordered):
        fragment_text = _semantic_subtitle_text(item)
        fragment_compact = _compact_subtitle_text(fragment_text)
        if (
            len(fragment_compact) < _RETAKE_MIN_PREFIX_LEN
            or len(fragment_compact) > _RETAKE_MAX_FRAGMENT_CHARS
            or _is_restart_cue_text(fragment_text)
        ):
            continue
        fragment_start = float(item.get("start_time", 0.0) or 0.0)
        fragment_end = float(item.get("end_time", 0.0) or 0.0)
        lookahead_stop = min(len(ordered), start_index + _RETAKE_MAX_WINDOW_ITEMS + 1)
        for next_index in range(start_index + 1, lookahead_stop):
            next_item = ordered[next_index]
            next_start = float(next_item.get("start_time", 0.0) or 0.0)
            if next_start - fragment_end > _RETAKE_MAX_GAP_SEC:
                break
            next_text = _semantic_subtitle_text(next_item)
            next_compact = _strip_restart_prefix(_compact_subtitle_text(next_text))
            if not _looks_like_retake_match(fragment_compact, next_compact):
                continue
            if not _window_has_restart_cue(ordered, start_index=start_index, next_index=next_index):
                continue
            if not _retake_window_is_disposable(
                ordered,
                start_index=start_index,
                next_index=next_index,
                content_profile=content_profile,
            ):
                continue
            if next_start - fragment_start >= 0.18:
                cuts.append((fragment_start, next_start, "restart_retake"))
            break
    return cuts


def _collect_restart_cue_cuts(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[tuple[float, float, str]]:
    ordered = sorted(
        subtitle_items,
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
        ),
    )
    cuts: list[tuple[float, float, str]] = []
    for index, item in enumerate(ordered):
        text = _semantic_subtitle_text(item)
        if not _is_disposable_restart_cue_text(text, content_profile=content_profile):
            continue
        start = float(item.get("start_time", 0.0) or 0.0)
        end = float(item.get("end_time", 0.0) or 0.0)
        previous_item = ordered[index - 1] if index > 0 else None
        if previous_item is not None:
            previous_end = float(previous_item.get("end_time", 0.0) or 0.0)
            if (
                start - previous_end <= 0.72
                and (
                    _looks_like_incomplete_tail(_semantic_subtitle_text(previous_item))
                    or _is_low_signal_subtitle_text(
                        _semantic_subtitle_text(previous_item),
                        content_profile=content_profile,
                    )
                )
            ):
                start = float(previous_item.get("start_time", start) or start)
        if end - start >= 0.08:
            cuts.append((start, end, "restart_cue"))
    return cuts


def _collect_rollback_instruction_cuts(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[CutCandidate]:
    ordered = sorted(
        subtitle_items,
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
        ),
    )
    candidates: list[CutCandidate] = []
    for index, item in enumerate(ordered):
        cue_text = _semantic_subtitle_text(item)
        if not _is_rollback_instruction_text(cue_text):
            continue
        cue_start = float(item.get("start_time", 0.0) or 0.0)
        if cue_start <= 0.0:
            continue
        window = _rollback_instruction_lookback_window(ordered, cue_index=index, cue_start=cue_start)
        if not window:
            continue
        start = float(window[0].get("start_time", 0.0) or 0.0)
        end = cue_start
        if end - start < _ROLLBACK_MIN_CUT_SEC:
            continue
        previous_text = _semantic_subtitle_text(window[-1])
        next_item = ordered[index + 1] if index + 1 < len(ordered) else None
        signals = ["hard_rule", "spoken_editorial_rollback"]
        if _is_rollback_asr_variant_text(cue_text):
            signals.append("asr_variant:减6")
        candidates.append(
            CutCandidate(
                start=max(0.0, start),
                end=max(start, end),
                reason="rollback_instruction",
                score=1.0,
                hard=True,
                signals=signals,
                evidence={
                    "instruction_text": cue_text[:64],
                    "previous_text": previous_text[:64],
                    "next_text": _semantic_subtitle_text(next_item)[:64] if next_item is not None else "",
                    "subtitle_count": len(window),
                    "duration_sec": round(max(0.0, end - start), 3),
                    "tags": ["rollback_instruction", "spoken_edit_note"],
                },
            )
        )
    return candidates


def _rollback_instruction_lookback_window(
    ordered: list[dict],
    *,
    cue_index: int,
    cue_start: float,
) -> list[dict]:
    window: list[dict] = []
    boundary = max(0.0, cue_start - _ROLLBACK_LOOKBACK_MAX_SEC)
    next_start = cue_start
    for item in reversed(ordered[:cue_index]):
        item_start = float(item.get("start_time", 0.0) or 0.0)
        item_end = float(item.get("end_time", item_start) or item_start)
        if item_end < boundary:
            break
        if next_start - item_end > _ROLLBACK_LOOKBACK_MAX_GAP_SEC and window:
            break
        window.append(item)
        next_start = item_start
    window.reverse()
    return window


def _is_rollback_instruction_text(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if any(term in compact for term in _ROLLBACK_INSTRUCTION_TERMS):
        return True
    if (
        any(reference in compact for reference in _ROLLBACK_REFERENCE_TERMS)
        and any(delete_term in compact for delete_term in _ROLLBACK_DELETE_TERMS)
    ):
        return True
    return _is_rollback_asr_variant_text(compact)


def _is_rollback_asr_variant_text(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    return bool(_ROLLBACK_ASR_VARIANT_RE.search(compact))


def _looks_like_retake_match(fragment_compact: str, next_compact: str) -> bool:
    if not fragment_compact or not next_compact:
        return False
    if len(next_compact) < len(fragment_compact) + 3:
        return False
    prefix_len = 0
    for left, right in zip(fragment_compact, next_compact):
        if left != right:
            break
        prefix_len += 1
    return prefix_len >= min(len(fragment_compact), 8) and prefix_len >= _RETAKE_MIN_PREFIX_LEN


def _strip_restart_prefix(compact_text: str) -> str:
    stripped = str(compact_text or "")
    previous = None
    while stripped and stripped != previous:
        previous = stripped
        for prefix in _RESTART_PREFIX_TERMS:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
    return stripped


def _window_has_restart_cue(
    ordered: list[dict],
    *,
    start_index: int,
    next_index: int,
) -> bool:
    for item in ordered[start_index:next_index + 1]:
        if _is_restart_cue_text(_semantic_subtitle_text(item)):
            return True
    return False


def _retake_window_is_disposable(
    ordered: list[dict],
    *,
    start_index: int,
    next_index: int,
    content_profile: dict | None,
) -> bool:
    if next_index <= start_index + 1:
        return True
    saw_restart_cue = False
    for middle_item in ordered[start_index + 1:next_index]:
        middle_text = _semantic_subtitle_text(middle_item)
        if _is_restart_cue_text(middle_text):
            saw_restart_cue = True
            continue
        if _is_low_signal_subtitle_text(middle_text, content_profile=content_profile):
            continue
        return False
    return saw_restart_cue


def _is_restart_cue_text(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if compact in _RESTART_SHORT_CUES:
        return True
    if any(term in compact for term in _RESTART_CUE_TERMS if len(term) > 1):
        return True
    return False


def _is_disposable_restart_cue_text(text: str, *, content_profile: dict | None) -> bool:
    compact = _compact_subtitle_text(text)
    if not _is_restart_cue_text(compact):
        return False
    if compact in _RESTART_SHORT_CUES:
        return True
    if len(compact) <= 18:
        return True
    return not _has_normal_language_signal(compact, content_profile=content_profile)


def _is_visual_showcase_gap(
    *,
    start_time: float,
    end_time: float,
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None,
    scene_points: list[float],
) -> bool:
    duration = max(0.0, end_time - start_time)
    if duration < _VISUAL_SHOWCASE_GAP_MIN_SEC or duration > _VISUAL_SHOWCASE_GAP_MAX_SEC:
        return False
    action = _contextual_section_action_for_range(start_time, end_time, timeline_analysis=timeline_analysis)
    if not bool((action or {}).get("broll_allowed")):
        return False
    context_gap = (
        _SHOWCASE_CONTEXT_APPRECIATION_MAX_GAP_SEC
        if duration >= _VISUAL_SHOWCASE_LONG_GAP_MIN_SEC
        else _SHOWCASE_CONTEXT_MAX_GAP_SEC
    )
    close_prev = previous_item is not None and start_time - float(previous_item.get("end_time", 0.0) or 0.0) <= context_gap
    close_next = next_item is not None and float(next_item.get("start_time", 0.0) or 0.0) - end_time <= context_gap
    if not (close_prev or close_next):
        return False
    context_texts = [_semantic_subtitle_text(item) for item in (previous_item, next_item) if item is not None]
    if not any(_has_visual_showcase_signal(text, content_profile=content_profile) for text in context_texts):
        return False
    scene_hits = sum(1 for point in scene_points if start_time - 0.12 <= point <= end_time + 0.12)
    role = str((action or {}).get("role") or "").strip().lower()
    if duration >= _VISUAL_SHOWCASE_LONG_GAP_MIN_SEC:
        return scene_hits >= 1 or (close_prev and close_next and role == "detail")
    return scene_hits >= 1 or (close_prev and close_next and role in {"detail", "body"})


def _should_remove_long_non_dialogue_keep(
    segment: EditSegment,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None,
    scene_points: list[float],
) -> bool:
    if not transcript_segments:
        return False
    if max(0.0, segment.end - segment.start) < _LONG_INVALID_NO_DIALOGUE_MIN_SEC:
        return False
    previous_item = _find_previous_subtitle(segment.start, subtitle_items)
    next_item = _find_next_subtitle(segment.end, subtitle_items)
    if _looks_like_sentence_continuation(previous_item, next_item):
        return False
    range_evidence = _build_range_evidence(
        segment.start,
        segment.end,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
        content_profile=content_profile,
        timeline_analysis=timeline_analysis,
        scene_points=scene_points,
        previous_item=previous_item,
        next_item=next_item,
    )
    if range_evidence.protection_score >= 0.62:
        return False
    return range_evidence.removal_score >= 0.42


def _cut_reason_priority(reason: str) -> int:
    priorities = {
        "rollback_instruction": 5,
        "restart_retake": 5,
        "failed_attempt": 5,
        "off_topic_interruption": 5,
        "restart_cue": 4,
        "noise_subtitle": 4,
        "low_signal_subtitle": 4,
        "filler_word": 4,
        "repeated_speech": 4,
        "long_non_dialogue": 3,
        "timing_trim": 3,
        "silence": 2,
        "micro_keep": 1,
        "micro_keep_bridge": 1,
        "gap_fill": 0,
    }
    return priorities.get(str(reason or "").strip(), 0)


def _silence_confidence_penalty(
    silence: SilenceSegment,
    *,
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    transcript_segments: list[dict[str, Any]],
) -> float:
    candidates: list[float] = []
    for item in (previous_item, next_item):
        confidence = _optional_float((item or {}).get("avg_confidence"))
        if confidence is not None:
            candidates.append(confidence)
    nearby_segments = _overlapping_transcript_segments(
        max(0.0, silence.start - _TRANSCRIPT_EVIDENCE_WINDOW_SEC),
        silence.end + _TRANSCRIPT_EVIDENCE_WINDOW_SEC,
        transcript_segments,
    )
    for item in nearby_segments:
        confidence = _optional_float(item.get("confidence"))
        if confidence is not None:
            candidates.append(confidence)
    if not candidates:
        return 0.0
    average_confidence = _mean(candidates)
    if average_confidence is None:
        return 0.0
    if average_confidence < 0.55:
        return -0.18
    if average_confidence < 0.68:
        return -0.10
    return 0.0


def _snap_edge(
    edge: float,
    scene_points: list[float],
    *,
    tolerance: float,
    lower_bound: float,
    upper_bound: float,
) -> float | None:
    nearest: float | None = None
    nearest_distance = math.inf
    for point in scene_points:
        if point < lower_bound - 1e-6 or point > upper_bound + 1e-6:
            continue
        distance = abs(point - edge)
        if distance <= tolerance and distance < nearest_distance:
            nearest = point
            nearest_distance = distance
    return nearest


def _dominant_label(labels: list[str]) -> str | None:
    if not labels:
        return None
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return max(sorted(counts), key=lambda label: counts[label])


def _mean(values: list[float]) -> float | None:
    filtered = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def _as_float(value: Any, *, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

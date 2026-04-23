from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill
from roughcut.media.scene import SceneBoundary
from roughcut.media.silence import SilenceSegment


FILLER_WORDS = [
    "那个", "这个", "嗯", "啊", "呃", "就是说", "然后就", "对吧对吧",
    "就是那个", "这个嘛", "我觉得那个",
]

FILLER_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in sorted(FILLER_WORDS, key=len, reverse=True)) + r")",
    re.UNICODE,
)
HEDGE_PATTERN = re.compile(
    r"(其实|也算|算是|上是|当然|吧|一下|一点|更加|感觉|可能|好像|还是|就|都|也|会|这个|那个|的话)",
    re.UNICODE,
)
PUNCTUATION_PATTERN = re.compile(r"[，。！？!?、；;：:,.\-\s]+", re.UNICODE)
_EDC_CONFLICT_TERMS = ("摄影", "光线", "灯光", "灯具", "补光", "曝光", "色温")
_CAMERA_CONFLICT_TERMS = ("折刀", "开刃", "刀尖", "柄材", "背夹", "钢码")
_ANCHOR_KEYWORDS = (
    "开箱",
    "对比",
    "升级",
    "区别",
    "差异",
    "实测",
    "体验",
    "推荐",
    "参数",
    "尺寸",
    "重量",
    "亮度",
    "续航",
    "功率",
    "容量",
    "价格",
    "便携",
    "口感",
    "味道",
    "口气",
    "零糖",
    "益生菌",
    "含片",
    "弹射",
    "莱德曼",
)
_BRIDGE_OPENERS = (
    "你看",
    "比如",
    "比如说",
    "平时",
    "正常来说",
    "当你",
    "另外",
    "另外呢",
    "然后",
    "然后呢",
    "其实",
    "我们都知道",
)
_NUMERIC_SIGNAL_PATTERN = re.compile(r"\d", re.UNICODE)
_NON_WORD_PATTERN = re.compile(r"[，。！？!?、；;：:,.~\-—_\s\[\]【】()（）]+", re.UNICODE)
_NOISE_MARKER_TERMS = (
    "噪音",
    "杂音",
    "电流",
    "风声",
    "破音",
    "爆麦",
    "喷麦",
    "卡顿",
    "笑声",
    "掌声",
    "音乐",
    "咳嗽",
)
_NOISE_INTERJECTION_CHARS = frozenset("啊嗯呃哦哎诶欸哈呵咳")
_VISUAL_SHOWCASE_TERMS = (
    "欣赏",
    "看一下",
    "来看",
    "看这里",
    "放一起",
    "放在一起",
    "并排",
    "同框",
    "对比看",
    "尺寸对比",
    "左边",
    "右边",
    "近看",
    "特写",
    "展示",
    "演示",
    "操作",
    "实操",
    "实测",
    "看细节",
    "细节",
    "纹理",
    "材质",
    "质感",
    "效果",
    "成品",
    "画面",
    "实拍",
    "镜头",
    "镜面",
    "雾面",
    "上手看",
    "上手",
    "开合",
    "打开",
    "合上",
    "转动",
    "滚动",
    "滑动",
    "按一下",
    "试一下",
    "听一下",
    "展开看",
    "收纳",
    "收纳看",
)
_NORMAL_LANGUAGE_SIGNAL_TERMS = (
    "可以",
    "看到",
    "看一下",
    "来看",
    "这里",
    "这个",
    "那个",
    "就是",
    "因为",
    "所以",
    "但是",
    "如果",
    "然后",
    "感觉",
    "适合",
    "支持",
    "需要",
    "打开",
    "放在",
    "拿来",
    "对比",
    "区别",
)
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
_EMPHASIS_REPEAT_CUE_RE = re.compile(r"(?:说|讲|重复)(?:一|两|二|三|3|好多)遍")
_COUNTING_REPEAT_UNIT_RE = re.compile(r"^(?:第[\u4e00-\u9fff\d]{1,3}|[\u4e00-\u9fff\d]{1,3}个)$")
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
_SCENE_SNAP_TOLERANCE_SEC = 0.24
_MIN_CUT_DURATION_SEC = 0.08
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
    effective_min_silence_to_cut = max(0.12, float(resolved_skill.get("silence_floor_sec", min_silence_to_cut) or min_silence_to_cut))
    normalized_subtitles = _normalize_subtitle_items(subtitle_items or [])
    normalized_transcript = _normalize_transcript_segments(transcript_segments or [])
    enriched_subtitles = _enrich_subtitle_items_with_transcript_evidence(
        normalized_subtitles,
        normalized_transcript,
    )
    scene_points = _normalize_scene_points(scene_boundaries or [])

    candidates: list[CutCandidate] = []
    timeline_analysis = infer_timeline_analysis(
        enriched_subtitles,
        content_profile=content_profile,
        duration=duration,
        editing_skill=resolved_skill,
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
    if cut_fillers and enriched_subtitles:
        candidates.extend(
            _build_subtitle_cut_candidates(
                enriched_subtitles,
                content_profile=content_profile,
            )
        )
        candidates.extend(_build_hard_cut_candidates(
            [
                *_collect_restart_retake_cuts(enriched_subtitles, content_profile=content_profile),
                *_collect_restart_cue_cuts(enriched_subtitles, content_profile=content_profile),
            ]
        ))

    merged_cuts = _merge_cut_intervals(
        [(candidate.start, candidate.end, candidate.reason) for candidate in candidates]
    )
    segments = _build_segments_from_cuts(duration=duration, merged_cuts=merged_cuts)
    if subtitle_items is not None:
        segments = _refine_segments_for_pacing(
            segments,
            subtitle_items=enriched_subtitles,
            transcript_segments=normalized_transcript,
            content_profile=content_profile,
            duration=duration,
            timeline_analysis=timeline_analysis,
            scene_points=scene_points,
        )
    segments = _merge_adjacent_segments(segments)
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
                    "retake_cues",
                ],
                "principle": "cut only when removal evidence beats speech, visual showcase, and semantic continuity protection",
            },
            "candidate_count": len(candidates),
            "scene_boundary_count": len(scene_points),
            "transcript_segment_count": len(normalized_transcript),
            "effective_min_silence_to_cut": round(effective_min_silence_to_cut, 3),
            "review_focus": str(resolved_skill.get("review_focus") or ""),
            "accepted_cuts": accepted_cuts,
            "cut_evidence_summary": _summarize_cut_evidence(accepted_cuts),
            "keep_energy_segments": keep_energy_segments,
            "keep_energy_summary": _summarize_keep_energy_segments(keep_energy_segments),
            **timeline_analysis,
        },
    )


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
            "emphasis_candidates": [],
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
    hook_end_sec = 0.0
    for section in sections:
        if section["role"] == "hook":
            hook_end_sec = max(hook_end_sec, float(section["end_sec"]))
    if hook_end_sec <= 0.0:
        hook_end_sec = min(total_duration, float(normalized[min(1, len(normalized) - 1)].get("end_time", 0.0) or 0.0))

    cta_candidates = [section for section in sections if section["role"] == "cta"]
    cta_start_sec = float(cta_candidates[0]["start_sec"]) if cta_candidates else None

    emphasis_candidates = _build_emphasis_candidates(annotated)
    return {
        "hook_end_sec": round(hook_end_sec, 3),
        "cta_start_sec": round(cta_start_sec, 3) if cta_start_sec is not None else None,
        "semantic_sections": sections,
        "section_directives": _build_section_directives(sections, editing_skill=resolved_skill),
        "section_actions": _build_section_actions(sections, editing_skill=resolved_skill),
        "editing_skill": resolved_skill,
        "emphasis_candidates": emphasis_candidates,
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
        if silence.duration < min_silence_to_cut:
            continue
        candidate = _score_silence_cut(
            silence,
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

    protection_score = visual_score * 0.72 + language_score * 0.46
    if transcript_coverage >= 0.25:
        protection_score += 0.18
        tags.append("transcript_present")
    if section_role in {"hook", "cta"}:
        protection_score += 0.12
        tags.append(f"{section_role}_guard")

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
        tags=list(dict.fromkeys(tags)),
        previous_text=previous_text,
        next_text=next_text,
    )


def _build_subtitle_cut_candidates(
    subtitle_items: list[dict[str, Any]],
    *,
    content_profile: dict | None,
) -> list[CutCandidate]:
    candidates: list[CutCandidate] = []
    for item in subtitle_items:
        text = _semantic_subtitle_text(item)
        if FILLER_PATTERN.search(text):
            clean = PUNCTUATION_PATTERN.sub("", FILLER_PATTERN.sub("", text).strip())
            if not clean:
                candidates.append(
                    CutCandidate(
                        start=float(item["start_time"]),
                        end=float(item["end_time"]),
                        reason="filler_word",
                        hard=True,
                        signals=["pure_filler"],
                    )
                )
    return candidates


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
        directives.append(
            {
                "index": index,
                "role": role,
                "start_sec": round(float(section.get("start_sec") or 0.0), 3),
                "end_sec": round(float(section.get("end_sec") or 0.0), 3),
                "overlay_weight": overlay_weight,
                "music_entry_allowed": music_entry_allowed,
                "music_entry_bonus": round(float(policy.get("music_entry_bonus", 0.0) or 0.0), 3),
                "insert_allowed": insert_allowed,
                "insert_priority": round(float(policy.get("insert_priority", 0.0) or 0.0), 3),
                "creative_preferences": preference_labels,
                "creative_rationale": rationale,
            }
        )
    return directives


def _build_section_actions(
    sections: list[dict[str, Any]],
    *,
    editing_skill: dict[str, Any] | None = None,
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
        actions.append(
            {
                "index": index,
                "role": role,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": round(duration_sec, 3),
                "trim_intensity": str(policy.get("trim_intensity") or "balanced"),
                "packaging_intent": str(policy.get("packaging_intent") or f"{role}_support"),
                "transition_boost": round(float(policy.get("transition_boost", 0.0) or 0.0), 3),
                "transition_anchor_sec": start_sec,
                "broll_allowed": bool(policy.get("broll_allowed", False)),
                "broll_anchor_sec": round(start_sec + duration_sec * anchor_bias, 3),
                "action_priority": round(float(policy.get("insert_priority", 0.0) or 0.0), 3),
                "creative_preferences": preference_labels,
                "creative_rationale": rationale,
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
                "text_raw": str(item.get("text_raw") or ""),
                "text_norm": str(item.get("text_norm") or ""),
                "text_final": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""),
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
        for word in payload.get("words") or payload.get("words_json") or []:
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
        overlaps = _overlapping_transcript_segments(item["start_time"], item["end_time"], transcript_segments)
        confidence_values: list[float] = []
        logprob_values: list[float] = []
        speaker_labels: list[str] = []
        transcript_texts: list[str] = []
        has_alignment = False
        word_count = 0
        for segment in overlaps:
            segment_text = str(segment.get("text") or "").strip()
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
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")


def _semantic_subtitle_text(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    transcript_text = str(item.get("transcript_text") or "").strip()
    if transcript_text:
        return transcript_text
    transcript_texts = [str(text).strip() for text in (item.get("transcript_texts") or []) if str(text).strip()]
    if transcript_texts:
        return " ".join(transcript_texts).strip()
    return _subtitle_text(item)


def _compact_subtitle_text(text: str) -> str:
    return _NON_WORD_PATTERN.sub("", str(text or "").strip()).upper()


def _subtitle_signal_score(text: str, *, content_profile: dict | None) -> float:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return 0.0
    score = 0.0
    if _NUMERIC_SIGNAL_PATTERN.search(compact):
        score += 1.0
    if any(keyword in compact for keyword in _ANCHOR_KEYWORDS):
        score += 1.5
    if _has_visual_showcase_signal(compact, content_profile=content_profile):
        score += 1.1
    for token in _extract_subject_tokens(content_profile or {}):
        if token and token in compact.upper():
            score += 2.5
            break
    if len(compact) >= 10:
        score += 0.5
    if any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS):
        score -= 1.0
    if _is_low_signal_subtitle_text(compact, content_profile=content_profile):
        score -= 1.5
    return score


def _is_low_signal_subtitle_text(text: str, *, content_profile: dict | None = None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return True
    if "�" in compact:
        return True
    if _looks_like_noise_subtitle(compact):
        return True
    if _is_exact_natural_emphasis_repetition(compact):
        return False
    if len(compact) <= 2:
        return True
    if _has_normal_language_signal(compact, content_profile=content_profile):
        return False
    if (
        len(compact) <= 8
        and any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS)
        and not _has_anchor_signal(compact, content_profile=content_profile)
        and not _has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    repeated_chunk = re.search(r"(.{2,8})\1{1,}", compact)
    if (
        repeated_chunk
        and len(repeated_chunk.group(0)) >= max(4, int(len(compact) * 0.55))
        and not _looks_like_natural_emphasis_repetition(
            repeated_chunk.group(1),
            repeat_count=max(2, len(repeated_chunk.group(0)) // max(len(repeated_chunk.group(1)), 1)),
            full_text=compact,
        )
        and not _has_anchor_signal(compact, content_profile=content_profile)
        and not _has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    unique_chars = len(set(compact))
    if len(compact) >= 8 and unique_chars <= max(2, len(compact) // 5):
        return True
    repeated_token_match = re.fullmatch(r"(.{1,6})", compact)
    if (
        repeated_token_match
        and compact.count(repeated_token_match.group(1)) >= 3
        and not _looks_like_natural_emphasis_repetition(
            repeated_token_match.group(1),
            repeat_count=compact.count(repeated_token_match.group(1)),
            full_text=compact,
        )
    ):
        return True
    stripped_hedge = HEDGE_PATTERN.sub("", compact)
    if (
        len(compact) <= 12
        and len(stripped_hedge) <= 4
        and not re.search(r"[A-Za-z0-9]", stripped_hedge)
        and not _has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if (
        len(compact) <= 18
        and len(stripped_hedge) <= max(4, int(len(compact) * 0.38))
        and not _has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if (
        len(compact) <= 14
        and len(stripped_hedge) <= 5
        and not _has_anchor_signal(compact, content_profile=content_profile)
        and not _has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if _looks_like_subject_conflict_subtitle(compact, content_profile=content_profile):
        return True
    return False


def _looks_like_natural_emphasis_repetition(unit: str, *, repeat_count: int, full_text: str = "") -> bool:
    phrase = str(unit or "").strip()
    candidate = str(full_text or "").strip()
    if not phrase or repeat_count < 2:
        return False
    combined = candidate or phrase
    if _EMPHASIS_REPEAT_CUE_RE.search(combined):
        return True
    if repeat_count > 3:
        return False
    if candidate != phrase * repeat_count:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", phrase):
        return False
    if _COUNTING_REPEAT_UNIT_RE.fullmatch(phrase):
        return False
    return True


def _is_exact_natural_emphasis_repetition(text: str) -> bool:
    candidate = str(text or "").strip()
    if len(candidate) < 4:
        return False
    for unit_len in range(2, len(candidate) // 2 + 1):
        if len(candidate) % unit_len != 0:
            continue
        repeat_count = len(candidate) // unit_len
        unit = candidate[:unit_len]
        if unit * repeat_count != candidate:
            continue
        if _looks_like_natural_emphasis_repetition(unit, repeat_count=repeat_count, full_text=candidate):
            return True
    return False


def _has_visual_showcase_signal(text: str, *, content_profile: dict | None) -> bool:
    normalized = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not normalized:
        return False
    return any(term in normalized for term in _VISUAL_SHOWCASE_TERMS)


def _has_normal_language_signal(text: str, *, content_profile: dict | None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if len(compact) < 4:
        return False
    if _has_anchor_signal(compact, content_profile=content_profile):
        return True
    if _has_visual_showcase_signal(compact, content_profile=content_profile):
        return True
    if re.search(r"[A-Za-z0-9]", compact):
        return True
    if (
        len(compact) >= 6
        and len(set(compact)) >= 3
        and any(term in compact for term in _NORMAL_LANGUAGE_SIGNAL_TERMS)
    ):
        return True
    return len(compact) >= 10 and len(set(compact)) >= max(4, len(compact) // 4)


def _looks_like_noise_subtitle(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in _NOISE_MARKER_TERMS):
        return True
    if len(compact) <= 6 and set(compact) <= _NOISE_INTERJECTION_CHARS and len(compact) >= 3:
        return True
    if len(compact) <= 8 and re.fullmatch(r"([啊嗯呃哦哎诶欸哈呵咳])\1{2,}", compact):
        return True
    return False


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
        fragment_incomplete = _looks_like_incomplete_tail(fragment_text)
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
            if not (fragment_incomplete or _window_has_restart_cue(ordered, start_index=start_index, next_index=next_index)):
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


def _has_anchor_signal(text: str, *, content_profile: dict | None) -> bool:
    normalized = str(text or "")
    if _NUMERIC_SIGNAL_PATTERN.search(normalized):
        return True
    if any(keyword in normalized for keyword in _ANCHOR_KEYWORDS):
        return True
    subject_tokens = _extract_subject_tokens(content_profile or {})
    return any(token in normalized.upper() for token in subject_tokens)


def _looks_like_subject_conflict_subtitle(text: str, *, content_profile: dict | None) -> bool:
    profile = content_profile or {}
    family = _subject_family(str(profile.get("subject_type") or ""))
    if not family:
        return False
    conflict_terms: tuple[str, ...] = ()
    if family == "edc":
        conflict_terms = _EDC_CONFLICT_TERMS
    elif family == "camera":
        conflict_terms = _CAMERA_CONFLICT_TERMS
    if not conflict_terms:
        return False
    normalized = str(text or "")
    if not any(term in normalized for term in conflict_terms):
        return False
    subject_tokens = _extract_subject_tokens(profile)
    if subject_tokens and not any(token in normalized.upper() for token in subject_tokens):
        return False
    return len(normalized) <= 18


def _extract_subject_tokens(profile: dict) -> set[str]:
    tokens: set[str] = set()
    for key in ("subject_brand", "subject_model", "visible_text"):
        raw = str(profile.get(key) or "")
        for token in re.findall(r"[A-Za-z0-9-]{2,}", raw.upper()):
            tokens.add(token)
            tokens.add(token.replace("-", ""))
    return {token for token in tokens if token}


def _subject_family(subject_type: str) -> str:
    normalized = str(subject_type or "").strip()
    if not normalized:
        return ""
    if any(token in normalized for token in ("折刀", "工具钳", "战术", "EDC", "刀", "背夹", "柄材")):
        return "edc"
    if any(token in normalized for token in ("相机", "镜头", "摄影", "灯", "补光")):
        return "camera"
    return ""


def _cut_reason_priority(reason: str) -> int:
    priorities = {
        "restart_retake": 5,
        "restart_cue": 4,
        "noise_subtitle": 4,
        "low_signal_subtitle": 4,
        "filler_word": 4,
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

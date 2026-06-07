from __future__ import annotations

import re
from typing import Any

from roughcut.edit.low_signal_text import (
    compact_subtitle_text,
    low_signal_subtitle_is_contextually_isolated,
    subtitle_signal_score,
)
from roughcut.edit.smart_cut_rules import normalize_smart_cut_rules_payload
from roughcut.review.video_understanding import normalize_video_understanding_segment_hints


_TERM_SPLIT_PATTERN = re.compile(r"[,，、;；\s]+")
_BOUNDARY_CHARS = set(" \t\r\n,，、.。!?！？；;：:\"'“”‘’()（）[]【】<>《》")
_WORD_BOUNDARY_GUARD_SEC = 0.16
_VISUAL_SHOWCASE_TEXT_RE = re.compile(r"(看到|看一下|来看|镜头|画面|展示|演示|操作|实操|特写|细节|同框|对比|手电|刀|上手|打开|合上)")
_HESITATION_FILLERS = {"嗯", "呃", "额", "呃呃", "嗯嗯"}
_SINGLE_PARTICLE_FILLERS = {"啊", "呀", "呢", "吧", "嘛", "哦", "喔", "哎", "唉", "诶", "欸", "嗯", "呃", "额"}
SMART_CUT_RULE_CANDIDATE_STAGE = "manual_editor_smart_cut_rules"
_MULTIMODAL_REVIEW_POSITIVE_ROLES = {"comparison", "detail_showcase", "demo", "hook", "cta", "transition"}


def _parse_term_list(value: Any) -> list[str]:
    text = str(value or "")
    terms = [item.strip() for item in _TERM_SPLIT_PATTERN.split(text) if item.strip()]
    return sorted(dict.fromkeys(terms), key=lambda item: (-len(item), item))


def _subtitle_text(item: dict[str, Any]) -> str:
    for key in ("transcript_text", "text_final", "text_norm", "text_raw"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def _subtitle_semantic_text(item: dict[str, Any]) -> str:
    for key in ("text_final", "timing_text", "text_norm", "transcript_text", "text_raw"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def _subtitle_spoken_rule_text(item: dict[str, Any]) -> str:
    for key in ("transcript_text", "text_raw", "text_norm", "text_final"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def _timed_chars(item: dict[str, Any]) -> list[dict[str, Any]]:
    chars: list[dict[str, Any]] = []
    for unit in _timed_units(item):
        text = str(unit.get("text") or "")
        tokens = list(text)
        if not tokens:
            continue
        start = float(unit["start"])
        end = float(unit["end"])
        duration = max(0.001, end - start)
        for index, char in enumerate(tokens):
            chars.append(
                {
                    "text": char,
                    "start": round(start + duration * (index / len(tokens)), 3),
                    "end": round(start + duration * ((index + 1) / len(tokens)), 3),
                }
            )
    return sorted(chars, key=lambda char: (float(char["start"]), float(char["end"])))


def _subtitle_timing_supported_rule_text(item: dict[str, Any]) -> str:
    timed_text = "".join(str(char.get("text") or "") for char in _timed_chars(item)).strip()
    return timed_text


def _subtitle_range(item: dict[str, Any]) -> tuple[float, float]:
    start = max(0.0, float(item.get("start_time", item.get("start", 0.0)) or 0.0))
    end = max(start, float(item.get("end_time", item.get("end", start)) or start))
    return round(start, 3), round(end, 3)


def _timed_units(item: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for collection_key, text_key in (("words", "word"), ("alignment_tokens", "text")):
        for raw in list(item.get(collection_key) or []):
            if not isinstance(raw, dict):
                continue
            try:
                start = float(raw.get("start", 0.0) or 0.0)
                end = float(raw.get("end", start) or start)
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            text = str(raw.get(text_key) or "").strip()
            if not text:
                continue
            units.append(
                {
                    "text": text,
                    "start": round(max(0.0, start), 3),
                    "end": round(max(start, end), 3),
                }
            )
    return sorted(units, key=lambda unit: (float(unit["start"]), float(unit["end"])))


def _char_range_to_time(item: dict[str, Any], text: str, start_char: int, end_char: int) -> tuple[float, float] | None:
    start_time, end_time = _subtitle_range(item)
    if end_time <= start_time or not text:
        return None
    timed_chars = _timed_chars(item)
    text_chars = list(text)
    if timed_chars and len(timed_chars) == len(text_chars):
        clamped_start = min(max(0, start_char), len(text_chars))
        clamped_end = min(max(clamped_start, end_char), len(text_chars))
        if clamped_end > clamped_start:
            start_token = timed_chars[clamped_start]
            end_token = timed_chars[clamped_end - 1]
            mapped_start = float(start_token["start"])
            mapped_end = float(end_token["end"])
            if mapped_end > mapped_start:
                return round(mapped_start, 3), round(mapped_end, 3)
    total_units = max(1, len(text))
    clamped_start = min(max(0, start_char), len(text))
    clamped_end = min(max(clamped_start, end_char), len(text))
    mapped_start = start_time + (end_time - start_time) * (clamped_start / total_units)
    mapped_end = start_time + (end_time - start_time) * (clamped_end / total_units)
    if mapped_end <= mapped_start + 0.02:
        mapped_end = min(end_time, mapped_start + max(0.02, (end_time - start_time) / total_units))
    if mapped_end <= mapped_start:
        return None
    return round(mapped_start, 3), round(mapped_end, 3)


def _iter_term_matches(text: str, needle: str) -> list[tuple[int, int]]:
    if not text or not needle:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        index = text.find(needle, start)
        if index < 0:
            break
        ranges.append((index, index + len(needle)))
        start = index + len(needle)
    return ranges


def _classify_filler_mode(text: str, start_char: int, end_char: int, term: str) -> str | None:
    previous = text[start_char - 1] if start_char > 0 else ""
    following = text[end_char] if end_char < len(text) else ""
    previous_boundary = start_char == 0 or previous in _BOUNDARY_CHARS
    following_boundary = end_char >= len(text) or following in _BOUNDARY_CHARS
    single_particle = term in _SINGLE_PARTICLE_FILLERS
    hesitation = term in _HESITATION_FILLERS
    if previous_boundary and following_boundary:
        return "standalone"
    if start_char == 0:
        return "sentence_head" if single_particle or hesitation else "standalone"
    if end_char >= len(text):
        return "sentence_tail" if single_particle or hesitation else "standalone"
    if hesitation:
        if previous_boundary:
            return "sentence_head"
        if following_boundary:
            return "sentence_tail"
    return None


def _smart_cut_meaningful_text(text: str, fillers: list[str]) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for filler in fillers:
        if filler:
            cleaned = cleaned.replace(filler, "")
    cleaned = re.sub(r"[啊呀呃额嗯哎唉喔哦嘛呢吧哈\s,，、。.!！?？;；:：()[\]（）【】\"'“”‘’]+", "", cleaned)
    return cleaned


def _subtitle_has_usable_timed_units(item: dict[str, Any]) -> bool:
    return any(float(unit["end"]) > float(unit["start"]) for unit in _timed_units(item))


def _silence_source(value: Any) -> str:
    return str(value or "").strip().lower()


def _silence_range_has_audio_evidence(item: dict[str, Any]) -> bool:
    source = _silence_source(item.get("source"))
    return "audio" in source or "vad" in source or source == "mixed"


def _silence_range_has_asr_evidence(item: dict[str, Any]) -> bool:
    source = _silence_source(item.get("source"))
    return "asr" in source or "word" in source or "alignment" in source or source == "mixed"


def _subtitles_sorted(subtitles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [item for item in list(subtitles or []) if isinstance(item, dict)],
        key=lambda item: (
            float(item.get("start_time", item.get("start", 0.0)) or 0.0),
            float(item.get("end_time", item.get("end", 0.0)) or 0.0),
        ),
    )


def _multimodal_segment_hints(
    subtitles: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(content_profile, dict):
        return []
    video_understanding = content_profile.get("video_understanding")
    if not isinstance(video_understanding, dict):
        return []
    duration = max((_subtitle_range(item)[1] for item in _subtitles_sorted(subtitles)), default=0.0)
    return normalize_video_understanding_segment_hints(video_understanding, duration=duration)


def _matched_multimodal_hints_for_range(
    start: float,
    end: float,
    *,
    multimodal_segment_hints: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for hint in list(multimodal_segment_hints or []):
        if not isinstance(hint, dict):
            continue
        hint_start = float(hint.get("start", 0.0) or 0.0)
        hint_end = float(hint.get("end", hint_start) or hint_start)
        if hint_end <= start or hint_start >= end:
            continue
        matched.append(hint)
    return matched


def _multimodal_review_fields(
    start: float,
    end: float,
    *,
    multimodal_segment_hints: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    matched = _matched_multimodal_hints_for_range(
        start,
        end,
        multimodal_segment_hints=multimodal_segment_hints,
    )
    if not matched:
        return {}
    roles: list[str] = []
    strongest_priority_rank = -1
    strongest_priority = ""
    strongest_confidence = 0.0
    review_required = False
    for hint in matched:
        role = str(hint.get("role") or "").strip().lower()
        keep_priority = str(hint.get("keep_priority") or "").strip().lower()
        confidence = round(float(hint.get("confidence", 0.0) or 0.0), 3)
        if role and role not in roles:
            roles.append(role)
        rank = {"drop": 0, "low": 1, "medium": 2, "high": 3}.get(keep_priority, -1)
        if rank > strongest_priority_rank:
            strongest_priority_rank = rank
            strongest_priority = keep_priority
        strongest_confidence = max(strongest_confidence, confidence)
        if role in _MULTIMODAL_REVIEW_POSITIVE_ROLES and keep_priority in {"medium", "high"}:
            review_required = True
    payload: dict[str, Any] = {
        "multimodal_roles": roles[:4],
        "multimodal_keep_priority": strongest_priority or None,
        "multimodal_confidence": round(strongest_confidence, 3),
    }
    if review_required:
        payload["multimodal_review_required"] = True
    return payload


def _meaningful_timed_ranges_for_pause(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> list[tuple[float, float]]:
    start, end = _subtitle_range(silence)
    ranges: list[tuple[float, float]] = []
    for subtitle in _subtitles_sorted(subtitles):
        subtitle_start, subtitle_end = _subtitle_range(subtitle)
        subtitle_overlap = min(end, subtitle_end) - max(start, subtitle_start)
        if subtitle_overlap <= 0.08:
            continue
        for unit in _timed_units(subtitle):
            if not _smart_cut_meaningful_text(str(unit.get("text") or ""), fillers):
                continue
            unit_start = float(unit["start"])
            unit_end = float(unit["end"])
            if unit_end <= unit_start:
                continue
            ranges.append((round(unit_start, 3), round(unit_end, 3)))
    ranges.sort()
    return ranges


def _pause_range_overlaps_timed_speech(
    start: float,
    end: float,
    word_ranges: list[tuple[float, float]],
) -> bool:
    return any(min(end, word_end) - max(start, word_start) > 0.03 for word_start, word_end in word_ranges)


def _word_bounded_pause_ranges(
    silence: dict[str, Any],
    word_ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    silence_start, silence_end = _subtitle_range(silence)
    ranges: list[tuple[float, float]] = []
    for index in range(1, len(word_ranges)):
        previous = word_ranges[index - 1]
        nxt = word_ranges[index]
        start = max(silence_start, previous[1] + _WORD_BOUNDARY_GUARD_SEC)
        end = min(silence_end, nxt[0] - _WORD_BOUNDARY_GUARD_SEC)
        if end > start + 0.02:
            ranges.append((round(start, 3), round(end, 3)))
    return ranges


def _speech_separated_pause_ranges(
    silence: dict[str, Any],
    word_ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    silence_start, silence_end = _subtitle_range(silence)
    ranges: list[tuple[float, float]] = []
    cursor = silence_start
    for word_start, word_end in word_ranges:
        if word_end <= silence_start + 0.001 or word_start >= silence_end - 0.001:
            continue
        end = min(silence_end, word_start - _WORD_BOUNDARY_GUARD_SEC)
        if end > cursor + 0.02:
            ranges.append((round(cursor, 3), round(end, 3)))
        cursor = max(cursor, word_end + _WORD_BOUNDARY_GUARD_SEC)
    if silence_end > cursor + 0.02:
        ranges.append((round(cursor, 3), round(silence_end, 3)))
    return ranges


def _range_overlaps_subtitle_speech(
    start: float,
    end: float,
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> bool:
    for subtitle in _subtitles_sorted(subtitles):
        subtitle_start, subtitle_end = _subtitle_range(subtitle)
        overlap = min(end, subtitle_end) - max(start, subtitle_start)
        if overlap <= 0.08:
            continue
        text = _subtitle_text(subtitle)
        if _smart_cut_meaningful_text(text, fillers):
            return True
    return False


def _range_overlaps_untrusted_subtitle_speech(
    start: float,
    end: float,
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> bool:
    for subtitle in _subtitles_sorted(subtitles):
        subtitle_start, subtitle_end = _subtitle_range(subtitle)
        overlap = min(end, subtitle_end) - max(start, subtitle_start)
        if overlap <= 0.08:
            continue
        text = _subtitle_text(subtitle)
        if _smart_cut_meaningful_text(text, fillers) and not _subtitle_has_usable_timed_units(subtitle):
            return True
    return False


def _audio_range_overlaps_protected_visual_subtitle(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> bool:
    start, end = _subtitle_range(silence)
    for subtitle in _subtitles_sorted(subtitles):
        text = _subtitle_text(subtitle)
        if not _VISUAL_SHOWCASE_TEXT_RE.search(text):
            continue
        if len(_smart_cut_meaningful_text(text, fillers)) < 2:
            continue
        subtitle_start, subtitle_end = _subtitle_range(subtitle)
        overlap = min(end, subtitle_end) - max(start, subtitle_start)
        if overlap > 0.08:
            return True
    return False


def _audio_range_broadly_overlaps_subtitle_speech(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> bool:
    start, end = _subtitle_range(silence)
    for subtitle in _subtitles_sorted(subtitles):
        text = _subtitle_text(subtitle)
        if len(_smart_cut_meaningful_text(text, fillers)) < 2:
            continue
        subtitle_start, subtitle_end = _subtitle_range(subtitle)
        subtitle_duration = max(0.001, subtitle_end - subtitle_start)
        overlap = min(end, subtitle_end) - max(start, subtitle_start)
        if overlap > 0.08 and overlap / subtitle_duration >= 0.55:
            return True
    return False


def _subtitle_bounded_pause_ranges(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> list[tuple[float, float]]:
    start, end = _subtitle_range(silence)
    candidates: list[tuple[float, float]] = []
    relevant = [
        subtitle for subtitle in _subtitles_sorted(subtitles)
        if len(_smart_cut_meaningful_text(_subtitle_text(subtitle), fillers)) >= 2
    ]
    for index in range(1, len(relevant)):
        previous = relevant[index - 1]
        nxt = relevant[index]
        previous_end = _subtitle_range(previous)[1]
        next_start = _subtitle_range(nxt)[0]
        candidate_start = max(start, previous_end)
        candidate_end = min(end, next_start)
        if candidate_end > candidate_start + 0.02:
            candidates.append((round(candidate_start, 3), round(candidate_end, 3)))
    return candidates


def _fallback_cuttable_pause_ranges(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> list[tuple[float, float]]:
    bounded_ranges = _subtitle_bounded_pause_ranges(silence, subtitles, fillers)
    if bounded_ranges:
        return [
            candidate
            for candidate in bounded_ranges
            if not _range_overlaps_subtitle_speech(candidate[0], candidate[1], subtitles, fillers)
        ]
    start, end = _subtitle_range(silence)
    if _silence_range_has_audio_evidence(silence) and _range_overlaps_untrusted_subtitle_speech(start, end, subtitles, fillers):
        return []
    if (
        _silence_range_has_audio_evidence(silence)
        and not _audio_range_broadly_overlaps_subtitle_speech(silence, subtitles, fillers)
        and not _audio_range_overlaps_protected_visual_subtitle(silence, subtitles, fillers)
    ):
        return [(start, end)]
    return [] if _range_overlaps_subtitle_speech(start, end, subtitles, fillers) else [(start, end)]


def _cuttable_pause_ranges(
    silence: dict[str, Any],
    subtitles: list[dict[str, Any]],
    fillers: list[str],
) -> list[tuple[float, float]]:
    word_ranges = _meaningful_timed_ranges_for_pause(silence, subtitles, fillers)
    if word_ranges:
        if _silence_range_has_asr_evidence(silence):
            return _speech_separated_pause_ranges(silence, word_ranges)
        start, end = _subtitle_range(silence)
        if _pause_range_overlaps_timed_speech(start, end, word_ranges):
            return []
        return _word_bounded_pause_ranges(silence, word_ranges)
    return _fallback_cuttable_pause_ranges(silence, subtitles, fillers)


def build_smart_cut_rule_candidates(
    subtitles: list[dict[str, Any]] | None,
    smart_cut_rules: dict[str, Any] | None,
    silence_segments: list[dict[str, Any]] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rules = normalize_smart_cut_rules_payload(smart_cut_rules)
    filler_terms = _parse_term_list(rules.get("fillers")) if bool(rules.get("fillerEnabled")) else []
    catchphrase_terms = _parse_term_list(rules.get("catchphrases")) if bool(rules.get("catchphraseEnabled")) else []
    normalized_subtitles = _subtitles_sorted(list(subtitles or []))
    multimodal_segment_hints = _multimodal_segment_hints(normalized_subtitles, content_profile)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float, str, str]] = set()
    for subtitle_index, subtitle in enumerate(normalized_subtitles):
        if not isinstance(subtitle, dict):
            continue
        text = _subtitle_timing_supported_rule_text(subtitle) or _subtitle_spoken_rule_text(subtitle)
        if not text:
            continue
        semantic_text = _subtitle_semantic_text(subtitle) or text
        previous_text = _subtitle_semantic_text(normalized_subtitles[subtitle_index - 1]) if subtitle_index > 0 else ""
        next_text = _subtitle_semantic_text(normalized_subtitles[subtitle_index + 1]) if subtitle_index + 1 < len(normalized_subtitles) else ""
        for term in filler_terms:
            for start_char, end_char in _iter_term_matches(text, term):
                timed = _char_range_to_time(subtitle, text, start_char, end_char)
                if timed is None:
                    continue
                mode = _classify_filler_mode(text, start_char, end_char, term)
                if not mode:
                    continue
                if mode == "standalone" and not bool(rules.get("fillerStandaloneEnabled")):
                    continue
                if mode == "sentence_head" and not bool(rules.get("fillerSentenceHeadEnabled")):
                    continue
                if mode == "sentence_tail" and not bool(rules.get("fillerSentenceTailEnabled")):
                    continue
                key = ("filler_word", timed[0], timed[1], term, mode)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "start": timed[0],
                        "end": timed[1],
                        "reason": "filler_word",
                        "candidate_stage": SMART_CUT_RULE_CANDIDATE_STAGE,
                        "auto_applied": False,
                        "score": 0.92 if mode == "standalone" else 0.72,
                        "source_text": term,
                        "filler_mode": mode,
                    }
                )
        for term in catchphrase_terms:
            for start_char, end_char in _iter_term_matches(text, term):
                timed = _char_range_to_time(subtitle, text, start_char, end_char)
                if timed is None:
                    continue
                key = ("catchphrase_phrase", timed[0], timed[1], term, "")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "start": timed[0],
                        "end": timed[1],
                        "reason": "catchphrase_phrase",
                        "candidate_stage": SMART_CUT_RULE_CANDIDATE_STAGE,
                        "auto_applied": False,
                        "score": 0.74,
                        "source_text": term,
                    }
                )
        if bool(rules.get("smartDeleteEnabled")):
            subtitle_start, subtitle_end = _subtitle_range(subtitle)
            duration = subtitle_end - subtitle_start
            compact_text = compact_subtitle_text(semantic_text)
            if (
                duration >= 0.18
                and duration <= 4.5
                and len(compact_text) >= 5
                and low_signal_subtitle_is_contextually_isolated(
                    semantic_text,
                    previous_text=previous_text,
                    next_text=next_text,
                    content_profile=content_profile,
                )
                and subtitle_signal_score(semantic_text, content_profile=content_profile) <= 0.15
            ):
                key = ("low_signal_subtitle", subtitle_start, subtitle_end, semantic_text, "")
                if key not in seen:
                    seen.add(key)
                    candidates.append(
                        {
                            "start": subtitle_start,
                            "end": subtitle_end,
                            "reason": "low_signal_subtitle",
                            "candidate_stage": SMART_CUT_RULE_CANDIDATE_STAGE,
                            "auto_applied": False,
                            "score": 0.62,
                            "source_text": semantic_text,
                            **_multimodal_review_fields(
                                subtitle_start,
                                subtitle_end,
                                multimodal_segment_hints=multimodal_segment_hints,
                            ),
                        }
                    )
    if bool(rules.get("pauseEnabled")):
        low_signal_terms = sorted(dict.fromkeys([*catchphrase_terms, *filler_terms]), key=lambda item: (-len(item), item))
        for silence in list(silence_segments or []):
            if not isinstance(silence, dict):
                continue
            for start, end in _cuttable_pause_ranges(silence, normalized_subtitles, low_signal_terms):
                key = ("silence", start, end, "", "")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "start": start,
                        "end": end,
                        "reason": "silence",
                        "candidate_stage": SMART_CUT_RULE_CANDIDATE_STAGE,
                        "auto_applied": False,
                        "score": 0.81,
                    }
                )
    return sorted(
        candidates,
        key=lambda item: (
            float(item.get("start", 0.0) or 0.0),
            float(item.get("end", 0.0) or 0.0),
            str(item.get("reason") or ""),
            str(item.get("source_text") or ""),
        ),
    )

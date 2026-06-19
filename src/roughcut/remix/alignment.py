from __future__ import annotations

import re
from array import array
from collections.abc import Sequence

from roughcut.remix.contracts import AsrToken, GateIssue, GateResult, SubtitleTiming


TTS_ALIGNMENT_SOURCE = "qwen3_asr_forced_aligner_on_tts"


def normalize_eval_text(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", str(text or ""))).lower()


def lcs_coverage(reference: str, candidate: str) -> float:
    if not reference:
        return 1.0 if not candidate else 0.0
    if not candidate:
        return 0.0
    previous = [0] * (len(candidate) + 1)
    for ref_char in reference:
        current = [0]
        for column, cand_char in enumerate(candidate, start=1):
            if ref_char == cand_char:
                current.append(previous[column - 1] + 1)
            else:
                current.append(max(previous[column], current[-1]))
        previous = current
    return previous[-1] / max(1, len(reference))


def canonical_coverage(canonical_text: str, recognized_text: str) -> float:
    return lcs_coverage(normalize_eval_text(canonical_text), normalize_eval_text(recognized_text))


def expand_tokens_to_chars(tokens: Sequence[AsrToken]) -> list[dict[str, float | str]]:
    chars: list[dict[str, float | str]] = []
    for token in tokens:
        units = list(normalize_eval_text(token.text))
        if not units:
            continue
        span = max(0.001, float(token.end_sec) - float(token.start_sec))
        for index, unit in enumerate(units):
            chars.append(
                {
                    "char": unit,
                    "start": round(float(token.start_sec) + span * index / len(units), 3),
                    "end": round(float(token.start_sec) + span * (index + 1) / len(units), 3),
                }
            )
    return chars


def build_asr_aligned_subtitle_timings(
    chunks: Sequence[str],
    tokens: Sequence[AsrToken],
    *,
    duration_sec: float,
) -> list[SubtitleTiming]:
    token_chars = expand_tokens_to_chars(tokens)
    if not chunks or not token_chars:
        return []
    chunk_chars = _chunk_char_index(chunks)
    if not chunk_chars:
        return []
    token_text = "".join(str(item["char"]) for item in token_chars)
    canonical_text = "".join(item["char"] for item in chunk_chars)
    canonical_to_token = _lcs_index_mapping(canonical_text, token_text)
    chunk_indexes: list[list[int]] = [[] for _ in chunks]
    for canonical_index, item in enumerate(chunk_chars):
        chunk_indexes[int(item["chunk_index"])].append(canonical_index)

    timings: list[SubtitleTiming] = []
    total_canonical_chars = max(1, len(chunk_chars))
    for chunk_index, chunk in enumerate(chunks):
        canonical_indexes = chunk_indexes[chunk_index]
        if not canonical_indexes:
            continue
        mapped_token_indexes = [
            canonical_to_token[index]
            for index in canonical_indexes
            if index in canonical_to_token
        ]
        if mapped_token_indexes:
            start_index = min(mapped_token_indexes)
            end_index = max(mapped_token_indexes)
        else:
            start_ratio = canonical_indexes[0] / total_canonical_chars
            end_ratio = (canonical_indexes[-1] + 1) / total_canonical_chars
            start_index = min(len(token_chars) - 1, int(round(start_ratio * max(0, len(token_chars) - 1))))
            end_index = min(len(token_chars) - 1, max(start_index, int(round(end_ratio * max(0, len(token_chars) - 1)))))
        start = max(0.0, float(token_chars[start_index]["start"]) - 0.04)
        end = min(float(duration_sec), float(token_chars[end_index]["end"]) + 0.12)
        if end - start < 0.75:
            end = min(float(duration_sec), start + 0.9)
        timings.append(SubtitleTiming(text=str(chunk), start_sec=start, end_sec=end))
    return normalize_subtitle_timings(timings, duration_sec=duration_sec)


def audit_subtitle_timing_alignment(
    timings: Sequence[SubtitleTiming],
    tokens: Sequence[AsrToken],
    *,
    max_start_drift_sec: float = 0.35,
    max_end_drift_sec: float = 0.75,
) -> dict[str, object]:
    token_chars = expand_tokens_to_chars(tokens)
    if not timings or not token_chars:
        return {
            "status": "fail",
            "event_count": len(timings),
            "matched_count": 0,
            "unmatched_count": len(timings),
            "bad_drift_count": len(timings),
            "avg_abs_start_drift_sec": None,
            "avg_abs_end_drift_sec": None,
            "max_abs_start_drift_sec": None,
            "max_abs_end_drift_sec": None,
        }
    chunks = [item.text for item in timings]
    chunk_chars = _chunk_char_index(chunks)
    token_text = "".join(str(item["char"]) for item in token_chars)
    canonical_text = "".join(item["char"] for item in chunk_chars)
    canonical_to_token = _lcs_index_mapping(canonical_text, token_text)
    chunk_indexes: list[list[int]] = [[] for _ in chunks]
    for canonical_index, item in enumerate(chunk_chars):
        chunk_indexes[int(item["chunk_index"])].append(canonical_index)
    rows: list[dict[str, object]] = []
    unmatched_count = 0
    bad_drift_count = 0
    start_drifts: list[float] = []
    end_drifts: list[float] = []
    for timing, canonical_indexes in zip(timings, chunk_indexes):
        mapped = [canonical_to_token[index] for index in canonical_indexes if index in canonical_to_token]
        if not mapped:
            unmatched_count += 1
            bad_drift_count += 1
            rows.append(
                {
                    "text": timing.text,
                    "subtitle_start_sec": round(float(timing.start_sec), 3),
                    "subtitle_end_sec": round(float(timing.end_sec), 3),
                    "matched": False,
                }
            )
            continue
        start_index = min(mapped)
        end_index = max(mapped)
        expected_start = float(token_chars[start_index]["start"])
        expected_end = float(token_chars[end_index]["end"])
        start_drift = float(timing.start_sec) - expected_start
        end_drift = float(timing.end_sec) - expected_end
        start_drifts.append(abs(start_drift))
        end_drifts.append(abs(end_drift))
        is_bad = abs(start_drift) > max_start_drift_sec or abs(end_drift) > max_end_drift_sec
        if is_bad:
            bad_drift_count += 1
        rows.append(
            {
                "text": timing.text,
                "subtitle_start_sec": round(float(timing.start_sec), 3),
                "subtitle_end_sec": round(float(timing.end_sec), 3),
                "expected_start_sec": round(expected_start, 3),
                "expected_end_sec": round(expected_end, 3),
                "start_drift_sec": round(start_drift, 3),
                "end_drift_sec": round(end_drift, 3),
                "matched": True,
                "bad_drift": is_bad,
            }
        )
    matched_count = len(timings) - unmatched_count
    status = "pass" if unmatched_count == 0 and bad_drift_count == 0 else "fail"
    return {
        "status": status,
        "event_count": len(timings),
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "bad_drift_count": bad_drift_count,
        "avg_abs_start_drift_sec": round(sum(start_drifts) / len(start_drifts), 3) if start_drifts else None,
        "avg_abs_end_drift_sec": round(sum(end_drifts) / len(end_drifts), 3) if end_drifts else None,
        "max_abs_start_drift_sec": round(max(start_drifts), 3) if start_drifts else None,
        "max_abs_end_drift_sec": round(max(end_drifts), 3) if end_drifts else None,
        "max_start_drift_sec": max_start_drift_sec,
        "max_end_drift_sec": max_end_drift_sec,
        "events": rows,
    }


def _chunk_char_index(chunks: Sequence[str]) -> list[dict[str, int | str]]:
    chars: list[dict[str, int | str]] = []
    for chunk_index, chunk in enumerate(chunks):
        for unit in normalize_eval_text(chunk):
            chars.append({"chunk_index": chunk_index, "char": unit})
    return chars


def _lcs_index_mapping(reference: str, candidate: str) -> dict[int, int]:
    if not reference or not candidate:
        return {}
    rows: list[array[int]] = [array("H", [0]) * (len(candidate) + 1)]
    for ref_char in reference:
        previous = rows[-1]
        current = array("H", [0])
        for column, cand_char in enumerate(candidate, start=1):
            if ref_char == cand_char:
                current.append(previous[column - 1] + 1)
            else:
                current.append(max(previous[column], current[-1]))
        rows.append(current)
    mapping: dict[int, int] = {}
    row = len(reference)
    column = len(candidate)
    while row > 0 and column > 0:
        if reference[row - 1] == candidate[column - 1]:
            mapping[row - 1] = column - 1
            row -= 1
            column -= 1
        elif rows[row - 1][column] >= rows[row][column - 1]:
            row -= 1
        else:
            column -= 1
    return mapping


def normalize_subtitle_timings(timings: Sequence[SubtitleTiming], *, duration_sec: float) -> list[SubtitleTiming]:
    normalized: list[SubtitleTiming] = []
    previous_end = 0.0
    for index, timing in enumerate(timings):
        start = max(previous_end, min(float(duration_sec), float(timing.start_sec)))
        end = max(start + 0.9, min(float(duration_sec), float(timing.end_sec)))
        if index + 1 < len(timings):
            next_start = float(timings[index + 1].start_sec)
            if end > next_start - 0.04:
                end = max(start + 0.75, next_start - 0.04)
        end = min(float(duration_sec), end)
        if end > start:
            normalized.append(SubtitleTiming(text=timing.text, start_sec=round(start, 3), end_sec=round(end, 3)))
            previous_end = end
    return normalized


def evaluate_tts_asr_alignment(
    *,
    canonical_text: str,
    recognized_text: str,
    tokens: Sequence[AsrToken],
    min_pass_coverage: float = 0.90,
    min_warn_coverage: float = 0.80,
) -> GateResult:
    coverage = canonical_coverage(canonical_text, recognized_text)
    issues: list[GateIssue] = []
    status = "pass"
    if not tokens:
        status = "fail"
        issues.append(
            GateIssue(
                code="tts_asr_no_timestamps",
                severity="error",
                message="TTS-ASR produced no usable word/char timestamps.",
            )
        )
    if coverage < min_warn_coverage:
        status = "fail"
        issues.append(
            GateIssue(
                code="tts_asr_coverage_fail",
                severity="error",
                message="TTS-ASR recognized text coverage is below the hard gate.",
                evidence={"coverage": round(coverage, 4), "min_warn_coverage": min_warn_coverage},
            )
        )
    elif coverage < min_pass_coverage and status != "fail":
        status = "warn"
        issues.append(
            GateIssue(
                code="tts_asr_coverage_warn",
                severity="warn",
                message="TTS-ASR coverage requires manual spot-check.",
                evidence={"coverage": round(coverage, 4), "min_pass_coverage": min_pass_coverage},
            )
        )
    return GateResult(
        status=status,  # type: ignore[arg-type]
        issues=tuple(issues),
        metrics={
            "tts_asr_coverage": round(coverage, 4),
            "tts_asr_token_count": len(tokens),
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
        },
    )

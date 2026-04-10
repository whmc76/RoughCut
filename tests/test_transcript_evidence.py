from __future__ import annotations

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming
from roughcut.speech.transcribe import _normalize_transcript_result


def test_normalize_transcript_result_preserves_raw_evidence():
    raw_word = WordTiming(
        word="NOC",
        start=0.0,
        end=0.4,
        provider="faster_whisper",
        model="base",
        raw_payload={"word": "NOC", "probability": 0.99},
        confidence=0.99,
    )
    raw_segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=1.2,
        text="NOC 是原词",
        words=[raw_word],
        provider="faster_whisper",
        model="base",
        raw_payload={"text": "NOC 是原词", "segment_id": 7},
        raw_text="NOC 是原词",
        context="热词：NOC",
        hotword="NOC",
    )
    result = TranscriptResult(
        segments=[raw_segment],
        language="zh-CN",
        duration=1.2,
        provider="faster_whisper",
        model="base",
        raw_payload={"segments": [{"text": "NOC 是原词"}]},
        raw_segments=[raw_segment],
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[
            {
                "correct_form": "NOC 1",
                "wrong_forms": ["NOC"],
                "category": "tech_term",
            }
        ],
        review_memory=None,
    )

    assert normalized.segments[0].text == "NOC 1 是原词"
    assert normalized.segments[0].raw_text == "NOC 是原词"
    assert normalized.segments[0].raw_payload == {"text": "NOC 是原词", "segment_id": 7}
    assert normalized.segments[0].words
    assert normalized.segments[0].alignment["_roughcut"]["source"] in {"provider", "synthetic"}
    assert normalized.raw_segments[0].text == "NOC 是原词"
    assert normalized.raw_segments[0].raw_text == "NOC 是原词"
    assert normalized.raw_segments[0].words[0].raw_payload == {"word": "NOC", "probability": 0.99}
    assert normalized.raw_payload == {"segments": [{"text": "NOC 是原词"}]}
    assert normalized.alignment["segments_total"] == 1


def test_normalize_transcript_result_keeps_provider_metadata_on_fallback():
    segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=1.0,
        text="fallback text",
    )
    result = TranscriptResult(
        segments=[segment],
        language="zh-CN",
        duration=1.0,
        provider="qwen3_asr",
        model="qwen3-asr-1.7b",
        raw_payload={"provider": "qwen3_asr", "model": "qwen3-asr-1.7b"},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory=None,
    )

    assert normalized.provider == "qwen3_asr"
    assert normalized.model == "qwen3-asr-1.7b"
    assert normalized.segments[0].provider == "qwen3_asr"
    assert normalized.segments[0].model == "qwen3-asr-1.7b"
    assert normalized.segments[0].raw_payload == {}
    assert normalized.raw_payload == {"provider": "qwen3_asr", "model": "qwen3-asr-1.7b"}
    assert normalized.segments[0].text == "fallback text"
    assert normalized.segments[0].words
    assert normalized.alignment["segments_with_synthesized_words"] == 1


def test_normalize_transcript_result_synthesizes_word_timings_for_dense_cjk_text():
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=1.08,
                text="磁吸尾盖夜骑补光",
                provider="funasr",
                model="sensevoice-small",
            )
        ],
        language="zh-CN",
        duration=1.08,
        provider="funasr",
        model="sensevoice-small",
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory=None,
    )

    assert [word.word for word in normalized.segments[0].words] == ["磁吸", "尾盖", "夜骑", "补光"]
    assert normalized.segments[0].words[0].start == 0.0
    assert normalized.segments[0].words[-1].end == 1.08
    assert normalized.alignment["segments_with_synthesized_words"] == 1


def test_normalize_transcript_result_preserves_reference_word_payload_when_synthesizing():
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=1.0,
                text="测试文本",
                words=[
                    WordTiming(
                        word="测试",
                        start=0.0,
                        end=0.4,
                        raw_payload={"timing": 0.4},
                    )
                ],
            )
        ],
        language="zh-CN",
        duration=1.0,
        provider="faster_whisper",
        model="large-v3",
    )

    normalized = _normalize_transcript_result(result, glossary_terms=[], review_memory=None)

    assert normalized.alignment["segments_with_synthesized_words"] == 1
    assert normalized.segments[0].words[0].raw_payload["timing"] == 0.4

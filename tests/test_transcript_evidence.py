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


def test_normalize_transcript_result_filters_tail_cta_noise_but_keeps_raw_segments():
    intro_segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=3.0,
        text="今天简单看一下这个快开结构。",
        raw_text="今天简单看一下这个快开结构。",
    )
    noise_segment = TranscriptSegment(
        index=1,
        start=897.0,
        end=899.0,
        text="请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
        raw_text="请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    )
    result = TranscriptResult(
        segments=[intro_segment, noise_segment],
        language="zh-CN",
        duration=900.0,
        provider="qwen3_asr",
        model="qwen3-asr-1.7b",
        raw_payload={"segments": [{"text": intro_segment.text}, {"text": noise_segment.text}]},
        raw_segments=[intro_segment, noise_segment],
    )

    normalized = _normalize_transcript_result(result, glossary_terms=[], review_memory=None)

    assert [segment.text for segment in normalized.segments] == ["今天简单看一下这个快开结构。"]
    assert len(normalized.raw_segments) == 2
    assert normalized.raw_segments[-1].text == "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"
    assert normalized.raw_payload["_roughcut_filtering"]["dropped_tail_cta_segments"][0]["reason"] == "tail_cta_noise"


def test_normalize_transcript_result_keeps_non_cta_tail_reference_text():
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=874.0,
                end=878.0,
                text="明镜与点点栏目这期继续讲前置快开结构。",
                raw_text="明镜与点点栏目这期继续讲前置快开结构。",
            )
        ],
        language="zh-CN",
        duration=878.0,
        provider="qwen3_asr",
        model="qwen3-asr-1.7b",
        raw_payload={"segments": [{"text": "明镜与点点栏目这期继续讲前置快开结构。"}]},
    )

    normalized = _normalize_transcript_result(result, glossary_terms=[], review_memory=None)

    assert [segment.text for segment in normalized.segments] == ["明镜与点点栏目这期继续讲前置快开结构。"]
    assert "_roughcut_filtering" not in normalized.raw_payload

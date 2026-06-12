from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming
from roughcut.pipeline.steps import (
    _apply_subtitle_semantic_cleanup,
    _build_transcript_first_canonical_layer,
    _filter_redundant_corrections_for_current_subtitles,
)
from roughcut.media.subtitle_spans import sanitize_transcript_segment_word_rows
from roughcut.speech.subtitle_pipeline import build_transcript_fact_layer_from_result
from roughcut.speech.transcribe import _normalize_segment_word_timings_for_text, _normalize_transcript_result


def test_normalize_transcript_result_cleans_flashlight_cross_domain_drift() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="然后这种电折刀的方式也注定它的这个防尘防水等级不会低",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "手电", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "然后这种电折刀的方式也注定它的这个防尘防水等级不会低"


def test_normalize_transcript_result_normalizes_asr_stutter_before_downstream() -> None:
    first_raw = "今今天天终终于于收收到到了了年年前前的的一个个款款"
    second_raw = "没想到这NOC现NOC现在这么火"
    third_raw = "NNOCOC的的这个个发发售售，太太难难了，没没有没有这个像很多兄弟一样隐恨"
    fourth_raw = "最近这三次 N O C 的发售啊，最后的一个一款小玩具，非常适合 E D C 啊"
    fifth_raw = "最近这三次NONOC的发售，经常会EDEDC用的啊"
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text=first_raw,
                words=[
                    WordTiming(word=char, start=index * 0.05, end=(index + 1) * 0.05)
                    for index, char in enumerate(first_raw)
                ],
            ),
            TranscriptSegment(
                index=1,
                start=3.0,
                end=6.0,
                text=second_raw,
                words=[
                    WordTiming(word=char, start=3.0 + index * 0.05, end=3.0 + (index + 1) * 0.05)
                    for index, char in enumerate(second_raw)
                ],
            ),
            TranscriptSegment(
                index=2,
                start=6.0,
                end=9.0,
                text=third_raw,
                words=[
                    WordTiming(word=char, start=6.0 + index * 0.05, end=6.0 + (index + 1) * 0.05)
                    for index, char in enumerate(third_raw)
                ],
            ),
            TranscriptSegment(
                index=3,
                start=9.0,
                end=12.0,
                text=fourth_raw,
                words=[
                    WordTiming(word=char, start=9.0 + index * 0.05, end=9.0 + (index + 1) * 0.05)
                    for index, char in enumerate(fourth_raw)
                ],
            ),
            TranscriptSegment(
                index=4,
                start=12.0,
                end=15.0,
                text=fifth_raw,
                words=[
                    WordTiming(word=char, start=12.0 + index * 0.05, end=12.0 + (index + 1) * 0.05)
                    for index, char in enumerate(fifth_raw)
                ],
            ),
        ],
        language="zh-CN",
        duration=15.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={},
    )

    assert [segment.text for segment in normalized.segments] == [
        "今天终于收到了年前的一个款",
        "没想到这NOC现在这么火",
        "NOC的这个发售，太难了，没有这个像很多兄弟一样隐恨",
        "最近这三次 NOC 的发售啊，最后的一款小玩具，非常适合 EDC 啊",
        "最近这三次NOC的发售，经常会EDC用的啊",
    ]
    assert ["".join(word.word for word in segment.words) for segment in normalized.segments] == [
        "今天终于收到了年前的一个款",
        "没想到这NOC现在这么火",
        "NOC的这个发售太难了没有这个像很多兄弟一样隐恨",
        "最近这三次NOC的发售啊最后的一款小玩具非常适合EDC啊",
        "最近这三次NOC的发售经常会EDC用的啊",
    ]
    assert normalized.segments[0].raw_payload["_roughcut_asr_normalization"]["original_text"].startswith("今今天天")
    assert normalized.segments[4].raw_payload["_roughcut_asr_normalization"]["stage"] == "transcribe.normalize"


def test_normalize_transcript_result_removes_known_hallucination_phrase() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="鱼头的小章鱼",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "NOC MT34", "count": 8, "category_scope": "knife"}]},
    )

    assert normalized.segments[0].text == "鱼头的小章鱼"


def test_normalize_transcript_result_normalizes_flashlight_edc17_shorthand() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="所以呢我的选择就是这个幺七",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "EDC17", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "所以呢我的选择就是这个EDC17"


def test_normalize_transcript_result_normalizes_flashlight_model_spellings() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="它算是定位相当高端的一款EC手电了",
            ),
            TranscriptSegment(
                index=1,
                start=3.0,
                end=6.0,
                text="这个我记得是那个UHD二零了",
            ),
        ],
        language="zh-CN",
        duration=6.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "EDC17", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "它算是定位相当高端的一款EDC手电了"
    assert normalized.segments[1].text == "这个我记得是那个UHD20了"


def test_normalize_transcript_result_keeps_original_word_timings_when_model_alias_adds_ascii_units() -> None:
    raw = "所以呢我的选择就是这个幺七"
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text=raw,
                words=[
                    WordTiming(word=char, start=index * 0.1, end=(index + 1) * 0.1)
                    for index, char in enumerate(raw)
                ],
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "EDC17", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "所以呢我的选择就是这个EDC17"
    assert "".join(word.word for word in normalized.segments[0].words) == raw
    assert all(word.end - word.start >= 0.01 for word in normalized.segments[0].words)


def test_normalize_segment_word_timings_keeps_original_words_when_duplicate_unit_would_be_synthetic() -> None:
    raw = "啊也是很轻松"
    seg = TranscriptSegment(
        index=0,
        start=0.0,
        end=2.0,
        text="啊，啊也是很轻松",
        words=[
            WordTiming(word=char, start=index * 0.1, end=(index + 1) * 0.1)
            for index, char in enumerate(raw)
        ],
    )

    normalized_words = _normalize_segment_word_timings_for_text(
        seg,
        normalized_text="啊，啊也是很轻松",
    )

    assert "".join(word.word for word in normalized_words) == raw
    assert all(word.end - word.start >= 0.01 for word in normalized_words)


def test_build_transcript_fact_layer_drops_redundant_synthetic_duplicate_words() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=2.0,
                text="啊啊也是很轻松",
                words=[
                    WordTiming(
                        word="啊",
                        start=0.0,
                        end=0.001,
                        raw_payload={"_roughcut_asr_normalization": {"matched": False}},
                    ),
                    WordTiming(
                        word="啊",
                        start=0.0,
                        end=0.4,
                        raw_payload={"_roughcut_asr_normalization": {"matched": True}},
                    ),
                    WordTiming(word="也", start=0.4, end=0.7),
                    WordTiming(word="是", start=0.7, end=1.0),
                    WordTiming(word="很", start=1.0, end=1.4),
                    WordTiming(word="轻", start=1.4, end=1.7),
                    WordTiming(word="松", start=1.7, end=2.0),
                ],
            )
        ],
        language="zh-CN",
        duration=2.0,
        raw_payload={},
    )

    layer = build_transcript_fact_layer_from_result(result)
    words = list(layer.segments[0].words)

    assert [word.word for word in words] == ["啊", "也", "是", "很", "轻", "松"]


def test_sanitize_transcript_segment_word_rows_rewrites_legacy_duplicate_words_json() -> None:
    row = TranscriptSegment(
        index=0,
        start=0.0,
        end=2.0,
        text="啊啊也是很轻松",
    )
    row.words_json = [
        {"word": "啊", "start": 0.0, "end": 0.001, "_roughcut_asr_normalization": {"matched": False}},
        {"word": "啊", "start": 0.0, "end": 0.4, "_roughcut_asr_normalization": {"matched": True}},
        {"word": "也", "start": 0.4, "end": 0.7},
        {"word": "是", "start": 0.7, "end": 1.0},
    ]

    changed = sanitize_transcript_segment_word_rows([row])

    assert changed == 1
    assert row.words_json == [
        {"word": "啊", "start": 0.0, "end": 0.4, "_roughcut_asr_normalization": {"matched": True}},
        {"word": "也", "start": 0.4, "end": 0.7},
        {"word": "是", "start": 0.7, "end": 1.0},
    ]


def test_transcript_first_canonical_layer_normalizes_flashlight_edc17_shorthand() -> None:
    row = type(
        "TranscriptRow",
        (),
        {
            "segment_index": 0,
            "start_time": 0.0,
            "end_time": 3.0,
            "text": "所以呢我的选择就是这个幺七",
        },
    )()

    layer = _build_transcript_first_canonical_layer(
        transcript_rows=[row],
        subtitle_items=[],
        corrections=[],
        category_scope="flashlight",
    )

    payload = layer.as_dict()
    assert payload["segments"][0]["text_raw"] == "所以呢我的选择就是这个EDC17"
    assert payload["segments"][0]["text_canonical"] == "所以呢我的选择就是这个EDC17"


def test_subtitle_semantic_cleanup_corrects_nfc_to_noc_when_source_confirms_noc() -> None:
    item = type(
        "Item",
        (),
        {
            "text_raw": "最近这三次NFC的发售太难了",
            "text_norm": "最近这三次NFC的发售太难了",
            "text_final": None,
        },
    )()
    job = type("Job", (), {"source_name": "4637 开箱NOC MT34 也叫S06mini.mp4"})()

    changed = _apply_subtitle_semantic_cleanup([item], job=job, content_profile={}, review_memory={})

    assert changed == 1
    assert item.text_norm == "最近这三次NOC的发售太难了"
    assert item.text_final == "最近这三次NOC的发售太难了"


def test_transcript_first_canonical_layer_applies_deduped_subtitle_corrections_to_matching_transcript() -> None:
    row = type(
        "TranscriptRow",
        (),
        {
            "segment_index": 7,
            "start_time": 10.0,
            "end_time": 14.0,
            "text": "这个错词版本我们继续看",
        },
    )()
    subtitle = type(
        "SubtitleItem",
        (),
        {
            "id": "subtitle-7",
            "item_index": 3,
            "start_time": 10.2,
            "end_time": 13.8,
            "text_raw": "这个错词版本我们继续看",
            "text_norm": "这个错词版本我们继续看",
            "text_final": "这个错词版本我们继续看",
        },
    )()
    correction = {
        "subtitle_item_id": "subtitle-7",
        "original_span": "错词",
        "suggested_span": "正词",
        "human_decision": "accepted",
        "auto_applied": False,
        "change_type": "replace",
        "confidence": 0.91,
        "source": "test",
    }

    layer = _build_transcript_first_canonical_layer(
        transcript_rows=[row],
        subtitle_items=[subtitle],
        corrections=[correction, dict(correction)],
        category_scope="",
    )

    payload = layer.as_dict()
    assert payload["segments"][0]["text_canonical"] == "这个正词版本我们继续看"
    assert payload["correction_metrics"]["accepted_correction_count"] == 1


def test_redundant_correction_filter_drops_candidates_already_in_current_subtitles() -> None:
    subtitle = type(
        "SubtitleItem",
        (),
        {
            "id": "subtitle-1",
            "text_raw": "旧词",
            "text_norm": "正词",
            "text_final": "正词",
        },
    )()
    redundant = {
        "subtitle_item_id": "subtitle-1",
        "original_span": "旧词",
        "suggested_span": "正词",
    }
    pending = {
        "subtitle_item_id": "subtitle-1",
        "original_span": "别词",
        "suggested_span": "新词",
    }

    assert _filter_redundant_corrections_for_current_subtitles([redundant, pending], [subtitle]) == [pending]


def test_redundant_correction_filter_respects_display_surface_contract() -> None:
    subtitle = type(
        "SubtitleItem",
        (),
        {
            "id": "subtitle-1",
            "text_raw": "旧词",
            "text_norm": "正词",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
    )()
    correction = {
        "subtitle_item_id": "subtitle-1",
        "original_span": "旧词",
        "suggested_span": "正词",
    }

    assert _filter_redundant_corrections_for_current_subtitles([correction], [subtitle]) == [correction]


def test_normalize_transcript_result_collapses_flashlight_model_alt_lists() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="现在这个EDC17 / EDC37 / EDC37啊已经出来了",
            ),
            TranscriptSegment(
                index=1,
                start=3.0,
                end=6.0,
                text="这期做EDC17 / EDC37对比",
            ),
        ],
        language="zh-CN",
        duration=6.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "EDC17", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "现在这个EDC17 / EDC37 / EDC37啊已经出来了"
    assert normalized.segments[1].text == "这期做EDC17 / EDC37对比"


def test_normalize_transcript_result_collapses_repeated_flashlight_model_sequence() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="也是前两个月出的这个EDC17 EDC37 EDC37",
            ),
            TranscriptSegment(
                index=1,
                start=3.0,
                end=6.0,
                text="这期做EDC17 EDC37对比",
            ),
        ],
        language="zh-CN",
        duration=6.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "EDC17", "count": 10, "category_scope": "flashlight"}]},
    )

    assert normalized.segments[0].text == "也是前两个月出的这个EDC17 EDC37 EDC37"
    assert normalized.segments[1].text == "这期做EDC17 EDC37对比"


def test_normalize_transcript_result_corrects_knife_material_reflection_terms() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="呃，包括它上面这个钢瓦，钢瓦和这个盖瓦的这个泛光",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "折刀", "count": 10, "category_scope": "knife"}]},
    )

    assert normalized.segments[0].text == "呃，包括它上面这个钢瓦，钢瓦和这个盖瓦的这个泛光"


def test_normalize_transcript_result_collapses_foxbat_brand_expansion() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="FOXBATFoxbat工业还是这个",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "狐蝠工业", "count": 10, "category_scope": "bag"}]},
    )

    assert normalized.segments[0].text == "FOXBATFoxbat工业还是这个"


def test_normalize_transcript_result_collapses_bag_brand_tail_duplication() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="不过狐蝠工业工业这次的新款",
            ),
            TranscriptSegment(
                index=1,
                start=3.0,
                end=6.0,
                text="勃朗峰户外勃朗峰户外和狐蝠工业",
            ),
        ],
        language="zh-CN",
        duration=6.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "狐蝠工业", "count": 10, "category_scope": "bag"}]},
    )

    assert normalized.segments[0].text == "不过狐蝠工业工业这次的新款"
    assert normalized.segments[1].text == "勃朗峰户外勃朗峰户外和狐蝠工业"


def test_normalize_transcript_result_collapses_bag_brand_bundle_expansion() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="狐蝠工业HSJUN x BOLTBOAT 勃朗峰户外 x BOLTBOAT 狐蝠工业的新款",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "狐蝠工业", "count": 10, "category_scope": "bag"}]},
    )

    assert normalized.segments[0].text == "狐蝠工业HSJUN x BOLTBOAT 勃朗峰户外 x BOLTBOAT 狐蝠工业的新款"


def test_normalize_transcript_result_collapses_adjacent_duplicate_model_tokens() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="MT34 S06mini S06mini S06mini",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "NOC MT34", "count": 8, "category_scope": "knife"}]},
    )

    assert normalized.segments[0].text == "MT34 S06mini S06mini S06mini"


def test_normalize_transcript_result_corrects_zirconium_material_variant() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="呃，包括它上面这个钢瓦，钢瓦和这个锆瓦的这个泛光",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "折刀", "count": 10, "category_scope": "knife"}]},
    )

    assert normalized.segments[0].text == "呃，包括它上面这个钢瓦，钢瓦和这个锆瓦的这个泛光"


def test_normalize_transcript_result_corrects_material_reflection_after_split() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=3.0,
                text="钢马和这个锆马的这个泛光",
            )
        ],
        language="zh-CN",
        duration=3.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(
        result,
        glossary_terms=[],
        review_memory={"terms": [{"term": "折刀", "count": 10, "category_scope": "knife"}]},
    )

    assert normalized.segments[0].text == "钢马和这个锆马的这个泛光"

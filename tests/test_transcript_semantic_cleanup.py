from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.pipeline.steps import _build_transcript_first_canonical_layer, _filter_redundant_corrections_for_current_subtitles
from roughcut.speech.transcribe import _normalize_transcript_result


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

    assert normalized.segments[0].text == "所以呢我的选择就是这个幺七"


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
    assert payload["segments"][0]["text_raw"] == "所以呢我的选择就是这个幺七"
    assert payload["segments"][0]["text_canonical"] == "所以呢我的选择就是这个幺七"


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

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
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

    assert normalized.segments[0].text == "然后这种手电的方式也注定它的这个防尘防水等级不会低"


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

    assert normalized.segments == []


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

    assert normalized.segments[0].text == "现在这个EDC17啊已经出来了"
    assert normalized.segments[1].text == "这期做EDC17 / EDC37对比"


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

    assert normalized.segments[0].text == "呃，包括它上面这个钢马，钢马和这个锆马的这个反光"


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

    assert normalized.segments[0].text == "呃，包括它上面这个钢马，钢马和这个锆马的这个反光"


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

    assert normalized.segments[0].text == "钢马和这个锆马的这个反光"

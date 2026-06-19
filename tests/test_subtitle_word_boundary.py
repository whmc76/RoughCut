from roughcut.review.subtitle_quality import build_subtitle_quality_report
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.speech.subtitle_pipeline import _build_canonical_transcript_words
from roughcut.speech.transcript_projection import build_transcript_projection_layer
from roughcut.speech.subtitle_segmentation import (
    _assess_subtitle_boundary,
    SubtitleEntry,
    _boundary_splits_reason_preamble,
    _boundary_splits_predicate_phrase,
    _boundary_splits_protected_term,
    _boundary_starts_with_suffix_particle_continuation,
    _entry_needs_residual_repair,
    _boundary_splits_single_char_residual,
    _is_forbidden_subtitle_boundary,
    _is_incomplete_subtitle_text,
    _looks_like_short_detached_clause_fragment,
    _merge_continuation_entries,
    _merge_same_source_segment_micro_fragments,
    _merge_short_chain_entries,
    _rebalance_semantic_boundaries,
    _resolve_subtitle_entry_sequence,
    _semantic_boundary_quality,
    _split_readability_overflow_entries,
    _starts_with_attached_fragment,
    _words_for_segmentation,
    analyze_subtitle_segmentation,
    normalize_display_text,
    normalize_projection_display_text,
    segment_subtitles,
)


def _entry(index: int, text: str) -> SubtitleEntry:
    return SubtitleEntry(
        index=index,
        start=float(index),
        end=float(index + 1),
        text_raw=text,
        text_norm=text,
    )


def test_analyzes_generic_chinese_word_split() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "这个产"),
        _entry(1, "品不错"),
    ])

    assert analysis.generic_word_split_count == 1
    assert analysis.protected_term_split_count == 0
    assert "generic_word_split" in analysis.boundary_decisions[0].reason_tags


def test_analyzes_common_product_review_word_splits_without_jieba_dependency() -> None:
    cases = [
        ("狐蝠", "工业今年主打"),
        ("这个设", "计取向"),
        ("很有特", "色"),
        ("它的手", "感不错"),
        ("他", "妈这个位置"),
    ]
    for left, right in cases:
        analysis = analyze_subtitle_segmentation([
            _entry(0, left),
            _entry(1, right),
        ])

        assert analysis.generic_word_split_count == 1


def test_alignment_tokenizer_keeps_common_chinese_words_atomic() -> None:
    tokens = tokenize_alignment_text("我们他妈这个迷你老大哥天敌特色手感和狐蝠工业版本今天终于收到了年前的最后一个一款小玩具毫不费力油光水润玉质感锆合金")

    assert "我们" in tokens
    assert "他妈" in tokens
    assert "迷你" in tokens
    assert "老大哥" in tokens
    assert "天敌" in tokens
    assert "特色" in tokens
    assert "手感" in tokens
    assert "狐蝠工业" in tokens
    assert "今天" in tokens
    assert "终于" in tokens
    assert "收到" in tokens
    assert "年前" in tokens
    assert "最后" in tokens
    assert "一个" in tokens
    assert "一款" in tokens
    assert "小玩具" in tokens
    assert "毫不费力" in tokens
    assert "油光水润" in tokens
    assert "玉质感" in tokens
    assert "锆合金" in tokens


def test_alignment_tokenizer_keeps_numeric_units_atomic() -> None:
    tokens = tokenize_alignment_text("最高1500流明也支持1200lm档位")

    assert "1500流明" in tokens
    assert "1200lm" in tokens


def test_alignment_tokenizer_splits_mixed_model_name_and_chinese_after_space() -> None:
    tokens = tokenize_alignment_text("那个 S06MINI这款啊这个好")

    assert "那个" in tokens
    assert "S06MINI" in tokens
    assert "这款" in tokens
    assert "S06MINI这款啊这个好" not in tokens


def test_alignment_tokenizer_preserves_atomic_suffix_words_with_single_char_prefix() -> None:
    tokens = tokenize_alignment_text("该升级。呃，我们就简单的做一下展示。然后，")

    assert tokens == ["该升级。", "呃，", "我们", "就", "简单的", "做", "一下", "展示。", "然后，"]


def test_alignment_tokenizer_keeps_common_review_phrases_atomic() -> None:
    tokens = tokenize_alignment_text("或者说简单的这个短途的通勤啊")

    assert tokens == ["或者说", "简单的", "这个", "短途", "的", "通勤", "啊"]


def test_alignment_tokenizer_keeps_product_positioning_phrases_atomic() -> None:
    tokens = tokenize_alignment_text("该升级因为大家知道奈特科尔产品线算是定位相当高端的一款手电了")

    assert "该升级" in tokens
    assert "奈特科尔" in tokens
    assert "产品线" in tokens
    assert "算是" in tokens
    assert "定位" in tokens
    assert "相当" in tokens
    assert "高端" in tokens


def test_canonical_realign_words_do_not_split_atomic_suffix_terms() -> None:
    reference_words = (
        {"word": "该", "start": 0.0, "end": 0.2, "source_index": 0},
        {"word": "升级", "start": 0.2, "end": 0.6, "source_index": 1},
        {"word": "呃", "start": 0.6, "end": 0.8, "source_index": 2},
        {"word": "我们", "start": 0.8, "end": 1.2, "source_index": 3},
        {"word": "就", "start": 1.2, "end": 1.35, "source_index": 4},
        {"word": "简单", "start": 1.35, "end": 1.7, "source_index": 5},
        {"word": "的", "start": 1.7, "end": 1.82, "source_index": 6},
        {"word": "做", "start": 1.82, "end": 1.96, "source_index": 7},
        {"word": "一下", "start": 1.96, "end": 2.28, "source_index": 8},
        {"word": "展示", "start": 2.28, "end": 2.72, "source_index": 9},
        {"word": "然后", "start": 2.72, "end": 3.0, "source_index": 10},
    )

    words = _build_canonical_transcript_words(
        "该升级。呃，我们就简单的做一下展示。然后，",
        start=0.0,
        end=3.0,
        reference_words=reference_words,
    )

    assert [word.word for word in words] == [
        "该升级。",
        "呃，",
        "我们",
        "就",
        "简单的",
        "做",
        "一下",
        "展示。",
        "然后，",
    ]


def test_segmenter_keeps_bare_determiner_upgrade_phrase_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "功能每一样都是我需要的，所以说那也就没啥好说的了。该升级。呃，我们其他博主也是也都发过这款手电了。",
            "start_time": 168.24,
            "end_time": 180.0,
            "words_json": [
                {"word": "功能", "start": 168.24, "end": 168.72},
                {"word": "每一样", "start": 168.72, "end": 169.76},
                {"word": "都是", "start": 169.76, "end": 170.08},
                {"word": "我需要", "start": 170.08, "end": 171.44},
                {"word": "的", "start": 171.44, "end": 171.6},
                {"word": "所以", "start": 171.6, "end": 171.76},
                {"word": "说那", "start": 171.76, "end": 172.0},
                {"word": "也", "start": 172.0, "end": 172.24},
                {"word": "就", "start": 172.24, "end": 172.44},
                {"word": "没啥", "start": 172.44, "end": 172.84},
                {"word": "好说", "start": 172.84, "end": 173.04},
                {"word": "的", "start": 173.04, "end": 173.2},
                {"word": "了。", "start": 173.2, "end": 173.36},
                {"word": "该", "start": 173.36, "end": 173.56},
                {"word": "升级。", "start": 173.56, "end": 173.92},
                {"word": "呃，", "start": 173.92, "end": 174.56},
                {"word": "我们", "start": 174.56, "end": 175.12},
                {"word": "其他", "start": 175.12, "end": 175.52},
                {"word": "博主", "start": 175.52, "end": 175.88},
                {"word": "也是", "start": 175.88, "end": 176.44},
                {"word": "也都", "start": 176.44, "end": 176.92},
                {"word": "发过", "start": 176.92, "end": 177.36},
                {"word": "这款", "start": 177.36, "end": 177.72},
                {"word": "手电", "start": 177.72, "end": 178.08},
                {"word": "了。", "start": 178.08, "end": 178.4},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("该") and right.startswith("升级") for left, right in zip(texts, texts[1:]))
    assert any("该升级" in item for item in texts)


def test_segmenter_keeps_verb_object_phrase_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "呃，我们其他博主也是也都发过这款手电了，我们就简单的做一下展示。",
            "start_time": 173.36,
            "end_time": 181.6,
            "words_json": [
                {"word": "呃，", "start": 173.36, "end": 175.2},
                {"word": "我们", "start": 175.2, "end": 175.76},
                {"word": "其他", "start": 176.88, "end": 177.2},
                {"word": "博主", "start": 177.2, "end": 177.36},
                {"word": "也", "start": 177.36, "end": 177.8},
                {"word": "是", "start": 177.8, "end": 178.24},
                {"word": "也", "start": 178.24, "end": 178.68},
                {"word": "都", "start": 178.68, "end": 179.12},
                {"word": "发过", "start": 179.12, "end": 179.36},
                {"word": "这款", "start": 179.36, "end": 179.6},
                {"word": "手电", "start": 179.6, "end": 179.84},
                {"word": "了，", "start": 179.84, "end": 180.0},
                {"word": "我们", "start": 180.0, "end": 180.24},
                {"word": "就", "start": 180.24, "end": 180.32},
                {"word": "简单", "start": 180.32, "end": 180.64},
                {"word": "的", "start": 180.64, "end": 180.84},
                {"word": "做", "start": 180.84, "end": 181.04},
                {"word": "一下", "start": 181.04, "end": 181.2},
                {"word": "展示。", "start": 181.2, "end": 181.6},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("发过") and right.startswith("这款") for left, right in zip(texts, texts[1:]))


def test_segmenter_keeps_locative_modifier_phrase_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "然后，呃，首先它前头一个功能键啊，这个功能键是这个就是M的这个标。",
            "start_time": 181.84,
            "end_time": 189.44,
            "words_json": [
                {"word": "然后，", "start": 181.84, "end": 182.0},
                {"word": "呃，", "start": 182.0, "end": 183.36},
                {"word": "首先", "start": 183.36, "end": 183.6},
                {"word": "它", "start": 183.6, "end": 183.68},
                {"word": "前头", "start": 183.68, "end": 184.0},
                {"word": "一个", "start": 184.0, "end": 184.16},
                {"word": "功能", "start": 184.16, "end": 184.48},
                {"word": "键啊，", "start": 184.48, "end": 184.8},
                {"word": "这个", "start": 184.8, "end": 185.12},
                {"word": "功能", "start": 185.12, "end": 185.44},
                {"word": "键", "start": 185.44, "end": 185.6},
                {"word": "是", "start": 185.6, "end": 185.84},
                {"word": "这个", "start": 185.84, "end": 186.08},
                {"word": "就是", "start": 186.08, "end": 186.64},
                {"word": "M", "start": 186.64, "end": 186.88},
                {"word": "的", "start": 186.88, "end": 187.04},
                {"word": "这个", "start": 187.04, "end": 187.44},
                {"word": "标。", "start": 187.44, "end": 187.84},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("前头") and right.startswith("一个") for left, right in zip(texts, texts[1:]))


def test_segmenter_keeps_light_verb_and_object_phrase_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "我们就简单的做一下展示。然后继续看这个功能。",
            "start_time": 180.0,
            "end_time": 186.0,
            "words_json": [
                {"word": "我们", "start": 180.0, "end": 180.24},
                {"word": "就", "start": 180.24, "end": 180.32},
                {"word": "简单", "start": 180.32, "end": 180.64},
                {"word": "的", "start": 180.64, "end": 180.84},
                {"word": "做", "start": 180.84, "end": 181.04},
                {"word": "一下", "start": 181.04, "end": 181.2},
                {"word": "展示。", "start": 181.2, "end": 181.6},
                {"word": "然后", "start": 181.84, "end": 182.0},
                {"word": "继续", "start": 182.0, "end": 182.48},
                {"word": "看", "start": 182.48, "end": 182.72},
                {"word": "这个", "start": 182.72, "end": 183.04},
                {"word": "功能。", "start": 183.04, "end": 183.52},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("做一下") and right.startswith("展示") for left, right in zip(texts, texts[1:]))


def test_segmenter_keeps_pronoun_modifier_phrase_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "然后首先它前头一个功能键啊。",
            "start_time": 181.84,
            "end_time": 184.8,
            "words_json": [
                {"word": "然后", "start": 181.84, "end": 182.0},
                {"word": "首先", "start": 182.0, "end": 183.36},
                {"word": "它", "start": 183.36, "end": 183.6},
                {"word": "前头", "start": 183.6, "end": 184.0},
                {"word": "一个", "start": 184.0, "end": 184.16},
                {"word": "功能", "start": 184.16, "end": 184.48},
                {"word": "键啊。", "start": 184.48, "end": 184.8},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("它") and right.startswith("前头") for left, right in zip(texts, texts[1:]))


def test_allows_normal_sentence_boundary_without_word_split() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "这个产品不错"),
        _entry(1, "我们今天继续看"),
    ])

    assert analysis.generic_word_split_count == 0


def test_analyzes_number_unit_split_as_measure_phrase() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "最高亮度1500"),
        _entry(1, "流明"),
    ])

    assert "measure_phrase_split" in analysis.boundary_decisions[0].reason_tags


def test_analyzes_number_approximation_split_as_measure_phrase() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "出光范围到了270"),
        _entry(1, "多的烛光范围"),
    ])

    assert "measure_phrase_split" in analysis.boundary_decisions[0].reason_tags


def test_segmenter_keeps_number_and_lumen_unit_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "最高亮度1500流明还有低亮度",
            "start_time": 0.0,
            "end_time": 3.0,
            "words_json": [
                {"word": "最高亮度", "start": 0.0, "end": 0.6},
                {"word": "1500", "start": 0.6, "end": 1.0},
                {"word": "流明", "start": 1.0, "end": 1.3},
                {"word": "还有", "start": 1.3, "end": 1.8},
                {"word": "低亮度", "start": 1.8, "end": 3.0},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=8, max_duration=2.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(
        left.endswith("1500") and right.startswith("流明")
        for left, right in zip(texts, texts[1:])
    )


def _timed_entry(index: int, start: float, end: float, text: str) -> SubtitleEntry:
    return SubtitleEntry(
        index=index,
        start=start,
        end=end,
        text_raw=text,
        text_norm=text,
    )


def _worded_entry(index: int, start: float, word_spans: list[tuple[str, float]], text: str | None = None) -> SubtitleEntry:
    cursor = start
    words: list[dict] = []
    pieces: list[str] = []
    for word_text, duration in word_spans:
        pieces.append(word_text)
        words.append({"word": word_text, "start": cursor, "end": cursor + duration})
        cursor += duration
    raw_text = text or "".join(pieces)
    return SubtitleEntry(
        index=index,
        start=start,
        end=cursor,
        text_raw=raw_text,
        text_norm=raw_text,
        words=tuple(words),
    )


def test_segmenter_retokenizes_char_level_provider_words_before_splitting() -> None:
    text = "哦今天终于收到了年前的最后的一个一款小玩具啊"
    chars = [char for char in text if char not in "，。！？!?；;：:,、"]
    words = []
    cursor = 1.6
    for char in chars:
        words.append({"word": char, "start": cursor, "end": cursor + 0.16})
        cursor += 0.16
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": text,
            "start_time": 1.6,
            "end_time": cursor,
            "words_json": words,
        },
    )()

    result = segment_subtitles([segment], max_chars=9, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(
        left.endswith("年") and right.startswith("前")
        for left, right in zip(texts, texts[1:])
    )
    assert any("年前" in item for item in texts)


def test_merge_continuation_entries_does_not_create_overlong_generic_bridge_rows() -> None:
    entries = [
        _timed_entry(0, 0.0, 2.48, "所以说为什么我平时比如临时"),
        _timed_entry(1, 2.48, 4.56, "出个门遛个狗啊，啊，"),
    ]

    merged = _merge_continuation_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == [
        "所以说为什么我平时比如临时",
        "出个门遛个狗啊，啊，",
    ]


def test_merge_continuation_entries_still_repairs_short_attached_fragment_rows() -> None:
    entries = [
        _timed_entry(0, 0.0, 2.96, "然后"),
        _timed_entry(1, 2.96, 5.76, "呃，首先它前头一个功能键啊，"),
    ]

    merged = _merge_continuation_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == ["然后呃，首先它前头一个功能键啊，"]


def test_same_source_pair_merge_repairs_contiguous_short_fragments_without_gap() -> None:
    segment_words = (
        {"word": "奈特", "start": 0.0, "end": 0.3, "segment_index": 0},
        {"word": "科尔", "start": 0.3, "end": 0.6, "segment_index": 0},
    )
    entries = [
        SubtitleEntry(index=0, start=0.0, end=0.3, text_raw="奈特", text_norm="奈特", words=(segment_words[0],)),
        SubtitleEntry(index=1, start=0.3, end=0.6, text_raw="科尔", text_norm="科尔", words=(segment_words[1],)),
    ]

    from roughcut.speech.subtitle_segmentation import _merge_same_source_segment_micro_fragments

    merged = _merge_same_source_segment_micro_fragments(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == ["奈特科尔"]


def test_same_source_pair_merge_does_not_force_overlong_single_row_without_quality_gain() -> None:
    segment_words = (
        {"word": "另外", "start": 0.0, "end": 0.2, "segment_index": 0},
        {"word": "颜色方面我觉得更稳定一些", "start": 0.2, "end": 1.8, "segment_index": 0},
    )
    entries = [
        SubtitleEntry(index=0, start=0.0, end=0.2, text_raw="另外", text_norm="另外", words=(segment_words[0],)),
        SubtitleEntry(index=1, start=0.2, end=1.8, text_raw="颜色方面我觉得更稳定一些", text_norm="颜色方面我觉得更稳定一些", words=(segment_words[1],)),
    ]

    from roughcut.speech.subtitle_segmentation import _merge_same_source_segment_micro_fragments

    merged = _merge_same_source_segment_micro_fragments(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == ["另外", "颜色方面我觉得更稳定一些"]


def test_same_source_pair_merge_repairs_short_followon_clause_after_soft_break() -> None:
    segment_words = (
        {"word": "所以说它的揣在兜里非常轻便，", "start": 0.0, "end": 2.41, "segment_index": 0},
        {"word": "呃，非常的无感。", "start": 2.41, "end": 3.44, "segment_index": 0},
    )
    entries = [
        SubtitleEntry(index=0, start=0.0, end=2.41, text_raw="所以说它的揣在兜里非常轻便，", text_norm="所以说它的揣在兜里非常轻便，", words=(segment_words[0],)),
        SubtitleEntry(index=1, start=2.41, end=3.44, text_raw="呃，非常的无感。", text_norm="呃，非常的无感。", words=(segment_words[1],)),
    ]

    merged = _merge_same_source_segment_micro_fragments(entries, max_chars=20, max_duration=3.8)

    assert [entry.text_raw for entry in merged] == ["所以说它的揣在兜里非常轻便，呃，非常的无感。"]


def test_same_source_pair_merge_repairs_short_incomplete_lead_tail() -> None:
    segment_words = (
        {"word": "该升级", "start": 0.0, "end": 0.35, "segment_index": 0},
        {"word": "我们其他博主也是也都发过这款手电了我们", "start": 0.7, "end": 4.95, "segment_index": 0},
    )
    entries = [
        SubtitleEntry(index=0, start=0.0, end=0.35, text_raw="该升级", text_norm="该升级", words=(segment_words[0],)),
        SubtitleEntry(index=1, start=0.7, end=4.95, text_raw="我们其他博主也是也都发过这款手电了我们", text_norm="我们其他博主也是也都发过这款手电了我们", words=(segment_words[1],)),
    ]

    merged = _merge_same_source_segment_micro_fragments(entries, max_chars=20, max_duration=3.8)

    assert [entry.text_raw for entry in merged] == ["该升级我们其他博主也是也都发过这款手电了我们"]


def test_same_source_run_compaction_keeps_already_readable_rows() -> None:
    entries = [
        SubtitleEntry(index=0, start=0.0, end=0.8, text_raw="特别的实用", text_norm="特别的实用", words=({"word": "特别的实用", "start": 0.0, "end": 0.8, "segment_index": 0},)),
        SubtitleEntry(index=1, start=0.8, end=1.6, text_raw="当你手电比较多", text_norm="当你手电比较多", words=({"word": "当你手电比较多", "start": 0.8, "end": 1.6, "segment_index": 0},)),
        SubtitleEntry(index=2, start=1.6, end=2.4, text_raw="的时候啊你就会", text_norm="的时候啊你就会", words=({"word": "的时候啊你就会", "start": 1.6, "end": 2.4, "segment_index": 0},)),
        SubtitleEntry(index=3, start=2.4, end=3.2, text_raw="理解这个易用性啊", text_norm="理解这个易用性啊", words=({"word": "理解这个易用性啊", "start": 2.4, "end": 3.2, "segment_index": 0},)),
    ]

    from roughcut.speech.subtitle_segmentation import _merge_same_source_segment_micro_fragments

    merged = _merge_same_source_segment_micro_fragments(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == [entry.text_raw for entry in entries]


def test_single_char_residual_boundary_detects_true_one_char_word_split() -> None:
    assert _boundary_splits_single_char_residual("这", "个功能键啊") is True


def test_single_char_residual_boundary_does_not_flag_normal_multi_char_phrase_boundary() -> None:
    assert _boundary_splits_single_char_residual("我们其他", "博主也是也都发过这款手电了，") is False


def test_incomplete_subtitle_text_treats_qita_tail_as_unclosed_nominal_fragment() -> None:
    assert _is_incomplete_subtitle_text("该升级我们其他") is True
    assert _semantic_boundary_quality("该升级我们其他", "博主也是也都发过这款手电了") <= -4.0


def test_predicate_continuation_treats_dingwei_followed_by_xiangdang_as_unclosed() -> None:
    assert _boundary_splits_predicate_phrase("产品线算是定位", "相当高端的一款EDC手电了") is True
    assert _semantic_boundary_quality("产品线算是定位", "相当高端的一款EDC手电了") <= -4.0


def test_incomplete_subtitle_text_treats_zhege_requirement_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("完美的符合了我所有的这个") is True
    assert _semantic_boundary_quality("完美的符合了我所有的这个", "EDC手电的一个要求啊它") <= -8.0


def test_incomplete_subtitle_text_treats_yikuan_model_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("相当高端的一款") is True
    assert _semantic_boundary_quality("相当高端的一款", "EDC手电了") <= -4.0


def test_incomplete_subtitle_text_treats_gaishengji_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("该升级") is True
    assert _semantic_boundary_quality("该升级", "我们其他博主也是也都发过") <= -8.0


def test_incomplete_subtitle_text_keeps_gaishengji_tail_unclosed_even_with_period() -> None:
    assert _is_incomplete_subtitle_text("该升级。") is True
    assert _semantic_boundary_quality("该升级。", "我们其他博主也是也都发过") <= -8.0


def test_incomplete_subtitle_text_treats_biru_linshi_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("所以说为什么我平时比如临时") is True
    assert _semantic_boundary_quality("所以说为什么我平时比如临时", "出个门遛个狗啊或者说") <= -4.0


def test_incomplete_subtitle_text_treats_huozheshuo_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("出个门遛个狗啊或者说") is True
    assert _semantic_boundary_quality("出个门遛个狗啊或者说", "简单的这个短途的通勤啊这个晚上") <= -4.0


def test_incomplete_subtitle_text_treats_yebushishuozhi_tail_as_unclosed() -> None:
    assert _is_incomplete_subtitle_text("而且它的这个UV的功能啊也不是说只") is True
    assert _semantic_boundary_quality("而且它的这个UV的功能啊也不是说只", "限用照明") <= -4.0


def test_segmenter_does_not_isolate_punctuation_masked_nominal_tail() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "该升级。呃，我们其他博主也是也都发过这款手电了，我们就简单的做一下展示。然后，",
            "start_time": 0.0,
            "end_time": 8.0,
            "words_json": [
                {"word": "该升级。", "start": 0.0, "end": 0.9},
                {"word": "呃，", "start": 0.9, "end": 1.2},
                {"word": "我们其他博主也是也都发过", "start": 1.2, "end": 4.2},
                {"word": "这款手电了，", "start": 4.2, "end": 5.0},
                {"word": "我们就简单的做一下展示。", "start": 5.0, "end": 7.4},
                {"word": "然后，", "start": 7.4, "end": 8.0},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=18, max_duration=4.0)
    texts = [entry.text_raw for entry in result.entries]

    assert "该升级。" not in texts
    assert any(text.startswith("该升级。呃，我们其他博主也是也都发过") for text in texts)


def test_rebalance_semantic_boundaries_does_not_create_new_generic_word_split() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("好说的了。", 0.8),
                ("该", 0.2),
                ("升", 0.2),
                ("级。", 0.2),
                ("呃，", 0.2),
            ],
            text="好说的了。该升级。呃，",
        ),
        _worded_entry(
            1,
            1.6,
            [("我们其他博主也是也都发过", 2.0)],
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "好说的了。该升级。呃，",
        "我们其他博主也是也都发过",
    ]


def test_rebalance_semantic_boundaries_does_not_create_new_attached_fragment_start() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("需要的，", 0.8),
                ("所以说", 0.4),
                ("那也就", 0.6),
                ("没啥", 0.4),
            ],
            text="需要的，所以说那也就没啥",
        ),
        _worded_entry(
            1,
            2.2,
            [
                ("好说", 0.5),
                ("的了。", 0.4),
                ("该升级。", 0.4),
                ("呃，", 0.3),
            ],
            text="好说的了。该升级。呃，",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "需要的，所以说那也就没啥",
        "好说的了。该升级。呃，",
    ]


def test_rebalance_semantic_boundaries_does_not_move_sentence_closer_into_following_row() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("我们其他博主也是也都发过", 1.8),
                ("这款手电", 0.8),
            ],
            text="我们其他博主也是也都发过这款手电",
        ),
        _worded_entry(
            1,
            2.8,
            [
                ("了，", 0.3),
                ("我们", 0.4),
                ("就简单的", 0.8),
                ("做一下展示。", 1.0),
            ],
            text="了，我们就简单的做一下展示。",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "我们其他博主也是也都发过这款手电了，",
        "我们就简单的做一下展示。",
    ]


def test_rebalance_semantic_boundaries_moves_short_detached_tail_into_following_clause() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("需要的，", 0.6),
                ("所以说", 0.4),
                ("那也就", 0.5),
                ("没啥好说的了", 1.0),
                ("该升级", 0.4),
            ],
            text="需要的，所以说那也就没啥好说的了该升级",
        ),
        _worded_entry(
            1,
            3.2,
            [
                ("我们其他博主也是也都发过这款手电了", 2.4),
                ("我们", 0.4),
            ],
            text="我们其他博主也是也都发过这款手电了我们",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "需要的，所以说那也就没啥好说的了",
        "该升级我们其他博主也是也都发过这款手电了我们",
    ]


def test_rebalance_semantic_boundaries_moves_short_detached_lead_in_leftward() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [("这个晚上出门都会带它", 1.8)],
            text="这个晚上出门都会带它",
        ),
        _worded_entry(
            1,
            2.0,
            [
                ("很实用", 0.8),
                ("而且它的这个UV的功能啊", 2.0),
            ],
            text="很实用而且它的这个UV的功能啊",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "这个晚上出门都会带它很实用",
        "而且它的这个UV的功能啊",
    ]


def test_rebalance_semantic_boundaries_preserves_subject_led_clause_restart() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("我们其他博主也是也都发过", 2.4),
                ("这款手电了，", 0.6),
            ],
            text="我们其他博主也是也都发过这款手电了，",
        ),
        _worded_entry(
            1,
            3.1,
            [
                ("我们", 0.36),
                ("就简单的", 0.84),
                ("做一下展示。", 0.96),
            ],
            text="我们就简单的做一下展示。",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "我们其他博主也是也都发过这款手电了，",
        "我们就简单的做一下展示。",
    ]


def test_rebalance_semantic_boundaries_preserves_adverb_led_clause_restart() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("很实用", 0.7),
                ("而且它的这个UV的功能啊，", 2.1),
            ],
            text="很实用而且它的这个UV的功能啊，",
        ),
        _worded_entry(
            1,
            2.9,
            [
                ("也", 0.28),
                ("不是说", 0.56),
                ("只限用照明", 0.92),
            ],
            text="也不是说只限用照明",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "很实用而且它的这个UV的功能啊，",
        "也不是说只限用照明",
    ]


def test_boundary_splits_reason_preamble_for_temporal_followon_clause() -> None:
    assert _boundary_splits_reason_preamble("所以说为什么我", "平时比如临时出个门") is True


def test_boundary_splits_reason_preamble_for_subject_clause_restart() -> None:
    assert _boundary_splits_reason_preamble("所以说为什么", "我平时比如临时出个门") is True


def test_boundary_splits_predicate_phrase_for_meisha_haoshuo_followon() -> None:
    assert _boundary_splits_predicate_phrase("所以说那也就没啥", "好说的了该升级") is True


def test_boundary_starts_with_suffix_particle_continuation_for_dele_clause() -> None:
    assert _boundary_starts_with_suffix_particle_continuation("所以说那也就没啥好说", "的了该升级我们") is True


def test_boundary_starts_with_suffix_particle_continuation_for_le_clause() -> None:
    assert _boundary_starts_with_suffix_particle_continuation("我们其他博主也是也都发过这款手电", "了我们就简单的做一下展示") is True


def test_assess_subtitle_boundary_centralizes_forbidden_reason_preamble_flags() -> None:
    assessment = _assess_subtitle_boundary("所以说为什么", "我平时比如临时出个门")

    assert assessment.forbidden is True
    assert "reason_preamble" in assessment.damage_flags


def test_assess_subtitle_boundary_centralizes_suffix_particle_continuation_flags() -> None:
    assessment = _assess_subtitle_boundary("我们其他博主也是也都发过这款手电", "了我们就简单的做一下展示")

    assert assessment.forbidden is True
    assert "suffix_particle_continuation" in assessment.damage_flags
    assert "protected_term" not in assessment.damage_flags


def test_forbidden_subtitle_boundary_blocks_reason_and_suffix_particle_splits() -> None:
    assert _is_forbidden_subtitle_boundary("所以说为什么", "我平时比如临时出个门")
    assert _is_forbidden_subtitle_boundary("所以说那也就没啥好说", "的了该升级我们")
    assert _is_forbidden_subtitle_boundary("我们其他博主也是也都发过这款手电", "了我们就简单的做一下展示")


def test_boundary_splits_protected_term_for_info_count_noun() -> None:
    assert _boundary_splits_protected_term("它前头一个功能", "键啊这个功能键是") is True


def test_boundary_splits_generic_word_ignores_explicit_clause_break() -> None:
    from roughcut.speech.subtitle_segmentation import _boundary_splits_generic_word

    assert _boundary_splits_generic_word("这个标", "你长按它就是一个激光") is True
    assert _boundary_splits_generic_word("这个标，", "你长按它就是一个激光") is False


def test_boundary_splits_generic_word_ignores_cross_boundary_bigram_artifacts() -> None:
    from roughcut.speech.subtitle_segmentation import _boundary_splits_generic_word

    cases = [
        ("这个总算这个年还能过", "要不然这个真的是难受。"),
        ("然后一体感很强", "嗯，配合这种通体抛。"),
        ("那个版本的重量呢也非常好", "非常适合EDC啊。"),
        ("什么叫强调", "非常呢？它"),
        ("这个非常近的话", "你实际"),
        ("开啊，就是你用这个指甲直接去", "呃，你用指甲卡住。"),
    ]

    for left, right in cases:
        assert _boundary_splits_generic_word(left, right) is False


def test_normalize_projection_display_text_compacts_internal_cjk_spacing() -> None:
    assert normalize_projection_display_text("然后 呃首先它前头1个功能键啊") == "然后呃首先它前头1个功能键啊"
    assert normalize_projection_display_text("你长按它就是一个激光啊 绿激光") == "你长按它就是一个激光啊绿激光"


def test_entry_needs_residual_repair_for_previous_word_continuation_fragment() -> None:
    previous = SubtitleEntry(index=0, start=0.0, end=1.0, text_raw="然后首先它前头一个功能", text_norm="然后首先它前头一个功能", words=())
    current = SubtitleEntry(index=1, start=1.01, end=2.5, text_raw="键啊这个功能键是这个就是M的这个标你", text_norm="键啊这个功能键是这个就是M的这个标你", words=())

    assert _entry_needs_residual_repair(previous=previous, current=current, following=None) is True


def test_rebalance_semantic_boundaries_moves_suffix_particle_back_to_left_clause() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("我们其他博主也是也都发过", 1.4),
                ("这款手电", 0.7),
            ],
            text="我们其他博主也是也都发过这款手电",
        ),
        _worded_entry(
            1,
            2.12,
            [
                ("了，", 0.2),
                ("我们", 0.32),
                ("就简单的", 0.72),
                ("做一下展示", 0.9),
            ],
            text="了，我们就简单的做一下展示",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "我们其他博主也是也都发过这款手电了，",
        "我们就简单的做一下展示",
    ]


def test_rebalance_semantic_boundaries_moves_subject_head_back_to_right_clause_after_punctuation() -> None:
    entries = [
        _worded_entry(
            0,
            0.0,
            [
                ("这个", 0.3),
                ("功能", 0.3),
                ("键是", 0.3),
                ("这个", 0.3),
                ("就是", 0.4),
                ("M", 0.2),
                ("的", 0.2),
                ("这个", 0.3),
                ("标，", 0.3),
                ("你", 0.2),
            ],
            text="这个功能键是这个就是M的这个标，你",
        ),
        _worded_entry(
            1,
            2.8,
            [
                ("长按", 0.4),
                ("它", 0.3),
                ("就是", 0.4),
                ("一个", 0.4),
                ("激光啊，", 0.5),
                ("绿激光。", 0.5),
            ],
            text="长按它就是一个激光啊，绿激光。",
        ),
    ]

    rebalanced = _rebalance_semantic_boundaries(entries, max_chars=18, max_duration=4.0)

    assert [entry.text_raw for entry in rebalanced] == [
        "这个功能键是这个就是M的这个标，",
        "你长按它就是一个激光啊，绿激光。",
    ]


def test_readability_split_does_not_split_complete_sentence_that_only_exceeds_soft_limit() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("或者说简单的这个", 1.44),
            ("短途的通勤啊", 1.20),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.4)

    assert [item.text_raw for item in split_entries] == ["或者说简单的这个短途的通勤啊"]


def test_readability_split_skips_poor_boundary_when_only_mildly_over_duration() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("这也是为什么我平时", 1.44),
            ("比如临时出个门遛个狗啊", 1.76),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.0)

    assert [item.text_raw for item in split_entries] == ["这也是为什么我平时比如临时出个门遛个狗啊"]


def test_readability_split_does_not_split_short_sentence_for_small_duration_overflow() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("这个是为什么", 1.20),
            ("我平时这么用", 1.35),
            ("的原因", 0.65),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.0)

    assert [item.text_raw for item in split_entries] == ["这个是为什么我平时这么用的原因"]


def test_readability_split_does_not_split_short_sentence_for_subsecond_duration_overflow() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("或者说", 1.10),
            ("简单的这个", 1.45),
            ("短途的通勤啊", 1.29),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.4)

    assert [item.text_raw for item in split_entries] == ["或者说简单的这个短途的通勤啊"]


def test_attached_fragment_detection_does_not_treat_temporal_phrase_as_residual() -> None:
    assert _starts_with_attached_fragment("晚上出门都会带它很实用") is False


def test_readability_split_uses_hard_overflow_fallback_for_closed_clause_boundary() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "我们其他博主也是也都发过这款手电了，我们就简单的做一下展示。",
            "start_time": 175.2,
            "end_time": 181.6,
            "words_json": [
                {"word": "我们", "start": 175.2, "end": 175.76},
                {"word": "其他", "start": 176.88, "end": 177.2},
                {"word": "博主", "start": 177.2, "end": 177.36},
                {"word": "也", "start": 177.36, "end": 177.8},
                {"word": "是", "start": 177.8, "end": 178.24},
                {"word": "也", "start": 178.24, "end": 178.68},
                {"word": "都", "start": 178.68, "end": 179.12},
                {"word": "发过", "start": 179.12, "end": 179.36},
                {"word": "这款", "start": 179.36, "end": 179.6},
                {"word": "手电", "start": 179.6, "end": 179.84},
                {"word": "了，", "start": 179.84, "end": 180.0},
                {"word": "我们", "start": 180.0, "end": 180.24},
                {"word": "就", "start": 180.24, "end": 180.32},
                {"word": "简单", "start": 180.32, "end": 180.64},
                {"word": "的", "start": 180.64, "end": 180.84},
                {"word": "做", "start": 180.84, "end": 181.04},
                {"word": "一下", "start": 181.04, "end": 181.2},
                {"word": "展示。", "start": 181.2, "end": 181.6},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)

    assert [item.text_raw for item in result.entries] == [
        "我们其他博主也是也都发过这款手电了，",
        "我们就简单的做一下展示。",
    ]


def test_readability_split_uses_hard_overflow_fallback_for_punctuated_intro_boundary() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "它前头一个功能键啊，这个功能键是这个就是M的这个标，你",
            "start_time": 183.6,
            "end_time": 189.44,
            "words_json": [
                {"word": "它", "start": 183.6, "end": 183.68},
                {"word": "前头", "start": 183.68, "end": 184.0},
                {"word": "一个", "start": 184.0, "end": 184.16},
                {"word": "功能", "start": 184.16, "end": 184.48},
                {"word": "键啊，", "start": 184.48, "end": 184.8},
                {"word": "这个", "start": 184.8, "end": 185.12},
                {"word": "功能", "start": 185.12, "end": 185.44},
                {"word": "键", "start": 185.44, "end": 185.6},
                {"word": "是", "start": 185.6, "end": 185.84},
                {"word": "这个", "start": 185.84, "end": 186.08},
                {"word": "就是", "start": 186.08, "end": 186.64},
                {"word": "M", "start": 186.64, "end": 186.88},
                {"word": "的", "start": 186.88, "end": 187.04},
                {"word": "这个", "start": 187.04, "end": 187.44},
                {"word": "标，", "start": 187.44, "end": 187.84},
                {"word": "你", "start": 187.84, "end": 189.44},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)

    assert [item.text_raw for item in result.entries] == [
        "它前头一个功能键啊，",
        "这个功能键是这个就是M的这个标，你",
    ]


def test_readability_split_uses_hard_overflow_fallback_for_char_overflow_with_good_restart() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("我把它啊替代了我的EDC23", 1.92),
            ("然后去作为我最新的一个", 1.86),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.4)

    assert [item.text_raw for item in split_entries] == [
        "我把它啊替代了我的EDC23",
        "然后去作为我最新的一个",
    ]


def test_readability_split_uses_punctuation_supported_fallback_for_mild_char_overflow_clause() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("而且它的这个UV的功能啊，", 2.75),
            ("也不是说只限用照明", 1.72),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=20, max_duration=3.8)

    assert [item.text_raw for item in split_entries] == [
        "而且它的这个UV的功能啊，",
        "也不是说只限用照明",
    ]


def test_readability_split_does_not_create_short_incomplete_residual_for_mild_overflow() -> None:
    entry = _worded_entry(
        0,
        0.0,
        [
            ("需要的，所以说那也就没啥好说的了。", 2.55),
            ("该升级。呃，", 0.62),
        ],
    )

    split_entries = _split_readability_overflow_entries([entry], max_chars=18, max_duration=3.0)

    assert [item.text_raw for item in split_entries] == ["需要的，所以说那也就没啥好说的了。该升级。呃，"]


def test_merge_short_chain_entries_merges_short_clause_into_good_break_followon() -> None:
    entries = [
        _worded_entry(0, 0.0, [("很实用", 0.6)]),
        _worded_entry(1, 0.6, [("而且它的这个UV的功能啊，", 2.75)]),
    ]

    merged = _merge_short_chain_entries(entries, max_chars=20, max_duration=3.8)

    assert [item.text_raw for item in merged] == ["很实用而且它的这个UV的功能啊，"]


def test_merge_short_chain_entries_merges_short_followon_clause_leftward() -> None:
    entries = [
        _worded_entry(0, 0.0, [("所以说它的揣在兜里非常轻便，", 2.41)]),
        _worded_entry(1, 2.41, [("呃，非常的无感。", 1.03)]),
    ]

    merged = _merge_short_chain_entries(entries, max_chars=20, max_duration=3.8)

    assert [item.text_raw for item in merged] == ["所以说它的揣在兜里非常轻便，呃，非常的无感。"]


def test_resolve_sequence_merges_orphan_pronoun_into_following_spoken_clause() -> None:
    entries = [
        _worded_entry(0, 0.0, [("当然", 1.93)]),
        _worded_entry(1, 1.93, [("你", 1.41)]),
        _worded_entry(2, 3.34, [("拉开以后你不去固定啊", 2.34)]),
    ]

    resolved = _resolve_subtitle_entry_sequence(entries, max_chars=20, max_duration=3.8, allow_window_refine=True)

    resolved_texts = [item.text_raw for item in resolved]
    assert "你" not in resolved_texts
    assert "".join(resolved_texts) == "当然你拉开以后你不去固定啊"
    assert any("你拉开以后你不去固定啊" in text for text in resolved_texts)


def test_resolve_sequence_repairs_short_followon_clause_after_readability_split() -> None:
    entries = [
        _worded_entry(0, 0.0, [("啊，这个晚上出门都会带它。", 2.41)]),
        _worded_entry(1, 2.41, [("呃，很实用，", 1.03)]),
        _worded_entry(
            2,
            3.44,
            [
                ("而且它的这个UV的功能啊，", 2.75),
                ("也不是说只限用照明", 1.72),
            ],
        ),
    ]

    resolved = _resolve_subtitle_entry_sequence(entries, max_chars=18, max_duration=3.8, allow_window_refine=True)

    assert [item.text_raw for item in resolved] == [
        "啊，这个晚上出门都会带它。",
        "呃，很实用，而且它的这个UV的功能啊，",
        "也不是说只限用照明",
    ]


def test_segmenter_keeps_material_phrases_atomic_after_char_level_retokenize() -> None:
    text = "摸起来油光水润的高抛光就有一种玉质感"
    words = []
    cursor = 10.0
    for char in text:
        words.append({"word": char, "start": cursor, "end": cursor + 0.12})
        cursor += 0.12
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": text,
            "start_time": 10.0,
            "end_time": cursor,
            "words_json": words,
        },
    )()

    result = segment_subtitles([segment], max_chars=6, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(left.endswith("油") and right.startswith("光水润") for left, right in zip(texts, texts[1:]))
    assert any("油光水润" in item for item in texts)
    assert any("玉质感" in item for item in texts)


def test_segmentation_falls_back_to_text_tokens_when_granular_words_do_not_retokenize() -> None:
    text = (
        "这些东西啊，有一个最主要的问题啊，就是说你要符合自己的需求啊。"
        "幺七啊，应该是完美的符合了我所有的这个 EDC 手电的一个要求啊。"
        "啊，它除了少了一个战术的爆闪功能，还有流明盾的功能，其他所有功能每一样都是我需要的，"
        "所以说那也就没啥好说的了。该升级。呃，我们其他博主也是也都发过这款手电了，我们就简单的做一下展示。"
    )
    word_stream = (
        "些东西啊有一个最主要的问题啊就是说你要符合自己的需求啊幺七啊应该是完美的符合了我所有的这个EDC手电的一个要求啊"
        "它除了少了一个战术的爆闪功能还有流明盾的功能其他所有功能每一样都是我需要的所以说那也就没啥好说的了该升级升级呃"
        "我们其他博主也是也都发过这款手电了我们就简单的做一下展示"
    )
    words = []
    cursor = 0.0
    for char in word_stream:
        words.append({"word": char, "start": cursor, "end": cursor + 0.08})
        cursor += 0.08
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": text,
            "start_time": 0.0,
            "end_time": cursor,
            "words_json": words,
        },
    )()

    segmentation_words = _words_for_segmentation(segment)
    result = segment_subtitles([segment], max_chars=18, max_duration=4.8)
    texts = [entry.text_raw for entry in result.entries]

    assert segmentation_words
    assert all(
        str((item.get("alignment") or {}).get("source") or "") == "postprocess_text_fallback"
        for item in segmentation_words
    )
    assert any(item["word"] == "手电" for item in segmentation_words)
    assert any(item["word"] == "了，" for item in segmentation_words)
    assert not any(left.endswith("手电") and right.startswith("了我们") for left, right in zip(texts, texts[1:]))


def test_segmentation_falls_back_when_canonical_realign_short_chunks_have_gap_spikes() -> None:
    text = (
        "该升级。呃，我们其他博主也是也都发过这款手电了，我们就简单的做一下展示。"
        "然后，呃，首先它前头一个功能键啊，这个功能键是这个就是M的这个标，你长按。"
    )
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": text,
            "start_time": 172.0,
            "end_time": 189.8,
            "words_json": [
                {"word": "该升", "start": 172.0, "end": 172.4, "alignment": {"source": "canonical_realign"}},
                {"word": "级。", "start": 172.4, "end": 172.8, "alignment": {"source": "canonical_realign"}},
                {"word": "呃，", "start": 174.2, "end": 175.2, "alignment": {"source": "canonical_realign"}},
                {"word": "我们", "start": 175.2, "end": 175.76, "alignment": {"source": "canonical_realign"}},
                {"word": "其他", "start": 176.88, "end": 177.2, "alignment": {"source": "canonical_realign"}},
                {"word": "博主", "start": 177.2, "end": 177.36, "alignment": {"source": "canonical_realign"}},
                {"word": "也", "start": 177.36, "end": 177.8, "alignment": {"source": "canonical_realign"}},
                {"word": "是", "start": 177.8, "end": 178.24, "alignment": {"source": "canonical_realign"}},
                {"word": "也", "start": 178.24, "end": 178.68, "alignment": {"source": "canonical_realign"}},
                {"word": "都", "start": 178.68, "end": 179.12, "alignment": {"source": "canonical_realign"}},
                {"word": "发过", "start": 179.12, "end": 179.36, "alignment": {"source": "canonical_realign"}},
                {"word": "这款", "start": 179.36, "end": 179.6, "alignment": {"source": "canonical_realign"}},
                {"word": "手电", "start": 179.6, "end": 179.84, "alignment": {"source": "canonical_realign"}},
                {"word": "了，", "start": 179.84, "end": 180.0, "alignment": {"source": "canonical_realign"}},
                {"word": "我们", "start": 180.0, "end": 180.24, "alignment": {"source": "canonical_realign"}},
                {"word": "就", "start": 180.24, "end": 180.32, "alignment": {"source": "canonical_realign"}},
                {"word": "简单", "start": 180.32, "end": 180.64, "alignment": {"source": "canonical_realign"}},
                {"word": "的", "start": 180.64, "end": 180.88, "alignment": {"source": "canonical_realign"}},
                {"word": "做一", "start": 180.88, "end": 181.04, "alignment": {"source": "canonical_realign"}},
                {"word": "下展", "start": 181.04, "end": 181.36, "alignment": {"source": "canonical_realign"}},
                {"word": "示。", "start": 181.36, "end": 181.84, "alignment": {"source": "canonical_realign"}},
                {"word": "然后", "start": 181.84, "end": 182.0, "alignment": {"source": "canonical_realign"}},
                {"word": "呃，", "start": 182.0, "end": 182.4, "alignment": {"source": "canonical_realign"}},
                {"word": "首先", "start": 182.4, "end": 183.0, "alignment": {"source": "canonical_realign"}},
                {"word": "它前", "start": 183.0, "end": 183.6, "alignment": {"source": "canonical_realign"}},
                {"word": "头一", "start": 183.6, "end": 184.0, "alignment": {"source": "canonical_realign"}},
                {"word": "个功", "start": 184.0, "end": 184.48, "alignment": {"source": "canonical_realign"}},
                {"word": "能键", "start": 184.48, "end": 184.8, "alignment": {"source": "canonical_realign"}},
            ],
        },
    )()

    segmentation_words = _words_for_segmentation(segment)
    result = segment_subtitles([segment], max_chars=18, max_duration=3.4)
    texts = [entry.text_raw for entry in result.entries]

    assert segmentation_words
    assert all(
        str((item.get("alignment") or {}).get("source") or "") == "postprocess_text_fallback"
        for item in segmentation_words
    )
    assert any(text == "我们其他博主也是也都发过这款手电了，" for text in texts)
    assert any(text == "我们就简单的做一下展示。" for text in texts)
    assert not any(left.endswith("手电") and right.startswith("了，") for left, right in zip(texts, texts[1:]))


def test_display_text_corrects_material_context_precast_mishearing() -> None:
    assert normalize_display_text("高抛光就有一种预制感吧") == "高抛光就有一种玉质感吧"


def test_segmenter_uses_covering_word_times_for_number_unit_entry() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "这个手电最高1500流明日用够了",
            "start_time": 0.0,
            "end_time": 14.0,
            "words_json": [
                {"word": "这个手电最高", "start": 0.2, "end": 1.4},
                {"word": "1500", "start": 8.0, "end": 8.35},
                {"word": "流明", "start": 8.35, "end": 8.7},
                {"word": "日用", "start": 12.0, "end": 12.4},
                {"word": "够了", "start": 12.4, "end": 12.9},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=4, max_duration=1.0)
    numeric_unit_entry = next(entry for entry in result.entries if "1500流明" in entry.text_raw)

    assert numeric_unit_entry.text_raw == "1500流明"
    assert numeric_unit_entry.start == 8.0
    assert numeric_unit_entry.end == 8.7


def test_segmenter_drops_timestamp_duplicate_homophone_number_word() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "我直接带37了三期了对不对",
            "start_time": 0.0,
            "end_time": 1.6,
            "words_json": [
                {"word": "我直接带", "start": 0.0, "end": 0.4},
                {"word": "37", "start": 0.4, "end": 0.72},
                {"word": "三期", "start": 0.42, "end": 0.72},
                {"word": "了对不对", "start": 0.72, "end": 1.6},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=3.0)

    assert "".join(entry.text_norm for entry in result.entries) == "我直接带37了对不对。"


def test_segmenter_prefers_shorter_readable_rows_before_hard_limit() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "或者说简单的这个短途的通勤啊晚上出门都会带它很实用",
            "start_time": 0.0,
            "end_time": 4.4,
            "words_json": [
                {"word": "或者说", "start": 0.0, "end": 0.45},
                {"word": "简单的这个", "start": 0.45, "end": 1.1},
                {"word": "短途的通勤啊", "start": 1.1, "end": 1.95},
                {"word": "晚上出门", "start": 2.35, "end": 2.95},
                {"word": "都会带它", "start": 2.95, "end": 3.55},
                {"word": "很实用", "start": 3.55, "end": 4.4},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert len(texts) >= 2
    assert texts[0] == "或者说简单的这个短途的通勤啊"
    assert texts[1] == "晚上出门都会带它很实用"


def test_low_confidence_analysis_flags_short_detached_residual_clause_window() -> None:
    entries = [
        _worded_entry(0, 0.0, [("需要的，所以说那也就没啥好说的了。", 1.6)]),
        _worded_entry(1, 1.61, [("该升级。呃", 0.42)]),
        _worded_entry(2, 2.04, [("我们其他博主也是也都发过这款手电了，我们。", 1.8)]),
        _worded_entry(3, 3.9, [("就简单的做一下展示。", 0.9)]),
    ]

    analysis = analyze_subtitle_segmentation(entries)
    windows = list(analysis.low_confidence_windows or ())

    assert _looks_like_short_detached_clause_fragment("该升级。呃") is True
    assert any(
        int(window.get("start_index") or -1) <= 1 <= int(window.get("end_index") or -1)
        for window in windows
    )


def test_low_confidence_analysis_flags_short_detached_followon_clause_window() -> None:
    entries = [
        _worded_entry(0, 0.0, [("这个晚上出门都会带它", 1.2)]),
        _worded_entry(1, 1.21, [("很实用", 0.38)]),
        _worded_entry(2, 1.60, [("而且它的这个UV的功能啊", 1.2)]),
        _worded_entry(3, 2.82, [("也不是说只限用照明", 0.9)]),
    ]

    analysis = analyze_subtitle_segmentation(entries)
    windows = list(analysis.low_confidence_windows or ())

    assert _looks_like_short_detached_clause_fragment("很实用") is True
    assert any(
        int(window.get("start_index") or -1) <= 1 <= int(window.get("end_index") or -1)
        for window in windows
    )


def test_segmenter_keeps_detachable_lead_in_attached_when_split_would_create_residual_clause() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "呃我们其他博主也是也都发过这款手电了",
            "start_time": 0.0,
            "end_time": 5.8,
            "words_json": [
                {"word": "呃，", "start": 0.0, "end": 0.28},
                {"word": "我们其他博主也是也都发过", "start": 0.28, "end": 3.85},
                {"word": "这款手电了", "start": 3.85, "end": 5.8},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert texts == ["呃，我们其他博主也是也都发过这款手电了"]


def test_segmenter_keeps_detachable_lead_in_chain_attached_to_following_clause() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "然后，呃，首先它前头一个功能键啊，这个功能键是这个就是M的这个标。",
            "start_time": 181.84,
            "end_time": 189.44,
            "words_json": [
                {"word": "然后，", "start": 181.84, "end": 182.0},
                {"word": "呃，", "start": 182.0, "end": 183.36},
                {"word": "首先", "start": 183.36, "end": 183.6},
                {"word": "它", "start": 183.6, "end": 183.68},
                {"word": "前头", "start": 183.68, "end": 184.0},
                {"word": "一个", "start": 184.0, "end": 184.16},
                {"word": "功能", "start": 184.16, "end": 184.48},
                {"word": "键啊，", "start": 184.48, "end": 184.8},
                {"word": "这个", "start": 184.8, "end": 185.12},
                {"word": "功能", "start": 185.12, "end": 185.44},
                {"word": "键是", "start": 185.44, "end": 185.76},
                {"word": "这个", "start": 185.76, "end": 186.16},
                {"word": "就是", "start": 186.16, "end": 186.48},
                {"word": "M的", "start": 186.48, "end": 186.8},
                {"word": "这个", "start": 186.8, "end": 187.2},
                {"word": "标。", "start": 187.2, "end": 187.52},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=30, max_duration=5.0)
    texts = [entry.text_raw for entry in result.entries]

    assert texts == ["然后，呃，首先它前头一个功能键啊，这个功能键是这个就是M的这个标。"]


def test_merge_short_chain_entries_merges_detachable_lead_in_chain_rightward() -> None:
    entries = [
        SubtitleEntry(index=0, start=0.0, end=1.0, text_raw="然后，呃，首先", text_norm="然后，呃，首先"),
        SubtitleEntry(
            index=1,
            start=1.0,
            end=4.0,
            text_raw="它前头一个功能键啊，这个功能键是这个就是M的这个标。",
            text_norm="它前头一个功能键啊，这个功能键是这个就是M的这个标。",
        ),
    ]

    merged = _merge_short_chain_entries(entries, max_chars=30, max_duration=5.0)

    assert [entry.text_raw for entry in merged] == [
        "然后，呃，首先它前头一个功能键啊，这个功能键是这个就是M的这个标。"
    ]


def test_merge_short_chain_entries_merges_compacted_detachable_lead_in_chain_rightward() -> None:
    entries = [
        SubtitleEntry(index=0, start=0.0, end=1.0, text_raw="然后首先", text_norm="然后首先"),
        SubtitleEntry(
            index=1,
            start=1.0,
            end=4.0,
            text_raw="它前头1个功能键啊这个功能",
            text_norm="它前头1个功能键啊这个功能",
        ),
    ]

    merged = _merge_short_chain_entries(entries, max_chars=30, max_duration=5.0)

    assert [entry.text_raw for entry in merged] == [
        "然后首先它前头1个功能键啊这个功能"
    ]


def test_transcript_projection_uses_segmented_word_level_times() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "segment_index": 0,
            "text": "这个手电最高1500流明日用够了",
            "start_time": 0.0,
            "end_time": 14.0,
            "words_json": [
                {"word": "这个手电最高", "start": 0.2, "end": 1.4},
                {"word": "1500", "start": 8.0, "end": 8.35},
                {"word": "流明", "start": 8.35, "end": 8.7},
                {"word": "日用", "start": 12.0, "end": 12.4},
                {"word": "够了", "start": 12.4, "end": 12.9},
            ],
        },
    )()

    layer = build_transcript_projection_layer(
        [segment],
        segmentation_analysis={},
        split_profile={"max_chars": 4, "max_duration": 1.0},
        boundary_refine={},
        quality_report={},
    )
    numeric_unit_entry = next(entry for entry in layer.entries if "1500流明" in entry.text_raw)

    assert numeric_unit_entry.text_raw == "1500流明"
    assert numeric_unit_entry.start == 8.0
    assert numeric_unit_entry.end == 8.7


def test_quality_report_warns_single_generic_word_split() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "先介"},
            {"text_final": "绍一下"},
        ],
    )

    assert report["blocking"] is False
    assert report["metrics"]["generic_word_split_count"] == 1
    assert any("普通词跨字幕截断" in reason for reason in report["warning_reasons"])


def test_quality_report_ignores_filler_and_complete_short_noun_boundary_false_positive() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "呃"},
            {"text_final": "包括这他们这个最近一。"},
            {"text_final": "小把手"},
            {"text_final": "你配合这个把手去开它的话， 它。"},
        ],
    )

    assert report["metrics"]["generic_word_split_count"] == 0
    assert not any("普通词跨字幕截断" in reason for reason in report["warning_reasons"])


def test_quality_report_blocks_dense_generic_word_splits() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "这个产"},
            {"text_final": "品不错"},
            {"text_final": "这个设"},
            {"text_final": "计取向"},
            {"text_final": "很有特"},
            {"text_final": "色"},
            {"text_final": "它的手"},
            {"text_final": "感不错"},
            {"text_final": "狐蝠"},
            {"text_final": "工业今年主打"},
            {"text_final": "这个产"},
            {"text_final": "品不错"},
            {"text_final": "这个设"},
            {"text_final": "计取向"},
            {"text_final": "很有特"},
            {"text_final": "色"},
            {"text_final": "它的手"},
            {"text_final": "感不错"},
            {"text_final": "这个产"},
            {"text_final": "品不错"},
        ],
    )

    assert report["blocking"] is True
    assert report["metrics"]["generic_word_split_count"] >= 10
    assert any("普通词跨字幕截断" in reason for reason in report["blocking_reasons"])


def test_quality_report_exposes_alignment_source_metrics_per_subtitle() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {
                "index": 0,
                "text_final": "正常口播",
                "words": [
                    {"word": "正常", "start": 0.0, "end": 0.4, "alignment": {"_roughcut": {"source": "provider"}}},
                    {"word": "口播", "start": 0.4, "end": 0.8, "alignment": {"_roughcut": {"source": "provider"}}},
                ],
            },
            {
                "index": 1,
                "text_final": "合成锚点",
                "words": [
                    {"word": "合成", "start": 1.0, "end": 1.4, "alignment": {"_roughcut": {"source": "synthetic"}}},
                    {"word": "锚点", "start": 1.4, "end": 1.8, "alignment": {"source": "postprocess_text_fallback"}},
                ],
            },
        ],
    )

    alignment = report["metrics"]["alignment_source"]
    assert alignment["word_count"] == 4
    assert alignment["source_counts"] == {"fallback": 1, "provider": 2, "synthetic": 1}
    assert alignment["source_ratios"]["provider"] == 0.5
    assert [item["dominant_source"] for item in alignment["per_subtitle"]] == ["provider", "synthetic"]


def test_quality_report_blocks_when_required_word_alignment_is_missing() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"index": 0, "text_final": "第一句没有词级时间戳"},
            {"index": 1, "text_final": "第二句也没有词级时间戳"},
        ],
        require_word_alignment=True,
    )

    assert report["blocking"] is True
    assert report["score"] <= 65.0
    assert report["metrics"]["alignment_source"]["missing_word_subtitle_count"] == 2
    assert any("缺少词级时间戳覆盖 2/2" in reason for reason in report["blocking_reasons"])


def test_quality_report_suppresses_generic_summary_warning_when_subject_context_is_specific() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[{"text_final": "先介绍一下"}],
        content_profile={
            "subject_brand": "NOC",
            "subject_model": "MT34",
            "summary": "这条视频主要围绕NOC MT34展开，内容方向偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
        },
    )

    assert report["warning_reasons"] == []
    assert report["metrics"]["summary_generic_hits"] == []
    assert report["metrics"]["suppressed_summary_generic_hits"] == ["适合后续做搜索校验、字幕纠错和剪辑包装"]


def test_quality_report_keeps_warning_for_pure_generic_summary_phrase() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[{"text_final": "先介绍一下"}],
        content_profile={
            "summary": "适合后续做搜索校验、字幕纠错和剪辑包装",
        },
    )

    assert any("摘要模板化命中" in reason for reason in report["warning_reasons"])
    assert report["metrics"]["summary_generic_hits"] == ["适合后续做搜索校验、字幕纠错和剪辑包装"]

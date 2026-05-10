from types import SimpleNamespace

from roughcut.pipeline.steps import _project_canonical_transcript_to_timeline, _should_keep_existing_subtitle_projection
from roughcut.speech.subtitle_pipeline import _build_canonical_transcript_words


def test_transcript_review_keeps_better_display_projection_without_accepted_corrections() -> None:
    assert _should_keep_existing_subtitle_projection(
        existing_quality_report={
            "score": 100.0,
            "blocking": False,
            "warning_reasons": [],
            "metrics": {
                "subtitle_count": 147,
                "short_fragment_count": 0,
                "generic_word_split_count": 0,
            },
        },
        refreshed_quality_report={
            "score": 94.09,
            "blocking": False,
            "warning_reasons": ["short fragments"],
            "metrics": {
                "subtitle_count": 204,
                "short_fragment_count": 5,
                "generic_word_split_count": 1,
            },
        },
        canonical_transcript_layer=SimpleNamespace(
            correction_metrics={"accepted_correction_count": 0, "pending_correction_count": 0},
        ),
    )


def test_transcript_review_prefers_canonical_when_human_corrections_exist() -> None:
    assert not _should_keep_existing_subtitle_projection(
        existing_quality_report={
            "score": 100.0,
            "blocking": False,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 147},
        },
        refreshed_quality_report={
            "score": 94.09,
            "blocking": False,
            "warning_reasons": ["short fragments"],
            "metrics": {"subtitle_count": 204},
        },
        canonical_transcript_layer=SimpleNamespace(
            correction_metrics={"accepted_correction_count": 1, "pending_correction_count": 0},
        ),
    )


def test_canonical_projection_splits_overlong_word_tokens_before_segmentation() -> None:
    canonical_layer = {
        "segments": [
            {
                "index": 5,
                "start": 79.17,
                "end": 118.50,
                "text": (
                    "其实我还经常会换一些EDC手电玩呢，为什么三七啊从来没有考虑过给它换掉呢？"
                    "因为它的性能确实是在这个呃尺寸下啊，做到了极致啊，八千流明，然后据说还是虚标的，"
                    "然后实际上能呃峰值能达到一万流明啊。当然那个啊咱们没有官方的数据啊，就不好说了。"
                    "但是这个确实是，呃，其实拿习惯了还是蛮小巧的嘛。但是呢，它作为一个揣兜里的这个嘛EDC"
                    "的手电来说啊，稍微有点重，你放在这个裤兜里啊，它会有点逛荡的感觉。所以呢，我们总归啊是需要有这么一个。"
                ),
                "words": [
                    {"word": "其实我还经常会换一些", "start": 79.17, "end": 81.01, "word_index": 0},
                    {"word": "EDC", "start": 81.01, "end": 81.45, "word_index": 1},
                    {
                        "word": (
                            "手电玩呢，为什么三七啊从来没有考虑过给它换掉呢？"
                            "因为它的性能确实是在这个呃尺寸下啊，做到了极致啊，八千流明，然后据说还是虚标的，"
                            "然后实际上能呃峰值能达到一万流明啊。当然那个啊咱们没有官方的数据啊，就不好说了。"
                            "但是这个确实是，呃，其实拿习惯了还是蛮小巧的嘛。但是呢，它作为一个揣兜里的这个嘛"
                        ),
                        "start": 81.45,
                        "end": 107.94,
                        "word_index": 2,
                    },
                    {"word": "EDC", "start": 107.94, "end": 108.38, "word_index": 3},
                    {
                        "word": "的手电来说啊，稍微有点重，你放在这个裤兜里啊，它会有点逛荡的感觉。所以呢，我们总归啊是需要有这么一个。",
                        "start": 108.38,
                        "end": 118.50,
                        "word_index": 4,
                    },
                ],
            }
        ]
    }

    entries = _project_canonical_transcript_to_timeline(
        canonical_layer,
        [{"start": 0.0, "end": 511.233}],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )

    assert entries
    assert max(item["end_time"] - item["start_time"] for item in entries) <= 8.6
    assert all(len(str(item["text_final"])) <= 40 for item in entries)
    assert not any(
        item["start_time"] == 81.45 and item["end_time"] == 107.94
        for item in entries
    )


def test_canonical_projection_drops_tiny_word_overlap_at_cut_boundary() -> None:
    canonical_layer = {
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 3.0,
                "text": "甲乙丙",
                "words": [
                    {"word": "甲", "start": 0.0, "end": 1.0, "alignment": {"source": "provider"}},
                    {"word": "乙", "start": 1.0, "end": 2.0, "alignment": {"source": "provider"}},
                    {"word": "丙", "start": 2.0, "end": 3.0, "alignment": {"source": "provider"}},
                ],
            }
        ]
    }

    entries = _project_canonical_transcript_to_timeline(
        canonical_layer,
        [{"start": 0.0, "end": 1.1}, {"start": 2.0, "end": 3.0}],
        split_profile={"max_chars": 8, "max_duration": 5.0},
    )

    rendered_text = "".join(item["text_final"] for item in entries)
    assert "甲" in rendered_text
    assert "丙" in rendered_text
    assert "乙" not in rendered_text


def test_canonical_projection_falls_back_when_word_timing_collapses_content() -> None:
    text = (
        "那个S06的迷你款啊，好，我们开开箱吧，"
        "用他的老大哥天敌啊，天敌开个箱。不得不说，"
        "你天敌的这个开箱手感真的是无敌了啊！"
    )
    compressed_tokens = [
        "迷你款啊",
        "好",
        "我们",
        "开开",
        "箱吧",
        "用他",
        "的",
        "老大哥",
        "天敌",
        "啊",
        "天敌",
        "开个箱",
        "不得不说",
    ]
    words = [
        {"word": "那个", "start": 59.0, "end": 59.06, "alignment": {"source": "canonical_realign"}},
        {"word": "S06", "start": 59.3, "end": 59.46, "alignment": {"source": "canonical_realign"}},
        {"word": "的", "start": 59.7, "end": 59.78, "alignment": {"source": "canonical_realign"}},
    ]
    cursor = 59.78
    for token in compressed_tokens:
        next_cursor = cursor + 0.035
        words.append(
            {
                "word": token,
                "start": round(cursor, 3),
                "end": round(next_cursor, 3),
                "alignment": {"source": "canonical_realign", "strategy": "reference_span_interpolate"},
            }
        )
        cursor = next_cursor
    words.extend(
        [
            {"word": "你", "start": 60.42, "end": 60.5, "alignment": {"source": "canonical_realign"}},
            {"word": "天敌", "start": 65.46, "end": 66.18, "alignment": {"source": "canonical_realign"}},
            {"word": "的这个开箱手感", "start": 66.18, "end": 68.34, "alignment": {"source": "canonical_realign"}},
            {"word": "真的是无敌了啊", "start": 68.34, "end": 70.5, "alignment": {"source": "canonical_realign"}},
        ]
    )
    canonical_layer = {
        "segments": [
            {
                "index": 3,
                "start": 59.0,
                "end": 78.5,
                "text": text,
                "words": words,
            }
        ]
    }

    entries = _project_canonical_transcript_to_timeline(
        canonical_layer,
        [{"start": 42.21, "end": 88.417}],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )

    rendered_text = "".join(item["text_final"] for item in entries)
    assert "S06的迷你款" in rendered_text
    assert "老大哥天敌" in rendered_text
    assert "天敌开个箱" in rendered_text
    affected_entries = [
        item
        for item in entries
        if any(token in item["text_final"] for token in ("S06", "老大哥", "天敌开个箱"))
    ]
    assert affected_entries
    assert max(item["end_time"] for item in affected_entries) - min(item["start_time"] for item in affected_entries) > 1.5


def test_canonical_realign_uses_character_units_for_char_level_asr_words() -> None:
    words = _build_canonical_transcript_words(
        "S06的迷你款开箱老大哥天敌",
        start=0.0,
        end=4.5,
        reference_words=(
            {"word": "S06", "start": 0.0, "end": 0.3, "source_index": 0},
            {"word": "的", "start": 0.3, "end": 0.4, "source_index": 1},
            {"word": "迷", "start": 0.4, "end": 0.7, "source_index": 2},
            {"word": "你", "start": 0.7, "end": 1.0, "source_index": 3},
            {"word": "款", "start": 1.0, "end": 1.3, "source_index": 4},
            {"word": "开", "start": 1.3, "end": 1.6, "source_index": 5},
            {"word": "箱", "start": 1.6, "end": 1.9, "source_index": 6},
            {"word": "老", "start": 1.9, "end": 2.2, "source_index": 7},
            {"word": "大", "start": 2.2, "end": 2.5, "source_index": 8},
            {"word": "哥", "start": 2.5, "end": 2.8, "source_index": 9},
            {"word": "天", "start": 2.8, "end": 3.1, "source_index": 10},
            {"word": "敌", "start": 3.1, "end": 3.4, "source_index": 11},
        ),
    )

    by_word = {word.word: word for word in words}
    assert by_word["S06"].alignment["strategy"] == "reference_unit_match"
    assert by_word["迷你款"].start == 0.4
    assert by_word["迷你款"].end == 1.3
    assert by_word["开箱"].start == 1.3
    assert by_word["老大哥"].start == 1.9
    assert by_word["天敌"].start == 2.8


def test_canonical_realign_rejects_short_function_token_as_compressing_anchor() -> None:
    text = "那个S06的迷你款啊，好，我们开开箱吧，用他的老大哥天敌啊，天敌开个箱。不得不说。"
    words = _build_canonical_transcript_words(
        text,
        start=59.0,
        end=78.5,
        reference_words=(
            {"word": "S06", "start": 59.3, "end": 59.46, "source_index": 0},
            {"word": "的", "start": 59.7, "end": 59.78, "source_index": 1},
            {"word": "你", "start": 60.26, "end": 60.42, "source_index": 2},
            {"word": "天", "start": 65.06, "end": 65.22, "source_index": 3},
            {"word": "敌", "start": 65.22, "end": 65.38, "source_index": 4},
        ),
    )

    rendered = "".join(word.word for word in words)
    assert rendered == text
    assert all(words[index].start >= words[index - 1].end - 1e-6 for index in range(1, len(words)))
    risk_block_words = [
        word
        for word in words
        if word.word in {"迷你款", "开开", "箱吧，", "老大哥", "天敌", "开个", "箱。", "不得", "不说。"}
    ]
    assert risk_block_words
    assert max(word.end for word in risk_block_words) - min(word.start for word in risk_block_words) > 3.0
    assert not any(
        word.word == "你" and word.alignment["strategy"] == "reference_unit_match"
        for word in words
    )


def test_canonical_realign_keeps_filler_between_adjacent_anchors_monotonic() -> None:
    words = _build_canonical_transcript_words(
        "你天敌的这个开箱手感",
        start=0.0,
        end=4.0,
        reference_words=(
            {"word": "你", "start": 0.0, "end": 0.2, "source_index": 0},
            {"word": "天", "start": 1.0, "end": 1.2, "source_index": 1},
            {"word": "敌", "start": 1.2, "end": 1.4, "source_index": 2},
            {"word": "这", "start": 1.4, "end": 1.6, "source_index": 3},
            {"word": "个", "start": 1.6, "end": 1.8, "source_index": 4},
            {"word": "开", "start": 2.0, "end": 2.2, "source_index": 5},
            {"word": "箱", "start": 2.2, "end": 2.4, "source_index": 6},
        ),
    )

    by_word = {word.word: word for word in words}
    assert by_word["的"].start == by_word["天敌"].end
    assert by_word["的"].end > by_word["的"].start
    assert by_word["的"].end == by_word["这个"].start
    assert all(words[index].start >= words[index - 1].end - 1e-6 for index in range(1, len(words)))

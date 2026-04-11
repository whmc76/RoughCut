from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem
from roughcut.speech.postprocess import (
    SubtitleEntry,
    _cleanup_subtitle_entries,
    _resolve_fragment_window,
    analyze_subtitle_segmentation,
    generate_subtitle_window_candidates,
    _merge_continuation_entries,
    _should_merge_subtitle_pair,
    normalize_text,
    resegment_subtitle_window_from_cuts,
    segment_subtitles,
    split_into_subtitles,
)
from roughcut.speech.postprocess import save_subtitle_items


def _mock_segment(idx, start, end, text, words=None):
    """Create a mock TranscriptSegment-like object."""
    return SimpleNamespace(
        segment_index=idx,
        start_time=start,
        end_time=end,
        text=text,
        words_json=words,
        speaker=None,
    )


def test_normalize_text_strips():
    assert normalize_text("  hello  ") == "hello"


def test_normalize_text_short_no_punctuation():
    result = normalize_text("好")
    assert result == "好"  # Too short to add punctuation


def test_normalize_text_cleans_mixed_punctuation_tail():
    assert normalize_text("效果非常帅，。") == "效果非常帅。"


def test_normalize_text_converts_display_numbers_and_prunes_fillers():
    assert normalize_text("呃然后这个方案是第二代增强百分之五十有两个档位吧") == "方案是第2代增强50%有2个档位吧。"


def test_normalize_text_keeps_natural_single_count_phrase():
    assert normalize_text("我先看一个整体效果再说") == "我先看一个整体效果再说。"


def test_normalize_text_keeps_vague_quantity_phrase():
    assert normalize_text("这块区域还有两三个气泡") == "这块区域还有两三个气泡。"


def test_normalize_text_formats_info_numbers_dates_and_alpha_numeric_tokens():
    assert (
        normalize_text("这个包装有两个档位三月五号上午八点二十上线a四纸也能放")
        == "包装有2个档位3月5号上午8点20上线A4纸也能放。"
    )


def test_normalize_text_formats_colloquial_price_expression():
    assert normalize_text("这套配置今天只要十九块九") == "这套配置今天只要19块9。"


def test_normalize_text_formats_spaced_model_token():
    assert normalize_text("现在默认转写模型是g p t 四 o") == "现在默认转写模型是GPT-4o。"


def test_normalize_text_adds_soft_clause_spacing_for_long_sentence():
    result = normalize_text("这把刀我觉得非常实用因为螺丝细节也处理得很好")
    assert " 因为" in result


def test_split_into_subtitles_basic():
    segs = [_mock_segment(0, 0.0, 5.0, "这是一段很长的测试文本，用于验证字幕分割功能是否正常工作")]
    entries = split_into_subtitles(segs, max_chars=15, max_duration=5.0)
    assert len(entries) > 1
    for e in entries:
        assert len(e.text_raw) <= 15


def test_split_into_subtitles_with_words():
    words = [
        {"word": "你好", "start": 0.0, "end": 0.5},
        {"word": "世界", "start": 0.5, "end": 1.0},
        {"word": "这是", "start": 1.0, "end": 1.5},
        {"word": "测试", "start": 1.5, "end": 2.0},
    ]
    segs = [_mock_segment(0, 0.0, 2.0, "你好世界这是测试", words=words)]
    entries = split_into_subtitles(segs, max_chars=4, max_duration=5.0)
    assert len(entries) >= 2
    assert entries[0].start == 0.0


def test_split_preserves_timing():
    segs = [
        _mock_segment(0, 0.0, 2.0, "第一句"),
        _mock_segment(1, 3.0, 5.0, "第二句"),
    ]
    entries = split_into_subtitles(segs)
    assert entries[0].start == 0.0
    assert entries[1].start == 3.0


def test_split_into_subtitles_prefers_natural_clause_boundary():
    segs = [
        _mock_segment(
            0,
            0.0,
            5.0,
            "这把刀我觉得非常实用因为螺丝细节也处理得很好",
        )
    ]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=5.0)

    assert len(entries) == 2
    assert entries[0].text_raw == "这把刀我觉得非常实用"
    assert entries[1].text_raw == "因为螺丝细节也处理得很好"


def test_split_into_subtitles_merges_particle_led_continuation():
    words = [
        {"word": "这个", "start": 0.0, "end": 0.3},
        {"word": "螺丝", "start": 0.3, "end": 0.7},
        {"word": "是", "start": 0.7, "end": 0.9},
        {"word": "T8", "start": 0.9, "end": 1.2},
        {"word": "的", "start": 1.2, "end": 1.35},
        {"word": "然后", "start": 1.35, "end": 1.7},
        {"word": "拆", "start": 1.7, "end": 2.0},
        {"word": "起来", "start": 2.0, "end": 2.4},
        {"word": "很", "start": 2.4, "end": 2.6},
        {"word": "方便", "start": 2.6, "end": 3.0},
    ]
    segs = [_mock_segment(0, 0.0, 3.0, "这个螺丝是T8的然后拆起来很方便", words=words)]

    entries = split_into_subtitles(segs, max_chars=8, max_duration=5.0)

    assert len(entries) == 2
    assert not entries[0].text_raw.endswith("然后")
    assert not entries[1].text_raw.startswith(("的", "起来"))


def test_short_fragment_pair_is_marked_for_merge():
    assert _should_merge_subtitle_pair("然后主体使", "用了彩雕，激光彩雕") is True


def test_split_avoids_cutting_protected_domain_term():
    segs = [
        _mock_segment(
            0,
            0.0,
            4.0,
            "并且整体采用了一个很自然的渐变效果",
        )
    ]

    entries = split_into_subtitles(segs, max_chars=11, max_duration=5.0)

    assert len(entries) >= 2
    assert all(not entry.text_raw.endswith("渐") for entry in entries)
    assert all(not entry.text_raw.startswith("变") for entry in entries)


def test_merge_single_char_fragment_with_punctuation():
    assert _should_merge_subtitle_pair("并且整体采用了一个非常均匀柔和的阳极渐变", "度，渐变的效果") is True


def test_split_merges_short_continuation_even_with_longer_duration():
    words = [
        {"word": "然后", "start": 0.0, "end": 0.8},
        {"word": "主体", "start": 0.8, "end": 1.8},
        {"word": "使", "start": 1.8, "end": 2.9},
        {"word": "用", "start": 2.9, "end": 3.8},
        {"word": "了", "start": 3.8, "end": 4.4},
        {"word": "彩雕", "start": 4.4, "end": 5.8},
        {"word": "激光", "start": 5.8, "end": 6.8},
        {"word": "彩雕", "start": 6.8, "end": 7.8},
    ]
    segs = [_mock_segment(0, 0.0, 7.8, "然后主体使用了彩雕激光彩雕", words=words)]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=5.0)

    assert len(entries) == 1
    assert entries[0].text_raw == "然后主体使用了彩雕激光彩雕"


def test_split_into_subtitles_drops_zero_duration_and_collapses_repeated_duplicates():
    words = [
        {"word": "这些", "start": 0.0, "end": 0.5},
        {"word": "配置", "start": 0.5, "end": 1.0},
        {"word": "尽量", "start": 1.0, "end": 1.4},
        {"word": "这些", "start": 1.42, "end": 1.8},
        {"word": "配置", "start": 1.8, "end": 2.2},
        {"word": "尽量", "start": 2.2, "end": 2.6},
        {"word": "", "start": 2.6, "end": 2.6},
    ]
    segs = [_mock_segment(0, 0.0, 2.6, "这些配置尽量这些配置尽量", words=words)]

    entries = split_into_subtitles(segs, max_chars=6, max_duration=1.4)

    assert len(entries) == 1
    assert entries[0].text_raw == "这些配置尽量"
    assert entries[0].end > entries[0].start


def test_split_into_subtitles_collapses_adjacent_near_duplicates():
    segs = [
        _mock_segment(0, 0.0, 0.9, "其实也算一个呼应"),
        _mock_segment(1, 0.96, 1.9, "其实也算上是一个呼应"),
    ]

    entries = split_into_subtitles(segs, max_chars=20, max_duration=4.0)

    assert len(entries) == 1
    assert entries[0].text_raw == "其实也算上是一个呼应"
    assert entries[0].start == 0.0
    assert entries[0].end == 1.9


def test_split_into_subtitles_bridges_long_pause_for_short_sentence_tail():
    segs = [
        _mock_segment(0, 0.0, 1.6, "这个结构我觉得已经很顺手"),
        _mock_segment(1, 4.3, 4.9, "了"),
    ]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=2.6)

    assert len(entries) == 1
    assert entries[0].text_raw == "这个结构我觉得已经很顺手了"
    assert entries[0].start == 0.0
    assert entries[0].end == 4.9


def test_split_into_subtitles_rebalances_leading_fragment_back_to_previous_sentence():
    segs = [
        _mock_segment(
            0,
            0.0,
            2.4,
            "这个纹理处理得很细",
            words=[
                {"word": "这个", "start": 0.0, "end": 0.4},
                {"word": "纹理", "start": 0.4, "end": 0.9},
                {"word": "处理", "start": 0.9, "end": 1.4},
                {"word": "得", "start": 1.4, "end": 1.6},
                {"word": "很", "start": 1.6, "end": 1.9},
                {"word": "细", "start": 1.9, "end": 2.4},
            ],
        ),
        _mock_segment(
            1,
            4.0,
            5.9,
            "腻而且握持更稳",
            words=[
                {"word": "腻", "start": 4.0, "end": 4.3},
                {"word": "而且", "start": 4.3, "end": 4.8},
                {"word": "握持", "start": 4.8, "end": 5.2},
                {"word": "更", "start": 5.2, "end": 5.4},
                {"word": "稳", "start": 5.4, "end": 5.9},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=2.6)

    assert len(entries) == 2
    assert entries[0].text_raw == "这个纹理处理得很细腻"
    assert entries[0].end == 4.3
    assert entries[1].text_raw == "而且握持更稳"
    assert entries[1].start == 4.3


def test_merge_continuation_entries_holds_short_plain_text_fragment():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=3.12,
            text_raw="好这个一",
            text_norm=normalize_text("好这个一"),
        ),
        SubtitleEntry(
            index=1,
            start=3.12,
            end=6.24,
            text_raw="个新的包装它也会送点儿",
            text_norm=normalize_text("个新的包装它也会送点儿"),
        ),
    ]

    merged = _merge_continuation_entries(entries, max_chars=12, max_duration=2.6)

    assert len(merged) == 1
    assert merged[0].text_raw == "好这个一个新的包装它也会送点儿"


def test_split_into_subtitles_rebalances_incomplete_prefix_across_neighbor_segments():
    segs = [
        _mock_segment(
            0,
            0.0,
            1.2,
            "可以把你的",
            words=[
                {"word": "可以", "start": 0.0, "end": 0.35},
                {"word": "把", "start": 0.35, "end": 0.55},
                {"word": "你", "start": 0.55, "end": 0.75},
                {"word": "的", "start": 0.75, "end": 1.2},
            ],
        ),
        _mock_segment(
            1,
            2.1,
            2.7,
            "小药丸",
            words=[
                {"word": "小", "start": 2.1, "end": 2.3},
                {"word": "药丸", "start": 2.3, "end": 2.7},
            ],
        ),
        _mock_segment(
            2,
            2.9,
            4.5,
            "直接做一个弹出式",
            words=[
                {"word": "直接", "start": 2.9, "end": 3.3},
                {"word": "做", "start": 3.3, "end": 3.55},
                {"word": "一个", "start": 3.55, "end": 3.95},
                {"word": "弹出式", "start": 3.95, "end": 4.5},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=2.6)

    assert len(entries) == 2
    assert entries[0].text_raw.startswith("可以把你的小药丸")
    assert not any(entry.text_raw == "可以把你的" for entry in entries)
    assert any("弹出式" in entry.text_raw for entry in entries)


def test_merge_continuation_entries_merges_continuous_broken_phrase_window():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=0.7,
            text_raw="犯困啊或者说需",
            text_norm=normalize_text("犯困啊或者说需"),
        ),
        SubtitleEntry(
            index=1,
            start=0.7,
            end=1.4,
            text_raw="要提神的时候",
            text_norm=normalize_text("要提神的时候"),
        ),
        SubtitleEntry(
            index=2,
            start=1.4,
            end=2.1,
            text_raw="啊来这么一颗我跟你说",
            text_norm=normalize_text("啊来这么一颗我跟你说"),
        ),
    ]

    merged = _merge_continuation_entries(entries, max_chars=12, max_duration=3.0)

    assert len(merged) == 2
    assert merged[0].text_raw == "犯困啊或者说需要提神的时候"
    assert merged[1].text_raw == "啊来这么一颗我跟你说"


def test_split_into_subtitles_attaches_prefix_across_a_short_fragment_window():
    segs = [
        _mock_segment(
            0,
            0.0,
            0.9,
            "可以把你的",
            words=[
                {"word": "可以", "start": 0.0, "end": 0.25},
                {"word": "把", "start": 0.25, "end": 0.45},
                {"word": "你", "start": 0.45, "end": 0.6},
                {"word": "的", "start": 0.6, "end": 0.9},
            ],
        ),
        _mock_segment(
            1,
            1.0,
            1.6,
            "小药丸",
            words=[
                {"word": "小", "start": 1.0, "end": 1.2},
                {"word": "药丸", "start": 1.2, "end": 1.6},
            ],
        ),
        _mock_segment(
            2,
            1.75,
            2.35,
            "直接做一个",
            words=[
                {"word": "直接", "start": 1.75, "end": 2.0},
                {"word": "做一个", "start": 2.0, "end": 2.35},
            ],
        ),
        _mock_segment(
            3,
            2.45,
            3.05,
            "弹出式",
            words=[
                {"word": "弹出式", "start": 2.45, "end": 3.05},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=12, max_duration=2.6)

    assert len(entries) == 2
    assert entries[0].text_raw.startswith("可以把你的小药丸")
    assert any(entry.text_raw.endswith("弹出式") for entry in entries)
    assert not any(entry.text_raw in {"可以把你的", "小药丸"} for entry in entries)


def test_merge_continuation_entries_merges_punctuation_masked_middle_fragment_window():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.45,
            text_raw="这个纹理处理得很细",
            text_norm=normalize_text("这个纹理处理得很细"),
        ),
        SubtitleEntry(
            index=1,
            start=1.45,
            end=1.72,
            text_raw="腻，",
            text_norm=normalize_text("腻，"),
        ),
        SubtitleEntry(
            index=2,
            start=1.72,
            end=3.1,
            text_raw="而且握持更稳",
            text_norm=normalize_text("而且握持更稳"),
        ),
    ]

    merged = _merge_continuation_entries(entries, max_chars=12, max_duration=2.6)

    assert len(merged) == 2
    assert merged[0].text_raw == "这个纹理处理得很细腻，"
    assert merged[1].text_raw == "而且握持更稳"
    assert not any(entry.text_raw == "腻，" for entry in merged)


def test_segment_subtitles_reports_low_confidence_window_samples():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=0.8,
            text_raw="犯困啊或者说需",
            text_norm=normalize_text("犯困啊或者说需"),
        ),
        SubtitleEntry(
            index=1,
            start=0.8,
            end=1.6,
            text_raw="要提神的时候啊来这么一颗",
            text_norm=normalize_text("要提神的时候啊来这么一颗"),
        ),
        SubtitleEntry(
            index=2,
            start=1.6,
            end=2.4,
            text_raw="我跟你说",
            text_norm=normalize_text("我跟你说"),
        ),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["low_confidence_window_count"] >= 1
    assert analysis["sample_low_confidence_windows"]
    assert any("犯困啊或者说需" in "".join(window["texts"]) for window in analysis["sample_low_confidence_windows"])


def test_analyze_subtitle_segmentation_ignores_long_gap_repeated_prefix_boundary():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=2.0,
            text_raw="实惠的一个小装备了好那我们",
            text_norm=normalize_text("实惠的一个小装备了好那我们"),
        ),
        SubtitleEntry(
            index=1,
            start=10.8,
            end=12.6,
            text_raw="好那我们这期就到这吧下期再见",
            text_norm=normalize_text("好那我们这期就到这吧下期再见"),
        ),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["suspicious_boundary_count"] == 0
    assert analysis["low_confidence_window_count"] == 0


def test_analyze_subtitle_segmentation_ignores_particle_led_new_sentence_boundary():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=2.0,
            text_raw="如果是小腰包可能你装一些比较大的东西就不太合适了",
            text_norm=normalize_text("如果是小腰包可能你装一些比较大的东西就不太合适了"),
        ),
        SubtitleEntry(
            index=1,
            start=2.1,
            end=4.4,
            text_raw="啊呃这期我们从实用的角度给大家介绍一下",
            text_norm=normalize_text("啊呃这期我们从实用的角度给大家介绍一下"),
        ),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["suspicious_boundary_count"] == 0
    assert analysis["low_confidence_window_count"] == 0


def test_resegment_subtitle_window_from_cuts_supports_entries_without_word_timings():
    entries = [
        SubtitleEntry(index=0, start=0.0, end=1.0, text_raw="犯困啊或者说需", text_norm=normalize_text("犯困啊或者说需")),
        SubtitleEntry(index=1, start=1.0, end=2.0, text_raw="要提神", text_norm=normalize_text("要提神")),
    ]

    rebuilt = resegment_subtitle_window_from_cuts(entries, cut_after_word_indices=[7])

    assert rebuilt is not None
    assert [entry.text_raw for entry in rebuilt] == ["犯困啊或者说需要", "提神"]


def test_generate_subtitle_window_candidates_considers_text_fallback_when_word_tokens_are_dirty():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.0,
            text_raw="这边做了一个很好的包装",
            text_norm=normalize_text("这边做了一个很好的包装"),
            words=(
                {"word": "这边", "start": 0.0, "end": 0.2},
                {"word": "做了", "start": 0.2, "end": 0.4},
                {"word": "一个", "start": 0.4, "end": 0.6},
                {"word": "很好的", "start": 0.6, "end": 0.8},
                {"word": "包装", "start": 0.8, "end": 1.0},
            ),
        ),
        SubtitleEntry(
            index=1,
            start=1.0,
            end=2.0,
            text_raw="因为我们通常来说这个口香糖",
            text_norm=normalize_text("因为我们通常来说这个口香糖"),
            words=(
                {"word": "为", "start": 1.0, "end": 1.15},
                {"word": "我们", "start": 1.15, "end": 1.35},
                {"word": "通常", "start": 1.35, "end": 1.55},
                {"word": "来说", "start": 1.55, "end": 1.75},
                {"word": "这个", "start": 1.75, "end": 1.9},
                {"word": "口香糖", "start": 1.9, "end": 2.0},
            ),
        ),
        SubtitleEntry(
            index=2,
            start=2.0,
            end=3.0,
            text_raw="还是要做一个出仓式设计",
            text_norm=normalize_text("还是要做一个出仓式设计"),
            words=(
                {"word": "还是", "start": 2.0, "end": 2.2},
                {"word": "要", "start": 2.2, "end": 2.35},
                {"word": "做", "start": 2.35, "end": 2.5},
                {"word": "一个", "start": 2.5, "end": 2.7},
                {"word": "出仓式", "start": 2.7, "end": 2.9},
                {"word": "设计", "start": 2.9, "end": 3.0},
            ),
        ),
    ]

    candidates = generate_subtitle_window_candidates(entries, max_chars=18, max_duration=3.4, top_k=4)

    assert candidates
    assert any("因为我们" in "".join(entry.text_raw for entry in candidate) for candidate in candidates)


def test_resolve_fragment_window_rebalances_plain_text_boundary_without_word_timings():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.0,
            text_raw="犯困啊或者说需",
            text_norm=normalize_text("犯困啊或者说需"),
        ),
        SubtitleEntry(
            index=1,
            start=1.0,
            end=1.8,
            text_raw="要提神",
            text_norm=normalize_text("要提神"),
        ),
    ]

    rebuilt = _resolve_fragment_window(entries, max_chars=13, max_duration=2.4)

    assert rebuilt is not None
    assert [entry.text_raw for entry in rebuilt] == ["犯困啊或者说需要提神"]


def test_cleanup_subtitle_entries_trims_adjacent_overlap_prefix():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.0,
            text_raw="实惠的一个小装备了好那我们",
            text_norm=normalize_text("实惠的一个小装备了好那我们"),
        ),
        SubtitleEntry(
            index=1,
            start=1.05,
            end=2.0,
            text_raw="好那我们这期就到这吧",
            text_norm=normalize_text("好那我们这期就到这吧"),
        ),
    ]

    cleaned = _cleanup_subtitle_entries(entries)

    assert [entry.text_raw for entry in cleaned] == ["实惠的一个小装备了好那我们", "这期就到这吧"]


def test_cleanup_subtitle_entries_trims_overlap_prefix_with_moderate_gap():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.0,
            text_raw="实惠的一个小装备了好那我们",
            text_norm=normalize_text("实惠的一个小装备了好那我们"),
        ),
        SubtitleEntry(
            index=1,
            start=1.32,
            end=2.2,
            text_raw="好那我们这期就到这吧下期再见",
            text_norm=normalize_text("好那我们这期就到这吧下期再见"),
        ),
    ]

    cleaned = _cleanup_subtitle_entries(entries)

    assert [entry.text_raw for entry in cleaned] == ["实惠的一个小装备了好那我们", "这期就到这吧下期再见"]


def test_cleanup_subtitle_entries_iteratively_trims_repeated_prefix_overlap():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.0,
            text_raw="啊我们看它的第二个仓",
            text_norm=normalize_text("啊我们看它的第二个仓"),
        ),
        SubtitleEntry(
            index=1,
            start=1.05,
            end=2.2,
            text_raw="第二个第二个仓相当于它的这个副仓",
            text_norm=normalize_text("第二个第二个仓相当于它的这个副仓"),
        ),
    ]

    cleaned = _cleanup_subtitle_entries(entries)

    assert [entry.text_raw for entry in cleaned] == ["啊我们看它的第二个仓", "相当于它的这个副仓"]


def test_should_merge_subtitle_pair_for_unclosed_nominal_phrase_boundary():
    assert _should_merge_subtitle_pair("一个这个密封的这个", "弹夹包啊然后这边一般") is True


def test_should_merge_subtitle_pair_for_compound_term_boundary():
    assert _should_merge_subtitle_pair("啊呃这期我们从实用的角", "度给大家介绍一下鸿福的这个用料啊我们就不") is True
    assert _should_merge_subtitle_pair("这个压胶拉链还是呃为了防水性啊牺牲了一", "定的这个呃牺牲了一定的这个开袋的手感啊但") is True
    assert _should_merge_subtitle_pair("小刀收纳包仓啊呃这边这个大", "网兜呢你放这个零五啊就非常好OK了啊") is True
    assert _should_merge_subtitle_pair("当然正常来说带着K", "片的不会放的包里啊你应该别在腰带上") is True


def test_split_into_subtitles_normalizes_filler_words_and_numbers_for_display():
    segs = [_mock_segment(0, 0.0, 2.0, "呃然后这个包装小了一圈有两个档位吧")]

    entries = split_into_subtitles(segs, max_chars=20, max_duration=5.0)

    assert len(entries) == 1
    assert entries[0].text_raw == "呃然后这个包装小了一圈有两个档位吧"
    assert entries[0].text_norm == "包装小了一圈有2个档位吧。"


@pytest.mark.asyncio
async def test_save_subtitle_items_replaces_existing_rows_for_same_job_version(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    initial_entries = split_into_subtitles([_mock_segment(0, 0.0, 2.0, "第一句第二句")], max_chars=4, max_duration=5.0)
    replacement_entries = split_into_subtitles([_mock_segment(0, 0.0, 1.0, "第三句")], max_chars=8, max_duration=5.0)

    async with factory() as session:
        items = await save_subtitle_items(job_id, initial_entries, session)
        session.add(
            SubtitleCorrection(
                job_id=job_id,
                subtitle_item_id=items[0].id,
                original_span="第一句",
                suggested_span="第一句",
                change_type="glossary",
                confidence=1.0,
            )
        )
        session.add(
            FactClaim(
                job_id=job_id,
                subtitle_item_id=items[0].id,
                claim_text="第一句",
                risk_level="low",
            )
        )
        await session.commit()

    async with factory() as session:
        await save_subtitle_items(job_id, replacement_entries, session)
        await session.commit()

    async with factory() as session:
        item_rows = (
            await session.execute(select(SubtitleItem).where(SubtitleItem.job_id == job_id).order_by(SubtitleItem.item_index))
        ).scalars().all()
        correction_rows = (await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))).scalars().all()
        claim_rows = (await session.execute(select(FactClaim).where(FactClaim.job_id == job_id))).scalars().all()

    assert len(item_rows) == len(replacement_entries)
    assert [item.text_raw for item in item_rows] == [entry.text_raw for entry in replacement_entries]
    assert correction_rows == []
    assert claim_rows == []

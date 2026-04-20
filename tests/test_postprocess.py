from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem
import roughcut.speech.subtitle_segmentation as subtitle_segmentation
from roughcut.speech.postprocess import (
    SubtitleEntry,
    _cleanup_subtitle_entries,
    _looks_like_split_measure_phrase,
    _resolve_fragment_window,
    analyze_subtitle_segmentation,
    cleanup_subtitle_fillers,
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


def test_normalize_text_formats_multi_letter_model_token_with_spoken_digits():
    assert normalize_text("另外一把就是这个edc幺七然后之前那把是edc三七") == "另外1把就是这个EDC17 然后之前那把是EDC37。"


def test_normalize_text_collapses_repeated_model_number_suffix():
    assert normalize_text("弟就是这个edc二三啊二三已经") == "弟就是这个EDC23已经。"


def test_normalize_text_repairs_common_hot_term_aliases():
    assert normalize_text("这次主要看威虎版的外观处理") == "这次主要看微弧版的外观处理。"
    assert normalize_text("呃铝合金CAC的这个外壳") == "铝合金CNC的这个外壳。"


def test_cleanup_subtitle_fillers_drops_low_signal_short_clauses():
    assert cleanup_subtitle_fillers("嗯今天，啊这个什么呢，待会再说那个刀，哎哦对") == ""


def test_cleanup_subtitle_fillers_keeps_meaningful_short_domain_clause():
    assert cleanup_subtitle_fillers("镜面") == "镜面"


def test_normalize_text_adds_soft_clause_spacing_for_long_sentence():
    result = normalize_text("这把刀我觉得非常实用因为螺丝细节也处理得很好")
    assert " 因为" in result


def test_split_into_subtitles_basic():
    segs = [_mock_segment(0, 0.0, 5.0, "这是一段很长的测试文本，用于验证字幕分割功能是否正常工作")]
    entries = split_into_subtitles(segs, max_chars=15, max_duration=5.0)
    assert len(entries) > 1
    for e in entries:
        assert len(e.text_raw) <= 16


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


def test_segment_subtitles_falls_back_when_global_word_segmentation_returns_empty(monkeypatch):
    segs = [
        _mock_segment(
            0,
            0.0,
            2.0,
            "今天来开箱",
            words=[
                {"word": "今天", "start": 0.0, "end": 0.5},
                {"word": "来", "start": 0.5, "end": 0.8},
                {"word": "开箱", "start": 0.8, "end": 1.3},
            ],
        ),
        _mock_segment(
            1,
            2.2,
            4.0,
            "看看细节",
            words=[
                {"word": "看看", "start": 2.2, "end": 2.8},
                {"word": "细节", "start": 2.8, "end": 3.5},
            ],
        ),
    ]
    monkeypatch.setattr(
        subtitle_segmentation,
        "_segment_subtitles_from_global_words",
        lambda *args, **kwargs: [],
    )

    result = segment_subtitles(segs, max_chars=6, max_duration=2.0)

    assert len(result.entries) >= 2
    assert result.entries[0].text_raw


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


def test_split_into_subtitles_keeps_short_emphasis_repetition():
    segs = [_mock_segment(0, 0.0, 1.2, "真的好久好久没见了")]

    entries = split_into_subtitles(segs, max_chars=20, max_duration=3.0)

    assert len(entries) == 1
    assert entries[0].text_raw == "真的好久好久没见了"


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


def test_resolve_subtitle_entry_sequence_compacts_micro_fragments_from_one_long_source_segment():
    segment_start = 0.0
    segment_end = 32.0
    entries = [
        SubtitleEntry(
            index=0,
            start=25.64,
            end=26.82,
            text_raw="没想到",
            text_norm=normalize_text("没想到"),
            words=(
                {"word": "没想到", "start": 25.64, "end": 26.82, "segment_index": 0, "segment_start": segment_start, "segment_end": segment_end},
            ),
        ),
        SubtitleEntry(
            index=1,
            start=28.48,
            end=31.34,
            text_raw="这次也是啊",
            text_norm=normalize_text("这次也是啊"),
            words=(
                {"word": "这次也是啊", "start": 28.48, "end": 31.34, "segment_index": 0, "segment_start": segment_start, "segment_end": segment_end},
            ),
        ),
        SubtitleEntry(
            index=2,
            start=31.4,
            end=32.56,
            text_raw="我2次抢",
            text_norm=normalize_text("我2次抢"),
            words=(
                {"word": "我2次抢", "start": 31.4, "end": 32.56, "segment_index": 0, "segment_start": segment_start, "segment_end": segment_end},
            ),
        ),
    ]

    resolved = subtitle_segmentation._resolve_subtitle_entry_sequence(
        entries,
        max_chars=18,
        max_duration=3.4,
        allow_window_refine=False,
    )

    assert len(resolved) == 1
    assert resolved[0].text_raw == "没想到这次也是啊我2次抢"


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


def test_merge_short_chain_entries_repairs_punctuation_masked_compound_fragment():
    entries = [
        SubtitleEntry(index=0, start=0.0, end=0.52, text_raw="联。", text_norm=normalize_text("联。")),
        SubtitleEntry(index=1, start=0.52, end=2.48, text_raw="名的之前他们已经出了一个托特包", text_norm=normalize_text("名的之前他们已经出了一个托特包")),
        SubtitleEntry(index=2, start=2.56, end=4.48, text_raw="网上也是好评不断", text_norm=normalize_text("网上也是好评不断")),
    ]

    merged = subtitle_segmentation._merge_short_chain_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged][:2] == [
        "联名的之前他们已经出了一个托特包",
        "网上也是好评不断",
    ]


def test_merge_same_source_segment_micro_fragments_compacts_two_entry_short_run():
    segment_start = 0.0
    segment_end = 22.0
    entries = [
        SubtitleEntry(
            index=0,
            start=8.2,
            end=9.0,
            text_raw="前3天",
            text_norm=normalize_text("前3天"),
            words=(
                {"word": "前3天", "start": 8.2, "end": 9.0, "segment_index": 0, "segment_start": segment_start, "segment_end": segment_end},
            ),
        ),
        SubtitleEntry(
            index=1,
            start=9.36,
            end=12.64,
            text_raw="根本就弹不开就纳闷了",
            text_norm=normalize_text("根本就弹不开就纳闷了"),
            words=(
                {
                    "word": "根本就弹不开就纳闷了",
                    "start": 9.36,
                    "end": 12.64,
                    "segment_index": 0,
                    "segment_start": segment_start,
                    "segment_end": segment_end,
                },
            ),
        ),
    ]

    merged = subtitle_segmentation._merge_same_source_segment_micro_fragments(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == ["前3天根本就弹不开就纳闷了"]


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


def test_analyze_subtitle_segmentation_collects_fragment_window_for_trailing_residual_entry():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=1.8,
            text_raw="这把我已经用了很久",
            text_norm=normalize_text("这把我已经用了很久"),
        ),
        SubtitleEntry(
            index=1,
            start=1.8,
            end=2.3,
            text_raw="我一直",
            text_norm=normalize_text("我一直"),
        ),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["low_confidence_window_count"] >= 1
    assert analysis["sample_low_confidence_windows"]


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


def test_cleanup_subtitle_entries_keeps_repetition_with_say_three_times_cue():
    entries = [
        SubtitleEntry(
            index=0,
            start=0.0,
            end=2.0,
            text_raw="重要的事情说三遍重要的事情说三遍重要的事情说三遍",
            text_norm=normalize_text("重要的事情说三遍重要的事情说三遍重要的事情说三遍"),
        ),
    ]

    cleaned = _cleanup_subtitle_entries(entries)

    assert [entry.text_raw for entry in cleaned] == ["重要的事情说三遍重要的事情说三遍重要的事情说三遍"]


def test_should_merge_subtitle_pair_for_unclosed_nominal_phrase_boundary():
    assert _should_merge_subtitle_pair("一个这个密封的这个", "弹夹包啊然后这边一般") is True


def test_should_merge_subtitle_pair_for_compound_term_boundary():
    assert _should_merge_subtitle_pair("啊呃这期我们从实用的角", "度给大家介绍一下鸿福的这个用料啊我们就不") is True
    assert _should_merge_subtitle_pair("这个压胶拉链还是呃为了防水性啊牺牲了一", "定的这个呃牺牲了一定的这个开袋的手感啊但") is True
    assert _should_merge_subtitle_pair("小刀收纳包仓啊呃这边这个大", "网兜呢你放这个零五啊就非常好OK了啊") is True
    assert _should_merge_subtitle_pair("当然正常来说带着K", "片的不会放的包里啊你应该别在腰带上") is True


def test_should_merge_subtitle_pair_for_single_char_residual_boundary():
    assert _should_merge_subtitle_pair("何借力就是直", "接开就行了这都得") is True


def test_merge_continuation_entries_repairs_single_char_residual_boundary():
    entries = [
        SubtitleEntry(index=0, start=503.844, end=505.489, text_raw="何借力就是直", text_norm=normalize_text("何借力就是直")),
        SubtitleEntry(index=1, start=505.489, end=507.637, text_raw="接开就行了这都得", text_norm=normalize_text("接开就行了这都得")),
    ]

    merged = _merge_continuation_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == ["何借力就是直接开就行了这都得"]


def test_merge_short_chain_entries_merges_trailing_single_char_residual():
    entries = [
        SubtitleEntry(index=0, start=0.0, end=2.4, text_raw="然后当你蓄力比较足的时候就是一个弹开的这么一个效", text_norm=normalize_text("然后当你蓄力比较足的时候就是一个弹开的这么一个效")),
        SubtitleEntry(index=1, start=2.4, end=2.54, text_raw="果", text_norm=normalize_text("果")),
        SubtitleEntry(index=2, start=4.0, end=6.2, text_raw="这个也一样我们一般的推刀钮是这一个钮", text_norm=normalize_text("这个也一样我们一般的推刀钮是这一个钮")),
    ]

    merged = subtitle_segmentation._merge_short_chain_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged][:2] == [
        "然后当你蓄力比较足的时候就是一个弹开的这么一个效果",
        "这个也一样我们一般的推刀钮是这一个钮",
    ]


def test_resolve_fragment_window_prefers_direct_single_char_residual_repair():
    entries = [
        SubtitleEntry(index=0, start=0.0, end=2.4, text_raw="然后当你蓄力比较足的时候就是一个弹开的这么一个效", text_norm=normalize_text("然后当你蓄力比较足的时候就是一个弹开的这么一个效")),
        SubtitleEntry(index=1, start=2.4, end=2.54, text_raw="果", text_norm=normalize_text("果")),
        SubtitleEntry(index=2, start=4.0, end=6.2, text_raw="这个也一样我们一般的推刀钮是这一个钮", text_norm=normalize_text("这个也一样我们一般的推刀钮是这一个钮")),
    ]

    rebuilt = _resolve_fragment_window(entries, max_chars=18, max_duration=3.4)

    assert rebuilt is not None
    assert [entry.text_raw for entry in rebuilt][:2] == [
        "然后当你蓄力比较足的时候就是一个弹开的这么一个效果",
        "这个也一样我们一般的推刀钮是这一个钮",
    ]


def test_should_merge_subtitle_pair_for_model_token_boundary():
    assert _should_merge_subtitle_pair("有两把手电啊这个一把是EDC", "三七是之前我一直") is True
    assert _should_merge_subtitle_pair("现在被这个新兄弟EDC", "幺七光荣取代了") is True


def test_analyze_subtitle_segmentation_flags_real_edc_fragment_window():
    entries = [
        SubtitleEntry(index=0, start=10.4, end=12.785, text_raw="有两把手电啊这个一把是", text_norm=normalize_text("有两把手电啊这个一把是")),
        SubtitleEntry(index=1, start=12.785, end=15.04, text_raw="EDC三七是之前我一直", text_norm=normalize_text("EDC三七是之前我一直")),
        SubtitleEntry(index=2, start=15.76, end=17.24, text_raw="呃经常会EDC用的我", text_norm=normalize_text("呃经常会EDC用的我")),
        SubtitleEntry(index=3, start=17.24, end=18.973, text_raw="一一般都是把它挂包上因", text_norm=normalize_text("一一般都是把它挂包上因")),
        SubtitleEntry(index=4, start=18.973, end=22.013, text_raw="为这个东西还是有点大的嘛呃另", text_norm=normalize_text("为这个东西还是有点大的嘛呃另")),
        SubtitleEntry(index=5, start=22.013, end=25.362, text_raw="外一把呢就是现在这个耐克", text_norm=normalize_text("外一把呢就是现在这个耐克")),
        SubtitleEntry(index=6, start=25.362, end=29.68, text_raw="尔也是前两个月出的这个EDC幺七啊呃", text_norm=normalize_text("尔也是前两个月出的这个EDC幺七啊呃")),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["suspicious_boundary_count"] >= 3
    assert analysis["low_confidence_window_count"] >= 1


def test_analyze_subtitle_segmentation_flags_dense_short_nominal_tail_split():
    entries = [
        SubtitleEntry(index=0, start=30.72, end=33.2, text_raw="可以大家之前看过我们节目的应该", text_norm=normalize_text("可以大家之前看过我们节目的应该")),
        SubtitleEntry(index=1, start=33.2, end=35.12, text_raw="可以看出来啊少了一个小", text_norm=normalize_text("可以看出来啊少了一个小")),
        SubtitleEntry(index=2, start=35.12, end=35.52, text_raw="兄弟", text_norm=normalize_text("兄弟")),
        SubtitleEntry(index=3, start=38.48, end=42.88, text_raw="少了一个小兄弟啊那小兄弟就是这个EDC二三啊二", text_norm=normalize_text("少了一个小兄弟啊那小兄弟就是这个EDC二三啊二")),
    ]

    analysis = analyze_subtitle_segmentation(entries).as_dict()

    assert analysis["low_confidence_window_count"] >= 1
    assert any("少了一个小" in "".join(window["texts"]) for window in analysis["sample_low_confidence_windows"])


def test_analyze_subtitle_segmentation_chunks_oversized_dense_windows():
    entries = [
        SubtitleEntry(index=0, start=30.72, end=33.2, text_raw="可以大家之前看过我们节目的应该", text_norm=normalize_text("可以大家之前看过我们节目的应该")),
        SubtitleEntry(index=1, start=33.2, end=35.12, text_raw="可以看出来啊少了一个小", text_norm=normalize_text("可以看出来啊少了一个小")),
        SubtitleEntry(index=2, start=35.12, end=35.52, text_raw="兄弟", text_norm=normalize_text("兄弟")),
        SubtitleEntry(index=3, start=35.62, end=37.52, text_raw="少了一个小兄弟啊那", text_norm=normalize_text("少了一个小兄弟啊那")),
        SubtitleEntry(index=4, start=37.62, end=39.52, text_raw="小兄弟就是这个EDC二三", text_norm=normalize_text("小兄弟就是这个EDC二三")),
        SubtitleEntry(index=5, start=39.62, end=41.52, text_raw="现在被这个新兄弟取代", text_norm=normalize_text("现在被这个新兄弟取代")),
        SubtitleEntry(index=6, start=41.62, end=43.52, text_raw="那么这一期给大家讲讲", text_norm=normalize_text("那么这一期给大家讲讲")),
        SubtitleEntry(index=7, start=43.62, end=45.52, text_raw="也算一个简单的开箱", text_norm=normalize_text("也算一个简单的开箱")),
        SubtitleEntry(index=8, start=45.62, end=47.52, text_raw="盒子里面东西不算复杂", text_norm=normalize_text("盒子里面东西不算复杂")),
        SubtitleEntry(index=9, start=47.62, end=49.52, text_raw="我们直接来看手电本体", text_norm=normalize_text("我们直接来看手电本体")),
        SubtitleEntry(index=10, start=49.62, end=51.52, text_raw="先看一下尾部结构", text_norm=normalize_text("先看一下尾部结构")),
        SubtitleEntry(index=11, start=51.62, end=53.52, text_raw="再看一下正面的按键", text_norm=normalize_text("再看一下正面的按键")),
    ]

    analysis_obj = analyze_subtitle_segmentation(entries)

    assert analysis_obj.low_confidence_window_count >= 2
    assert analysis_obj.low_confidence_windows
    assert max(int(window["entry_count"]) for window in analysis_obj.low_confidence_windows) <= 6


def test_merge_and_cleanup_trim_repeated_overlap_after_pause():
    entries = [
        SubtitleEntry(index=0, start=32.58, end=35.52, text_raw="目的应该可以看出来啊少了一个小兄弟", text_norm=normalize_text("目的应该可以看出来啊少了一个小兄弟")),
        SubtitleEntry(index=1, start=38.48, end=40.13, text_raw="少了一个小兄弟啊那", text_norm=normalize_text("少了一个小兄弟啊那")),
        SubtitleEntry(index=2, start=40.13, end=42.33, text_raw="小兄弟就是这个EDC二三啊二", text_norm=normalize_text("小兄弟就是这个EDC二三啊二")),
    ]

    merged = _merge_continuation_entries(entries, max_chars=18, max_duration=3.4)
    cleaned = _cleanup_subtitle_entries(merged)

    assert [entry.text_raw for entry in cleaned] == [
        "目的应该可以看出来啊少了一个小兄弟",
        "啊那小兄弟就是这个EDC二三啊二",
    ]


def test_segment_subtitles_falls_back_from_synthetic_word_timings():
    segs = [
        _mock_segment(
            0,
            10.4,
            15.04,
            "有两把手电啊这个一把是EDC三七是之前我一直",
            words=[
                {"word": "有", "start": 10.4, "end": 10.62, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "两把", "start": 10.62, "end": 11.05, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "手电", "start": 11.05, "end": 11.48, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "这个一", "start": 11.9, "end": 12.35, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "把是", "start": 12.35, "end": 12.79, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "EDC", "start": 12.79, "end": 13.2, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "三七", "start": 13.2, "end": 13.6, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "是之前", "start": 13.6, "end": 14.2, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "我一直", "start": 14.2, "end": 15.04, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
        _mock_segment(
            1,
            15.76,
            18.973,
            "呃经常会EDC用的我一一般都是把它挂包上因",
            words=[
                {"word": "呃经常", "start": 15.76, "end": 16.2, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "会EDC", "start": 16.2, "end": 16.75, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "用的我", "start": 16.75, "end": 17.24, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "一一般", "start": 17.24, "end": 17.75, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "都是把", "start": 17.75, "end": 18.2, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "它挂包", "start": 18.2, "end": 18.6, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "上因", "start": 18.6, "end": 18.973, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=18, max_duration=3.4)

    assert entries
    assert not any(entry.text_raw.endswith("EDC") for entry in entries)
    assert not any(entry.text_raw.startswith("三七") for entry in entries)
    assert any("EDC三七" in entry.text_raw for entry in entries)


def test_segment_subtitles_uses_synthetic_word_anchors_for_global_boundaries():
    segs = [
        _mock_segment(
            0,
            21.767,
            23.74,
            "另外一把呢就是现",
            words=[
                {"word": "另外", "start": 21.767, "end": 22.205, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "一把呢", "start": 22.205, "end": 22.863, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "就是", "start": 22.863, "end": 23.301, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "现", "start": 23.301, "end": 23.74, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
        _mock_segment(
            1,
            23.74,
            29.68,
            "在这个耐克尔也是前两个月出的这个EDC幺七啊",
            words=[
                {"word": "在这个", "start": 23.74, "end": 24.401, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "耐克尔", "start": 24.401, "end": 25.061, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "也是", "start": 25.061, "end": 25.722, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "前两", "start": 25.722, "end": 26.382, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "个月", "start": 26.382, "end": 27.042, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "出的", "start": 27.042, "end": 27.703, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "这个", "start": 27.703, "end": 28.363, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "EDC", "start": 28.363, "end": 29.022, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "幺七啊", "start": 29.022, "end": 29.68, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=18, max_duration=3.4)

    assert entries
    assert not any(entry.text_raw.endswith("另") for entry in entries)
    assert not any(entry.text_raw.startswith("外一把") for entry in entries[1:])
    assert not any(entry.text_raw.endswith("现") for entry in entries)
    assert not any(entry.text_raw.startswith("在这个") for entry in entries[1:])
    assert not any(entry.text_raw.endswith("另外一") for entry in entries)
    assert not any(entry.text_raw.startswith("把呢") for entry in entries[1:])
    assert not any(entry.text_raw.endswith("前两") for entry in entries)
    assert not any(entry.text_raw.startswith("个月") for entry in entries[1:])


def test_segment_subtitles_avoids_predicate_phrase_split():
    segs = [
        _mock_segment(
            0,
            30.72,
            35.12,
            "大家之前看过我们节目的应该可以看出来少了一个小兄弟",
            words=[
                {"word": "大家之前", "start": 30.72, "end": 31.48, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "看过我们", "start": 31.48, "end": 32.24, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "节目的", "start": 32.24, "end": 32.98, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "应该", "start": 32.98, "end": 33.38, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "可以看出来", "start": 33.38, "end": 34.24, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "少了", "start": 34.24, "end": 34.62, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "一个小兄弟", "start": 34.62, "end": 35.12, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
    ]

    entries = split_into_subtitles(segs, max_chars=18, max_duration=3.4)

    assert entries
    assert any("应该可以看出来" in entry.text_raw for entry in entries)
    assert not any(entry.text_raw.endswith("应该") for entry in entries)
    assert not any(entry.text_raw.startswith("可以看出来") for entry in entries[1:])


def test_merge_continuation_entries_repairs_compound_and_possessive_splits():
    entries = [
        SubtitleEntry(index=0, start=22.1, end=23.6, text_raw="好说的耐克尔", text_norm=normalize_text("好说的耐克尔")),
        SubtitleEntry(index=1, start=23.64, end=25.68, text_raw="家的这个特色都在这个东西", text_norm=normalize_text("家的这个特色都在这个东西")),
        SubtitleEntry(index=2, start=30.72, end=33.2, text_raw="可以大家之前看过我们节", text_norm=normalize_text("可以大家之前看过我们节")),
        SubtitleEntry(index=3, start=33.2, end=35.12, text_raw="目的应该可以看出来少了一个小兄弟", text_norm=normalize_text("目的应该可以看出来少了一个小兄弟")),
        SubtitleEntry(index=4, start=35.18, end=36.88, text_raw="那小兄弟就是这个新", text_norm=normalize_text("那小兄弟就是这个新")),
        SubtitleEntry(index=5, start=36.9, end=38.8, text_raw="兄弟EDC17", text_norm=normalize_text("兄弟EDC17")),
    ]

    merged = _merge_continuation_entries(entries, max_chars=18, max_duration=3.4)

    assert [entry.text_raw for entry in merged] == [
        "好说的耐克尔家的这个特色都在这个东西",
        "可以大家之前看过我们节目的应该可以看出来少了一个小兄弟",
        "那小兄弟就是这个新兄弟EDC17",
    ]


def test_split_measure_phrase_detects_front_two_month_boundary():
    assert _looks_like_split_measure_phrase("另外一把呢就是现在这个耐克尔也是前", "两个月出的这个EDC幺七啊呃") is True


def test_predicate_phrase_detects_seen_our_program_boundary():
    assert _should_merge_subtitle_pair("可以大家之前看过", "我们节目的应该可以看出来啊少了一个小兄弟") is True


def test_compound_phrase_detects_our_program_boundary():
    assert _should_merge_subtitle_pair("可以大家之前看过我们", "节目的应该可以看出来啊少了一个小兄弟") is True


def test_model_suffix_boundary_detects_repeated_digit_continuation():
    assert _should_merge_subtitle_pair("啊那小兄弟就是这个EDC二三啊二", "三已经呃荣誉退") is True


def test_should_merge_subtitle_pair_for_honor_transition_phrase():
    assert _should_merge_subtitle_pair("那小兄弟就是这个EDC23已经", "荣誉退役了它现在被这个新") is True
    assert _should_merge_subtitle_pair("兄弟EDC17光荣", "取代了那么为什么这期给大家讲") is True


def test_segment_subtitles_reports_untrusted_word_input_stats():
    segs = [
        _mock_segment(
            0,
            10.4,
            15.04,
            "有两把手电啊这个一把是EDC三七是之前我一直",
            words=[
                {"word": "有", "start": 10.4, "end": 10.62, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
                {"word": "两把", "start": 10.62, "end": 11.05, "alignment": {"_roughcut": {"source": "synthetic", "coverage": 0.0}}},
            ],
        ),
        _mock_segment(
            1,
            15.76,
            18.973,
            "呃经常会EDC用的我一一般都是把它挂包上因",
            words=None,
        ),
    ]

    result = segment_subtitles(segs, max_chars=18, max_duration=3.4).analysis.as_dict()

    assert result["synthetic_word_segment_count"] == 1
    assert result["text_only_segment_count"] == 1
    assert result["provider_word_segment_count"] == 0
    assert result["global_word_segmentation_used"] is True


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

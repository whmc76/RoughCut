from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem
from roughcut.speech.postprocess import _should_merge_subtitle_pair, normalize_text, split_into_subtitles
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

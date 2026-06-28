from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.media.output import write_srt_file
from roughcut.media.subtitles import split_subtitle_display_item, split_subtitle_display_text, write_ass_file
from roughcut.pipeline.quality import _parse_srt_timeline, _subtitle_timing_structure_diagnostics
from roughcut.media.subtitle_text import (
    clean_final_subtitle_text,
    clean_subtitle_payloads,
    normalize_contextual_noc_alias_text,
    normalize_contextual_unboxing_sale_text,
    normalize_editable_subtitle_text,
    normalize_source_transcript_text,
    subtitle_display_suppression_reason,
)
from roughcut.review import content_profile as content_profile_module
from roughcut.review.content_profile import polish_subtitle_items
from roughcut.speech.subtitle_segmentation import normalize_display_text


def test_clean_final_subtitle_text_drops_only_standalone_fillers() -> None:
    assert clean_final_subtitle_text("呃，吧。这个") == ""
    assert clean_final_subtitle_text("这个") == ""
    assert clean_final_subtitle_text("这个产品吧还行") == "这个产品吧还行"
    assert clean_final_subtitle_text("好吧") == "好吧"


def test_clean_final_subtitle_text_removes_punctuation_fillers_and_interruptions() -> None:
    assert clean_final_subtitle_text("吧。啊。啊。") == ""
    assert clean_final_subtitle_text("不对， 也不叫。") == "不对 也不叫"
    assert clean_final_subtitle_text("滚") == ""
    assert clean_final_subtitle_text("滚，继续看细节") == "继续看细节"


def test_clean_final_subtitle_text_preserves_normal_cjk_phrases() -> None:
    assert clean_final_subtitle_text("我 跟 你 说") == "我跟你说"
    assert clean_final_subtitle_text("即 使") == "即使"
    assert clean_final_subtitle_text("我") == "我"
    assert clean_final_subtitle_text("好好好") == "好好好"


def test_clean_final_subtitle_text_collapses_asr_character_stutter() -> None:
    assert clean_final_subtitle_text("今今天天终终于于收收到到了了年年前前的的一个个款款") == "今天终于收到了年前的一个款"
    assert clean_final_subtitle_text("小小玩玩具具也也是是耗耗尽尽了了") == "小玩具也是耗尽了"
    assert clean_final_subtitle_text("大家大家看到看到现在这个镜头") == "大家看到现在这个镜头"
    assert clean_final_subtitle_text("没想到这NOC现NOC现在这么火") == "没想到这NOC现在这么火"


def test_normalize_editable_subtitle_text_collapses_asr_overlap_noise_from_full_editor() -> None:
    assert normalize_editable_subtitle_text("NNOCOC的的这个个发发售售，太太难难了") == "NOC的这个发售，太难了"
    assert normalize_editable_subtitle_text("你看，好好不不过过好好好在在，还还还还算算抢抢抢到了了") == "你看，好不过好在，还算抢到了"
    assert normalize_editable_subtitle_text("没没有没有这个像很多兄弟一样隐恨") == "没有这个像很多兄弟一样隐恨"
    assert normalize_editable_subtitle_text("还还是确实还是蛮") == "还是确实还是蛮"
    assert normalize_editable_subtitle_text("我一一般都是把它挂包上") == "我一般都是把它挂包上"


def test_normalize_editable_subtitle_text_collapses_asr_spellouts_and_measure_alternatives() -> None:
    assert normalize_editable_subtitle_text("最近这三次 N O C 的发售") == "最近这三次 NOC 的发售"
    assert normalize_editable_subtitle_text("非常适合 E D C 啊") == "非常适合 EDC 啊"
    assert normalize_editable_subtitle_text("S 06 mini 的迷你款") == "S06mini 的迷你款"
    assert normalize_editable_subtitle_text("最后的一个一款小玩具") == "最后的一款小玩具"
    assert normalize_editable_subtitle_text("\ufeff型号，，不错！！") == "型号，不错！"


def test_contextual_noc_alias_correction_requires_noc_context() -> None:
    assert normalize_contextual_noc_alias_text(
        "最近这三次NFC的发售太难了",
        context_text="开箱NOC MT34",
    ) == "最近这三次NOC的发售太难了"
    assert normalize_contextual_noc_alias_text(
        "这个手机NFC功能",
        context_text="手机功能演示",
    ) == "这个手机NFC功能"


def test_contextual_unboxing_sale_correction_requires_sale_context() -> None:
    context = "开箱NOC MT34 抢购 发售 一刀难求"

    assert normalize_contextual_unboxing_sale_text("最近这个发烧啊", context_text=context) == "最近这个发售啊"
    assert normalize_contextual_unboxing_sale_text("两次发烧都是极限赶涨", context_text=context) == "两次发售都是极限赶涨"
    assert normalize_contextual_unboxing_sale_text("这个发烧友很懂", context_text=context) == "这个发烧友很懂"
    assert normalize_contextual_unboxing_sale_text("真的发烧了", context_text="体温记录") == "真的发烧了"


def test_normalize_editable_subtitle_text_collapses_function_word_asr_prefix_stutter() -> None:
    assert normalize_editable_subtitle_text("纸纸箱了之类") == "纸箱了之类"
    assert normalize_editable_subtitle_text("既既能这个切菜，又又很帅") == "既能这个切菜，又很帅"
    assert normalize_editable_subtitle_text("尾部呢，还有有一个挂孔") == "尾部呢，还有一个挂孔"
    assert normalize_editable_subtitle_text("因为我我应该是指甲有点短") == "因为我应该是指甲有点短"
    assert normalize_editable_subtitle_text("开开箱，轻轻这么一指，试试它") == "开开箱，轻轻这么一指，试试它"


def test_normalize_editable_subtitle_text_collapses_overlapping_phrase_stutter() -> None:
    assert normalize_editable_subtitle_text("要手落在这个防滑防防滑纹上") == "要手落在这个防滑纹上"
    assert normalize_editable_subtitle_text("最近这个发售发发售啊太难") == "最近这个发售啊太难"
    assert normalize_editable_subtitle_text("一点点手法") == "一点点手法"


def test_normalize_source_transcript_text_preserves_real_spoken_fillers_and_interjections() -> None:
    assert normalize_source_transcript_text("啊，呃，嗯，我靠，饮恨") == "啊，呃，嗯，我靠，饮恨"
    assert normalize_source_transcript_text("这个、那个、就是、然后") == "这个、那个、就是、然后"
    assert normalize_source_transcript_text("NNOCOC的的这个个发发售售，太太难难了") == "NOC的这个发售，太难了"
    assert normalize_source_transcript_text("最近这三次NONOC的发售") == "最近这三次NOC的发售"
    assert normalize_source_transcript_text("经常会EDEDC用的啊") == "经常会EDC用的啊"
    assert normalize_source_transcript_text("太太难了") == "太太难了"
    assert normalize_source_transcript_text("<|nospeech|> 啊我靠饮恨") == "啊我靠饮恨"


def test_normalize_source_transcript_text_can_preserve_stutter_for_authoritative_manual_surfaces() -> None:
    assert (
        normalize_source_transcript_text("NNOCOC的的这个个发发售售，太太难难了", collapse_stutter=False)
        == "NNOCOC的的这个个发发售售，太太难难了"
    )
    assert normalize_source_transcript_text("最近这个发售发发售啊太难", collapse_stutter=False) == "最近这个发售发发售啊太难"


def test_normalize_source_transcript_text_preserves_legitimate_repeated_digits() -> None:
    assert normalize_source_transcript_text("最高2500流明，日用1500流明") == "最高2500流明，日用1500流明"
    assert normalize_source_transcript_text("峰值能达到10000流明啊") == "峰值能达到10000流明啊"
    assert normalize_editable_subtitle_text("这个8200给你的安全感更足") == "这个8200给你的安全感更足"


def test_clean_final_subtitle_text_hides_asr_noise_markers() -> None:
    assert clean_final_subtitle_text("[silence]") == ""
    assert clean_final_subtitle_text("(music)") == ""
    assert clean_final_subtitle_text("[Silence Music]") == ""
    assert clean_final_subtitle_text("silence music") == ""
    assert clean_final_subtitle_text("EnvironmentalSounds") == ""
    assert clean_final_subtitle_text("HumanSounds") == ""
    assert clean_final_subtitle_text("SoundsSoundsSilence") == ""
    assert clean_final_subtitle_text("Noise 好") == "好"
    assert clean_final_subtitle_text("<|nospeech|>") == ""
    assert clean_final_subtitle_text("这个细节 [music] 继续看") == "这个细节继续看"
    assert clean_final_subtitle_text("这个细节 silence music 继续看。") == "这个细节 silence music 继续看"
    assert clean_final_subtitle_text("给它塞进去啊EnvironmentalSounds哎") == "给它塞进去啊"
    assert clean_final_subtitle_text("噪音") == ""
    assert clean_final_subtitle_text("背景音") == ""


def test_clean_subtitle_payloads_marks_explicit_display_suppression_reason() -> None:
    cleaned = clean_subtitle_payloads(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "[silence]"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "呃"},
        ],
        drop_empty=False,
    )

    assert cleaned[0]["text_final"] == ""
    assert cleaned[0]["display_suppressed_reason"] == "asr_noise_marker"
    assert cleaned[1]["display_suppressed_reason"] == "standalone_filler"
    assert subtitle_display_suppression_reason("滚") == "disruption_clause"


def test_clean_final_subtitle_text_replaces_all_punctuation_with_spaces() -> None:
    assert clean_final_subtitle_text("型号：EDC17（黑色），不错！") == "型号 EDC17 黑色 不错"
    assert clean_final_subtitle_text("A/B｜C【D】") == "A B C D"


def test_clean_subtitle_payloads_collapses_future_asr_repeat_runs() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    cleaned = clean_subtitle_payloads(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
            {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
            {"index": 3, "start_time": 3.0, "end_time": 4.0, "text_final": repeated},
            {"index": 4, "start_time": 4.0, "end_time": 5.0, "text_final": "下一句正常内容"},
        ]
    )

    assert [item["index"] for item in cleaned] == [0, 4]


def test_clean_subtitle_payloads_keeps_intentional_short_repetition() -> None:
    cleaned = clean_subtitle_payloads(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "好好好"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "好好好"},
            {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": "好好好"},
        ]
    )

    assert [item["index"] for item in cleaned] == [0, 1, 2]


def test_clean_subtitle_payloads_normalizes_projection_timing_keys() -> None:
    cleaned = clean_subtitle_payloads(
        [
            {"index": 0, "start": 99.26, "end": 101.18, "text_final": "但是这个确实是"},
        ]
    )

    assert cleaned == [
        {
            "index": 0,
            "start_time": 99.26,
            "end_time": 101.18,
            "text_final": "但是这个确实是",
        }
    ]


def test_clean_subtitle_payloads_can_preserve_projection_text_for_validation() -> None:
    cleaned = clean_subtitle_payloads(
        [
            {"index": 0, "start": 1.0, "end": 2.0, "text_final": "型号：EDC17（黑色），不错！"},
            {"index": 1, "start": 2.0, "end": 3.0, "text_final": "呃，嗯。"},
        ],
        clean_text=False,
    )

    assert cleaned[0]["text_final"] == "型号：EDC17（黑色），不错！"
    assert cleaned[1]["text_final"] == "呃，嗯。"


def test_normalize_display_text_hides_asr_noise_markers_before_review() -> None:
    assert normalize_display_text("[silence]") == ""
    assert normalize_display_text("silence music") == ""
    assert normalize_display_text("Noise 好") == "好"
    assert normalize_display_text("HumanSounds哇") == "哇"
    assert normalize_display_text("OK的EnvironmentalSoundsSounds") == "OK的"
    assert normalize_display_text("细节 <|music|> 继续看") == "细节继续看"
    assert normalize_display_text("细节 silence music 继续看") == "细节 silence music 继续看"
    assert normalize_display_text("给它塞进去啊EnvironmentalSounds哎") == "给它塞进去啊， 哎"


@pytest.mark.asyncio
async def test_polish_subtitle_items_persists_final_text_without_asr_labels_or_punctuation() -> None:
    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="这个细节 silence music 继续看。",
        text_norm="这个细节 silence music 继续看。",
        text_final=None,
    )

    polished_count = await polish_subtitle_items(
        [item],
        content_profile={"workflow_template": "unboxing_standard"},
        glossary_terms=[],
        allow_llm=False,
    )

    assert polished_count == 1
    assert item.text_final == "细节 silence music 继续看"


@pytest.mark.asyncio
async def test_polish_subtitle_items_sends_normalized_text_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _Response:
        def as_json(self) -> dict:
            return {"items": []}

    class _Provider:
        async def complete(self, messages, **_kwargs):
            captured["prompt"] = messages[-1].content
            return _Response()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: _Provider())
    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="今今天天终终于于收收到到了了年年前前的的一个个款款",
        text_norm="今今天天终终于于收收到到了了年年前前的的一个个款款",
        text_final=None,
    )

    await polish_subtitle_items(
        [item],
        content_profile={"workflow_template": "unboxing_standard"},
        glossary_terms=[],
        allow_llm=True,
    )

    assert "今天终于收到了年前的一个款" in captured["prompt"]
    assert "今今天天" not in captured["prompt"]
    assert item.text_final == "今天终于收到了年前的一个款"


def test_write_srt_file_skips_filler_only_cues_with_consecutive_numbers(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {"start_time": 0.0, "end_time": 0.8, "text_final": "呃"},
            {"start_time": 0.8, "end_time": 1.6, "text_final": "这个产品吧还行"},
            {"start_time": 1.6, "end_time": 2.2, "text_final": "吧"},
            {"start_time": 2.2, "end_time": 3.0, "text_final": "继续看细节"},
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "\n呃\n" not in content
    assert "\n吧\n" not in content
    assert "1\n00:00:00,800 --> 00:00:01,600\n这个产品吧还行" in content
    assert "2\n00:00:02,200 --> 00:00:03,000\n继续看细节" in content


def test_write_srt_file_serializes_final_text_without_punctuation(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {"start_time": 0.0, "end_time": 1.0, "text_final": "是Ultra版本。"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "黑绿配色，手感不错"},
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "是Ultra版本\n" in content
    assert "黑绿配色 手感不错\n" in content
    assert "。" not in content
    assert "，" not in content


def test_write_srt_file_merges_orphan_single_cjk_cue_to_next_phrase(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {"index": 0, "start_time": 274.987, "end_time": 277.358, "text_final": "要一只手按着这个包"},
            {"index": 1, "start_time": 277.387, "end_time": 277.543, "text_final": "它"},
            {"index": 2, "start_time": 277.543, "end_time": 280.026, "text_final": "拉上以后"},
            {"index": 3, "start_time": 280.026, "end_time": 281.505, "text_final": "你再给它手动的去锁紧"},
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "它拉上以后" in content
    assert "\n它\n" not in content


def test_write_srt_file_sorts_projection_items_before_timeline_validation(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {"index": 2, "start_time": 1.0, "end_time": 2.0, "text_final": "第二句"},
            {"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "第一句"},
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "1\n00:00:00,000 --> 00:00:01,000\n第一句" in content
    assert "2\n00:00:01,000 --> 00:00:02,000\n第二句" in content


def test_write_srt_file_splits_overlong_display_cues(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {
                "start_time": 0.0,
                "end_time": 12.0,
                "text_final": "第一段很长 继续讲第二个重点 再补充第三个细节 最后收束这一条字幕",
            },
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "1\n00:00:00,000" in content
    assert "2\n" in content


def test_write_srt_file_merges_short_flash_fragments_from_display_split(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.srt"

    write_srt_file(
        [
            {
                "start_time": 609.061,
                "end_time": 611.649,
                "text_final": "日常场景啊真正的使用一次你才能理解到它到底有多么的实用和优秀嗯虽然它不如",
            },
            {
                "start_time": 611.649,
                "end_time": 614.022,
                "text_final": "我们这些机能包啊那么花里胡哨啊呃当然它这个纯黑肯定也会有很多人喜欢",
            },
        ],
        output_path,
    )

    timeline = _parse_srt_timeline(output_path)
    diagnostics = _subtitle_timing_structure_diagnostics(timeline["ranges"], video_duration_sec=620.708)
    content = output_path.read_text(encoding="utf-8-sig")

    assert diagnostics["short_flash_count"] == 0
    assert diagnostics["abrupt_flash_count"] == 0
    assert "\n然它不如\n" not in content
    assert "\n欢\n" not in content


def test_write_ass_file_skips_filler_only_dialogues(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.ass"

    write_ass_file(
        [
            {"start_time": 0.0, "end_time": 0.8, "text_final": "这个"},
            {"start_time": 0.8, "end_time": 1.6, "text_final": "这个产品吧还行"},
            {"start_time": 1.6, "end_time": 2.2, "text_final": "吧"},
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == 1
    assert "这个产品吧还行" in dialogue_lines[0]


def test_write_ass_file_does_not_restore_display_suppressed_row_from_hidden_surfaces(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.ass"

    write_ass_file(
        [
            {
                "start_time": 0.0,
                "end_time": 0.8,
                "text_raw": "这个",
                "text_norm": "这个",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            },
            {
                "start_time": 0.8,
                "end_time": 1.6,
                "text_final": "这个产品吧还行",
            },
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == 1
    assert "这个产品吧还行" in dialogue_lines[0]


def test_write_ass_file_splits_long_dialogues_instead_of_truncating(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.ass"

    write_ass_file(
        [
            {
                "start_time": 10.0,
                "end_time": 18.0,
                "text_final": "你看 好 不过好在呢 还还算抢到了 没有没有没有这个像很多兄弟一样",
            },
        ],
        output_path,
        play_res_x=1920,
        play_res_y=1080,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) >= 2
    assert "…" not in "\n".join(dialogue_lines)
    assert "很多兄弟一样" in "\n".join(dialogue_lines)


def test_write_ass_file_uses_explicit_semantic_wrap_without_verb_complement_tail(tmp_path: Path) -> None:
    output_path = tmp_path / "subtitle.ass"

    write_ass_file(
        [
            {
                "start_time": 167.74,
                "end_time": 171.168,
                "text_final": "比如说我刚才我想把这个拉回来嘛",
            },
        ],
        output_path,
        play_res_x=1920,
        play_res_y=1080,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert "WrapStyle: 2" in content
    assert len(dialogue_lines) == 1
    assert "拉\\N回来嘛" not in dialogue_lines[0]
    assert "拉回来嘛" in dialogue_lines[0]


def test_split_subtitle_display_item_uses_word_timed_boundaries_for_display_segments() -> None:
    segments = split_subtitle_display_item(
        start_time=0.0,
        end_time=12.0,
        text="甲乙丙丁戊己",
        subtitle_item={
            "start_time": 0.0,
            "end_time": 12.0,
            "text_final": "甲乙丙丁戊己",
            "words": [
                {"word": "甲", "start": 0.0, "end": 1.0},
                {"word": "乙", "start": 1.0, "end": 2.0},
                {"word": "丙", "start": 2.0, "end": 6.0},
                {"word": "丁", "start": 6.0, "end": 7.0},
                {"word": "戊", "start": 7.0, "end": 8.0},
                {"word": "己", "start": 8.0, "end": 12.0},
            ],
        },
        max_duration_sec=4.0,
        max_chars=2,
    )

    assert [segment["text"] for segment in segments] == ["甲乙", "丙丁", "戊己"]
    assert [(segment["start_time"], segment["end_time"]) for segment in segments] == [
        (0.0, 2.0),
        (2.0, 7.0),
        (7.0, 12.0),
    ]


def test_write_srt_file_uses_faithful_source_surface_when_display_text_omits_words(tmp_path: Path) -> None:
    output_path = tmp_path / "faithful.srt"

    write_srt_file(
        [
            {
                "start_time": 0.0,
                "end_time": 3.0,
                "text_final": "去伤人的重中之重",
                "transcript_text": "这个去伤人的这个重中之重",
                "words": [
                    {"word": "这个", "start": 0.0, "end": 0.4},
                    {"word": "去伤人的", "start": 0.4, "end": 1.3},
                    {"word": "这个", "start": 1.3, "end": 1.7},
                    {"word": "重中之重", "start": 1.7, "end": 3.0},
                ],
            }
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "这个去伤人的这个重中之重" in content
    assert "去伤人的重中之重" not in content


def test_write_srt_file_keeps_numeric_display_surface_when_it_matches_spoken_numbers(tmp_path: Path) -> None:
    output_path = tmp_path / "numbers.srt"

    write_srt_file(
        [
            {
                "start_time": 0.0,
                "end_time": 2.0,
                "text_final": "10000流明啊",
                "transcript_text": "一万流明啊",
                "words": [
                    {"word": "一万", "start": 0.0, "end": 0.8},
                    {"word": "流明", "start": 0.8, "end": 1.5},
                    {"word": "啊", "start": 1.5, "end": 2.0},
                ],
            }
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8-sig")
    assert "10000流明啊" in content
    assert "一万流明啊" not in content


def test_split_subtitle_display_text_splits_oversized_chinese_token_before_latin_token() -> None:
    text = "今天我们直奔主题啊大家看到现在这个镜头里有两把手电啊这个一把是EDC37之前我一直经常会用的 EDC37"

    pieces = split_subtitle_display_text(text, max_chars=16)

    assert len(pieces) > 2
    assert all(len(piece.replace(" ", "")) <= 16 for piece in pieces)
    assert "".join(piece.replace(" ", "") for piece in pieces) == text.replace(" ", "")

from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.media.output import write_srt_file
from roughcut.media.subtitles import write_ass_file
from roughcut.media.subtitle_text import clean_final_subtitle_text
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


def test_clean_final_subtitle_text_hides_asr_noise_markers() -> None:
    assert clean_final_subtitle_text("[silence]") == ""
    assert clean_final_subtitle_text("(music)") == ""
    assert clean_final_subtitle_text("[Silence Music]") == ""
    assert clean_final_subtitle_text("silence music") == ""
    assert clean_final_subtitle_text("<|nospeech|>") == ""
    assert clean_final_subtitle_text("这个细节 [music] 继续看") == "这个细节继续看"
    assert clean_final_subtitle_text("这个细节 silence music 继续看。") == "这个细节 silence music 继续看"


def test_clean_final_subtitle_text_replaces_all_punctuation_with_spaces() -> None:
    assert clean_final_subtitle_text("型号：EDC17（黑色），不错！") == "型号 EDC17 黑色 不错"
    assert clean_final_subtitle_text("A/B｜C【D】") == "A B C D"


def test_normalize_display_text_hides_asr_noise_markers_before_review() -> None:
    assert normalize_display_text("[silence]") == ""
    assert normalize_display_text("silence music") == ""
    assert normalize_display_text("细节 <|music|> 继续看") == "细节继续看"
    assert normalize_display_text("细节 silence music 继续看") == "细节 silence music 继续看"


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

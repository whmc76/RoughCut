from pathlib import Path

from roughcut.media.output import write_srt_file
from roughcut.media.subtitles import write_ass_file
from roughcut.media.subtitle_text import clean_final_subtitle_text


def test_clean_final_subtitle_text_drops_only_standalone_fillers() -> None:
    assert clean_final_subtitle_text("呃，吧。这个") == ""
    assert clean_final_subtitle_text("这个") == ""
    assert clean_final_subtitle_text("这个产品吧还行") == "这个产品吧还行"
    assert clean_final_subtitle_text("好吧") == "好吧"


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

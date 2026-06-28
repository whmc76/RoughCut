from roughcut.review.chapter_analysis import normalize_chapter_analysis_segments
from roughcut.pipeline.steps import _duration_from_chapter_timed_text


def test_normalize_chapter_analysis_segments_preserves_asr_topic_titles() -> None:
    chapters = normalize_chapter_analysis_segments(
        {
            "chapters": [
                {"title": "品牌产品名介绍", "start_sec": 0.7, "end_sec": 9.2, "summary": "介绍狐蝠工业新包"},
                {"title": "主体外观", "start_sec": 9.2, "end_sec": 21.0},
                {"title": "肩带使用方法", "start_sec": 21.0, "end_sec": 36.5},
                {"title": "背负方式", "start_sec": 36.5, "end_sec": 48.0},
                {"title": "分仓特点", "start_sec": 48.0, "end_sec": 64.0},
            ]
        },
        duration_sec=66.0,
    )

    assert [item["title"] for item in chapters] == ["品牌产品名介绍", "主体外观", "肩带使用方法", "背负方式", "分仓特点"]
    assert chapters[0]["start_sec"] == 0.0
    assert chapters[-1]["end_sec"] == 66.0
    assert all(left["end_sec"] <= right["start_sec"] for left, right in zip(chapters, chapters[1:]))
    assert {item["source"] for item in chapters} == {"llm_chapter_analysis"}


def test_normalize_chapter_analysis_segments_summarizes_spoken_sentence_titles() -> None:
    chapters = normalize_chapter_analysis_segments(
        {
            "chapters": [
                {
                    "title_short": "定位差异",
                    "title": "这是一个新的物种本质上的区别的甚至可以说",
                    "start_sec": 0.0,
                    "end_sec": 8.0,
                },
                {
                    "title_short": "背带调节",
                    "title": "这里主要讲这个肩带到底怎么调节和快拆",
                    "start_sec": 8.0,
                    "end_sec": 16.0,
                },
                {
                    "title_short": "收纳层次",
                    "title": "然后这个包里面的分仓和拉链口袋比较多",
                    "start_sec": 16.0,
                    "end_sec": 24.0,
                },
            ]
        },
        duration_sec=24.0,
    )

    assert [item["title"] for item in chapters] == ["定位差异", "背带调节", "收纳层次"]
    assert all(len(item["title"]) <= 8 for item in chapters)


def test_normalize_chapter_analysis_segments_does_not_template_spoken_titles() -> None:
    chapters = normalize_chapter_analysis_segments(
        {
            "chapters": [
                {"title": "这里主要讲这个肩带到底怎么调节和快拆", "start_sec": 0.0, "end_sec": 8.0},
                {"title": "然后这个包里面的分仓和拉链口袋比较多", "start_sec": 8.0, "end_sec": 16.0},
            ]
        },
        duration_sec=16.0,
    )

    assert [item["title"] for item in chapters] == ["章节1", "章节2"]


def test_chapter_analysis_duration_uses_transcript_when_editorial_subtitles_are_missing() -> None:
    duration = _duration_from_chapter_timed_text(
        [],
        [
            {"start": 0.0, "end": 12.5, "text": "开场介绍"},
            {"start": 12.5, "end": 31.25, "text": "主体展示"},
        ],
    )

    assert duration == 31.25

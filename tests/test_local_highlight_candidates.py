from roughcut.edit.decisions import infer_timeline_analysis


def _subtitle(text: str, *, start: float, end: float) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "text_raw": text,
        "text_norm": text,
        "text_final": text,
    }


def test_short_clip_does_not_emit_highlight_candidates() -> None:
    analysis = infer_timeline_analysis(
        [
            _subtitle("先讲结论", start=0.0, end=1.8),
            _subtitle("这里补充细节", start=2.0, end=4.4),
            _subtitle("欢迎留言", start=4.6, end=6.2),
        ],
        duration=6.2,
        content_profile={"content_kind": "gameplay"},
    )

    assert analysis["highlight_candidates"] == []


def test_long_gameplay_like_clip_emits_conservative_highlight_candidates() -> None:
    analysis = infer_timeline_analysis(
        [
            _subtitle("这一波直接三连击打满了", start=0.0, end=2.6),
            _subtitle("注意这里反打的节奏和关键换枪", start=2.9, end=6.1),
            _subtitle("再看这一段对比就知道为什么赢了", start=6.4, end=10.3),
            _subtitle("最后这波收尾直接带走", start=10.8, end=14.6),
            _subtitle("结尾提醒大家点赞关注", start=15.0, end=17.2),
        ],
        duration=17.2,
        content_profile={"content_kind": "gameplay"},
    )

    candidates = analysis["highlight_candidates"]

    assert candidates
    assert candidates[0]["role"] in {"detail", "body", "hook"}
    assert candidates[0]["score"] >= 0.9
    assert candidates[0]["start_sec"] < candidates[0]["end_sec"]
    assert "reasons" in candidates[0]


def test_multimodal_keep_hints_raise_highlight_candidate_priority() -> None:
    base_items = [
        _subtitle("先讲结论这个片段到底值不值看这段", start=0.0, end=2.5),
        _subtitle("这里看关键细节对比和上手展示", start=2.8, end=7.1),
        _subtitle("然后再看结尾表现", start=7.4, end=13.8),
    ]
    baseline = infer_timeline_analysis(base_items, duration=13.8, content_profile={"content_kind": "tutorial"})
    guided = infer_timeline_analysis(
        base_items,
        duration=13.8,
        content_profile={
            "content_kind": "tutorial",
            "video_understanding": {
                "segment_understanding": [
                    {
                        "start": 2.8,
                        "end": 7.1,
                        "role": "detail_showcase",
                        "keep_priority": "high",
                        "confidence": 0.88,
                    }
                ]
            },
        },
    )

    assert baseline["highlight_candidates"]
    assert guided["highlight_candidates"]
    assert guided["highlight_candidates"][0]["score"] >= baseline["highlight_candidates"][0]["score"]
    assert any("视频理解提示命中" in reason for reason in guided["highlight_candidates"][0]["reasons"])

from roughcut.pipeline.steps import _project_canonical_transcript_to_timeline


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

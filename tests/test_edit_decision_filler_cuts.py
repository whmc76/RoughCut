from roughcut.edit.decisions import _build_subtitle_cut_candidates


def _subtitle(text: str) -> dict:
    return {
        "start_time": 1.0,
        "end_time": 2.0,
        "text_raw": text,
        "text_norm": text,
        "text_final": text,
    }


def test_filler_cut_keeps_short_normal_speech_after_filler_prefix() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle("这个刀"),
            _subtitle("这个我跟你说"),
            _subtitle("即使这样"),
        ],
        content_profile=None,
    )

    assert candidates == []


def test_filler_cut_only_removes_pure_filler_subtitle() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("这个嘛")],
        content_profile=None,
    )

    assert len(candidates) == 1
    assert candidates[0].reason == "filler_word"

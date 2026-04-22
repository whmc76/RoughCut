from roughcut.edit.decisions import _collect_restart_retake_cuts, _is_restart_cue_text


def _subtitle(index: int, start: float, end: float, text: str) -> dict:
    return {
        "index": index,
        "start_time": start,
        "end_time": end,
        "text_final": text,
    }


def test_interruption_cue_is_restart_cue() -> None:
    assert _is_restart_cue_text("滚")
    assert _is_restart_cue_text("别打扰")


def test_interruption_between_retake_lines_becomes_cut_candidate() -> None:
    cuts = _collect_restart_retake_cuts(
        [
            _subtitle(0, 0.0, 1.0, "这个手感不错"),
            _subtitle(1, 1.2, 1.6, "滚"),
            _subtitle(2, 2.0, 4.0, "这个手感不错但是容量更大"),
        ],
        content_profile={},
    )

    assert cuts == [(0.0, 2.0, "restart_retake")]

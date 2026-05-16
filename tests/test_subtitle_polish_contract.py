from types import SimpleNamespace

from roughcut.review.content_profile import (
    _capture_subtitle_text_only_contract,
    _enforce_subtitle_text_only_contract,
)


def test_subtitle_polish_contract_restores_structure_fields() -> None:
    item = SimpleNamespace(
        item_index=3,
        start_time=1.25,
        end_time=2.5,
        text_raw="EDC幺七",
        text_norm="EDC幺七",
        text_final="EDC17",
    )
    contract = _capture_subtitle_text_only_contract([item])

    item.item_index = 9
    item.start_time = 0.0
    item.end_time = 9.0
    item.text_final = "EDC17"

    repairs = _enforce_subtitle_text_only_contract([item], contract)

    assert item.item_index == 3
    assert item.start_time == 1.25
    assert item.end_time == 2.5
    assert item.text_final == "EDC17"
    assert {repair["field"] for repair in repairs} == {"item_index", "start_time", "end_time"}

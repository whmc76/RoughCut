from __future__ import annotations

from roughcut.review.model_identity import (
    extract_model_signature,
    filter_conflicting_model_wrong_forms,
    model_numbers_conflict,
    normalize_model_number,
)


def test_normalize_model_number_supports_spoken_and_chinese_numerals():
    assert normalize_model_number("幺七") == "17"
    assert normalize_model_number("三七") == "37"
    assert normalize_model_number("十七") == "17"


def test_extract_model_signature_normalizes_spoken_digits():
    assert extract_model_signature(" EDC 幺七 ") == ("EDC", "17", "")
    assert extract_model_signature(" MT 拐洞7 ") == ("MTG", "07", "")


def test_model_numbers_conflict_detects_same_family_different_numbers():
    assert model_numbers_conflict("EDC37", "EDC17") is True
    assert model_numbers_conflict("EDC幺七", "EDC17") is False
    assert model_numbers_conflict("MT332", "MT33") is True


def test_filter_conflicting_model_wrong_forms_keeps_true_aliases_only():
    assert filter_conflicting_model_wrong_forms(
        correct_form="EDC17",
        wrong_forms=["EDC37", "EDC幺七", "EDC17"],
    ) == ["EDC幺七", "EDC17"]

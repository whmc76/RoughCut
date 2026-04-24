from roughcut.review.content_profile import (
    apply_source_identity_constraints,
    extract_source_identity_constraints,
)


SOURCE_NAME = "IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV"


def test_extracts_boltboat_eclipse_identity_from_source_name() -> None:
    constraints = extract_source_identity_constraints({}, source_name=SOURCE_NAME)

    assert constraints["authoritative"] is True
    assert constraints["subject_brand"] == "BOLTBOAT"
    assert constraints["subject_model"] == "影蚀"
    assert "机能" in constraints["subject_type"]


def test_source_identity_overrides_related_profile_model_contamination() -> None:
    profile = {
        "subject_brand": "BOLTBOAT",
        "subject_model": "FXX1小副包",
        "subject_type": "EDC机能包",
        "summary": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "video_theme": "BOLTBOAT FXX1小副包挂点与收纳展示",
    }

    constrained = apply_source_identity_constraints(profile, source_name=SOURCE_NAME)

    assert constrained["subject_brand"] == "BOLTBOAT"
    assert constrained["subject_model"] == "影蚀"
    assert "FXX1" not in constrained["summary"]
    assert "FXX1" not in constrained["video_theme"]

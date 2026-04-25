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


def test_extracts_nitecore_edc17_flashlight_identity_from_source_name() -> None:
    constraints = extract_source_identity_constraints(
        {},
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
    )

    assert constraints["subject_brand"] == "NITECORE"
    assert constraints["subject_model"] == "EDC17"
    assert constraints["subject_type"] == "EDC手电"


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


def test_source_identity_rewrites_conflicting_edc_visible_text() -> None:
    profile = {
        "subject_model": "EDC17",
        "subject_type": "",
        "visible_text": "EDC37",
        "cover_title": {"top": "EDC37", "main": "EDC17", "bottom": "EDC17强光测试"},
        "summary": "EDC37 对比展示",
        "video_theme": "EDC37 对比",
    }

    constrained = apply_source_identity_constraints(
        profile,
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        transcript_excerpt="这个EDC17手电有UV和白光模式",
    )

    assert constrained["subject_brand"] == "NITECORE"
    assert constrained["subject_model"] == "EDC17"
    assert constrained["subject_type"] == "EDC手电"
    assert "EDC37" not in constrained["visible_text"]

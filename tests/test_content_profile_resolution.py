from roughcut.review.content_profile_candidates import build_identity_candidates
from roughcut.review.content_profile_evidence import IdentityEvidenceBundle
from roughcut.review.content_profile_resolve import resolve_identity_candidates
from roughcut.review.content_profile_scoring import score_identity_candidates


def _normalize(value: object) -> str:
    return "".join(str(value or "").strip().upper().split())


def test_build_identity_candidates_includes_memory_confirmed_source():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次手电开箱重点看司令官2的 Ultra 版本。",
        source_name="demo.mp4",
        transcript_hints={"subject_type": "EDC手电"},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={"subject_brand": "傲雷", "subject_model": "司令官2Ultra"},
    )

    candidates = build_identity_candidates(bundle)
    source_pairs = {(item.field_name, item.value, item.source_type) for item in candidates}

    assert ("subject_brand", "傲雷", "memory_confirmed") in source_pairs
    assert ("subject_model", "司令官2Ultra", "memory_confirmed") in source_pairs


def test_score_identity_candidates_treats_memory_confirmed_as_supporting_evidence():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次手电开箱重点看司令官2Ultra 的流明档位。",
        source_name="demo.mp4",
        transcript_hints={"subject_model": "司令官2Ultra"},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={"subject_brand": "傲雷", "subject_model": "司令官2Ultra"},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)

    model = scored["subject_model"][0]
    brand = scored["subject_brand"][0]

    assert model.value == "司令官2Ultra"
    assert model.current_evidence_score > 0
    assert "memory_confirmed" in model.all_sources
    assert brand.value == "傲雷"
    assert brand.current_evidence_score == 0
    assert "memory_confirmed" in brand.all_sources


def test_resolve_identity_candidates_does_not_accept_memory_confirmed_without_current_evidence():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次主要聊桌面布光，没有具体产品名。",
        source_name="demo.mp4",
        transcript_hints={},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={"subject_brand": "傲雷", "subject_model": "司令官2Ultra"},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)
    resolved = resolve_identity_candidates(
        scored,
        normalize=_normalize,
        mapped_brand_for_model=lambda value: "",
    )

    assert resolved.subject_brand == ""
    assert resolved.subject_model == ""


def test_resolve_identity_candidates_prefers_current_evidence_video_theme():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次是手电开箱，重点看不同版本的差异。",
        source_name="demo.mp4",
        transcript_hints={"video_theme": "手电开箱与版本对比"},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={"video_theme": "ComfyUI 工作流演示"},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)
    resolved = resolve_identity_candidates(
        scored,
        normalize=_normalize,
        mapped_brand_for_model=lambda value: "",
    )

    assert resolved.video_theme == "手电开箱与版本对比"


def test_resolve_identity_candidates_drops_profile_only_video_theme():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次主要聊桌面布光。",
        source_name="demo.mp4",
        transcript_hints={},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={"video_theme": "ComfyUI 工作流演示"},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)
    resolved = resolve_identity_candidates(
        scored,
        normalize=_normalize,
        mapped_brand_for_model=lambda value: "",
    )

    assert resolved.video_theme == ""


def test_build_identity_candidates_includes_visual_cluster_source():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次主要看手上的折刀。",
        source_name="demo.mp4",
        transcript_hints={},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={"subject_brand": "NOC", "subject_model": "MT33", "subject_type": "EDC折刀"},
        visible_text_hints={"subject_model": "ARC"},
        profile_identity={},
        memory_confirmed_hints={},
    )

    candidates = build_identity_candidates(bundle)
    source_pairs = {(item.field_name, item.value, item.source_type) for item in candidates}

    assert ("subject_brand", "NOC", "visual_cluster") in source_pairs
    assert ("subject_model", "MT33", "visual_cluster") in source_pairs


def test_score_identity_candidates_prefers_visual_cluster_over_visible_text_fragment():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次主要看手上的折刀。",
        source_name="demo.mp4",
        transcript_hints={},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={"subject_brand": "NOC", "subject_model": "MT33", "subject_type": "EDC折刀"},
        visible_text_hints={"subject_model": "ARC"},
        profile_identity={},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)

    assert scored["subject_model"][0].value == "MT33"
    assert "visual_cluster" in scored["subject_model"][0].all_sources


def test_score_identity_candidates_does_not_double_count_duplicate_visual_cluster_as_visual():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次主要看手上的折刀。",
        source_name="demo.mp4",
        transcript_hints={},
        source_hints={},
        visual_hints={"subject_brand": "NOC", "subject_model": "MT33", "subject_type": "EDC折刀"},
        visual_cluster_hints={"subject_brand": "NOC", "subject_model": "MT33", "subject_type": "EDC折刀"},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)

    assert scored["subject_model"][0].value == "MT33"
    assert scored["subject_model"][0].current_evidence_score == 4
    assert scored["subject_model"][0].all_sources == ("visual_cluster",)

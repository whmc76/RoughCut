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


def test_resolve_identity_candidates_prefers_more_specific_compatible_model_value():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这次开箱 FOXBAT F21 小副包，重点看分仓和挂点。",
        source_name="f21.mp4",
        transcript_hints={"subject_model": "FXX1小副包"},
        source_hints={"subject_model": "F21"},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)
    resolved = resolve_identity_candidates(
        scored,
        normalize=_normalize,
        mapped_brand_for_model=lambda value: "",
    )

    assert resolved.subject_model == "FXX1小副包"


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


def test_build_identity_candidates_includes_graph_ocr_and_transcript_source_label_sources():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这期主要看分仓和挂点。",
        source_name="demo.mp4",
        transcript_hints={},
        transcript_source_labels={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "video_theme": "狐蝠工业FXX1小副包开箱与挂点评测",
        },
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        ocr_hints={"subject_brand": "狐蝠工业", "subject_model": "FXX1小副包"},
        profile_identity={},
        memory_confirmed_hints={},
        graph_confirmed_entities=[
            {"brand": "傲雷", "model": "司令官2Ultra", "subject_type": "EDC手电"},
        ],
    )

    candidates = build_identity_candidates(bundle)
    source_pairs = {(item.field_name, item.value, item.source_type) for item in candidates}

    assert ("subject_brand", "狐蝠工业", "transcript_labels") in source_pairs
    assert ("subject_model", "FXX1小副包", "ocr") in source_pairs
    assert ("subject_brand", "傲雷", "graph_confirmed") in source_pairs


def test_score_identity_candidates_prefers_current_video_evidence_over_graph_memory():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这期主要看挂点和分仓。",
        source_name="demo.mp4",
        transcript_hints={},
        transcript_source_labels={"subject_brand": "狐蝠工业", "subject_model": "FXX1小副包"},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={"subject_brand": "狐蝠工业", "subject_model": "FXX1小副包"},
        visible_text_hints={},
        ocr_hints={"subject_brand": "狐蝠工业", "subject_model": "FXX1小副包"},
        profile_identity={},
        memory_confirmed_hints={"subject_brand": "傲雷", "subject_model": "司令官2Ultra"},
        graph_confirmed_entities=[
            {"brand": "傲雷", "model": "司令官2Ultra", "subject_type": "EDC手电"},
        ],
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)

    brand = scored["subject_brand"][0]
    model = scored["subject_model"][0]

    assert brand.value == "狐蝠工业"
    assert model.value == "FXX1小副包"
    assert brand.current_evidence_score > 0
    assert model.current_evidence_score > 0
    assert "graph_confirmed" not in brand.all_sources


def test_build_identity_candidates_includes_source_context_identity_hints():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这条片子主要是同一支工具钳的连续镜头。",
        source_name="20260130-140529.mp4",
        transcript_hints={},
        source_hints={},
        source_context_hints={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "related_source_names": ["20260130-134317.mp4"],
        },
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        profile_identity={},
        memory_confirmed_hints={},
    )

    candidates = build_identity_candidates(bundle)
    source_pairs = {(item.field_name, item.value, item.source_type) for item in candidates}

    assert ("subject_brand", "LEATHERMAN", "source_context") in source_pairs
    assert ("subject_model", "ARC", "source_context") in source_pairs


def test_score_identity_candidates_prefers_exact_source_and_visual_overlap_for_unknown_brand():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这期主要看这尊铜貔貅的细节。",
        source_name="IMG_0026 琢匠年度旗舰铜貔貅铜雕像.MOV",
        transcript_hints={},
        source_hints={},
        source_visual_overlap_hints={"subject_brand": "琢匠", "visible_text": "琢匠 铜貔貅"},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        ocr_hints={"subject_brand": "卓匠", "visible_text": "卓匠 铜貔貅"},
        profile_identity={},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)

    assert scored["subject_brand"][0].value == "琢匠"
    assert "source_visual_overlap" in scored["subject_brand"][0].all_sources
    assert scored["subject_brand"][0].current_evidence_score == 6


def test_resolve_identity_candidates_clears_brand_and_model_when_current_ocr_and_transcript_conflict():
    bundle = IdentityEvidenceBundle(
        transcript_excerpt="这期主要看挂点和分仓。",
        source_name="demo.mp4",
        transcript_hints={},
        transcript_source_labels={"subject_brand": "狐蝠工业", "subject_model": "FXX1小副包"},
        source_hints={},
        visual_hints={},
        visual_cluster_hints={},
        visible_text_hints={},
        ocr_hints={"subject_brand": "NOC", "subject_model": "MT33"},
        profile_identity={},
        memory_confirmed_hints={},
    )

    scored = score_identity_candidates(build_identity_candidates(bundle), normalize=_normalize)
    resolved = resolve_identity_candidates(
        scored,
        normalize=_normalize,
        mapped_brand_for_model=lambda value: {"FXX1小副包": "狐蝠工业", "MT33": "NOC"}.get(str(value), ""),
    )

    assert resolved.subject_brand == ""
    assert resolved.subject_model == ""
    assert "current_identity_conflict" in resolved.conflicts

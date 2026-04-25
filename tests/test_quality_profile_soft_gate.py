from roughcut.db.models import Artifact, Job, SubtitleItem
from roughcut.pipeline.quality import assess_job_quality
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT, build_subtitle_quality_report


def _subtitle(index: int, text: str) -> SubtitleItem:
    return SubtitleItem(
        item_index=index,
        start_time=float(index),
        end_time=float(index + 1),
        text_raw=text,
        text_norm=text,
        text_final=text,
    )


def test_short_hash_named_clip_does_not_fail_on_generic_profile() -> None:
    job = Job(
        source_path="F:/clips/8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
        "automation_review": {"score": 0.6},
    }
    artifact = Artifact(artifact_type="content_profile_final", data_json=profile)

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[artifact],
        subtitle_items=[_subtitle(0, "看一下这里"), _subtitle(1, "这个操作")],
        completion_candidate=True,
    )

    assert assessment["score"] == 100.0
    assert "low_profile_confidence" not in assessment["issue_codes"]
    assert "generic_video_theme" not in assessment["issue_codes"]


def test_informative_source_name_still_requires_specific_profile() -> None:
    job = Job(
        source_path="F:/clips/merged_3_NOC_MT34_S06mini开箱玩法补充_未剪辑.mp4",
        source_name="merged_3_NOC_MT34_S06mini开箱玩法补充_未剪辑.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
        "automation_review": {"score": 0.6},
    }
    artifact = Artifact(artifact_type="content_profile_final", data_json=profile)

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[artifact],
        subtitle_items=[_subtitle(0, "看一下这里"), _subtitle(1, "这个操作")],
        completion_candidate=True,
    )

    assert "low_profile_confidence" in assessment["issue_codes"]
    assert assessment["score"] < 100.0


def test_stale_single_word_split_blocker_is_downgraded() -> None:
    job = Job(
        source_path="F:/clips/8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
    }
    artifacts = [
        Artifact(artifact_type="content_profile_final", data_json=profile),
        Artifact(
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json={
                "blocking": True,
                "blocking_reasons": ["普通词跨字幕截断 1 处"],
                "warning_reasons": [],
                "metrics": {"generic_word_split_count": 1},
                "score": 92,
            },
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介"), _subtitle(1, "绍一下")],
        completion_candidate=True,
    )

    assert "subtitle_quality_blocking" not in assessment["issue_codes"]


def test_short_fragment_rate_is_warning_not_blocking() -> None:
    subtitles = [
        {"text_final": "看"},
        {"text_final": "这里"},
        {"text_final": "这个"},
        {"text_final": "做工"},
        {"text_final": "细节"},
        {"text_final": "打开"},
        {"text_final": "侧面"},
        {"text_final": "按键"},
        {"text_final": "亮度"},
        {"text_final": "尾盖"},
        {"text_final": "卡扣"},
        {"text_final": "手感"},
        {"text_final": "换个角度"},
        {"text_final": "再对比一下"},
        {"text_final": "这款手电的按键和光斑表现都比较直观。"},
        {"text_final": "整体内容可以继续进入后续剪辑流程。"},
    ]

    report = build_subtitle_quality_report(subtitle_items=subtitles)

    assert report["blocking"] is False
    assert report["blocking_reasons"] == []
    assert any("短碎句率过高" in reason for reason in report["warning_reasons"])


def test_quality_assessment_applies_source_identity_constraints() -> None:
    job = Job(
        source_path="F:/clips/IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
        source_name="IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
        status="done",
    )
    profile = {
        "subject_brand": "BOLTBOAT",
        "subject_model": "FXX1小副包",
        "subject_type": "EDC机能包",
        "summary": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "video_theme": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "engagement_question": "你怎么看？",
    }

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[Artifact(artifact_type="content_profile_final", data_json=profile)],
        subtitle_items=[_subtitle(0, "这个影蚀斜挎包"), _subtitle(1, "收纳比较轻量")],
        completion_candidate=True,
    )

    assert "identity_narrative_conflict" not in assessment["issue_codes"]

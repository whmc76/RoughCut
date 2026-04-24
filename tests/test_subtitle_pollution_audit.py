from scripts.audit_batch_subtitles import _audit_job


def test_bag_carry_context_allows_flashlight_mentions() -> None:
    report = _audit_job(
        {
            "job_id": "job-1",
            "source_name": "BOLTBOAT 影蚀包",
            "status": "completed",
            "content_profile": {"subject_type": "机能包"},
            "transcript_excerpt": "[00:00] 这个包里放了很多一些玩的东西，包括工艺钳啊、手电啊什么的",
        },
        {},
    )

    assert report["category"] == "bag"
    assert report["blocking_count"] == 0
    assert report["manual_review_required"] is False


def test_knife_uncorrected_floodlight_word_still_blocks() -> None:
    report = _audit_job(
        {
            "job_id": "job-2",
            "source_name": "NOC MT33 两款折刀的外观和细节",
            "status": "completed",
            "content_profile": {"subject_type": "EDC折刀"},
            "transcript_excerpt": "[00:00] 呃，包括它上面这个钢瓦，钢瓦和这个盖瓦的这个泛光",
        },
        {},
    )

    assert report["category"] == "knife"
    assert report["blocking_count"] == 1
    assert report["manual_review_required"] is True


def test_knife_corrected_surface_reflection_passes() -> None:
    report = _audit_job(
        {
            "job_id": "job-3",
            "source_name": "NOC MT33 两款折刀的外观和细节",
            "status": "completed",
            "content_profile": {"subject_type": "EDC折刀"},
            "transcript_excerpt": "[00:00] 呃，包括它上面这个钢马，钢马和这个锆马的这个反光",
        },
        {},
    )

    assert report["category"] == "knife"
    assert report["blocking_count"] == 0
    assert report["manual_review_required"] is False

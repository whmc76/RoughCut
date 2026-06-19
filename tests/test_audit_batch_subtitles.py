from __future__ import annotations

from scripts.audit_batch_subtitles import _audit_job


def _bag_job(*, transcript_excerpt: str = "") -> dict[str, object]:
    return {
        "job_id": "job-1",
        "source_name": "IMG_0181 狐蝠工业 fxx1 戒备配色edc小副包.MOV",
        "status": "done",
        "quality_score": 100.0,
        "quality_grade": "A",
        "content_profile": {
            "subject_brand": "狐蝠工业",
            "subject_type": "小副包",
            "video_theme": "EDC小副包装载与快拆肩带体验",
        },
        "transcript_excerpt": transcript_excerpt,
    }


def test_bag_audit_allows_normal_open_close_action() -> None:
    report = _audit_job(
        _bag_job(
            transcript_excerpt="\n".join(
                [
                    "虽然不能像以前的那个蜜獾一样",
                    "很轻松的单手开合",
                    "但是实际上也不是不能开",
                ]
            )
        ),
        {"plain_srt": ""},
    )

    assert report["severity"] == "low"
    assert report["blocking_findings"] == []


def test_bag_audit_uses_adjacent_subtitle_context_for_edc_contents() -> None:
    report = _audit_job(
        _bag_job(
            transcript_excerpt="\n".join(
                [
                    "这个包里可以放很多小东西",
                    "包括呃工",
                    "具钳啊手电啊什么",
                    "的再加上它的自重",
                ]
            )
        ),
        {"plain_srt": ""},
    )

    assert report["severity"] == "low"
    assert report["blocking_findings"] == []


def test_bag_audit_still_blocks_strong_knife_model_drift() -> None:
    report = _audit_job(
        _bag_job(transcript_excerpt="这个EDC17折刀帕的钢材表现非常明显"),
        {"plain_srt": ""},
    )

    assert report["severity"] == "critical"
    assert any(item["kind"] == "knife_drift_flashlight_model" for item in report["blocking_findings"])

from roughcut.api.jobs import _ensure_content_understanding_payload
from roughcut.review.content_profile import _attach_content_understanding_timed_focus_spans


def test_attach_content_understanding_timed_focus_spans_from_evidence_bundle() -> None:
    profile = {
        "content_understanding": {
            "video_type": "unboxing",
            "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
        }
    }
    evidence_bundle = {
        "semantic_fact_inputs": {
            "timed_focus_spans": [
                {
                    "timestamp": "00:00-00:02",
                    "text": "开场先讲结论",
                    "type": "hook",
                    "start_time": 0.0,
                    "end_time": 2.0,
                },
                {
                    "timestamp": "00:02-00:05",
                    "text": "这里拿 EDC17 和 EDC37 做对比",
                    "type": "comparison",
                    "start_time": 2.0,
                    "end_time": 5.0,
                },
            ]
        }
    }

    enriched = _attach_content_understanding_timed_focus_spans(profile, evidence_bundle=evidence_bundle)

    assert len(enriched["content_understanding"]["timed_focus_spans"]) == 2
    assert enriched["content_understanding"]["timed_focus_spans"][0]["type"] == "hook"


def test_ensure_content_understanding_payload_preserves_timed_focus_spans() -> None:
    payload = _ensure_content_understanding_payload(
        {
            "subject_type": "NITECORE EDC17 手电",
            "content_understanding": {
                "video_type": "unboxing",
                "content_domain": "flashlight",
                "primary_subject": "NITECORE EDC17 手电",
                "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
                "timed_focus_spans": [
                    {
                        "timestamp": "00:00-00:02",
                        "text": "开场先讲结论",
                        "type": "hook",
                        "start_time": 0.0,
                        "end_time": 2.0,
                    }
                ],
                "needs_review": False,
            },
        }
    )

    assert payload is not None
    assert payload["content_understanding"]["timed_focus_spans"][0]["timestamp"] == "00:00-00:02"
    assert payload["content_understanding"]["evidence_spans"][0]["type"] == "comparison"

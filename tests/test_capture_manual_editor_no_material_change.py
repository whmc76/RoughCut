from types import SimpleNamespace

from scripts import capture_manual_editor_no_material_change as capture


class _FakeVideoTransform:
    def model_dump(self):
        return {
            "rotation_cw": 90,
            "aspect_ratio": "source",
            "resolution_mode": "source",
            "resolution_preset": "1080p",
        }


def test_build_no_material_change_request_payload_uses_base_session_state() -> None:
    session_payload = SimpleNamespace(
        base_keep_segments=[SimpleNamespace(model_dump=lambda include=None: {"start": 1.2345, "end": 9.8765})],
        base_video_transform=_FakeVideoTransform(),
        smart_cut_rules={"fillers": True},
        base_video_summary="summary",
        timeline_id="timeline-1",
        timeline_version=3,
        render_plan_version=5,
        subtitle_fingerprint="fp-1",
    )

    payload = capture._build_no_material_change_request_payload(session_payload)

    assert payload == {
        "keep_segments": [{"start": 1.234, "end": 9.877}],
        "subtitle_overrides": [],
        "subtitle_replacements": [],
        "video_transform": {
            "rotation_cw": 90,
            "aspect_ratio": "source",
            "resolution_mode": "source",
            "resolution_preset": "1080p",
        },
        "smart_cut_rules": {"fillers": True},
        "video_summary": "summary",
        "base_timeline_id": "timeline-1",
        "base_timeline_version": 3,
        "base_render_plan_version": 5,
        "base_subtitle_fingerprint": "fp-1",
        "note": "codex_capture_no_material_change",
    }

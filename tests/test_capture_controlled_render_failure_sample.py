from scripts import capture_controlled_render_failure_sample as capture


def test_inject_controlled_failure_sets_invalid_intro_and_clears_other_bookends() -> None:
    payload = capture._inject_controlled_failure(
        {
            "intro": None,
            "outro": {"path": "old-outro.mp4"},
            "insert": {"path": "old-insert.mp4"},
        },
        failure_mode="render_ffprobe_failed",
    )

    assert payload["intro"]["path"].endswith("docs\\agent-doc-index.md") or payload["intro"]["path"].endswith("docs/agent-doc-index.md")
    assert payload["intro"]["source"] == "controlled_failure_sample"
    assert payload["outro"] is None
    assert payload["insert"] is None

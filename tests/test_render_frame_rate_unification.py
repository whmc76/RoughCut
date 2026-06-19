from types import SimpleNamespace

import pytest

from roughcut.edit.manual_editor_contract import manual_editor_is_subtitle_only_render
from roughcut.edit import render_plan as render_plan_module
from roughcut.edit.render_plan import build_ai_effect_render_plan, build_render_plan, build_smart_editing_accents
from roughcut.media import render as render_module
from roughcut.media.render import (
    _apply_packaging_plan,
    _apply_music_and_watermark,
    _apply_timed_overlays_to_video,
    _build_timed_overlay_filter_chain,
    _build_hyperframes_visual_filters,
    _build_overlay_only_editing_accents,
    _normalize_render_emphasis_overlays,
    _normalize_watermark_plan,
    _default_dynamic_text_watermark_plan,
    _watermark_detection_sample_times,
    _render_packaging_context,
    _render_runtime_plan_context,
    _build_segment_filter_chain,
    _build_video_transform_editing_accents,
    _ffmpeg_fps_expr,
    _run_process,
    _resolve_delivery_frame_rate,
    render_video,
)
from roughcut import hyperframes as hyperframes_module
from roughcut.packaging.library import _normalize_config
from roughcut.hyperframes import HYPERFRAMES_PLAN_SCHEMA


def test_packaging_config_accepts_export_frame_rate_selection() -> None:
    config = _normalize_config(
        {
            "export_frame_rate_mode": "specified",
            "export_frame_rate_preset": "50",
        },
        {},
    )

    assert config["export_frame_rate_mode"] == "specified"
    assert config["export_frame_rate_preset"] == "50"


def test_packaging_config_clamps_watermark_to_low_intrusion_defaults() -> None:
    config = _normalize_config(
        {
            "watermark_opacity": 0.82,
            "watermark_scale": 0.16,
        },
        {},
    )

    assert config["watermark_opacity"] == 0.34
    assert config["watermark_scale"] == 0.12


def test_render_plan_carries_user_selected_frame_rate() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        export_frame_rate_mode="specified",
        export_frame_rate_preset="25",
    )

    assert plan["delivery"]["frame_rate_mode"] == "specified"
    assert plan["delivery"]["frame_rate_preset"] == "25"


def test_delivery_frame_rate_uses_source_or_selected_preset() -> None:
    assert _resolve_delivery_frame_rate(source_fps=29.97, delivery={"frame_rate_mode": "source"}) == 29.97
    assert _resolve_delivery_frame_rate(
        source_fps=29.97,
        delivery={"frame_rate_mode": "specified", "frame_rate_preset": "60"},
    ) == 60.0
    assert _ffmpeg_fps_expr(29.97) == "30000/1001"


@pytest.mark.asyncio
async def test_run_process_closes_asyncio_subprocess_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = False
    pipe_closed: list[int] = []

    class FakeTransport:
        def __init__(self) -> None:
            self._pipes = {
                1: SimpleNamespace(pipe=FakePipeTransport(1)),
                2: SimpleNamespace(pipe=FakePipeTransport(2)),
            }

        def close(self) -> None:
            nonlocal closed
            closed = True

    class FakePipeTransport:
        def __init__(self, fd: int) -> None:
            self.fd = fd

        def close(self) -> None:
            pipe_closed.append(self.fd)

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self._transport = FakeTransport()

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"out", b"err"

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeProcess:
        del args, kwargs
        return FakeProcess()

    monkeypatch.setattr(render_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await _run_process(["ffmpeg", "-version"], timeout=5)

    assert result.returncode == 0
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert closed is True
    assert pipe_closed == [1, 2]


def test_segment_filters_force_target_frame_rate_before_concat() -> None:
    filters, video_label, _audio_label = _build_segment_filter_chain(
        [
            {"type": "keep", "start": 0.0, "end": 1.0},
            {"type": "keep", "start": 2.0, "end": 3.0},
        ],
        transpose_suffix="",
        editing_accents={"transitions": {"enabled": False}},
        target_fps_expr="25",
    )

    assert video_label == "vout"
    assert any("fps=25,settb=AVTB[v0]" in item for item in filters)
    assert any("fps=25,settb=AVTB[v1]" in item for item in filters)


def test_segment_filters_reuse_transition_config_for_xfade() -> None:
    filters, video_label, _audio_label = _build_segment_filter_chain(
        [
            {"type": "keep", "start": 0.0, "end": 1.0},
            {"type": "keep", "start": 2.0, "end": 3.0},
        ],
        transpose_suffix="",
        editing_accents={
            "transitions": {
                "enabled": True,
                "transition": "wipeleft",
                "duration_sec": 0.18,
                "boundary_indexes": [0],
            }
        },
    )

    assert video_label == "vout"
    assert any("xfade=transition=wipeleft:duration=0.18:offset=0.82" in item for item in filters)


def test_ai_effect_render_plan_reuses_bound_assets_for_manual_subtitle_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_plan_module,
        "_build_section_choreography",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild section choreography")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_insert_to_section_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind insert")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_music_to_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind music")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_subtitles_to_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind subtitles")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_select_transition_boundaries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild transition boundaries")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_select_emphasis_overlays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild emphasis overlays")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_build_transition_pulse_overlays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild transition pulse overlays")),
    )

    plan = build_ai_effect_render_plan(
        {
            "workflow_preset": "unboxing_standard",
            "section_choreography": {"sections": [{"start_time": 0.0, "end_time": 5.0}]},
            "insert": {"asset_id": "insert-a", "start_time": 1.0},
            "music": {"asset_id": "music-a", "start_time": 0.0},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static", "version": 1},
            "editing_accents": {
                "style": "smart_effect_commercial",
                "transitions": {"enabled": True, "boundary_indexes": [1], "duration_sec": 0.12},
                "emphasis_overlays": [{"text": "kept", "start_time": 0.8, "end_time": 1.2}],
                "sound_effects": [{"start_time": 0.8, "duration_sec": 0.08, "frequency": 880, "volume": 0.04}],
            },
        },
        reuse_bound_assets=True,
    )

    assert plan["section_choreography"] == {"sections": [{"start_time": 0.0, "end_time": 5.0}]}
    assert plan["insert"] == {"asset_id": "insert-a", "start_time": 1.0}
    assert plan["music"] == {"asset_id": "music-a", "start_time": 0.0}
    assert plan["subtitles"]["style"] == "bold_yellow_outline"
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == [1]
    assert plan["editing_accents"]["emphasis_overlays"] == [{"text": "kept", "start_time": 0.8, "end_time": 1.2}]
    assert plan["editing_accents"]["sound_effects"] == [
        {"start_time": 0.8, "duration_sec": 0.08, "frequency": 880, "volume": 0.04}
    ]


def test_manual_editor_subtitle_only_contract_is_shared_with_render() -> None:
    assert manual_editor_is_subtitle_only_render(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "reuse_timeline_effect_plan",
            "timeline_changed": False,
        }
    ) is True
    assert manual_editor_is_subtitle_only_render(
        {
            "change_scope": "timeline",
            "render_strategy": "full_timeline_render",
            "timeline_changed": True,
        }
    ) is False


def test_overlay_only_editing_accents_can_skip_subtitle_unit_synthesis() -> None:
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_commercial",
            "emphasis_overlays": [{"text": "kept", "start_time": 0.4, "end_time": 0.8}],
            "sound_effects": [{"start_time": 0.4, "frequency": 880}],
        },
        subtitle_items=[
            {
                "text_final": "new subtitle text",
                "start_time": 1.0,
                "end_time": 1.5,
                "subtitle_unit_role": "lead",
            }
        ],
        synthesize_subtitle_unit_accents=False,
    )

    assert accents["emphasis_overlays"] == [{"text": "kept", "start_time": 0.4, "end_time": 1.25}]
    assert accents["sound_effects"] == [{"start_time": 0.4, "frequency": 880}]


def test_render_packaging_context_reads_nested_packaging_timeline_payload() -> None:
    context = _render_packaging_context(
        {
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "section_choreography": {"sections": [{"start_time": 0.0, "end_time": 5.0}]},
                "editing_accents": {"style": "smart_effect_punch"},
                "focus": {"focus_events": [{"event_type": "hook_focus", "start_time": 0.0, "end_time": 2.0, "text": "先讲结论"}]},
                "packaging": {
                    "intro": {"path": "intro.mp4"},
                    "music": {"path": "music.mp3", "enter_sec": 4.2, "timing_summary": {"review_recommended": False}},
                },
            }
        }
    )

    assert context["subtitles"]["style"] == "clean_white"
    assert context["section_choreography"]["sections"] == [{"start_time": 0.0, "end_time": 5.0}]
    assert context["editing_accents"]["style"] == "smart_effect_punch"
    assert context["has_packaging_assets"] is True
    assert context["assets"]["intro"] == {"path": "intro.mp4"}
    assert context["assets"]["music"]["path"] == "music.mp3"
    assert context["focus"]["focus_events"][0]["event_type"] == "hook_focus"
    assert context["assets"]["music"]["audio_cues"][0]["kind"] == "bgm_entry"
    assert context["audio_cues"][0]["kind"] == "bgm_entry"
    assert context["hyperframes"]["schema"] == HYPERFRAMES_PLAN_SCHEMA
    assert "progress_bar" in set(context["hyperframes"]["tracks"])


def test_render_packaging_context_reuses_local_assets_for_presence() -> None:
    from roughcut.media import render as render_module

    assert not hasattr(render_module, "packaging_timeline_has_packaging_assets")

    context = _render_packaging_context(
        {
            "packaging_timeline": {
                "packaging": {
                    "outro": {"path": "outro.mp4"},
                }
            }
        }
    )

    assert context["has_packaging_assets"] is True
    assert context["assets"]["outro"] == {"path": "outro.mp4"}


def test_render_packaging_context_reuses_local_normalized_packaging_payload(
) -> None:
    from roughcut.media import render as render_module

    assert not hasattr(render_module, "packaging_timeline_assets")
    assert not hasattr(render_module, "packaging_timeline_editing_accents")
    assert not hasattr(render_module, "packaging_timeline_section_choreography")
    assert not hasattr(render_module, "packaging_timeline_subtitles")

    context = _render_packaging_context(
        {
            "packaging": {
                "intro": {"path": "intro.mp4"},
            },
            "editing_accents": {"style": "smart_effect_punch"},
            "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 2.0}]},
            "subtitles": {"style": "clean_white"},
        }
    )

    assert context["assets"] == {
        "intro": {"path": "intro.mp4"},
        "outro": None,
        "insert": None,
        "watermark": None,
        "music": None,
    }
    assert context["editing_accents"] == {"style": "smart_effect_punch"}
    assert context["has_packaging_assets"] is True
    assert context["focus"] is None
    assert context["audio_cues"] == []
    assert context["section_choreography"] == {"sections": [{"start_sec": 0.0, "end_sec": 2.0}]}
    assert context["subtitles"] == {"style": "clean_white"}
    assert context["hyperframes"]["schema"] == HYPERFRAMES_PLAN_SCHEMA


def test_render_plan_uses_hyperframes_as_visual_timeline() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        subtitle_style="keyword_highlight",
        subtitle_motion_style="motion_pop",
        editing_accents={
            "style": "smart_effect_punch",
            "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.16},
            "emphasis_overlays": [{"text": "重点", "start_time": 0.4, "end_time": 1.2}],
            "sound_effects": [],
        },
    )

    assert plan["render_engine"] == "hyperframes"
    assert plan["hyperframes"]["schema"] == HYPERFRAMES_PLAN_SCHEMA
    assert plan["packaging_timeline"]["hyperframes"]["schema"] == HYPERFRAMES_PLAN_SCHEMA
    assert plan["hyperframes"]["metadata"]["subtitle"]["style"] == "keyword_highlight"
    assert plan["hyperframes"]["metadata"]["effects"]["style"] == "smart_effect_punch"


def test_hyperframes_progress_filter_draws_real_chapter_segments() -> None:
    plan = hyperframes_module.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=12.0,
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "先看整体", "subtitle_section_role": "hook"},
            {"start_time": 3.0, "end_time": 6.0, "text_final": "结构细节", "subtitle_section_role": "detail"},
            {"start_time": 8.0, "end_time": 11.0, "text_final": "最后总结", "subtitle_section_role": "cta"},
        ],
    )

    filter_parts, video_label = _build_hyperframes_visual_filters(
        "v0",
        plan,
        render_w=1920,
        render_h=1080,
    )
    filter_text = ";".join(filter_parts)

    assert video_label.startswith("vhfprogress")
    assert "T/12.0" in filter_text
    assert "geq=" in filter_text
    assert "color=black@0.45" in filter_text
    assert "h=45" in filter_text
    assert "vhfprogresschaptertick1" in filter_text
    assert "vhfprogresschaptertitle1" in filter_text
    assert "text='细节'" in filter_text
    assert "结构细节" not in filter_text
    assert "color=0x28d3a2" not in filter_text
    assert "color=0x4f8cff" not in filter_text
    assert "color=white@0.58" in filter_text


def test_smart_editing_accents_use_social_packaging_density_by_default() -> None:
    subtitle_items = [
        {"start_time": 0.2, "end_time": 1.0, "text_final": "你看这个快拆结构", "subtitle_unit_role": "lead"},
        {"start_time": 4.2, "end_time": 5.0, "text_final": "这里是锁定细节", "subtitle_unit_role": "focus"},
        {"start_time": 8.6, "end_time": 9.4, "text_final": "直接演示容量", "subtitle_unit_role": "focus"},
        {"start_time": 13.0, "end_time": 13.8, "text_final": "对比一下区别", "subtitle_unit_role": "focus"},
        {"start_time": 17.4, "end_time": 18.2, "text_final": "实测背负效果", "subtitle_unit_role": "focus"},
        {"start_time": 21.8, "end_time": 22.6, "text_final": "注意这个功能", "subtitle_unit_role": "focus"},
    ]

    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 7.0},
            {"start": 8.0, "end": 11.0},
            {"start": 12.0, "end": 15.0},
            {"start": 16.0, "end": 19.0},
        ],
        subtitle_items=subtitle_items,
        timeline_analysis={
            "semantic_sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 3.5},
                {"role": "detail", "start_sec": 3.5, "end_sec": 15.5},
                {"role": "body", "start_sec": 15.5, "end_sec": 24.0},
            ]
        },
        style="smart_effect_commercial",
    )

    assert len(accents["emphasis_overlays"]) >= 5
    assert len(accents["sound_effects"]) == len(accents["emphasis_overlays"])
    assert accents["social_packaging"]["strategy"] == "hyperframes_social_retention_v2"
    assert accents["social_packaging"]["target_density"]["overlay_max_count"] >= 6
    assert {item["visual_treatment"] for item in accents["emphasis_overlays"]} >= {"hook_pop", "keyword_sticker"}
    overlay_texts = [item["text"] for item in accents["emphasis_overlays"] if item.get("text")]
    assert overlay_texts
    assert all(len(text) <= 8 for text in overlay_texts)
    assert "你看这个快拆结构" not in overlay_texts
    assert "这里是锁定细节" not in overlay_texts
    assert any("快拆" in text for text in overlay_texts)
    assert sum(any(keyword in text for keyword in ("演示", "容量", "对比", "实测", "背负", "功能")) for text in overlay_texts) >= 3
    assert all("一下" not in text for text in overlay_texts)


def test_smart_editing_accents_do_not_promote_long_spoken_lines_to_popups() -> None:
    accents = build_smart_editing_accents(
        keep_segments=[{"start": 0.0, "end": 5.0}],
        subtitle_items=[
            {
                "start_time": 0.2,
                "end_time": 2.4,
                "text_final": "也还行因为它不太不算疼嘛呢看啊这个刀",
                "subtitle_unit_role": "focus",
            }
        ],
        timeline_analysis={"semantic_sections": [{"role": "detail", "start_sec": 0.0, "end_sec": 5.0}]},
        style="smart_effect_commercial",
    )

    assert [item.get("text") for item in accents["emphasis_overlays"] if item.get("text")] == []


def test_ai_effect_render_plan_rebuilds_hyperframes_after_effect_enrichment() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        subtitle_style="keyword_highlight",
        subtitle_motion_style="motion_pop",
        editing_accents={
            "style": "smart_effect_commercial",
            "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
            "emphasis_overlays": [],
            "sound_effects": [],
        },
    )

    ai_plan = build_ai_effect_render_plan(
        plan,
        keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}],
        subtitle_items=[
            {"start_time": 0.2, "end_time": 1.0, "text_final": "你看这个重点", "subtitle_unit_role": "lead"}
        ],
    )

    assert ai_plan["editing_accents"]["style"] == "smart_effect_commercial_ai"
    assert ai_plan["hyperframes"]["metadata"]["effects"]["style"] == "smart_effect_commercial_ai"
    assert ai_plan["packaging_timeline"]["hyperframes"]["metadata"]["effects"]["style"] == "smart_effect_commercial_ai"


@pytest.mark.asyncio
async def test_timed_overlay_filter_chain_applies_unified_hyperframes_subtitle_style(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    async def _fake_resolve_subtitle_margin_with_avatar(**_kwargs) -> None:
        return None

    captured: dict[str, object] = {}

    def _fake_write_ass_file(subtitles, _path, **kwargs) -> None:
        captured["subtitles"] = list(subtitles)
        captured["kwargs"] = dict(kwargs)

    monkeypatch.setattr(
        "roughcut.media.render._resolve_subtitle_margin_with_avatar",
        _fake_resolve_subtitle_margin_with_avatar,
    )
    monkeypatch.setattr("roughcut.media.subtitles.write_ass_file", _fake_write_ass_file)
    monkeypatch.setattr("roughcut.media.subtitles.escape_path_for_ffmpeg_filter", lambda _path: "escaped.ass")

    hyperframes_plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        subtitle_style="keyword_highlight",
        subtitle_motion_style="motion_pop",
    )["hyperframes"]

    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan=None,
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo", "style_name": "white_minimal"}],
        choreographed_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo", "style_name": "white_minimal"}],
        overlay_plan={},
        output_path=tmp_path / "overlay.mp4",
        render_w=1920,
        render_h=1080,
        video_label="v0",
        audio_label="a0",
        debug_dir=None,
        subtitles_plan={"style": "white_minimal", "motion_style": "motion_static"},
        hyperframes_plan=hyperframes_plan,
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert any("subtitles='escaped.ass'[vsub]" in item for item in filter_parts)
    assert video_label.endswith("progress") or video_label == "vsub"
    assert audio_label == "a0"
    assert captured["kwargs"]["style_name"] == "keyword_highlight"
    assert captured["kwargs"]["motion_style"] == "motion_pop"
    assert captured["subtitles"][0]["style_name"] == "keyword_highlight"
    assert captured["subtitles"][0]["motion_style"] == "motion_pop"


def test_render_runtime_plan_context_reads_render_plan_once() -> None:
    context = _render_runtime_plan_context(
        {
            "delivery": {"frame_rate_mode": "specified", "frame_rate_preset": "50"},
            "manual_editor": {"video_transform": {"rotation_manual": True, "rotation_cw": 90}},
            "avatar_commentary": {"mode": "full_track_audio_passthrough"},
            "voice_processing": {"noise_reduction": False},
            "loudness": {"target_lufs": -14.0, "peak_limit": -1.0},
        }
    )

    assert context == {
        "delivery": {"frame_rate_mode": "specified", "frame_rate_preset": "50"},
        "video_transform": {
            "rotation_manual": True,
            "rotation_cw": 90,
            "aspect_ratio": "source",
            "resolution_mode": "source",
            "resolution_preset": "1080p",
        },
        "avatar_plan": {"mode": "full_track_audio_passthrough"},
        "voice_processing": {"noise_reduction": False},
        "loudness": {"target_lufs": -14.0, "peak_limit": -1.0},
    }


@pytest.mark.asyncio
async def test_render_video_reuses_passed_packaging_assets_and_runtime_contexts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided packaging context")),
    )
    monkeypatch.setattr(
        "roughcut.media.render._render_runtime_plan_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided runtime plan context")),
    )
    monkeypatch.setattr("roughcut.media.render._probe_duration", lambda _path: 0.0)
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
            "fps": 30.0,
        },
    )
    monkeypatch.setattr("roughcut.media.render._write_debug_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("roughcut.media.render._write_debug_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("roughcut.media.render._write_process_debug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("roughcut.media.render._append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)
    monkeypatch.setattr("roughcut.media.render._build_segment_filter_chain", lambda *args, **kwargs: ([], "0:v", "0:a"))
    monkeypatch.setattr("roughcut.media.render._build_video_transform_editing_accents", lambda *args, **kwargs: {})
    monkeypatch.setattr("roughcut.media.render._build_master_audio_filter_chain", lambda **_kwargs: "anull[afinal]")
    monkeypatch.setattr("roughcut.media.render._prefer_software_encoder_for_source", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("roughcut.media.render._video_delivery_encode_args", lambda **_kwargs: [])
    monkeypatch.setattr("roughcut.media.render._audio_encode_args", lambda: [])
    monkeypatch.setattr(
        "roughcut.media.rotation.detect_video_rotation_decision",
        lambda _source_path: (_ for _ in ()).throw(AssertionError("should not detect rotation when manual runtime context already provides it")),
    )

    async def _fake_run_process(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    async def _fake_normalize_rendered_output(*_args, **_kwargs):
        return None

    observed: dict[str, object] = {}

    async def _fake_apply_packaging_plan(source_path, **kwargs):
        observed["packaging_render_plan"] = kwargs["render_plan"]
        observed["packaging_context"] = kwargs["packaging_context"]
        observed["packaging_assets"] = kwargs["packaging_assets"]
        return kwargs["output_path"]

    async def _fake_apply_timed_overlays_to_video(source_path, **kwargs):
        observed["overlay_render_plan"] = kwargs["render_plan"]
        observed["overlay_packaging_context"] = kwargs["packaging_context"]
        observed["overlay_subtitles_plan"] = kwargs["subtitles_plan"]
        observed["overlay_section_choreography"] = kwargs["section_choreography"]
        observed["overlay_avatar_plan"] = kwargs["avatar_plan"]
        return kwargs["output_path"]

    monkeypatch.setattr("roughcut.media.render._run_process", _fake_run_process)
    monkeypatch.setattr("roughcut.media.render._normalize_rendered_output", _fake_normalize_rendered_output)
    monkeypatch.setattr("roughcut.media.render._apply_packaging_plan", _fake_apply_packaging_plan)
    monkeypatch.setattr("roughcut.media.render._apply_timed_overlays_to_video", _fake_apply_timed_overlays_to_video)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    output_path = await render_video(
        source_path=tmp_path / "source.mp4",
        render_plan=None,
        editorial_timeline={},
        output_path=tmp_path / "final.mp4",
        keep_segments=[{"type": "keep", "start": 0.0, "end": 1.0}],
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        packaging_context={
            "assets": {"intro": {"path": "intro.mp4"}},
            "editing_accents": {},
            "has_packaging_assets": True,
            "section_choreography": {"sections": []},
            "subtitles": {"style": "clean_white"},
        },
        runtime_plan_context={
            "delivery": {"frame_rate_mode": "source"},
            "video_transform": {
                "rotation_manual": True,
                "rotation_cw": 0,
                "aspect_ratio": "source",
                "resolution_mode": "source",
                "resolution_preset": "1080p",
            },
            "avatar_plan": {"mode": "full_track_audio_passthrough"},
            "voice_processing": {},
            "loudness": {},
        },
    )

    assert output_path == tmp_path / "final.mp4"
    assert observed["packaging_render_plan"] is None
    assert observed["packaging_context"] is None
    assert observed["packaging_assets"] == {"intro": {"path": "intro.mp4"}}
    assert observed["overlay_render_plan"] is None
    assert observed["overlay_packaging_context"] is None
    assert observed["overlay_subtitles_plan"] == {"style": "clean_white"}
    assert observed["overlay_section_choreography"] == {"sections": []}
    assert observed["overlay_avatar_plan"] == {"mode": "full_track_audio_passthrough"}


@pytest.mark.asyncio
async def test_apply_packaging_plan_reuses_nested_packaging_asset_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr("roughcut.media.render._stage_packaging_source", lambda source_path, _tmp: source_path)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    async def _fake_apply_insert_clip(source_path, **kwargs):
        calls.append(("insert", {"source_path": source_path, **kwargs}))
        return kwargs["output_path"]

    async def _fake_apply_intro_outro(source_path, **kwargs):
        calls.append(("bookends", {"source_path": source_path, **kwargs}))
        return kwargs["output_path"]

    async def _fake_apply_music_and_watermark(source_path, **kwargs):
        calls.append(("packaged", {"source_path": source_path, **kwargs}))
        return kwargs["output_path"]

    monkeypatch.setattr("roughcut.media.render._apply_insert_clip", _fake_apply_insert_clip)
    monkeypatch.setattr("roughcut.media.render._apply_intro_outro", _fake_apply_intro_outro)
    monkeypatch.setattr("roughcut.media.render._apply_music_and_watermark", _fake_apply_music_and_watermark)

    output_path = await _apply_packaging_plan(
        tmp_path / "source.mp4",
        render_plan={
            "packaging_timeline": {
                "packaging": {
                    "insert": {"path": "insert.mp4"},
                    "intro": {"path": "intro.mp4"},
                    "outro": {"path": "outro.mp4"},
                    "music": {"path": "music.mp3"},
                    "watermark": {"path": "watermark.png"},
                }
            }
        },
        output_path=tmp_path / "final.mp4",
        expected_width=1920,
        expected_height=1080,
        debug_dir=None,
        target_fps=30.0,
    )

    assert output_path == tmp_path / "final.mp4"
    assert [name for name, _payload in calls] == ["insert", "bookends", "packaged"]
    assert calls[0][1]["insert_plan"] == {"path": "insert.mp4"}
    assert calls[1][1]["intro_plan"] == {"path": "intro.mp4"}
    assert calls[1][1]["outro_plan"] == {"path": "outro.mp4"}
    assert calls[2][1]["music_plan"] == {
        "path": "music.mp3",
        "audio_cues": [
            {
                "kind": "bgm_entry",
                "time_sec": 0.0,
                "reason": "",
                "review_recommended": False,
            }
        ],
    }
    assert calls[2][1]["watermark_plan"] == {"path": "watermark.png"}


def test_render_packaging_context_normalizes_nested_insert_payload() -> None:
    context = _render_packaging_context(
        {
            "packaging_timeline": {
                "packaging": {
                    "insert": {
                        "asset_id": "insert-a",
                        "path": "insert.mp4",
                        "insert_target_duration_sec": 1.23456,
                    }
                }
            }
        }
    )

    assert context["assets"]["insert"]["insert_target_duration_sec"] == 1.235
    assert context["assets"]["insert"]["candidate_assets"][0]["asset_id"] == "insert-a"


@pytest.mark.asyncio
async def test_apply_packaging_plan_reuses_passed_packaging_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided packaging context")),
    )
    monkeypatch.setattr("roughcut.media.render._stage_packaging_source", lambda source_path, _tmp: source_path)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    async def _fake_apply_insert_clip(source_path, **kwargs):
        return kwargs["output_path"]

    monkeypatch.setattr("roughcut.media.render._apply_insert_clip", _fake_apply_insert_clip)

    output_path = await _apply_packaging_plan(
        tmp_path / "source.mp4",
        render_plan=None,
        output_path=tmp_path / "final.mp4",
        expected_width=1920,
        expected_height=1080,
        debug_dir=None,
        target_fps=30.0,
        packaging_context={"assets": {"insert": {"path": "insert.mp4"}}},
    )

    assert output_path == tmp_path / "final.mp4"


@pytest.mark.asyncio
async def test_apply_packaging_plan_reuses_passed_packaging_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided packaging assets")),
    )
    monkeypatch.setattr("roughcut.media.render._stage_packaging_source", lambda source_path, _tmp: source_path)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    async def _fake_apply_insert_clip(source_path, **kwargs):
        return kwargs["output_path"]

    monkeypatch.setattr("roughcut.media.render._apply_insert_clip", _fake_apply_insert_clip)

    output_path = await _apply_packaging_plan(
        tmp_path / "source.mp4",
        render_plan=None,
        output_path=tmp_path / "final.mp4",
        expected_width=1920,
        expected_height=1080,
        debug_dir=None,
        target_fps=30.0,
        packaging_assets={"insert": {"path": "insert.mp4"}},
    )

    assert output_path == tmp_path / "final.mp4"


@pytest.mark.asyncio
async def test_timed_overlay_filter_chain_reuses_passed_packaging_context_and_avatar_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided packaging context")),
    )
    monkeypatch.setattr(
        "roughcut.media.render.render_plan_avatar_commentary",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided avatar plan")),
    )

    async def _fake_resolve_subtitle_margin_with_avatar(**_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "roughcut.media.render._resolve_subtitle_margin_with_avatar",
        _fake_resolve_subtitle_margin_with_avatar,
    )
    monkeypatch.setattr("roughcut.media.subtitles.write_ass_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("roughcut.media.subtitles.escape_path_for_ffmpeg_filter", lambda _path: "escaped.ass")

    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan=None,
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        overlay_plan={},
        output_path=tmp_path / "overlay.mp4",
        render_w=1920,
        render_h=1080,
        video_label="v0",
        audio_label="a0",
        debug_dir=None,
        packaging_context={"subtitles": {"style": "clean_white", "motion_style": "motion_static"}},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert any("subtitles='escaped.ass'[vsub]" in item for item in filter_parts)
    assert video_label == "vsub"
    assert audio_label == "a0"


@pytest.mark.asyncio
async def test_timed_overlay_filter_chain_reuses_passed_subtitles_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided subtitles plan")),
    )

    async def _fake_resolve_subtitle_margin_with_avatar(**_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "roughcut.media.render._resolve_subtitle_margin_with_avatar",
        _fake_resolve_subtitle_margin_with_avatar,
    )
    monkeypatch.setattr("roughcut.media.subtitles.write_ass_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("roughcut.media.subtitles.escape_path_for_ffmpeg_filter", lambda _path: "escaped.ass")

    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan=None,
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        overlay_plan={},
        output_path=tmp_path / "overlay.mp4",
        render_w=1920,
        render_h=1080,
        video_label="v0",
        audio_label="a0",
        debug_dir=None,
        subtitles_plan={"style": "clean_white", "motion_style": "motion_static"},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert any("subtitles='escaped.ass'[vsub]" in item for item in filter_parts)
    assert video_label == "vsub"
    assert audio_label == "a0"


@pytest.mark.asyncio
async def test_timed_overlay_filter_chain_reuses_passed_choreographed_subtitles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._build_choreographed_subtitle_items",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse provided choreographed subtitles")),
    )

    captured_subtitles: list[dict] = []

    async def _fake_resolve_subtitle_margin_with_avatar(**_kwargs) -> None:
        return None

    def _fake_write_ass_file(subtitles, *_args, **_kwargs) -> None:
        captured_subtitles.extend(subtitles)

    monkeypatch.setattr(
        "roughcut.media.render._resolve_subtitle_margin_with_avatar",
        _fake_resolve_subtitle_margin_with_avatar,
    )
    monkeypatch.setattr("roughcut.media.subtitles.write_ass_file", _fake_write_ass_file)
    monkeypatch.setattr("roughcut.media.subtitles.escape_path_for_ffmpeg_filter", lambda _path: "escaped.ass")

    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan={"packaging_timeline": {"subtitles": {"style": "should_not_be_read"}}},
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "raw"}],
        choreographed_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "styled"}],
        overlay_plan={},
        output_path=tmp_path / "overlay.mp4",
        render_w=1920,
        render_h=1080,
        video_label="v0",
        audio_label="a0",
        debug_dir=None,
        packaging_context={"subtitles": {"style": "clean_white", "motion_style": "motion_static"}},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert captured_subtitles == [{"start_time": 0.0, "end_time": 1.0, "text_final": "styled"}]
    assert any("subtitles='escaped.ass'[vsub]" in item for item in filter_parts)
    assert video_label == "vsub"
    assert audio_label == "a0"


@pytest.mark.asyncio
async def test_apply_timed_overlays_reuses_passed_packaging_context_and_avatar_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided packaging context")),
    )
    monkeypatch.setattr(
        "roughcut.media.render.render_plan_avatar_commentary",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided avatar plan")),
    )
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
            "fps": 30.0,
        },
    )
    monkeypatch.setattr("roughcut.media.render._append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)

    observed: dict[str, object] = {}

    async def _fake_build_timed_overlay_filter_chain(**kwargs):
        observed["render_plan"] = kwargs["render_plan"]
        observed["packaging_context"] = kwargs["packaging_context"]
        observed["subtitles_plan"] = kwargs["subtitles_plan"]
        observed["avatar_plan"] = kwargs["avatar_plan"]
        return [], kwargs["video_label"], kwargs["audio_label"]

    monkeypatch.setattr("roughcut.media.render._build_timed_overlay_filter_chain", _fake_build_timed_overlay_filter_chain)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    output_path = await _apply_timed_overlays_to_video(
        tmp_path / "source.mp4",
        output_path=tmp_path / "overlay.mp4",
        render_plan={"packaging_timeline": {"subtitles": {"style": "should_not_be_read"}}},
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        overlay_editing_accents={"emphasis_overlays": []},
        debug_dir=None,
        packaging_context={"section_choreography": {"sections": []}, "subtitles": {"style": "clean_white"}},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert output_path == tmp_path / "overlay.mp4"
    assert observed["render_plan"] is None
    assert observed["packaging_context"] is None
    assert observed["subtitles_plan"] == {"style": "clean_white"}
    assert observed["avatar_plan"] == {"mode": "full_track_audio_passthrough"}


@pytest.mark.asyncio
async def test_render_video_reuses_passed_subtitles_plan_for_direct_overlay_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
            "fps": 30.0,
        },
    )
    monkeypatch.setattr(
        "roughcut.media.render._probe_duration",
        lambda _source_path: 1.0,
    )
    monkeypatch.setattr(
        "roughcut.media.render._resolve_delivery_frame_rate",
        lambda source_fps, delivery: source_fps or 30.0,
    )
    monkeypatch.setattr(
        "roughcut.media.render._append_delivery_color_filter",
        lambda parts, input_label, _source_info, output_label: input_label,
    )
    monkeypatch.setattr(
        "roughcut.media.render._build_segment_filter_chain",
        lambda *args, **kwargs: ([], "0:v", "0:a"),
    )
    monkeypatch.setattr(
        "roughcut.media.render._build_master_audio_filter_chain",
        lambda **kwargs: "anull[afinal]",
    )
    async def _fake_normalize_rendered_output(*_args, **_kwargs):
        return None

    async def _fake_run_process(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(
        "roughcut.media.render._normalize_rendered_output",
        _fake_normalize_rendered_output,
    )
    monkeypatch.setattr(
        "roughcut.media.render._run_process",
        _fake_run_process,
    )
    monkeypatch.setattr(
        "roughcut.media.render._write_debug_text",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "roughcut.media.render._write_process_debug",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "roughcut.media.render._build_overlay_only_editing_accents",
        lambda _editing_accents, **_kwargs: {},
    )
    monkeypatch.setattr(
        "roughcut.media.render._build_video_transform_editing_accents",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "roughcut.media.render._should_apply_smart_effect_video_transforms",
        lambda _avatar_plan: False,
    )
    async def _fake_detect_video_rotation_decision(_source_path):
        return SimpleNamespace(rotation_cw=0, confidence=1.0, source="test", reason="stub", to_dict=lambda: {})

    monkeypatch.setattr(
        "roughcut.media.rotation.detect_video_rotation_decision",
        _fake_detect_video_rotation_decision,
    )

    observed: dict[str, object] = {}

    async def _fake_build_timed_overlay_filter_chain(**kwargs):
        observed["render_plan"] = kwargs["render_plan"]
        observed["packaging_context"] = kwargs["packaging_context"]
        observed["subtitles_plan"] = kwargs["subtitles_plan"]
        observed["avatar_plan"] = kwargs["avatar_plan"]
        return [], kwargs["video_label"], kwargs["audio_label"]

    monkeypatch.setattr(
        "roughcut.media.render._build_timed_overlay_filter_chain",
        _fake_build_timed_overlay_filter_chain,
    )

    output_path = await render_video(
        source_path=tmp_path / "source.mp4",
        render_plan=None,
        editorial_timeline={},
        output_path=tmp_path / "final.mp4",
        keep_segments=[{"type": "keep", "start": 0.0, "end": 1.0}],
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        packaging_context={
            "assets": {},
            "editing_accents": {},
            "has_packaging_assets": False,
            "section_choreography": {"sections": []},
            "subtitles": {"style": "clean_white"},
        },
        runtime_plan_context={
            "delivery": {"frame_rate_mode": "source"},
            "video_transform": {
                "rotation_manual": False,
                "rotation_cw": 0,
                "aspect_ratio": "source",
                "resolution_mode": "source",
                "resolution_preset": "1080p",
            },
            "avatar_plan": {"mode": "full_track_audio_passthrough"},
            "voice_processing": {},
            "loudness": {},
        },
    )

    assert output_path == tmp_path / "final.mp4"
    assert observed["render_plan"] is None
    assert observed["packaging_context"] is None
    assert observed["subtitles_plan"] == {"style": "clean_white"}
    assert observed["avatar_plan"] == {"mode": "full_track_audio_passthrough"}


@pytest.mark.asyncio
async def test_apply_timed_overlays_reuses_passed_subtitles_plan_and_section_choreography(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._render_packaging_context",
        lambda _render_plan: (_ for _ in ()).throw(AssertionError("should reuse provided subtitles plan and section choreography")),
    )
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {"width": 1920, "height": 1080, "display_width": 1920, "display_height": 1080},
    )
    monkeypatch.setattr("roughcut.media.render._append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)

    observed: dict[str, object] = {}

    def _fake_build_overlay_only_editing_accents(_editing_accents, **kwargs):
        observed["section_choreography"] = kwargs["section_choreography"]
        return {}

    async def _fake_build_timed_overlay_filter_chain(**kwargs):
        observed["subtitles_plan"] = kwargs["subtitles_plan"]
        return [], kwargs["video_label"], kwargs["audio_label"]

    monkeypatch.setattr("roughcut.media.render._build_overlay_only_editing_accents", _fake_build_overlay_only_editing_accents)
    monkeypatch.setattr("roughcut.media.render._build_timed_overlay_filter_chain", _fake_build_timed_overlay_filter_chain)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    output_path = await _apply_timed_overlays_to_video(
        tmp_path / "source.mp4",
        output_path=tmp_path / "overlay.mp4",
        render_plan={"packaging_timeline": {"subtitles": {"style": "should_not_be_read"}}},
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        overlay_editing_accents={"emphasis_overlays": []},
        debug_dir=None,
        subtitles_plan={"style": "clean_white"},
        section_choreography={"sections": []},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert output_path == tmp_path / "overlay.mp4"
    assert observed["subtitles_plan"] == {"style": "clean_white"}
    assert observed["section_choreography"] == {"sections": []}


@pytest.mark.asyncio
async def test_apply_timed_overlays_reuses_passed_choreographed_subtitles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {"width": 1920, "height": 1080, "display_width": 1920, "display_height": 1080},
    )
    monkeypatch.setattr("roughcut.media.render._append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)

    observed: dict[str, object] = {}

    async def _fake_build_timed_overlay_filter_chain(**kwargs):
        observed["choreographed_subtitles"] = kwargs["choreographed_subtitles"]
        return [], kwargs["video_label"], kwargs["audio_label"]

    monkeypatch.setattr("roughcut.media.render._build_timed_overlay_filter_chain", _fake_build_timed_overlay_filter_chain)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    output_path = await _apply_timed_overlays_to_video(
        tmp_path / "source.mp4",
        output_path=tmp_path / "overlay.mp4",
        render_plan={"packaging_timeline": {"subtitles": {"style": "should_not_be_read"}}},
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        choreographed_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "styled"}],
        overlay_editing_accents={"emphasis_overlays": []},
        debug_dir=None,
        packaging_context={"section_choreography": {"sections": []}, "subtitles": {"style": "clean_white"}},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert output_path == tmp_path / "overlay.mp4"
    assert observed["choreographed_subtitles"] == [{"start_time": 0.0, "end_time": 1.0, "text_final": "styled"}]


@pytest.mark.asyncio
async def test_apply_timed_overlays_reuses_passed_overlay_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "roughcut.media.render._build_overlay_only_editing_accents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse provided overlay plan")),
    )
    monkeypatch.setattr(
        "roughcut.media.render._probe_video_stream",
        lambda _source_path: {"width": 1920, "height": 1080, "display_width": 1920, "display_height": 1080},
    )
    monkeypatch.setattr("roughcut.media.render._append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)

    observed: dict[str, object] = {}

    async def _fake_build_timed_overlay_filter_chain(**kwargs):
        observed["overlay_plan"] = kwargs["overlay_plan"]
        return [], kwargs["video_label"], kwargs["audio_label"]

    monkeypatch.setattr("roughcut.media.render._build_timed_overlay_filter_chain", _fake_build_timed_overlay_filter_chain)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    output_path = await _apply_timed_overlays_to_video(
        tmp_path / "source.mp4",
        output_path=tmp_path / "overlay.mp4",
        render_plan={"packaging_timeline": {"subtitles": {"style": "should_not_be_read"}}},
        subtitle_items=[{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        overlay_editing_accents={"emphasis_overlays": []},
        overlay_plan={"emphasis_overlays": [{"text": "kept"}], "sound_effects": []},
        debug_dir=None,
        packaging_context={"section_choreography": {"sections": []}, "subtitles": {"style": "clean_white"}},
        avatar_plan={"mode": "full_track_audio_passthrough"},
    )

    assert output_path == tmp_path / "overlay.mp4"
    assert observed["overlay_plan"] == {"emphasis_overlays": [{"text": "kept"}], "sound_effects": []}


def test_video_transform_accents_can_skip_subtitle_unit_synthesis() -> None:
    accents = _build_video_transform_editing_accents(
        {
            "style": "smart_effect_commercial",
            "emphasis_overlays": [{"text": "kept", "start_time": 0.6, "end_time": 1.0}],
            "sound_effects": [{"start_time": 0.6, "frequency": 920}],
        },
        subtitle_items=[
            {
                "text_final": "new subtitle text",
                "start_time": 1.0,
                "end_time": 1.6,
                "subtitle_unit_role": "lead",
            }
        ],
        synthesize_subtitle_unit_accents=False,
    )

    assert accents["emphasis_overlays"] == [{"text": "kept", "start_time": 0.6, "end_time": 1.45}]
    assert accents["sound_effects"] == [{"start_time": 0.6, "frequency": 920}]


def test_overlay_accents_do_not_synthesize_subtitle_unit_overlays_by_default() -> None:
    accents = _build_overlay_only_editing_accents(
        {"style": "smart_effect_minimal", "emphasis_overlays": [], "sound_effects": []},
        subtitle_items=[
            {
                "text_final": "不要复制成顶部闪字",
                "start_time": 1.0,
                "end_time": 1.6,
                "subtitle_unit_role": "lead",
            }
        ],
    )

    assert accents["emphasis_overlays"] == []
    assert accents["sound_effects"] == []


def test_render_emphasis_overlay_normalization_drops_subtitle_unit_flashes() -> None:
    overlays = _normalize_render_emphasis_overlays(
        [
            {"text": "主字幕复制", "start_time": 1.0, "end_time": 1.2, "source": "subtitle_unit"},
            {"text": "保留重点", "start_time": 2.0, "end_time": 2.2, "source": "manual"},
            {"text": "过近重点", "start_time": 2.5, "end_time": 3.0, "source": "manual"},
        ]
    )

    assert overlays == [{"text": "保留重点", "start_time": 2.0, "end_time": 2.85, "source": "manual"}]


def test_render_emphasis_overlay_normalization_drops_long_sentence_popups() -> None:
    overlays = _normalize_render_emphasis_overlays(
        [
            {
                "text": "也还行因为它不太不算疼嘛呢看啊这个刀",
                "start_time": 1.0,
                "end_time": 2.0,
                "source": "timeline_emphasis_candidate",
            },
            {"text": "快拆结构", "start_time": 4.0, "end_time": 5.0, "source": "timeline_emphasis_candidate"},
        ]
    )

    assert overlays == [
        {"text": "快拆结构", "start_time": 4.0, "end_time": 5.0, "source": "timeline_emphasis_candidate"}
    ]


def test_watermark_plan_defaults_to_dynamic_low_intrusion() -> None:
    plan = _normalize_watermark_plan({"path": "watermark.png", "opacity": 1.4, "scale": 0.5})

    assert plan is not None
    assert plan["dynamic"] is True
    assert plan["motion"] == "dynamic_float"
    assert plan["opacity"] == 0.34
    assert plan["scale"] == 0.12


def test_default_text_watermark_plan_is_available_for_final_render_plans() -> None:
    plan = _default_dynamic_text_watermark_plan({"creative_profile": {"watermark_text": "EDC剪辑台"}})

    assert plan is not None
    assert plan["text"] == "EDC剪辑台"
    assert plan["dynamic"] is True
    assert plan["motion"] == "dynamic_float"


def test_text_watermark_plan_normalization_does_not_require_image_asset() -> None:
    plan = _normalize_watermark_plan({"text": "RoughCut", "opacity": 0.4, "scale": 0.2})

    assert plan is not None
    assert plan["text"] == "RoughCut"
    assert "path" not in plan
    assert plan["dynamic"] is True
    assert plan["scale"] == 0.09


def test_watermark_detection_samples_early_product_showcase_windows() -> None:
    sample_times = _watermark_detection_sample_times(960.0)

    assert 60.0 in sample_times
    assert 120.0 in sample_times
    assert 240.0 in sample_times


@pytest.mark.asyncio
async def test_apply_music_and_watermark_renders_dynamic_watermark(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr("roughcut.media.render._probe_duration", lambda _path: 3.0)

    async def _fake_run_process(cmd, **kwargs):
        observed["cmd"] = list(cmd)
        observed["kwargs"] = dict(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("roughcut.media.render._run_process", _fake_run_process)

    output = await _apply_music_and_watermark(
        tmp_path / "source.mp4",
        music_plan=None,
        watermark_plan={"path": "watermark.png"},
        expected_width=1920,
        expected_height=1080,
        output_path=tmp_path / "out.mp4",
        debug_dir=None,
    )

    cmd_text = " ".join(str(part) for part in observed["cmd"])
    assert output == tmp_path / "out.mp4"
    assert "overlay=x='" in cmd_text
    assert "sin(t*0.11)" in cmd_text
    assert "eval=frame" in cmd_text


@pytest.mark.asyncio
async def test_apply_music_and_watermark_skips_duplicate_existing_image_watermark(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr("roughcut.media.render._probe_duration", lambda _path: 3.0)

    async def _fake_already_contains_watermark(*_args, **_kwargs):
        return True

    async def _fake_run_process(cmd, **kwargs):
        observed["cmd"] = list(cmd)
        observed["kwargs"] = dict(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("roughcut.media.render._source_already_contains_image_watermark", _fake_already_contains_watermark)
    monkeypatch.setattr("roughcut.media.render._run_process", _fake_run_process)

    output = await _apply_music_and_watermark(
        tmp_path / "source.mp4",
        music_plan={"path": str(tmp_path / "music.mp3"), "volume": 0.12},
        watermark_plan={"path": "watermark.png"},
        expected_width=1920,
        expected_height=1080,
        output_path=tmp_path / "out.mp4",
        debug_dir=None,
    )

    cmd_text = " ".join(str(part) for part in observed["cmd"])
    assert output == tmp_path / "out.mp4"
    assert "watermark.png" not in cmd_text
    assert "overlay=x='" not in cmd_text
    assert "sidechaincompress" in cmd_text


@pytest.mark.asyncio
async def test_apply_music_and_watermark_renders_dynamic_text_watermark(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr("roughcut.media.render._probe_duration", lambda _path: 3.0)

    async def _fake_run_process(cmd, **kwargs):
        observed["cmd"] = list(cmd)
        observed["kwargs"] = dict(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("roughcut.media.render._run_process", _fake_run_process)

    output = await _apply_music_and_watermark(
        tmp_path / "source.mp4",
        music_plan=None,
        watermark_plan={"text": "RoughCut"},
        expected_width=1920,
        expected_height=1080,
        output_path=tmp_path / "out.mp4",
        debug_dir=None,
    )

    cmd_text = " ".join(str(part) for part in observed["cmd"])
    assert output == tmp_path / "out.mp4"
    assert "drawtext=" in cmd_text
    assert "RoughCut" in cmd_text
    assert "sin(t*0.11)" in cmd_text


@pytest.mark.asyncio
async def test_apply_packaging_plan_adds_default_dynamic_text_watermark_for_render_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setattr("roughcut.media.render._stage_packaging_source", lambda source_path, _tmp: source_path)
    monkeypatch.setattr("roughcut.media.render._finalize_output_file", lambda _src, _dst: None)

    async def _fake_apply_music_and_watermark(source_path, **kwargs):
        calls.append({"source_path": source_path, **kwargs})
        return kwargs["output_path"]

    monkeypatch.setattr("roughcut.media.render._apply_music_and_watermark", _fake_apply_music_and_watermark)

    output = await _apply_packaging_plan(
        tmp_path / "source.mp4",
        render_plan={"creative_profile": {"watermark_text": "EDC剪辑台"}},
        output_path=tmp_path / "final.mp4",
        expected_width=1920,
        expected_height=1080,
        debug_dir=None,
        target_fps=30.0,
        packaging_assets={},
    )

    assert output == tmp_path / "final.mp4"
    assert calls[0]["watermark_plan"] == {
        "text": "EDC剪辑台",
        "opacity": 0.5,
        "scale": 0.052,
        "position": "top_right",
        "motion": "dynamic_float",
        "dynamic": True,
        "source": "default_text_watermark",
    }

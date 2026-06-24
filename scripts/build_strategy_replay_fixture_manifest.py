from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output" / "test" / "strategy-replay-fixtures"
DEFAULT_MANIFEST_NAME = "strategy-replay-fixtures.v1.json"
STRATEGY_REPLAY_FIXTURE_SCHEMA = "strategy_replay_fixtures.v1"
STRATEGY_CONTENT_REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "information_density": (),
    "step_demonstration": (),
    "experience_and_mood": (),
    "event_highlight": (),
    "narrative_assembly": (
        "strategy_review_preview_evidence",
        "strategy_review_preview_media_evidence",
    ),
}
STRATEGY_RENDER_REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "information_density": (),
    "step_demonstration": (),
    "experience_and_mood": (),
    "event_highlight": ("strategy_boundary_samples",),
    "narrative_assembly": (),
}


@dataclass(frozen=True, slots=True)
class FixtureMediaSpec:
    fixture_id: str
    path: Path
    color: str
    tone_hz: int
    duration_seconds: float = 3.0


def strategy_replay_fixture_media_specs(output_dir: Path) -> list[FixtureMediaSpec]:
    media_dir = output_dir.resolve() / "media"
    return [
        FixtureMediaSpec(
            fixture_id="information_commentary_main",
            path=media_dir / "information_density_talking_head_commentary.mp4",
            color="0x4b5563",
            tone_hz=360,
        ),
        FixtureMediaSpec(
            fixture_id="step_tutorial_screen",
            path=media_dir / "step_demonstration_screen_tutorial.mp4",
            color="0x6d28d9",
            tone_hz=580,
        ),
        FixtureMediaSpec(
            fixture_id="experience_vlog_main",
            path=media_dir / "experience_mood_travel_market_vlog.mp4",
            color="0x2f80ed",
            tone_hz=440,
        ),
        FixtureMediaSpec(
            fixture_id="event_highlight_gameplay",
            path=media_dir / "event_highlight_gameplay_action_peak.mp4",
            color="0xdc2626",
            tone_hz=920,
        ),
        FixtureMediaSpec(
            fixture_id="narrative_anchor",
            path=media_dir / "narrative_anchor_avatar_commentary.mp4",
            color="0x3a3d46",
            tone_hz=520,
        ),
        FixtureMediaSpec(
            fixture_id="narrative_detail",
            path=media_dir / "narrative_detail_insert_material.mp4",
            color="0xe0a21a",
            tone_hz=660,
        ),
        FixtureMediaSpec(
            fixture_id="narrative_broll",
            path=media_dir / "narrative_broll_storybeat.mp4",
            color="0x2a9d8f",
            tone_hz=780,
        ),
    ]


def _media_spec_map(output_dir: Path) -> dict[str, FixtureMediaSpec]:
    return {spec.fixture_id: spec for spec in strategy_replay_fixture_media_specs(output_dir)}


def strategy_required_checks(strategy_type: str, *, include_render_required_checks: bool = False) -> list[str]:
    normalized_strategy = str(strategy_type or "").strip()
    checks = ["strategy_pipeline_coverage"]
    checks.extend(STRATEGY_CONTENT_REQUIRED_CHECKS.get(normalized_strategy, ()))
    if include_render_required_checks:
        checks.extend(STRATEGY_RENDER_REQUIRED_CHECKS.get(normalized_strategy, ()))
    return checks


def build_strategy_replay_fixture_manifest(
    output_dir: Path,
    *,
    include_render_required_checks: bool = False,
) -> dict[str, Any]:
    specs = _media_spec_map(output_dir)
    information_path = specs["information_commentary_main"].path.resolve()
    step_path = specs["step_tutorial_screen"].path.resolve()
    experience_path = specs["experience_vlog_main"].path.resolve()
    event_path = specs["event_highlight_gameplay"].path.resolve()
    narrative_paths = [
        specs["narrative_anchor"].path.resolve(),
        specs["narrative_detail"].path.resolve(),
        specs["narrative_broll"].path.resolve(),
    ]

    return {
        "schema": STRATEGY_REPLAY_FIXTURE_SCHEMA,
        "description": "Replay-safe generated fixtures for strategy pipeline coverage.",
        "jobs": [
            {
                "case_id": "strategy_information_density_generated_commentary",
                "scenario": "Generated talking-head commentary fixture.",
                "source_path": str(information_path),
                "workflow_template": "commentary_focus",
                "language": "zh-CN",
                "product_controls": {
                    "edit_mode": "talking_head",
                    "automation_level": "standard",
                    "material_usage": "main_only",
                },
                "strategy_classification": {
                    "schema": "strategy_classification.v1",
                    "primary_type": "talking_head",
                    "production_mode": "source_cut",
                    "content_tags": ["talking_head", "commentary"],
                    "media_tags": ["single_speaker", "speech_dominant"],
                    "editing_signals": ["retake_likely", "silence_trim_useful", "subtitle_important"],
                    "asset_tags": [],
                    "confidence": 0.94,
                },
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                    "fixture_media_id": "information_commentary_main",
                    "video_description": "Talking-head commentary with dense speech cleanup needs.",
                    "manual_video_summary": "Information density fixture for speech cleanup and subtitle timeline coverage.",
                },
                "transcript_segments": [
                    {
                        "start": 0.0,
                        "end": 2.8,
                        "text": "This commentary explains the main point, removes repeated phrasing, and keeps subtitle timing clear.",
                    }
                ],
                "tags": [
                    "strategy:information_density",
                    "strategy_fixture",
                    "generated_fixture",
                    "replay_safe",
                ],
                "required_checks": strategy_required_checks(
                    "information_density",
                    include_render_required_checks=include_render_required_checks,
                ),
                "risk_hints": {"expected_strategy_type": "information_density"},
            },
            {
                "case_id": "strategy_step_demonstration_generated_tutorial",
                "scenario": "Generated screen tutorial fixture.",
                "source_path": str(step_path),
                "workflow_template": "tutorial_standard",
                "language": "zh-CN",
                "product_controls": {
                    "edit_mode": "tutorial",
                    "automation_level": "standard",
                    "material_usage": "main_only",
                },
                "strategy_classification": {
                    "schema": "strategy_classification.v1",
                    "primary_type": "tutorial",
                    "production_mode": "source_cut",
                    "content_tags": ["tutorial"],
                    "media_tags": ["screen_recording", "operation_demo"],
                    "editing_signals": ["step_by_step", "workflow_breakdown", "subtitle_important"],
                    "asset_tags": [],
                    "confidence": 0.93,
                },
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                    "fixture_media_id": "step_tutorial_screen",
                    "video_description": "Screen-recording tutorial with ordered operation steps.",
                    "manual_video_summary": "Step demonstration fixture for tutorial focus and chapter packaging coverage.",
                },
                "transcript_segments": [
                    {
                        "start": 0.0,
                        "end": 2.8,
                        "text": "Step one opens the timeline, step two selects the clip, and step three exports the tutorial result.",
                    }
                ],
                "tags": [
                    "strategy:step_demonstration",
                    "strategy_fixture",
                    "generated_fixture",
                    "replay_safe",
                ],
                "required_checks": strategy_required_checks(
                    "step_demonstration",
                    include_render_required_checks=include_render_required_checks,
                ),
                "risk_hints": {"expected_strategy_type": "step_demonstration"},
            },
            {
                "case_id": "strategy_experience_and_mood_generated_vlog",
                "scenario": "Generated travel and mood vlog fixture.",
                "source_path": str(experience_path),
                "workflow_template": "vlog_daily",
                "language": "zh-CN",
                "product_controls": {
                    "edit_mode": "vlog",
                    "automation_level": "standard",
                    "material_usage": "main_only",
                },
                "strategy_classification": {
                    "schema": "strategy_classification.v1",
                    "primary_type": "vlog",
                    "production_mode": "source_cut",
                    "content_tags": ["vlog", "travel", "experience"],
                    "media_tags": ["mood", "ambient_broll"],
                    "editing_signals": ["subtitle_important"],
                    "asset_tags": [],
                    "confidence": 0.92,
                },
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                    "fixture_media_id": "experience_vlog_main",
                    "video_description": "Travel market vlog with mood beats and light narration.",
                    "manual_video_summary": "Experience and mood fixture for preserving ambience while trimming lightly.",
                },
                "transcript_segments": [
                    {
                        "start": 0.0,
                        "end": 2.8,
                        "text": "Today I walk through the market, keep the travel mood, and preserve the small ambient moments.",
                    }
                ],
                "tags": [
                    "strategy:experience_and_mood",
                    "strategy_fixture",
                    "generated_fixture",
                    "replay_safe",
                ],
                "required_checks": strategy_required_checks(
                    "experience_and_mood",
                    include_render_required_checks=include_render_required_checks,
                ),
                "risk_hints": {"expected_strategy_type": "experience_and_mood"},
            },
            {
                "case_id": "strategy_event_highlight_generated_gameplay",
                "scenario": "Generated gameplay action-peak highlight fixture.",
                "source_path": str(event_path),
                "workflow_template": "gameplay_highlight",
                "language": "zh-CN",
                "product_controls": {
                    "edit_mode": "highlight",
                    "automation_level": "standard",
                    "material_usage": "main_only",
                },
                "strategy_classification": {
                    "schema": "strategy_classification.v1",
                    "primary_type": "gameplay",
                    "production_mode": "source_cut",
                    "content_tags": ["gameplay", "highlight", "event_highlight"],
                    "media_tags": ["match", "action_peak"],
                    "editing_signals": ["high_energy"],
                    "asset_tags": [],
                    "confidence": 0.91,
                },
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                    "fixture_media_id": "event_highlight_gameplay",
                    "video_description": "Gameplay highlight with action peak and high-energy moments.",
                    "manual_video_summary": "Event highlight fixture for preserving action windows and checking highlight strategy evidence.",
                },
                "transcript_segments": [
                    {
                        "start": 0.0,
                        "end": 1.25,
                        "text": "The match reaches an action peak here.",
                    },
                    {
                        "start": 1.25,
                        "end": 2.45,
                        "text": "The edit should protect the highlight window.",
                    }
                ],
                "tags": [
                    "strategy:event_highlight",
                    "strategy_fixture",
                    "generated_fixture",
                    "replay_safe",
                ],
                "required_checks": strategy_required_checks(
                    "event_highlight",
                    include_render_required_checks=include_render_required_checks,
                ),
                "risk_hints": {"expected_strategy_type": "event_highlight"},
            },
            {
                "case_id": "strategy_narrative_assembly_generated_multimaterial",
                "scenario": "Generated multi-material narrative assembly fixture.",
                "source_paths": [str(path) for path in narrative_paths],
                "workflow_template": "commentary_focus",
                "language": "zh-CN",
                "product_controls": {
                    "edit_mode": "multi_material",
                    "automation_level": "standard",
                    "material_usage": "all_uploaded",
                },
                "strategy_classification": {
                    "schema": "strategy_classification.v1",
                    "primary_type": "avatar_commentary_remix",
                    "production_mode": "remix",
                    "content_tags": ["commentary", "remix"],
                    "media_tags": ["script_driven", "digital_human", "multi_material"],
                    "editing_signals": ["material_insert_required", "storyboard_required"],
                    "asset_tags": ["multi_material_ready", "visual_inserts_available"],
                    "confidence": 0.93,
                },
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                    "fixture_media_id": "narrative_multimaterial",
                    "video_description": "Script-driven commentary with anchor, detail insert, and broll material.",
                    "manual_video_summary": "Narrative assembly fixture that requires material insert planning and storyboard review.",
                },
                "transcript_segments": [
                    {
                        "start": 0.0,
                        "end": 2.8,
                        "text": "The anchor narration introduces the story, then detail material and b roll support the scripted assembly.",
                    }
                ],
                "tags": [
                    "strategy:narrative_assembly",
                    "strategy_fixture",
                    "generated_fixture",
                    "replay_safe",
                ],
                "required_checks": strategy_required_checks(
                    "narrative_assembly",
                    include_render_required_checks=include_render_required_checks,
                ),
                "risk_hints": {"expected_strategy_type": "narrative_assembly"},
            },
        ],
    }


def _ffmpeg_command(ffmpeg_bin: str, spec: FixtureMediaSpec) -> list[str]:
    duration = f"{spec.duration_seconds:.3f}"
    return [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={spec.color}:s=1280x720:r=30:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={spec.tone_hz}:sample_rate=48000:duration={duration}",
        "-t",
        duration,
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(spec.path),
    ]


def generate_strategy_replay_fixture_media(
    output_dir: Path,
    *,
    force: bool = False,
    ffmpeg_bin: str | None = None,
) -> list[Path]:
    resolved_ffmpeg = ffmpeg_bin or shutil.which("ffmpeg")
    if not resolved_ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH; rerun with --manifest-only to inspect the manifest")

    generated: list[Path] = []
    for spec in strategy_replay_fixture_media_specs(output_dir):
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        if spec.path.exists() and spec.path.stat().st_size > 0 and not force:
            continue
        if spec.path.exists():
            spec.path.unlink()
        cmd = _ffmpeg_command(resolved_ffmpeg, spec)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not spec.path.exists() or spec.path.stat().st_size <= 0:
            stderr = str(result.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed for {spec.fixture_id}: {stderr[-500:]}")
        generated.append(spec.path)
    return generated


def write_strategy_replay_fixture_manifest(
    output_dir: Path,
    *,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    force_media: bool = False,
    generate_media: bool = True,
    include_render_required_checks: bool = False,
) -> Path:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if generate_media:
        generate_strategy_replay_fixture_media(output_dir, force=force_media)
    payload = build_strategy_replay_fixture_manifest(
        output_dir,
        include_render_required_checks=include_render_required_checks,
    )
    manifest_path = output_dir / manifest_name
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build replay-safe generated strategy fixture media and golden manifest."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated media and manifest.",
    )
    parser.add_argument(
        "--manifest-name",
        default=DEFAULT_MANIFEST_NAME,
        help="Manifest filename inside output-dir.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate media even when existing files are present.",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Write the manifest without generating media.",
    )
    parser.add_argument(
        "--include-render-required-checks",
        action="store_true",
        help="Add render-stage required checks for fixtures that have strategy render evidence contracts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest_path = write_strategy_replay_fixture_manifest(
            args.output_dir,
            manifest_name=args.manifest_name,
            force_media=bool(args.force),
            generate_media=not bool(args.manifest_only),
            include_render_required_checks=bool(args.include_render_required_checks),
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "manifest_path": str(manifest_path),
                "media_dir": str(args.output_dir.resolve() / "media"),
                "job_count": len(
                    build_strategy_replay_fixture_manifest(
                        args.output_dir,
                        include_render_required_checks=bool(args.include_render_required_checks),
                    )["jobs"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

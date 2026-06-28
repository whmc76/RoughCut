from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roughcut.remix import alignment as remix_alignment  # noqa: E402
from roughcut.remix import batch_report as remix_batch_report  # noqa: E402
from roughcut.remix import caption_packager as remix_caption_packager  # noqa: E402
from roughcut.remix import edit_plan as remix_edit_plan  # noqa: E402
from roughcut.remix import qa as remix_qa  # noqa: E402
from roughcut.remix import review_frames as remix_review_frames  # noqa: E402
from roughcut.remix import scene_index as remix_scene_index  # noqa: E402
from roughcut.remix import script_topics as remix_script_topics  # noqa: E402
from roughcut.remix import source_selection as remix_source_selection  # noqa: E402
from roughcut.remix.creator_profile import (  # noqa: E402
    creator_caption_style_defaults,
    creator_display_name,
    creator_profile_id,
    creator_tts_defaults,
    load_creator_profile,
)
from roughcut.remix.contracts import AsrToken as RemixAsrToken  # noqa: E402
from roughcut.remix.contracts import SceneSpan  # noqa: E402
from roughcut.remix.contracts import SourceAnchor  # noqa: E402
from roughcut.remix.contracts import SubtitleTiming as RemixSubtitleTiming  # noqa: E402
from roughcut.llm_cache import build_cache_key, load_cached_json, save_cached_json  # noqa: E402
from roughcut.providers.factory import get_reasoning_provider  # noqa: E402
from roughcut.providers.reasoning.base import Message  # noqa: E402

DEFAULT_API_BASE = "http://127.0.0.1:38471"
DEFAULT_QWEN3_ASR_BASE = "http://127.0.0.1:30230"
DEFAULT_TTS_PROMPT_TEXT = "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。"
DEFAULT_CREATOR_PROFILE = ""
DEFAULT_PRODUCTION_MANIFEST = ROOT / "data" / "remix_production_tasks" / "example_remix_pending.json"
REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080
REFERENCE_FPS = 28
REFERENCE_WATERMARK = "Demo Parenting"
REMIX_SEGMENT_X264_PRESET = "medium"
REMIX_SEGMENT_X264_CRF = "14"
REMIX_FINAL_X264_PRESET = "medium"
REMIX_FINAL_X264_CRF = "15"
REMIX_X264_TUNE = "animation"
NARRATION_SAMPLE_RATE = 24000
MAX_INTERNAL_BREATH_SEC = 0.22
MAX_EDGE_SILENCE_SEC = 0.08
VOICE_FRAME_SEC = 0.02
ORIGINAL_AUDIO_INTENT_SCHEMA = "roughcut.remix.original_audio_reference_intent.v1"
ORIGINAL_AUDIO_INTENT_POLICY_VERSION = "scene_evidence_bridge_v3"
ORIGINAL_AUDIO_INTENT_CONFIDENCE_GATE = 0.78
ORIGINAL_AUDIO_INTENT_MAX_REQUESTS = 5
ORIGINAL_AUDIO_BRIDGE_MIN_DURATION_SEC = 6.0
ORIGINAL_AUDIO_BRIDGE_MAX_DURATION_SEC = 12.0
ORIGINAL_AUDIO_BRIDGE_PREROLL_SEC = 0.6
ORIGINAL_AUDIO_BRIDGE_POSTROLL_SEC = 2.0
ORIGINAL_AUDIO_BRIDGE_REFINED_MAX_DURATION_SEC = 16.0
ORIGINAL_AUDIO_SOURCE_MAPPING_SCHEMA = "roughcut.remix.original_audio_source_mapping.v1"
ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION = "source_asr_llm_mapping_v1"
ORIGINAL_AUDIO_SOURCE_MAPPING_CONFIDENCE_GATE = 0.6
SEMANTIC_CAPTION_PACKAGING_SCHEMA = "roughcut.remix.semantic_caption_packaging.v1"
SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION = "llm_script_packaging_v1"
TTS_REQUEST_SCHEMA = "roughcut.remix.tts_request.v1"


@dataclass
class EpisodeScript:
    episode: int
    title: str
    question: str
    body: str
    script_path: str


@dataclass
class SampleReport:
    episode: int
    title: str
    source_video: str
    script_path: str
    creator_profile_id: str
    creator_profile_name: str
    creator_profile_path: str | None
    output_path: str
    narration_path: str
    render_narration_path: str
    tts_request_metadata_path: str | None
    tts_provider: str
    tts_mode: str
    tts_reference_history_path: str
    tts_prompt_text: str
    tts_voice_signature: str
    subtitle_path: str
    caption_package_path: str
    semantic_packaging_plan_path: str | None
    topic_plan_path: str
    edit_plan_path: str
    qa_report_path: str
    review_frames_manifest_path: str
    cover_path: str | None
    scene_index_path: str
    source_duration_sec: float
    narration_duration_sec: float
    render_narration_duration_sec: float
    output_duration_sec: float
    script_chars: int
    clip_count: int
    clip_duration_sec: float
    narration_rms_dbfs: float | None
    silence_trimmed_sec: float
    tts_segment_count: int
    original_audio_intent_analysis_path: str | None
    original_audio_intent_source: str
    original_audio_intent_decision: str
    original_audio_intent_confidence: float | None
    original_audio_intent_llm_reviewed: bool
    original_audio_source_mapping_path: str | None
    original_audio_source_mapping_source: str
    original_audio_source_mapping_llm_reviewed: bool
    original_audio_reference_intent_count: int
    original_audio_insert_count: int
    original_audio_insert_total_duration_sec: float
    original_audio_insertions_path: str | None
    original_audio_visual_bridge_count: int
    subtitle_alignment_source: str
    subtitle_event_count: int
    subtitle_text_coverage: float
    subtitle_style_profile: str
    packaging_framework: str
    hyperframes_enabled: bool
    hyperframes_plan_schema: str
    hyperframes_track_count: int
    hyperframes_element_count: int
    hyperframes_effect_count: int
    semantic_packaging_source: str
    semantic_packaging_llm_reviewed: bool
    max_subtitle_lines_per_event: int
    max_subtitle_line_chars: int
    subtitle_timing_alignment_status: str
    subtitle_timing_unmatched_count: int
    subtitle_timing_bad_drift_count: int
    subtitle_timing_max_abs_start_drift_sec: float | None
    subtitle_timing_max_abs_end_drift_sec: float | None
    subtitle_timing_audit_path: str | None
    tts_asr_status: str
    tts_asr_coverage: float | None
    tts_asr_token_count: int
    tts_asr_evidence_path: str | None
    source_asr_status: str
    source_asr_anchor_count: int
    source_asr_selected_starts: list[float]
    source_asr_index_path: str | None
    scene_index_status: str
    scene_count: int
    packaging_event_count: int
    theme_banner_count: int
    keyword_sticker_count: int
    watermark_event_count: int
    emphasis_keyword_count: int
    animated_subtitle_event_count: int
    animated_packaging_event_count: int
    motion_effect_count: int
    highlight_effect_count: int
    packaging_audio_cue_count: int
    source_bridge_count: int
    review_frame_count: int
    qa_status: str
    qa_issue_count: int
    tts_status: str
    build_status: str
    notes: list[str]


@dataclass
class SilenceTrimStats:
    original_duration_sec: float
    output_duration_sec: float
    trimmed_sec: float
    voice_segment_count: int
    max_removed_gap_sec: float


@dataclass
class TtsSegmentTiming:
    index: int
    text: str
    start_sec: float
    end_sec: float
    raw_duration_sec: float
    render_duration_sec: float


@dataclass
class AsrToken:
    text: str
    start_sec: float
    end_sec: float


@dataclass
class AsrEvidence:
    status: str
    purpose: str
    provider: str
    model: str
    text: str
    duration_sec: float
    token_count: int
    normalized_char_count: int
    canonical_coverage: float | None
    evidence_path: str | None
    error: str | None = None


@dataclass
class SourceAsrIndex:
    status: str
    evidence_path: str | None
    anchor_count: int
    selected_starts: list[float]
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build script-driven source-footage remix sample videos.")
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--episodes", default="1", help="Comma separated second-season episode numbers.")
    parser.add_argument(
        "--production-manifest",
        type=Path,
        default=None,
        help="Optional formal production task manifest. When set, pending tasks from the manifest define the episode order.",
    )
    parser.add_argument(
        "--task-status",
        choices=["pending", "blocked_missing_script", "done", "all"],
        default="pending",
        help="Task status to read from --production-manifest.",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "script-footage-remix-samples")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--creator-profile", default=DEFAULT_CREATOR_PROFILE, help="Creator profile slug bound to this remix task.")
    parser.add_argument("--creator-profile-path", type=Path, default=None, help="Explicit creator profile JSON path.")
    parser.add_argument("--subtitle-style-profile", default="", help="Optional caption style profile; creator profile supplies the default when omitted.")
    parser.add_argument("--tts-provider", choices=["moss_tts_local", "cosyvoice3"], default="moss_tts_local")
    parser.add_argument(
        "--tts-mode",
        default="",
        help="Override TTS mode. Defaults to voice clone only when a reference voice exists; otherwise uses no-reference TTS.",
    )
    parser.add_argument("--reference-history-path", default="", help="Reference audio history path for voice clone modes.")
    parser.add_argument("--prompt-text", default=DEFAULT_TTS_PROMPT_TEXT, help="Prompt text matching the reference audio.")
    parser.add_argument("--skip-tts", action="store_true", help="Smoke-test only: use silent placeholder narration instead of TTS.")
    parser.add_argument("--max-script-chars", type=int, default=0, help="Deprecated: script truncation is blocked for final remix builds.")
    parser.add_argument("--tts-target-duration-sec", type=float, default=148.0, help="Target TTS duration only when --condense-script is explicitly enabled.")
    parser.add_argument("--final-target-duration-sec", type=float, default=0.0, help="Optional explicit audio tempo-fit target. Default keeps the full narrated script duration.")
    parser.add_argument("--chars-per-sec", type=float, default=3.8, help="Estimated Chinese narration characters per second for explicit script condensation.")
    parser.add_argument("--condense-script", action="store_true", help="Explicit experimental mode: condense the script before TTS. Disabled by default.")
    parser.add_argument("--no-condense", action="store_true", help="Deprecated compatibility flag; full script is already the default.")
    parser.add_argument("--force", action="store_true", help="Rebuild existing TTS and sample outputs.")
    parser.add_argument("--force-tts", action="store_true", help="Regenerate TTS even when cached narration exists.")
    parser.add_argument("--tts-timeout-sec", type=float, default=300.0, help="Maximum time to wait for one TTS API run.")
    parser.add_argument("--tts-poll-sec", type=float, default=3.0, help="Polling interval for TTS API runs.")
    parser.add_argument("--qwen3-asr-base", default=DEFAULT_QWEN3_ASR_BASE, help="Qwen3-ASR + ForcedAligner HTTP base URL.")
    parser.add_argument("--asr-timeout-sec", type=float, default=1800.0)
    parser.add_argument("--asr-chunk-sec", type=float, default=65.0, help="Chunk long narration before Qwen3 ASR alignment.")
    parser.add_argument("--min-tts-asr-coverage", type=float, default=0.78, help="Minimum canonical script coverage for TTS-ASR subtitle timing.")
    parser.add_argument("--skip-tts-asr-align", action="store_true", help="Fallback mode only: do not use Qwen3 ASR for TTS subtitle alignment.")
    parser.add_argument("--skip-source-asr-index", action="store_true", help="Fallback mode only: do not ASR source-video anchors for clip positioning evidence.")
    parser.add_argument("--source-asr-window-sec", type=float, default=18.0)
    parser.add_argument("--source-asr-candidate-count", type=int, default=14)
    parser.add_argument("--min-source-asr-anchors", type=int, default=3)
    parser.add_argument("--scene-threshold", type=float, default=30.0)
    parser.add_argument("--scene-frame-skip", type=int, default=2)
    parser.add_argument("--scene-detect-timeout-sec", type=float, default=90.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    apply_production_manifest_defaults(args)
    apply_creator_profile_defaults(args)
    args.source_root = resolve_source_root(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    episodes = resolve_requested_episodes(args)
    all_scripts = load_episode_scripts(args.source_root)
    reports: list[SampleReport] = []

    for episode in episodes:
        if episode not in all_scripts:
            raise SystemExit(f"Missing script for S02E{episode:02d}")
        script = all_scripts[episode]
        video = find_episode_video(args.source_root, episode)
        if video is None:
            raise SystemExit(f"Missing source video for S02E{episode:02d}")
        reports.append(build_episode_sample(script, video, args))

    report_payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(args.source_root),
        "api_base": str(args.api_base),
        "creator_profile": {
            "id": creator_profile_id(getattr(args, "creator_profile_payload", None)),
            "name": creator_display_name(getattr(args, "creator_profile_payload", None)),
            "path": str(getattr(args, "creator_profile_resolved_path", "") or "") or None,
        },
        "episodes": episodes,
        "reports": [asdict(item) for item in reports],
        "summary": {
            "sample_count": len(reports),
            "success_count": sum(1 for item in reports if item.build_status == "done"),
            "total_output_duration_sec": round(sum(item.output_duration_sec for item in reports), 3),
        },
    }
    batch_payload = remix_batch_report.build_batch_report_payload(
        report_payload["reports"],
        source_root=str(args.source_root),
        episodes=episodes,
        verify_file_exists=True,
    )
    (args.output_dir / "script_footage_remix_sample_report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "script_footage_remix_sample_report.md").write_text(
        render_markdown_report(report_payload),
        encoding="utf-8",
    )
    (args.output_dir / "batch_report.json").write_text(json.dumps(batch_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "batch_report.md").write_text(
        remix_batch_report.render_batch_report_markdown(batch_payload),
        encoding="utf-8",
    )
    (args.output_dir / "methodology_report.md").write_text(
        remix_batch_report.render_methodology_report_markdown(),
        encoding="utf-8",
    )
    print(json.dumps(report_payload["summary"], ensure_ascii=False, indent=2))


def load_production_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Production manifest must be a JSON object: {path}")
    return payload


def apply_production_manifest_defaults(args: argparse.Namespace) -> None:
    manifest_path = getattr(args, "production_manifest", None)
    if not manifest_path:
        return
    payload = load_production_manifest(Path(manifest_path))
    setattr(args, "production_manifest_payload", payload)
    if not str(getattr(args, "creator_profile", "") or "").strip():
        args.creator_profile = str(payload.get("creator_profile") or "").strip()


def resolve_source_root(args: argparse.Namespace) -> Path:
    source_root = getattr(args, "source_root", None)
    if source_root:
        return Path(source_root)
    manifest_path = getattr(args, "production_manifest", None)
    if manifest_path:
        payload = getattr(args, "production_manifest_payload", None)
        if not isinstance(payload, dict):
            payload = load_production_manifest(Path(manifest_path))
        manifest_source_root = str(payload.get("source_root") or "").strip()
        if manifest_source_root:
            return Path(manifest_source_root)
    raise SystemExit("--source-root is required unless --production-manifest contains source_root")


def resolve_requested_episodes(args: argparse.Namespace) -> list[int]:
    manifest_path = getattr(args, "production_manifest", None)
    if manifest_path:
        return load_production_manifest_episodes(Path(manifest_path), status=str(getattr(args, "task_status", "pending") or "pending"))
    return [int(item.strip()) for item in str(args.episodes).split(",") if item.strip()]


def load_production_manifest_episodes(path: Path, *, status: str = "pending") -> list[int]:
    payload = load_production_manifest(path)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"Production manifest missing tasks array: {path}")
    selected: list[int] = []
    wanted_status = str(status or "pending").strip()
    for item in tasks:
        if not isinstance(item, dict):
            continue
        item_status = str(item.get("status") or "").strip()
        if wanted_status != "all" and item_status != wanted_status:
            continue
        season = int(item.get("season") or 0)
        if season != 2:
            continue
        episode = int(item.get("episode") or 0)
        if episode <= 0:
            continue
        selected.append(episode)
    if not selected:
        raise ValueError(f"Production manifest has no {wanted_status} S02 tasks: {path}")
    return selected


def load_episode_scripts(source_root: Path) -> dict[int, EpisodeScript]:
    scripts: dict[int, EpisodeScript] = {}
    script_paths = {
        *source_root.glob("示例动画第二季新风格育儿文案_第*.md"),
        *source_root.glob("*第二季*文案_第*.md"),
    }
    for path in sorted(script_paths):
        text = path.read_text(encoding="utf-8")
        matches = list(re.finditer(r"^##\s*第(\d+)集《([^》]+)》\s*$", text, flags=re.M))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[start:end].strip()
            question_match = re.search(r"\*\*([^*]+)\*\*", block)
            question = question_match.group(1).strip() if question_match else ""
            body = re.sub(r"\*\*([^*]+)\*\*", r"\1", block).strip()
            body = normalize_script_body(body)
            episode = int(match.group(1))
            scripts[episode] = EpisodeScript(
                episode=episode,
                title=match.group(2).strip(),
                question=question,
                body=body,
                script_path=str(path),
            )
    return scripts


def normalize_script_body(text: str) -> str:
    return remix_script_topics.normalize_script_body(text)


def resolve_tts_provider(provider: str | None) -> str:
    return str(provider or "moss_tts_local").strip() or "moss_tts_local"


def resolve_tts_mode(provider: str | None, mode: str | None, reference_history_path: str | None = None) -> str:
    resolved_provider = resolve_tts_provider(provider)
    resolved_mode = str(mode or "").strip()
    if resolved_mode:
        return resolved_mode
    has_reference_voice = bool(str(reference_history_path or "").strip())
    if resolved_provider == "moss_tts_local":
        return "moss_voice_clone" if has_reference_voice else "moss_direct_tts"
    return "zero_shot" if has_reference_voice else "sft"


def build_tts_request_metadata(
    text: str,
    *,
    provider: str | None,
    mode: str | None,
    reference_history_path: str | None,
    prompt_text: str | None,
) -> dict[str, Any]:
    normalized_text = normalize_text_for_match(text)
    request = {
        "schema": TTS_REQUEST_SCHEMA,
        "provider": resolve_tts_provider(provider),
        "mode": resolve_tts_mode(provider, mode, reference_history_path),
        "reference_history_path": str(reference_history_path or "").strip(),
        "prompt_text": str(prompt_text or ""),
        "text_sha256": hashlib.sha256(str(text or "").encode("utf-8")).hexdigest(),
        "normalized_text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        "normalized_text_chars": len(normalized_text),
    }
    voice_identity = {
        key: request[key]
        for key in ("provider", "mode", "reference_history_path", "prompt_text", "normalized_text_sha256")
    }
    request["voice_signature"] = hashlib.sha256(
        json.dumps(voice_identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return request


def tts_request_matches(expected: dict[str, Any], actual: dict[str, Any] | None) -> bool:
    if not isinstance(actual, dict):
        return False
    for key in (
        "schema",
        "provider",
        "mode",
        "reference_history_path",
        "prompt_text",
        "normalized_text_sha256",
        "voice_signature",
    ):
        if str(actual.get(key) or "") != str(expected.get(key) or ""):
            return False
    return True


def load_matching_tts_request_metadata(path: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    return payload if tts_request_matches(expected, request) else None


def write_tts_request_metadata(
    path: Path,
    *,
    request: dict[str, Any],
    status: str,
    narration_path: Path,
    source: str,
    run_metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "schema": TTS_REQUEST_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source": source,
        "narration_path": str(narration_path),
        "request": request,
    }
    if run_metadata is not None:
        payload["run_metadata"] = run_metadata
        payload["run_voice_evidence"] = extract_tts_run_voice_evidence(run_metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_creator_profile_defaults(args: argparse.Namespace) -> dict[str, Any] | None:
    profile = load_creator_profile(
        repo_root=ROOT,
        slug=str(getattr(args, "creator_profile", "") or "").strip(),
        profile_path=getattr(args, "creator_profile_path", None),
    )
    setattr(args, "creator_profile_payload", profile)
    if profile is None:
        setattr(args, "creator_profile_resolved_path", None)
        return None
    profile_path = getattr(args, "creator_profile_path", None)
    if profile_path is None:
        profile_path = ROOT / "data" / "creator_profiles" / f"{str(profile.get('slug') or profile.get('id') or '').strip()}.json"
    setattr(args, "creator_profile_resolved_path", profile_path if Path(profile_path).exists() else None)
    defaults = creator_tts_defaults(profile)
    if defaults.get("provider") and str(getattr(args, "tts_provider", "") or "moss_tts_local") == "moss_tts_local":
        args.tts_provider = defaults["provider"]
    if defaults.get("mode") and not str(getattr(args, "tts_mode", "") or "").strip():
        args.tts_mode = defaults["mode"]
    if defaults.get("reference_history_path") and not str(getattr(args, "reference_history_path", "") or "").strip():
        args.reference_history_path = defaults["reference_history_path"]
    if defaults.get("prompt_text") and str(getattr(args, "prompt_text", "") or "") in {"", DEFAULT_TTS_PROMPT_TEXT}:
        args.prompt_text = defaults["prompt_text"]
    caption_defaults = creator_caption_style_defaults(profile)
    if caption_defaults.get("subtitle_style_profile") and not str(getattr(args, "subtitle_style_profile", "") or "").strip():
        args.subtitle_style_profile = caption_defaults["subtitle_style_profile"]
    return profile


def extract_tts_run_voice_evidence(run_payload: dict[str, Any]) -> dict[str, Any]:
    request = run_payload.get("request") if isinstance(run_payload.get("request"), dict) else {}
    result = run_payload.get("result") if isinstance(run_payload.get("result"), dict) else {}
    return {
        "run_id": str(run_payload.get("run_id") or ""),
        "request_provider": str(request.get("provider") or ""),
        "request_mode": str(request.get("mode") or ""),
        "request_reference_path": str(request.get("reference_path") or request.get("reference_history_path") or ""),
        "request_prompt_text": str(request.get("prompt_text") or ""),
        "result_provider": str(result.get("provider") or ""),
        "result_mode": str(result.get("mode") or ""),
        "result_reference_audio": str(result.get("reference_audio") or ""),
        "result_prompt_text": str(result.get("prompt_text") or ""),
        "config_summary": str(result.get("config_summary") or ""),
        "audio_url": str(result.get("audio_url") or ""),
    }


def find_episode_video(source_root: Path, episode: int) -> Path | None:
    season_dir = source_root / "中文配音 (中文字幕)" / "第二季 (Season 2)"
    patterns = [
        f"SampleShow.S02E{episode:02d}.*.mp4",
        f"*S02E{episode:02d}*.mp4",
    ]
    for pattern in patterns:
        matches = sorted(season_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def build_episode_sample(script: EpisodeScript, video: Path, args: argparse.Namespace) -> SampleReport:
    episode_dir = args.output_dir / f"s02e{script.episode:02d}_{safe_name(script.title)}"
    work_dir = episode_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    episode_dir.mkdir(parents=True, exist_ok=True)

    target_chars = max(500, min(820, int(float(args.tts_target_duration_sec or 148.0) * float(args.chars_per_sec or 3.8))))
    script_text = resolve_script_text_for_tts(script.body, args=args, target_chars=target_chars)
    script_chars = len(script_text)
    source_duration = probe_duration(video)
    narration_path = episode_dir / f"s02e{script.episode:02d}_narration.wav"
    tts_request_metadata_path = episode_dir / f"s02e{script.episode:02d}_tts_request.json"
    tts_request_metadata = build_tts_request_metadata(
        script_text,
        provider=args.tts_provider,
        mode=args.tts_mode,
        reference_history_path=args.reference_history_path,
        prompt_text=args.prompt_text,
    )
    notes: list[str] = []
    tts_status = "skipped"
    tts_source = "none"

    if args.skip_tts:
        estimated_duration = max(120.0, min(180.0, script_chars / max(1.0, float(args.chars_per_sec or 3.8))))
        synthesize_silence(narration_path, estimated_duration)
        write_tts_request_metadata(
            tts_request_metadata_path,
            request=tts_request_metadata,
            status="skipped",
            narration_path=narration_path,
            source="silent_placeholder",
        )
        notes.append("TTS skipped; used silent placeholder narration.")
    else:
        cached_tts_metadata = (
            load_matching_tts_request_metadata(tts_request_metadata_path, tts_request_metadata)
            if narration_path.exists() and not (args.force_tts or args.force)
            else None
        )
        if cached_tts_metadata is not None:
            tts_status = "cached"
            tts_source = str(cached_tts_metadata.get("source") or "local_cache")
        else:
            if narration_path.exists() and not (args.force_tts or args.force):
                notes.append("Ignored stale local narration cache because TTS voice signature metadata was missing or mismatched.")
            history_result = None if args.force_tts else find_completed_tts_run_result(script_text, tts_request=tts_request_metadata)
            if history_result is not None and restore_tts_audio_from_history(history_result, output_path=narration_path, api_base=args.api_base):
                tts_status = "reused_history"
                tts_source = "tool_run_history"
                write_tts_request_metadata(
                    tts_request_metadata_path,
                    request=tts_request_metadata,
                    status=tts_status,
                    narration_path=narration_path,
                    source=tts_source,
                    run_metadata=history_result,
                )
                notes.append("Reused completed MOSS TTS audio from tool run history for matching script text and voice signature.")
            else:
                synthesis_result = synthesize_tts_via_api(
                    api_base=args.api_base,
                    text=script_text,
                    output_path=narration_path,
                    provider=args.tts_provider,
                    mode=args.tts_mode,
                    reference_history_path=args.reference_history_path,
                    prompt_text=args.prompt_text,
                    seed=20260617 + script.episode,
                    timeout_sec=float(args.tts_timeout_sec),
                    poll_sec=float(args.tts_poll_sec),
                )
                tts_status = str(synthesis_result.get("status") or "completed")
                tts_source = "live_tts_api"
                write_tts_request_metadata(
                    tts_request_metadata_path,
                    request=tts_request_metadata,
                    status=tts_status,
                    narration_path=narration_path,
                    source=tts_source,
                    run_metadata=synthesis_result,
                )

    narration_duration = probe_duration(narration_path)
    if narration_duration <= 0:
        raise RuntimeError(f"S02E{script.episode:02d} TTS produced invalid narration audio: {narration_path}")
    narration_rms_dbfs = probe_wav_rms_dbfs(narration_path)
    if not args.skip_tts and (narration_rms_dbfs is None or narration_rms_dbfs < -45.0):
        raise RuntimeError(
            f"S02E{script.episode:02d} TTS narration is silent or too quiet "
            f"({narration_rms_dbfs} dBFS): {narration_path}"
        )

    paced_audio_path = work_dir / f"s02e{script.episode:02d}_narration_paced.wav"
    tts_metadata = find_tts_run_metadata(
        script_text,
        narration_duration=narration_duration,
        tts_request=tts_request_metadata,
    )
    tts_segment_timings: list[TtsSegmentTiming] = []
    subtitle_alignment_source = "audio_voice_activity"
    if tts_metadata is not None:
        silence_stats, tts_segment_timings = build_tts_segment_paced_audio(
            tts_metadata,
            paced_audio_path,
            work_dir=work_dir / "tts_segment_pacing",
            min_output_duration_sec=0.0,
            force=args.force,
        )
        subtitle_alignment_source = "moss_tts_live_segments"
    else:
        normalized_audio_path = work_dir / f"s02e{script.episode:02d}_narration_pcm.wav"
        normalize_wav_for_edit(narration_path, normalized_audio_path, force=args.force)
        silence_stats = trim_long_silences(
            normalized_audio_path,
            paced_audio_path,
            max_internal_silence_sec=MAX_INTERNAL_BREATH_SEC,
            max_edge_silence_sec=MAX_EDGE_SILENCE_SEC,
            force=args.force,
        )
    if silence_stats.trimmed_sec > 0.05:
        notes.append(
            f"Trimmed long TTS breaths/silence by {silence_stats.trimmed_sec:.2f}s "
            f"(voice_segments={silence_stats.voice_segment_count}, max_removed_gap={silence_stats.max_removed_gap_sec:.2f}s)."
        )
    if tts_segment_timings:
        notes.append(f"MOSS TTS live_segments used for segment pacing and breath trimming ({len(tts_segment_timings)} generated audio segments).")

    final_target_duration = float(args.final_target_duration_sec or 0.0)
    paced_duration = probe_duration(paced_audio_path)
    effective_output_duration = paced_duration
    render_audio_path = paced_audio_path
    if final_target_duration > 0 and paced_duration > final_target_duration:
        effective_output_duration = final_target_duration
        speed_ratio = paced_duration / max(effective_output_duration, 1.0)
        if speed_ratio > 1.55:
            raise RuntimeError(
                f"S02E{script.episode:02d} narration is too long for the explicit final tempo-fit target "
                f"({paced_duration:.1f}s -> {effective_output_duration:.1f}s, ratio={speed_ratio:.2f}). "
                "Increase --final-target-duration-sec or render the full-length script without a target fit."
            )
        render_audio_path = work_dir / f"s02e{script.episode:02d}_narration_fit.wav"
        time_compress_audio(paced_audio_path, render_audio_path, speed_ratio=speed_ratio, force=args.force)
        notes.append(
            f"Narration exceeded final target; generated fitted narration at {speed_ratio:.2f}x "
            f"({paced_duration:.1f}s -> {effective_output_duration:.1f}s) after silence pacing instead of cutting the ending."
        )
    effective_output_duration = probe_duration(render_audio_path)

    tts_asr_evidence = AsrEvidence(
        status="skipped",
        purpose="tts_subtitle_alignment",
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        text="",
        duration_sec=round(effective_output_duration, 3),
        token_count=0,
        normalized_char_count=0,
        canonical_coverage=None,
        evidence_path=None,
    )
    asr_subtitle_timings: list[tuple[str, float, float]] = []
    remix_subtitle_timings: list[RemixSubtitleTiming] = []
    remix_asr_tokens: list[RemixAsrToken] = []
    subtitle_timing_audit: dict[str, Any] = {
        "status": "skipped",
        "event_count": 0,
        "matched_count": 0,
        "unmatched_count": 0,
        "bad_drift_count": 0,
        "max_abs_start_drift_sec": None,
        "max_abs_end_drift_sec": None,
    }
    subtitle_timing_audit_path = work_dir / f"s02e{script.episode:02d}_subtitle_asr_timing_audit.json"
    if args.skip_tts_asr_align or args.skip_tts:
        notes.append("TTS-ASR subtitle alignment was skipped by flag; this is not a final-sample quality path.")
    else:
        tts_asr_evidence, asr_tokens = build_tts_asr_alignment_evidence(
            audio_path=render_audio_path,
            canonical_text=script_text,
            work_dir=work_dir,
            episode=script.episode,
            args=args,
        )
        remix_asr_tokens = [RemixAsrToken(token.text, token.start_sec, token.end_sec) for token in asr_tokens]
        tts_alignment_gate = remix_alignment.evaluate_tts_asr_alignment(
            canonical_text=script_text,
            recognized_text=tts_asr_evidence.text,
            tokens=remix_asr_tokens,
            min_pass_coverage=max(0.90, float(args.min_tts_asr_coverage)),
            min_warn_coverage=float(args.min_tts_asr_coverage),
        )
        if tts_asr_evidence.status != "done":
            raise RuntimeError(f"S02E{script.episode:02d} TTS-ASR alignment failed: {tts_asr_evidence.error}")
        if tts_alignment_gate.failed:
            raise RuntimeError(
                f"S02E{script.episode:02d} TTS-ASR coverage below quality gate: "
                f"{tts_asr_evidence.canonical_coverage} < {args.min_tts_asr_coverage}. "
                f"Evidence: {tts_asr_evidence.evidence_path}"
            )
        remix_subtitle_timings = remix_alignment.build_asr_aligned_subtitle_timings(
            split_subtitle_chunks(script_text),
            remix_asr_tokens,
            duration_sec=effective_output_duration,
        )
        asr_subtitle_timings = [(item.text, item.start_sec, item.end_sec) for item in remix_subtitle_timings]
        if not asr_subtitle_timings:
            raise RuntimeError(f"S02E{script.episode:02d} TTS-ASR produced no usable subtitle timings.")
        subtitle_alignment_source = remix_alignment.TTS_ALIGNMENT_SOURCE
        notes.append(
            f"TTS-ASR subtitle timing uses Qwen3-ASR forced-aligner evidence "
            f"(coverage={tts_asr_evidence.canonical_coverage:.3f}, tokens={tts_asr_evidence.token_count})."
        )

    clip_count = min(18, max(10, int(math.ceil(effective_output_duration / 22.0))))
    clip_duration = max(5.0, effective_output_duration / clip_count)
    source_asr_index = build_source_asr_index(
        video=video,
        work_dir=work_dir,
        script=script,
        script_text=script_text,
        source_duration=source_duration,
        clip_count=clip_count,
        clip_duration=clip_duration,
        args=args,
    )
    if source_asr_index.status != "done" and not args.skip_source_asr_index:
        raise RuntimeError(f"S02E{script.episode:02d} source ASR index failed: {source_asr_index.error}")
    if source_asr_index.status == "done" and source_asr_index.anchor_count < int(args.min_source_asr_anchors):
        raise RuntimeError(
            f"S02E{script.episode:02d} source ASR evidence is too sparse: "
            f"{source_asr_index.anchor_count} < {args.min_source_asr_anchors}. "
            f"Evidence: {source_asr_index.evidence_path}"
        )
    if source_asr_index.status == "done":
        notes.append(
            f"Source-video ASR index uses Qwen3-ASR on plot-anchor windows "
            f"({source_asr_index.anchor_count} usable anchors) for clip positioning evidence."
        )
    original_audio_insertions_path = work_dir / f"s02e{script.episode:02d}_original_audio_insertions.json"
    original_audio_intent_analysis_path = work_dir / f"s02e{script.episode:02d}_original_audio_reference_intent.json"
    original_audio_source_mapping_path = work_dir / f"s02e{script.episode:02d}_original_audio_source_mapping.json"
    original_audio_intent_analysis = analyze_original_audio_reference_intent_with_llm(
        script=script,
        script_text=script_text,
        output_path=original_audio_intent_analysis_path,
        force=args.force,
    )
    reference_intents = list(original_audio_intent_analysis.get("source_quote_requests") or [])
    candidate_reference_intent_count = len(reference_intents)
    original_audio_insertions: list[dict[str, Any]] = []
    if reference_intents and source_asr_index.selected_starts:
        original_audio_insertions = build_original_audio_insert_plan(
            intents=reference_intents,
            selected_source_starts=source_asr_index.selected_starts,
            narration_duration_sec=effective_output_duration,
            source_duration_sec=source_duration,
            script_char_count=len(script_text),
        )
        original_audio_insertions = map_original_audio_insertions_to_source_asr_with_llm(
            script=script,
            script_text=script_text,
            intents=reference_intents,
            insertions=original_audio_insertions,
            source_asr_index_path=Path(source_asr_index.evidence_path) if source_asr_index.evidence_path else None,
            output_path=original_audio_source_mapping_path,
            force=args.force,
        )
        original_audio_insertions = filter_original_audio_insertions_by_mapping_quality(original_audio_insertions)
        reference_intents = [
            reference_intents[int(item.get("index") or 0) - 1]
            for item in original_audio_insertions
            if 0 < int(item.get("index") or 0) <= len(reference_intents)
        ]
        original_audio_insertions = refine_original_audio_bridge_boundaries(
            original_audio_insertions,
            source_duration_sec=source_duration,
        )
        original_audio_insertions = align_original_audio_insertions_to_tts_asr_timings(
            script_text=script_text,
            insertions=original_audio_insertions,
            subtitle_timings=remix_subtitle_timings,
        )
        original_audio_insertions = snap_original_audio_insertions_to_subtitle_boundaries(
            original_audio_insertions,
            subtitle_timings=remix_subtitle_timings,
        )
        if original_audio_insertions:
            mixed_audio_path = work_dir / f"s02e{script.episode:02d}_narration_with_original_audio.wav"
            apply_original_audio_insertions(
                narration_path=render_audio_path,
                source_video=video,
                output_path=mixed_audio_path,
                insertions=original_audio_insertions,
                work_dir=work_dir / "original_audio_insertions",
                force=args.force,
            )
            render_audio_path = mixed_audio_path
            effective_output_duration = probe_duration(render_audio_path)
            remix_subtitle_timings = shift_subtitle_timings_for_insertions(remix_subtitle_timings, original_audio_insertions)
            remix_asr_tokens = shift_asr_tokens_for_insertions(remix_asr_tokens, original_audio_insertions)
            asr_subtitle_timings = [(item.text, item.start_sec, item.end_sec) for item in remix_subtitle_timings]
            notes.append(
                f"Detected {len(reference_intents)} original-footage context bridge intent(s); inserted "
                f"{len(original_audio_insertions)} source audio/video bridge(s) totaling "
                f"{sum(float(item.get('duration_sec') or 0.0) for item in original_audio_insertions):.1f}s."
            )
    original_audio_insertions_path.write_text(
        json.dumps(
            {
                "schema": "roughcut.remix.original_audio_insertions.v1",
                "episode": script.episode,
                "intent_analysis_path": str(original_audio_intent_analysis_path),
                "source_mapping_path": str(original_audio_source_mapping_path) if original_audio_source_mapping_path.exists() else None,
                "source_mapping_source": original_audio_insertions[0].get("source_mapping_source") if original_audio_insertions else "",
                "source_mapping_llm_reviewed": all(bool(item.get("source_mapping_llm_reviewed")) for item in original_audio_insertions) if original_audio_insertions else False,
                "intent_detection_source": original_audio_intent_analysis.get("source"),
                "llm_reviewed": bool(original_audio_intent_analysis.get("llm_reviewed")),
                "decision": original_audio_intent_analysis.get("decision"),
                "confidence": original_audio_intent_analysis.get("confidence"),
                "candidate_reference_intent_count": candidate_reference_intent_count,
                "reference_intent_count": len(reference_intents),
                "insert_count": len(original_audio_insertions),
                "insert_total_duration_sec": round(sum(float(item.get("duration_sec") or 0.0) for item in original_audio_insertions), 3),
                "insertions": original_audio_insertions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if remix_subtitle_timings and remix_asr_tokens:
        subtitle_timing_audit = remix_alignment.audit_subtitle_timing_alignment(remix_subtitle_timings, remix_asr_tokens)
        subtitle_timing_audit_path.write_text(json.dumps(subtitle_timing_audit, ensure_ascii=False, indent=2), encoding="utf-8")
        if subtitle_timing_audit.get("status") != "pass":
            raise RuntimeError(
                f"S02E{script.episode:02d} subtitle timing failed ASR audit: "
                f"unmatched={subtitle_timing_audit.get('unmatched_count')}, "
                f"bad_drift={subtitle_timing_audit.get('bad_drift_count')}. "
                f"Evidence: {subtitle_timing_audit_path}"
            )
        notes.append(
            f"Subtitle ASR timing audit passed "
            f"(unmatched={subtitle_timing_audit.get('unmatched_count')}, bad_drift={subtitle_timing_audit.get('bad_drift_count')})."
        )
    clip_count = min(18, max(10, int(math.ceil(effective_output_duration / 22.0))))
    clip_duration = max(5.0, effective_output_duration / clip_count)
    scene_index_path = episode_dir / f"s02e{script.episode:02d}_scene_index.json"
    scene_index_status, scene_spans = build_scene_index_file(
        video=video,
        output_path=scene_index_path,
        source_duration=source_duration,
        args=args,
    )
    notes.append(f"Scene index status={scene_index_status}, scenes={len(scene_spans)}.")
    segment_paths, clip_starts, clip_durations = build_video_segments(
        video,
        work_dir,
        source_duration,
        clip_count,
        clip_duration,
        episode=script.episode,
        clip_anchor_starts=source_asr_index.selected_starts,
        force=args.force,
    )
    concat_path = episode_dir / f"s02e{script.episode:02d}_video_montage.mp4"
    concat_segments(segment_paths, concat_path, force=args.force)
    original_audio_visual_bridge_count = 0
    if original_audio_insertions:
        bridged_concat_path = episode_dir / f"s02e{script.episode:02d}_video_montage_with_source_bridges.mp4"
        original_audio_visual_bridge_count = apply_original_audio_visual_bridges(
            montage_path=concat_path,
            source_video=video,
            output_path=bridged_concat_path,
            insertions=original_audio_insertions,
            work_dir=work_dir / "original_audio_visual_bridges",
            duration_sec=effective_output_duration,
            force=args.force,
        )
        if original_audio_visual_bridge_count:
            concat_path = bridged_concat_path
            notes.append(
                f"Inserted {original_audio_visual_bridge_count} source-video bridge segment(s) "
                "at the original-audio bridge positions."
            )
    clean_narration_path = episode_dir / f"s02e{script.episode:02d}_narration_clean.wav"

    subtitle_path = episode_dir / f"s02e{script.episode:02d}_narration.ass"
    caption_package_path = episode_dir / f"s02e{script.episode:02d}_caption_package.json"
    semantic_packaging_plan_path = work_dir / f"s02e{script.episode:02d}_semantic_caption_packaging.json"
    semantic_packaging_plan = analyze_semantic_caption_packaging_with_llm(
        script=script,
        script_text=script_text,
        subtitle_timings=asr_subtitle_timings,
        duration_sec=effective_output_duration,
        original_audio_insertions=original_audio_insertions,
        output_path=semantic_packaging_plan_path,
        force=args.force,
    )
    notes.append(
        "LLM semantic packaging plan generated for theme banners, keyword bubbles, impact words, "
        f"inline emphasis, and source-bridge labels: {semantic_packaging_plan_path}."
    )
    caption_package = write_ass_subtitles(
        subtitle_path,
        title=f"第{script.episode}集《{script.title}》",
        question=script.question,
        text=script_text,
        duration=effective_output_duration,
        audio_path=render_audio_path,
        asr_aligned_timings=asr_subtitle_timings,
        tts_segment_timings=scale_tts_segment_timings(tts_segment_timings, target_duration=effective_output_duration),
        episode=script.episode,
        episode_title=script.title,
        subtitle_style_profile=str(getattr(args, "subtitle_style_profile", "") or ""),
        semantic_packaging_plan=semantic_packaging_plan,
        original_audio_insertions=original_audio_insertions,
    )
    caption_package_path.write_text(json.dumps(caption_package, ensure_ascii=False, indent=2), encoding="utf-8")
    subtitle_event_count = int(caption_package.get("subtitle_event_count") or 0)
    subtitle_text_coverage = float(caption_package.get("subtitle_text_coverage") or 0.0)
    packaging_event_count = int(caption_package.get("packaging_event_count") or 0)
    packaging_audio_cues = [item for item in caption_package.get("audio_cues") or [] if isinstance(item, dict)]
    if packaging_audio_cues:
        cue_audio_path = work_dir / f"s02e{script.episode:02d}_narration_with_packaging_cues.wav"
        apply_packaging_audio_cues(render_audio_path, cue_audio_path, audio_cues=packaging_audio_cues, force=args.force)
        render_audio_path = cue_audio_path
        effective_output_duration = probe_duration(render_audio_path)
        notes.append(f"Mixed {len(packaging_audio_cues)} short packaging cue sound(s) into final narration audio.")
    copy_file(render_audio_path, clean_narration_path, force=args.force)

    output_path = episode_dir / f"sample_show_s02e{script.episode:02d}_{safe_name(script.title)}_parenting_remix.mp4"
    mux_final(concat_path, render_audio_path, subtitle_path, output_path, duration=effective_output_duration, force=args.force)
    output_duration = probe_duration(output_path)
    if output_duration <= 0:
        raise RuntimeError(f"S02E{script.episode:02d} output duration is invalid: {output_duration:.3f}s")
    if not output_has_audio_stream(output_path):
        raise RuntimeError(f"S02E{script.episode:02d} output has no audio stream: {output_path}")
    review_frames_manifest_path = episode_dir / f"s02e{script.episode:02d}_review_frames.json"
    review_frames_manifest = extract_review_frames(
        episode=script.episode,
        title=script.title,
        output_path=output_path,
        output_duration=output_duration,
        review_dir=episode_dir / "review_frames",
        manifest_path=review_frames_manifest_path,
        force=args.force,
    )
    cover_path = episode_dir / f"s02e{script.episode:02d}_{safe_name(script.title)}_cover.jpg"
    cover_path = derive_remix_cover_from_review_frames(
        review_frames_manifest=review_frames_manifest,
        cover_path=cover_path,
        force=args.force,
    )

    compliance_notes = [
        f"完整保留原始成稿文案进入 TTS，不做删句、摘要或语义压缩；"
        f"本集原始旁白 {narration_duration:.1f}s，压缩长气口后成片旁白 {effective_output_duration:.1f}s。",
        "使用原片画面作为观点型育儿解说的镜头证据。",
        "样片以新旁白和新结构为主体，不保留原片整段音频。",
        f"镜头取样避开片头片尾，起点约为：{', '.join(f'{value:.1f}s' for value in clip_starts[:6])}...",
        f"原片 ASR 定位证据：{source_asr_index.evidence_path or 'skipped'}。",
        "正式发布前仍需确认素材授权、平台规则和连续引用比例。",
    ]
    notes.extend(compliance_notes)
    topic_plan_path = episode_dir / f"s02e{script.episode:02d}_topic_plan.json"
    edit_plan_path = episode_dir / f"s02e{script.episode:02d}_edit_plan.json"
    qa_report_path = episode_dir / f"s02e{script.episode:02d}_qa_report.json"
    topic_plan = build_topic_plan_payload(
        script=script,
        script_text=script_text,
        clip_starts=clip_starts,
        clip_durations=clip_durations,
        source_asr_index=source_asr_index,
    )
    edit_plan = build_edit_plan_payload(
        script=script,
        video=video,
        concat_path=concat_path,
        output_path=output_path,
        topic_plan_path=topic_plan_path,
        scene_index_path=scene_index_path,
        scene_spans=scene_spans,
        source_asr_index=source_asr_index,
        clip_starts=clip_starts,
        clip_durations=clip_durations,
        segment_paths=segment_paths,
        subtitle_path=subtitle_path,
        narration_path=clean_narration_path,
    )
    topic_plan_path.write_text(json.dumps(topic_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    edit_plan_path.write_text(json.dumps(edit_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    sample_report = SampleReport(
        episode=script.episode,
        title=script.title,
        source_video=str(video),
        script_path=script.script_path,
        creator_profile_id=creator_profile_id(getattr(args, "creator_profile_payload", None)),
        creator_profile_name=creator_display_name(getattr(args, "creator_profile_payload", None)),
        creator_profile_path=str(getattr(args, "creator_profile_resolved_path", "") or "") or None,
        output_path=str(output_path),
        narration_path=str(narration_path),
        render_narration_path=str(clean_narration_path),
        tts_request_metadata_path=str(tts_request_metadata_path) if tts_request_metadata_path.exists() else None,
        tts_provider=str(tts_request_metadata.get("provider") or ""),
        tts_mode=str(tts_request_metadata.get("mode") or ""),
        tts_reference_history_path=str(tts_request_metadata.get("reference_history_path") or ""),
        tts_prompt_text=str(tts_request_metadata.get("prompt_text") or ""),
        tts_voice_signature=str(tts_request_metadata.get("voice_signature") or ""),
        subtitle_path=str(subtitle_path),
        caption_package_path=str(caption_package_path),
        semantic_packaging_plan_path=str(semantic_packaging_plan_path) if semantic_packaging_plan_path.exists() else None,
        topic_plan_path=str(topic_plan_path),
        edit_plan_path=str(edit_plan_path),
        qa_report_path=str(qa_report_path),
        review_frames_manifest_path=str(review_frames_manifest_path),
        cover_path=str(cover_path) if cover_path is not None else None,
        scene_index_path=str(scene_index_path),
        source_duration_sec=round(source_duration, 3),
        narration_duration_sec=round(narration_duration, 3),
        render_narration_duration_sec=round(effective_output_duration, 3),
        output_duration_sec=round(output_duration, 3),
        script_chars=script_chars,
        clip_count=clip_count,
        clip_duration_sec=round(sum(clip_durations) / max(1, len(clip_durations)), 3),
        narration_rms_dbfs=round(narration_rms_dbfs, 2) if narration_rms_dbfs is not None else None,
        silence_trimmed_sec=round(silence_stats.trimmed_sec, 3),
        tts_segment_count=len(tts_segment_timings),
        original_audio_intent_analysis_path=str(original_audio_intent_analysis_path) if original_audio_intent_analysis_path.exists() else None,
        original_audio_intent_source=str(original_audio_intent_analysis.get("source") or ""),
        original_audio_intent_decision=str(original_audio_intent_analysis.get("decision") or ""),
        original_audio_intent_confidence=coerce_optional_float(original_audio_intent_analysis.get("confidence")),
        original_audio_intent_llm_reviewed=bool(original_audio_intent_analysis.get("llm_reviewed")),
        original_audio_source_mapping_path=str(original_audio_source_mapping_path) if original_audio_source_mapping_path.exists() else None,
        original_audio_source_mapping_source=(
            str(original_audio_insertions[0].get("source_mapping_source") or "") if original_audio_insertions else ""
        ),
        original_audio_source_mapping_llm_reviewed=(
            all(bool(item.get("source_mapping_llm_reviewed")) for item in original_audio_insertions)
            if original_audio_insertions
            else bool(not reference_intents)
        ),
        original_audio_reference_intent_count=len(reference_intents),
        original_audio_insert_count=len(original_audio_insertions),
        original_audio_insert_total_duration_sec=round(
            sum(float(item.get("duration_sec") or 0.0) for item in original_audio_insertions),
            3,
        ),
        original_audio_insertions_path=str(original_audio_insertions_path) if original_audio_insertions_path.exists() else None,
        original_audio_visual_bridge_count=original_audio_visual_bridge_count,
        subtitle_alignment_source=subtitle_alignment_source,
        subtitle_event_count=subtitle_event_count,
        subtitle_text_coverage=round(subtitle_text_coverage, 4),
        subtitle_style_profile=str(caption_package.get("subtitle_style_profile") or ""),
        packaging_framework=str(caption_package.get("packaging_framework") or ""),
        hyperframes_enabled=bool(caption_package.get("hyperframes_enabled")),
        hyperframes_plan_schema=str(caption_package.get("hyperframes_plan_schema") or ""),
        hyperframes_track_count=int(caption_package.get("hyperframes_track_count") or 0),
        hyperframes_element_count=int(caption_package.get("hyperframes_element_count") or 0),
        hyperframes_effect_count=int(caption_package.get("hyperframes_effect_count") or 0),
        semantic_packaging_source=str(caption_package.get("semantic_packaging_source") or ""),
        semantic_packaging_llm_reviewed=bool(caption_package.get("semantic_packaging_llm_reviewed")),
        max_subtitle_lines_per_event=int(caption_package.get("max_subtitle_lines_per_event") or 0),
        max_subtitle_line_chars=int(caption_package.get("max_subtitle_line_chars") or 0),
        subtitle_timing_alignment_status=str(subtitle_timing_audit.get("status") or "unknown"),
        subtitle_timing_unmatched_count=int(subtitle_timing_audit.get("unmatched_count") or 0),
        subtitle_timing_bad_drift_count=int(subtitle_timing_audit.get("bad_drift_count") or 0),
        subtitle_timing_max_abs_start_drift_sec=coerce_optional_float(subtitle_timing_audit.get("max_abs_start_drift_sec")),
        subtitle_timing_max_abs_end_drift_sec=coerce_optional_float(subtitle_timing_audit.get("max_abs_end_drift_sec")),
        subtitle_timing_audit_path=str(subtitle_timing_audit_path) if subtitle_timing_audit_path.exists() else None,
        tts_asr_status=tts_asr_evidence.status,
        tts_asr_coverage=round(tts_asr_evidence.canonical_coverage, 4) if tts_asr_evidence.canonical_coverage is not None else None,
        tts_asr_token_count=tts_asr_evidence.token_count,
        tts_asr_evidence_path=tts_asr_evidence.evidence_path,
        source_asr_status=source_asr_index.status,
        source_asr_anchor_count=source_asr_index.anchor_count,
        source_asr_selected_starts=[round(value, 3) for value in source_asr_index.selected_starts],
        source_asr_index_path=source_asr_index.evidence_path,
        scene_index_status=scene_index_status,
        scene_count=len(scene_spans),
        packaging_event_count=packaging_event_count,
        theme_banner_count=int(caption_package.get("theme_banner_count") or 0),
        keyword_sticker_count=int(caption_package.get("keyword_sticker_count") or 0),
        watermark_event_count=int(caption_package.get("watermark_event_count") or 0),
        emphasis_keyword_count=int(caption_package.get("emphasis_keyword_count") or 0),
        animated_subtitle_event_count=int(caption_package.get("animated_subtitle_event_count") or 0),
        animated_packaging_event_count=int(caption_package.get("animated_packaging_event_count") or 0),
        motion_effect_count=int(caption_package.get("motion_effect_count") or 0),
        highlight_effect_count=int(caption_package.get("highlight_effect_count") or 0),
        packaging_audio_cue_count=int(caption_package.get("audio_cue_count") or 0),
        source_bridge_count=int(caption_package.get("source_bridge_count") or 0),
        review_frame_count=int(review_frames_manifest.get("frame_count") or 0),
        qa_status="pending",
        qa_issue_count=0,
        tts_status=tts_status,
        build_status="done" if output_path.exists() else "failed",
        notes=notes,
    )
    qa_payload = build_qa_report_payload(sample_report)
    qa_report_path.write_text(json.dumps(qa_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    sample_report.qa_status = str(qa_payload.get("status") or "unknown")
    sample_report.qa_issue_count = len(qa_payload.get("issues") or [])
    if sample_report.qa_status == "fail" and not (args.skip_tts or args.skip_tts_asr_align or args.skip_source_asr_index):
        raise RuntimeError(f"S02E{script.episode:02d} remix QA failed: {qa_report_path}")
    qa_report_path.write_text(json.dumps(build_qa_report_payload(sample_report), ensure_ascii=False, indent=2), encoding="utf-8")
    return sample_report


def condense_script_for_sample(text: str, *, target_chars: int) -> str:
    sentences = split_script_sentences(text)
    if not sentences:
        return text.strip()[:target_chars].strip()

    selected: list[int] = []

    def add_indexes(indexes: list[int], *, limit_chars: int) -> None:
        used = 0
        for index in indexes:
            if index < 0 or index >= len(sentences) or index in selected:
                continue
            sentence = sentences[index]
            sentence_len = len(strip_punctuation(sentence))
            if used + sentence_len > limit_chars and used > 0:
                continue
            selected.append(index)
            used += sentence_len

    opener_end = next(
        (index for index, sentence in enumerate(sentences[:14]) if "今天借" in sentence or "跟大家聊" in sentence),
        min(6, len(sentences) - 1),
    )
    add_indexes(list(range(0, opener_end + 1)), limit_chars=210)

    story_keywords = ("这一集", "示例动画", "宾果", "爸爸", "妈妈", "姐姐", "妹妹", "结果", "后来", "到最后", "这一刻")
    story_indexes = [index for index, sentence in enumerate(sentences) if any(keyword in sentence for keyword in story_keywords)]
    add_indexes(story_indexes, limit_chars=230)

    analysis_keywords = ("可能", "第一种", "第二种", "第三种", "第四种", "第五种", "背后", "其实", "不是")
    analysis_indexes = [index for index, sentence in enumerate(sentences) if any(keyword in sentence for keyword in analysis_keywords)]
    add_indexes(analysis_indexes, limit_chars=250)

    action_keywords = ("可以说", "你可以", "不要", "别急", "下次", "换成", "提醒", "更好的做法")
    action_indexes = [index for index, sentence in enumerate(sentences) if any(keyword in sentence for keyword in action_keywords)]
    add_indexes(action_indexes, limit_chars=210)

    add_indexes(list(range(max(0, len(sentences) - 4), len(sentences))), limit_chars=160)

    if len("".join(sentences[index] for index in selected)) < target_chars * 0.75:
        scored = sorted(
            range(len(sentences)),
            key=lambda index: sentence_score(sentences[index], index=index, total=len(sentences)),
            reverse=True,
        )
        add_indexes(scored, limit_chars=max(0, target_chars - len("".join(sentences[index] for index in selected))))

    ordered = sorted(set(selected))
    output: list[str] = []
    total = 0
    for index in ordered:
        sentence = sentences[index]
        sentence_len = len(strip_punctuation(sentence))
        if output and total + sentence_len > target_chars:
            continue
        output.append(sentence)
        total += sentence_len
    return "\n".join(output).strip()


def resolve_script_text_for_tts(text: str, *, args: argparse.Namespace, target_chars: int) -> str:
    if int(getattr(args, "max_script_chars", 0) or 0) > 0:
        raise RuntimeError(
            "--max-script-chars is disabled for script-footage remix builds. "
            "The source script is a polished deliverable and must not be truncated."
        )
    if bool(getattr(args, "condense_script", False)) and not bool(getattr(args, "no_condense", False)):
        return condense_script_for_sample(text, target_chars=target_chars)
    return str(text or "").strip()


def split_script_sentences(text: str) -> list[str]:
    return remix_script_topics.split_script_sentences(text)


def sentence_score(sentence: str, *, index: int, total: int) -> int:
    score = 0
    if index < 8:
        score += 4
    if index >= max(0, total - 5):
        score += 3
    for keyword in ("今天借", "这一集", "你看", "可能", "可以说", "你可以", "真正", "孩子不是", "一个被"):
        if keyword in sentence:
            score += 3
    for keyword in ("示例动画", "宾果", "爸爸", "妈妈", "孩子", "家长"):
        if keyword in sentence:
            score += 1
    return score


def synthesize_tts_via_api(
    *,
    api_base: str,
    text: str,
    output_path: Path,
    provider: str,
    mode: str,
    reference_history_path: str,
    prompt_text: str,
    seed: int,
    timeout_sec: float,
    poll_sec: float,
) -> dict[str, Any]:
    resolved_provider = resolve_tts_provider(provider)
    resolved_mode = resolve_tts_mode(resolved_provider, mode, reference_history_path)
    data = urllib.parse.urlencode(
        {
            "provider": resolved_provider,
            "mode": resolved_mode,
            "tts_text": text,
            "prompt_text": str(prompt_text or ""),
            "reference_history_path": str(reference_history_path or "").strip(),
            "stream": "false",
            "seed": str(seed),
            "moss_max_new_tokens": "4096",
            "moss_temperature": "1.0",
            "moss_top_p": "0.9",
            "moss_top_k": "50",
            "moss_repetition_penalty": "1.08",
            "auto_prompt_text_asr": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base.rstrip()}/api/v1/tools/tts",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS API request failed with HTTP {exc.code}: {detail}") from exc
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("TTS API did not return run_id")

    wait_timeout_sec = resolve_tts_wait_timeout_seconds(text, base_timeout_sec=timeout_sec)
    deadline = time.monotonic() + wait_timeout_sec
    poll_interval = min(30.0, max(0.5, float(poll_sec)))
    last_payload: dict[str, Any] = payload
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{api_base.rstrip()}/api/v1/tools/runs/{run_id}", timeout=30) as response:
            last_payload = json.loads(response.read().decode("utf-8"))
        status = str(last_payload.get("status") or "").strip()
        if status == "completed":
            result = last_payload.get("result") if isinstance(last_payload.get("result"), dict) else {}
            audio_url = str(result.get("audio_url") or "").strip()
            if not audio_url:
                raise RuntimeError("TTS completed without audio_url")
            download_url = audio_url if audio_url.startswith("http") else f"{api_base.rstrip()}{audio_url}"
            with urllib.request.urlopen(quote_url(download_url), timeout=120) as response:
                output_path.write_bytes(response.read())
            result_payload = dict(last_payload)
            result_payload["status"] = "completed"
            return result_payload
        if status == "failed":
            raise RuntimeError(f"TTS failed: {last_payload.get('error')}")
        time.sleep(poll_interval)
    raise TimeoutError(
        "TTS timed out "
        f"for run {run_id} after {wait_timeout_sec:.1f}s: "
        f"status={last_payload.get('status')!r}, detail={last_payload.get('detail')!r}, "
        f"error={last_payload.get('error')!r}"
    )


def resolve_tts_wait_timeout_seconds(text: str, *, base_timeout_sec: float) -> float:
    base_timeout = max(10.0, float(base_timeout_sec))
    segment_count = max(1, math.ceil(len(str(text or "")) / 120))
    moss_budget = 120.0 + segment_count * 90.0
    return max(base_timeout, moss_budget)


def tts_run_payload_matches_request(payload: dict[str, Any], expected_request: dict[str, Any]) -> bool:
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if not request and not result:
        return False
    run_text = str(
        request.get("text")
        or request.get("tts_text")
        or request.get("original_text")
        or result.get("tts_text")
        or result.get("text")
        or ""
    )
    actual_request = build_tts_request_metadata(
        run_text,
        provider=str(request.get("provider") or result.get("provider") or ""),
        mode=str(request.get("mode") or result.get("mode") or ""),
        reference_history_path=str(
            request.get("reference_history_path")
            or request.get("reference_path")
            or result.get("reference_history_path")
            or result.get("reference_path")
            or result.get("reference_audio")
            or ""
        ),
        prompt_text=str(request.get("prompt_text") or result.get("prompt_text") or ""),
    )
    return tts_request_matches(expected_request, actual_request)


def find_completed_tts_run_result(text: str, *, tts_request: dict[str, Any] | None = None) -> dict[str, Any] | None:
    runs_root = ROOT / "data" / "runtime" / "tools" / "runs"
    if not runs_root.exists():
        return None
    normalized_text = normalize_text_for_match(text)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in runs_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("tool") or "") != "tts":
            continue
        if str(payload.get("status") or "").strip() != "completed":
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if not result:
            continue
        result_text = normalize_text_for_match(str(result.get("tts_text") or result.get("text") or payload.get("request", {}).get("text") or ""))
        if result_text != normalized_text:
            continue
        if tts_request is not None and not tts_run_payload_matches_request(payload, tts_request):
            continue
        audio_url = str(result.get("audio_url") or "").strip()
        if not audio_url:
            continue
        candidates.append((path.stat().st_mtime, payload))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def restore_tts_audio_from_history(result: dict[str, Any], *, output_path: Path, api_base: str) -> bool:
    result_payload = result.get("result") if isinstance(result.get("result"), dict) else result
    audio_url = str(result_payload.get("audio_url") or "").strip()
    if not audio_url:
        return False
    download_url = audio_url if audio_url.startswith("http") else f"{api_base.rstrip()}{audio_url}"
    try:
        with urllib.request.urlopen(quote_url(download_url), timeout=120) as response:
            audio = response.read()
    except Exception:
        return False
    if not audio:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    return True


def find_tts_run_metadata(
    text: str,
    *,
    narration_duration: float,
    tts_request: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    runs_root = ROOT / "data" / "runtime" / "tools" / "runs"
    if not runs_root.exists():
        return None
    normalized_text = normalize_text_for_match(text)
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for path in runs_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("status") or "").strip() != "completed":
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if not isinstance(result, dict):
            continue
        result_text = normalize_text_for_match(str(result.get("tts_text") or result.get("text") or ""))
        if result_text != normalized_text:
            continue
        if tts_request is not None and not tts_run_payload_matches_request(payload, tts_request):
            continue
        live_segments = result.get("live_segments")
        if not isinstance(live_segments, list) or not live_segments:
            continue
        duration = coerce_float(result.get("duration"), default=0.0)
        duration_delta = abs(duration - narration_duration) if duration > 0 and narration_duration > 0 else 0.0
        if duration_delta > 1.0:
            continue
        candidates.append((path.stat().st_mtime, path, result))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][2]


def normalize_text_for_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def build_tts_segment_paced_audio(
    metadata: dict[str, Any],
    output_path: Path,
    *,
    work_dir: Path,
    min_output_duration_sec: float = 0.0,
    force: bool,
) -> tuple[SilenceTrimStats, list[TtsSegmentTiming]]:
    alignment_path = output_path.with_suffix(".segments.json")
    if output_path.exists() and alignment_path.exists() and not force:
        try:
            payload = json.loads(alignment_path.read_text(encoding="utf-8"))
            timings = [
                TtsSegmentTiming(
                    index=int(item.get("index") or 0),
                    text=str(item.get("text") or ""),
                    start_sec=float(item.get("start_sec") or 0.0),
                    end_sec=float(item.get("end_sec") or 0.0),
                    raw_duration_sec=float(item.get("raw_duration_sec") or 0.0),
                    render_duration_sec=float(item.get("render_duration_sec") or 0.0),
                )
                for item in payload.get("segments", [])
                if isinstance(item, dict)
            ]
            stats_payload = payload.get("silence_stats") if isinstance(payload.get("silence_stats"), dict) else {}
            stats = SilenceTrimStats(
                original_duration_sec=float(stats_payload.get("original_duration_sec") or probe_duration_from_segments(timings, raw=True)),
                output_duration_sec=float(stats_payload.get("output_duration_sec") or probe_duration(output_path)),
                trimmed_sec=float(stats_payload.get("trimmed_sec") or 0.0),
                voice_segment_count=int(stats_payload.get("voice_segment_count") or len(timings)),
                max_removed_gap_sec=float(stats_payload.get("max_removed_gap_sec") or 0.0),
            )
            if timings and (
                min_output_duration_sec <= 0
                or stats.output_duration_sec >= min_output_duration_sec
                or stats.original_duration_sec < min_output_duration_sec
            ):
                return stats, timings
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    work_dir.mkdir(parents=True, exist_ok=True)
    live_segments = [item for item in metadata.get("live_segments") or [] if isinstance(item, dict)]
    source_segments: list[tuple[int, str, Path]] = []
    for fallback_index, segment in enumerate(live_segments, start=1):
        source_path = resolve_runtime_artifact_path(str(segment.get("path") or ""))
        if source_path is not None and source_path.exists():
            source_segments.append((int(segment.get("index") or fallback_index), str(segment.get("text") or ""), source_path))
    if not source_segments:
        raise RuntimeError("MOSS TTS metadata had no readable live segment audio paths")

    def build_with_limits(
        max_internal_silence_sec: float,
        max_edge_silence_sec: float,
        suffix: str,
    ) -> tuple[SilenceTrimStats, list[TtsSegmentTiming]]:
        processed_paths: list[Path] = []
        timings: list[TtsSegmentTiming] = []
        cursor = 0.0
        total_original = 0.0
        total_trimmed = 0.0
        total_voice_segments = 0
        max_removed_gap = 0.0
        for index, text, source_path in source_segments:
            normalized_path = work_dir / f"segment_{index:03d}_pcm.wav"
            paced_path = work_dir / f"segment_{index:03d}_{suffix}.wav"
            normalize_wav_for_edit(source_path, normalized_path, force=force)
            stats = trim_long_silences(
                normalized_path,
                paced_path,
                max_internal_silence_sec=max_internal_silence_sec,
                max_edge_silence_sec=max_edge_silence_sec,
                force=True,
            )
            render_duration = probe_duration(paced_path)
            raw_duration = probe_duration(normalized_path)
            processed_paths.append(paced_path)
            timings.append(
                TtsSegmentTiming(
                    index=index,
                    text=text,
                    start_sec=round(cursor, 3),
                    end_sec=round(cursor + render_duration, 3),
                    raw_duration_sec=round(raw_duration, 3),
                    render_duration_sec=round(render_duration, 3),
                )
            )
            cursor += render_duration
            total_original += raw_duration
            total_trimmed += max(0.0, raw_duration - render_duration)
            total_voice_segments += stats.voice_segment_count
            max_removed_gap = max(max_removed_gap, stats.max_removed_gap_sec)
        concat_wav_segments(processed_paths, output_path, force=True)
        output_duration = probe_duration(output_path)
        return (
            SilenceTrimStats(
                original_duration_sec=round(total_original, 3),
                output_duration_sec=round(output_duration, 3),
                trimmed_sec=round(total_trimmed, 3),
                voice_segment_count=total_voice_segments,
                max_removed_gap_sec=round(max_removed_gap, 3),
            ),
            timings,
        )

    stats, timings = build_with_limits(MAX_INTERNAL_BREATH_SEC, MAX_EDGE_SILENCE_SEC, "paced")
    if (
        min_output_duration_sec > 0
        and stats.output_duration_sec < min_output_duration_sec
        and stats.original_duration_sec >= min_output_duration_sec
    ):
        deficit = min_output_duration_sec - stats.output_duration_sec
        relaxed_internal_silence = min(5.0, MAX_INTERNAL_BREATH_SEC + deficit / max(1, stats.voice_segment_count))
        stats, timings = build_with_limits(relaxed_internal_silence, relaxed_internal_silence, "paced_duration_guard")
    alignment_path.write_text(
        json.dumps(
            {
                "source": "moss_tts_live_segments",
                "min_output_duration_sec": min_output_duration_sec,
                "silence_stats": asdict(stats),
                "segments": [asdict(item) for item in timings],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return stats, timings


def probe_duration_from_segments(timings: list[TtsSegmentTiming], *, raw: bool) -> float:
    if raw:
        return round(sum(item.raw_duration_sec for item in timings), 3)
    return round(sum(item.render_duration_sec for item in timings), 3)


def resolve_runtime_artifact_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("/app/data/"):
        return ROOT / "data" / "runtime" / raw.removeprefix("/app/data/")
    path = Path(raw)
    if path.exists():
        return path
    return None


def concat_wav_segments(segment_paths: list[Path], output_path: Path, *, force: bool) -> None:
    if output_path.exists() and not force:
        return
    output_samples: list[int] = []
    sample_rate = NARRATION_SAMPLE_RATE
    for path in segment_paths:
        audio = read_pcm16_mono(path)
        sample_rate = int(audio["sample_rate"])
        output_samples.extend(audio["samples"])
    write_pcm16_mono(output_path, output_samples, sample_rate)


def coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def scale_tts_segment_timings(timings: list[TtsSegmentTiming], *, target_duration: float) -> list[TtsSegmentTiming]:
    if not timings:
        return []
    source_duration = max(item.end_sec for item in timings)
    if source_duration <= 0 or target_duration <= 0:
        return timings
    ratio = target_duration / source_duration
    return [
        TtsSegmentTiming(
            index=item.index,
            text=item.text,
            start_sec=round(item.start_sec * ratio, 3),
            end_sec=round(item.end_sec * ratio, 3),
            raw_duration_sec=item.raw_duration_sec,
            render_duration_sec=round(item.render_duration_sec * ratio, 3),
        )
        for item in timings
    ]


def build_tts_asr_alignment_evidence(
    *,
    audio_path: Path,
    canonical_text: str,
    work_dir: Path,
    episode: int,
    args: argparse.Namespace,
) -> tuple[AsrEvidence, list[AsrToken]]:
    evidence_path = work_dir / f"s02e{episode:02d}_tts_qwen3_asr_alignment.json"
    if evidence_path.exists() and not args.force:
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            tokens = asr_tokens_from_payload(payload)
            evidence = asr_evidence_from_payload(payload, purpose="tts_subtitle_alignment", evidence_path=evidence_path)
            if tokens:
                return evidence, tokens
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    try:
        payload = transcribe_qwen3_audio(
            audio_path,
            base_url=str(args.qwen3_asr_base),
            hotwords=build_asr_hotwords(canonical_text),
            max_new_tokens=1024,
            timeout_sec=float(args.asr_timeout_sec),
            chunk_sec=float(args.asr_chunk_sec),
            work_dir=work_dir / "tts_asr_chunks",
            force=args.force,
        )
        tokens = asr_tokens_from_payload(payload)
        recognized_text = str(payload.get("text") or "")
        coverage = lcs_coverage(normalize_eval_text(canonical_text), normalize_eval_text(recognized_text))
        evidence = AsrEvidence(
            status="done",
            purpose="tts_subtitle_alignment",
            provider="local_http_asr",
            model=str(payload.get("model") or "qwen3-asr-1.7b-forced-aligner"),
            text=recognized_text,
            duration_sec=round(float(payload.get("duration") or probe_duration(audio_path)), 3),
            token_count=len(tokens),
            normalized_char_count=len(normalize_eval_text(recognized_text)),
            canonical_coverage=round(coverage, 4),
            evidence_path=str(evidence_path),
        )
        evidence_path.write_text(
            json.dumps(
                {
                    "purpose": evidence.purpose,
                    "provider": evidence.provider,
                    "model": evidence.model,
                    "status": evidence.status,
                    "audio_path": str(audio_path),
                    "canonical_coverage": evidence.canonical_coverage,
                    "canonical_char_count": len(normalize_eval_text(canonical_text)),
                    "normalized_char_count": evidence.normalized_char_count,
                    "token_count": evidence.token_count,
                    "duration": evidence.duration_sec,
                    "text": recognized_text,
                    "tokens": [asdict(token) for token in tokens],
                    "raw": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return evidence, tokens
    except Exception as exc:
        evidence = AsrEvidence(
            status="failed",
            purpose="tts_subtitle_alignment",
            provider="local_http_asr",
            model="qwen3-asr-1.7b-forced-aligner",
            text="",
            duration_sec=round(probe_duration(audio_path), 3),
            token_count=0,
            normalized_char_count=0,
            canonical_coverage=None,
            evidence_path=str(evidence_path),
            error=f"{type(exc).__name__}: {exc}",
        )
        evidence_path.write_text(json.dumps(asdict(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
        return evidence, []


def build_source_asr_index(
    *,
    video: Path,
    work_dir: Path,
    script: EpisodeScript,
    script_text: str,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
    args: argparse.Namespace,
) -> SourceAsrIndex:
    index_path = work_dir / f"s02e{script.episode:02d}_source_qwen3_asr_index.json"
    if args.skip_source_asr_index:
        return SourceAsrIndex(
            status="skipped",
            evidence_path=None,
            anchor_count=0,
            selected_starts=episode_plot_anchor_starts(script.episode),
        )
    if index_path.exists() and not args.force:
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            selected = [float(value) for value in payload.get("selected_starts") or []]
            anchors = [item for item in payload.get("anchors") or [] if isinstance(item, dict) and item.get("status") == "done"]
            return SourceAsrIndex(
                status=str(payload.get("status") or "done"),
                evidence_path=str(index_path),
                anchor_count=len(anchors),
                selected_starts=selected,
                error=payload.get("error"),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    anchors = build_source_asr_candidate_starts(
        episode=script.episode,
        source_duration=source_duration,
        clip_count=max(clip_count, int(args.source_asr_candidate_count or 0)),
        clip_duration=clip_duration,
    )
    keywords = extract_source_anchor_keywords(script.title, script_text)
    anchor_rows: list[dict[str, Any]] = []
    error_count = 0
    for index, start in enumerate(anchors, start=1):
        snippet_path = work_dir / "source_asr_windows" / f"source_anchor_{index:02d}_{start:.1f}.wav"
        try:
            extract_audio_window(
                video,
                snippet_path,
                start_sec=start,
                duration_sec=float(args.source_asr_window_sec or 18.0),
                force=args.force,
            )
            payload = transcribe_qwen3_audio(
                snippet_path,
                base_url=str(args.qwen3_asr_base),
                hotwords=",".join(keywords[:24]),
                max_new_tokens=512,
                timeout_sec=float(args.asr_timeout_sec),
                chunk_sec=0.0,
                work_dir=work_dir / "source_asr_windows",
                force=args.force,
            )
            text = str(payload.get("text") or "")
            tokens = asr_tokens_from_payload(payload)
            matched = [keyword for keyword in keywords if keyword and keyword in text]
            anchor_rows.append(
                {
                    "index": index,
                    "status": "done",
                    "start_sec": round(start, 3),
                    "duration_sec": round(float(args.source_asr_window_sec or 18.0), 3),
                    "text": text,
                    "token_count": len(tokens),
                    "score": score_source_asr_anchor(text, keywords=keywords, time_rank=index),
                    "matched_keywords": matched[:12],
                    "audio_path": str(snippet_path),
                    "raw": payload,
                }
            )
        except Exception as exc:
            error_count += 1
            anchor_rows.append(
                {
                    "index": index,
                    "status": "failed",
                    "start_sec": round(start, 3),
                    "duration_sec": round(float(args.source_asr_window_sec or 18.0), 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    done_rows = [row for row in anchor_rows if row.get("status") == "done"]
    selected_starts = select_source_asr_clip_starts(
        done_rows,
        episode=script.episode,
        source_duration=source_duration,
        clip_count=clip_count,
        clip_duration=clip_duration,
    )
    status = "done" if done_rows else "failed"
    payload = {
        "status": status,
        "purpose": "source_plot_clip_positioning",
        "provider": "local_http_asr",
        "model": "qwen3-asr-1.7b-forced-aligner",
        "source_video": str(video),
        "keywords": keywords,
        "candidate_starts": [round(value, 3) for value in anchors],
        "selected_starts": [round(value, 3) for value in selected_starts],
        "anchor_count": len(done_rows),
        "error_count": error_count,
        "anchors": anchor_rows,
    }
    if status != "done":
        payload["error"] = "No source-video ASR anchors completed."
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return SourceAsrIndex(
        status=status,
        evidence_path=str(index_path),
        anchor_count=len(done_rows),
        selected_starts=selected_starts,
        error=payload.get("error"),
    )


def transcribe_qwen3_audio(
    audio_path: Path,
    *,
    base_url: str,
    hotwords: str,
    max_new_tokens: int,
    timeout_sec: float,
    chunk_sec: float,
    work_dir: Path,
    force: bool,
) -> dict[str, Any]:
    duration = probe_duration(audio_path)
    if chunk_sec > 0 and duration > chunk_sec * 1.25:
        work_dir.mkdir(parents=True, exist_ok=True)
        chunk_payloads: list[dict[str, Any]] = []
        all_tokens: list[AsrToken] = []
        texts: list[str] = []
        cursor = 0.0
        chunk_index = 0
        while cursor < duration - 0.05:
            chunk_index += 1
            chunk_duration = min(chunk_sec, duration - cursor)
            chunk_path = work_dir / f"{audio_path.stem}_asr_chunk_{chunk_index:02d}.wav"
            extract_audio_window(audio_path, chunk_path, start_sec=cursor, duration_sec=chunk_duration, force=force)
            payload = call_qwen3_asr_once(
                chunk_path,
                base_url=base_url,
                hotwords=hotwords,
                max_new_tokens=max_new_tokens,
                timeout_sec=timeout_sec,
            )
            chunk_tokens = [
                AsrToken(token.text, round(token.start_sec + cursor, 3), round(token.end_sec + cursor, 3))
                for token in asr_tokens_from_payload(payload)
            ]
            all_tokens.extend(chunk_tokens)
            texts.append(str(payload.get("text") or ""))
            chunk_payloads.append({"start_sec": round(cursor, 3), "duration_sec": round(chunk_duration, 3), "payload": payload})
            cursor += chunk_duration
        return {
            "text": "".join(texts),
            "duration": round(duration, 3),
            "model": "qwen3-asr-1.7b-forced-aligner",
            "segments": [],
            "word_or_char_timestamps": [asdict(token) for token in all_tokens],
            "chunks": chunk_payloads,
            "meta_info": {"chunked": True, "chunk_sec": chunk_sec},
        }
    return call_qwen3_asr_once(
        audio_path,
        base_url=base_url,
        hotwords=hotwords,
        max_new_tokens=max_new_tokens,
        timeout_sec=timeout_sec,
    )


def call_qwen3_asr_once(
    audio_path: Path,
    *,
    base_url: str,
    hotwords: str,
    max_new_tokens: int,
    timeout_sec: float,
) -> dict[str, Any]:
    url = f"{str(base_url).rstrip('/')}/transcribe"
    payload = post_multipart_form(
        url,
        fields={
            "language": "Chinese",
            "hotwords": str(hotwords or ""),
            "max_new_tokens": str(max_new_tokens),
        },
        file_field="file",
        file_path=audio_path,
        timeout_sec=timeout_sec,
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Qwen3-ASR returned invalid payload for {audio_path}")
    return payload


def post_multipart_form(
    url: str,
    *,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    boundary = f"roughcut-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def asr_tokens_from_payload(payload: dict[str, Any]) -> list[AsrToken]:
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else None
    chunked_source = payload if isinstance(payload.get("chunks"), list) else raw
    if isinstance(chunked_source, dict) and isinstance(chunked_source.get("chunks"), list):
        chunked_tokens: list[AsrToken] = []
        for chunk in chunked_source.get("chunks") or []:
            if not isinstance(chunk, dict) or not isinstance(chunk.get("payload"), dict):
                continue
            offset = coerce_float(chunk.get("start_sec"), default=0.0)
            for token in _asr_tokens_from_single_payload(chunk["payload"]):
                chunked_tokens.append(
                    AsrToken(
                        text=token.text,
                        start_sec=round(token.start_sec + offset, 3),
                        end_sec=round(token.end_sec + offset, 3),
                    )
                )
        if chunked_tokens:
            return normalize_asr_token_timeline(chunked_tokens)
    return normalize_asr_token_timeline(_asr_tokens_from_single_payload(payload))


def _asr_tokens_from_single_payload(payload: dict[str, Any]) -> list[AsrToken]:
    direct = payload.get("tokens")
    rows: list[Any] = list(direct) if isinstance(direct, list) else []
    timestamps = payload.get("word_or_char_timestamps") or payload.get("timestamps")
    if isinstance(timestamps, list):
        rows.extend(timestamps)
    for segment in payload.get("segments") or []:
        if isinstance(segment, dict) and isinstance(segment.get("words"), list):
            rows.extend(segment["words"])
    tokens: list[AsrToken] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or row.get("word") or row.get("char") or "").strip()
        if not text:
            continue
        start = coerce_float(row.get("start_sec", row.get("start", row.get("start_time"))), default=0.0)
        end = coerce_float(row.get("end_sec", row.get("end", row.get("end_time"))), default=0.0)
        if end <= start:
            continue
        tokens.append(AsrToken(text=text, start_sec=round(start, 3), end_sec=round(end, 3)))
    return tokens


def normalize_asr_token_timeline(tokens: list[AsrToken]) -> list[AsrToken]:
    normalized: list[AsrToken] = []
    previous_end = 0.0
    for token in sorted(tokens, key=lambda item: (item.start_sec, item.end_sec)):
        start = max(0.0, float(token.start_sec))
        end = max(start + 0.001, float(token.end_sec))
        if normalized and end <= previous_end + 0.001:
            continue
        normalized.append(AsrToken(text=token.text, start_sec=round(start, 3), end_sec=round(end, 3)))
        previous_end = end
    return normalized


def asr_evidence_from_payload(payload: dict[str, Any], *, purpose: str, evidence_path: Path) -> AsrEvidence:
    tokens = asr_tokens_from_payload(payload)
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else payload
    text = str(payload.get("text") or raw.get("text") or "")
    return AsrEvidence(
        status=str(payload.get("status") or "done"),
        purpose=str(payload.get("purpose") or purpose),
        provider=str(payload.get("provider") or "local_http_asr"),
        model=str(payload.get("model") or raw.get("model") or "qwen3-asr-1.7b-forced-aligner"),
        text=text,
        duration_sec=coerce_float(payload.get("duration", raw.get("duration")), default=0.0),
        token_count=int(payload.get("token_count") or len(tokens)),
        normalized_char_count=int(payload.get("normalized_char_count") or len(normalize_eval_text(text))),
        canonical_coverage=coerce_optional_float(payload.get("canonical_coverage")),
        evidence_path=str(evidence_path),
        error=payload.get("error"),
    )


def coerce_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_asr_aligned_subtitle_timings(
    chunks: list[str],
    tokens: list[AsrToken],
    *,
    duration: float,
) -> list[tuple[str, float, float]]:
    token_chars = expand_asr_tokens_to_chars(tokens)
    if not chunks or not token_chars:
        return []
    token_text = "".join(item["char"] for item in token_chars)
    total_canonical_chars = sum(max(1, len(normalize_eval_text(chunk))) for chunk in chunks)
    timings: list[tuple[str, float, float]] = []
    cursor = 0
    canonical_cursor = 0
    for chunk in chunks:
        chunk_norm = normalize_eval_text(chunk)
        chunk_len = max(1, len(chunk_norm))
        start_index = token_text.find(chunk_norm, cursor) if chunk_norm else -1
        if start_index >= 0:
            end_index = min(len(token_chars) - 1, start_index + chunk_len - 1)
            cursor = end_index + 1
        else:
            start_ratio = canonical_cursor / max(1, total_canonical_chars)
            end_ratio = (canonical_cursor + chunk_len) / max(1, total_canonical_chars)
            start_index = min(len(token_chars) - 1, int(round(start_ratio * max(0, len(token_chars) - 1))))
            end_index = min(len(token_chars) - 1, max(start_index, int(round(end_ratio * max(0, len(token_chars) - 1)))))
        canonical_cursor += chunk_len
        start = max(0.0, float(token_chars[start_index]["start"]) - 0.04)
        end = min(duration, float(token_chars[end_index]["end"]) + 0.12)
        if end - start < 0.75:
            end = min(duration, start + 0.9)
        timings.append((chunk, start, end))
    return normalize_subtitle_timings(timings, duration=duration)


def expand_asr_tokens_to_chars(tokens: list[AsrToken]) -> list[dict[str, float | str]]:
    chars: list[dict[str, float | str]] = []
    for token in tokens:
        units = list(normalize_eval_text(token.text))
        if not units:
            continue
        span = max(0.001, token.end_sec - token.start_sec)
        for index, unit in enumerate(units):
            chars.append(
                {
                    "char": unit,
                    "start": round(token.start_sec + span * index / len(units), 3),
                    "end": round(token.start_sec + span * (index + 1) / len(units), 3),
                }
            )
    return chars


def normalize_eval_text(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", str(text or ""))).lower()


def lcs_coverage(reference: str, candidate: str) -> float:
    if not reference:
        return 1.0 if not candidate else 0.0
    if not candidate:
        return 0.0
    previous = [0] * (len(candidate) + 1)
    for ref_char in reference:
        current = [0]
        for column, cand_char in enumerate(candidate, start=1):
            if ref_char == cand_char:
                current.append(previous[column - 1] + 1)
            else:
                current.append(max(previous[column], current[-1]))
        previous = current
    return previous[-1] / max(1, len(reference))


def build_asr_hotwords(text: str) -> str:
    return ",".join(extract_source_anchor_keywords("", text)[:30])


def extract_source_anchor_keywords(title: str, text: str) -> list[str]:
    keywords: list[str] = []
    for item in [title, *re.findall(r"[\u4e00-\u9fff]{2,6}", text)]:
        value = str(item or "").strip()
        if len(value) < 2:
            continue
        if value in keywords:
            continue
        if value in {"一个", "这个", "就是", "不是", "可以", "孩子", "我们", "他们", "自己", "今天", "因为", "所以"}:
            continue
        keywords.append(value)
        if len(keywords) >= 48:
            break
    for value in ("示例动画", "宾果", "爸爸", "妈妈", "孩子", "规则", "感受", "愿望", "边界"):
        if value not in keywords:
            keywords.append(value)
    return keywords


def build_source_asr_candidate_starts(
    *,
    episode: int,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
) -> list[float]:
    anchors = episode_plot_anchor_starts(episode)
    even = build_even_story_starts(
        source_duration=source_duration,
        clip_count=max(clip_count, len(anchors), 1),
        clip_duration=clip_duration,
        start_guard=22.0,
        end_guard=35.0,
    )
    combined = sorted(dict.fromkeys(round(value, 3) for value in [*anchors, *even]))
    return fit_anchor_count(combined, clip_count=clip_count, source_duration=source_duration, clip_duration=clip_duration)


def score_source_asr_anchor(text: str, *, keywords: list[str], time_rank: int) -> float:
    normalized = str(text or "")
    keyword_score = sum(2.0 if keyword in normalized else 0.0 for keyword in keywords[:24])
    density_score = min(8.0, len(normalize_eval_text(normalized)) / 12.0)
    time_score = max(0.0, 3.0 - time_rank * 0.08)
    return round(keyword_score + density_score + time_score, 3)


def select_source_asr_clip_starts(
    rows: list[dict[str, Any]],
    *,
    episode: int,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
) -> list[float]:
    if not rows:
        return episode_plot_anchor_starts(episode)
    anchors = [
        SourceAnchor(
            start_sec=coerce_float(row.get("start_sec"), default=0.0),
            end_sec=coerce_float(row.get("start_sec"), default=0.0) + coerce_float(row.get("duration_sec"), default=0.0),
            text=str(row.get("text") or ""),
            score=coerce_float(row.get("score"), default=0.0),
            matched_keywords=tuple(str(item) for item in row.get("matched_keywords") or []),
            status=str(row.get("status") or "done"),
        )
        for row in rows
    ]
    return remix_source_selection.select_source_asr_clip_starts(
        anchors,
        source_duration_sec=source_duration,
        clip_count=clip_count,
        clip_duration_sec=clip_duration,
    )


def extract_audio_window(
    source: Path,
    output_path: Path,
    *,
    start_sec: float,
    duration_sec: float,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.05, duration_sec):.3f}",
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def detect_original_audio_reference_intents(text: str, *, max_intents: int = 2) -> list[dict[str, Any]]:
    patterns = [
        r"先听.{0,12}(原片|原声|这段|台词|对话)",
        r"听一?下.{0,12}(原片|原声|这段|台词|对话)",
        r"(原片|原剧).{0,12}(怎么说|说了什么|声音|台词|对话)",
        r"(这段|这句).{0,8}(台词|对话|原声)",
        r"(播放|插入).{0,8}(原片|原声|台词|对话)",
    ]
    matches: list[dict[str, Any]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = int(match.start())
            context_start = max(0, start - 18)
            context_end = min(len(text), int(match.end()) + 18)
            matches.append(
                {
                    "char_start": start,
                    "char_end": int(match.end()),
                    "matched_text": match.group(0),
                    "context": text[context_start:context_end],
                }
            )
    unique: dict[int, dict[str, Any]] = {}
    for item in sorted(matches, key=lambda value: int(value["char_start"])):
        char_start = int(item["char_start"])
        if any(abs(char_start - existing) < 8 for existing in unique):
            continue
        unique[char_start] = item
    return list(unique.values())[:max_intents]


def analyze_original_audio_reference_intent_with_llm(
    *,
    script: EpisodeScript,
    script_text: str,
    output_path: Path,
    force: bool,
) -> dict[str, Any]:
    if output_path.exists() and not force:
        try:
            raw_payload = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(raw_payload, dict) and raw_payload.get("policy_version") == ORIGINAL_AUDIO_INTENT_POLICY_VERSION:
                payload = raw_payload
                return normalize_original_audio_intent_analysis(payload, script_text=script_text)
        except Exception:
            pass

    fingerprint = {
        "schema": ORIGINAL_AUDIO_INTENT_SCHEMA,
        "policy_version": ORIGINAL_AUDIO_INTENT_POLICY_VERSION,
        "episode": script.episode,
        "title": script.title,
        "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        "confidence_gate": ORIGINAL_AUDIO_INTENT_CONFIDENCE_GATE,
    }
    cache_key = build_cache_key("roughcut.remix.original_audio_reference_intent", fingerprint)
    cached = None if force else load_cached_json("roughcut.remix.original_audio_reference_intent", cache_key)
    if cached:
        payload = normalize_original_audio_intent_analysis(cached, script_text=script_text)
        payload["cached"] = True
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    prompt = build_original_audio_intent_prompt(script=script, script_text=script_text)
    try:
        response = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = asyncio.run(
                    get_reasoning_provider().complete(
                        [
                            Message(
                                role="system",
                                content=(
                                    "你是严谨的中文解说二创剪辑策划。只做文案语义判断。"
                                    "当文案正在描述原片里的具体场景、连续对话、角色动作、剧情证据或声音线索，"
                                    "且暂停解说播放一段完整原片声画能增强沉浸和证据感时，规划原片情景桥；"
                                    "只是泛泛提到原片、角色名或抽象观点时不要规划。"
                                ),
                            ),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.0,
                        max_tokens=900,
                        json_mode=True,
                    )
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 2:
                    raise
                wait_sec = 8.0 if "429" in str(exc) else 2.0
                time.sleep(wait_sec)
        if response is None:
            raise RuntimeError(f"LLM intent review returned no response: {last_exc}")
        raw_payload = response.as_json()
        if not isinstance(raw_payload, dict):
            raise ValueError("LLM did not return a JSON object")
        payload = normalize_original_audio_intent_analysis(
            {
                **raw_payload,
                "schema": ORIGINAL_AUDIO_INTENT_SCHEMA,
                "policy_version": ORIGINAL_AUDIO_INTENT_POLICY_VERSION,
                "source": "llm_script_intent",
                "llm_reviewed": True,
                "provider": response.model,
                "usage": response.usage,
            },
            script_text=script_text,
        )
        save_cached_json(
            "roughcut.remix.original_audio_reference_intent",
            cache_key,
            fingerprint=fingerprint,
            result=payload,
            usage_baseline=response.usage,
        )
    except Exception as exc:
        reviewed_fallback = load_reviewed_original_audio_intent_fallback(output_path, script_text=script_text)
        if reviewed_fallback:
            payload = reviewed_fallback
        else:
            payload = normalize_original_audio_intent_analysis(
                {
                    "schema": ORIGINAL_AUDIO_INTENT_SCHEMA,
                    "policy_version": ORIGINAL_AUDIO_INTENT_POLICY_VERSION,
                    "source": "llm_script_intent",
                    "llm_reviewed": False,
                    "decision": "no_insert",
                    "confidence": 0.0,
                    "reason": f"LLM intent review unavailable; QA must fail until reviewed: {type(exc).__name__}: {exc}",
                    "source_quote_requests": [],
                    "error": str(exc),
                },
                script_text=script_text,
            )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_reviewed_original_audio_intent_fallback(output_path: Path, *, script_text: str) -> dict[str, Any] | None:
    candidates = [
        output_path,
        output_path.with_name(f"{output_path.stem}.probe.json"),
        output_path.with_name(f"{output_path.stem}.reviewed.json"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            raw_payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw_payload, dict) or not raw_payload.get("llm_reviewed"):
            continue
        payload = normalize_original_audio_intent_analysis(
            {
                **raw_payload,
                "schema": ORIGINAL_AUDIO_INTENT_SCHEMA,
                "policy_version": ORIGINAL_AUDIO_INTENT_POLICY_VERSION,
                "source": "llm_script_intent",
                "llm_reviewed": True,
            },
            script_text=script_text,
        )
        if payload.get("llm_reviewed"):
            payload["cached"] = True
            payload["fallback_source"] = str(candidate)
            return payload
    return None


def build_original_audio_intent_prompt(*, script: EpisodeScript, script_text: str) -> str:
    return (
        "请判断这份二创解说文案是否应该在若干位置暂停解说、播放一段完整原片声画情景。\n"
        "核心规则：\n"
        "1. 文案明确说“听原片/听这段/播放原声/插入台词/听角色怎么说”等，必须返回 insert_original_audio。\n"
        "2. 文案正在复述原片角色对话、角色动作、场景调度、连续剧情或关键证据时，也应该返回 insert_original_audio；这类情景桥用于让观众看到并听到一个完整原片上下文，然后继续解说。\n"
        "3. 前半段如果已经描述了具体原片场景或剧情证据，必须优先规划至少 1 个前置情景桥；不能只把桥段放在视频后半段。\n"
        "4. 不要逐句插入，也不要泛泛提到原片、角色名、抽象观点就插入。只有具体场景/剧情/对话证据才插入。\n"
        "5. 每个桥段建议 6-12 秒，必须能形成一个较完整的小对话或情景，不要只截 2-3 秒单句。\n"
        "6. source_quote_requests 建议 3-5 个，覆盖前/中/后核心剧情证据；如果整篇文案只有少量具体原片证据，可以少于 3 个，但必须在 reason 说明。\n"
        "7. request_type 只能是 dialogue_quote、scene_evidence、plot_evidence、sound_evidence；char_start/char_end 是该依据在原文中的大概字符位置；matched_text 必须尽量原文摘录。\n"
        "只输出 JSON：\n"
        "{\n"
        '  "decision": "insert_original_audio|no_insert",\n'
        '  "confidence": 0.0,\n'
        '  "reason": "一句话说明",\n'
        '  "source_quote_requests": [\n'
        '    {"request_type":"scene_evidence","matched_text":"原文依据","context":"上下文","char_start":0,"char_end":0,"suggested_duration_sec":8.0,"reason":"为什么这里需要完整原片情景"}\n'
        "  ]\n"
        "}\n"
        f"集数：S02E{script.episode:02d}\n"
        f"标题：{script.title}\n"
        f"问题：{script.question}\n"
        f"文案：\n{script_text}"
    )


def normalize_original_audio_intent_analysis(payload: dict[str, Any], *, script_text: str) -> dict[str, Any]:
    decision = str(payload.get("decision") or "no_insert").strip()
    if decision not in {"insert_original_audio", "no_insert"}:
        decision = "no_insert"
    confidence = max(0.0, min(1.0, coerce_float(payload.get("confidence"), default=0.0)))
    requests: list[dict[str, Any]] = []
    if decision == "insert_original_audio" and confidence >= ORIGINAL_AUDIO_INTENT_CONFIDENCE_GATE:
        for raw_item in list(payload.get("source_quote_requests") or [])[:ORIGINAL_AUDIO_INTENT_MAX_REQUESTS]:
            if not isinstance(raw_item, dict):
                continue
            item = normalize_original_audio_quote_request(raw_item, script_text=script_text)
            if item:
                requests.append(item)
    if not requests:
        decision = "no_insert"
    return {
        "schema": ORIGINAL_AUDIO_INTENT_SCHEMA,
        "policy_version": str(payload.get("policy_version") or ORIGINAL_AUDIO_INTENT_POLICY_VERSION),
        "source": str(payload.get("source") or "llm_script_intent"),
        "llm_reviewed": bool(payload.get("llm_reviewed")),
        "cached": bool(payload.get("cached")),
        "fallback_source": payload.get("fallback_source"),
        "provider": payload.get("provider"),
        "decision": decision,
        "confidence": round(confidence, 3),
        "confidence_gate": ORIGINAL_AUDIO_INTENT_CONFIDENCE_GATE,
        "reason": str(payload.get("reason") or "").strip(),
        "source_quote_requests": requests,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "error": payload.get("error"),
    }


def normalize_original_audio_quote_request(raw_item: dict[str, Any], *, script_text: str) -> dict[str, Any] | None:
    matched_text = str(raw_item.get("matched_text") or "").strip()
    context = str(raw_item.get("context") or "").strip()
    request_type = str(raw_item.get("request_type") or raw_item.get("bridge_type") or "scene_evidence").strip()
    if request_type not in {"dialogue_quote", "scene_evidence", "plot_evidence", "sound_evidence"}:
        request_type = "scene_evidence"
    char_start = int(coerce_float(raw_item.get("char_start"), default=-1))
    char_end = int(coerce_float(raw_item.get("char_end"), default=-1))
    if matched_text:
        found = script_text.find(matched_text)
        if found >= 0:
            char_start = found
            char_end = found + len(matched_text)
    if char_start < 0 or char_start >= len(script_text):
        if context:
            found = script_text.find(context)
            if found >= 0:
                char_start = found
                char_end = found + len(context)
    if char_start < 0 or char_start >= len(script_text):
        return None
    if char_end <= char_start:
        char_end = min(len(script_text), char_start + max(1, len(matched_text)))
    default_duration = 7.0 if request_type == "dialogue_quote" else 8.0
    duration = max(
        ORIGINAL_AUDIO_BRIDGE_MIN_DURATION_SEC,
        min(ORIGINAL_AUDIO_BRIDGE_MAX_DURATION_SEC, coerce_float(raw_item.get("suggested_duration_sec"), default=default_duration)),
    )
    context_start = max(0, char_start - 24)
    context_end = min(len(script_text), char_end + 24)
    return {
        "request_type": request_type,
        "char_start": char_start,
        "char_end": char_end,
        "matched_text": matched_text or script_text[char_start:char_end],
        "context": context or script_text[context_start:context_end],
        "suggested_duration_sec": round(duration, 3),
        "reason": str(raw_item.get("reason") or "").strip(),
    }


def analyze_semantic_caption_packaging_with_llm(
    *,
    script: EpisodeScript,
    script_text: str,
    subtitle_timings: list[tuple[str, float, float]],
    duration_sec: float,
    original_audio_insertions: list[dict[str, Any]],
    output_path: Path,
    force: bool,
) -> dict[str, Any]:
    if output_path.exists() and not force:
        try:
            raw_payload = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(raw_payload, dict) and raw_payload.get("policy_version") == SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION:
                return normalize_semantic_caption_packaging_payload(
                    raw_payload,
                    script=script,
                    subtitle_timings=subtitle_timings,
                    duration_sec=duration_sec,
                )
        except Exception:
            pass

    timing_fingerprint = [
        [str(text), round(float(start), 3), round(float(end), 3)]
        for text, start, end in subtitle_timings
    ]
    insertion_fingerprint = [
        {
            "matched_text": str(item.get("matched_text") or ""),
            "insert_at_sec": round(coerce_float(item.get("insert_at_sec"), default=0.0), 3),
            "duration_sec": round(coerce_float(item.get("duration_sec"), default=0.0), 3),
        }
        for item in original_audio_insertions
    ]
    fingerprint = {
        "schema": SEMANTIC_CAPTION_PACKAGING_SCHEMA,
        "policy_version": SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION,
        "episode": script.episode,
        "title": script.title,
        "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        "subtitle_timings_sha256": hashlib.sha256(
            json.dumps(timing_fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "original_audio_insertions_sha256": hashlib.sha256(
            json.dumps(insertion_fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    cache_key = build_cache_key("roughcut.remix.semantic_caption_packaging", fingerprint)
    cached = None if force else load_cached_json("roughcut.remix.semantic_caption_packaging", cache_key)
    if cached:
        payload = normalize_semantic_caption_packaging_payload(
            cached,
            script=script,
            subtitle_timings=subtitle_timings,
            duration_sec=duration_sec,
        )
        payload["cached"] = True
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    prompt = build_semantic_caption_packaging_prompt(
        script=script,
        script_text=script_text,
        subtitle_timings=subtitle_timings,
        original_audio_insertions=original_audio_insertions,
    )
    try:
        response = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = asyncio.run(
                    get_reasoning_provider().complete(
                        [
                            Message(
                                role="system",
                                content=(
                                    "你是严谨的中文短视频剪辑包装导演。"
                                    "所有字幕重点、气泡、大字、主题横幅都必须来自文案语义，"
                                    "必须给出原文依据，不允许套用固定模板词或编造角色。"
                                ),
                            ),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.0,
                        max_tokens=1800,
                        json_mode=True,
                    )
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 2:
                    raise
                time.sleep(8.0 if "429" in str(exc) else 2.0)
        if response is None:
            raise RuntimeError(f"LLM semantic packaging review returned no response: {last_exc}")
        raw_payload = response.as_json()
        if not isinstance(raw_payload, dict):
            raise ValueError("LLM did not return a JSON object")
        payload = normalize_semantic_caption_packaging_payload(
            {
                **raw_payload,
                "schema": SEMANTIC_CAPTION_PACKAGING_SCHEMA,
                "policy_version": SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION,
                "source": "llm_script_packaging",
                "llm_reviewed": True,
                "provider": response.model,
                "usage": response.usage,
            },
            script=script,
            subtitle_timings=subtitle_timings,
            duration_sec=duration_sec,
        )
        save_cached_json(
            "roughcut.remix.semantic_caption_packaging",
            cache_key,
            fingerprint=fingerprint,
            result=payload,
            usage_baseline=response.usage,
        )
    except Exception as exc:
        reviewed_fallback = load_reviewed_semantic_packaging_fallback(
            output_path,
            script=script,
            subtitle_timings=subtitle_timings,
            duration_sec=duration_sec,
        )
        if reviewed_fallback:
            payload = reviewed_fallback
        else:
            payload = normalize_semantic_caption_packaging_payload(
                {
                    "schema": SEMANTIC_CAPTION_PACKAGING_SCHEMA,
                    "policy_version": SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION,
                    "source": "llm_script_packaging",
                    "llm_reviewed": False,
                    "opening_title": script.question or script.title,
                    "closing_title": "回到孩子的感受",
                    "subtitle_emphasis_keywords": [],
                    "theme_banners": [],
                    "keyword_bubbles": [],
                    "impact_events": [],
                    "pulse_chips": [],
                    "error": str(exc),
                },
                script=script,
                subtitle_timings=subtitle_timings,
                duration_sec=duration_sec,
            )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_reviewed_semantic_packaging_fallback(
    output_path: Path,
    *,
    script: EpisodeScript,
    subtitle_timings: list[tuple[str, float, float]],
    duration_sec: float,
) -> dict[str, Any] | None:
    for candidate in [
        output_path,
        output_path.with_name(f"{output_path.stem}.probe.json"),
        output_path.with_name(f"{output_path.stem}.reviewed.json"),
    ]:
        if not candidate.exists():
            continue
        try:
            raw_payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw_payload, dict) or not raw_payload.get("llm_reviewed"):
            continue
        payload = normalize_semantic_caption_packaging_payload(
            {
                **raw_payload,
                "schema": SEMANTIC_CAPTION_PACKAGING_SCHEMA,
                "policy_version": SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION,
                "source": "llm_script_packaging",
                "llm_reviewed": True,
            },
            script=script,
            subtitle_timings=subtitle_timings,
            duration_sec=duration_sec,
        )
        if payload.get("llm_reviewed"):
            payload["cached"] = True
            payload["fallback_source"] = str(candidate)
            return payload
    return None


def build_semantic_caption_packaging_prompt(
    *,
    script: EpisodeScript,
    script_text: str,
    subtitle_timings: list[tuple[str, float, float]],
    original_audio_insertions: list[dict[str, Any]],
) -> str:
    timing_lines = []
    for index, (text, start, end) in enumerate(subtitle_timings[:120], start=1):
        timing_lines.append(f"{index}. {start:.2f}-{end:.2f}s：{text}")
    bridge_lines = []
    for item in original_audio_insertions:
        bridge_lines.append(
            f"- {coerce_float(item.get('insert_at_sec'), default=0.0):.2f}s/"
            f"{coerce_float(item.get('duration_sec'), default=0.0):.1f}s："
            f"{item.get('matched_text') or item.get('context') or ''}"
        )
    return (
        "请基于完整二创文案和最终字幕时间戳，设计剪映风格的语义字幕包装计划。\n"
        "硬性规则：\n"
        "1. 所有 opening_title、closing_title、theme_banners、keyword_bubbles、impact_events、pulse_chips、subtitle_emphasis_keywords 都必须服务当前文案含义。\n"
        "2. 不允许使用固定模板词；不允许写文案里没有依据的角色、人物关系或剧情。\n"
        "3. 每个 theme_banners/keyword_bubbles/impact_events/pulse_chips 必须有 matched_text，matched_text 必须能在下方字幕或文案中找到语义依据。\n"
        "4. impact_events 是 1 秒左右的大字冲击，只放真正需要强调的观点或剧情转折，短词，不要为了热闹乱加。\n"
        "5. keyword_bubbles 是气泡提示，应该解释此刻育儿观点或剧情重点。\n"
        "6. theme_banners 是阶段主题横幅，必须跟接下来一段文案主题一致。\n"
        "7. subtitle_emphasis_keywords 只选字幕原文中会出现的短词，用于字幕内重点字高亮。\n"
        "8. 若存在原片声桥，包装文案要配合声桥，不要遮住字幕，不要把声桥误写成解说字幕。\n"
        "数量要求：theme_banners 3 个，keyword_bubbles 3 个，impact_events 3 个，pulse_chips 3 个，subtitle_emphasis_keywords 6-12 个。\n"
        "只输出 JSON：\n"
        "{\n"
        '  "opening_title": "不超过10字",\n'
        '  "closing_title": "不超过10字",\n'
        '  "subtitle_emphasis_keywords": [{"phrase":"字幕中出现的短词","matched_text":"字幕原文","reason":"为什么强调"}],\n'
        '  "theme_banners": [{"phrase":"不超过8字","matched_text":"字幕/文案依据","reason":"主题依据"}],\n'
        '  "keyword_bubbles": [{"phrase":"不超过8字","matched_text":"字幕/文案依据","reason":"提示依据"}],\n'
        '  "impact_events": [{"phrase":"不超过6字","matched_text":"字幕/文案依据","reason":"冲击依据"}],\n'
        '  "pulse_chips": [{"phrase":"不超过4字","matched_text":"字幕/文案依据","reason":"辅助提示依据"}]\n'
        "}\n"
        f"集数：S02E{script.episode:02d}\n"
        f"标题：{script.title}\n"
        f"问题：{script.question}\n"
        f"原片声桥计划：\n{chr(10).join(bridge_lines) if bridge_lines else '无'}\n"
        f"最终字幕时间戳：\n{chr(10).join(timing_lines)}\n"
        f"完整文案：\n{script_text}"
    )


def normalize_semantic_caption_packaging_payload(
    payload: dict[str, Any],
    *,
    script: EpisodeScript,
    subtitle_timings: list[tuple[str, float, float]],
    duration_sec: float,
) -> dict[str, Any]:
    normalized = remix_caption_packager.normalize_semantic_packaging_plan(
        payload,
        subtitle_timings=subtitle_timings,
        duration_sec=duration_sec,
        episode=script.episode,
        title=script.title,
        question=script.question,
    )
    return {
        "schema": SEMANTIC_CAPTION_PACKAGING_SCHEMA,
        "policy_version": str(payload.get("policy_version") or SEMANTIC_CAPTION_PACKAGING_POLICY_VERSION),
        "source": str(normalized.get("source") or "llm_script_packaging"),
        "llm_reviewed": bool(normalized.get("llm_reviewed")),
        "cached": bool(payload.get("cached")),
        "fallback_source": payload.get("fallback_source"),
        "provider": payload.get("provider"),
        "episode": script.episode,
        "title": script.title,
        "question": script.question,
        "opening_title": normalized.get("opening_title"),
        "closing_title": normalized.get("closing_title"),
        "subtitle_emphasis_keywords": [
            {"phrase": phrase, "matched_text": phrase, "reason": "validated_llm_keyword"}
            for phrase in list(normalized.get("subtitle_emphasis_keywords") or [])
        ],
        "theme_banners": list(normalized.get("theme_banners") or []),
        "keyword_bubbles": list(normalized.get("keyword_bubbles") or []),
        "impact_events": list(normalized.get("impact_events") or []),
        "pulse_chips": list(normalized.get("pulse_chips") or []),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "error": payload.get("error"),
    }


def map_original_audio_insertions_to_source_asr_with_llm(
    *,
    script: EpisodeScript,
    script_text: str,
    intents: list[dict[str, Any]],
    insertions: list[dict[str, Any]],
    source_asr_index_path: Path | None,
    output_path: Path,
    force: bool,
) -> list[dict[str, Any]]:
    anchors = load_source_asr_anchors(source_asr_index_path)
    if not insertions or not anchors:
        return insertions
    if output_path.exists() and not force:
        try:
            raw_payload = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(raw_payload, dict) and raw_payload.get("policy_version") == ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION:
                return normalize_original_audio_source_mapping(
                    raw_payload,
                    insertions=insertions,
                    anchors=anchors,
                )
        except Exception:
            pass

    fingerprint = {
        "schema": ORIGINAL_AUDIO_SOURCE_MAPPING_SCHEMA,
        "policy_version": ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION,
        "episode": script.episode,
        "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        "intents_sha256": hashlib.sha256(
            json.dumps(intents, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "anchors_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "start_sec": item.get("start_sec"),
                        "duration_sec": item.get("duration_sec"),
                        "text": item.get("text"),
                    }
                    for item in anchors
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    cache_key = build_cache_key("roughcut.remix.original_audio_source_mapping", fingerprint)
    cached = None if force else load_cached_json("roughcut.remix.original_audio_source_mapping", cache_key)
    if cached:
        mapped = normalize_original_audio_source_mapping(cached, insertions=insertions, anchors=anchors)
        payload = build_original_audio_source_mapping_payload(mapped, cached, anchors=anchors)
        payload["cached"] = True
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return mapped

    prompt = build_original_audio_source_mapping_prompt(
        script=script,
        intents=intents,
        insertions=insertions,
        anchors=anchors,
    )
    try:
        response = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = asyncio.run(
                    get_reasoning_provider().complete(
                        [
                            Message(
                                role="system",
                                content=(
                                    "你是中文解说二创剪辑定位助手。"
                                    "必须根据原片 ASR 文本选择原片声桥片段，不能只按时间比例猜。"
                                    "如果没有合适原片 ASR 证据，要明确低置信度。"
                                ),
                            ),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.0,
                        max_tokens=1400,
                        json_mode=True,
                    )
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 2:
                    raise
                time.sleep(8.0 if "429" in str(exc) else 2.0)
        if response is None:
            raise RuntimeError(f"LLM source-ASR mapping returned no response: {last_exc}")
        raw_payload = response.as_json()
        if not isinstance(raw_payload, dict):
            raise ValueError("LLM did not return a JSON object")
        payload = {
            **raw_payload,
            "schema": ORIGINAL_AUDIO_SOURCE_MAPPING_SCHEMA,
            "policy_version": ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION,
            "source": "llm_source_asr_mapping",
            "llm_reviewed": True,
            "provider": response.model,
            "usage": response.usage,
        }
        mapped = normalize_original_audio_source_mapping(payload, insertions=insertions, anchors=anchors)
        payload = build_original_audio_source_mapping_payload(mapped, payload, anchors=anchors)
        save_cached_json(
            "roughcut.remix.original_audio_source_mapping",
            cache_key,
            fingerprint=fingerprint,
            result=payload,
            usage_baseline=response.usage,
        )
    except Exception as exc:
        mapped = fallback_original_audio_source_mapping(
            insertions=insertions,
            anchors=anchors,
            error=f"{type(exc).__name__}: {exc}",
        )
        payload = build_original_audio_source_mapping_payload(
            mapped,
            {
                "schema": ORIGINAL_AUDIO_SOURCE_MAPPING_SCHEMA,
                "policy_version": ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION,
                "source": "source_asr_mapping_fallback",
                "llm_reviewed": False,
                "error": str(exc),
            },
            anchors=anchors,
        )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapped


def load_source_asr_anchors(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    anchors: list[dict[str, Any]] = []
    for row in payload.get("anchors") or []:
        if not isinstance(row, dict) or row.get("status") != "done":
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        anchors.append(
            {
                "index": int(coerce_float(row.get("index"), default=len(anchors) + 1)),
                "start_sec": round(coerce_float(row.get("start_sec"), default=0.0), 3),
                "duration_sec": round(coerce_float(row.get("duration_sec"), default=0.0), 3),
                "text": text,
                "score": coerce_float(row.get("score"), default=0.0),
                "matched_keywords": [str(item) for item in list(row.get("matched_keywords") or [])],
            }
        )
    return anchors


def build_original_audio_source_mapping_prompt(
    *,
    script: EpisodeScript,
    intents: list[dict[str, Any]],
    insertions: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> str:
    intent_lines: list[str] = []
    for insertion in insertions:
        idx = int(insertion.get("index") or len(intent_lines) + 1)
        intent = intents[idx - 1] if idx - 1 < len(intents) else {}
        intent_lines.append(
            f"{idx}. insert_at={coerce_float(insertion.get('insert_at_sec'), default=0.0):.2f}s, "
            f"duration={coerce_float(insertion.get('duration_sec'), default=0.0):.1f}s\n"
            f"   文案依据：{intent.get('matched_text') or insertion.get('matched_text') or ''}\n"
            f"   上下文：{intent.get('context') or insertion.get('context') or ''}"
        )
    anchor_lines: list[str] = []
    for anchor in anchors[:24]:
        anchor_lines.append(
            f"{anchor['index']}. {anchor['start_sec']:.3f}-{anchor['start_sec'] + anchor['duration_sec']:.3f}s "
            f"score={anchor.get('score')} keywords={','.join(anchor.get('matched_keywords') or [])}\n"
            f"   ASR：{anchor.get('text')}"
        )
    return (
        "请根据原片 ASR 窗口，为每个原片声桥意图选择最相关的原片片段。\n"
        "规则：\n"
        "1. 必须基于下面的原片 ASR 文本和文案依据进行匹配，不能按时间比例猜。\n"
        "2. source_start_sec 必须落在所选 anchor 的时间范围内，最好从相关台词/剧情前 0.5-1.5 秒开始，让片段形成完整对话或情景。\n"
        "3. evidence_text 必须摘自所选 anchor 的 ASR 文本，说明为什么这段是对应剧情。\n"
        "4. 如果找不到强相关证据，confidence 低于 0.7，并说明原因。\n"
        "5. 不要新增声桥，只为已有 index 选择 source_start_sec。\n"
        "只输出 JSON：\n"
        "{\n"
        '  "mappings": [\n'
        '    {"index":1,"anchor_index":7,"anchor_start_sec":158.0,"source_start_sec":157.2,"duration_sec":8.0,"evidence_text":"ASR依据","confidence":0.0,"reason":"为什么匹配"}\n'
        "  ]\n"
        "}\n"
        f"集数：S02E{script.episode:02d}《{script.title}》\n"
        f"声桥意图：\n{chr(10).join(intent_lines)}\n"
        f"原片 ASR 候选：\n{chr(10).join(anchor_lines)}"
    )


def normalize_original_audio_source_mapping(
    payload: dict[str, Any],
    *,
    insertions: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_index = {int(item.get("index") or idx + 1): dict(item) for idx, item in enumerate(insertions)}
    anchors_by_index = {int(item.get("index") or 0): item for item in anchors}
    mapped: list[dict[str, Any]] = []
    raw_mappings = payload.get("mappings") if isinstance(payload.get("mappings"), list) else []
    for raw in raw_mappings:
        if not isinstance(raw, dict):
            continue
        index = int(coerce_float(raw.get("index"), default=0))
        base = by_index.get(index)
        if not base:
            continue
        anchor_index = int(coerce_float(raw.get("anchor_index"), default=0))
        anchor = anchors_by_index.get(anchor_index) or nearest_anchor(
            anchors,
            coerce_float(raw.get("anchor_start_sec"), default=coerce_float(base.get("source_start_sec"), default=0.0)),
        )
        if not anchor:
            continue
        duration = max(
            ORIGINAL_AUDIO_BRIDGE_MIN_DURATION_SEC,
            min(ORIGINAL_AUDIO_BRIDGE_MAX_DURATION_SEC, coerce_float(raw.get("duration_sec"), default=base.get("duration_sec") or 8.0)),
        )
        anchor_start = coerce_float(anchor.get("start_sec"), default=0.0)
        anchor_end = anchor_start + max(duration, coerce_float(anchor.get("duration_sec"), default=0.0))
        source_start = coerce_float(raw.get("source_start_sec"), default=anchor_start)
        source_start = max(anchor_start, min(anchor_end - duration, source_start))
        confidence = max(0.0, min(1.0, coerce_float(raw.get("confidence"), default=0.0)))
        reviewed = bool(payload.get("llm_reviewed")) and confidence >= ORIGINAL_AUDIO_SOURCE_MAPPING_CONFIDENCE_GATE
        base.update(
            {
                "source_start_sec": round(source_start, 3),
                "duration_sec": round(duration, 3),
                "source_mapping_source": str(payload.get("source") or "llm_source_asr_mapping"),
                "source_mapping_llm_reviewed": reviewed,
                "source_mapping_confidence": round(confidence, 3),
                "source_asr_anchor_index": int(anchor.get("index") or anchor_index),
                "source_asr_anchor_start_sec": round(anchor_start, 3),
                "source_asr_text": str(anchor.get("text") or ""),
                "source_asr_evidence_text": str(raw.get("evidence_text") or "").strip(),
                "source_mapping_reason": str(raw.get("reason") or "").strip(),
            }
        )
        mapped.append(base)
    missing = [item for idx, item in by_index.items() if idx not in {int(row.get("index") or 0) for row in mapped}]
    if missing:
        mapped.extend(fallback_original_audio_source_mapping(insertions=missing, anchors=anchors, error="missing_llm_mapping"))
    return sorted(mapped, key=lambda item: int(item.get("index") or 0))


def fallback_original_audio_source_mapping(
    *,
    insertions: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    error: str,
) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for insertion in insertions:
        anchor = nearest_anchor(anchors, coerce_float(insertion.get("source_start_sec"), default=0.0))
        item = dict(insertion)
        if anchor:
            item.update(
                {
                    "source_start_sec": round(coerce_float(anchor.get("start_sec"), default=0.0), 3),
                    "source_asr_anchor_index": int(anchor.get("index") or 0),
                    "source_asr_anchor_start_sec": round(coerce_float(anchor.get("start_sec"), default=0.0), 3),
                    "source_asr_text": str(anchor.get("text") or ""),
                }
            )
        item.update(
            {
                "source_mapping_source": "source_asr_mapping_fallback",
                "source_mapping_llm_reviewed": False,
                "source_mapping_confidence": 0.0,
                "source_mapping_reason": error,
            }
        )
        mapped.append(item)
    return mapped


def filter_original_audio_insertions_by_mapping_quality(
    insertions: list[dict[str, Any]],
    *,
    min_confidence: float = ORIGINAL_AUDIO_SOURCE_MAPPING_CONFIDENCE_GATE,
) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []
    for insertion in insertions:
        confidence = coerce_float(insertion.get("source_mapping_confidence"), default=0.0)
        if not bool(insertion.get("source_mapping_llm_reviewed")) or confidence < min_confidence:
            continue
        approved.append(dict(insertion))
    return sorted(approved, key=lambda item: int(item.get("index") or 0))


def nearest_anchor(anchors: list[dict[str, Any]], target_sec: float) -> dict[str, Any] | None:
    if not anchors:
        return None
    return min(anchors, key=lambda item: abs(coerce_float(item.get("start_sec"), default=0.0) - target_sec))


def build_original_audio_source_mapping_payload(
    mapped: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": ORIGINAL_AUDIO_SOURCE_MAPPING_SCHEMA,
        "policy_version": str(payload.get("policy_version") or ORIGINAL_AUDIO_SOURCE_MAPPING_POLICY_VERSION),
        "source": str(payload.get("source") or ""),
        "llm_reviewed": bool(payload.get("llm_reviewed")),
        "provider": payload.get("provider"),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "error": payload.get("error"),
        "confidence_gate": ORIGINAL_AUDIO_SOURCE_MAPPING_CONFIDENCE_GATE,
        "anchor_count": len(anchors),
        "mapped_count": len(mapped),
        "reviewed_count": sum(1 for item in mapped if item.get("source_mapping_llm_reviewed")),
        "mappings": mapped,
    }


def build_original_audio_insert_plan(
    *,
    intents: list[dict[str, Any]],
    selected_source_starts: list[float],
    narration_duration_sec: float,
    source_duration_sec: float,
    script_char_count: int,
    insert_duration_sec: float = 8.0,
) -> list[dict[str, Any]]:
    if not intents or not selected_source_starts or narration_duration_sec <= 0:
        return []
    text_length = max(1, int(script_char_count))
    insertions: list[dict[str, Any]] = []
    for index, intent in enumerate(intents):
        ratio = min(0.96, max(0.04, int(intent.get("char_start") or 0) / text_length))
        narration_time = round(min(narration_duration_sec - 0.5, max(0.5, narration_duration_sec * ratio)), 3)
        source_index = min(len(selected_source_starts) - 1, max(0, int(round(ratio * (len(selected_source_starts) - 1)))))
        source_anchor = selected_source_starts[source_index]
        duration = max(
            ORIGINAL_AUDIO_BRIDGE_MIN_DURATION_SEC,
            min(ORIGINAL_AUDIO_BRIDGE_MAX_DURATION_SEC, coerce_float(intent.get("suggested_duration_sec"), default=insert_duration_sec)),
        )
        source_start = round(min(max(0.0, source_duration_sec - duration), source_anchor + 1.0), 3)
        insertions.append(
            {
                "index": index + 1,
                "reason": "llm_script_original_footage_context_bridge",
                "request_type": intent.get("request_type") or "scene_evidence",
                "matched_text": intent.get("matched_text"),
                "context": intent.get("context"),
                "char_start": int(coerce_float(intent.get("char_start"), default=-1)),
                "char_end": int(coerce_float(intent.get("char_end"), default=-1)),
                "insert_at_sec": narration_time,
                "source_start_sec": source_start,
                "duration_sec": round(duration, 3),
            }
        )
    return insertions


def refine_original_audio_bridge_boundaries(
    insertions: list[dict[str, Any]],
    *,
    source_duration_sec: float,
    preroll_sec: float = ORIGINAL_AUDIO_BRIDGE_PREROLL_SEC,
    postroll_sec: float = ORIGINAL_AUDIO_BRIDGE_POSTROLL_SEC,
    max_duration_sec: float = ORIGINAL_AUDIO_BRIDGE_REFINED_MAX_DURATION_SEC,
) -> list[dict[str, Any]]:
    refined: list[dict[str, Any]] = []
    source_duration = max(0.0, float(source_duration_sec))
    for insertion in insertions:
        item = dict(insertion)
        source_start = coerce_float(item.get("source_start_sec"), default=0.0)
        duration = coerce_float(item.get("duration_sec"), default=0.0)
        if duration <= 0.05 or source_duration <= 0.05:
            refined.append(item)
            continue
        new_start = max(0.0, source_start - max(0.0, preroll_sec))
        added_preroll = source_start - new_start
        new_duration = duration + added_preroll + max(0.0, postroll_sec)
        new_duration = min(max_duration_sec, max(duration, new_duration), max(0.05, source_duration - new_start))
        item.update(
            {
                "source_start_sec": round(new_start, 3),
                "duration_sec": round(new_duration, 3),
                "boundary_refinement_source": "source_bridge_context_preroll_postroll",
                "boundary_preroll_sec": round(added_preroll, 3),
                "boundary_postroll_sec": round(max(0.0, new_duration - duration - added_preroll), 3),
                "boundary_original_source_start_sec": round(source_start, 3),
                "boundary_original_duration_sec": round(duration, 3),
            }
        )
        refined.append(item)
    return refined


def align_original_audio_insertions_to_tts_asr_timings(
    *,
    script_text: str,
    insertions: list[dict[str, Any]],
    subtitle_timings: list[RemixSubtitleTiming],
    pad_sec: float = 0.08,
) -> list[dict[str, Any]]:
    if not insertions or not subtitle_timings:
        return insertions
    indexed_timings = index_subtitle_timings_against_script(script_text, subtitle_timings)
    candidates: list[dict[str, Any]] = []
    for insertion in insertions:
        item = dict(insertion)
        timing = find_tts_asr_insertion_timing(item, indexed_timings)
        if timing:
            raw_at = coerce_float(item.get("insert_at_sec"), default=0.0)
            item["insert_at_sec"] = round(float(timing["end_sec"]) + pad_sec, 3)
            item["insert_at_original_sec"] = round(raw_at, 3)
            item["insert_tts_asr_alignment_source"] = "matched_script_text_to_tts_asr_subtitle"
            item["insert_tts_asr_matched_subtitle"] = str(timing.get("text") or "")
            item["insert_tts_asr_matched_subtitle_start_sec"] = round(float(timing["start_sec"]), 3)
            item["insert_tts_asr_matched_subtitle_end_sec"] = round(float(timing["end_sec"]), 3)
        else:
            item["insert_tts_asr_alignment_source"] = "fallback_script_ratio"
        candidates.append(item)
    aligned: list[dict[str, Any]] = []
    previous_at = 0.0
    for item in sorted(candidates, key=lambda value: coerce_float(value.get("insert_at_sec"), default=0.0)):
        raw_at = coerce_float(item.get("insert_at_sec"), default=0.0)
        item["insert_at_sec"] = round(max(previous_at, raw_at), 3)
        previous_at = item["insert_at_sec"] + 0.05
        aligned.append(item)
    return aligned


def index_subtitle_timings_against_script(
    script_text: str,
    subtitle_timings: list[RemixSubtitleTiming],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    for timing in subtitle_timings:
        text = str(timing.text or "")
        found = script_text.find(text, cursor)
        if found < 0:
            found = script_text.find(text)
        if found >= 0:
            char_start = found
            char_end = found + len(text)
            cursor = char_end
        else:
            char_start = -1
            char_end = -1
        rows.append(
            {
                "text": text,
                "norm_text": normalize_eval_text(text),
                "char_start": char_start,
                "char_end": char_end,
                "start_sec": float(timing.start_sec),
                "end_sec": float(timing.end_sec),
            }
        )
    return rows


def find_tts_asr_insertion_timing(
    insertion: dict[str, Any],
    indexed_timings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not indexed_timings:
        return None
    for key in ("matched_text", "context"):
        timing = find_tts_asr_timing_by_text(str(insertion.get(key) or ""), indexed_timings)
        if timing:
            return timing
    char_start = int(coerce_float(insertion.get("char_start"), default=-1))
    char_end = int(coerce_float(insertion.get("char_end"), default=-1))
    if char_start >= 0:
        for row in indexed_timings:
            row_start = int(coerce_float(row.get("char_start"), default=-1))
            row_end = int(coerce_float(row.get("char_end"), default=-1))
            if row_start < 0 or row_end <= row_start:
                continue
            if row_start <= max(char_start, char_end - 1) <= row_end or (char_start <= row_end and char_end >= row_start):
                return row
    return None


def find_tts_asr_timing_by_text(
    text: str,
    indexed_timings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    needle = normalize_eval_text(text)
    if needle:
        best_row: dict[str, Any] | None = None
        best_score = 0.0
        for start_index in range(len(indexed_timings)):
            for window_size in range(1, 5):
                window = indexed_timings[start_index : start_index + window_size]
                if not window:
                    continue
                haystack = "".join(str(row.get("norm_text") or "") for row in window)
                if not haystack:
                    continue
                if needle in haystack:
                    return window[-1]
                if haystack in needle:
                    score = len(haystack) / max(1, len(needle))
                else:
                    score = lcs_coverage(needle, haystack)
                if score > best_score:
                    best_score = score
                    best_row = window[-1]
        if best_row and best_score >= 0.62:
            return best_row
    return None


def snap_original_audio_insertions_to_subtitle_boundaries(
    insertions: list[dict[str, Any]],
    *,
    subtitle_timings: list[RemixSubtitleTiming],
    pad_sec: float = 0.08,
) -> list[dict[str, Any]]:
    if not insertions or not subtitle_timings:
        return insertions
    snapped: list[dict[str, Any]] = []
    previous_at = 0.0
    for insertion in sorted(insertions, key=lambda item: coerce_float(item.get("insert_at_sec"), default=0.0)):
        item = dict(insertion)
        raw_at = coerce_float(item.get("insert_at_sec"), default=0.0)
        snapped_at = raw_at
        boundary_reason = "unchanged"
        matched_end = coerce_float(item.get("insert_tts_asr_matched_subtitle_end_sec"), default=-1.0)
        if (
            str(item.get("insert_tts_asr_alignment_source") or "") == "matched_script_text_to_tts_asr_subtitle"
            and matched_end >= 0.0
        ):
            snapped_at = matched_end + pad_sec
            boundary_reason = "after_matched_tts_asr_subtitle"
        else:
            for timing in subtitle_timings:
                start = float(timing.start_sec)
                end = float(timing.end_sec)
                if start - 0.001 <= raw_at <= end + 0.001:
                    snapped_at = end + pad_sec
                    boundary_reason = "after_overlapping_subtitle"
                    break
        snapped_at = max(previous_at, snapped_at)
        item["insert_at_sec"] = round(snapped_at, 3)
        item["insert_at_original_sec"] = round(raw_at, 3)
        item["insert_boundary_source"] = "tts_asr_subtitle_boundary"
        item["insert_boundary_reason"] = boundary_reason
        previous_at = snapped_at + 0.05
        snapped.append(item)
    return snapped


def extract_wav_window_24k(source: Path, output_path: Path, *, start_sec: float, duration_sec: float, force: bool) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.05, duration_sec):.3f}",
            "-vn",
            "-ar",
            str(NARRATION_SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def apply_original_audio_insertions(
    *,
    narration_path: Path,
    source_video: Path,
    output_path: Path,
    insertions: list[dict[str, Any]],
    work_dir: Path,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    if not insertions:
        copy_file(narration_path, output_path, force=True)
        return
    work_dir.mkdir(parents=True, exist_ok=True)
    narration_duration = probe_duration(narration_path)
    cursor = 0.0
    parts: list[Path] = []
    for insertion in sorted(insertions, key=lambda item: float(item.get("insert_at_sec") or 0.0)):
        insert_at = min(narration_duration, max(cursor, float(insertion.get("insert_at_sec") or 0.0)))
        if insert_at > cursor + 0.03:
            part_path = work_dir / f"tts_before_{len(parts) + 1:02d}.wav"
            extract_wav_window_24k(narration_path, part_path, start_sec=cursor, duration_sec=insert_at - cursor, force=force)
            parts.append(part_path)
        source_part = work_dir / f"source_audio_{int(insertion.get('index') or len(parts) + 1):02d}.wav"
        extract_wav_window_24k(
            source_video,
            source_part,
            start_sec=float(insertion.get("source_start_sec") or 0.0),
            duration_sec=float(insertion.get("duration_sec") or 0.0),
            force=force,
        )
        normalize_wav_rms_dbfs(source_part, target_dbfs=-18.0, peak_ceiling=0.92)
        parts.append(source_part)
        cursor = insert_at
    if narration_duration > cursor + 0.03:
        tail_path = work_dir / f"tts_after_{len(parts) + 1:02d}.wav"
        extract_wav_window_24k(narration_path, tail_path, start_sec=cursor, duration_sec=narration_duration - cursor, force=force)
        parts.append(tail_path)
    concat_wav_segments(parts, output_path, force=True)


def apply_packaging_audio_cues(
    input_path: Path,
    output_path: Path,
    *,
    audio_cues: list[dict[str, Any]],
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    if not audio_cues:
        copy_file(input_path, output_path, force=True)
        return
    audio = read_pcm16_mono(input_path)
    sample_rate = int(audio["sample_rate"])
    samples = [int(value) for value in audio["samples"]]
    for cue in audio_cues:
        start_index = int(max(0.0, coerce_float(cue.get("time_sec"), default=0.0)) * sample_rate)
        kind = str(cue.get("kind") or "")
        duration = 0.11 if kind == "pulse_tick" else 0.16
        base_freq = 720.0 if kind == "banner_whoosh" else 980.0
        second_freq = 1320.0 if kind == "keyword_pop" else 1040.0
        cue_samples = max(1, int(duration * sample_rate))
        for offset in range(cue_samples):
            index = start_index + offset
            if index >= len(samples):
                break
            t = offset / sample_rate
            attack = min(1.0, offset / max(1, int(0.018 * sample_rate)))
            release = max(0.0, 1.0 - offset / cue_samples)
            envelope = attack * (release**1.7)
            wave = math.sin(2 * math.pi * base_freq * t) + 0.55 * math.sin(2 * math.pi * second_freq * t)
            value = samples[index] + int(2500 * envelope * wave)
            samples[index] = max(-32768, min(32767, value))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_pcm16_mono(output_path, samples, sample_rate)


def normalize_wav_rms_dbfs(path: Path, *, target_dbfs: float, peak_ceiling: float) -> None:
    try:
        audio = read_pcm16_mono(path)
    except (wave.Error, OSError, RuntimeError):
        return
    samples = [int(value) for value in audio["samples"]]
    if not samples:
        return
    mean_square = sum((sample / 32768.0) ** 2 for sample in samples) / len(samples)
    if mean_square <= 0.0:
        return
    rms = math.sqrt(mean_square)
    target_rms = 10 ** (float(target_dbfs) / 20.0)
    gain = target_rms / max(rms, 1e-6)
    peak = max(abs(sample) for sample in samples) / 32768.0
    if peak > 0:
        gain = min(gain, max(0.1, float(peak_ceiling) / peak))
    if gain <= 1.02:
        return
    normalized = [max(-32768, min(32767, int(round(sample * gain)))) for sample in samples]
    write_pcm16_mono(path, normalized, int(audio["sample_rate"]))


def insertion_offset_at(time_sec: float, insertions: list[dict[str, Any]]) -> float:
    offset = 0.0
    for insertion in insertions:
        if time_sec >= float(insertion.get("insert_at_sec") or 0.0):
            offset += float(insertion.get("duration_sec") or 0.0)
    return offset


def shift_subtitle_timings_for_insertions(
    timings: list[RemixSubtitleTiming],
    insertions: list[dict[str, Any]],
) -> list[RemixSubtitleTiming]:
    if not insertions:
        return timings
    shifted: list[RemixSubtitleTiming] = []
    for item in timings:
        offset = insertion_offset_for_subtitle_event(item.start_sec, item.end_sec, insertions)
        shifted.append(
            RemixSubtitleTiming(
                text=item.text,
                start_sec=round(item.start_sec + offset, 3),
                end_sec=round(item.end_sec + offset, 3),
            )
        )
    return shifted


def insertion_offset_for_subtitle_event(start_sec: float, end_sec: float, insertions: list[dict[str, Any]]) -> float:
    offset = 0.0
    for insertion in insertions:
        insert_at = float(insertion.get("insert_at_sec") or 0.0)
        if start_sec >= insert_at or end_sec > insert_at:
            offset += float(insertion.get("duration_sec") or 0.0)
    return offset


def shift_asr_tokens_for_insertions(tokens: list[RemixAsrToken], insertions: list[dict[str, Any]]) -> list[RemixAsrToken]:
    if not insertions:
        return tokens
    return [
        RemixAsrToken(
            text=item.text,
            start_sec=round(item.start_sec + insertion_offset_at(item.start_sec, insertions), 3),
            end_sec=round(item.end_sec + insertion_offset_at(item.end_sec, insertions), 3),
        )
        for item in tokens
    ]


def synthesize_silence(output_path: Path, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def normalize_wav_for_edit(input_path: Path, output_path: Path, *, force: bool) -> None:
    if output_path.exists() and not force:
        return
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-ar",
            str(NARRATION_SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def trim_long_silences(
    input_path: Path,
    output_path: Path,
    *,
    max_internal_silence_sec: float,
    max_edge_silence_sec: float,
    force: bool,
) -> SilenceTrimStats:
    if output_path.exists() and not force:
        stats = estimate_silence_trim_stats(
            input_path,
            output_duration=probe_duration(output_path),
            max_internal_silence_sec=max_internal_silence_sec,
            max_edge_silence_sec=max_edge_silence_sec,
        )
        if stats is not None:
            return stats
        original_duration = probe_duration(input_path)
        output_duration = probe_duration(output_path)
        segments = detect_voice_segments(input_path)
        return SilenceTrimStats(
            original_duration_sec=round(original_duration, 3),
            output_duration_sec=round(output_duration, 3),
            trimmed_sec=round(max(0.0, original_duration - output_duration), 3),
            voice_segment_count=len(segments),
            max_removed_gap_sec=0.0,
        )

    audio = read_pcm16_mono(input_path)
    sample_rate = int(audio["sample_rate"])
    samples: list[int] = audio["samples"]
    if not samples:
        output_path.write_bytes(input_path.read_bytes())
        return SilenceTrimStats(0.0, 0.0, 0.0, 0, 0.0)

    voice_segments = detect_voice_segments_from_samples(samples, sample_rate)
    if not voice_segments:
        write_pcm16_mono(output_path, samples, sample_rate)
        duration = len(samples) / sample_rate
        return SilenceTrimStats(duration, duration, 0.0, 0, 0.0)

    output_samples: list[int] = []
    previous_end = 0
    max_removed_gap = 0.0
    for index, (start, end) in enumerate(voice_segments):
        gap_len = max(0, start - previous_end)
        keep_gap_sec = max_edge_silence_sec if index == 0 else max_internal_silence_sec
        keep_gap = min(gap_len, int(round(keep_gap_sec * sample_rate)))
        removed_gap = max(0, gap_len - keep_gap) / sample_rate
        max_removed_gap = max(max_removed_gap, removed_gap)
        if keep_gap > 0:
            output_samples.extend(samples[previous_end : previous_end + keep_gap])
        output_samples.extend(samples[start:end])
        previous_end = end

    tail_gap = max(0, len(samples) - previous_end)
    keep_tail = min(tail_gap, int(round(max_edge_silence_sec * sample_rate)))
    max_removed_gap = max(max_removed_gap, max(0, tail_gap - keep_tail) / sample_rate)
    if keep_tail > 0:
        output_samples.extend(samples[previous_end : previous_end + keep_tail])

    write_pcm16_mono(output_path, output_samples, sample_rate)
    original_duration = len(samples) / sample_rate
    output_duration = len(output_samples) / sample_rate
    return SilenceTrimStats(
        original_duration_sec=round(original_duration, 3),
        output_duration_sec=round(output_duration, 3),
        trimmed_sec=round(max(0.0, original_duration - output_duration), 3),
        voice_segment_count=len(voice_segments),
        max_removed_gap_sec=round(max_removed_gap, 3),
    )


def estimate_silence_trim_stats(
    input_path: Path,
    *,
    output_duration: float,
    max_internal_silence_sec: float,
    max_edge_silence_sec: float,
) -> SilenceTrimStats | None:
    try:
        audio = read_pcm16_mono(input_path)
    except (wave.Error, OSError, RuntimeError):
        return None
    sample_rate = int(audio["sample_rate"])
    samples: list[int] = audio["samples"]
    if not samples or sample_rate <= 0:
        return None
    voice_segments = detect_voice_segments_from_samples(samples, sample_rate)
    if not voice_segments:
        duration = len(samples) / sample_rate
        return SilenceTrimStats(duration, output_duration, max(0.0, duration - output_duration), 0, 0.0)
    previous_end = 0
    max_removed_gap = 0.0
    for index, (start, end) in enumerate(voice_segments):
        gap_len = max(0, start - previous_end)
        keep_gap_sec = max_edge_silence_sec if index == 0 else max_internal_silence_sec
        keep_gap = min(gap_len, int(round(keep_gap_sec * sample_rate)))
        max_removed_gap = max(max_removed_gap, max(0, gap_len - keep_gap) / sample_rate)
        previous_end = end
    tail_gap = max(0, len(samples) - previous_end)
    keep_tail = min(tail_gap, int(round(max_edge_silence_sec * sample_rate)))
    max_removed_gap = max(max_removed_gap, max(0, tail_gap - keep_tail) / sample_rate)
    original_duration = len(samples) / sample_rate
    return SilenceTrimStats(
        original_duration_sec=round(original_duration, 3),
        output_duration_sec=round(output_duration, 3),
        trimmed_sec=round(max(0.0, original_duration - output_duration), 3),
        voice_segment_count=len(voice_segments),
        max_removed_gap_sec=round(max_removed_gap, 3),
    )


def read_pcm16_mono(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)
    if channels != 1 or sample_width != 2:
        raise RuntimeError(f"Expected mono PCM16 wav after normalization: {path}")
    samples = [
        int.from_bytes(frames[index : index + 2], byteorder="little", signed=True)
        for index in range(0, len(frames) - 1, 2)
    ]
    return {"sample_rate": sample_rate, "samples": samples}


def write_pcm16_mono(path: Path, samples: list[int], sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frame_bytes = bytearray()
        for sample in samples:
            clamped = max(-32768, min(32767, int(sample)))
            frame_bytes.extend(clamped.to_bytes(2, byteorder="little", signed=True))
        wav.writeframes(bytes(frame_bytes))


def detect_voice_segments(path: Path) -> list[tuple[float, float]]:
    try:
        audio = read_pcm16_mono(path)
    except (wave.Error, OSError, RuntimeError):
        return []
    sample_rate = int(audio["sample_rate"])
    return [
        (start / sample_rate, end / sample_rate)
        for start, end in detect_voice_segments_from_samples(audio["samples"], sample_rate)
    ]


def detect_voice_segments_from_samples(samples: list[int], sample_rate: int) -> list[tuple[int, int]]:
    if not samples or sample_rate <= 0:
        return []
    frame_size = max(1, int(round(sample_rate * VOICE_FRAME_SEC)))
    frame_db: list[float] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        mean_square = sum((sample / 32768.0) ** 2 for sample in frame) / len(frame)
        if mean_square <= 0:
            frame_db.append(-120.0)
        else:
            frame_db.append(20.0 * math.log10(math.sqrt(mean_square)))
    if not frame_db:
        return []
    max_db = max(frame_db)
    threshold = max(-42.0, min(-30.0, max_db - 28.0))
    voiced = [value >= threshold for value in frame_db]
    voiced = close_short_boolean_gaps(voiced, max_gap_frames=max(1, int(round(0.12 / VOICE_FRAME_SEC))))
    voiced = drop_short_boolean_runs(voiced, min_run_frames=max(1, int(round(0.06 / VOICE_FRAME_SEC))))
    segments: list[tuple[int, int]] = []
    index = 0
    while index < len(voiced):
        if not voiced[index]:
            index += 1
            continue
        start_frame = index
        while index < len(voiced) and voiced[index]:
            index += 1
        end_frame = index
        start_sample = max(0, start_frame * frame_size)
        end_sample = min(len(samples), end_frame * frame_size)
        if end_sample > start_sample:
            segments.append((start_sample, end_sample))
    return segments


def close_short_boolean_gaps(values: list[bool], *, max_gap_frames: int) -> list[bool]:
    output = list(values)
    index = 0
    while index < len(output):
        if output[index]:
            index += 1
            continue
        start = index
        while index < len(output) and not output[index]:
            index += 1
        end = index
        if start > 0 and end < len(output) and end - start <= max_gap_frames:
            for fill_index in range(start, end):
                output[fill_index] = True
    return output


def drop_short_boolean_runs(values: list[bool], *, min_run_frames: int) -> list[bool]:
    output = list(values)
    index = 0
    while index < len(output):
        if not output[index]:
            index += 1
            continue
        start = index
        while index < len(output) and output[index]:
            index += 1
        end = index
        if end - start < min_run_frames:
            for fill_index in range(start, end):
                output[fill_index] = False
    return output


def time_compress_audio(input_path: Path, output_path: Path, *, speed_ratio: float, force: bool) -> None:
    if output_path.exists() and not force:
        return
    filters = atempo_filter_chain(speed_ratio)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            filters,
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )


def atempo_filter_chain(speed_ratio: float) -> str:
    ratio = max(0.5, float(speed_ratio or 1.0))
    filters: list[str] = []
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0
    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5
    filters.append(f"atempo={ratio:.5f}")
    return ",".join(filters)


def build_video_segments(
    source: Path,
    work_dir: Path,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
    *,
    episode: int,
    clip_anchor_starts: list[float] | None,
    force: bool,
) -> tuple[list[Path], list[float], list[float]]:
    segment_paths: list[Path] = []
    clip_spans = build_clip_spans(
        episode=episode,
        source_duration=source_duration,
        clip_count=clip_count,
        clip_duration=clip_duration,
        clip_anchor_starts=clip_anchor_starts,
    )
    clip_starts = [start for start, _duration in clip_spans]
    clip_durations = [duration for _start, duration in clip_spans]
    for index in range(clip_count):
        start = clip_starts[index]
        duration = clip_durations[index]
        output = work_dir / f"segment_{index + 1:02d}.mp4"
        segment_paths.append(output)
        if output.exists() and not force:
            continue
        run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration:.3f}",
                "-an",
                "-vf",
                (
                    f"{source_clean_crop_filter()},"
                    f"scale={REFERENCE_WIDTH}:{REFERENCE_HEIGHT}:flags=lanczos,"
                    f"fps={REFERENCE_FPS},setsar=1"
                ),
                "-c:v",
                "libx264",
                "-preset",
                REMIX_SEGMENT_X264_PRESET,
                "-tune",
                REMIX_X264_TUNE,
                "-crf",
                REMIX_SEGMENT_X264_CRF,
                "-pix_fmt",
                "yuv420p",
                str(output),
            ]
        )
    return segment_paths, clip_starts, clip_durations


def source_clean_crop_filter() -> str:
    # Source is 1080p in the SampleShow batch. This inner crop removes the top-right
    # platform mark and the burned-in bottom subtitles before our own packaging.
    return "crop=1440:810:180:50"


def build_clip_spans(
    *,
    episode: int,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
    clip_anchor_starts: list[float] | None = None,
) -> list[tuple[float, float]]:
    anchors = list(clip_anchor_starts or []) or episode_plot_anchor_starts(episode)
    start_guard = 22.0
    end_guard = 35.0
    latest_start = max(start_guard, source_duration - end_guard - clip_duration)
    if anchors:
        starts = [
            max(start_guard, min(float(value), latest_start))
            for value in anchors
            if start_guard <= float(value) <= latest_start + 0.1
        ]
    else:
        starts = []
    if not starts:
        starts = build_even_story_starts(
            source_duration=source_duration,
            clip_count=clip_count,
            clip_duration=clip_duration,
            start_guard=start_guard,
            end_guard=end_guard,
        )
    starts = fit_anchor_count(starts, clip_count=clip_count, source_duration=source_duration, clip_duration=clip_duration)
    durations = durations_until_next_anchor(
        starts,
        clip_duration=clip_duration,
        source_duration=source_duration,
        end_guard=end_guard,
    )
    return list(zip(starts, durations))


def episode_plot_anchor_starts(episode: int) -> list[float]:
    anchors_by_episode = {
        # E01 Dance Mode: chip incident -> asking/permission -> public dance choices -> final car reflection.
        1: [24.0, 48.0, 72.0, 98.0, 126.0, 158.0, 190.0, 224.0, 260.0, 304.0],
        # E02 Hammerbarn: want impulse -> store arrival -> toy house/play -> comparison -> buying/repair.
        2: [24.0, 54.0, 82.0, 112.0, 142.0, 172.0, 204.0, 238.0, 276.0, 324.0],
        # E03 Featherwand: exclusion setup -> heavy game -> birthday prep -> outside conflict -> resolution.
        3: [24.0, 52.0, 82.0, 112.0, 144.0, 178.0, 212.0, 248.0, 292.0, 336.0],
    }
    return list(anchors_by_episode.get(int(episode), []))


def build_even_story_starts(
    *,
    source_duration: float,
    clip_count: int,
    clip_duration: float,
    start_guard: float,
    end_guard: float,
) -> list[float]:
    first = min(max(0.0, start_guard), max(0.0, source_duration - clip_duration))
    latest = max(first, source_duration - end_guard - clip_duration)
    if clip_count <= 1:
        return [first]
    return [first + (latest - first) * index / max(1, clip_count - 1) for index in range(clip_count)]


def fit_anchor_count(
    starts: list[float],
    *,
    clip_count: int,
    source_duration: float,
    clip_duration: float,
) -> list[float]:
    ordered = sorted(dict.fromkeys(round(float(value), 3) for value in starts))
    if len(ordered) >= clip_count:
        if len(ordered) == clip_count:
            return ordered
        step = (len(ordered) - 1) / max(1, clip_count - 1)
        return [ordered[round(index * step)] for index in range(clip_count)]
    fallback = build_even_story_starts(
        source_duration=source_duration,
        clip_count=clip_count,
        clip_duration=clip_duration,
        start_guard=22.0,
        end_guard=35.0,
    )
    merged = sorted(dict.fromkeys([*ordered, *[round(value, 3) for value in fallback]]))
    return fit_anchor_count(merged, clip_count=clip_count, source_duration=source_duration, clip_duration=clip_duration)


def durations_until_next_anchor(
    starts: list[float],
    *,
    clip_duration: float,
    source_duration: float,
    end_guard: float,
) -> list[float]:
    durations: list[float] = []
    for index, start in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else source_duration - end_guard
        available = max(3.0, next_start - start)
        durations.append(max(3.0, min(clip_duration, available)))
    return durations


def concat_segments(segment_paths: list[Path], output_path: Path, *, force: bool) -> None:
    if output_path.exists() and not force:
        return
    list_path = output_path.with_suffix(".concat.txt")
    lines = [f"file '{path.resolve().as_posix()}'" for path in segment_paths]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(output_path)])


def apply_original_audio_visual_bridges(
    *,
    montage_path: Path,
    source_video: Path,
    output_path: Path,
    insertions: list[dict[str, Any]],
    work_dir: Path,
    duration_sec: float,
    force: bool,
) -> int:
    if output_path.exists() and not force:
        return len([item for item in insertions if coerce_float(item.get("duration_sec"), default=0.0) > 0.0])
    if not insertions:
        copy_file(montage_path, output_path, force=True)
        return 0
    work_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    cursor = 0.0
    bridge_count = 0
    cumulative_insert_offset = 0.0
    for insertion in sorted(insertions, key=lambda item: coerce_float(item.get("insert_at_sec"), default=0.0)):
        bridge_duration = max(0.0, coerce_float(insertion.get("duration_sec"), default=0.0))
        if bridge_duration <= 0.05:
            continue
        bridge_start = coerce_float(insertion.get("insert_at_sec"), default=0.0) + cumulative_insert_offset
        bridge_start = max(0.0, min(float(duration_sec), bridge_start))
        bridge_end = min(float(duration_sec), bridge_start + bridge_duration)
        cumulative_insert_offset += bridge_duration
        if bridge_end <= bridge_start + 0.05:
            continue
        if bridge_start > cursor + 0.04:
            base_part = work_dir / f"base_before_bridge_{len(parts) + 1:02d}.mp4"
            extract_montage_video_window(
                montage_path,
                base_part,
                start_sec=cursor,
                duration_sec=bridge_start - cursor,
                force=force,
            )
            parts.append(base_part)
        bridge_count += 1
        bridge_part = work_dir / f"source_visual_bridge_{bridge_count:02d}.mp4"
        extract_source_video_window(
            source_video,
            bridge_part,
            start_sec=coerce_float(insertion.get("source_start_sec"), default=0.0),
            duration_sec=bridge_end - bridge_start,
            force=force,
        )
        parts.append(bridge_part)
        cursor = bridge_end
    if float(duration_sec) > cursor + 0.04:
        tail_part = work_dir / f"base_after_bridge_{len(parts) + 1:02d}.mp4"
        extract_montage_video_window(
            montage_path,
            tail_part,
            start_sec=cursor,
            duration_sec=float(duration_sec) - cursor,
            force=force,
        )
        parts.append(tail_part)
    if not parts:
        copy_file(montage_path, output_path, force=True)
        return 0
    concat_segments(parts, output_path, force=True)
    return bridge_count


def extract_montage_video_window(
    source: Path,
    output_path: Path,
    *,
    start_sec: float,
    duration_sec: float,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.05, duration_sec):.3f}",
            "-an",
            "-vf",
            f"fps={REFERENCE_FPS},setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            REMIX_SEGMENT_X264_PRESET,
            "-tune",
            REMIX_X264_TUNE,
            "-crf",
            REMIX_SEGMENT_X264_CRF,
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    )


def extract_source_video_window(
    source: Path,
    output_path: Path,
    *,
    start_sec: float,
    duration_sec: float,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.05, duration_sec):.3f}",
            "-an",
            "-vf",
            (
                f"{source_clean_crop_filter()},"
                f"scale={REFERENCE_WIDTH}:{REFERENCE_HEIGHT}:flags=lanczos,"
                f"fps={REFERENCE_FPS},setsar=1"
            ),
            "-c:v",
            "libx264",
            "-preset",
            REMIX_SEGMENT_X264_PRESET,
            "-tune",
            REMIX_X264_TUNE,
            "-crf",
            REMIX_SEGMENT_X264_CRF,
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    )


def write_ass_subtitles(
    path: Path,
    *,
    title: str,
    question: str,
    text: str,
    duration: float,
    audio_path: Path | None,
    asr_aligned_timings: list[tuple[str, float, float]] | None,
    tts_segment_timings: list[TtsSegmentTiming] | None,
    episode: int,
    episode_title: str,
    subtitle_style_profile: str | None = None,
    semantic_packaging_plan: dict[str, Any] | None = None,
    original_audio_insertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timings = list(asr_aligned_timings or [])
    if timings:
        timings = normalize_subtitle_timings(timings, duration=duration)
    if not timings:
        timings = build_tts_segment_subtitle_timings(tts_segment_timings, duration=duration) if tts_segment_timings else []
    if not timings:
        chunks = split_subtitle_chunks(text)
        timings = build_speech_aligned_subtitle_timings(chunks, duration=duration, audio_path=audio_path)
    package = remix_caption_packager.build_caption_package(
        episode=episode,
        title=episode_title,
        question=question,
        subtitle_timings=timings,
        duration_sec=duration,
        width=REFERENCE_WIDTH,
        height=REFERENCE_HEIGHT,
        watermark=REFERENCE_WATERMARK,
        subtitle_style_profile=subtitle_style_profile,
        semantic_packaging_plan=semantic_packaging_plan,
        original_audio_insertions=original_audio_insertions,
    )
    path.write_text(package.ass_text, encoding="utf-8")
    metadata = package.to_metadata()
    metadata.update(
        {
            "subtitle_path": str(path),
            "title": title,
            "episode_title": episode_title,
            "question": question,
        }
    )
    return metadata


def build_speech_aligned_subtitle_timings(
    chunks: list[str],
    *,
    duration: float,
    audio_path: Path | None,
) -> list[tuple[str, float, float]]:
    if not chunks:
        return []
    speech_segments = detect_voice_segments(audio_path) if audio_path is not None else []
    speech_segments = [(max(0.0, start), min(duration, end)) for start, end in speech_segments if end > start]
    speech_segments = merge_time_segments(speech_segments, max_gap=0.18)
    if not speech_segments:
        return build_weighted_subtitle_timings(chunks, duration=duration)

    total_speech = sum(end - start for start, end in speech_segments)
    total_weight = sum(max(1, len(strip_punctuation(chunk))) for chunk in chunks)
    timings: list[tuple[str, float, float]] = []
    speech_cursor = 0.0
    for chunk in chunks:
        weight = max(1, len(strip_punctuation(chunk)))
        speech_span = total_speech * weight / max(total_weight, 1)
        start = time_at_speech_position(speech_segments, speech_cursor)
        end = time_at_speech_position(speech_segments, min(total_speech, speech_cursor + speech_span))
        speech_cursor += speech_span
        timings.append((chunk, max(0.0, start - 0.04), min(duration, end + 0.12)))
    return normalize_subtitle_timings(timings, duration=duration)


def build_tts_segment_subtitle_timings(
    tts_segments: list[TtsSegmentTiming] | None,
    *,
    duration: float,
) -> list[tuple[str, float, float]]:
    timings: list[tuple[str, float, float]] = []
    for segment in tts_segments or []:
        start = max(0.0, min(duration, segment.start_sec))
        end = max(start, min(duration, segment.end_sec))
        if end - start < 0.2 or not segment.text.strip():
            continue
        chunks = split_subtitle_chunks(segment.text)
        if not chunks:
            continue
        local_timings = build_weighted_subtitle_timings(chunks, duration=end - start)
        for chunk, local_start, local_end in local_timings:
            timings.append((chunk, start + local_start, min(end, start + local_end)))
    return normalize_subtitle_timings(timings, duration=duration)


def build_weighted_subtitle_timings(chunks: list[str], *, duration: float) -> list[tuple[str, float, float]]:
    total_weight = sum(max(1, len(strip_punctuation(chunk))) for chunk in chunks)
    cursor = 0.0
    timings: list[tuple[str, float, float]] = []
    for chunk in chunks:
        weight = max(1, len(strip_punctuation(chunk)))
        chunk_duration = max(1.4, duration * weight / max(total_weight, 1))
        start = cursor
        end = min(duration, cursor + chunk_duration)
        cursor = end
        timings.append((chunk, start, end))
        if cursor >= duration:
            break
    return normalize_subtitle_timings(timings, duration=duration)


def merge_time_segments(segments: list[tuple[float, float]], *, max_gap: float) -> list[tuple[float, float]]:
    if not segments:
        return []
    ordered = sorted(segments)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def time_at_speech_position(segments: list[tuple[float, float]], position: float) -> float:
    remaining = max(0.0, position)
    for start, end in segments:
        span = end - start
        if remaining <= span:
            return start + remaining
        remaining -= span
    return segments[-1][1]


def normalize_subtitle_timings(
    timings: list[tuple[str, float, float]],
    *,
    duration: float,
) -> list[tuple[str, float, float]]:
    normalized: list[tuple[str, float, float]] = []
    previous_end = 0.0
    for index, (chunk, start, end) in enumerate(timings):
        start = max(previous_end, min(duration, start))
        end = max(start + 0.9, min(duration, end))
        if index + 1 < len(timings):
            next_start = timings[index + 1][1]
            if end > next_start - 0.04:
                end = max(start + 0.75, next_start - 0.04)
        end = min(duration, end)
        if end > start:
            normalized.append((chunk, start, end))
            previous_end = end
    return normalized


def dynamic_subtitle_text(text: str, *, episode: int) -> str:
    wrapped = wrap_ass_text(text)
    escaped = escape_ass_text(wrapped)
    escaped = apply_inline_emphasis(escaped, episode=episode)
    return (
        r"{\an2\pos(960,935)\fad(70,110)"
        r"\fscx96\fscy96\t(0,160,\fscx107\fscy107)\t(160,320,\fscx100\fscy100)}"
        + escaped
    )


def apply_inline_emphasis(escaped_text: str, *, episode: int) -> str:
    keywords = subtitle_emphasis_keywords(episode)
    output = escaped_text
    for keyword in keywords:
        escaped_keyword = escape_ass_text(keyword)
        if escaped_keyword not in output:
            continue
        output = output.replace(
            escaped_keyword,
            rf"{{\c&H0000F7FF&\3c&HAA24005B&\fscx116\fscy116}}{escaped_keyword}{{\rDefault}}",
            1,
        )
    return output


def subtitle_emphasis_keywords(episode: int) -> list[str]:
    presets = {
        1: ["好吧", "不想要", "可以说不", "边界", "拒绝权", "我愿意"],
        2: ["想要", "贪心", "愿望", "规则", "先约定", "慢慢选"],
        3: ["没关系", "难过", "不舒服", "说出来", "感受", "被看见"],
    }
    return list(presets.get(int(episode), ["孩子", "感受", "规则", "可以"]))


def build_reference_style_packaging_events(episode: int, title: str, question: str, duration: float) -> list[str]:
    overlays = packaging_phrases_for_episode(episode, title, question)
    events = [
        ass_event(1, 0.0, duration, "Watermark", rf"{{\fad(300,300)}}{escape_ass_text(REFERENCE_WATERMARK)}"),
    ]
    if overlays["opening"]:
        events.append(
            ass_event(
                2,
                0.45,
                min(4.8, duration),
                "BigTitle",
                rf"{{\pos(120,150)\fad(120,220)\fscx72\fscy72\t(0,220,\fscx112\fscy112)\t(220,420,\fscx100\fscy100)\t(3200,4100,\frz-1)}}{escape_ass_text(overlays['opening'])}",
            )
        )
    for index, phrase in enumerate(overlays["banners"]):
        start = min(duration - 2.0, 26.0 + index * 38.0)
        if start <= 0:
            continue
        end = min(duration, start + 4.8)
        events.append(
            ass_event(
                2,
                start,
                end,
                "BlueBanner",
                r"{\p1\move(230,88,600,88,0,260)\c&HDD7A22&\alpha&H22&\bord0\shad0\fad(120,240)\t(0,220,\alpha&H08&)}m 0 0 l 760 0 l 704 108 l 0 108",
            )
        )
        events.append(
            ass_event(
                3,
                start,
                end,
                "BlueBanner",
                rf"{{\move(730,144,960,144,0,240)\fad(100,220)\fscx82\fscy82\t(0,220,\fscx106\fscy106)\t(220,380,\fscx100\fscy100)}}{escape_ass_text(phrase)}",
            )
        )
    for index, phrase in enumerate(overlays["keywords"]):
        start = min(duration - 1.8, 50.0 + index * 28.0)
        if start <= 0:
            continue
        style = "RedKeyword" if index % 2 == 0 else "Keyword"
        y = 348 if index % 2 == 0 else 416
        x = 1440 if index % 3 == 0 else 500
        enter_x = x + (180 if x < REFERENCE_WIDTH / 2 else -180)
        end = min(duration, start + 3.2)
        events.append(
            ass_event(
                3,
                start,
                end,
                style,
                rf"{{\p1\pos({x - 170},{y - 56})\c&HFFFFFF&\alpha&H55&\bord0\shad0\fad(80,160)\t(0,160,\alpha&H35&)}}m 0 0 l 340 0 l 340 112 l 0 112",
            )
        )
        events.append(
            ass_event(
                4,
                start,
                end,
                style,
                rf"{{\move({enter_x},{y},{x},{y},0,170)\fad(70,160)\frz{(-4 if index % 2 == 0 else 3)}\fscx62\fscy62\t(0,160,\fscx118\fscy118)\t(160,310,\fscx100\fscy100)\t(1900,2600,\fscx108\fscy108)}}{escape_ass_text(phrase)}",
            )
        )
    return events


def packaging_phrases_for_episode(episode: int, title: str, question: str) -> dict[str, Any]:
    presets: dict[int, dict[str, list[str] | str]] = {
        1: {
            "opening": "好吧不等于愿意",
            "banners": ["孩子边界感", "先停一下", "给孩子拒绝权"],
            "keywords": ["不想要", "可以说不", "我愿意"],
        },
        2: {
            "opening": "想要很多不等于贪心",
            "banners": ["购物欲望管理", "愿望可以被看见", "规则先说清"],
            "keywords": ["太想要", "先约定", "慢慢选"],
        },
        3: {
            "opening": "嘴上没关系不代表不难过",
            "banners": ["情绪表达练习", "别急着劝大度", "先承认感受"],
            "keywords": ["不舒服", "说出来", "被看见"],
        },
    }
    if episode in presets:
        item = presets[episode]
        return {
            "opening": str(item["opening"]),
            "banners": list(item["banners"]),
            "keywords": list(item["keywords"]),
        }
    compact_question = strip_punctuation(question)
    return {
        "opening": compact_question[:10] or title,
        "banners": ["看见孩子", "先共情", "再立规则"],
        "keywords": ["别急", "说出来", "慢慢来"],
    }


def ass_event(layer: int, start: float, end: float, style: str, text: str) -> str:
    return f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"


def split_subtitle_chunks(text: str) -> list[str]:
    sentences = re.split(r"(?<=[。！？?])\s*|\n+", text)
    chunks: list[str] = []
    current = ""
    for sentence in [item.strip() for item in sentences if item.strip()]:
        if len(sentence) > 34:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(split_long_subtitle_text(sentence, max_chars=32))
            continue
        candidate = (current + sentence).strip()
        if current and len(candidate) > 34:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_long_subtitle_text(text: str, *, max_chars: int) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while len(remaining) > max_chars:
        split_at = max(
            remaining.rfind("，", 0, max_chars + 1),
            remaining.rfind("、", 0, max_chars + 1),
            remaining.rfind(" ", 0, max_chars + 1),
        )
        if split_at < max_chars // 2:
            split_at = max_chars
        chunk = remaining[:split_at].strip(" ，、")
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip(" ，、")
    if remaining:
        chunks.append(remaining)
    return chunks


def quote_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parsed.path, safe="/%")
    query = urllib.parse.quote(parsed.query, safe="=&;%")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def mux_final(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    *,
    duration: float,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        return
    subtitle_filter_path = subtitle_path.as_posix().replace(":", r"\:")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-vf",
        f"subtitles='{subtitle_filter_path}'",
        "-r",
        str(REFERENCE_FPS),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        REMIX_FINAL_X264_PRESET,
        "-tune",
        REMIX_X264_TUNE,
        "-crf",
        REMIX_FINAL_X264_CRF,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
    ]
    if duration > 0:
        command.extend(["-t", f"{duration:.3f}"])
    command.extend(["-shortest", str(output_path)])
    run(command)


def extract_review_frames(
    *,
    episode: int,
    title: str,
    output_path: Path,
    output_duration: float,
    review_dir: Path,
    manifest_path: Path,
    force: bool,
) -> dict[str, Any]:
    timestamps = remix_review_frames.review_frame_timestamps(output_duration, min_count=5)
    review_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for index, timestamp in enumerate(timestamps):
        frame_path = review_dir / f"s02e{episode:02d}_review_{index + 1:02d}_{int(round(timestamp * 1000)):06d}ms.jpg"
        frame_paths.append(frame_path)
        if frame_path.exists() and not force:
            continue
        run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(output_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ]
        )
    manifest = remix_review_frames.build_review_frames_manifest(
        episode=episode,
        title=title,
        video_path=output_path,
        review_dir=review_dir,
        frame_paths=frame_paths,
        timestamps_sec=timestamps,
        crop_evidence={
            "final_resolution": {"width": REFERENCE_WIDTH, "height": REFERENCE_HEIGHT},
            "source_clean_crop_filter": source_clean_crop_filter(),
            "purpose": "verify source platform logo and burned-in bottom subtitle area are removed or de-emphasized after crop/scale",
        },
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def derive_remix_cover_from_review_frames(
    *,
    review_frames_manifest: dict[str, Any],
    cover_path: Path,
    force: bool,
) -> Path | None:
    frames = [
        item
        for item in (review_frames_manifest.get("frames") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    if not frames:
        return None
    selected = frames[len(frames) // 2]
    source_path = Path(str(selected.get("path") or "")).expanduser()
    if not source_path.is_file():
        return None
    if cover_path.exists() and not force:
        return cover_path
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, cover_path)
    return cover_path


def probe_duration(path: Path) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def output_has_audio_stream(path: Path) -> bool:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    return "audio" in result.stdout.lower()


def copy_file(input_path: Path, output_path: Path, *, force: bool) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, output_path)


def count_ass_dialogue_events(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:"))
    except OSError:
        return 0


def build_topic_plan_payload(
    *,
    script: EpisodeScript,
    script_text: str,
    clip_starts: list[float],
    clip_durations: list[float],
    source_asr_index: SourceAsrIndex,
) -> dict[str, Any]:
    return remix_script_topics.build_topic_plan_payload(
        episode=script.episode,
        title=script.title,
        question=script.question,
        script_path=script.script_path,
        script_text=script_text,
        clip_starts=clip_starts,
        clip_durations=clip_durations,
        source_asr_index_path=source_asr_index.evidence_path,
    )


def build_scene_index_file(
    *,
    video: Path,
    output_path: Path,
    source_duration: float,
    args: argparse.Namespace,
) -> tuple[str, list[SceneSpan]]:
    if output_path.exists() and not args.force:
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            scenes = [
                SceneSpan(
                    start_sec=coerce_float(item.get("start_sec"), default=0.0),
                    end_sec=coerce_float(item.get("end_sec"), default=0.0),
                    score=coerce_float(item.get("score"), default=0.0),
                    source=str(item.get("source") or "detected"),
                )
                for item in payload.get("scenes") or []
                if isinstance(item, dict)
            ]
            cached_status = str(payload.get("status") or "cached")
            if scenes and cached_status == "detected":
                return str(payload.get("status") or "cached"), scenes
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    status, scenes = remix_scene_index.detect_scene_spans(
        video,
        source_duration_sec=source_duration,
        threshold=float(args.scene_threshold),
        frame_skip=int(args.scene_frame_skip),
        max_runtime_sec=float(args.scene_detect_timeout_sec) if args.scene_detect_timeout_sec else None,
    )
    payload = remix_scene_index.build_scene_index_payload(
        video_path=video,
        source_duration_sec=source_duration,
        status=status,
        scenes=scenes,
        threshold=float(args.scene_threshold),
        frame_skip=int(args.scene_frame_skip),
        max_runtime_sec=float(args.scene_detect_timeout_sec) if args.scene_detect_timeout_sec else None,
    )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return status, scenes


def build_topic_chunks(script_text: str, *, target_count: int) -> list[str]:
    return remix_script_topics.build_topic_chunks(script_text, target_count=target_count)


def infer_topic_title(text: str, *, fallback: str) -> str:
    return remix_script_topics.infer_topic_title(text, fallback=fallback)


def infer_visual_intent(script: EpisodeScript, text: str) -> str:
    return remix_script_topics.infer_visual_intent(episode_title=script.title, text=text)


def build_edit_plan_payload(
    *,
    script: EpisodeScript,
    video: Path,
    concat_path: Path,
    output_path: Path,
    topic_plan_path: Path,
    scene_index_path: Path,
    scene_spans: list[SceneSpan],
    source_asr_index: SourceAsrIndex,
    clip_starts: list[float],
    clip_durations: list[float],
    segment_paths: list[Path],
    subtitle_path: Path,
    narration_path: Path,
) -> dict[str, Any]:
    return remix_edit_plan.build_edit_plan_payload(
        episode=script.episode,
        title=script.title,
        source_video=video,
        topic_plan_path=topic_plan_path,
        scene_index_path=scene_index_path,
        source_asr_index_path=source_asr_index.evidence_path,
        narration_path=narration_path,
        subtitle_path=subtitle_path,
        montage_path=concat_path,
        output_path=output_path,
        clip_starts=clip_starts,
        clip_durations=clip_durations,
        segment_paths=segment_paths,
        scene_spans=scene_spans,
        video_transform={
            "crop": source_clean_crop_filter(),
            "width": REFERENCE_WIDTH,
            "height": REFERENCE_HEIGHT,
            "fps": REFERENCE_FPS,
        },
    )


def build_qa_report_payload(report: SampleReport) -> dict[str, Any]:
    report_payload = asdict(report)
    gate_result = remix_qa.evaluate_episode_report(report_payload)
    return {
        "schema": "roughcut.remix.qa_report.v1",
        "episode": report.episode,
        "title": report.title,
        "status": gate_result.status,
        "passed": gate_result.passed,
        "metrics": gate_result.metrics,
        "issues": [asdict(issue) for issue in gate_result.issues],
        "inputs": {
            "output_path": report.output_path,
            "narration_path": report.render_narration_path,
            "tts_request_metadata_path": report.tts_request_metadata_path,
            "subtitle_path": report.subtitle_path,
            "caption_package_path": report.caption_package_path,
            "semantic_packaging_plan_path": report.semantic_packaging_plan_path,
            "original_audio_intent_analysis_path": report.original_audio_intent_analysis_path,
            "original_audio_source_mapping_path": report.original_audio_source_mapping_path,
            "original_audio_insertions_path": report.original_audio_insertions_path,
            "topic_plan_path": report.topic_plan_path,
            "edit_plan_path": report.edit_plan_path,
            "review_frames_manifest_path": report.review_frames_manifest_path,
            "scene_index_path": report.scene_index_path,
            "tts_asr_evidence_path": report.tts_asr_evidence_path,
            "source_asr_index_path": report.source_asr_index_path,
        },
    }


def probe_wav_rms_dbfs(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = max(1, wav.getnchannels())
            sample_width = wav.getsampwidth()
            frame_count = wav.getnframes()
            if frame_count <= 0 or sample_width not in {1, 2, 3, 4}:
                return None
            frames = wav.readframes(frame_count)
    except (wave.Error, OSError):
        return None
    if not frames:
        return None

    max_abs = float((1 << (sample_width * 8 - 1)) - 1)
    if max_abs <= 0:
        return None
    total_square = 0.0
    sample_count = 0
    step = sample_width * channels
    for index in range(0, len(frames) - step + 1, step):
        for channel in range(channels):
            start = index + channel * sample_width
            raw = frames[start : start + sample_width]
            if sample_width == 1:
                sample = raw[0] - 128
            else:
                sample = int.from_bytes(raw, byteorder="little", signed=True)
            normalized = max(-1.0, min(1.0, sample / max_abs))
            total_square += normalized * normalized
            sample_count += 1
    if sample_count <= 0:
        return None
    rms = math.sqrt(total_square / sample_count)
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(rms)


def render_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# SampleShow Parenting Remix Sample Report",
        "",
        f"- created_at: {payload.get('created_at')}",
        f"- source_root: `{payload.get('source_root')}`",
        f"- creator_profile: `{(payload.get('creator_profile') or {}).get('name')}` (`{(payload.get('creator_profile') or {}).get('id')}`)",
        f"- sample_count: {payload.get('summary', {}).get('sample_count')}",
        f"- success_count: {payload.get('summary', {}).get('success_count')}",
        "",
        "## Build Method",
        "",
        "- 文案按集数解析为育儿观点口播脚本。",
        "- 每集原片按文案主题和剧情重点定位画面段落，到下一个主题点前保持连续播放。",
        "- 原片画面先放大裁切，去掉平台 logo 区和原片底部字幕区，再输出成片画幅。",
        "- MOSS TTS 生成旁白音轨后压缩过长气口；当 LLM 判定文案正在引用原片台词、对话或关键剧情证据时，短暂停解说插入 2-4 秒原片原声。",
        "- TTS 成音后用 Qwen3-ASR + ForcedAligner 重新识别最终旁白，字幕显示沿用原文案，时间戳使用 TTS-ASR 证据。",
        "- 原片画面定位单独用 Qwen3-ASR 识别剧情锚点窗口，作为主题/剧情点选段证据；它不参与字幕时间戳。",
        "- 仅在显式 fallback 模式下才回退到 MOSS live_segments 或音频活动区间；正式样片默认要求 TTS-ASR 质量门通过。",
        f"- 最终成片输出为 {REFERENCE_WIDTH}x{REFERENCE_HEIGHT}、{REFERENCE_FPS}fps H.264/AAC MP4。",
        "",
    ]
    for item in payload.get("reports", []):
        lines.extend(
            [
                f"## S02E{int(item['episode']):02d} {item['title']}",
                f"- status: {item['build_status']}",
                f"- output: `{item['output_path']}`",
                f"- source_video: `{item['source_video']}`",
        f"- creator_profile_name: {item.get('creator_profile_name')}",
        f"- creator_profile_path: `{item.get('creator_profile_path')}`",
        f"- render_narration_path: `{item.get('render_narration_path')}`",
        f"- tts_request_metadata_path: `{item.get('tts_request_metadata_path')}`",
        f"- tts_provider: {item.get('tts_provider')}",
        f"- tts_mode: {item.get('tts_mode')}",
        f"- tts_reference_history_path: `{item.get('tts_reference_history_path')}`",
        f"- tts_voice_signature: `{item.get('tts_voice_signature')}`",
        f"- topic_plan_path: `{item.get('topic_plan_path')}`",
        f"- edit_plan_path: `{item.get('edit_plan_path')}`",
        f"- qa_report_path: `{item.get('qa_report_path')}`",
        f"- caption_package_path: `{item.get('caption_package_path')}`",
        f"- semantic_packaging_plan_path: `{item.get('semantic_packaging_plan_path')}`",
        f"- review_frames_manifest_path: `{item.get('review_frames_manifest_path')}`",
        f"- scene_index_path: `{item.get('scene_index_path')}`",
        f"- script_chars: {item['script_chars']}",
        f"- source_duration_sec: {item['source_duration_sec']}",
        f"- narration_duration_sec: {item['narration_duration_sec']}",
        f"- render_narration_duration_sec: {item.get('render_narration_duration_sec')}",
        f"- output_duration_sec: {item['output_duration_sec']}",
        f"- narration_rms_dbfs: {item.get('narration_rms_dbfs')}",
        f"- silence_trimmed_sec: {item.get('silence_trimmed_sec')}",
        f"- tts_segment_count: {item.get('tts_segment_count')}",
        f"- original_audio_intent_analysis_path: `{item.get('original_audio_intent_analysis_path')}`",
        f"- original_audio_intent_source: {item.get('original_audio_intent_source')}",
        f"- original_audio_intent_decision: {item.get('original_audio_intent_decision')}",
        f"- original_audio_intent_confidence: {item.get('original_audio_intent_confidence')}",
        f"- original_audio_intent_llm_reviewed: {item.get('original_audio_intent_llm_reviewed')}",
        f"- original_audio_source_mapping_path: `{item.get('original_audio_source_mapping_path')}`",
        f"- original_audio_source_mapping_source: {item.get('original_audio_source_mapping_source')}",
        f"- original_audio_source_mapping_llm_reviewed: {item.get('original_audio_source_mapping_llm_reviewed')}",
        f"- original_audio_reference_intent_count: {item.get('original_audio_reference_intent_count')}",
        f"- original_audio_insert_count: {item.get('original_audio_insert_count')}",
        f"- original_audio_insert_total_duration_sec: {item.get('original_audio_insert_total_duration_sec')}",
        f"- original_audio_insertions_path: `{item.get('original_audio_insertions_path')}`",
        f"- original_audio_visual_bridge_count: {item.get('original_audio_visual_bridge_count')}",
        f"- subtitle_alignment_source: {item.get('subtitle_alignment_source')}",
        f"- subtitle_event_count: {item.get('subtitle_event_count')}",
        f"- subtitle_text_coverage: {item.get('subtitle_text_coverage')}",
        f"- subtitle_style_profile: {item.get('subtitle_style_profile')}",
        f"- packaging_framework: {item.get('packaging_framework')}",
        f"- hyperframes_enabled: {item.get('hyperframes_enabled')}",
        f"- hyperframes_plan_schema: {item.get('hyperframes_plan_schema')}",
        f"- hyperframes_element_count: {item.get('hyperframes_element_count')}",
        f"- hyperframes_effect_count: {item.get('hyperframes_effect_count')}",
        f"- semantic_packaging_source: {item.get('semantic_packaging_source')}",
        f"- semantic_packaging_llm_reviewed: {item.get('semantic_packaging_llm_reviewed')}",
        f"- max_subtitle_lines_per_event: {item.get('max_subtitle_lines_per_event')}",
        f"- max_subtitle_line_chars: {item.get('max_subtitle_line_chars')}",
        f"- subtitle_timing_alignment_status: {item.get('subtitle_timing_alignment_status')}",
        f"- subtitle_timing_unmatched_count: {item.get('subtitle_timing_unmatched_count')}",
        f"- subtitle_timing_bad_drift_count: {item.get('subtitle_timing_bad_drift_count')}",
        f"- subtitle_timing_max_abs_start_drift_sec: {item.get('subtitle_timing_max_abs_start_drift_sec')}",
        f"- subtitle_timing_max_abs_end_drift_sec: {item.get('subtitle_timing_max_abs_end_drift_sec')}",
        f"- subtitle_timing_audit_path: `{item.get('subtitle_timing_audit_path')}`",
        f"- tts_asr_status: {item.get('tts_asr_status')}",
        f"- tts_asr_coverage: {item.get('tts_asr_coverage')}",
        f"- tts_asr_token_count: {item.get('tts_asr_token_count')}",
        f"- tts_asr_evidence_path: `{item.get('tts_asr_evidence_path')}`",
        f"- source_asr_status: {item.get('source_asr_status')}",
        f"- source_asr_anchor_count: {item.get('source_asr_anchor_count')}",
        f"- source_asr_selected_starts: {item.get('source_asr_selected_starts')}",
        f"- source_asr_index_path: `{item.get('source_asr_index_path')}`",
        f"- scene_index_status: {item.get('scene_index_status')}",
        f"- scene_count: {item.get('scene_count')}",
        f"- packaging_event_count: {item.get('packaging_event_count')}",
        f"- theme_banner_count: {item.get('theme_banner_count')}",
        f"- keyword_sticker_count: {item.get('keyword_sticker_count')}",
        f"- watermark_event_count: {item.get('watermark_event_count')}",
        f"- emphasis_keyword_count: {item.get('emphasis_keyword_count')}",
        f"- animated_subtitle_event_count: {item.get('animated_subtitle_event_count')}",
        f"- animated_packaging_event_count: {item.get('animated_packaging_event_count')}",
        f"- motion_effect_count: {item.get('motion_effect_count')}",
        f"- highlight_effect_count: {item.get('highlight_effect_count')}",
        f"- packaging_audio_cue_count: {item.get('packaging_audio_cue_count')}",
        f"- source_bridge_count: {item.get('source_bridge_count')}",
        f"- review_frame_count: {item.get('review_frame_count')}",
        f"- qa_status: {item.get('qa_status')}",
        f"- qa_issue_count: {item.get('qa_issue_count')}",
                f"- clip_count: {item['clip_count']}",
                f"- tts_status: {item['tts_status']}",
                "- notes: " + " / ".join(item.get("notes") or []),
                "",
            ]
        )
    return "\n".join(lines)


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    if command and Path(command[0]).name.lower() == "ffmpeg":
        command = [command[0], "-hide_banner", "-loglevel", "error", *command[1:]]
    return subprocess.run(
        command,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def safe_name(value: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.U)
    return normalized.strip("_") or "episode"


def strip_punctuation(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:“”\"'《》]+", "", value)


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:d}:{minutes:02d}:{secs:05.2f}"


def wrap_ass_text(text: str, line_chars: int = 18) -> str:
    stripped = text.strip()
    if len(stripped) <= line_chars:
        return stripped
    lines = [stripped[index : index + line_chars] for index in range(0, len(stripped), line_chars)]
    return r"\N".join(lines[:2])


def escape_ass_text(text: str) -> str:
    return text.replace("{", r"\{").replace("}", r"\}")


if __name__ == "__main__":
    main()

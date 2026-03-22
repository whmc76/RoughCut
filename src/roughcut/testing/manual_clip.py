from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from roughcut.edit.decisions import build_edit_decision
from roughcut.edit.render_plan import build_render_plan
from roughcut.media.audio import extract_audio
from roughcut.media.output import build_output_name, extract_cover_frame, write_srt_file
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.providers.factory import get_transcription_provider
from roughcut.review.content_profile import infer_content_profile, polish_subtitle_items
from roughcut.speech.postprocess import split_into_subtitles


@dataclass
class RuntimeSubtitleItem:
    item_index: int
    start_time: float
    end_time: float
    text_raw: str
    text_norm: str
    text_final: str | None = None


async def run_manual_clip_test(
    source: Path,
    *,
    language: str = "zh-CN",
    channel_profile: str | None = None,
    sample_seconds: int = 90,
) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)

    output_root = Path("output/test/manual-tests")
    output_root.mkdir(parents=True, exist_ok=True)
    run_name = f"{build_output_name(source.name)}_manual_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        working_source = await _build_sample_clip(source, tmpdir / "sample.mp4", sample_seconds)
        audio_path = tmpdir / "audio.wav"
        await extract_audio(working_source, audio_path)

        transcript = await get_transcription_provider().transcribe(audio_path, language=language)
        db_like_segments = [
            SimpleNamespace(
                text=seg.text,
                start_time=seg.start,
                end_time=seg.end,
                words_json=[{"word": w.word, "start": w.start, "end": w.end} for w in seg.words],
            )
            for seg in transcript.segments
        ]
        entries = split_into_subtitles(db_like_segments)
        subtitle_items = [
            RuntimeSubtitleItem(
                item_index=entry.index,
                start_time=entry.start,
                end_time=entry.end,
                text_raw=entry.text_raw,
                text_norm=entry.text_norm,
            )
            for entry in entries
        ]
        subtitle_dicts = [_subtitle_dict(item) for item in subtitle_items]

        content_profile = await infer_content_profile(
            source_path=working_source,
            source_name=source.name,
            subtitle_items=subtitle_dicts,
            channel_profile=channel_profile,
        )
        polished_count = await polish_subtitle_items(
            subtitle_items,
            content_profile=content_profile,
            glossary_terms=[],
        )
        polished_subtitle_dicts = [_subtitle_dict(item) for item in subtitle_items]

        silences = detect_silence(audio_path)
        decision = build_edit_decision(
            source_path=str(working_source),
            duration=transcript.duration,
            silence_segments=silences,
            subtitle_items=polished_subtitle_dicts,
        )
        editorial_timeline = decision.to_dict()
        workflow_preset = content_profile.get("preset_name") or channel_profile or "unboxing_default"
        render_plan = build_render_plan(uuid.uuid4(), workflow_preset=workflow_preset)

        output_mp4 = run_dir / f"{run_name}.mp4"
        await render_video(
            source_path=working_source,
            render_plan=render_plan,
            editorial_timeline=editorial_timeline,
            output_path=output_mp4,
            subtitle_items=polished_subtitle_dicts,
            debug_dir=run_dir / "render-debug",
        )

        keep_segments = [seg for seg in editorial_timeline.get("segments", []) if seg.get("type") == "keep"]
        remapped = remap_subtitles_to_timeline(polished_subtitle_dicts, keep_segments)
        srt_path = run_dir / f"{run_name}.srt"
        write_srt_file(remapped, srt_path)

        cover_path = run_dir / f"{run_name}_cover.jpg"
        cover_variants = await extract_cover_frame(
            output_mp4,
            cover_path,
            seek_sec=min(8.0, transcript.duration * 0.1 if transcript.duration else 5.0),
            content_profile=content_profile,
        )

        report = {
            "source": str(source),
            "sample_source": str(working_source),
            "language": language,
            "channel_profile": channel_profile,
            "transcript_segments": len(transcript.segments),
            "subtitle_items": len(subtitle_items),
            "polished_count": polished_count,
            "silence_segments": len(silences),
            "workflow_preset": workflow_preset,
            "content_profile": content_profile,
            "output": {
                "run_dir": str(run_dir),
                "video": str(output_mp4),
                "srt": str(srt_path),
                "cover": str(cover_path),
                "cover_variants": [str(path) for path in cover_variants],
            },
        }
        report_path = run_dir / "manual_clip_report.json"
        report["output"]["report"] = str(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report


def _subtitle_dict(item: RuntimeSubtitleItem) -> dict[str, Any]:
    return {
        "index": item.item_index,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "text_raw": item.text_raw,
        "text_norm": item.text_norm,
        "text_final": item.text_final,
    }


async def _build_sample_clip(source: Path, target: Path, sample_seconds: int) -> Path:
    duration = _probe_duration(source)
    if duration <= 0 or duration <= sample_seconds:
        return source

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-t",
                str(sample_seconds),
                "-c",
                "copy",
                str(target),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"sample clip extraction failed: {result.stderr[-1000:]}")
    return target


def _probe_duration(source: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(source)],
        capture_output=True,
        timeout=20,
    )
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return 0.0
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)

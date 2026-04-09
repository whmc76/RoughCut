from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from roughcut.db.models import Artifact, Job, SubtitleItem
from roughcut.db.session import get_session_factory
from roughcut.edit.decisions import build_edit_decision
from roughcut.edit.render_plan import build_render_plan
from roughcut.media.audio import extract_audio
from roughcut.media.output import write_srt_file
from roughcut.media.probe import probe
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.storage.s3 import get_storage


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--workflow-preset", default="unboxing_standard")
    args = parser.parse_args()

    async with get_session_factory()() as session:
        job = (await session.execute(select(Job).where(Job.id == args.job_id))).scalar_one()
        content_profile = (
            await session.execute(
                select(Artifact.data_json)
                .where(
                    Artifact.job_id == args.job_id,
                    Artifact.artifact_type.in_(["content_profile_final", "content_profile"]),
                )
                .order_by(Artifact.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or {}
        subtitle_rows = (
            await session.execute(
                select(
                    SubtitleItem.item_index,
                    SubtitleItem.start_time,
                    SubtitleItem.end_time,
                    SubtitleItem.text_raw,
                    SubtitleItem.text_norm,
                    SubtitleItem.text_final,
                )
                .where(
                    SubtitleItem.job_id == args.job_id,
                    SubtitleItem.start_time < args.seconds,
                )
                .order_by(SubtitleItem.item_index.asc())
            )
        ).all()

    source_path = get_storage().resolve_path(job.source_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    output_root = Path(str(job.output_dir or "output")).expanduser()
    stem = "20260406_赫斯俊_与船长联名推出的机能双肩包黑白双色对比开箱"
    if source_path.stem and source_path.stem not in {"IMG_0041", stem}:
        stem = source_path.stem
    output_dir = output_root / stem
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"recut_first{int(args.seconds)}s_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    sample_path = run_dir / f"source_first{int(args.seconds)}s.mp4"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-t",
        str(args.seconds),
        "-c",
        "copy",
        str(sample_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-2000:])

    audio_path = run_dir / f"source_first{int(args.seconds)}s.wav"
    await extract_audio(sample_path, audio_path)
    silences = detect_silence(audio_path)

    subtitle_items: list[dict[str, object]] = []
    for item_index, start_time, end_time, text_raw, text_norm, text_final in subtitle_rows:
        start = float(start_time or 0.0)
        end = min(float(end_time or 0.0), float(args.seconds))
        if end <= start:
            continue
        subtitle_items.append(
            {
                "index": int(item_index),
                "start_time": start,
                "end_time": end,
                "text_raw": text_raw,
                "text_norm": text_norm,
                "text_final": text_final,
            }
        )

    media_meta = await probe(sample_path)
    duration = float(media_meta.duration or args.seconds)
    decision = build_edit_decision(
        source_path=str(sample_path),
        duration=duration,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile=content_profile if isinstance(content_profile, dict) else {},
    )
    timeline = decision.to_dict()
    keep_segments = [segment for segment in timeline.get("segments", []) if segment.get("type") == "keep"]
    remapped_subtitles = remap_subtitles_to_timeline(subtitle_items, keep_segments)

    render_plan = build_render_plan(
        editorial_timeline_id=uuid.uuid4(),
        workflow_preset=args.workflow_preset,
        subtitle_style="bold_yellow_outline",
        subtitle_motion_style="motion_static",
    )

    output_video = run_dir / f"{stem}_横版_成片_前{int(args.seconds // 60)}分钟重剪.mp4"
    await render_video(
        source_path=sample_path,
        render_plan=render_plan,
        editorial_timeline=timeline,
        output_path=output_video,
        subtitle_items=remapped_subtitles,
        debug_dir=run_dir / "render-debug",
    )

    output_srt = run_dir / f"{stem}_横版_成片_前{int(args.seconds // 60)}分钟重剪.srt"
    write_srt_file(remapped_subtitles, output_srt)

    report = {
        "job_id": args.job_id,
        "source_path": str(source_path),
        "sample_path": str(sample_path),
        "duration": duration,
        "subtitle_items": len(subtitle_items),
        "silence_segments": len(silences),
        "keep_segments": len(keep_segments),
        "remove_segments": len([segment for segment in timeline.get("segments", []) if segment.get("type") == "remove"]),
        "output_video": str(output_video),
        "output_srt": str(output_srt),
        "run_dir": str(run_dir),
        "segments": timeline.get("segments", []),
    }
    report_path = run_dir / "recut_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

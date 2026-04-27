"""OTIO (OpenTimelineIO) export for editorial timelines."""
from __future__ import annotations

import json
from pathlib import Path


def export_to_otio(editorial_timeline: dict, output_path: Path | None = None) -> str:
    """
    Convert editorial timeline dict to OTIO format.
    Returns OTIO JSON string.
    """
    source = editorial_timeline.get("source", "unknown.mp4")
    segments = editorial_timeline.get("segments", [])
    tracks = editorial_timeline.get("tracks") if isinstance(editorial_timeline.get("tracks"), list) else []
    output_items = []
    for track_data in tracks:
        if not isinstance(track_data, dict):
            continue
        if str(track_data.get("name") or "") == "output_video":
            output_items = [item for item in list(track_data.get("items") or []) if isinstance(item, dict)]
            break

    try:
        import opentimelineio as otio
    except ImportError:
        otio_str = _fallback_otio_json(
            source=str(source),
            segments=segments,
            output_items=output_items,
        )
        if output_path:
            output_path.write_text(otio_str, encoding="utf-8")
        return otio_str

    timeline = otio.schema.Timeline(name=Path(source).stem)
    track = otio.schema.Track(name="Video")

    media_ref = otio.schema.ExternalReference(target_url=source)

    if output_items:
        for item in output_items:
            if str(item.get("type") or "") != "clip":
                continue
            source_range = item.get("source_range") if isinstance(item.get("source_range"), dict) else {}
            start = float(source_range.get("start", 0.0) or 0.0)
            duration = float(source_range.get("duration", 0.0) or 0.0)
            if duration <= 0.0:
                continue
            media_reference = item.get("media_reference") if isinstance(item.get("media_reference"), dict) else {}
            target_url = str(media_reference.get("target_url") or source)
            clip = otio.schema.Clip(
                name=str(item.get("name") or f"clip_{start:.2f}"),
                media_reference=otio.schema.ExternalReference(target_url=target_url),
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(start * 24, 24),
                    duration=otio.opentime.RationalTime(duration * 24, 24),
                ),
            )
            track.append(clip)
    else:
        for seg in segments:
            if seg.get("type") == "keep":
                start = seg["start"]
                end = seg["end"]
                duration = end - start

                clip = otio.schema.Clip(
                    name=f"clip_{start:.2f}",
                    media_reference=media_ref,
                    source_range=otio.opentime.TimeRange(
                        start_time=otio.opentime.RationalTime(start * 24, 24),
                        duration=otio.opentime.RationalTime(duration * 24, 24),
                    ),
                )
                track.append(clip)

    timeline.tracks.append(track)

    otio_str = otio.adapters.write_to_string(timeline, adapter_name="otio_json")

    if output_path:
        output_path.write_text(otio_str, encoding="utf-8")

    return otio_str


def _fallback_otio_json(
    *,
    source: str,
    segments: list,
    output_items: list[dict],
    rate: int = 24,
) -> str:
    clips: list[dict] = []
    if output_items:
        for item in output_items:
            if str(item.get("type") or "") != "clip":
                continue
            source_range = item.get("source_range") if isinstance(item.get("source_range"), dict) else {}
            start = float(source_range.get("start", 0.0) or 0.0)
            duration = float(source_range.get("duration", 0.0) or 0.0)
            if duration <= 0.0:
                continue
            media_reference = item.get("media_reference") if isinstance(item.get("media_reference"), dict) else {}
            clips.append(
                _fallback_clip_payload(
                    name=str(item.get("name") or f"clip_{start:.2f}"),
                    target_url=str(media_reference.get("target_url") or source),
                    start=start,
                    duration=duration,
                    rate=rate,
                )
            )
    else:
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("type") != "keep":
                continue
            start = float(segment.get("start", 0.0) or 0.0)
            end = float(segment.get("end", start) or start)
            duration = end - start
            if duration <= 0.0:
                continue
            clips.append(
                _fallback_clip_payload(
                    name=f"clip_{start:.2f}",
                    target_url=source,
                    start=start,
                    duration=duration,
                    rate=rate,
                )
            )

    payload = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": Path(source).stem,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video",
                    "kind": "Video",
                    "children": clips,
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fallback_clip_payload(
    *,
    name: str,
    target_url: str,
    start: float,
    duration: float,
    rate: int,
) -> dict:
    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": name,
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": target_url,
        },
        "source_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {
                "OTIO_SCHEMA": "RationalTime.1",
                "value": start * rate,
                "rate": rate,
            },
            "duration": {
                "OTIO_SCHEMA": "RationalTime.1",
                "value": duration * rate,
                "rate": rate,
            },
        },
    }

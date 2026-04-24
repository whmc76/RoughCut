"""OTIO (OpenTimelineIO) export for editorial timelines."""
from __future__ import annotations

from pathlib import Path


def export_to_otio(editorial_timeline: dict, output_path: Path | None = None) -> str:
    """
    Convert editorial timeline dict to OTIO format.
    Returns OTIO JSON string.
    """
    try:
        import opentimelineio as otio
    except ImportError:
        raise RuntimeError("opentimelineio is not installed. Run: pip install opentimelineio")

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

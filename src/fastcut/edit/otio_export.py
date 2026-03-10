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

    timeline = otio.schema.Timeline(name=Path(source).stem)
    track = otio.schema.Track(name="Video")

    media_ref = otio.schema.ExternalReference(target_url=source)

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

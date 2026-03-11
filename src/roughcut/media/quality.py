"""Media quality checks."""
from __future__ import annotations

from pathlib import Path

from roughcut.media.probe import MediaMeta


def check_audio_quality(meta: MediaMeta) -> list[str]:
    """Return a list of quality warnings."""
    warnings: list[str] = []
    if meta.audio_sample_rate < 16000:
        warnings.append(f"Low audio sample rate: {meta.audio_sample_rate} Hz (recommend ≥16 kHz)")
    if meta.audio_channels == 0:
        warnings.append("No audio stream detected")
    if meta.bit_rate and meta.bit_rate < 64000:
        warnings.append(f"Low overall bitrate: {meta.bit_rate} bps")
    return warnings

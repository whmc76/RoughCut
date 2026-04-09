from __future__ import annotations

from types import SimpleNamespace

from roughcut.media.probe import MediaMeta, validate_media


def test_validate_media_skips_size_limit_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "roughcut.media.probe.get_settings",
        lambda: SimpleNamespace(max_video_duration_sec=7200, max_upload_size_bytes=0),
    )

    validate_media(
        MediaMeta(
            duration=30.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=5 * 1024 * 1024 * 1024,
            format_name="mp4",
            bit_rate=10_000_000,
        )
    )

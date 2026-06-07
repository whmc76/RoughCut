from __future__ import annotations

import pytest

from roughcut.config import apply_in_memory_runtime_overrides
from roughcut.media.probe import MediaMeta, publication_upload_compatibility, validate_media


def _media_meta(*, duration: float = 60.0, file_size: int = 1) -> MediaMeta:
    return MediaMeta(
        duration=duration,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        audio_sample_rate=48000,
        audio_channels=2,
        file_size=file_size,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        bit_rate=8_000_000,
        pix_fmt="yuv420p",
        has_video_stream=True,
        has_audio_stream=True,
    )


def test_validate_media_does_not_reject_large_source_files() -> None:
    apply_in_memory_runtime_overrides({"max_upload_size_mb": 2048, "max_video_duration_sec": 3600})

    validate_media(_media_meta(file_size=3 * 1024 * 1024 * 1024))


def test_validate_media_still_rejects_overlong_sources() -> None:
    apply_in_memory_runtime_overrides({"max_upload_size_mb": 0, "max_video_duration_sec": 60})

    with pytest.raises(ValueError, match="Video duration"):
        validate_media(_media_meta(duration=61.0))


def test_publication_upload_compatibility_rejects_hevc_main10_sources() -> None:
    result = publication_upload_compatibility(
        MediaMeta(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="hevc",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=1,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            bit_rate=8_000_000,
            pix_fmt="yuv420p10le",
            video_profile="Main 10",
            video_codec_tag="hvc1",
            has_video_stream=True,
            has_audio_stream=True,
        )
    )

    assert result["compatible"] is False
    assert "video_codec:hevc" in result["reasons"]
    assert "pix_fmt:yuv420p10le" in result["reasons"]

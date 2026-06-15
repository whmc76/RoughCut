from pathlib import Path

import pytest

from roughcut.media import output as output_module


@pytest.mark.asyncio
async def test_extract_cover_frame_blocks_fallback_cover_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "input.mp4"
    output_path = tmp_path / "cover.jpg"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(output_module, "_probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        output_module,
        "_sample_cover_candidates",
        lambda *args, **kwargs: [{"seek": 3.0, "preview": None}],
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("rank_failed")

    monkeypatch.setattr(output_module, "_rank_cover_candidates", _boom)

    with pytest.raises(RuntimeError, match="cover_generation_fallback_blocked: rank_failed"):
        await output_module.extract_cover_frame(video_path, output_path, seek_sec=3.0)

    assert not output_path.exists()
    assert not output_module.get_cover_manifest_path(output_path).exists()


@pytest.mark.asyncio
async def test_extract_cover_frame_blocks_empty_ranked_candidate_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "input.mp4"
    output_path = tmp_path / "cover.jpg"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(output_module, "_probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        output_module,
        "_sample_cover_candidates",
        lambda *args, **kwargs: [{"seek": 3.0, "preview": None}],
    )

    async def _empty_rank(*args, **kwargs):
        return []

    monkeypatch.setattr(output_module, "_rank_cover_candidates", _empty_rank)

    with pytest.raises(
        RuntimeError,
        match="cover_generation_fallback_blocked: cover_candidate_ranking_returned_no_formal_selection",
    ):
        await output_module.extract_cover_frame(video_path, output_path, seek_sec=3.0)

    assert not output_path.exists()
    assert not output_module.get_cover_manifest_path(output_path).exists()


@pytest.mark.asyncio
async def test_extract_cover_frame_blocks_fallback_ranked_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "input.mp4"
    output_path = tmp_path / "cover.jpg"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(output_module, "_probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        output_module,
        "_sample_cover_candidates",
        lambda *args, **kwargs: [{"seek": 3.0, "preview": None}],
    )

    async def _fallback_rank(*args, **kwargs):
        return [{"index": 0, "score": 0.82, "reason": "", "source": "fallback_rank"}]

    monkeypatch.setattr(output_module, "_rank_cover_candidates", _fallback_rank)

    with pytest.raises(
        RuntimeError,
        match="cover_generation_fallback_blocked: cover_candidate_ranking_used_fallback_source",
    ):
        await output_module.extract_cover_frame(video_path, output_path, seek_sec=3.0)

    assert not output_path.exists()
    assert not output_module.get_cover_manifest_path(output_path).exists()

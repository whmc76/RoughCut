from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from roughcut.review import intelligent_copy_cover_quality as quality


def _request(output_path: Path, *, status: str = "completed") -> dict[str, object]:
    return {
        "status": status,
        "backend": "codex_builtin",
        "created_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        "output_path": str(output_path),
        "target_size": {"width": 1080, "height": 1920},
    }


def _metadata(output_path: Path, *, status: str = "completed") -> dict[str, object]:
    return {
        "image_generation": {
            "status": status,
            "backend": "codex_builtin",
            "output_path": str(output_path),
        }
    }


def test_pending_codex_cover_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output, status="pending_codex_imagegen"),
        _request(output, status="pending_codex_imagegen"),
        output,
    )

    assert result["publish_ready"] is False
    assert "封面等待 Codex 内置 imagegen 执行完成" in result["blocking_reasons"]
    assert f"封面输出文件不存在：{output}" in result["blocking_reasons"]


def test_completed_codex_cover_with_existing_matching_file_is_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []
    assert result["image_dimensions"] == {"width": 1080, "height": 1920}


def test_completed_codex_cover_missing_file_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "missing-cover.jpg"

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == [f"封面输出文件不存在：{output}"]


def test_completed_codex_cover_with_bad_aspect_ratio_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1920, 1080, None))

    result = quality.assess_cover_publish_readiness(
        _metadata(output),
        _request(output),
        output,
    )

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == [
        "封面尺寸比例与平台目标严重不符：output=1920x1080, target=1080x1920"
    ]


def test_completed_codex_cover_with_stale_output_is_not_publish_ready(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"old-generated")
    old_time = datetime.now(UTC) - timedelta(hours=2)
    output.touch()
    output_stat_time = old_time.timestamp()
    import os

    os.utime(output, (output_stat_time, output_stat_time))

    monkeypatch.setattr(quality, "_read_image_dimensions", lambda path: (1080, 1920, None))

    request = _request(output)
    request["created_at"] = datetime.now(UTC).isoformat()
    result = quality.assess_cover_publish_readiness(_metadata(output), request, output)

    assert result["publish_ready"] is False
    assert result["blocking_reasons"] == ["封面输出文件早于本次 Codex imagegen 请求，可能是旧 stale output"]

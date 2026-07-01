from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.providers import asset_generation


@pytest.mark.asyncio
async def test_generate_dreamina_image_asset_uses_runner_and_downloads_output(tmp_path, monkeypatch) -> None:
    output = tmp_path / "asset.jpg"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        asset_generation,
        "get_settings",
        lambda: SimpleNamespace(
            smart_director_image_generation_provider="dreamina_web",
            smart_director_image_generation_model="5.0",
            smart_director_dreamina_placeholder_reference_enabled=True,
            intelligent_copy_cover_image_model="",
            intelligent_copy_cover_image_timeout_sec=120,
        ),
    )

    async def fake_request_dreamina_web_generation(*, settings, request_spec):
        captured["request_spec"] = request_spec
        return {
            "result": {
                "url": "https://example.com/generated.jpg",
                "candidates": [{"url": "https://example.com/generated.jpg"}],
            },
            "generationStatus": "done",
            "responseMeta": {"transport": "test", "submit_id": "submit-1", "resolved_model_version": "5.0"},
        }

    async def fake_download_generated_image(url: str, output_path: Path, *, timeout_sec: float) -> None:
        captured["download"] = {"url": url, "timeout_sec": timeout_sec}
        output_path.write_bytes(b"image")

    monkeypatch.setattr(asset_generation, "_request_dreamina_web_generation", fake_request_dreamina_web_generation)
    monkeypatch.setattr(asset_generation, "_download_generated_image", fake_download_generated_image)

    result = await asset_generation.generate_dreamina_image_asset(
        prompt="生成一张科技科普短片分镜图",
        output_path=output,
        width=1080,
        height=1920,
    )

    assert output.read_bytes() == b"image"
    assert captured["request_spec"]["ratio"] == "9:16"
    assert captured["request_spec"]["model"] == "5.0"
    assert captured["request_spec"]["reference_images"][0]["alias"] == "smart_director_reference"
    assert result["status"] == "completed"
    assert result["provider"] == "dreamina_web"


@pytest.mark.asyncio
async def test_generate_jimeng_video_asset_runs_json_cli_contract(tmp_path, monkeypatch) -> None:
    cli_script = tmp_path / "fake_jimeng_cli.py"
    cli_script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "payload = json.loads(sys.stdin.read())",
                "path = pathlib.Path(payload['output_path'])",
                "path.parent.mkdir(parents=True, exist_ok=True)",
                "path.write_bytes(b'video')",
                "print(json.dumps({'ok': True, 'output_path': str(path), 'asset_id': payload['asset_id']}))",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "clip.mp4"
    monkeypatch.setattr(
        asset_generation,
        "get_settings",
        lambda: SimpleNamespace(
            smart_director_video_generation_command=json.dumps([sys.executable, str(cli_script)]),
            smart_director_video_generation_timeout_sec=30,
        ),
    )

    result = await asset_generation.generate_jimeng_video_asset(
        job_id="job-1",
        asset_id="S01_visual",
        prompt="生成视频",
        output_path=output,
        image_path=None,
        duration_sec=5,
        aspect_ratio="16:9",
    )

    assert output.read_bytes() == b"video"
    assert result["status"] == "completed"
    assert result["provider"] == "jimeng_cli"
    assert result["cli_response"]["asset_id"] == "S01_visual"

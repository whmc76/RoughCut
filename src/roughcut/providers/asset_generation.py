from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roughcut.config import DEFAULT_OUTPUT_ROOT, get_settings
from roughcut.providers.image_generation import (
    _download_generated_image,
    _request_dreamina_web_generation,
    _resolve_dreamina_ratio,
)
from roughcut.utils.asyncio_subprocess import close_asyncio_subprocess_transport


async def generate_smart_director_assets(
    *,
    job_id: str,
    asset_plan: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    output_dir = DEFAULT_OUTPUT_ROOT / "smart-director" / str(job_id) / "generated-assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = [item for item in list(asset_plan.get("assets") or []) if isinstance(item, dict)]
    max_items = max(0, int(getattr(settings, "smart_director_asset_generation_max_items", 4) or 4))
    selected_assets = assets[:max_items] if max_items else []
    if not bool(getattr(settings, "smart_director_asset_generation_enabled", True)):
        return {
            "schema": "smart_director_asset_generation.v1",
            "status": "skipped",
            "reason": "smart_director_asset_generation_disabled",
            "generated_assets": [],
            "asset_count": len(assets),
        }

    generated_assets: list[dict[str, Any]] = []
    for index, asset in enumerate(selected_assets, start=1):
        generated_assets.append(
            await _generate_one_smart_director_asset(
                job_id=str(job_id),
                asset=asset,
                output_dir=output_dir,
                index=index,
            )
        )

    success_count = sum(1 for item in generated_assets if str(item.get("status") or "") == "completed")
    partial_count = sum(1 for item in generated_assets if str(item.get("status") or "") == "partial")
    failed_count = sum(1 for item in generated_assets if str(item.get("status") or "") == "failed")
    status = "completed" if generated_assets and success_count == len(generated_assets) else "partial"
    if generated_assets and success_count == 0 and partial_count == 0:
        status = "failed"
    if not generated_assets:
        status = "skipped"
    return {
        "schema": "smart_director_asset_generation.v1",
        "status": status,
        "provider": {
            "image": str(getattr(settings, "smart_director_image_generation_provider", "dreamina_web") or "dreamina_web"),
            "video": str(getattr(settings, "smart_director_video_generation_provider", "jimeng_cli") or "jimeng_cli"),
        },
        "asset_count": len(assets),
        "requested_count": len(selected_assets),
        "success_count": success_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
        "generated_assets": generated_assets,
        "output_dir": str(output_dir),
    }


async def _generate_one_smart_director_asset(
    *,
    job_id: str,
    asset: dict[str, Any],
    output_dir: Path,
    index: int,
) -> dict[str, Any]:
    asset_id = _safe_asset_id(str(asset.get("asset_id") or f"asset_{index:02d}"))
    prompt = str(asset.get("prompt") or "").strip() or str(asset.get("description") or "").strip()
    image_path = output_dir / f"{index:02d}_{asset_id}.jpg"
    video_path = output_dir / f"{index:02d}_{asset_id}.mp4"
    result: dict[str, Any] = {
        "asset_id": asset.get("asset_id") or asset_id,
        "scene_id": asset.get("scene_id"),
        "prompt": prompt,
        "status": "pending",
    }

    image_result: dict[str, Any] | None = None
    try:
        image_result = await generate_dreamina_image_asset(
            prompt=prompt,
            output_path=image_path,
            width=int(asset.get("width") or 1536),
            height=int(asset.get("height") or 1024),
            reference_image_path=_resolve_optional_existing_path(asset.get("reference_image_path")),
        )
        result["image"] = image_result
    except Exception as exc:
        result["image"] = {
            "status": "failed",
            "provider": "dreamina_web",
            "error": str(exc),
            "output_path": str(image_path),
        }

    try:
        video_result = await generate_jimeng_video_asset(
            job_id=job_id,
            asset_id=str(asset.get("asset_id") or asset_id),
            prompt=prompt,
            output_path=video_path,
            image_path=image_path if image_path.exists() else None,
            duration_sec=_positive_float(asset.get("duration_sec"), 5.0),
            aspect_ratio=str(asset.get("aspect_ratio") or "16:9"),
        )
        result["video"] = video_result
    except Exception as exc:
        result["video"] = {
            "status": "failed",
            "provider": "jimeng_cli",
            "error": str(exc),
            "output_path": str(video_path),
        }

    image_status = str(((result.get("image") or {}) if isinstance(result.get("image"), dict) else {}).get("status") or "")
    video_status = str(((result.get("video") or {}) if isinstance(result.get("video"), dict) else {}).get("status") or "")
    if image_status == "completed" and video_status in {"completed", "skipped"}:
        result["status"] = "completed"
    elif image_status == "completed" or video_status == "completed":
        result["status"] = "partial"
    else:
        result["status"] = "failed"
    return result


async def generate_dreamina_image_asset(
    *,
    prompt: str,
    output_path: Path,
    width: int,
    height: int,
    reference_image_path: Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    provider = str(getattr(settings, "smart_director_image_generation_provider", "dreamina_web") or "dreamina_web")
    if provider.strip().lower() not in {"dreamina", "dreamina_web", "jimeng", "jimeng_cli"}:
        return {
            "status": "skipped",
            "provider": provider,
            "reason": "unsupported_smart_director_image_generation_provider",
            "output_path": str(output_path),
        }
    request_spec: dict[str, Any] = {
        "prompt": prompt,
        "prompt_base64": base64.b64encode(prompt.encode("utf-8")).decode("ascii"),
        "ratio": _resolve_dreamina_ratio(width, height),
    }
    model = str(
        getattr(settings, "smart_director_image_generation_model", "")
        or getattr(settings, "intelligent_copy_cover_image_model", "")
        or ""
    ).strip()
    if model:
        request_spec["model"] = model
        request_spec["modelVersion"] = model
    if reference_image_path is not None and reference_image_path.exists():
        request_spec["reference_images"] = [
            {
                "path": str(reference_image_path),
                "alias": reference_image_path.stem or "reference_image",
            }
        ]
    elif _dreamina_requires_reference_image(settings):
        placeholder = output_path.with_suffix(".reference.png")
        _write_placeholder_reference_image(placeholder, width=width, height=height)
        request_spec["reference_images"] = [
            {
                "path": str(placeholder),
                "alias": "smart_director_reference",
            }
        ]

    runner_response = await _request_dreamina_web_generation(settings=settings, request_spec=request_spec)
    result_block = runner_response.get("result") if isinstance(runner_response, dict) else {}
    if not isinstance(result_block, dict):
        raise RuntimeError("Dreamina runner response missing result block")
    image_url = str(result_block.get("url") or "").strip()
    if not image_url:
        selected = result_block.get("selectedCandidate") if isinstance(result_block.get("selectedCandidate"), dict) else {}
        image_url = str(selected.get("url") or "").strip()
    if not image_url:
        raise RuntimeError("Dreamina generation did not return an image URL")
    timeout_sec = float(max(30, int(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 240) or 240)))
    await _download_generated_image(image_url, output_path, timeout_sec=timeout_sec)
    response_meta = runner_response.get("responseMeta") if isinstance(runner_response.get("responseMeta"), dict) else {}
    candidates = result_block.get("candidates") if isinstance(result_block.get("candidates"), list) else []
    return {
        "status": "completed",
        "provider": "dreamina_web",
        "output_path": str(output_path),
        "image_url": image_url,
        "candidate_count": len(candidates),
        "generation_status": str(runner_response.get("generationStatus") or "").strip(),
        "transport": str(response_meta.get("transport") or "").strip(),
        "submit_id": str(response_meta.get("submit_id") or "").strip(),
        "model": str(response_meta.get("resolved_model_version") or model or "").strip(),
        "ratio": request_spec["ratio"],
    }


async def generate_jimeng_video_asset(
    *,
    job_id: str,
    asset_id: str,
    prompt: str,
    output_path: Path,
    image_path: Path | None,
    duration_sec: float,
    aspect_ratio: str,
) -> dict[str, Any]:
    settings = get_settings()
    command = str(getattr(settings, "smart_director_video_generation_command", "") or "").strip()
    if not command:
        return {
            "status": "skipped",
            "provider": "jimeng_cli",
            "reason": "smart_director_video_generation_command_not_configured",
            "output_path": str(output_path),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "jimeng_cli",
        "job_id": job_id,
        "asset_id": asset_id,
        "prompt": prompt,
        "output_path": str(output_path),
        "image_path": str(image_path) if image_path is not None else "",
        "duration_sec": duration_sec,
        "aspect_ratio": aspect_ratio,
    }
    timeout_sec = max(30, int(getattr(settings, "smart_director_video_generation_timeout_sec", 900) or 900))
    stdout, stderr = await _run_json_cli(command=command, payload=payload, timeout_sec=timeout_sec)
    response = _parse_cli_response(stdout)
    if not output_path.exists():
        returned_path = str(response.get("output_path") or response.get("path") or "").strip()
        if returned_path and Path(returned_path).expanduser().exists():
            output_path.write_bytes(Path(returned_path).expanduser().read_bytes())
    if not output_path.exists():
        raise RuntimeError(f"jimeng_cli did not create output_path: {output_path}; stderr={stderr[-500:]}")
    return {
        "status": "completed",
        "provider": "jimeng_cli",
        "output_path": str(output_path),
        "cli_response": response,
    }


async def _run_json_cli(*, command: str, payload: dict[str, Any], timeout_sec: int) -> tuple[str, str]:
    argv = _split_command(command)
    if not argv:
        raise RuntimeError("smart_director_video_generation_command_empty")
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path.cwd()),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            timeout=float(timeout_sec),
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        await close_asyncio_subprocess_transport(process)
        raise RuntimeError(f"jimeng_cli timed out after {timeout_sec}s") from exc
    await close_asyncio_subprocess_transport(process)
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise RuntimeError(f"jimeng_cli failed: {stderr_text or stdout_text or process.returncode}")
    return stdout_text, stderr_text


def _parse_cli_response(stdout: str) -> dict[str, Any]:
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"raw_stdout": stdout}
    return payload if isinstance(payload, dict) else {"value": payload}


def _split_command(command: str) -> list[str]:
    stripped = command.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return shlex.split(command, posix=os.name != "nt")


def _safe_asset_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value).strip("._")
    return safe or uuid.uuid4().hex[:10]


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _resolve_optional_existing_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.exists() else None


def _dreamina_requires_reference_image(settings: Any) -> bool:
    return bool(getattr(settings, "smart_director_dreamina_placeholder_reference_enabled", True))


def _write_placeholder_reference_image(path: Path, *, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_width = max(256, min(1536, int(width or 1024)))
    safe_height = max(256, min(1536, int(height or 1024)))
    image = Image.new("RGB", (safe_width, safe_height), (24, 28, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle((safe_width * 0.12, safe_height * 0.18, safe_width * 0.88, safe_height * 0.82), outline=(90, 110, 135), width=4)
    draw.line((safe_width * 0.12, safe_height * 0.18, safe_width * 0.88, safe_height * 0.82), fill=(70, 88, 108), width=3)
    draw.line((safe_width * 0.88, safe_height * 0.18, safe_width * 0.12, safe_height * 0.82), fill=(70, 88, 108), width=3)
    image.save(path)

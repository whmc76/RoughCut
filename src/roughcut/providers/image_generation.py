from __future__ import annotations

import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openai

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential

CODEX_BUILTIN_IMAGE_MODEL_LABEL = "codex_builtin_image_generation"


class CodexImageGenerationPending(RuntimeError):
    def __init__(self, metadata: dict[str, Any]):
        super().__init__("Codex built-in image generation requires a Codex imagegen runner")
        self.metadata = metadata


def resolve_image_generation_size(width: int, height: int) -> str:
    safe_width = max(1, int(width or 0))
    safe_height = max(1, int(height or 0))
    ratio = safe_width / safe_height
    if 0.82 <= ratio <= 1.22:
        return "1024x1024"
    if ratio > 1.0:
        return "1536x1024"
    return "1024x1536"


def resolve_codex_imagegen_runner_config(settings: Any | None = None) -> dict[str, str]:
    current = settings or get_settings()
    model = str(getattr(current, "intelligent_copy_cover_codex_runner_model", "") or "gpt-5.4-mini").strip()
    effort = str(getattr(current, "intelligent_copy_cover_codex_runner_effort", "") or "low").strip().lower()
    if effort not in {"minimal", "low", "medium", "high"}:
        effort = "low"
    return {
        "model": model or "gpt-5.4-mini",
        "reasoning_effort": effort,
        "role": "codex_exec_agent",
        "note": "This config controls the Codex text agent that invokes image_generation; it is not the underlying image model.",
    }


async def generate_edited_cover_image(
    *,
    source_image_path: Path,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
    request_path: Path | None = None,
    final_output_path: Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    backend = str(getattr(settings, "intelligent_copy_cover_image_backend", "") or "codex_builtin").strip().lower()
    if backend in {"", "codex", "codex_cli", "codex_imagegen", "codex_builtin"}:
        final_path = final_output_path or output_path
        if request_path is not None and _codex_imagegen_request_completed(request_path, final_path):
            runner_config = resolve_codex_imagegen_runner_config(settings)
            return {
                "status": "completed",
                "backend": "codex_builtin",
                "image_model": CODEX_BUILTIN_IMAGE_MODEL_LABEL,
                "codex_runner": runner_config,
                "output_path": str(final_path),
                "request_path": str(request_path),
                "size": resolve_image_generation_size(width, height),
            }
        metadata = _write_codex_imagegen_request(
            source_image_path=source_image_path,
            request_path=request_path,
            output_path=final_path,
            prompt=prompt,
            width=width,
            height=height,
        )
        raise CodexImageGenerationPending(metadata)
    if backend not in {"openai_images_api", "openai_api"}:
        raise RuntimeError(f"Unsupported cover image generation backend: {backend}")
    return await _generate_with_openai_images_api(
        source_image_path=source_image_path,
        output_path=output_path,
        prompt=prompt,
        width=width,
        height=height,
    )


def _write_codex_imagegen_request(
    *,
    source_image_path: Path,
    request_path: Path | None,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    request_file = request_path or output_path.with_suffix(".codex-imagegen.json")
    request_file.parent.mkdir(parents=True, exist_ok=True)
    reference_path = request_file.with_name(f"{request_file.stem}-reference{source_image_path.suffix or '.jpg'}")
    if source_image_path.exists():
        shutil.copy2(source_image_path, reference_path)
    runner_config = resolve_codex_imagegen_runner_config()
    size = resolve_image_generation_size(width, height)
    payload = {
        "status": "pending_codex_imagegen",
        "backend": "codex_builtin",
        "created_at": datetime.now(UTC).isoformat(),
        "source_image_path": str(reference_path),
        "output_path": str(output_path),
        "prompt": prompt,
        "target_size": {"width": int(width), "height": int(height)},
        "image_generation": {
            "backend": "codex_builtin",
            "image_model": CODEX_BUILTIN_IMAGE_MODEL_LABEL,
            "size": size,
        },
        "codex_runner": runner_config,
        "codex_imagegen_size": size,
        "cover_director_policy": {
            "codex_role": "write_clear_image_generation_brief",
            "goal": "Send the image model a concise cover brief and let the image model produce the final cover.",
            "typography_owner": "image_model",
            "forbidden_extra_visual_text": [
                "subtitles",
                "slogans",
                "labels",
                "buttons",
                "watermarks",
                "pseudo logos",
                "Chinese or English words not explicitly requested in the prompt",
            ],
            "completion_requires": [
                "A real bitmap generated with Codex built-in image_gen/edit mode.",
                "The exact requested title is rendered by the image model as part of the cover.",
                "Title text is readable at thumbnail size and stays within the image bounds.",
                "Title text and key subject stay in the center safe area for common platform crops.",
                "No extra unrequested typography or decorative text in the bitmap.",
                "The generated bitmap copied to output_path before marking this request completed.",
            ],
        },
        "instructions": (
            "Use Codex built-in image_gen/edit mode with source_image_path as the edit target/reference. "
            "Treat codex_runner.model as the Codex execution agent model only, not as the underlying image model. "
            "Do not use the OpenAI Images API fallback unless explicitly requested. "
            "Pass the prompt as the concise image-generation brief; let the image model handle composition and typography. "
            "Copy the selected generated bitmap into output_path."
        ),
    }
    request_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "pending_codex_imagegen",
        "backend": "codex_builtin",
        "image_model": CODEX_BUILTIN_IMAGE_MODEL_LABEL,
        "codex_runner": runner_config,
        "request_path": str(request_file),
        "source_image_path": str(reference_path),
        "output_path": str(output_path),
        "size": size,
    }


def _codex_imagegen_request_completed(request_path: Path, output_path: Path) -> bool:
    if not request_path.exists() or not output_path.exists():
        return False
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(payload.get("status") or "").strip().lower() != "completed":
        return False
    recorded_output = str(payload.get("output_path") or "").strip()
    return not recorded_output or Path(recorded_output) == output_path


def mark_codex_imagegen_request_completed(*, request_path: Path, output_path: Path, result_path: Path | None = None) -> dict[str, Any]:
    if not request_path.exists():
        raise FileNotFoundError(f"Codex imagegen request not found: {request_path}")
    if not output_path.exists():
        raise FileNotFoundError(f"Codex imagegen output not found: {output_path}")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["status"] = "completed"
    payload["completed_at"] = datetime.now(UTC).isoformat()
    payload["output_path"] = str(output_path)
    if result_path is not None:
        payload["result_path"] = str(result_path)
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


async def _generate_with_openai_images_api(
    *,
    source_image_path: Path,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    settings = get_settings()
    model = str(getattr(settings, "intelligent_copy_cover_image_model", "") or "image2").strip()
    quality = str(getattr(settings, "intelligent_copy_cover_image_quality", "") or "medium").strip()
    timeout = float(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 90) or 90)
    client = openai.AsyncOpenAI(
        api_key=resolve_credential(
            mode=settings.openai_auth_mode,
            direct_value=settings.openai_api_key,
            helper_command=settings.openai_api_key_helper,
            provider_name="OpenAI",
        ),
        base_url=settings.openai_base_url.rstrip("/"),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with source_image_path.open("rb") as source_file:
        response = await client.images.edit(
            model=model,
            image=source_file,
            prompt=prompt,
            size=resolve_image_generation_size(width, height),
            quality=quality,
            output_format="jpeg",
            response_format="b64_json",
            input_fidelity="high",
            timeout=timeout,
        )
    data = list(getattr(response, "data", []) or [])
    if not data or not getattr(data[0], "b64_json", None):
        raise RuntimeError("Image generation did not return image data")
    output_path.write_bytes(base64.b64decode(str(data[0].b64_json)))
    return {
        "backend": "openai_images_api",
        "model": str(getattr(response, "model", "") or model),
        "size": resolve_image_generation_size(width, height),
        "quality": quality,
        "revised_prompt": str(getattr(data[0], "revised_prompt", "") or ""),
    }

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import openai

from roughcut.config import get_settings
from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token
from roughcut.intelligent_copy_layout import SMART_COPY_COVER_DIRNAME
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.providers.auth import resolve_credential
from roughcut.utils.asyncio_subprocess import close_asyncio_subprocess_transport

CODEX_BUILTIN_IMAGE_MODEL_LABEL = "codex_builtin_image_generation"
MINIMAX_IMAGE_MODEL_LABEL = "image-01"
DREAMINA_WEB_IMAGE_BACKEND = "dreamina_web"
DREAMINA_RISKY_PROMPT_TOKEN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"MAXACE", "参考商品"),
    (r"美杜莎\d*", "参考商品"),
    (r"EDC", ""),
    (r"折刀|刀具|刀身|刀型|双刀", "主体"),
    (r"开孔|转轴", "结构细节"),
)


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
    reference_image_paths: list[Path] | None = None,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
    request_path: Path | None = None,
    final_output_path: Path | None = None,
    hard_contract: dict[str, Any] | None = None,
    director_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    backend = str(getattr(settings, "intelligent_copy_cover_image_backend", "") or "codex_builtin").strip().lower()
    if backend in {"", "codex", "codex_cli", "codex_imagegen", "codex_builtin"}:
        final_path = final_output_path or output_path
        if request_path is not None and _codex_imagegen_request_completed(
            request_path,
            final_path,
            expected_prompt=prompt,
            expected_hard_contract=hard_contract,
            expected_director_policy=director_policy,
        ):
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
            reference_image_paths=reference_image_paths,
            request_path=request_path,
            output_path=final_path,
            prompt=prompt,
            width=width,
            height=height,
            hard_contract=hard_contract,
            director_policy=director_policy,
        )
        request_file = Path(str(metadata.get("request_path") or "")).expanduser()
        if request_file.exists():
            try:
                await _attempt_codex_imagegen_auto_completion(
                    request_path=request_file,
                    output_path=final_path,
                    settings=settings,
                )
            except Exception as exc:
                metadata["auto_completion_error"] = _record_codex_imagegen_request_bridge_error(
                    request_path=request_file,
                    error=str(exc),
                )
            if _codex_imagegen_request_completed(
                request_file,
                final_path,
                expected_prompt=prompt,
                expected_hard_contract=hard_contract,
                expected_director_policy=director_policy,
            ):
                runner_config = resolve_codex_imagegen_runner_config(settings)
                return {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "image_model": CODEX_BUILTIN_IMAGE_MODEL_LABEL,
                    "codex_runner": runner_config,
                    "output_path": str(final_path),
                    "request_path": str(request_file),
                    "size": resolve_image_generation_size(width, height),
                }
        raise CodexImageGenerationPending(metadata)
    if backend in {DREAMINA_WEB_IMAGE_BACKEND, "dreamina", "dreamina_cdp", "dreamina_web_cdp"}:
        return await _generate_with_dreamina_web(
            source_image_path=source_image_path,
            output_path=output_path,
            prompt=prompt,
            width=width,
            height=height,
        )
    if backend in {"minimax_images_api", "minimax_api"}:
        return await _generate_with_minimax_images_api(
            source_image_path=source_image_path,
            output_path=output_path,
            prompt=prompt,
            width=width,
            height=height,
        )
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
    reference_image_paths: list[Path] | None = None,
    request_path: Path | None,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
    hard_contract: dict[str, Any] | None = None,
    director_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_file = request_path or output_path.with_suffix(".codex-imagegen.json")
    request_file.parent.mkdir(parents=True, exist_ok=True)
    copied_reference_paths = _copy_codex_reference_images(
        request_file=request_file,
        source_image_path=source_image_path,
        reference_image_paths=reference_image_paths,
    )
    reference_path = copied_reference_paths[0]
    runner_config = resolve_codex_imagegen_runner_config()
    size = resolve_image_generation_size(width, height)
    payload = {
        "status": "pending_codex_imagegen",
        "backend": "codex_builtin",
        "created_at": datetime.now(UTC).isoformat(),
        "source_image_path": str(reference_path),
        "reference_image_paths": [str(path) for path in copied_reference_paths],
        "reference_pack_contract": {
            "same_product_multi_angle": len(copied_reference_paths) > 1,
            "primary_reference_index": 1,
            "reference_count": len(copied_reference_paths),
            "majority_view_policy": "prefer_majority_hero_angle"
            if len(copied_reference_paths) > 1
            else "single_reference_only",
        },
        "output_path": str(output_path),
        "prompt": prompt,
        "cover_hard_contract": dict(hard_contract or {}),
        "target_size": {"width": int(width), "height": int(height)},
        "image_generation": {
            "backend": "codex_builtin",
            "image_model": CODEX_BUILTIN_IMAGE_MODEL_LABEL,
            "size": size,
        },
        "codex_runner": runner_config,
        "codex_imagegen_size": size,
        "cover_director_policy": dict(director_policy or {
            "direction_version": "local_overlay_required_v1",
            "codex_role": "render_cover_base_for_local_overlay",
            "goal": "Let Codex image generation produce a clean cover base that is safe for deterministic local typography overlay.",
            "typography_owner": "local_post_overlay",
            "forbidden_extra_visual_text": [
                "subtitles",
                "watermarks",
                "pseudo logos unrelated to the requested brand",
                "any readable Chinese or English text",
                "any readable numbers or pseudo text",
            ],
            "completion_requires": [
                "A real bitmap generated with Codex built-in image_gen/edit mode.",
                "The bitmap is a clean cover base, not the final text-integrated cover.",
                "No extra unrequested typography, subtitles, watermarks, or unrelated pseudo logos appear in the bitmap.",
                "Key subject stays complete and readable after later local typography placement.",
                "The generated bitmap copied to output_path before marking this request completed.",
            ],
        }),
        "instructions": (
            "Use Codex built-in image_gen/edit mode with source_image_path as the primary hero-angle anchor from the same-product reference pack. "
            "When reference_image_paths is present, treat the full ordered set as the allowed same-product multi-angle reference pack. "
            "Treat codex_runner.model as the Codex execution agent model only, not as the underlying image model. "
            "Do not use the OpenAI Images API fallback unless explicitly requested. "
            "Pass the prompt as the concise image-generation brief for a text-free cover base; local post-processing owns typography. "
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
        "reference_image_paths": [str(path) for path in copied_reference_paths],
        "output_path": str(output_path),
        "size": size,
    }


def _copy_codex_reference_images(
    *,
    request_file: Path,
    source_image_path: Path,
    reference_image_paths: list[Path] | None = None,
) -> list[Path]:
    candidate_paths: list[Path] = []
    for candidate in [source_image_path, *(reference_image_paths or [])]:
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in candidate_paths:
            continue
        candidate_paths.append(resolved)
    if not candidate_paths:
        raise FileNotFoundError(f"Codex imagegen source image missing: {source_image_path}")

    copied_paths: list[Path] = []
    for index, candidate in enumerate(candidate_paths, start=1):
        if _should_reuse_shared_codex_reference_path(request_file=request_file, candidate=candidate):
            copied_paths.append(candidate)
            continue
        if index == 1:
            reference_path = request_file.with_name(
                f"{request_file.stem}-reference{candidate.suffix or '.jpg'}"
            )
        else:
            reference_path = request_file.with_name(
                f"{request_file.stem}-reference-{index}{candidate.suffix or '.jpg'}"
            )
        shutil.copy2(candidate, reference_path)
        copied_paths.append(reference_path)
    return copied_paths


def _should_reuse_shared_codex_reference_path(*, request_file: Path, candidate: Path) -> bool:
    try:
        request_parent = request_file.parent.resolve()
        candidate_path = candidate.resolve()
    except OSError:
        return False
    if candidate_path.parent != request_parent:
        return False
    if request_parent.name != SMART_COPY_COVER_DIRNAME:
        return False
    name = candidate_path.name
    return name.startswith("00-highlight-reference-") or name == "00-highlight-cover-source.jpg"


def _codex_imagegen_request_completed(
    request_path: Path,
    output_path: Path,
    *,
    expected_prompt: str | None = None,
    expected_hard_contract: dict[str, Any] | None = None,
    expected_director_policy: dict[str, Any] | None = None,
) -> bool:
    if not request_path.exists() or not output_path.exists():
        return False
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(payload.get("status") or "").strip().lower() != "completed":
        return False
    if not bool(payload.get("generated_by_codex_bridge")):
        return False
    recorded_output = str(payload.get("output_path") or "").strip()
    if recorded_output and Path(recorded_output) != output_path:
        return False
    recorded_result = str(payload.get("result_path") or "").strip()
    if recorded_result and not codex_imagegen_result_path_is_allowed(
        Path(recorded_result).expanduser(),
        output_path=output_path,
    ):
        return False
    if expected_prompt is not None and str(payload.get("prompt") or "") != str(expected_prompt or ""):
        return False
    if expected_hard_contract is not None:
        recorded_hard_contract = payload.get("cover_hard_contract")
        if not isinstance(recorded_hard_contract, dict):
            return False
        if recorded_hard_contract != dict(expected_hard_contract or {}):
            return False
    if expected_director_policy is not None:
        recorded_director_policy = payload.get("cover_director_policy")
        if not isinstance(recorded_director_policy, dict):
            return False
        if recorded_director_policy != dict(expected_director_policy or {}):
            return False
    return True


def mark_codex_imagegen_request_completed(
    *,
    request_path: Path,
    output_path: Path,
    result_path: Path | None = None,
    recorded_output_path: str | None = None,
    session_id: str | None = None,
    timed_out: bool | None = None,
) -> dict[str, Any]:
    if not request_path.exists():
        raise FileNotFoundError(f"Codex imagegen request not found: {request_path}")
    if not output_path.exists():
        raise FileNotFoundError(f"Codex imagegen output not found: {output_path}")
    if result_path is not None and not codex_imagegen_result_path_is_allowed(result_path, output_path=output_path):
        raise ValueError(f"Codex imagegen result path is outside the allowed Codex output roots: {result_path}")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    completed_at = datetime.now(UTC).isoformat()
    payload["status"] = "completed"
    payload["completed_at"] = completed_at
    payload["last_attempted_at"] = completed_at
    payload["output_path"] = str(recorded_output_path or output_path)
    payload["auto_completion_error"] = ""
    payload["generated_by_codex_bridge"] = True
    if result_path is not None:
        payload["result_path"] = str(result_path)
    if session_id:
        payload["session_id"] = str(session_id).strip()
    if timed_out is not None:
        payload["timed_out"] = bool(timed_out)
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def codex_imagegen_result_path_is_allowed(result_path: Path, *, output_path: Path) -> bool:
    try:
        resolved_result = Path(result_path).expanduser().resolve()
        resolved_output = Path(output_path).expanduser().resolve()
    except OSError:
        return False
    if resolved_result == resolved_output:
        return True
    return any(_path_is_relative_to(resolved_result, root) for root in codex_generated_image_roots())


def codex_generated_image_roots() -> list[Path]:
    roots: list[Path] = []
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        roots.append(Path(codex_home).expanduser() / "generated_images")
    roots.append(Path.home() / ".codex" / "generated_images")
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _record_codex_imagegen_request_bridge_error(*, request_path: Path, error: str) -> str:
    normalized_error = str(error or "").strip()
    if not request_path.exists():
        return normalized_error
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["auto_completion_error"] = normalized_error
    payload["last_attempted_at"] = datetime.now(UTC).isoformat()
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized_error


async def _attempt_codex_imagegen_auto_completion(*, request_path: Path, output_path: Path, settings: Any) -> None:
    url = resolve_codex_proxy_sibling_url("/v1/host/complete-codex-imagegen")
    token = resolve_codex_proxy_token()
    if not url or not token:
        return
    configured_timeout_sec = int(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 90) or 90)
    exec_timeout_sec = max(
        45,
        min(
            180,
            configured_timeout_sec,
        ),
    )
    request_timeout_sec = max(exec_timeout_sec + 20, 65)
    payload = {
        "request_path": str(request_path),
        "repo_root": "/app",
        "timeout_sec": exec_timeout_sec,
        "model": str(getattr(settings, "intelligent_copy_cover_codex_runner_model", "") or "").strip(),
    }
    async with httpx.AsyncClient(timeout=float(request_timeout_sec)) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Codex imagegen host runner returned an invalid response")
    if str(result.get("status") or "").strip().lower() != "completed":
        raise RuntimeError(str(result.get("error") or "Codex imagegen host runner did not complete the request"))
    if not output_path.exists():
        raise RuntimeError("Codex imagegen host runner completed without producing the output file")
    mark_codex_imagegen_request_completed(
        request_path=request_path,
        output_path=output_path,
        result_path=Path(str(result.get("result_path") or "")).expanduser()
        if str(result.get("result_path") or "").strip()
        else None,
        recorded_output_path=str(result.get("output_path") or output_path),
        session_id=str(result.get("session_id") or "").strip() or None,
        timed_out=bool(result.get("timed_out")) if "timed_out" in result else None,
    )


def _resolve_minimax_aspect_ratio(width: int, height: int) -> str:
    safe_width = max(1, int(width or 0))
    safe_height = max(1, int(height or 0))
    ratio = safe_width / safe_height
    options = {
        "1:1": 1.0,
        "16:9": 16 / 9,
        "4:3": 4 / 3,
        "3:2": 3 / 2,
        "2:3": 2 / 3,
        "3:4": 3 / 4,
        "9:16": 9 / 16,
        "21:9": 21 / 9,
    }
    return min(options, key=lambda key: abs(options[key] - ratio))


def _encode_image_as_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


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


async def _generate_with_minimax_images_api(
    *,
    source_image_path: Path,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    settings = get_settings()
    model = str(getattr(settings, "intelligent_copy_cover_image_model", "") or MINIMAX_IMAGE_MODEL_LABEL).strip()
    if model in {"", "image2"}:
        model = MINIMAX_IMAGE_MODEL_LABEL
    timeout = float(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 90) or 90)
    base_url = str(getattr(settings, "minimax_base_url", "") or "https://api.minimaxi.com/v1").rstrip("/")
    token = resolve_credential(
        mode="api_key",
        direct_value=str(getattr(settings, "minimax_api_key", "") or ""),
        helper_command="",
        provider_name="MiniMax",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "aspect_ratio": _resolve_minimax_aspect_ratio(width, height),
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": False,
        # Inference from the official subject_reference contract: image_file is passed as a data URL
        # so we can keep the reference-image workflow local without introducing a separate host/upload step.
        "subject_reference": [
            {
                "type": "character",
                "image_file": _encode_image_as_data_url(source_image_path),
            }
        ],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/image_generation",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    base_resp = data.get("base_resp") if isinstance(data, dict) else {}
    if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) != 0:
        raise RuntimeError(f"MiniMax image generation failed: {base_resp.get('status_msg') or base_resp}")
    images = []
    if isinstance(data, dict):
        data_block = data.get("data")
        if isinstance(data_block, dict):
            raw_images = (
                data_block.get("image_base64")
                or data_block.get("images_base64")
                or data_block.get("images")
                or []
            )
            if isinstance(raw_images, str):
                images = [raw_images]
            elif isinstance(raw_images, list):
                images = list(raw_images)
    if not images:
        raise RuntimeError("MiniMax image generation did not return image data")
    first_image = images[0]
    if not isinstance(first_image, str) or not first_image.strip():
        raise RuntimeError("MiniMax image generation returned an empty image payload")
    output_path.write_bytes(base64.b64decode(first_image))
    return {
        "backend": "minimax_images_api",
        "model": model,
        "size": f"{int(width)}x{int(height)}",
        "aspect_ratio": payload["aspect_ratio"],
        "request_id": str(data.get("id") or "") if isinstance(data, dict) else "",
    }


def _sanitize_dreamina_reference_alias(source_image_path: Path) -> str:
    stem = str(source_image_path.stem or "reference").strip()
    normalized = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._")
    return normalized or "reference_image"


def _sanitize_dreamina_prompt(prompt: str) -> str:
    text = str(prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    sanitized_lines: list[str] = []
    immutable_prefixes = (
        "封面主题：",
        "标题：",
        "标题必须完整渲染：",
        "主体识别：",
        "品牌/商品名必须完整保留：",
        "风格：",
    )
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(immutable_prefixes):
            sanitized_lines.append(line)
            continue
        for pattern, replacement in DREAMINA_RISKY_PROMPT_TOKEN_REPLACEMENTS:
            line = re.sub(pattern, replacement, line, flags=re.I)
        if line.startswith("重点强调商品细节一致性："):
            line = "重点强调商品细节一致性：保留轮廓、比例、纹理分区、结构细节和主要部件位置，不改款，不变形。"
        elif line.startswith("画面 brief："):
            line = line.replace("并排展示", "并排呈现").replace("聚焦刀身", "聚焦主体")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            sanitized_lines.append(line)
    return "\n".join(sanitized_lines)


def _resolve_dreamina_ratio(width: int, height: int) -> str:
    safe_width = max(1, int(width or 0))
    safe_height = max(1, int(height or 0))
    divisor = math.gcd(safe_width, safe_height)
    return f"{safe_width // divisor}:{safe_height // divisor}"


def _resolve_dreamina_runner_script(settings: Any) -> Path:
    configured = str(getattr(settings, "intelligent_copy_cover_dreamina_runner_script", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    bundled = Path(__file__).resolve().parents[3] / "scripts" / "dreamina_web_cdp.mjs"
    return bundled


def _build_dreamina_backend_config(settings: Any) -> dict[str, Any]:
    return {
        "provider": DREAMINA_WEB_IMAGE_BACKEND,
        "model": str(getattr(settings, "intelligent_copy_cover_image_model", "") or "").strip(),
        "quality": str(getattr(settings, "intelligent_copy_cover_image_quality", "") or "").strip(),
        "cdpBaseUrl": str(
            getattr(settings, "intelligent_copy_cover_dreamina_cdp_base_url", "") or "http://127.0.0.1:9222"
        ).strip(),
        "cdpCookieSourceBaseUrl": str(
            getattr(settings, "intelligent_copy_cover_dreamina_cookie_source_base_url", "") or "http://127.0.0.1:9222"
        ).strip(),
        "cdpTargetPageUrl": str(
            getattr(settings, "intelligent_copy_cover_dreamina_page_url", "")
            or "https://jimeng.jianying.com/ai-tool/generate/?type=image"
        ).strip(),
        "pageUrlPattern": str(
            getattr(settings, "intelligent_copy_cover_dreamina_page_url_pattern", "")
            or "jimeng.jianying.com/ai-tool/generate"
        ).strip(),
        "cdpUserDataDir": str(getattr(settings, "intelligent_copy_cover_dreamina_user_data_dir", "") or "").strip(),
        "cdpHeadlessUserDataDir": str(
            getattr(settings, "intelligent_copy_cover_dreamina_headless_user_data_dir", "") or ""
        ).strip(),
        "templatePath": str(getattr(settings, "intelligent_copy_cover_dreamina_template_path", "") or "").strip(),
        "submitStatePath": str(
            getattr(settings, "intelligent_copy_cover_dreamina_submit_state_path", "") or ""
        ).strip(),
        "cdpExecutablePath": str(
            getattr(settings, "intelligent_copy_cover_dreamina_executable_path", "") or ""
        ).strip(),
        "httpReplayEnabled": bool(
            getattr(settings, "intelligent_copy_cover_dreamina_http_replay_enabled", True)
        ),
        "cdpAutoLaunch": bool(getattr(settings, "intelligent_copy_cover_dreamina_auto_launch", True)),
        "cdpHeadless": bool(getattr(settings, "intelligent_copy_cover_dreamina_headless", True)),
        "cdpKeepAlive": bool(getattr(settings, "intelligent_copy_cover_dreamina_keep_alive", False)),
        "pollIntervalMs": max(
            1000,
            int(getattr(settings, "intelligent_copy_cover_dreamina_poll_interval_ms", 5000) or 5000),
        ),
        "pollTimeoutMs": max(
            5000,
            int(getattr(settings, "intelligent_copy_cover_dreamina_poll_timeout_ms", 300000) or 300000),
        ),
        "submitTimeoutMs": max(
            5000,
            int(getattr(settings, "intelligent_copy_cover_dreamina_submit_timeout_ms", 60000) or 60000),
        ),
        "captureTimeoutMs": max(
            5000,
            int(getattr(settings, "intelligent_copy_cover_dreamina_capture_timeout_ms", 120000) or 120000),
        ),
        "minSubmitIntervalMs": max(
            0,
            int(getattr(settings, "intelligent_copy_cover_dreamina_min_submit_interval_ms", 45000) or 45000),
        ),
    }


def _resolve_dreamina_runner_timeout_sec(settings: Any) -> int:
    base_timeout_sec = max(30, int(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 90) or 90))
    poll_timeout_sec = max(
        5,
        math.ceil(int(getattr(settings, "intelligent_copy_cover_dreamina_poll_timeout_ms", 300000) or 300000) / 1000),
    )
    submit_timeout_sec = max(
        5,
        math.ceil(int(getattr(settings, "intelligent_copy_cover_dreamina_submit_timeout_ms", 60000) or 60000) / 1000),
    )
    return max(base_timeout_sec, poll_timeout_sec + submit_timeout_sec + 30)


async def _request_dreamina_web_generation(
    *,
    settings: Any,
    request_spec: dict[str, Any],
) -> dict[str, Any]:
    runner_script = _resolve_dreamina_runner_script(settings)
    if not runner_script.exists():
        raise RuntimeError(
            "Dreamina runner script not found. "
            "Restore scripts/dreamina_web_cdp.mjs or override "
            "INTELLIGENT_COPY_COVER_DREAMINA_RUNNER_SCRIPT with a valid module path."
        )
    bridge_script = Path(__file__).resolve().parents[3] / "scripts" / "dreamina_request_bridge.mjs"
    if not bridge_script.exists():
        raise RuntimeError(f"Dreamina request bridge not found: {bridge_script}")
    node_command = str(getattr(settings, "intelligent_copy_cover_dreamina_command", "") or "node").strip() or "node"
    payload = {
        "runnerScript": str(runner_script),
        "config": _build_dreamina_backend_config(settings),
        "requestSpec": request_spec,
    }
    timeout_sec = _resolve_dreamina_runner_timeout_sec(settings)
    process = await asyncio.create_subprocess_exec(
        node_command,
        str(bridge_script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    stdout: bytes
    stderr: bytes
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            timeout=float(timeout_sec),
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        await close_asyncio_subprocess_transport(process)
        raise RuntimeError(f"Dreamina runner timed out after {timeout_sec}s") from exc
    await close_asyncio_subprocess_transport(process)
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        detail = stderr_text or stdout.decode("utf-8", errors="replace").strip() or "unknown error"
        raise RuntimeError(f"Dreamina runner failed: {detail}")
    try:
        result = json.loads(stdout.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Dreamina runner returned invalid JSON: {stdout.decode('utf-8', errors='replace')[:500]}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError("Dreamina runner returned an invalid response payload")
    return result


async def _download_generated_image(url: str, output_path: Path, *, timeout_sec: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {}
    host = str(urlparse(url).hostname or "").strip().lower()
    if host.endswith("byteimg.com") or host.endswith("ibytedtos.com"):
        headers["Referer"] = "https://jimeng.jianying.com/"
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        output_path.write_bytes(response.content)


def _normalize_score(value: Any, *, fallback: float = 0.0) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except Exception:
        return round(max(0.0, min(1.0, float(fallback))), 3)


async def _rank_dreamina_candidates_by_reference(
    *,
    source_image_path: Path,
    candidate_paths: list[Path],
    prompt: str,
) -> dict[str, Any]:
    if len(candidate_paths) <= 1:
        return {
            "selected_index": 0 if candidate_paths else -1,
            "selected_reason": "single_candidate",
            "scores": [],
            "all_low_confidence": False,
        }
    ranking_prompt = (
        "你在做封面候选的一致性审核。"
        "第 1 张图是原始参考图，后面的图片依次是候选封面。"
        "你的首要目标不是看哪张更花哨，而是判断哪张最像同一个真实主体/同一件实物。"
        "重点看：主体类别、整体轮廓、结构比例、关键部件位置、材质观感、数量关系。"
        "如果候选把原物变成了另一种东西、明显变形、关键结构消失、部件数量错了、轮廓差异大，要严厉扣分。"
        "次要才看构图、清晰度和标题可读性。"
        "请返回 JSON："
        '{"best_number":2,"all_low_confidence":false,"reason":"","scores":[{"number":2,"subject_match":0.0,"deformation_risk":0.0,"title_readability":0.0,"overall":0.0,"reason":""}]}'
        f"\n封面 brief：{prompt[:1200]}"
    )
    content = await complete_with_images(
        ranking_prompt,
        [source_image_path, *candidate_paths],
        max_tokens=900,
        temperature=0.1,
        json_mode=True,
    )
    payload = json.loads(extract_json_text(content))
    raw_scores = payload.get("scores") if isinstance(payload, dict) else []
    scores: list[dict[str, Any]] = []
    for item in raw_scores if isinstance(raw_scores, list) else []:
        if not isinstance(item, dict):
            continue
        number = int(item.get("number") or 0)
        if number < 2 or number > len(candidate_paths) + 1:
            continue
        scores.append(
            {
                "number": number,
                "candidate_index": number - 2,
                "subject_match": _normalize_score(item.get("subject_match")),
                "deformation_risk": _normalize_score(item.get("deformation_risk")),
                "title_readability": _normalize_score(item.get("title_readability")),
                "overall": _normalize_score(item.get("overall")),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    selected_index = max(
        0,
        min(
            len(candidate_paths) - 1,
            int(payload.get("best_number") or 2) - 2,
        ),
    )
    if scores:
        selected_index = max(
            0,
            min(
                len(candidate_paths) - 1,
                max(scores, key=lambda item: (item["overall"], item["subject_match"], -item["deformation_risk"]))[
                    "candidate_index"
                ],
            )
        )
    return {
        "selected_index": selected_index,
        "selected_reason": str(payload.get("reason") or "").strip(),
        "scores": scores,
        "all_low_confidence": bool(payload.get("all_low_confidence", False)),
    }


async def _generate_with_dreamina_web(
    *,
    source_image_path: Path,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    settings = get_settings()
    requested_model = str(getattr(settings, "intelligent_copy_cover_image_model", "") or "").strip()
    safe_prompt = _sanitize_dreamina_prompt(prompt)
    alias = _sanitize_dreamina_reference_alias(source_image_path)
    request_spec = {
        "prompt": safe_prompt,
        "prompt_base64": base64.b64encode(safe_prompt.encode("utf-8")).decode("ascii"),
        "ratio": _resolve_dreamina_ratio(width, height),
        "reference_images": [{"path": str(source_image_path), "alias": alias}],
    }
    if requested_model:
        request_spec["model"] = requested_model
        request_spec["modelVersion"] = requested_model
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
    candidates = result_block.get("candidates") if isinstance(result_block.get("candidates"), list) else []
    selected_candidate = (
        result_block.get("selectedCandidate")
        if isinstance(result_block.get("selectedCandidate"), dict)
        else {}
    )
    response_meta = runner_response.get("responseMeta") if isinstance(runner_response.get("responseMeta"), dict) else {}
    selected_index = int(result_block.get("selectedCandidateIndex", result_block.get("selected_candidate_index", 0)) or 0)
    runner_selected_index = selected_index
    resolved_model = str(response_meta.get("resolved_model_version") or requested_model or "").strip()
    timeout_sec = float(max(30, int(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 90) or 90)))
    ranking_timeout_sec = float(max(10, min(timeout_sec, 45)))
    candidate_urls = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        if url:
            candidate_urls.append(url)
    consistency_assessment: dict[str, Any] | None = None
    if len(candidate_urls) > 1:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            candidate_paths: list[Path] = []
            for index, url in enumerate(candidate_urls, start=1):
                candidate_path = tmpdir_path / f"candidate-{index}.jpg"
                await _download_generated_image(url, candidate_path, timeout_sec=timeout_sec)
                candidate_paths.append(candidate_path)
            try:
                consistency_assessment = await asyncio.wait_for(
                    _rank_dreamina_candidates_by_reference(
                        source_image_path=source_image_path,
                        candidate_paths=candidate_paths,
                        prompt=prompt,
                    ),
                    timeout=ranking_timeout_sec,
                )
                scores = consistency_assessment.get("scores") if isinstance(consistency_assessment, dict) else []
                if (
                    isinstance(scores, list)
                    and scores
                    and _dreamina_consistency_ranking_should_override(
                        consistency_assessment,
                        runner_selected_index=runner_selected_index,
                    )
                ):
                    selected_index = max(
                        0,
                        min(len(candidate_urls) - 1, int(consistency_assessment.get("selected_index", selected_index) or 0)),
                    )
                image_url = candidate_urls[selected_index]
                selected_candidate = candidates[selected_index] if selected_index < len(candidates) else selected_candidate
                shutil.copy2(candidate_paths[selected_index], output_path)
            except Exception as exc:
                consistency_assessment = {
                    "selected_index": selected_index,
                    "selected_reason": "consistency_ranking_failed",
                    "scores": [],
                    "all_low_confidence": False,
                    "error": str(exc),
                    "timeout_sec": ranking_timeout_sec,
                }
                await _download_generated_image(image_url, output_path, timeout_sec=timeout_sec)
    else:
        await _download_generated_image(image_url, output_path, timeout_sec=timeout_sec)
        if candidate_urls:
            selected_index = max(0, min(len(candidate_urls) - 1, selected_index))
            selected_candidate = candidates[selected_index] if selected_index < len(candidates) else selected_candidate
    subject_match_scores = [
        _normalize_score(item.get("subject_match"))
        for item in (consistency_assessment or {}).get("scores", [])
        if isinstance(item, dict)
    ]
    deformation_risks = [
        _normalize_score(item.get("deformation_risk"))
        for item in (consistency_assessment or {}).get("scores", [])
        if isinstance(item, dict)
    ]
    selected_score = next(
        (
            item
            for item in (consistency_assessment or {}).get("scores", [])
            if isinstance(item, dict) and int(item.get("candidate_index", -1)) == selected_index
        ),
        {},
    )
    subject_consistency_score = _normalize_score(selected_score.get("subject_match"), fallback=1.0 if len(candidate_urls) <= 1 else 0.0)
    deformation_risk = _normalize_score(selected_score.get("deformation_risk"))
    subject_consistency_passed = subject_consistency_score >= 0.72 and deformation_risk <= 0.45
    return {
        "status": "completed",
        "backend": DREAMINA_WEB_IMAGE_BACKEND,
        "model": resolved_model or ("5.0" if request_spec["reference_images"] else "4.5"),
        "size": f"{int(width)}x{int(height)}",
        "ratio": request_spec["ratio"],
        "image_url": image_url,
        "selected_candidate_index": selected_index,
        "selected_candidate": selected_candidate,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "generation_status": str(runner_response.get("generationStatus") or "").strip(),
        "transport": str(response_meta.get("transport") or "").strip(),
        "submit_id": str(response_meta.get("submit_id") or "").strip(),
        "history_url": str(response_meta.get("history_url") or "").strip(),
        "reference_aliases": [alias],
        "subject_consistency_score": subject_consistency_score,
        "subject_consistency_passed": subject_consistency_passed,
        "deformation_risk": deformation_risk,
        "candidate_consistency_assessment": consistency_assessment,
        "subject_consistency_reason": str(selected_score.get("reason") or (consistency_assessment or {}).get("selected_reason") or "").strip(),
        "candidate_subject_match_max": max(subject_match_scores) if subject_match_scores else None,
        "candidate_deformation_risk_min": min(deformation_risks) if deformation_risks else None,
    }


def _dreamina_consistency_ranking_should_override(
    assessment: dict[str, Any] | None,
    *,
    runner_selected_index: int,
) -> bool:
    if not isinstance(assessment, dict) or bool(assessment.get("all_low_confidence")):
        return False
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), list) else []
    selected_index = int(assessment.get("selected_index", runner_selected_index) or 0)
    selected_score = next(
        (item for item in scores if isinstance(item, dict) and int(item.get("candidate_index", -1)) == selected_index),
        None,
    )
    if not isinstance(selected_score, dict):
        return False
    selected_overall = float(selected_score.get("overall") or 0.0)
    selected_subject = float(selected_score.get("subject_match") or 0.0)
    if selected_overall < 0.72 or selected_subject < 0.70:
        return False
    runner_score = next(
        (item for item in scores if isinstance(item, dict) and int(item.get("candidate_index", -1)) == runner_selected_index),
        None,
    )
    if not isinstance(runner_score, dict):
        return selected_overall >= 0.85 and selected_subject >= 0.80
    runner_overall = float(runner_score.get("overall") or 0.0)
    runner_subject = float(runner_score.get("subject_match") or 0.0)
    return (selected_overall - runner_overall) >= 0.12 or (selected_subject - runner_subject) >= 0.12

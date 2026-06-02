from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

import roughcut.config as config_mod
from roughcut.host.codex_bridge import run_codex_exec
from roughcut.providers.image_generation import generate_edited_cover_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate side-by-side cover outputs for Codex imagegen and MiniMax using the same request prompt."
    )
    parser.add_argument("request", type=Path, help="Path to one *.codex-imagegen.json request file.")
    parser.add_argument("--out-dir", type=Path, help="Directory for comparison outputs. Defaults next to the request.")
    parser.add_argument(
        "--backend",
        action="append",
        choices=("codex", "minimax"),
        dest="backends",
        help="Backend(s) to run. Repeatable. Default: run both.",
    )
    parser.add_argument("--codex-model", default="", help="Override the Codex exec model.")
    parser.add_argument("--minimax-model", default="image-01", help="Override the MiniMax image model.")
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_request(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request payload must be an object")
    return payload


def _map_path_to_host(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("path is empty")
    candidate = Path(text).expanduser()
    if candidate.exists():
        return candidate.resolve()
    normalized = text.replace("\\", "/")
    container_prefix = "/app/data/"
    if normalized.startswith(container_prefix):
        host_output_root = _repo_root() / "data" / "runtime"
        relative = normalized[len(container_prefix):].lstrip("/")
        return (host_output_root / Path(relative)).resolve()
    return candidate


def _resolve_existing_host_path(raw_path: str) -> Path:
    host_path = _map_path_to_host(raw_path)
    if host_path.exists():
        return host_path
    raise FileNotFoundError(f"Unable to resolve host path: {raw_path}")


def _make_output_dir(request_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        output_dir = explicit.expanduser().resolve()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_dir = request_path.parent / "_cover-ab" / f"{request_path.stem}-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _copy_reference_image(source_path: Path, output_dir: Path) -> Path:
    reference_path = output_dir / f"reference{source_path.suffix.lower() or '.jpg'}"
    shutil.copy2(source_path, reference_path)
    return reference_path


def _build_codex_exec_prompt(*, request: dict[str, Any], output_path: Path) -> str:
    prompt = str(request.get("prompt") or "").strip()
    return (
        "Use the attached image as the reference/edit target and generate exactly one final bitmap cover.\n"
        "Use Codex built-in image_gen or image edit capabilities, not any external image API.\n"
        "Follow this cover brief exactly:\n\n"
        f"{prompt}\n\n"
        "Hard requirements:\n"
        f"- Save the final bitmap exactly at this path: {output_path}\n"
        "- If an intermediate file is produced, copy or rename it to the exact output path.\n"
        "- Keep the subject identity unchanged.\n"
        "- Render the requested title text directly in the image.\n"
        "- Do not add extra text, watermarks, pseudo logos, or subtitles.\n"
        "- Return JSON only after the bitmap exists on disk.\n"
        '- Final response JSON must be: {"status":"completed","output_path":"<exact path>","notes":"short summary"}\n'
    )


def _run_codex_backend(
    *,
    request: dict[str, Any],
    reference_path: Path,
    output_path: Path,
    model_override: str,
) -> dict[str, Any]:
    runner = request.get("codex_runner") if isinstance(request.get("codex_runner"), dict) else {}
    model = str(model_override or runner.get("model") or "").strip()
    started = time.perf_counter()
    print(json.dumps({"stage": "codex_backend_start", "output_path": str(output_path), "model": model}, ensure_ascii=False), flush=True)
    try:
        result = run_codex_exec(
            {
                "repo_root": str(_repo_root()),
                "prompt": _build_codex_exec_prompt(request=request, output_path=output_path),
                "images": [str(reference_path)],
                "model": model,
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "output_path": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["status", "output_path", "notes"],
                    "additionalProperties": False,
                },
            }
        )
    except TimeoutError as exc:
        elapsed = round(time.perf_counter() - started, 3)
        print(json.dumps({"stage": "codex_backend_timeout", "elapsed_sec": elapsed, "error": str(exc)}, ensure_ascii=False), flush=True)
        if output_path.exists():
            return {
                "backend": "codex_builtin",
                "model": model or str(runner.get("model") or ""),
                "latency_sec": elapsed,
                "output_path": str(output_path),
                "warning": str(exc),
                "response": {
                    "status": "completed_with_timeout",
                    "output_path": str(output_path),
                    "notes": "bitmap exists but codex exec timed out before clean exit",
                },
            }
        raise
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        print(json.dumps({"stage": "codex_backend_error", "elapsed_sec": elapsed, "error": str(exc)}, ensure_ascii=False), flush=True)
        raise
    elapsed = round(time.perf_counter() - started, 3)
    print(json.dumps({"stage": "codex_backend_complete", "elapsed_sec": elapsed, "output_exists": output_path.exists()}, ensure_ascii=False), flush=True)
    if not output_path.exists():
        raise RuntimeError("Codex exec returned without writing the expected bitmap output.")
    stdout = str(result.get("stdout") or "").strip()
    payload: dict[str, Any] = {}
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
    return {
        "backend": "codex_builtin",
        "model": model or str(runner.get("model") or ""),
        "latency_sec": elapsed,
        "output_path": str(output_path),
        "response": payload,
    }


async def _generate_minimax_cover(
    *,
    reference_path: Path,
    output_path: Path,
    prompt: str,
    width: int,
    height: int,
    model: str,
) -> dict[str, Any]:
    saved_settings = config_mod._settings
    try:
        config_mod.apply_in_memory_runtime_overrides(
            {
                "intelligent_copy_cover_image_backend": "minimax_images_api",
                "intelligent_copy_cover_image_model": model,
            }
        )
        return await generate_edited_cover_image(
            source_image_path=reference_path,
            output_path=output_path,
            prompt=prompt,
            width=width,
            height=height,
        )
    finally:
        config_mod._settings = saved_settings


def _run_minimax_backend(
    *,
    request: dict[str, Any],
    reference_path: Path,
    output_path: Path,
    model: str,
) -> dict[str, Any]:
    target = request.get("target_size") if isinstance(request.get("target_size"), dict) else {}
    width = int(target.get("width") or 0)
    height = int(target.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("request target_size is missing width/height")
    started = time.perf_counter()
    metadata = asyncio.run(
        _generate_minimax_cover(
            reference_path=reference_path,
            output_path=output_path,
            prompt=str(request.get("prompt") or ""),
            width=width,
            height=height,
            model=model,
        )
    )
    elapsed = round(time.perf_counter() - started, 3)
    return {
        **metadata,
        "latency_sec": elapsed,
        "output_path": str(output_path),
    }


def main() -> int:
    args = parse_args()
    request_path = args.request.expanduser().resolve()
    request = _load_request(request_path)
    source_image_path = _resolve_existing_host_path(str(request.get("source_image_path") or ""))
    original_output_path = _map_path_to_host(str(request.get("output_path") or ""))
    output_dir = _make_output_dir(request_path, args.out_dir)
    reference_path = _copy_reference_image(source_image_path, output_dir)
    ext = original_output_path.suffix or ".jpg"
    selected_backends = args.backends or ["codex", "minimax"]

    manifest: dict[str, Any] = {
        "request_path": str(request_path),
        "reference_path": str(reference_path),
        "prompt": str(request.get("prompt") or ""),
        "target_size": request.get("target_size"),
        "results": {},
    }

    for backend in selected_backends:
        try:
            if backend == "codex":
                result = _run_codex_backend(
                    request=request,
                    reference_path=reference_path,
                    output_path=output_dir / f"codex{ext}",
                    model_override=str(args.codex_model or ""),
                )
            else:
                result = _run_minimax_backend(
                    request=request,
                    reference_path=reference_path,
                    output_path=output_dir / f"minimax{ext}",
                    model=str(args.minimax_model or "image-01"),
                )
            manifest["results"][backend] = {"ok": True, **result}
        except Exception as exc:
            manifest["results"][backend] = {"ok": False, "error": str(exc)}

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "manifest_path": str(manifest_path), "results": manifest["results"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

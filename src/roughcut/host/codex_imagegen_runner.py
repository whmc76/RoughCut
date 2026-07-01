from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any
import re

from roughcut.host.codex_bridge import _resolve_codex_command_candidates, run_codex_exec
from roughcut.providers.image_generation import mark_codex_imagegen_request_completed


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _output_path_was_written_during_current_attempt(output_path: Path, *, started_at: float) -> bool:
    if not output_path.exists():
        return False
    try:
        return output_path.stat().st_mtime >= float(started_at) - 1.0
    except OSError:
        return False


def fulfill_codex_imagegen_request(
    *,
    request_path: Path,
    repo_root: Path,
    timeout_sec: int = 360,
    model: str = "",
) -> dict[str, Any]:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Codex imagegen request must be a JSON object")
    recorded_output_path = str(payload.get("output_path") or "").strip()
    output_path = _resolve_runtime_mount_path(recorded_output_path, require_exists=False)
    reference_image_paths = _resolve_reference_image_paths(payload)
    source_image_path = reference_image_paths[0]
    prompt = str(payload.get("prompt") or "").strip()
    if not str(output_path):
        raise ValueError("Codex imagegen request missing output_path")
    if not str(source_image_path) or not source_image_path.exists():
        raise FileNotFoundError(f"Codex imagegen source image missing: {source_image_path}")
    if not prompt:
        raise ValueError("Codex imagegen request missing prompt")

    if str(payload.get("status") or "").strip().lower() == "completed" and output_path.exists():
        return {
            "status": "completed",
            "request_path": str(request_path),
            "output_path": str(output_path),
            "result_path": str(payload.get("result_path") or output_path),
            "already_completed": True,
        }

    command_name = str(
        os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_COMMAND", "") or "codex"
    ).strip()
    command_candidates = _resolve_codex_command_candidates(command_name)
    if not command_candidates:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")
    model_name = str(model or ((payload.get("codex_runner") or {}).get("model")) or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_MODEL", "")).strip()
    sandbox_mode = str(os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_SANDBOX", "danger-full-access") or "danger-full-access").strip()
    hard_timeout = max(30, int(timeout_sec or 360))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    last_error = ""
    for candidate_command in command_candidates:
        try:
            result = _run_single_codex_imagegen(
                command=candidate_command,
                repo_root=repo_root,
                reference_image_paths=reference_image_paths,
                prompt=_build_codex_imagegen_prompt(
                    prompt,
                    output_path=output_path,
                    reference_count=len(reference_image_paths),
                    reference_pack_contract=payload.get("reference_pack_contract"),
                ),
                output_path=output_path,
                model_name=model_name,
                sandbox_mode=sandbox_mode,
                timeout_sec=hard_timeout,
                started_at=started_at,
            )
            raw_result_path = Path(str(result.get("result_path") or ""))
            result_path = output_path if output_path.exists() else raw_result_path
            completed = mark_codex_imagegen_request_completed(
                request_path=request_path,
                output_path=output_path,
                result_path=result_path,
                recorded_output_path=recorded_output_path or None,
                session_id=str(result.get("session_id") or "").strip() or None,
                timed_out=bool(result.get("timed_out")),
            )
            return {
                "status": "completed",
                "request_path": str(request_path),
                "output_path": recorded_output_path or str(output_path),
                "result_path": str(result_path),
                "command": candidate_command,
                "session_id": result.get("session_id"),
                "timed_out": bool(result.get("timed_out")),
                "request_payload": completed,
            }
        except Exception as exc:
            last_error = f"{candidate_command}: {exc}"
            continue
    raise RuntimeError(last_error or "Codex imagegen execution failed")


def _build_codex_imagegen_prompt(
    brief: str,
    *,
    output_path: Path,
    reference_count: int = 1,
    reference_pack_contract: dict[str, Any] | None = None,
) -> str:
    contract = reference_pack_contract if isinstance(reference_pack_contract, dict) else {}
    reference_line = (
        "Use all attached images as a single same-product multi-angle reference pack."
        if int(reference_count or 0) > 1
        else "Use the attached image as the only reference/edit target."
    )
    multi_angle_policy = ""
    if int(reference_count or 0) > 1 or bool(contract.get("same_product_multi_angle")):
        multi_angle_policy = (
            "All attached images show the same real product or the same real comparison pair from different angles.\n"
            "Treat image 1 as the preferred hero-angle anchor.\n"
            "Infer the final composition from the majority hero view across the pack: if most references show a front view, three-quarter front view, or fuller hero angle, keep that as the final dominant view.\n"
            "Use minority side-profile, edge-on, or detail-only references only to preserve structure and surface details while the dominant front/hero composition stays primary.\n"
        )
    return (
        f"{reference_line}\n"
        f"{multi_angle_policy}"
        "Use Codex built-in image_gen or image editing capabilities to create exactly one final bitmap cover.\n"
        "Use only the built-in image generation capability for this request.\n"
        "Stay within this image generation request and its attached reference files.\n"
        "Follow this cover brief exactly:\n\n"
        f"{brief}\n\n"
        "Requirements:\n"
        "- Keep the product identity consistent with the reference.\n"
        "- When multiple reference images are attached, combine them to preserve the same real product identity and cross-angle consistency.\n"
        "- Use the reference set to keep the final cover anchored on the intended hero view.\n"
        "- The bitmap itself must be the final publishable cover with requested title text integrated.\n"
        "- Render the requested brand line, main title, subtitle, and hook text directly in the bitmap when the brief asks for them.\n"
        "- Keep readable visual text limited to the brief's requested brand line, main title, subtitle, and hook text.\n"
        "- Keep the subject readable after typography placement, with main product details visible.\n"
        f"- The final bitmap must be written exactly to this path before you finish: {output_path}\n"
        "- If direct bitmap rendering in code is needed, save the final image to that exact output path.\n"
        "- After generating the best final bitmap, stop.\n"
        '- Final response JSON only: {"status":"completed","notes":"short summary"}\n'
    )


def _run_single_codex_imagegen(
    *,
    command: str,
    repo_root: Path,
    reference_image_paths: list[Path],
    prompt: str,
    output_path: Path,
    model_name: str,
    sandbox_mode: str,
    timeout_sec: int,
    started_at: float,
) -> dict[str, Any]:
    timed_out = False
    try:
        exec_result = run_codex_exec(
            {
                "repo_root": str(repo_root),
                "prompt": prompt,
                "images": [str(path) for path in reference_image_paths],
                "model": model_name,
                "sandbox": sandbox_mode,
                "timeout_sec": timeout_sec,
                "command": command,
            }
        )
    except TimeoutError as exc:
        timed_out = True
        exec_result = {
            "stdout": "",
            "stderr": str(exc),
            "excerpt": str(exc),
        }

    stdout = str(exec_result.get("stdout") or "")
    stderr = str(exec_result.get("stderr") or "")
    excerpt = str(exec_result.get("excerpt") or "")
    combined = "\n".join(part for part in (stdout, stderr, excerpt) if part)
    session_id = _extract_codex_session_id(combined)
    allowed_roots = _generated_image_search_roots(output_path=output_path)
    generated = output_path if _output_path_was_written_during_current_attempt(output_path, started_at=started_at) else None
    if generated is None:
        generated = _extract_generated_image_path_from_text(
            combined,
            allowed_roots=allowed_roots,
            started_at=started_at,
        )
        if generated is not None and generated.resolve() == output_path.resolve():
            if not _output_path_was_written_during_current_attempt(output_path, started_at=started_at):
                generated = None
    if generated is None:
        generated = _resolve_generated_image(session_id=session_id, started_at=started_at)
        if generated is not None and generated.resolve() == output_path.resolve():
            if not _output_path_was_written_during_current_attempt(output_path, started_at=started_at):
                generated = None
    if generated is None:
        if timed_out:
            raise TimeoutError(f"codex imagegen timed out after {timeout_sec}s and no generated image was found")
        raise RuntimeError(stderr or stdout or "codex imagegen finished but no generated image was found")
    if generated.resolve() != output_path.resolve():
        shutil.copy2(generated, output_path)
    return {
        "session_id": session_id,
        "result_path": str(generated),
        "timed_out": timed_out,
    }


def _resolve_reference_image_paths(payload: dict[str, Any]) -> list[Path]:
    raw_references = payload.get("reference_image_paths")
    candidates = raw_references if isinstance(raw_references, list) and raw_references else [payload.get("source_image_path")]
    resolved: list[Path] = []
    for raw_path in candidates:
        text = str(raw_path or "").strip()
        if not text:
            continue
        path = _resolve_runtime_mount_path(text, require_exists=True)
        if path in resolved:
            continue
        resolved.append(path)
    if not resolved:
        raise FileNotFoundError("Codex imagegen reference image missing")
    return resolved


def _extract_codex_session_id(text: str) -> str:
    for line in str(text or "").splitlines():
        if "session id:" not in line.lower():
            continue
        _, _, tail = line.partition(":")
        value = tail.strip()
        if value:
            return value
    return ""


def _extract_generated_image_path_from_text(
    text: str,
    *,
    allowed_roots: list[Path] | None = None,
    started_at: float | None = None,
) -> Path | None:
    if not text:
        return None
    roots = [root.resolve() for root in (allowed_roots or []) if isinstance(root, Path)]
    candidates: list[Path] = []
    for match in re.findall(r"[A-Za-z]:\\[^\r\n]+?\.(?:png|jpg|jpeg|webp)", text, flags=re.IGNORECASE):
        path = Path(match.strip().strip('"'))
        try:
            resolved = path.resolve()
            if not resolved.exists() or not resolved.is_file():
                continue
            if started_at is not None and resolved.stat().st_mtime < float(started_at) - 30:
                continue
            if roots:
                try:
                    if not any(resolved.is_relative_to(root) for root in roots):
                        continue
                except AttributeError:
                    if not any(str(resolved).lower().startswith(str(root).lower()) for root in roots):
                        continue
            candidates.append(resolved)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _resolve_generated_image(*, session_id: str, started_at: float) -> Path | None:
    roots: list[Path] = []
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        roots.append(Path(codex_home) / "generated_images")
    roots.append(Path.home() / ".codex" / "generated_images")

    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if session_id:
            session_root = root / session_id
            if session_root.exists():
                candidates.extend(_list_generated_images(session_root))
        else:
            for session_root in root.iterdir():
                if session_root.is_dir():
                    candidates.extend(_list_generated_images(session_root))
    candidates = [
        path for path in candidates
        if path.suffix.lower() in _IMAGE_EXTENSIONS and path.stat().st_mtime >= started_at - 30
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _generated_image_search_roots(*, output_path: Path) -> list[Path]:
    roots = [output_path.parent]
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        roots.append(Path(codex_home) / "generated_images")
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


def _list_generated_images(root: Path) -> list[Path]:
    try:
        return [path for path in root.rglob("*") if path.is_file()]
    except Exception:
        return []


def _resolve_runtime_mount_path(raw_path: str, *, require_exists: bool) -> Path:
    raw_text = str(raw_path or "").strip().strip('"')
    if not raw_text:
        return Path()

    normalized = raw_text.replace("\\", "/")
    container_prefix = "/app/data/"
    if normalized.startswith(container_prefix):
        workspace_root = Path(__file__).resolve().parents[3]
        host_output_root = Path(
            os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT", "") or (workspace_root / "data" / "runtime")
        ).expanduser()
        relative = normalized[len(container_prefix):].lstrip("/")
        mapped = (host_output_root / Path(relative)).resolve()
        if mapped.exists() or not require_exists:
            return mapped

    candidate = Path(raw_text).expanduser()
    try:
        if candidate.exists() or not require_exists:
            return candidate.resolve()
    except OSError:
        pass

    if require_exists:
        raise FileNotFoundError(f"Host runtime path does not exist: {raw_text}")
    return candidate

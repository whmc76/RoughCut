from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from roughcut.host.codex_bridge import _resolve_codex_command_candidates, _terminate_process_tree
from roughcut.providers.image_generation import mark_codex_imagegen_request_completed
from roughcut.telegram.output_codec import decode_process_output


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


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
    source_image_path = _resolve_runtime_mount_path(str(payload.get("source_image_path") or ""), require_exists=True)
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
                source_image_path=source_image_path,
                prompt=_build_codex_imagegen_prompt(prompt),
                output_path=output_path,
                model_name=model_name,
                sandbox_mode=sandbox_mode,
                timeout_sec=hard_timeout,
                started_at=started_at,
            )
            completed = mark_codex_imagegen_request_completed(
                request_path=request_path,
                output_path=output_path,
                result_path=Path(result["result_path"]),
                recorded_output_path=recorded_output_path or None,
            )
            return {
                "status": "completed",
                "request_path": str(request_path),
                "output_path": recorded_output_path or str(output_path),
                "result_path": str(result["result_path"]),
                "command": candidate_command,
                "session_id": result.get("session_id"),
                "timed_out": bool(result.get("timed_out")),
                "request_payload": completed,
            }
        except Exception as exc:
            last_error = f"{candidate_command}: {exc}"
            continue
    raise RuntimeError(last_error or "Codex imagegen execution failed")


def _build_codex_imagegen_prompt(brief: str) -> str:
    return (
        "Use the attached image as the only reference/edit target.\n"
        "Use Codex built-in image_gen or image editing capabilities to create exactly one final bitmap cover.\n"
        "Do not use any external image APIs.\n"
        "Do not inspect the repository or run unrelated shell commands.\n"
        "Follow this cover brief exactly:\n\n"
        f"{brief}\n\n"
        "Requirements:\n"
        "- Keep the product identity consistent with the reference.\n"
        "- The bitmap itself must be the final publishable cover, not a text-free base image.\n"
        "- Render the requested brand line, main title, subtitle, and hook text directly in the bitmap when the brief asks for them.\n"
        "- Do not add any extra subtitles, slogans, logos, watermarks, or pseudo text beyond what the brief explicitly requests.\n"
        "- Keep the subject readable after typography placement; do not let title effects cover the main product details.\n"
        "- After generating the best final bitmap, stop.\n"
        '- Final response JSON only: {"status":"completed","notes":"short summary"}\n'
    )


def _run_single_codex_imagegen(
    *,
    command: str,
    repo_root: Path,
    source_image_path: Path,
    prompt: str,
    output_path: Path,
    model_name: str,
    sandbox_mode: str,
    timeout_sec: int,
    started_at: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="roughcut-host-imagegen-") as temp_dir:
        stdout_override_path = Path(temp_dir) / "last-message.txt"
        cmd = [
            command,
            "-a",
            "never",
        ]
        if model_name:
            cmd.extend(["-m", model_name])
        cmd.extend(
            [
                "exec",
                "--color",
                "never",
                "-C",
                str(repo_root),
                "-s",
                sandbox_mode,
                "-o",
                str(stdout_override_path),
                "-i",
                str(source_image_path),
                "-",
            ]
        )
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(repo_root),
            env={**os.environ.copy(), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        timed_out = False
        session_id = ""
        generated: Path | None = None
        try:
            if process.stdin is None:
                raise RuntimeError("codex imagegen stdin is unavailable")
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
            deadline = time.time() + timeout_sec
            stdout_bytes = b""
            stderr_bytes = b""
            while True:
                session_id = _read_codex_session_id(stdout_override_path, fallback=session_id)
                if session_id:
                    generated = _resolve_generated_image(session_id=session_id, started_at=started_at)
                if session_id and generated is not None:
                    _terminate_process_tree(process)
                    try:
                        stdout_bytes, stderr_bytes = process.communicate(timeout=5)
                    except Exception:
                        stdout_bytes = b""
                        stderr_bytes = b""
                    break
                if process.poll() is not None:
                    stdout_bytes = process.stdout.read() if process.stdout is not None else b""
                    stderr_bytes = process.stderr.read() if process.stderr is not None else b""
                    break
                if time.time() >= deadline:
                    raise subprocess.TimeoutExpired(cmd, timeout_sec, output=stdout_bytes, stderr=stderr_bytes)
                time.sleep(1.0)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            _terminate_process_tree(process)
            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=5)
            except Exception:
                stdout_bytes = exc.output or b""
                stderr_bytes = exc.stderr or b""
        stdout = decode_process_output(stdout_override_path.read_bytes()) if stdout_override_path.exists() else decode_process_output(stdout_bytes)
        stderr = decode_process_output(stderr_bytes)
        combined = "\n".join(part for part in (stdout, stderr) if part)
        session_id = _extract_codex_session_id(combined) or session_id
        generated = generated or _resolve_generated_image(session_id=session_id, started_at=started_at)
        if generated is None:
            if timed_out:
                raise TimeoutError(f"codex imagegen timed out after {timeout_sec}s and no generated image was found")
            if process.returncode != 0:
                raise RuntimeError(stderr or stdout or f"codex exited with code {process.returncode}")
            raise RuntimeError("codex imagegen finished but no generated image was found")
        shutil.copy2(generated, output_path)
        return {
            "session_id": session_id,
            "result_path": str(generated),
            "timed_out": timed_out,
        }


def _read_codex_session_id(path: Path, *, fallback: str = "") -> str:
    try:
        if path.exists():
            value = _extract_codex_session_id(decode_process_output(path.read_bytes()))
            if value:
                return value
    except Exception:
        pass
    return str(fallback or "")


def _extract_codex_session_id(text: str) -> str:
    for line in str(text or "").splitlines():
        if "session id:" not in line.lower():
            continue
        _, _, tail = line.partition(":")
        value = tail.strip()
        if value:
            return value
    return ""


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

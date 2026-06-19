from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from roughcut.telegram.output_codec import decode_process_output


_WINDOWS_EXECUTABLE_SUFFIXES = {".exe", ".cmd", ".bat", ".com"}
_RETRIABLE_CODEX_LAUNCHER_ERROR_MARKERS = (
    "requires a newer version of codex",
)


def _is_direct_process_command(path: str) -> bool:
    if os.name != "nt":
        return True
    suffix = Path(path).suffix.lower()
    return suffix in _WINDOWS_EXECUTABLE_SUFFIXES


def _append_command_candidate(candidates: list[str], value: str | None, *, allow_shell_script: bool = False) -> None:
    if not value:
        return
    normalized = str(value).strip()
    if not normalized:
        return
    if not allow_shell_script and not _is_direct_process_command(normalized):
        return
    if normalized not in candidates:
        candidates.append(normalized)


def _resolve_codex_command_candidates(command_name: str) -> list[str]:
    normalized_command = str(command_name or "").strip().lower()
    candidates: list[str] = []

    if os.name == "nt" and normalized_command == "codex":
        for launcher_name in ("codex.cmd", "codex.bat", "codex.exe", "codex"):
            _append_command_candidate(candidates, shutil.which(launcher_name))
    else:
        _append_command_candidate(candidates, shutil.which(command_name), allow_shell_script=os.name != "nt")

    explicit = candidates[0] if candidates else shutil.which(command_name)
    explicit_path = Path(explicit) if explicit else None

    path_candidates: list[Path] = []

    windows_apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    if windows_apps.exists():
        for sibling_name in ("codex.cmd", "codex.exe", "codex"):
            candidate = windows_apps / sibling_name
            if candidate.exists():
                path_candidates.append(candidate)

    codex_app_bin_root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if codex_app_bin_root.exists():
        for child in sorted(codex_app_bin_root.iterdir(), key=lambda item: item.name, reverse=True):
            candidate = child / "codex.exe"
            if candidate.exists():
                path_candidates.append(candidate)

    package_root = Path(r"C:\Program Files\WindowsApps")
    if package_root.exists():
        for child in sorted(package_root.glob("OpenAI.Codex_*"), reverse=True):
            candidate = child / "app" / "resources" / "codex.exe"
            if candidate.exists():
                path_candidates.append(candidate)

    if explicit_path is not None:
        for sibling_name in ("codex.cmd", "codex.exe", "codex"):
            sibling = explicit_path.with_name(sibling_name)
            if sibling.exists():
                path_candidates.append(sibling)

    for candidate in path_candidates:
        _append_command_candidate(candidates, str(candidate))
    if explicit_path is not None:
        _append_command_candidate(candidates, str(explicit_path), allow_shell_script=os.name != "nt")
    return candidates


def _resolve_codex_command(command_name: str) -> str | None:
    candidates = _resolve_codex_command_candidates(command_name)
    return candidates[0] if candidates else None


def _is_retriable_codex_launcher_error(stdout: str, stderr: str) -> bool:
    text = f"{stderr}\n{stdout}".strip().lower()
    return any(marker in text for marker in _RETRIABLE_CODEX_LAUNCHER_ERROR_MARKERS)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def run_codex_exec(payload: dict[str, Any]) -> dict[str, Any]:
    repo_root = Path(str(payload.get("repo_root") or ".")).resolve()
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    image_paths = _resolve_codex_image_paths(payload.get("images"))

    command_name = str(
        payload.get("command")
        or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_COMMAND", "")
        or "codex"
    ).strip()
    command_candidates = _resolve_codex_command_candidates(command_name)
    if not command_candidates:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")

    model_name = str(payload.get("model") or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_MODEL", "")).strip()
    sandbox_mode = str(
        payload.get("sandbox")
        or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_SANDBOX", "danger-full-access")
        or "danger-full-access"
    ).strip()
    timeout_sec = max(
        30,
        int(
            payload.get("timeout_sec")
            or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_TIMEOUT_SEC", "900")
            or "900"
        ),
    )

    with tempfile.TemporaryDirectory(prefix="roughcut-host-codex-") as temp_dir:
        print(json.dumps({"stage": "run_codex_exec_start", "repo_root": str(repo_root), "image_count": len(image_paths)}, ensure_ascii=False), flush=True)
        stdout_override_path = Path(temp_dir) / "last-message.txt"
        output_schema = payload.get("output_schema")
        output_schema_path: Path | None = None
        if isinstance(output_schema, dict):
            output_schema_path = Path(temp_dir) / "output-schema.json"
            output_schema_path.write_text(json.dumps(output_schema, ensure_ascii=False), encoding="utf-8")
        elif output_schema:
            output_schema_path = Path(str(output_schema)).resolve()
        last_start_error: OSError | None = None
        retriable_launcher_errors: list[str] = []
        for candidate_command in command_candidates:
            print(json.dumps({"stage": "run_codex_exec_candidate", "command": candidate_command}, ensure_ascii=False), flush=True)
            command = [
                candidate_command,
                "-a",
                "never",
            ]
            if model_name:
                command.extend(["-m", model_name])
            command.extend(
                [
                    "exec",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--color",
                    "never",
                    "-C",
                    str(repo_root),
                    "-s",
                    sandbox_mode,
                    "-o",
                    str(stdout_override_path),
                ]
            )
            if output_schema_path is not None:
                command.extend(["--output-schema", str(output_schema_path)])
            for image_path in image_paths:
                command.extend(["-i", str(image_path)])
            command.append("-")
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(repo_root),
                    env={**os.environ.copy(), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")},
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                last_start_error = exc
                print(json.dumps({"stage": "run_codex_exec_spawn_error", "command": candidate_command, "error": str(exc)}, ensure_ascii=False), flush=True)
                continue
            process_pid = getattr(process, "pid", None)
            print(json.dumps({"stage": "run_codex_exec_spawned", "command": candidate_command, "pid": process_pid}, ensure_ascii=False), flush=True)
            try:
                stdout_bytes, stderr_bytes = process.communicate(
                    input=prompt.encode("utf-8"),
                    timeout=timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                print(json.dumps({"stage": "run_codex_exec_timeout", "command": candidate_command, "pid": process_pid, "timeout_sec": timeout_sec}, ensure_ascii=False), flush=True)
                _terminate_process_tree(process)
                try:
                    stdout_bytes, stderr_bytes = process.communicate(timeout=5)
                except Exception:
                    stdout_bytes = exc.output or b""
                    stderr_bytes = exc.stderr or b""
                stdout = (
                    decode_process_output(stdout_override_path.read_bytes())
                    if stdout_override_path.exists()
                    else decode_process_output(stdout_bytes)
                )
                stderr = decode_process_output(stderr_bytes)
                raise TimeoutError(
                    f"codex exec timed out after {timeout_sec}s"
                    + (f": {stderr.strip()}" if str(stderr or "").strip() else "")
                )
            stdout = decode_process_output(stdout_override_path.read_bytes()) if stdout_override_path.exists() else ""
            if not stdout:
                stdout = decode_process_output(stdout_bytes)
            stderr = decode_process_output(stderr_bytes)
            print(json.dumps({"stage": "run_codex_exec_process_exit", "command": candidate_command, "pid": process_pid, "returncode": process.returncode, "stdout_len": len(stdout), "stderr_len": len(stderr)}, ensure_ascii=False), flush=True)
            excerpt = stdout or stderr
            if len(excerpt) > 3500:
                excerpt = excerpt[:3484].rstrip() + "\n...[truncated]"
            if process.returncode != 0:
                error_text = stderr or stdout or f"codex exited with code {process.returncode}"
                if _is_retriable_codex_launcher_error(stdout, stderr):
                    retriable_launcher_errors.append(f"{candidate_command}: {error_text}")
                    continue
                raise RuntimeError(error_text)
            return {
                "provider": "acp",
                "backend": "codex",
                "command": candidate_command,
                "stdout": stdout,
                "stderr": stderr,
                "excerpt": excerpt,
                "returncode": process.returncode,
                "host_bridge": True,
            }
        if last_start_error is not None:
            raise last_start_error
        if retriable_launcher_errors:
            joined = "\n\n".join(retriable_launcher_errors)
            raise RuntimeError(f"All Codex command candidates rejected the requested model:\n{joined}")
        raise RuntimeError(f"Codex command could not be started: {command_name}")


def _resolve_codex_image_paths(raw_images: Any) -> list[Path]:
    if raw_images in (None, ""):
        return []
    if not isinstance(raw_images, list):
        raise ValueError("images must be a list of file paths")
    image_paths: list[Path] = []
    for raw_image in raw_images:
        image_path = Path(str(raw_image or "").strip().strip('"')).expanduser()
        if not str(image_path):
            continue
        resolved = image_path.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise ValueError(f"Codex image path does not exist or is not a file: {image_path}")
        image_paths.append(resolved)
    return image_paths

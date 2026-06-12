from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from roughcut.host.codex_bridge import run_codex_exec
from roughcut.host.file_manager import open_in_file_manager
from roughcut.host.codex_imagegen_runner import fulfill_codex_imagegen_request

_MATERIALIZE_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".m4v",
    ".webm",
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
_SMART_COPY_EXCLUDED_TOP_LEVEL_DIRS = frozenset({"_publication_runtime"})
_SMART_COPY_MANAGED_DIRS = frozenset({"_meta", "_copy", "_cover"})
_SMART_COPY_ROOT_GENERATED_FILE_PATTERNS = (
    re.compile(r"^\d{2}-.+-cover\.jpg$", re.IGNORECASE),
    re.compile(r"^\d{2}-.+\.md$", re.IGNORECASE),
)
_SMART_COPY_ROOT_LEGACY_INTERNAL_FILE_PATTERNS = (
    re.compile(r"^\d{2}-.+-(titles|body|tags)\.txt$", re.IGNORECASE),
    re.compile(r"^00-cover-.+\.(jpg|codex-imagegen\.json|codex-imagegen-reference\.jpg)$", re.IGNORECASE),
    re.compile(r"^00-highlight-cover-source\.(jpg|json)$", re.IGNORECASE),
    re.compile(r"^00-highlight-candidates-sheet\.jpg$", re.IGNORECASE),
)
_SMART_COPY_ROOT_LEGACY_INTERNAL_FILENAMES = {
    "smart-copy.json",
    "platform-packaging.json",
    "platform-packaging.md",
}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _make_handler(expected_token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.rstrip("/") == "/healthz":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self):
            normalized_path = self.path.rstrip("/")
            if normalized_path not in {
                "/v1/codex/exec",
                "/v1/host/path-suggestions",
                "/v1/host/materialize-directory",
                "/v1/host/sync-smart-copy",
                "/v1/host/complete-codex-imagegen",
                "/v1/host/open-path",
            }:
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            auth_header = str(self.headers.get("Authorization") or "").strip()
            if expected_token and auth_header != f"Bearer {expected_token}":
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                if normalized_path == "/v1/host/path-suggestions":
                    result = {"suggestions": suggest_host_directory_paths(payload)}
                elif normalized_path == "/v1/host/materialize-directory":
                    result = materialize_host_directory(payload)
                elif normalized_path == "/v1/host/sync-smart-copy":
                    result = sync_smart_copy_directory(payload)
                elif normalized_path == "/v1/host/complete-codex-imagegen":
                    result = complete_codex_imagegen_request(payload)
                elif normalized_path == "/v1/host/open-path":
                    result = open_host_path(payload)
                else:
                    result = run_codex_exec(_normalize_codex_exec_payload(payload))
            except Exception as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            _json_response(self, HTTPStatus.OK, result)

        def log_message(self, format: str, *args):
            return

    return Handler


def suggest_host_directory_paths(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw_query = str(payload.get("query") or "").strip().strip('"')
    safe_limit = max(1, min(int(payload.get("limit") or 12), 30))
    if not raw_query:
        return []

    base_dir, prefix = _split_directory_suggestion_query(raw_query)
    if base_dir is None:
        return []

    try:
        if not base_dir.exists() or not base_dir.is_dir():
            return []
    except OSError:
        return []

    prefix_lower = prefix.casefold()
    starts_with: list[Path] = []
    contains: list[Path] = []
    try:
        with os.scandir(base_dir) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue
                name_lower = entry.name.casefold()
                if not prefix_lower or name_lower.startswith(prefix_lower):
                    starts_with.append(Path(entry.path))
                elif prefix_lower in name_lower:
                    contains.append(Path(entry.path))
    except OSError:
        return []

    suggestions: list[dict[str, str]] = []
    for item in sorted(starts_with, key=lambda path: path.name.casefold()) + sorted(contains, key=lambda path: path.name.casefold()):
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item.absolute()
        suggestions.append(
            {
                "path": str(resolved),
                "label": item.name,
                "parent": str(base_dir),
                "kind": "folder",
            }
        )
        if len(suggestions) >= safe_limit:
            break
    return suggestions


def materialize_host_directory(payload: dict[str, Any]) -> dict[str, Any]:
    raw_folder_path = str(payload.get("folder_path") or "").strip().strip('"')
    if not raw_folder_path:
        raise ValueError("folder_path is required")

    source_dir = Path(raw_folder_path).expanduser()
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError("directory does not exist or is not accessible")

    repo_root = Path(__file__).resolve().parents[1]
    host_output_root = Path(os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT", "") or (repo_root / "data" / "runtime")).expanduser()
    container_output_root = str(payload.get("container_output_root") or "/app/data").strip() or "/app/data"
    digest = hashlib.sha1(str(source_dir.resolve()).casefold().encode("utf-8", errors="ignore")).hexdigest()[:16]
    target_dir = host_output_root / "host-intelligent-copy" / f"{digest}-{_sanitize_path_name(source_dir.name)}"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, Any]] = []
    for source_file in sorted((item for item in source_dir.iterdir() if item.is_file()), key=lambda item: item.name.casefold()):
        if source_file.suffix.lower() not in _MATERIALIZE_SUFFIXES:
            continue
        target_file = target_dir / source_file.name
        if _should_copy_file(source_file, target_file):
            shutil.copy2(source_file, target_file)
        copied.append(
            {
                "source_path": str(source_file),
                "path": _container_path_for_materialized_file(target_file, host_output_root, container_output_root),
                "name": source_file.name,
                "size": source_file.stat().st_size,
            }
        )

    source_material_dir = source_dir / "smart-copy"
    if source_material_dir.exists() and source_material_dir.is_dir():
        _sync_smart_copy_tree(source_material_dir, target_dir / "smart-copy")
    else:
        stale_material_dir = target_dir / "smart-copy"
        if stale_material_dir.exists():
            shutil.rmtree(stale_material_dir, ignore_errors=True)

    return {
        "source_folder_path": str(source_dir.resolve()),
        "folder_path": _container_path_for_materialized_file(target_dir, host_output_root, container_output_root),
        "host_folder_path": str(target_dir.resolve()),
        "files": copied,
    }


def sync_smart_copy_directory(payload: dict[str, Any]) -> dict[str, Any]:
    source_material_dir = Path(_host_path_for_runtime_mount(payload.get("source_material_dir"), require_exists=True))
    if not source_material_dir.exists() or not source_material_dir.is_dir():
        raise ValueError("source smart-copy directory does not exist")

    raw_target_folder = str(payload.get("target_folder_path") or "").strip().strip('"')
    if not raw_target_folder:
        raise ValueError("target_folder_path is required")
    target_folder = Path(raw_target_folder).expanduser()
    if target_folder.exists() and not target_folder.is_dir():
        raise ValueError("target_folder_path is not a directory")
    target_folder.mkdir(parents=True, exist_ok=True)

    target_material_dir = target_folder / "smart-copy"
    copied_files = _sync_smart_copy_tree(source_material_dir, target_material_dir)
    return {
        "source_material_dir": str(source_material_dir.resolve()),
        "target_material_dir": str(target_material_dir.resolve()),
        "copied_file_count": copied_files,
    }


def complete_codex_imagegen_request(payload: dict[str, Any]) -> dict[str, Any]:
    request_path = _host_path_for_runtime_mount(payload.get("request_path"), require_exists=True)
    repo_root = Path(_host_repo_root_for_codex(payload.get("repo_root")))
    timeout_sec = max(30, int(payload.get("timeout_sec") or 360))
    model = str(payload.get("model") or "").strip()
    return fulfill_codex_imagegen_request(
        request_path=Path(request_path),
        repo_root=repo_root,
        timeout_sec=timeout_sec,
        model=model,
    )


def open_host_path(payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = payload.get("path")
    target_path = Path(_host_path_for_runtime_mount(raw_path, require_exists=True))
    open_in_file_manager(target_path)
    return {
        "path": str(target_path.resolve()),
        "kind": "file" if target_path.is_file() else "folder",
    }


def _normalize_codex_exec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["repo_root"] = _host_repo_root_for_codex(payload.get("repo_root"))
    images = payload.get("images")
    if isinstance(images, list):
        normalized["images"] = [_host_path_for_codex_image(path) for path in images]
    return normalized


def _host_repo_root_for_codex(raw_path: Any) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    raw_text = str(raw_path or "").strip().strip('"')
    if not raw_text:
        return str(repo_root)
    normalized_text = raw_text.replace("\\", "/").rstrip("/")
    if normalized_text in {"/app", "/workspace"} or normalized_text.startswith(("/app/", "/workspace/")):
        return str(repo_root)
    candidate = Path(raw_text).expanduser()
    try:
        if candidate.exists() and candidate.is_dir():
            return str(candidate.resolve())
    except OSError:
        pass
    return str(repo_root)


def _host_path_for_codex_image(raw_path: Any) -> str:
    return _host_path_for_runtime_mount(raw_path, require_exists=True)


def _host_path_for_runtime_mount(raw_path: Any, *, require_exists: bool) -> str:
    raw_text = str(raw_path or "").strip().strip('"')
    if not raw_text:
        return raw_text

    container_prefix = "/app/data/"
    normalized_text = raw_text.replace("\\", "/")
    if normalized_text.startswith(container_prefix):
        repo_root = Path(__file__).resolve().parents[1]
        host_output_root = Path(os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT", "") or (repo_root / "data" / "runtime")).expanduser()
        relative = normalized_text[len(container_prefix):].lstrip("/")
        mapped = (host_output_root / Path(relative)).resolve()
        if mapped.exists() or not require_exists:
            return str(mapped)

    candidate = Path(raw_text).expanduser()
    try:
        if candidate.exists() or not require_exists:
            return str(candidate.resolve())
    except OSError:
        pass

    if require_exists:
        raise FileNotFoundError(f"Host path does not exist: {raw_text}")
    return raw_text


def _should_copy_file(source_file: Path, target_file: Path) -> bool:
    if not target_file.exists():
        return True
    try:
        source_stat = source_file.stat()
        target_stat = target_file.stat()
    except OSError:
        return True
    return source_stat.st_size != target_stat.st_size or int(source_stat.st_mtime) > int(target_stat.st_mtime)


def _sync_smart_copy_tree(source_dir: Path, target_dir: Path) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    _remove_top_level_dirs(target_dir, _SMART_COPY_EXCLUDED_TOP_LEVEL_DIRS)
    copied_files = _copy_tree_contents(
        source_dir,
        target_dir,
        exclude_top_level_names=_SMART_COPY_EXCLUDED_TOP_LEVEL_DIRS,
    )
    _remove_legacy_root_internal_files(target_dir)
    _prune_managed_subtrees(source_dir, target_dir)
    _prune_missing_root_generated_deliverables(source_dir, target_dir)
    return copied_files


def _copy_tree_contents(
    source_dir: Path,
    target_dir: Path,
    *,
    exclude_top_level_names: set[str] | frozenset[str] | None = None,
) -> int:
    copied_files = 0
    for source_path in sorted(source_dir.rglob("*")):
        relative = source_path.relative_to(source_dir)
        if _relative_path_starts_with(relative, exclude_top_level_names):
            continue
        target_path = target_dir / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if _should_copy_file(source_path, target_path):
            shutil.copy2(source_path, target_path)
            copied_files += 1
    return copied_files


def _relative_path_starts_with(relative: Path, names: set[str] | frozenset[str] | None) -> bool:
    if not names:
        return False
    return bool(relative.parts) and relative.parts[0] in names


def _remove_top_level_dirs(target_dir: Path, dir_names: set[str] | frozenset[str]) -> None:
    for name in dir_names:
        candidate = target_dir / name
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)


def _remove_legacy_root_internal_files(target_dir: Path) -> None:
    if not target_dir.exists():
        return
    for child in target_dir.iterdir():
        if not child.is_file():
            continue
        name = child.name
        if name in _SMART_COPY_ROOT_LEGACY_INTERNAL_FILENAMES or any(
            pattern.fullmatch(name) for pattern in _SMART_COPY_ROOT_LEGACY_INTERNAL_FILE_PATTERNS
        ):
            child.unlink(missing_ok=True)


def _prune_managed_subtrees(source_dir: Path, target_dir: Path) -> None:
    for dirname in _SMART_COPY_MANAGED_DIRS:
        source_subdir = source_dir / dirname
        target_subdir = target_dir / dirname
        if not source_subdir.exists():
            if target_subdir.exists():
                shutil.rmtree(target_subdir, ignore_errors=True)
            continue
        _prune_missing_tree_contents(source_subdir, target_subdir)


def _prune_missing_tree_contents(source_dir: Path, target_dir: Path) -> None:
    if not target_dir.exists():
        return
    for target_path in sorted(target_dir.rglob("*"), reverse=True):
        relative = target_path.relative_to(target_dir)
        source_path = source_dir / relative
        if source_path.exists():
            continue
        if target_path.is_dir():
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            target_path.unlink(missing_ok=True)


def _prune_missing_root_generated_deliverables(source_dir: Path, target_dir: Path) -> None:
    if not target_dir.exists():
        return
    for target_path in target_dir.iterdir():
        if not target_path.is_file():
            continue
        if not any(pattern.fullmatch(target_path.name) for pattern in _SMART_COPY_ROOT_GENERATED_FILE_PATTERNS):
            continue
        if not (source_dir / target_path.name).exists():
            target_path.unlink(missing_ok=True)


def _container_path_for_materialized_file(path: Path, host_output_root: Path, container_output_root: str) -> str:
    try:
        relative = path.resolve().relative_to(host_output_root.resolve())
    except ValueError:
        return str(path.resolve())
    return str(Path(container_output_root) / relative).replace("\\", "/")


def _sanitize_path_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(value or "").strip()).strip(". ")
    return cleaned[:80] or "folder"


def _split_directory_suggestion_query(raw_query: str) -> tuple[Path | None, str]:
    drive_match = re.fullmatch(r"([A-Za-z]):", raw_query)
    if drive_match:
        return Path(f"{drive_match.group(1)}:\\"), ""

    query_path = Path(raw_query).expanduser()
    has_trailing_separator = raw_query.endswith(("\\", "/"))
    try:
        if has_trailing_separator or (query_path.exists() and query_path.is_dir()):
            return query_path, ""
    except OSError:
        pass

    parent = query_path.parent
    if str(parent) == "":
        return None, ""
    return parent, query_path.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Host-side Codex bridge for RoughCut Docker ACP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=38695)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(args.token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

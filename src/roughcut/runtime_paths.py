from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

from roughcut.config import DEFAULT_PROJECT_ROOT

_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def resolve_runtime_media_path(value: str | Path) -> Path:
    raw_value = str(value or "").strip()
    if not raw_value:
        return Path(raw_value)

    direct_path = Path(raw_value)
    if direct_path.exists():
        return direct_path

    candidates: list[Path] = []
    normalized = raw_value.replace("\\", "/")
    if normalized.startswith("/app/") and _WINDOWS_DRIVE_PATH_RE.match(normalized.removeprefix("/app/")):
        normalized = normalized.removeprefix("/app/")

    for prefix in ("/app/data/", "/code/data/", "app/data/", "code/data/"):
        if normalized.startswith(prefix):
            relative_value = normalized[len(prefix) :].lstrip("/")
            candidates.append(DEFAULT_PROJECT_ROOT / "data" / Path(relative_value))
            break

    if _WINDOWS_DRIVE_PATH_RE.match(normalized):
        windows_parts = PureWindowsPath(normalized).parts
        data_index = next(
            (index for index, part in enumerate(windows_parts) if str(part).strip().lower() == "data"),
            None,
        )
        if data_index is not None:
            candidates.append(DEFAULT_PROJECT_ROOT.joinpath(*windows_parts[data_index:]))

    for candidate in list(candidates):
        candidates.extend(_runtime_output_compatibility_candidates(candidate))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else direct_path


def _runtime_output_compatibility_candidates(path: Path) -> list[Path]:
    runtime_output_root = DEFAULT_PROJECT_ROOT / "data" / "runtime" / "output"
    legacy_output_root = DEFAULT_PROJECT_ROOT / "data" / "output"
    try:
        relative_path = path.relative_to(runtime_output_root)
    except ValueError:
        return []
    return [legacy_output_root / relative_path]

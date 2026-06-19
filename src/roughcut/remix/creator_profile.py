from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CREATOR_PROFILE_SCHEMA = "roughcut.creator_profile.v1"


def default_creator_profile_root(repo_root: Path) -> Path:
    return repo_root / "data" / "creator_profiles"


def load_creator_profile(
    *,
    repo_root: Path,
    slug: str | None = None,
    profile_path: Path | None = None,
) -> dict[str, Any] | None:
    if profile_path is not None:
        return _read_profile(profile_path)
    normalized_slug = str(slug or "").strip()
    if not normalized_slug:
        return None
    candidate = default_creator_profile_root(repo_root) / f"{normalized_slug}.json"
    if candidate.exists():
        return _read_profile(candidate)
    return None


def creator_tts_defaults(profile: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(profile, dict):
        return {}
    tts = profile.get("tts_defaults") if isinstance(profile.get("tts_defaults"), dict) else {}
    return {
        "provider": str(tts.get("provider") or "").strip(),
        "mode": str(tts.get("mode") or "").strip(),
        "reference_history_path": str(tts.get("reference_history_path") or "").strip(),
        "prompt_text": str(tts.get("prompt_text") or ""),
    }


def creator_caption_style_defaults(profile: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(profile, dict):
        return {}
    remix_style = profile.get("remix_style") if isinstance(profile.get("remix_style"), dict) else {}
    caption = remix_style.get("caption") if isinstance(remix_style.get("caption"), dict) else {}
    return {
        "subtitle_style_profile": str(caption.get("subtitle_style_profile") or "").strip(),
    }


def creator_display_name(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("name") or profile.get("slug") or profile.get("id") or "").strip()


def creator_profile_id(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("id") or profile.get("slug") or "").strip()


def _read_profile(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Creator profile must be a JSON object: {path}")
    return payload

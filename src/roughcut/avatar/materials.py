from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AVATAR_MATERIALS_ROOT = Path("data/avatar_materials")


def avatar_materials_root() -> Path:
    root = _AVATAR_MATERIALS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def avatar_materials_index_path() -> Path:
    return avatar_materials_root() / "profiles.json"


def list_avatar_material_profiles() -> list[dict[str, Any]]:
    index_path = avatar_materials_index_path()
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    profiles = payload if isinstance(payload, list) else []
    profiles.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return profiles


def save_avatar_material_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profiles = list_avatar_material_profiles()
    profiles = [item for item in profiles if str(item.get("id")) != str(profile.get("id"))]
    profiles.append(profile)
    avatar_materials_index_path().write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return profile


def get_avatar_material_profile(profile_id: str) -> dict[str, Any]:
    for profile in list_avatar_material_profiles():
        if str(profile.get("id")) == str(profile_id):
            return profile
    raise KeyError(profile_id)


def delete_avatar_material_profile(profile_id: str) -> None:
    profile = get_avatar_material_profile(profile_id)
    profile_dir = Path(str(profile.get("profile_dir") or ""))
    if profile_dir.exists():
        for child in sorted(profile_dir.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink(missing_ok=True)
            else:
                child.rmdir()
        profile_dir.rmdir()
    profiles = [item for item in list_avatar_material_profiles() if str(item.get("id")) != str(profile_id)]
    avatar_materials_index_path().write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_avatar_material_requirements() -> dict[str, Any]:
    return {
        "provider": "heygem",
        "training_api_available": False,
        "intake_mode": "guided_processing",
        "summary": "数字人素材现在分成三类上传：讲话视频片段给 HeyGem 数字人，声音采样给语音克隆，肖像照给形象核验与模板管理。系统会优先把声音采样转成标准 WAV，并在训练预处理接口可用时自动准备可复用的参考文本。",
        "sections": [
            {
                "title": "上传类型与用途",
                "rules": [
                    {
                        "severity": "required",
                        "title": "讲话视频片段",
                        "detail": "用于 HeyGem 数字人训练/建模。建议单人出镜、口型清楚、连续说话 20 到 120 秒。",
                    },
                    {
                        "severity": "recommended",
                        "title": "声音采样",
                        "detail": "用于声音克隆和 AI 导演重配音。建议干净人声 10 到 60 秒，单说话人，无背景音乐。",
                    },
                    {
                        "severity": "recommended",
                        "title": "肖像照",
                        "detail": "用于人物核验、形象管理和后续模板筛选。建议正脸、无遮挡、3 到 10 张。",
                    },
                ],
            },
            {
                "title": "必须满足",
                "rules": [
                    {
                        "severity": "required",
                        "title": "至少上传 1 个讲话视频片段",
                        "detail": "单人出镜，正脸或微侧脸，口型清楚，画面连续无硬切。",
                    },
                    {
                        "severity": "required",
                        "title": "视频时长建议 20 到 120 秒",
                        "detail": "低于 8 秒通常不足以稳定建模，20 到 120 秒会更稳，过长会拖慢清洗和训练。",
                    },
                    {
                        "severity": "required",
                        "title": "声音干净且只有一个说话人",
                        "detail": "不要混入背景音乐、旁白叠加、他人插话和重回声。",
                    },
                    {
                        "severity": "required",
                        "title": "画面不要带字幕、水印、贴纸和遮挡",
                        "detail": "口部、下巴、脸颊和额头应尽量完整可见。",
                    },
                ],
            },
            {
                "title": "强烈建议",
                "rules": [
                    {
                        "severity": "recommended",
                        "title": "分辨率不低于 720p",
                        "detail": "建议 1080p，帧率 24 到 60fps，光线稳定，避免过曝和强逆光。",
                    },
                    {
                        "severity": "recommended",
                        "title": "补充 3 到 10 张肖像照",
                        "detail": "表情自然，无遮挡，可帮助后续人工挑选模板和核验人物一致性。",
                    },
                    {
                        "severity": "recommended",
                        "title": "补充 1 到 3 段声音采样",
                        "detail": "用于后续语音克隆或校验音色稳定性，推荐 16kHz 以上 WAV/MP3。",
                    },
                ],
            },
            {
                "title": "支持格式",
                "rules": [
                    {
                        "severity": "info",
                        "title": "视频",
                        "detail": "mp4, mov, mkv, avi",
                    },
                    {
                        "severity": "info",
                        "title": "图片",
                        "detail": "jpg, jpeg, png",
                    },
                    {
                        "severity": "info",
                        "title": "音频",
                        "detail": "wav, mp3, m4a",
                    },
                ],
            },
        ],
    }


def create_profile_dir(display_name: str) -> tuple[str, Path]:
    profile_id = uuid.uuid4().hex
    safe_name = re.sub(r"[^a-zA-Z0-9\-_]+", "_", display_name).strip("_") or "avatar_profile"
    profile_dir = avatar_materials_root() / "profiles" / f"{safe_name}_{profile_id[:8]}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_id, profile_dir


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_filename(name: str) -> str:
    original = Path(name or "upload.bin").name
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", original)
    return safe or "upload.bin"

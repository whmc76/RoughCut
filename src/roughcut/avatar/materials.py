from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AVATAR_MATERIALS_ROOT = Path("data/avatar_materials")

_PERSONAL_INFO_FIELDS = (
    "public_name",
    "real_name",
    "title",
    "organization",
    "location",
    "bio",
    "expertise",
    "experience",
    "achievements",
    "creator_focus",
    "audience",
    "style",
    "contact",
    "extra_notes",
)

_CREATOR_PUBLISHING_FIELDS = (
    "primary_platform",
    "active_platforms",
    "signature",
    "default_call_to_action",
    "description_strategy",
)

_CREATOR_BUSINESS_FIELDS = (
    "contact",
    "collaboration_notes",
    "availability",
)

_DEMO_PROFILE_NAME_PATTERNS = (
    "演示创作者",
    "creatordemo",
    "demo creator",
    "demo_creator",
)


def avatar_materials_root() -> Path:
    root = _AVATAR_MATERIALS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def avatar_materials_index_path() -> Path:
    return avatar_materials_root() / "profiles.json"


def resolve_avatar_material_path(value: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path("__roughcut_missing_avatar_material__")

    normalized_raw = raw.replace("\\", "/")
    direct_path = Path(raw).expanduser()
    normalized_path = Path(normalized_raw).expanduser()
    remapped_path = _remap_avatar_material_storage_path(normalized_raw)

    for candidate in (direct_path, normalized_path, remapped_path):
        if candidate is not None and candidate.exists():
            return candidate.resolve()

    sibling_match = _resolve_unique_avatar_material_sibling(remapped_path or normalized_path)
    if sibling_match is not None:
        return sibling_match.resolve()

    if remapped_path is not None:
        return remapped_path
    if normalized_raw != raw:
        return normalized_path
    return direct_path


def list_avatar_material_profiles() -> list[dict[str, Any]]:
    index_path = avatar_materials_index_path()
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    profiles = [normalize_avatar_material_profile(item) for item in payload] if isinstance(payload, list) else []
    profiles.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return profiles


def save_avatar_material_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_avatar_material_profile(profile)
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
            return normalize_avatar_material_profile(profile)
    raise KeyError(profile_id)


def delete_avatar_material_profile(profile_id: str) -> None:
    profile = get_avatar_material_profile(profile_id)
    profile_dir = resolve_avatar_material_path(profile.get("profile_dir"))
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
        "warnings": [],
        "summary": "这里现在是创作者档案工作台。一个档案同时管理作者身份、内容定位、渠道信息、商务备注，以及数字人口播所需的讲话视频、声音采样和肖像照，后续简介生成与数字人链路都会复用这些信息。",
        "sections": [
            {
                "title": "档案组成",
                "rules": [
                    {
                        "severity": "required",
                        "title": "创作者身份与定位",
                        "detail": "建议至少填写作者名、身份标题、内容定位、受众和表达风格，方便平台简介按策略引用。",
                    },
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


def _remap_avatar_material_storage_path(raw: str) -> Path | None:
    cleaned = str(raw or "").strip().replace("\\", "/")
    if not cleaned or "://" in cleaned:
        return None

    segments = [segment for segment in cleaned.split("/") if segment and segment != "."]
    if not segments:
        return None

    lowered = [segment.lower() for segment in segments]
    if "avatar_materials" in lowered:
        avatar_root_index = lowered.index("avatar_materials")
        return avatar_materials_root().joinpath(*segments[avatar_root_index + 1 :])

    if lowered[0] in {"profiles", "profiles.json"}:
        return avatar_materials_root().joinpath(*segments)

    return None


def _resolve_unique_avatar_material_sibling(candidate: Path | None) -> Path | None:
    if candidate is None:
        return None

    parent = candidate.parent
    suffix = candidate.suffix.lower()
    if not suffix or not parent.exists():
        return None

    siblings = [child for child in parent.iterdir() if child.is_file() and child.suffix.lower() == suffix]
    if len(siblings) == 1:
        return siblings[0]
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_filename(name: str) -> str:
    original = Path(name or "upload.bin").name
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", original)
    return safe or "upload.bin"


def normalize_avatar_material_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(profile or {})
    normalized["personal_info"] = normalize_avatar_personal_info(
        normalized.get("personal_info"),
        display_name=str(normalized.get("display_name") or "").strip(),
        presenter_alias=str(normalized.get("presenter_alias") or "").strip(),
    )
    normalized["creator_profile"] = normalize_creator_profile(
        normalized.get("creator_profile"),
        personal_info=normalized["personal_info"],
        display_name=str(normalized.get("display_name") or "").strip(),
        presenter_alias=str(normalized.get("presenter_alias") or "").strip(),
        notes=str(normalized.get("notes") or "").strip(),
    )
    normalized["profile_dashboard"] = build_creator_profile_dashboard(normalized)
    return normalized


def normalize_avatar_personal_info(
    value: Any,
    *,
    display_name: str = "",
    presenter_alias: str = "",
) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}

    def _clean_text(raw: Any) -> str | None:
        text = str(raw or "").strip()
        return text or None

    expertise_raw = payload.get("expertise")
    if isinstance(expertise_raw, str):
        expertise = [
            item.strip()
            for item in re.split(r"[\n,，、;/；]+", expertise_raw)
            if item and item.strip()
        ]
    elif isinstance(expertise_raw, (list, tuple, set)):
        expertise = [str(item).strip() for item in expertise_raw if str(item).strip()]
    else:
        expertise = []

    normalized: dict[str, Any] = {field: None for field in _PERSONAL_INFO_FIELDS}
    normalized["public_name"] = _clean_text(payload.get("public_name")) or _clean_text(presenter_alias) or _clean_text(display_name)
    normalized["real_name"] = _clean_text(payload.get("real_name"))
    normalized["title"] = _clean_text(payload.get("title"))
    normalized["organization"] = _clean_text(payload.get("organization"))
    normalized["location"] = _clean_text(payload.get("location"))
    normalized["bio"] = _clean_text(payload.get("bio"))
    normalized["expertise"] = expertise[:12]
    normalized["experience"] = _clean_text(payload.get("experience"))
    normalized["achievements"] = _clean_text(payload.get("achievements"))
    normalized["creator_focus"] = _clean_text(payload.get("creator_focus"))
    normalized["audience"] = _clean_text(payload.get("audience"))
    normalized["style"] = _clean_text(payload.get("style"))
    normalized["contact"] = _clean_text(payload.get("contact"))
    normalized["extra_notes"] = _clean_text(payload.get("extra_notes"))
    return normalized


def normalize_creator_profile(
    value: Any,
    *,
    personal_info: dict[str, Any] | None,
    display_name: str = "",
    presenter_alias: str = "",
    notes: str = "",
) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    info = personal_info or normalize_avatar_personal_info(None, display_name=display_name, presenter_alias=presenter_alias)

    def _clean_text(raw: Any) -> str | None:
        text = str(raw or "").strip()
        return text or None

    def _clean_list(raw: Any) -> list[str]:
        if isinstance(raw, str):
            return [item.strip() for item in re.split(r"[\n,，、;/；]+", raw) if item and item.strip()]
        if isinstance(raw, (list, tuple, set)):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    identity_raw = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    positioning_raw = payload.get("positioning") if isinstance(payload.get("positioning"), dict) else {}
    publishing_raw = payload.get("publishing") if isinstance(payload.get("publishing"), dict) else {}
    business_raw = payload.get("business") if isinstance(payload.get("business"), dict) else {}

    expertise = _clean_list(positioning_raw.get("expertise")) or list(info.get("expertise") or [])
    active_platforms = _clean_list(publishing_raw.get("active_platforms"))
    tone_keywords = _clean_list(positioning_raw.get("tone_keywords"))

    return {
        "identity": {
            "public_name": _clean_text(identity_raw.get("public_name")) or info.get("public_name"),
            "real_name": _clean_text(identity_raw.get("real_name")) or info.get("real_name"),
            "title": _clean_text(identity_raw.get("title")) or info.get("title"),
            "organization": _clean_text(identity_raw.get("organization")) or info.get("organization"),
            "location": _clean_text(identity_raw.get("location")) or info.get("location"),
            "bio": _clean_text(identity_raw.get("bio")) or info.get("bio"),
        },
        "positioning": {
            "creator_focus": _clean_text(positioning_raw.get("creator_focus")) or info.get("creator_focus"),
            "expertise": expertise[:12],
            "audience": _clean_text(positioning_raw.get("audience")) or info.get("audience"),
            "style": _clean_text(positioning_raw.get("style")) or info.get("style"),
            "tone_keywords": tone_keywords[:8],
        },
        "publishing": {
            "primary_platform": _clean_text(publishing_raw.get("primary_platform")),
            "active_platforms": active_platforms[:8],
            "signature": _clean_text(publishing_raw.get("signature")),
            "default_call_to_action": _clean_text(publishing_raw.get("default_call_to_action")),
            "description_strategy": _clean_text(publishing_raw.get("description_strategy")),
        },
        "business": {
            "contact": _clean_text(business_raw.get("contact")) or info.get("contact"),
            "collaboration_notes": _clean_text(business_raw.get("collaboration_notes")),
            "availability": _clean_text(business_raw.get("availability")),
        },
        "archive_notes": _clean_text(payload.get("archive_notes")) or info.get("extra_notes") or _clean_text(notes),
    }


def personal_info_from_creator_profile(
    creator_profile: dict[str, Any] | None,
    *,
    display_name: str = "",
    presenter_alias: str = "",
) -> dict[str, Any]:
    profile = normalize_creator_profile(
        creator_profile,
        personal_info=None,
        display_name=display_name,
        presenter_alias=presenter_alias,
    )
    identity = profile.get("identity") or {}
    positioning = profile.get("positioning") or {}
    business = profile.get("business") or {}
    return normalize_avatar_personal_info(
        {
            "public_name": identity.get("public_name"),
            "real_name": identity.get("real_name"),
            "title": identity.get("title"),
            "organization": identity.get("organization"),
            "location": identity.get("location"),
            "bio": identity.get("bio"),
            "expertise": positioning.get("expertise"),
            "experience": None,
            "achievements": None,
            "creator_focus": positioning.get("creator_focus"),
            "audience": positioning.get("audience"),
            "style": positioning.get("style"),
            "contact": business.get("contact"),
            "extra_notes": profile.get("archive_notes"),
        },
        display_name=display_name,
        presenter_alias=presenter_alias,
    )


def build_creator_profile_dashboard(profile: dict[str, Any]) -> dict[str, Any]:
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    business = creator_profile.get("business") if isinstance(creator_profile.get("business"), dict) else {}
    files = list(profile.get("files") or [])
    material_counts = {
        "speaking_videos": sum(1 for item in files if str(item.get("role") or "") == "speaking_video"),
        "portrait_photos": sum(1 for item in files if str(item.get("role") or "") == "portrait_photo"),
        "voice_samples": sum(1 for item in files if str(item.get("role") or "") == "voice_sample"),
    }
    section_status = {
        "identity": bool(identity.get("public_name") and (identity.get("title") or identity.get("bio"))),
        "positioning": bool(positioning.get("creator_focus") and (positioning.get("audience") or positioning.get("style"))),
        "publishing": bool(publishing.get("primary_platform") or list(publishing.get("active_platforms") or [])),
        "business": bool(business.get("contact") or business.get("collaboration_notes")),
        "materials": bool(material_counts["speaking_videos"] and material_counts["voice_samples"]),
    }
    completed = sum(1 for item in section_status.values() if item)
    completeness_score = int(round(completed / max(len(section_status), 1) * 100))
    strengths: list[str] = []
    if section_status["identity"]:
        strengths.append("创作者身份锚点完整")
    if section_status["positioning"]:
        strengths.append("内容定位可直接用于平台简介")
    if section_status["publishing"]:
        strengths.append("渠道侧信息已具备复用价值")
    if section_status["materials"]:
        strengths.append("数字人口播素材链路已打通")

    next_steps: list[str] = []
    if not section_status["identity"]:
        next_steps.append("补充作者名、身份标题或简介，先把对外身份讲清楚。")
    if not section_status["positioning"]:
        next_steps.append("补充内容定位、受众和表达风格，方便平台文案按策略生成。")
    if not section_status["publishing"]:
        next_steps.append("补充主平台、活跃平台和个性签名，方便形成渠道化档案。")
    if not section_status["business"]:
        next_steps.append("补充联系方式或合作备注，方便归档为完整创作者档案。")
    if not section_status["materials"]:
        next_steps.append("至少补齐讲话视频和声音采样，才能稳定生成数字人预览。")

    return {
        "completeness_score": completeness_score,
        "section_status": section_status,
        "material_counts": material_counts,
        "strengths": strengths[:4],
        "next_steps": next_steps[:5],
    }


def detect_avatar_material_library_warnings(profiles: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    suspicious_profiles = [
        profile for profile in profiles
        if _looks_like_demo_avatar_profile(profile)
    ]
    if suspicious_profiles:
        names = "、".join(
            str(profile.get("display_name") or profile.get("presenter_alias") or profile.get("id") or "未命名档案")
            for profile in suspicious_profiles[:3]
        )
        warnings.append(
            f"检测到疑似演示创作者档案：{names}。如果这是正式工作台，请检查本地状态文件 data/avatar_materials/profiles.json 是否被样例数据覆盖。"
        )
    return warnings


def _looks_like_demo_avatar_profile(profile: dict[str, Any]) -> bool:
    display_name = str(profile.get("display_name") or "").strip()
    presenter_alias = str(profile.get("presenter_alias") or "").strip()
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    dashboard = profile.get("profile_dashboard") if isinstance(profile.get("profile_dashboard"), dict) else {}

    if not _matches_demo_profile_name(display_name, presenter_alias):
        return False

    completeness_score = int(dashboard.get("completeness_score") or 0)
    return completeness_score <= 20 and _creator_profile_is_nearly_empty(creator_profile)


def _matches_demo_profile_name(display_name: str, presenter_alias: str) -> bool:
    blob = f"{display_name} {presenter_alias}".lower()
    return any(pattern in blob for pattern in _DEMO_PROFILE_NAME_PATTERNS)


def _creator_profile_is_nearly_empty(profile: dict[str, Any]) -> bool:
    identity = profile.get("identity") if isinstance(profile.get("identity"), dict) else {}
    positioning = profile.get("positioning") if isinstance(profile.get("positioning"), dict) else {}
    publishing = profile.get("publishing") if isinstance(profile.get("publishing"), dict) else {}
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}

    meaningful_fields = (
        str(identity.get("title") or "").strip(),
        str(identity.get("bio") or "").strip(),
        str(positioning.get("creator_focus") or "").strip(),
        str(positioning.get("audience") or "").strip(),
        str(positioning.get("style") or "").strip(),
        str(publishing.get("primary_platform") or "").strip(),
        str(publishing.get("signature") or "").strip(),
        str(business.get("contact") or "").strip(),
        str(business.get("collaboration_notes") or "").strip(),
    )
    list_fields = (
        list(positioning.get("expertise") or []),
        list(positioning.get("tone_keywords") or []),
        list(publishing.get("active_platforms") or []),
    )
    return not any(meaningful_fields) and not any(list_fields)

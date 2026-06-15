from __future__ import annotations

import json
import httpx
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from roughcut.api.schemas import AvatarMaterialLibraryOut, AvatarPublicationProfileListOut
from roughcut.avatar import (
    avatar_material_role_matches_kind,
    build_avatar_material_requirements,
    create_profile_dir,
    detect_avatar_material_library_warnings,
    delete_avatar_material_profile,
    get_avatar_material_profile,
    now_iso,
    normalize_creator_profile,
    normalize_avatar_personal_info,
    personal_info_from_creator_profile,
    resolve_avatar_material_path,
    sanitize_filename,
    save_avatar_material_profile,
)
from roughcut.avatar.runtime import (
    generate_avatar_preview,
    is_heygem_preview_available,
    is_heygem_training_available,
    prepare_voice_sample_artifacts,
)
from roughcut.config import get_settings
from roughcut.media.probe import probe
from roughcut.naming import (
    AVATAR_CAPABILITY_GENERATION,
    AVATAR_CAPABILITY_PORTRAIT,
    AVATAR_CAPABILITY_PREVIEW,
    AVATAR_CAPABILITY_VOICE,
    normalize_avatar_capability_status,
)
from roughcut.publication import CANONICAL_PUBLICATION_ADAPTER, normalize_publication_platform, platform_label
from roughcut.publication import (
    build_publication_browser_profile_id,
    normalize_publication_browser_binding,
    normalize_publication_browser_name,
)

router = APIRouter(prefix="/avatar-materials", tags=["avatar-materials"])

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}


class AvatarPreviewRequest(BaseModel):
    script: str | None = None


class AvatarMaterialProfileUpdate(BaseModel):
    display_name: str | None = None
    presenter_alias: str | None = None
    notes: str | None = None
    personal_info: dict[str, Any] | None = None
    creator_profile: dict[str, Any] | None = None


class PublicationBrowserLoginMatchIn(BaseModel):
    browser: str
    platforms: list[str] = []
    user_data_dir: str | None = None
    profile_directory: str | None = None
    cdp_base_url: str | None = None


@router.get("", response_model=AvatarMaterialLibraryOut)
async def get_avatar_materials():
    payload = build_avatar_material_requirements()
    payload["training_api_available"] = await is_heygem_training_available()
    preview_service_available = await is_heygem_preview_available()
    profiles = _list_profiles()
    for profile in profiles:
        capability_status, next_action = _derive_runtime_preview_capability(
            profile.get("capability_status") or {},
            profile.get("files") or [],
            preview_service_available,
        )
        profile["capability_status"] = capability_status
        profile["next_action"] = next_action
    payload["preview_service_available"] = preview_service_available
    payload["warnings"] = detect_avatar_material_library_warnings(profiles)
    payload["profiles"] = profiles
    return payload


@router.get("/publication-profiles", response_model=AvatarPublicationProfileListOut)
def get_avatar_publication_profiles():
    profiles = [
        {
            "id": str(profile.get("id") or ""),
            "display_name": str(profile.get("display_name") or "未命名账号"),
            "presenter_alias": profile.get("presenter_alias"),
            "creator_profile": profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {},
            "created_at": str(profile.get("created_at") or ""),
        }
        for profile in _list_profiles()
        if str(profile.get("id") or "").strip()
    ]
    return {"profiles": profiles}


def _normalize_publication_browser(value: str) -> str:
    browser = normalize_publication_browser_name(value)
    if browser:
        return browser
    raise HTTPException(status_code=400, detail="不支持的浏览器选项。")


def _publication_browser_label(browser: str) -> str:
    return {
        "chrome": "Chrome",
        "edge": "Edge",
        "firefox": "Firefox",
        "browser-agent": "Browser Agent 默认浏览器",
    }.get(browser, browser)


def _normalize_publication_browser_platforms(platforms: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in platforms or []:
        platform = normalize_publication_platform(item)
        if platform and platform not in normalized:
            normalized.append(platform)
    return normalized


def _publication_browser_local_state_path(browser: str) -> Path | None:
    local_app_data = Path.home() / "AppData" / "Local"
    candidates = {
        "chrome": local_app_data / "Google" / "Chrome" / "User Data" / "Local State",
        "edge": local_app_data / "Microsoft" / "Edge" / "User Data" / "Local State",
    }
    path = candidates.get(browser)
    return path if path and path.exists() else None


def _publication_browser_user_data_dir(browser: str) -> Path | None:
    state_path = _publication_browser_local_state_path(browser)
    return state_path.parent if state_path is not None else None


def _collect_creator_identity_tokens(profile: dict[str, Any]) -> set[str]:
    creator_identity = (
        profile.get("creator_profile", {}).get("identity", {})
        if isinstance(profile.get("creator_profile"), dict)
        else {}
    )
    personal_info = (
        profile.get("personal_info", {})
        if isinstance(profile.get("personal_info"), dict)
        else {}
    )
    business = (
        profile.get("creator_profile", {}).get("business", {})
        if isinstance(profile.get("creator_profile"), dict)
        else {}
    )
    raw_tokens = [
        profile.get("display_name"),
        profile.get("presenter_alias"),
        creator_identity.get("public_name"),
        creator_identity.get("real_name"),
        creator_identity.get("email"),
        personal_info.get("contact"),
        business.get("contact"),
    ]
    tokens: set[str] = set()
    for raw in raw_tokens:
        value = str(raw or "").strip().replace("_", " ").replace("-", " ")
        for token in value.split():
            token = token.strip()
            if len(token) >= 2:
                tokens.add(token.lower())
    return tokens


def _resolve_existing_browser_binding(profile: dict[str, Any], browser: str) -> dict[str, Any]:
    publishing = profile.get("creator_profile", {}).get("publishing", {})
    if not isinstance(publishing, dict):
        return {}
    credentials = publishing.get("platform_credentials")
    if not isinstance(credentials, list):
        return {}
    normalized_browser = normalize_publication_browser_name(browser)
    candidates: list[dict[str, Any]] = []
    for item in credentials:
        if not isinstance(item, dict):
            continue
        if str(item.get("adapter") or "").strip().lower().replace("-", "_") != CANONICAL_PUBLICATION_ADAPTER:
            continue
        browser_binding = item.get("browser_binding")
        if not isinstance(browser_binding, dict):
            continue
        if normalize_publication_browser_name(browser_binding.get("browser")) != normalized_browser:
            continue
        if not browser_binding.get("profile_id"):
            continue
        candidates.append(browser_binding)
    unique_ids = {
        str(item.get("profile_id") or "").strip()
        for item in candidates
        if str(item.get("profile_id") or "").strip()
    }
    if len(unique_ids) != 1:
        return {}
    return normalize_publication_browser_binding(candidates[0])


def _resolve_agent_attached_browser_binding(browser: str) -> dict[str, Any]:
    settings = get_settings()
    base_url = str(getattr(settings, "publication_browser_agent_base_url", "") or "").strip().rstrip("/")
    if not base_url:
        return {}
    normalized_browser = normalize_publication_browser_name(browser)
    if not normalized_browser:
        return {}
    headers: dict[str, str] = {}
    auth_token = str(getattr(settings, "publication_browser_agent_auth_token", "") or "").strip()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    try:
        with httpx.Client(timeout=httpx.Timeout(2.0)) as client:
            response = client.get(f"{base_url}/healthz", headers=headers)
            response.raise_for_status()
            payload = response.json() or {}
    except Exception:
        return {}
    attached = payload.get("attached_profile_binding") if isinstance(payload, dict) else None
    if not isinstance(attached, dict):
        return {}
    if normalize_publication_browser_name(attached.get("browser")) != normalized_browser:
        return {}
    return normalize_publication_browser_binding(
        {
            "browser": attached.get("browser"),
            "user_data_dir": attached.get("user_data_dir"),
            "profile_directory": attached.get("profile_directory"),
            "cdp_base_url": attached.get("cdp_base_url") if isinstance(attached.get("cdp_base_url"), str) else None,
        }
    )


def _resolve_browser_profile_binding_for_creator(
    *,
    browser: str,
    profile: dict[str, Any],
    body: PublicationBrowserLoginMatchIn,
) -> dict[str, Any]:
    explicit_binding = normalize_publication_browser_binding(
        {
            "browser": browser,
            "user_data_dir": body.user_data_dir,
            "profile_directory": body.profile_directory,
            "cdp_base_url": body.cdp_base_url,
        }
    )
    if explicit_binding.get("profile_id"):
        return explicit_binding
    if browser not in {"chrome", "edge"}:
        return explicit_binding
    agent_binding = normalize_publication_browser_binding(_resolve_agent_attached_browser_binding(browser=browser))
    local_state_path = _publication_browser_local_state_path(browser)
    user_data_dir = _publication_browser_user_data_dir(browser)
    if local_state_path is None or user_data_dir is None:
        return agent_binding if agent_binding.get("profile_id") else explicit_binding
    try:
        payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    except Exception:
        if existing_binding := _resolve_existing_browser_binding(profile=profile, browser=browser):
            return existing_binding
        return agent_binding if agent_binding.get("profile_id") else explicit_binding
    info_cache = (
        (payload.get("profile") or {}).get("info_cache")
        if isinstance((payload.get("profile") or {}), dict)
        else {}
    )
    if not isinstance(info_cache, dict):
        if existing_binding := _resolve_existing_browser_binding(profile=profile, browser=browser):
            return existing_binding
        return agent_binding if agent_binding.get("profile_id") else explicit_binding
    creator_tokens = _collect_creator_identity_tokens(profile)
    if not creator_tokens:
        return _resolve_existing_browser_binding(profile=profile, browser=browser) or (
            agent_binding if agent_binding.get("profile_id") else explicit_binding
        )
    matches: list[dict[str, Any]] = []
    for directory, raw_entry in info_cache.items():
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        searchable = " ".join(
            [
                str(directory or ""),
                str(entry.get("name") or ""),
                str(entry.get("gaia_given_name") or ""),
                str(entry.get("gaia_name") or ""),
                str(entry.get("user_name") or ""),
            ]
        ).lower()
        score = sum(1 for token in creator_tokens if token in searchable)
        if score <= 0:
            continue
        matches.append(
            {
                "score": score,
                "profile_directory": str(directory or "").strip(),
                "profile_name": str(entry.get("name") or "").strip() or None,
                "profile_email": str(entry.get("user_name") or "").strip() or None,
            }
        )
    if not matches:
        return _resolve_existing_browser_binding(profile=profile, browser=browser) or (
            agent_binding if agent_binding.get("profile_id") else explicit_binding
        )
    matches.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("profile_directory") or "")))
    best = matches[0]
    if len(matches) > 1 and int(matches[1].get("score") or 0) == int(best.get("score") or 0):
        return explicit_binding
    resolved = normalize_publication_browser_binding(
        {
            "browser": browser,
            "user_data_dir": str(user_data_dir),
            "profile_directory": best.get("profile_directory"),
            "profile_name": best.get("profile_name"),
            "profile_email": best.get("profile_email"),
            "cdp_base_url": body.cdp_base_url,
            "profile_id": build_publication_browser_profile_id(
                browser=browser,
                user_data_dir=str(user_data_dir),
                profile_directory=best.get("profile_directory"),
            ),
        }
    )
    return resolved


def _preserve_profile_credentials_on_update(
    existing_creator_profile: dict[str, Any] | None,
    creator_profile_update: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(creator_profile_update, dict):
        return {}

    update_payload = dict(creator_profile_update)
    if not isinstance(existing_creator_profile, dict):
        return update_payload

    existing_publishing = existing_creator_profile.get("publishing")
    if not isinstance(existing_publishing, dict):
        return update_payload

    update_publishing = update_payload.get("publishing")
    if not isinstance(update_publishing, dict):
        return update_payload

    if "platform_credentials" not in update_publishing:
        merged_publishing = dict(update_publishing)
        merged_publishing["platform_credentials"] = existing_publishing.get("platform_credentials", [])
        update_payload["publishing"] = merged_publishing

    return update_payload


@router.post("/publication-profiles/{profile_id}/match-browser-login", response_model=AvatarPublicationProfileListOut)
def match_publication_browser_login(profile_id: str, body: PublicationBrowserLoginMatchIn):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    browser = _normalize_publication_browser(body.browser)
    platforms = _normalize_publication_browser_platforms(body.platforms)
    if not platforms:
        raise HTTPException(status_code=400, detail="当前物料没有后端支持的一键发布平台。")

    creator_profile = normalize_creator_profile(
        profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {},
        personal_info=profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else None,
        display_name=str(profile.get("display_name") or "").strip(),
        presenter_alias=str(profile.get("presenter_alias") or "").strip(),
        notes=str(profile.get("notes") or "").strip(),
    )
    publishing = creator_profile.setdefault("publishing", {})
    if not isinstance(publishing, dict):
        publishing = {}
        creator_profile["publishing"] = publishing

    browser_label = _publication_browser_label(browser)
    profile_name = str(profile.get("display_name") or profile.get("presenter_alias") or "发布账号").strip()
    browser_binding = _resolve_browser_profile_binding_for_creator(browser=browser, profile=profile, body=body)
    credentials = [
        dict(item)
        for item in (publishing.get("platform_credentials") or [])
        if isinstance(item, dict) and normalize_publication_platform(item.get("platform"))
    ]
    now = now_iso()
    binding_note = ""
    if browser_binding.get("profile_directory") and browser_binding.get("user_data_dir"):
        binding_note = (
            f" 已绑定真实浏览器 profile：{browser_binding.get('profile_directory')}"
            f" @ {browser_binding.get('user_data_dir')}。"
        )
    note = (
        f"由智能发布页根据用户选择的{browser_label}本地浏览器会话引用自动匹配；"
        f"未读取或保存平台密码、Cookie 或浏览器凭证。{binding_note}"
    ).strip()
    for platform in platforms:
        existing = next(
            (
                item
                for item in credentials
                if normalize_publication_platform(item.get("platform")) == platform
                and str(item.get("adapter") or CANONICAL_PUBLICATION_ADAPTER).strip().lower().replace("-", "_")
                == CANONICAL_PUBLICATION_ADAPTER
            ),
            None,
        )
        credential_ref = f"browser-agent:{browser}:{profile_id}:{platform}"
        patch = {
            "id": str((existing or {}).get("id") or uuid.uuid4().hex),
            "platform": platform,
            "platform_label": platform_label(platform),
            "account_label": str((existing or {}).get("account_label") or f"{profile_name} · {browser_label}").strip(),
            "credential_ref": credential_ref,
            "browser_profile_id": str(
                browser_binding.get("profile_id") or (existing or {}).get("browser_profile_id") or credential_ref
            ).strip(),
            "browser_binding": browser_binding,
            "status": "logged_in",
            "enabled": True,
            "adapter": CANONICAL_PUBLICATION_ADAPTER,
            "verified_at": now,
            "notes": note,
            "last_error": None,
        }
        if existing is not None:
            existing.update(patch)
        else:
            credentials.append(patch)

    active_platforms = [
        str(item).strip()
        for item in (publishing.get("active_platforms") or [])
        if str(item).strip()
    ]
    for platform in platforms:
        label = platform_label(platform)
        if label not in active_platforms:
            active_platforms.append(label)
    publishing["active_platforms"] = active_platforms[:8]
    publishing["platform_credentials"] = credentials

    profile["creator_profile"] = normalize_creator_profile(
        creator_profile,
        personal_info=profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else None,
        display_name=str(profile.get("display_name") or "").strip(),
        presenter_alias=str(profile.get("presenter_alias") or "").strip(),
        notes=str(profile.get("notes") or "").strip(),
    )
    profile["personal_info"] = personal_info_from_creator_profile(
        profile["creator_profile"],
        display_name=str(profile.get("display_name") or "").strip(),
        presenter_alias=str(profile.get("presenter_alias") or "").strip(),
    )
    save_avatar_material_profile(profile)
    return get_avatar_publication_profiles()


@router.post("/profiles", response_model=AvatarMaterialLibraryOut, status_code=201)
async def upload_avatar_material_profile(
    display_name: str = Form(...),
    presenter_alias: str | None = Form(None),
    notes: str | None = Form(None),
    personal_info_json: str | None = Form(None),
    creator_profile_json: str | None = Form(None),
    speaking_videos: list[UploadFile] | None = File(None),
    portrait_photos: list[UploadFile] | None = File(None),
    voice_samples: list[UploadFile] | None = File(None),
    files: list[UploadFile] | None = File(None),
):
    cleaned_name = str(display_name or "").strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="display_name is required")
    uploads_with_role = [
        *((("speaking_video", item) for item in (speaking_videos or []))),
        *((("portrait_photo", item) for item in (portrait_photos or []))),
        *((("voice_sample", item) for item in (voice_samples or []))),
        *((("generic", item) for item in (files or []))),
    ]
    if not uploads_with_role:
        raise HTTPException(status_code=400, detail="At least one avatar material file is required")

    settings = get_settings()
    training_api_available = await is_heygem_training_available()
    preview_service_available = await is_heygem_preview_available()
    profile_id, profile_dir = create_profile_dir(cleaned_name)
    personal_info = _parse_personal_info_form(
        personal_info_json,
        display_name=cleaned_name,
        presenter_alias=str(presenter_alias or "").strip(),
    )
    creator_profile = _parse_creator_profile_form(
        creator_profile_json,
        display_name=cleaned_name,
        presenter_alias=str(presenter_alias or "").strip(),
        notes=str(notes or "").strip(),
        personal_info=personal_info,
    )
    personal_info = personal_info_from_creator_profile(
        creator_profile,
        display_name=cleaned_name,
        presenter_alias=str(presenter_alias or "").strip(),
    )
    stored_files: list[dict[str, Any]] = []
    blocking_issues: list[str] = []
    warnings: list[str] = []
    speaking_video_count = 0
    portrait_photo_count = 0
    voice_sample_count = 0

    for role, upload in uploads_with_role:
        payload = await upload.read()
        if not payload:
            continue
        if settings.max_upload_size_bytes > 0 and len(payload) > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename or 'file'} exceeds max upload size",
            )
        file_record = await _save_material_file(profile_dir=profile_dir, upload=upload, payload=payload, role=role)
        if str(file_record.get("role") or "") == "voice_sample":
            try:
                file_record = await prepare_voice_sample_artifacts(
                    file_record,
                    attempt_preprocess=training_api_available,
                    require_preprocess=False,
                )
            except Exception as exc:
                checks = list(file_record.get("checks") or [])
                checks.append({"level": "warning", "message": f"声音标准化失败：{exc}"})
                file_record["checks"] = checks
            else:
                preprocess_error = str((file_record.get("artifacts") or {}).get("training_preprocess_error") or "").strip()
                if preprocess_error:
                    checks = list(file_record.get("checks") or [])
                    checks.append({"level": "warning", "message": f"声音预处理失败：{preprocess_error}"})
                    file_record["checks"] = checks
        stored_files.append(file_record)
        resolved_role = str(file_record.get("role") or "")
        if resolved_role == "speaking_video":
            speaking_video_count += 1
            _merge_checks(file_record, blocking_issues, warnings)
        elif resolved_role == "portrait_photo":
            portrait_photo_count += 1
            _merge_checks(file_record, blocking_issues, warnings)
        elif resolved_role == "voice_sample":
            voice_sample_count += 1
            _merge_checks(file_record, blocking_issues, warnings)

    if not stored_files:
        raise HTTPException(status_code=400, detail="Uploaded files are empty")
    profile_state = _build_profile_runtime_state(
        speaking_video_count=speaking_video_count,
        portrait_photo_count=portrait_photo_count,
        voice_sample_count=voice_sample_count,
        training_api_available=training_api_available,
        preview_service_available=preview_service_available,
        blocking_issues=blocking_issues,
        warnings=warnings,
    )
    profile = {
        "id": profile_id,
        "display_name": cleaned_name,
        "presenter_alias": str(presenter_alias or "").strip() or None,
        "notes": str(notes or "").strip() or None,
        "personal_info": personal_info,
        "creator_profile": creator_profile,
        "profile_dir": str(profile_dir),
        "training_status": profile_state["training_status"],
        "training_provider": "heygem",
        "training_api_available": training_api_available,
        "next_action": profile_state["next_action"],
        "capability_status": profile_state["capability_status"],
        "blocking_issues": profile_state["blocking_issues"],
        "warnings": profile_state["warnings"],
        "created_at": now_iso(),
        "files": stored_files,
        "preview_runs": [],
    }
    save_avatar_material_profile(profile)
    return await get_avatar_materials()


@router.put("/profiles/{profile_id}/files/{file_id}", response_model=AvatarMaterialLibraryOut)
async def replace_avatar_material_file(
    profile_id: str,
    file_id: str,
    file: UploadFile = File(...),
):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    files = list(profile.get("files") or [])
    file_idx = next((index for index, item in enumerate(files) if str(item.get("id")) == str(file_id)), -1)
    if file_idx < 0:
        raise HTTPException(status_code=404, detail="Avatar material file not found")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Replace file is empty")

    settings = get_settings()
    if settings.max_upload_size_bytes > 0 and len(payload) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=400, detail=f"{file.filename or 'file'} exceeds max upload size")

    profile_dir = resolve_avatar_material_path(profile.get("profile_dir"))
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)
    training_api_available = await is_heygem_training_available()
    preview_service_available = await is_heygem_preview_available()
    target = files[file_idx]
    target_role = str(target.get("role") or "generic")
    old_path = resolve_avatar_material_path(target.get("path"))
    if old_path.exists():
        old_path.unlink(missing_ok=True)

    file_record = await _save_material_file(profile_dir=profile_dir, upload=file, payload=payload, role=target_role)
    file_record["id"] = str(target.get("id") or file_record["id"])
    file_record["created_at"] = now_iso()
    if str(file_record.get("role")) == "voice_sample":
        try:
            file_record = await prepare_voice_sample_artifacts(
                file_record,
                attempt_preprocess=training_api_available,
                require_preprocess=False,
            )
        except Exception as exc:
            checks = list(file_record.get("checks") or [])
            checks.append({"level": "warning", "message": f"声音标准化失败：{exc}"})
            file_record["checks"] = checks
        else:
            preprocess_error = str((file_record.get("artifacts") or {}).get("training_preprocess_error") or "").strip()
            if preprocess_error:
                checks = list(file_record.get("checks") or [])
                checks.append({"level": "warning", "message": f"声音预处理失败：{preprocess_error}"})
                file_record["checks"] = checks

    files[file_idx] = file_record

    speaking_video_count = 0
    portrait_photo_count = 0
    voice_sample_count = 0
    blocking_issues: list[str] = []
    warnings: list[str] = []
    for item in files:
        resolved_role = str(item.get("role") or "")
        if resolved_role == "speaking_video":
            speaking_video_count += 1
            _merge_checks(item, blocking_issues, warnings)
        elif resolved_role == "portrait_photo":
            portrait_photo_count += 1
            _merge_checks(item, blocking_issues, warnings)
        elif resolved_role == "voice_sample":
            voice_sample_count += 1
            _merge_checks(item, blocking_issues, warnings)

    profile_state = _build_profile_runtime_state(
        speaking_video_count=speaking_video_count,
        portrait_photo_count=portrait_photo_count,
        voice_sample_count=voice_sample_count,
        training_api_available=training_api_available,
        preview_service_available=preview_service_available,
        blocking_issues=blocking_issues,
        warnings=warnings,
    )
    profile["files"] = files
    profile["training_api_available"] = training_api_available
    profile["training_status"] = profile_state["training_status"]
    profile["capability_status"] = profile_state["capability_status"]
    profile["next_action"] = profile_state["next_action"]
    profile["blocking_issues"] = profile_state["blocking_issues"]
    profile["warnings"] = profile_state["warnings"]
    profile["preview_runs"] = []
    save_avatar_material_profile(profile)
    return await get_avatar_materials()


@router.delete("/profiles/{profile_id}/files/{file_id}", response_model=AvatarMaterialLibraryOut)
async def remove_avatar_material_file(profile_id: str, file_id: str):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    files = list(profile.get("files") or [])
    file_idx = next((index for index, item in enumerate(files) if str(item.get("id")) == str(file_id)), -1)
    if file_idx < 0:
        raise HTTPException(status_code=404, detail="Avatar material file not found")

    removed_file = files.pop(file_idx)
    _unlink_avatar_material_file_paths(removed_file)

    training_api_available = await is_heygem_training_available()
    preview_service_available = await is_heygem_preview_available()
    profile_state = _build_profile_runtime_state_from_files(
        files=files,
        training_api_available=training_api_available,
        preview_service_available=preview_service_available,
    )
    profile["files"] = files
    profile["training_api_available"] = training_api_available
    profile["training_status"] = profile_state["training_status"]
    profile["capability_status"] = profile_state["capability_status"]
    profile["next_action"] = profile_state["next_action"]
    profile["blocking_issues"] = profile_state["blocking_issues"]
    profile["warnings"] = profile_state["warnings"]
    profile["preview_runs"] = []
    save_avatar_material_profile(profile)
    return await get_avatar_materials()


@router.patch("/profiles/{profile_id}", response_model=AvatarMaterialLibraryOut)
async def update_avatar_material_profile(profile_id: str, payload: AvatarMaterialProfileUpdate):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    if payload.display_name is not None:
        display_name = str(payload.display_name).strip()
        if not display_name:
            raise HTTPException(status_code=400, detail="display_name cannot be empty")
        profile["display_name"] = display_name

    if payload.presenter_alias is not None:
        profile["presenter_alias"] = str(payload.presenter_alias).strip() or None

    if payload.notes is not None:
        profile["notes"] = str(payload.notes).strip() or None

    if payload.personal_info is not None:
        profile["personal_info"] = normalize_avatar_personal_info(
            payload.personal_info,
            display_name=str(profile.get("display_name") or "").strip(),
            presenter_alias=str(profile.get("presenter_alias") or "").strip(),
        )

    if payload.creator_profile is not None:
        normalized_creator_profile = _preserve_profile_credentials_on_update(
            existing_creator_profile=profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else None,
            creator_profile_update=payload.creator_profile,
        )
        profile["creator_profile"] = normalize_creator_profile(
            normalized_creator_profile,
            personal_info=profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else None,
            display_name=str(profile.get("display_name") or "").strip(),
            presenter_alias=str(profile.get("presenter_alias") or "").strip(),
            notes=str(profile.get("notes") or "").strip(),
        )
        profile["personal_info"] = personal_info_from_creator_profile(
            profile["creator_profile"],
            display_name=str(profile.get("display_name") or "").strip(),
            presenter_alias=str(profile.get("presenter_alias") or "").strip(),
        )

    save_avatar_material_profile(profile)
    return await get_avatar_materials()


@router.delete("/profiles/{profile_id}", response_model=AvatarMaterialLibraryOut)
async def remove_avatar_material_profile(profile_id: str):
    try:
        delete_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc
    return await get_avatar_materials()


@router.post("/profiles/{profile_id}/preview", response_model=AvatarMaterialLibraryOut)
async def generate_avatar_material_preview(profile_id: str, body: AvatarPreviewRequest):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    script = str(body.script or "").strip() or _default_preview_script(profile)
    try:
        preview_run = await generate_avatar_preview(profile=profile, script=script)
    except Exception as exc:
        preview_run = {
            "id": uuid.uuid4().hex,
            "status": "failed",
            "script": script,
            "error_message": str(exc),
            "created_at": now_iso(),
        }

    preview_runs = list(profile.get("preview_runs") or [])
    preview_runs.insert(0, preview_run)
    profile["preview_runs"] = preview_runs[:10]
    save_avatar_material_profile(profile)
    return await get_avatar_materials()


@router.get("/profiles/{profile_id}/files/{file_id}")
def get_avatar_material_file(profile_id: str, file_id: str):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc
    file_entry = next((item for item in profile.get("files") or [] if str(item.get("id")) == str(file_id)), None)
    if not file_entry:
        raise HTTPException(status_code=404, detail="Avatar material file not found")
    file_path = resolve_avatar_material_path(file_entry.get("path"))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Avatar material file missing on disk")
    return FileResponse(
        file_path,
        media_type=str(file_entry.get("content_type") or "application/octet-stream"),
        filename=str(file_entry.get("original_name") or file_path.name),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/profiles/{profile_id}/preview-runs/{preview_id}/file")
def get_avatar_preview_file(profile_id: str, preview_id: str):
    try:
        profile = get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Avatar material profile not found") from exc

    preview_run = next((item for item in profile.get("preview_runs") or [] if str(item.get("id")) == str(preview_id)), None)
    if not preview_run:
        raise HTTPException(status_code=404, detail="Avatar preview not found")

    file_path = resolve_avatar_material_path(preview_run.get("output_path"))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Avatar preview file missing on disk")

    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=file_path.name,
    )


def _list_profiles() -> list[dict[str, Any]]:
    from roughcut.avatar import list_avatar_material_profiles

    profiles = list_avatar_material_profiles()
    return profiles


def _parse_personal_info_form(
    raw: str | None,
    *,
    display_name: str,
    presenter_alias: str,
) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return normalize_avatar_personal_info(
            None,
            display_name=display_name,
            presenter_alias=presenter_alias,
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid personal_info_json: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="personal_info_json must be a JSON object")
    return normalize_avatar_personal_info(
        payload,
        display_name=display_name,
        presenter_alias=presenter_alias,
    )


def _parse_creator_profile_form(
    raw: str | None,
    *,
    display_name: str,
    presenter_alias: str,
    notes: str,
    personal_info: dict[str, Any] | None,
) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return normalize_creator_profile(
            None,
            personal_info=personal_info,
            display_name=display_name,
            presenter_alias=presenter_alias,
            notes=notes,
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid creator_profile_json: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="creator_profile_json must be a JSON object")
    return normalize_creator_profile(
        payload,
        personal_info=personal_info,
        display_name=display_name,
        presenter_alias=presenter_alias,
        notes=notes,
    )


def _build_profile_runtime_state(
    *,
    speaking_video_count: int,
    portrait_photo_count: int,
    voice_sample_count: int,
    training_api_available: bool,
    preview_service_available: bool = True,
    blocking_issues: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if speaking_video_count == 0:
        blocking_issues.append("至少需要 1 个讲话视频片段，当前档案还不能进入 HeyGem 数字人训练。")
    if portrait_photo_count == 0:
        warnings.append("还没有肖像照，建议补 3 到 10 张正脸图片用于形象核验。")
    if voice_sample_count == 0:
        warnings.append("还没有声音采样，后续语音克隆和 AI 导演重配音将无法直接复用同音色。")

    avatar_ready = speaking_video_count > 0 and not any("讲话视频" in item for item in blocking_issues)
    voice_clone_ready = voice_sample_count > 0 and not any("声音采样" in item for item in blocking_issues)
    portrait_ready = portrait_photo_count > 0 and not any("肖像照" in item for item in blocking_issues)
    preview_ready = avatar_ready and voice_clone_ready and preview_service_available
    training_ready = avatar_ready

    return {
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "training_status": "ready_for_manual_training" if training_ready else "needs_more_material",
        "capability_status": {
            AVATAR_CAPABILITY_GENERATION: "ready" if avatar_ready else "missing",
            AVATAR_CAPABILITY_VOICE: "ready" if voice_clone_ready else "missing",
            AVATAR_CAPABILITY_PORTRAIT: "ready" if portrait_ready else "missing",
            AVATAR_CAPABILITY_PREVIEW: "ready" if preview_ready else "missing",
        },
        "next_action": (
            "素材已通过基础预检，声音采样也已完成预处理，可以直接生成脚本驱动的数字人预览样片。"
            if preview_ready and training_api_available
            else "素材已通过基础预检，可以先用原始声音样本生成数字人预览样片，后续再补训练预处理。"
            if preview_ready
            else "讲话视频片段已通过基础预检，可继续人工导入 HeyGem 训练。"
            if training_ready
            else "先补齐讲话视频片段或修复阻塞项，再导入 HeyGem 训练。"
        ),
    }


def _build_profile_runtime_state_from_files(
    *,
    files: list[dict[str, Any]],
    training_api_available: bool,
    preview_service_available: bool,
) -> dict[str, Any]:
    speaking_video_count = 0
    portrait_photo_count = 0
    voice_sample_count = 0
    blocking_issues: list[str] = []
    warnings: list[str] = []
    for item in files:
        resolved_role = str(item.get("role") or "")
        if resolved_role == "speaking_video":
            speaking_video_count += 1
            _merge_checks(item, blocking_issues, warnings)
        elif resolved_role == "portrait_photo":
            portrait_photo_count += 1
            _merge_checks(item, blocking_issues, warnings)
        elif resolved_role == "voice_sample":
            voice_sample_count += 1
            _merge_checks(item, blocking_issues, warnings)
    return _build_profile_runtime_state(
        speaking_video_count=speaking_video_count,
        portrait_photo_count=portrait_photo_count,
        voice_sample_count=voice_sample_count,
        training_api_available=training_api_available,
        preview_service_available=preview_service_available,
        blocking_issues=blocking_issues,
        warnings=warnings,
    )


def _iter_avatar_material_file_paths(file_record: dict[str, Any]):
    yield file_record.get("path")
    artifacts = file_record.get("artifacts")
    if isinstance(artifacts, dict):
        for value in artifacts.values():
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        yield item
            elif isinstance(value, dict):
                for item in value.values():
                    if isinstance(item, str):
                        yield item


def _unlink_avatar_material_file_paths(file_record: dict[str, Any]) -> None:
    seen: set[str] = set()
    for raw_path in _iter_avatar_material_file_paths(file_record):
        path_key = str(raw_path or "").strip()
        if not path_key or path_key in seen:
            continue
        seen.add(path_key)
        try:
            path = resolve_avatar_material_path(path_key)
        except Exception:
            continue
        if path.exists() and path.is_file():
            path.unlink(missing_ok=True)


def _derive_runtime_preview_capability(
    capability_status: dict[str, str],
    files: list[dict[str, Any]],
    preview_service_available: bool,
) -> tuple[dict[str, str], str]:
    capability_status = normalize_avatar_capability_status(capability_status)
    has_video = _has_ready_material(files, "speaking_video")
    has_voice = _has_ready_material(files, "voice_sample")
    has_portrait = _has_ready_material(files, "portrait_photo")
    has_blocking_issues = _has_blocking_material_issues(files)

    if not files:
        return (
            {
                AVATAR_CAPABILITY_GENERATION: "missing",
                AVATAR_CAPABILITY_VOICE: "missing",
                AVATAR_CAPABILITY_PORTRAIT: "missing",
                AVATAR_CAPABILITY_PREVIEW: "missing",
            },
            "先补齐讲话视频片段或修复阻塞项，再导入 HeyGem 训练。",
        )

    avatar_ready = "ready" if has_video else "missing"
    voice_ready = "ready" if has_voice else "missing"
    portrait_ready = "ready" if has_portrait else "missing"
    preview_ready = "ready" if has_video and has_voice and preview_service_available else "missing"

    if has_blocking_issues:
        return (
            {
                AVATAR_CAPABILITY_GENERATION: avatar_ready,
                AVATAR_CAPABILITY_VOICE: voice_ready,
                AVATAR_CAPABILITY_PORTRAIT: portrait_ready,
                AVATAR_CAPABILITY_PREVIEW: "missing",
            },
            "素材存在阻塞项，先修复后再继续。",
        )

    if not has_video:
        return (
            {
                AVATAR_CAPABILITY_GENERATION: "missing",
                AVATAR_CAPABILITY_VOICE: capability_status.get(AVATAR_CAPABILITY_VOICE, voice_ready),
                AVATAR_CAPABILITY_PORTRAIT: capability_status.get(AVATAR_CAPABILITY_PORTRAIT, portrait_ready),
                AVATAR_CAPABILITY_PREVIEW: "missing",
            },
            "先补齐讲话视频片段后再导入 HeyGem 训练。",
        )
    if not has_voice:
        return (
            {
                AVATAR_CAPABILITY_GENERATION: avatar_ready,
                AVATAR_CAPABILITY_VOICE: "missing",
                AVATAR_CAPABILITY_PORTRAIT: capability_status.get(AVATAR_CAPABILITY_PORTRAIT, portrait_ready),
                AVATAR_CAPABILITY_PREVIEW: "missing",
            },
            "已具备视频片段，需补充声音采样后才能做数字人口播预览。",
        )
    if not preview_service_available:
        return (
            {
                AVATAR_CAPABILITY_GENERATION: avatar_ready,
                AVATAR_CAPABILITY_VOICE: voice_ready,
                AVATAR_CAPABILITY_PORTRAIT: capability_status.get(AVATAR_CAPABILITY_PORTRAIT, portrait_ready),
                AVATAR_CAPABILITY_PREVIEW: "missing",
            },
            "未检测到可用的数字人口播预览服务（easy/submit）。请先启动 HeyGem 预览服务后再生成预览。",
        )

    return (
        {
            AVATAR_CAPABILITY_GENERATION: capability_status.get(AVATAR_CAPABILITY_GENERATION, avatar_ready),
            AVATAR_CAPABILITY_VOICE: capability_status.get(AVATAR_CAPABILITY_VOICE, voice_ready),
            AVATAR_CAPABILITY_PORTRAIT: capability_status.get(AVATAR_CAPABILITY_PORTRAIT, portrait_ready),
            AVATAR_CAPABILITY_PREVIEW: preview_ready,
        },
        "素材已通过基础预检，声音采样也已完成预处理，可以直接生成脚本驱动的数字人预览样片。"
        if preview_ready == "ready"
        else "素材已通过基础预检，可以先用原始声音样本生成数字人预览，后续再补训练预处理。",
    )


async def _save_material_file(
    *,
    profile_dir: Path,
    upload: UploadFile,
    payload: bytes,
    role: str,
) -> dict[str, Any]:
    original_name = upload.filename or "upload.bin"
    stored_name = sanitize_filename(original_name)
    file_path = profile_dir / stored_name
    file_path.write_bytes(payload)
    suffix = file_path.suffix.lower()
    kind = _guess_kind(suffix=suffix, content_type=str(upload.content_type or ""))
    resolved_role = _resolve_role(explicit_role=role, kind=kind)
    probe_payload: dict[str, Any] | None = None
    checks: list[dict[str, str]] = []

    if kind in {"video", "audio"}:
        try:
            meta = await probe(file_path)
            probe_payload = {
                "duration": meta.duration,
                "width": meta.width,
                "height": meta.height,
                "fps": meta.fps,
                "video_codec": meta.video_codec,
                "audio_codec": meta.audio_codec,
                "audio_sample_rate": meta.audio_sample_rate,
                "audio_channels": meta.audio_channels,
                "format_name": meta.format_name,
                "bit_rate": meta.bit_rate,
            }
            checks = _build_material_checks(role=resolved_role, kind=kind, meta=probe_payload)
        except Exception as exc:
            if avatar_material_role_matches_kind(resolved_role, kind):
                checks.append({"level": "error", "message": f"媒体探测失败，无法确认素材是否达标：{exc}"})
            else:
                checks.extend(_build_material_checks(role=resolved_role, kind=kind, meta={}))
    elif resolved_role == "portrait_photo":
        checks = _build_material_checks(role=resolved_role, kind=kind, meta={})
    else:
        checks = _build_material_checks(role=resolved_role, kind=kind, meta={})

    return {
        "id": uuid.uuid4().hex,
        "original_name": original_name,
        "stored_name": stored_name,
        "kind": kind,
        "role": resolved_role,
        "role_label": _role_label(resolved_role),
        "pipeline_target": _pipeline_target(resolved_role),
        "content_type": str(upload.content_type or "application/octet-stream"),
        "size_bytes": len(payload),
        "path": str(file_path),
        "created_at": now_iso(),
        "probe": probe_payload,
        "artifacts": None,
        "checks": checks,
    }


def _guess_kind(*, suffix: str, content_type: str) -> str:
    if suffix in _VIDEO_EXTENSIONS or content_type.startswith("video/"):
        return "video"
    if suffix in _IMAGE_EXTENSIONS or content_type.startswith("image/"):
        return "image"
    if suffix in _AUDIO_EXTENSIONS or content_type.startswith("audio/"):
        return "audio"
    return "other"


def _resolve_role(*, explicit_role: str, kind: str) -> str:
    if explicit_role in {"speaking_video", "portrait_photo", "voice_sample"}:
        return explicit_role
    if kind == "video":
        return "speaking_video"
    if kind == "image":
        return "portrait_photo"
    if kind == "audio":
        return "voice_sample"
    return "generic"


def _role_label(role: str) -> str:
    labels = {
        "speaking_video": "讲话视频片段",
        "portrait_photo": "肖像照",
        "voice_sample": "声音采样",
        "generic": "未分类素材",
    }
    return labels.get(role, role)


def _pipeline_target(role: str) -> str:
    targets = {
        "speaking_video": AVATAR_CAPABILITY_GENERATION,
        "portrait_photo": AVATAR_CAPABILITY_PORTRAIT,
        "voice_sample": AVATAR_CAPABILITY_VOICE,
        "generic": "manual_review",
    }
    return targets.get(role, "manual_review")


def _build_material_checks(*, role: str, kind: str, meta: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if not avatar_material_role_matches_kind(role, kind):
        checks.append(
            {
                "level": "error",
                "message": (
                    f"{_role_label(role)}字段只接受{_kind_label(_expected_kind_for_role(role))}文件，"
                    f"当前文件识别为{_kind_label(kind)}。"
                ),
            }
        )
        return checks

    duration = float(meta.get("duration") or 0.0)
    if role == "speaking_video" and kind == "video":
        if duration < 8.0:
            checks.append({"level": "error", "message": "讲话视频片段短于 8 秒，通常不足以做稳定训练。"})
        elif duration < 20.0:
            checks.append({"level": "warning", "message": "讲话视频片段短于推荐时长 20 秒，训练稳定性可能一般。"})
        elif duration > 120.0:
            checks.append({"level": "warning", "message": "讲话视频片段长于推荐时长 120 秒，建议裁到更集中的人像片段。"})
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        if max(width, height) < 720:
            checks.append({"level": "warning", "message": "分辨率低于 720p，建议上传更清晰的讲话视频片段。"})
        fps = float(meta.get("fps") or 0.0)
        if fps and fps < 20.0:
            checks.append({"level": "warning", "message": "帧率偏低，口型细节可能不够稳定。"})
        if not checks:
            checks.append({"level": "ok", "message": "讲话视频片段基础参数达标，可进入 HeyGem 人工复核。"})
        return checks

    if role == "voice_sample" and kind == "audio":
        if duration < 10.0:
            checks.append({"level": "warning", "message": "声音采样偏短，建议补 10 秒以上的干净人声。"})
        sample_rate = int(meta.get("audio_sample_rate") or 0)
        if sample_rate and sample_rate < 16000:
            checks.append({"level": "warning", "message": "采样率低于 16kHz，语音克隆质量可能受影响。"})
        if not checks:
            checks.append({"level": "ok", "message": "声音采样基础参数达标，可用于语音克隆。"})
        return checks

    if role == "portrait_photo" and kind == "image":
        checks.append({"level": "ok", "message": "肖像照已入库，可用于形象核验和模板管理。"})
        return checks

    return checks


def _expected_kind_for_role(role: str) -> str:
    return {
        "speaking_video": "video",
        "portrait_photo": "image",
        "voice_sample": "audio",
    }.get(role, "other")


def _kind_label(kind: str) -> str:
    return {
        "video": "视频",
        "image": "图片",
        "audio": "音频",
        "other": "可人工复核",
    }.get(kind, str(kind or "未知"))


def _has_ready_material(files: list[dict[str, Any]], role: str) -> bool:
    return any(
        str(item.get("role") or "") == role
        and avatar_material_role_matches_kind(item.get("role"), item.get("kind"))
        and not _has_blocking_material_issues([item])
        for item in files
    )


def _has_blocking_material_issues(files: list[dict[str, Any]]) -> bool:
    return any(
        str(check.get("level") or "").strip().lower() == "error"
        for file in files
        for check in (file.get("checks") or [])
    )


def _merge_checks(file_record: dict[str, Any], blocking_issues: list[str], warnings: list[str]) -> None:
    for check in file_record.get("checks") or []:
        level = str(check.get("level") or "")
        message = str(check.get("message") or "").strip()
        if not message:
            continue
        if level == "error":
            blocking_issues.append(f"{file_record.get('original_name')}: {message}")
        elif level == "warning":
            warnings.append(f"{file_record.get('original_name')}: {message}")


def _default_preview_script(profile: dict[str, Any]) -> str:
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    name = (
        str(identity.get("public_name") or "").strip()
        or str(profile.get("presenter_alias") or "").strip()
        or str(profile.get("display_name") or "该数字人").strip()
        or "该数字人"
    )
    return (
        f"大家好，我是{name}。"
        "现在这是一条 RoughCut 自动生成的数字人预览样片，"
        "主要用于检查音色一致性、口型同步和讲话镜头的整体稳定性。"
    )

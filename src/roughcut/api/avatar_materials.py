from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from roughcut.api.schemas import AvatarMaterialLibraryOut
from roughcut.avatar import (
    build_avatar_material_requirements,
    create_profile_dir,
    detect_avatar_material_library_warnings,
    delete_avatar_material_profile,
    get_avatar_material_profile,
    now_iso,
    normalize_creator_profile,
    normalize_avatar_personal_info,
    personal_info_from_creator_profile,
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
        if len(payload) > settings.max_upload_size_bytes:
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
    if len(payload) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=400, detail=f"{file.filename or 'file'} exceeds max upload size")

    profile_dir = Path(str(profile.get("profile_dir") or "")).resolve()
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)
    training_api_available = await is_heygem_training_available()
    preview_service_available = await is_heygem_preview_available()
    target = files[file_idx]
    target_role = str(target.get("role") or "generic")
    old_path = Path(str(target.get("path") or ""))
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
        profile["creator_profile"] = normalize_creator_profile(
            payload.creator_profile,
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
    file_path = Path(str(file_entry.get("path") or ""))
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

    file_path = Path(str(preview_run.get("output_path") or ""))
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

    heygem_ready = speaking_video_count > 0 and not any("讲话视频片段" in item for item in blocking_issues)
    voice_clone_ready = voice_sample_count > 0
    portrait_ready = portrait_photo_count > 0
    preview_ready = heygem_ready and voice_clone_ready and preview_service_available
    training_ready = heygem_ready

    return {
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "training_status": "ready_for_manual_training" if training_ready else "needs_more_material",
        "capability_status": {
            "heygem_avatar": "ready" if heygem_ready else "missing",
            "voice_clone": "ready" if voice_clone_ready else "missing",
            "portrait_reference": "ready" if portrait_ready else "missing",
            "preview": "ready" if preview_ready else "missing",
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


def _derive_runtime_preview_capability(
    capability_status: dict[str, str],
    files: list[dict[str, Any]],
    preview_service_available: bool,
) -> tuple[dict[str, str], str]:
    has_video = any(str(item.get("role") or "") == "speaking_video" for item in files)
    has_voice = any(str(item.get("role") or "") == "voice_sample" for item in files)
    has_portrait = any(str(item.get("role") or "") == "portrait_photo" for item in files)
    has_blocking_issues = any(
        str(check.get("level") or "").strip().lower() == "error"
        for file in files
        for check in (file.get("checks") or [])
    )

    if not files:
        return (
            {
                "heygem_avatar": "missing",
                "voice_clone": "missing",
                "portrait_reference": "missing",
                "preview": "missing",
            },
            "先补齐讲话视频片段或修复阻塞项，再导入 HeyGem 训练。",
        )

    heygem_ready = "ready" if has_video and not has_blocking_issues else "missing"
    voice_ready = "ready" if has_voice else "missing"
    portrait_ready = "ready" if has_portrait else "missing"
    preview_ready = "ready" if has_video and has_voice and preview_service_available else "missing"

    if has_blocking_issues:
        return (
            {
                "heygem_avatar": "missing" if capability_status.get("heygem_avatar") == "missing" else heygem_ready,
                "voice_clone": capability_status.get("voice_clone", voice_ready),
                "portrait_reference": capability_status.get("portrait_reference", portrait_ready),
                "preview": "missing",
            },
            "素材存在阻塞项，先修复后再继续。",
        )

    if not has_video:
        return (
            {
                "heygem_avatar": "missing",
                "voice_clone": capability_status.get("voice_clone", voice_ready),
                "portrait_reference": capability_status.get("portrait_reference", portrait_ready),
                "preview": "missing",
            },
            "先补齐讲话视频片段后再导入 HeyGem 训练。",
        )
    if not has_voice:
        return (
            {
                "heygem_avatar": heygem_ready,
                "voice_clone": "missing",
                "portrait_reference": capability_status.get("portrait_reference", portrait_ready),
                "preview": "missing",
            },
            "已具备视频片段，需补充声音采样后才能做数字人口播预览。",
        )
    if not preview_service_available:
        return (
            {
                "heygem_avatar": heygem_ready,
                "voice_clone": voice_ready,
                "portrait_reference": capability_status.get("portrait_reference", portrait_ready),
                "preview": "missing",
            },
            "未检测到可用的数字人口播预览服务（easy/submit）。请先启动 HeyGem 预览服务后再生成预览。",
        )

    return (
        {
            "heygem_avatar": capability_status.get("heygem_avatar", heygem_ready),
            "voice_clone": capability_status.get("voice_clone", voice_ready),
            "portrait_reference": capability_status.get("portrait_reference", portrait_ready),
            "preview": preview_ready,
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
            checks.append({"level": "warning", "message": f"媒体探测失败：{exc}"})
    elif resolved_role == "portrait_photo":
        checks = [{"level": "ok", "message": "肖像照已入库，可用于形象核验和模板管理。"}]

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
        "speaking_video": "heygem_avatar",
        "portrait_photo": "avatar_identity",
        "voice_sample": "voice_clone",
        "generic": "manual_review",
    }
    return targets.get(role, "manual_review")


def _build_material_checks(*, role: str, kind: str, meta: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
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

    return checks


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

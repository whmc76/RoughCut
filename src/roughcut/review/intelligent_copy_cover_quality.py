from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from roughcut.media.output import _title_style_tokens


DEFAULT_ASPECT_RATIO_TOLERANCE = 0.08


def assess_cover_publish_readiness(
    cover_generation_metadata: dict[str, Any] | None,
    request_payload: dict[str, Any] | None,
    output_path: str | Path | None,
    *,
    aspect_ratio_tolerance: float = DEFAULT_ASPECT_RATIO_TOLERANCE,
) -> dict[str, Any]:
    """Assess whether a generated cover result is ready for publication."""

    cover_generation = cover_generation_metadata if isinstance(cover_generation_metadata, dict) else {}
    metadata = _image_generation_metadata(cover_generation)
    request = request_payload if isinstance(request_payload, dict) else {}
    path = Path(output_path) if output_path else None
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    backend = str(metadata.get("backend") or request.get("backend") or "").strip().lower()
    effective_source = _effective_cover_source(cover_generation)
    trusted_master_output_path = _resolve_trusted_master_output_path(
        cover_generation_metadata=cover_generation,
        request_payload=request,
    )

    request_status = _normalized_status(request.get("status"))
    metadata_status = _normalized_status(metadata.get("status"))
    request_status = _resolve_effective_cover_status(
        status=request_status,
        backend=backend,
        payload=request,
        output_path=path,
        counterpart_status=metadata_status,
    )
    metadata_status = _resolve_effective_cover_status(
        status=metadata_status,
        backend=backend,
        payload=metadata,
        output_path=path,
        counterpart_status=request_status,
    )

    if backend in {"", "codex_builtin"}:
        if not request:
            blocking_reasons.append("封面 Codex imagegen 请求缺失或不可读")
        _append_status_blockers(
            blocking_reasons,
            status=request_status,
            label="封面 Codex imagegen 请求",
            pending_reason="封面等待 Codex 内置 imagegen 执行完成",
        )
    elif not request:
        warnings.append("封面请求快照缺失，已仅根据生成元数据和输出文件继续校验")
    if metadata_status:
        _append_status_blockers(
            blocking_reasons,
            status=metadata_status,
            label="封面生成元数据",
            pending_reason="封面生成元数据仍标记为等待图片生成完成",
        )
    if effective_source == "reference_cover_fallback":
        blocking_reasons.append("封面当前仅为参考帧占位图，正式生图尚未完成")

    if path is None:
        blocking_reasons.append("封面输出路径缺失")
    elif not path.exists():
        blocking_reasons.append(f"封面输出文件不存在：{path}")
    elif not path.is_file():
        blocking_reasons.append(f"封面输出路径不是文件：{path}")

    if path is not None:
        _check_output_path_matches_request(
            blocking_reasons,
            request=request,
            output_path=path,
            trusted_master_output_path=trusted_master_output_path,
        )
        _check_output_path_matches_metadata(
            blocking_reasons,
            metadata=metadata,
            output_path=path,
            trusted_master_output_path=trusted_master_output_path,
        )
        _check_subject_consistency(blocking_reasons, warnings, metadata=metadata)
        _check_cover_hard_contract(blocking_reasons, warnings, request=request, metadata=metadata)

    target_size = _extract_target_size(request, metadata)
    image_dimensions: dict[str, int] | None = None
    if path is not None and path.exists() and path.is_file():
        _check_stale_output(
            blocking_reasons,
            warnings,
            request=request,
            output_path=path,
            trusted_master_output_path=trusted_master_output_path,
        )
        width, height, dimension_warning = _read_image_dimensions(path)
        if dimension_warning:
            warnings.append(dimension_warning)
        if width and height:
            image_dimensions = {"width": width, "height": height}
            _check_aspect_ratio(
                blocking_reasons,
                output_width=width,
                output_height=height,
                target_size=target_size,
                tolerance=aspect_ratio_tolerance,
            )
            _check_overlay_layout_occupancy(
                blocking_reasons,
                warnings,
                request=request,
                canvas_size=image_dimensions,
            )
    elif target_size is None:
        warnings.append("封面目标尺寸缺失，无法校验平台比例")

    return {
        "publish_ready": not blocking_reasons,
        "blocking_reasons": _dedupe(blocking_reasons),
        "warnings": _dedupe(warnings),
        "output_path": str(path) if path is not None else None,
        "target_size": target_size,
        "image_dimensions": image_dimensions,
    }


def _effective_cover_source(cover_generation_metadata: dict[str, Any] | None) -> str:
    if not isinstance(cover_generation_metadata, dict):
        return ""
    source = str(cover_generation_metadata.get("source") or "").strip().lower()
    if source:
        group_generation = (
            cover_generation_metadata.get("group_generation")
            if isinstance(cover_generation_metadata.get("group_generation"), dict)
            else {}
        )
        nested_source = str(group_generation.get("source") or "").strip().lower()
        if source == "cover_group_reuse" and nested_source:
            return nested_source
        return source
    group_generation = (
        cover_generation_metadata.get("group_generation")
        if isinstance(cover_generation_metadata.get("group_generation"), dict)
        else {}
    )
    return str(group_generation.get("source") or "").strip().lower()


def _image_generation_metadata(cover_generation_metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cover_generation_metadata, dict):
        return {}
    nested = cover_generation_metadata.get("image_generation")
    if isinstance(nested, dict):
        return nested
    return cover_generation_metadata


def _normalized_status(status: Any) -> str:
    return str(status or "").strip().lower()


def _append_status_blockers(
    blocking_reasons: list[str],
    *,
    status: str,
    label: str,
    pending_reason: str,
) -> None:
    if status == "completed":
        return
    if status in {"pending", "pending_codex_imagegen", "queued", "running", "in_progress"}:
        blocking_reasons.append(pending_reason)
        return
    if status in {"failed", "error", "cancelled", "canceled"}:
        blocking_reasons.append(f"{label}失败：status={status}")
        return
    if not status:
        blocking_reasons.append(f"{label}缺少 status=completed")
        return
    blocking_reasons.append(f"{label}状态不是 completed：status={status}")


def _resolve_effective_cover_status(
    *,
    status: str,
    backend: str,
    payload: dict[str, Any] | None,
    output_path: Path | None,
    counterpart_status: str,
) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "completed":
        return "completed"
    if counterpart_status == "completed" and _cover_output_exists(output_path):
        return "completed"
    if normalized in {"pending", "pending_codex_imagegen", "queued", "running", "in_progress"}:
        if backend in {"", "codex_builtin"} and _cover_payload_has_completion_evidence(payload) and _cover_output_exists(output_path):
            return "completed"
    return normalized


def _cover_output_exists(output_path: Path | None) -> bool:
    if output_path is None:
        return False
    try:
        return output_path.exists() and output_path.is_file()
    except OSError:
        return False


def _cover_payload_has_completion_evidence(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for field in (
        "completed_at",
        "result_path",
        "bitmap_title_contract_verified_at",
        "bitmap_unexpected_text_checked_at",
        "compare_subject_contract_checked_at",
    ):
        if str(payload.get(field) or "").strip():
            return True
    if bool(payload.get("post_title_overlay_applied")) or bool(payload.get("generated_by_codex_bridge")):
        return True
    return False


def _check_output_path_matches_request(
    blocking_reasons: list[str],
    *,
    request: dict[str, Any],
    output_path: Path,
    trusted_master_output_path: Path | None = None,
) -> None:
    recorded = str(request.get("output_path") or "").strip()
    if not recorded:
        return
    recorded_path = Path(recorded)
    if trusted_master_output_path is not None and recorded_path == trusted_master_output_path:
        return
    if recorded_path != output_path:
        blocking_reasons.append(f"封面请求 output_path 与待发布文件不一致：{recorded} != {output_path}")


def _check_output_path_matches_metadata(
    blocking_reasons: list[str],
    *,
    metadata: dict[str, Any],
    output_path: Path,
    trusted_master_output_path: Path | None = None,
) -> None:
    recorded = str(metadata.get("output_path") or "").strip()
    if not recorded:
        return
    recorded_path = Path(recorded)
    if trusted_master_output_path is not None and recorded_path == trusted_master_output_path:
        return
    if recorded_path != output_path:
        blocking_reasons.append(f"封面生成元数据 output_path 与待发布文件不一致：{recorded} != {output_path}")


def _check_stale_output(
    blocking_reasons: list[str],
    warnings: list[str],
    *,
    request: dict[str, Any],
    output_path: Path,
    trusted_master_output_path: Path | None = None,
) -> None:
    if trusted_master_output_path is not None and trusted_master_output_path.exists():
        master_mtime = datetime.fromtimestamp(trusted_master_output_path.stat().st_mtime)
        output_mtime = datetime.fromtimestamp(output_path.stat().st_mtime)
        if output_mtime.timestamp() + 1 < master_mtime.timestamp():
            blocking_reasons.append("平台封面副本早于已验证母版，可能是旧 stale derivative")
        return
    created_at = _parse_datetime(request.get("created_at"))
    if created_at is None:
        warnings.append("封面请求缺少 created_at，无法确认输出文件是否为本次生成")
        return
    output_mtime = datetime.fromtimestamp(output_path.stat().st_mtime, tz=created_at.tzinfo)
    if output_mtime.timestamp() + 1 < created_at.timestamp():
        blocking_reasons.append("封面输出文件早于本次 Codex imagegen 请求，可能是旧 stale output")


def _resolve_trusted_master_output_path(
    *,
    cover_generation_metadata: dict[str, Any],
    request_payload: dict[str, Any],
) -> Path | None:
    source_kind = str(cover_generation_metadata.get("source") or "").strip().lower()
    if source_kind != "cover_group_reuse":
        return None
    cover_group = (
        cover_generation_metadata.get("cover_group")
        if isinstance(cover_generation_metadata.get("cover_group"), dict)
        else {}
    )
    group_generation = (
        cover_generation_metadata.get("group_generation")
        if isinstance(cover_generation_metadata.get("group_generation"), dict)
        else {}
    )
    image_generation = (
        group_generation.get("image_generation")
        if isinstance(group_generation.get("image_generation"), dict)
        else {}
    )
    for raw_path in (
        request_payload.get("output_path"),
        image_generation.get("output_path"),
        group_generation.get("output_path"),
        cover_group.get("cover_path"),
    ):
        text = str(raw_path or "").strip()
        if text:
            return Path(text)
    return None


def _check_subject_consistency(
    blocking_reasons: list[str],
    warnings: list[str],
    *,
    metadata: dict[str, Any],
) -> None:
    passed = metadata.get("subject_consistency_passed")
    score = _positive_float(metadata.get("subject_consistency_score"))
    deformation_risk = _positive_float(metadata.get("deformation_risk"))
    reason = str(metadata.get("subject_consistency_reason") or "").strip()
    if passed is False:
        detail = []
        if score is not None:
            detail.append(f"score={score:.2f}")
        if deformation_risk is not None:
            detail.append(f"deformation_risk={deformation_risk:.2f}")
        suffix = f"（{'，'.join(detail)}）" if detail else ""
        explanation = f"：{reason}" if reason else ""
        blocking_reasons.append(f"封面主体与参考图一致性不足{suffix}{explanation}")
        return
    if score is not None and score < 0.72:
        warnings.append(f"封面主体一致性偏低：score={score:.2f}")
    if deformation_risk is not None and deformation_risk > 0.45:
        warnings.append(f"封面主体变形风险偏高：deformation_risk={deformation_risk:.2f}")


def _check_cover_hard_contract(
    blocking_reasons: list[str],
    warnings: list[str],
    *,
    request: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    contract = request.get("cover_hard_contract") if isinstance(request.get("cover_hard_contract"), dict) else {}
    if not contract:
        return
    typography_owner = str(
        ((request.get("cover_director_policy") or {}) if isinstance(request.get("cover_director_policy"), dict) else {}).get("typography_owner")
        or ""
    ).strip().lower()
    full_cover_typography_required = typography_owner in {"codex_full_cover", "bitmap_full_cover", "imagegen_full_cover"}
    image_text_quality_is_blocking = (
        typography_owner == "local_post_overlay"
        or bool(contract.get("post_title_overlay_required"))
        or bool(contract.get("full_bitmap_cover_required"))
        or full_cover_typography_required
    )
    if bool(contract.get("preserve_subject_geometry")):
        deformation_risk = _positive_float(metadata.get("deformation_risk"))
        if deformation_risk is not None and deformation_risk > 0.35:
            message = f"封面主体几何稳定性不满足硬合同：deformation_risk={deformation_risk:.2f}"
            if image_text_quality_is_blocking:
                blocking_reasons.append(message)
            else:
                warnings.append(message)
    if typography_owner == "local_post_overlay" and not request.get("bitmap_unexpected_text_checked_at"):
        blocking_reasons.append("封面位图额外文字校验未完成，不能放行到最终封面")
    if typography_owner == "local_post_overlay" and bool(request.get("bitmap_unexpected_text_check_unavailable")):
        blocking_reasons.append("封面位图额外文字校验未产出有效结论，不能放行到最终封面")
    if bool(contract.get("compare_subject_pair_required")) and not request.get("compare_subject_contract_checked_at"):
        if image_text_quality_is_blocking:
            blocking_reasons.append("对比封面双主体校验未完成，不能放行到最终封面")
        else:
            warnings.append("对比封面双主体校验未完成，已降级为提示")
    if bool(request.get("compare_subject_contract_check_unavailable")):
        if image_text_quality_is_blocking:
            blocking_reasons.append("对比封面双主体校验未产出有效结论，不能放行到最终封面")
        else:
            warnings.append("对比封面双主体校验未产出有效结论，已降级为提示")
    if typography_owner == "local_post_overlay" and bool(request.get("bitmap_unexpected_text_detected")):
        detected_lines = request.get("bitmap_unexpected_text_detected_lines")
        detected_text = ", ".join(
            str(item).strip() for item in detected_lines if str(item).strip()
        ) if isinstance(detected_lines, list) else ""
        reason = str(request.get("bitmap_unexpected_text_reason") or "").strip()
        suffix = f"：{detected_text}" if detected_text else ""
        explanation = f"（{reason}）" if reason else ""
        blocking_reasons.append(f"封面位图仍含额外可读文字或伪标题{suffix}{explanation}")
    if bool(contract.get("compare_subject_pair_required")) and request.get("compare_subject_contract_passed") is False:
        reason = str(request.get("compare_subject_contract_reason") or "").strip()
        explanation = f"：{reason}" if reason else ""
        message = f"对比封面双主体展示不满足硬合同{explanation}"
        if image_text_quality_is_blocking:
            blocking_reasons.append(message)
        else:
            warnings.append(message)
    bitmap_title_verification_unavailable = bool(request.get("bitmap_title_contract_check_unavailable"))
    actual_lines, title_contract_satisfied = _resolve_verified_cover_title_lines(request)
    if bool(contract.get("post_title_overlay_required")) and not title_contract_satisfied:
        blocking_reasons.append("封面标题后叠字未完成，不满足品牌/型号主标题与配置副标题硬合同")
    if (bool(contract.get("full_bitmap_cover_required")) or full_cover_typography_required) and not bool(request.get("bitmap_title_contract_verified_at")):
        if image_text_quality_is_blocking:
            blocking_reasons.append("完整封面位图标题校验未完成，不能放行到最终封面")
        else:
            warnings.append("完整封面位图标题校验未完成，已降级为提示")
    if (bool(contract.get("full_bitmap_cover_required")) or full_cover_typography_required) and request.get("bitmap_title_contract_passed") is False:
        reason = str(request.get("bitmap_title_contract_reason") or "").strip()
        explanation = f"：{reason}" if reason else ""
        message = f"完整封面位图标题不满足硬合同{explanation}"
        if image_text_quality_is_blocking:
            blocking_reasons.append(message)
        else:
            warnings.append(message)
    required_lines = contract.get("required_title_lines") if isinstance(contract.get("required_title_lines"), dict) else {}
    required_top = str(required_lines.get("top") or "").strip()
    required_main = str(required_lines.get("main") or "").strip()
    required_bottom = str(required_lines.get("bottom") or "").strip()
    actual_top = str(actual_lines.get("top") or "").strip()
    actual_main = str(actual_lines.get("main") or "").strip()
    actual_bottom = str(actual_lines.get("bottom") or "").strip()
    if bool(contract.get("brand_model_title_required")) and required_top and actual_top != required_top:
        message = "封面品牌行未稳定锁定，存在内容签名漂移风险"
        if image_text_quality_is_blocking:
            blocking_reasons.append(message)
        else:
            warnings.append(message)
    if bool(contract.get("brand_model_title_required")) and required_main and actual_main != required_main:
        message = "封面主标题未稳定锁定品牌/型号，存在内容签名漂移风险"
        if image_text_quality_is_blocking:
            blocking_reasons.append(message)
        else:
            warnings.append(message)
    if bool(contract.get("config_subtitle_required")) and required_bottom and actual_bottom != required_bottom:
        message = "封面配置副标题未稳定锁定，存在内容签名漂移风险"
        if image_text_quality_is_blocking:
            blocking_reasons.append(message)
        else:
            warnings.append(message)
    style_key = str(contract.get("unified_style_key") or "").strip()
    style_verified = bool(str(request.get("post_title_overlay_title_style") or "").strip()) or bool(request.get("bitmap_title_style_verified"))
    if style_key and not style_verified:
        warnings.append(f"封面未记录标题风格校验，无法完全确认组内风格统一：style={style_key}")
    if bool(contract.get("signature_stability_required")):
        if not title_contract_satisfied or (required_top and actual_top != required_top) or (required_main and actual_main != required_main):
            warnings.append("signature_stability_risk: cover title contract not locked")
    if bitmap_title_verification_unavailable and (bool(contract.get("full_bitmap_cover_required")) or full_cover_typography_required):
        blocking_reasons.append("完整封面位图标题校验未产出有效结论，不能放行到最终封面")
    elif bitmap_title_verification_unavailable:
        warnings.append("bitmap_title_contract_verification_unavailable: cover accepted without OCR-style title proof")


def _check_overlay_layout_occupancy(
    blocking_reasons: list[str],
    warnings: list[str],
    *,
    request: dict[str, Any],
    canvas_size: dict[str, int] | None,
) -> None:
    if not isinstance(canvas_size, dict):
        return
    width = _positive_int(canvas_size.get("width"))
    height = _positive_int(canvas_size.get("height"))
    if not width or not height:
        return
    if not bool(request.get("post_title_overlay_applied")):
        return
    lines = request.get("post_title_overlay_lines") if isinstance(request.get("post_title_overlay_lines"), dict) else {}
    if not lines:
        return
    title_style = str(request.get("post_title_overlay_title_style") or "").strip()
    cover_style = str(request.get("post_title_overlay_group_style") or "").strip()
    if not title_style:
        return
    try:
        tokens = _title_style_tokens(
            title_style,
            title_lines={
                "top": str(lines.get("top") or "").strip(),
                "main": str(lines.get("main") or "").strip(),
                "bottom": str(lines.get("bottom") or "").strip(),
            },
            cover_style=cover_style,
        )
    except Exception:
        return
    if not isinstance(tokens, dict):
        return
    top_ratio = _layout_font_ratio(tokens, "top", height)
    main_ratio = _layout_font_ratio(tokens, "main", height)
    bottom_ratio = _layout_font_ratio(tokens, "bottom", height)
    total_ratio = top_ratio + main_ratio + bottom_ratio
    main_width_ratio = _layout_safe_width_ratio(tokens, "main")
    is_landscape = width > height
    if main_ratio > 0.17 or total_ratio > 0.34:
        blocking_reasons.append(
            "封面后叠字占主体区域过大，当前标题层已压缩主体展示，不满足最终封面质量要求"
        )
        return
    if is_landscape and main_ratio > 0.14 and main_width_ratio > 0.58:
        blocking_reasons.append(
            "横版封面主标题覆盖范围过宽，已影响主体对比信息展示"
        )
        return
    if total_ratio > 0.28:
        warnings.append("封面标题层占比偏高，建议进一步收紧字号或上移标题安全区")


def _layout_font_ratio(tokens: dict[str, Any], key: str, height: int) -> float:
    section = tokens.get(key) if isinstance(tokens.get(key), dict) else {}
    size = _positive_float(section.get("size")) or 0.0
    return size / max(float(height), 1.0)


def _layout_safe_width_ratio(tokens: dict[str, Any], key: str) -> float:
    section = tokens.get(key) if isinstance(tokens.get(key), dict) else {}
    ratio = _positive_float(section.get("safe_width_ratio"))
    return ratio if ratio is not None else 1.0


def _resolve_verified_cover_title_lines(request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    typography_owner = str(
        ((request.get("cover_director_policy") or {}) if isinstance(request.get("cover_director_policy"), dict) else {}).get("typography_owner")
        or ""
    ).strip().lower()
    overlay_lines = request.get("post_title_overlay_lines") if isinstance(request.get("post_title_overlay_lines"), dict) else {}
    if bool(request.get("post_title_overlay_applied")) and overlay_lines:
        return overlay_lines, True
    if typography_owner == "local_post_overlay":
        return {}, False
    bitmap_lines = request.get("bitmap_title_lines") if isinstance(request.get("bitmap_title_lines"), dict) else {}
    if bool(request.get("bitmap_title_contract_passed")) and bitmap_lines:
        return bitmap_lines, True
    if bool(request.get("bitmap_title_contract_check_unavailable")):
        fallback_lines = _extract_required_title_lines(request)
        if fallback_lines:
            return fallback_lines, False
    return {}, False


def _extract_required_title_lines(request: dict[str, Any]) -> dict[str, str]:
    contract = request.get("cover_hard_contract") if isinstance(request.get("cover_hard_contract"), dict) else {}
    required_lines = contract.get("required_title_lines") if isinstance(contract.get("required_title_lines"), dict) else {}
    if not isinstance(required_lines, dict):
        return {}
    return {
        key: str(required_lines.get(key) or "").strip()
        for key in ("brand", "top", "main", "sub", "bottom", "hook")
        if str(required_lines.get(key) or "").strip()
    }


def _extract_target_size(*sources: dict[str, Any]) -> dict[str, int] | None:
    for source in sources:
        size = source.get("target_size")
        if isinstance(size, dict):
            width = _positive_int(size.get("width"))
            height = _positive_int(size.get("height"))
            if width and height:
                return {"width": width, "height": height}
        width = _positive_int(source.get("width"))
        height = _positive_int(source.get("height"))
        if width and height:
            return {"width": width, "height": height}
    return None


def _check_aspect_ratio(
    blocking_reasons: list[str],
    *,
    output_width: int,
    output_height: int,
    target_size: dict[str, int] | None,
    tolerance: float,
) -> None:
    if not target_size:
        return
    target_ratio = target_size["width"] / target_size["height"]
    output_ratio = output_width / output_height
    relative_delta = abs(output_ratio - target_ratio) / target_ratio
    if relative_delta > max(0.0, tolerance):
        blocking_reasons.append(
            "封面尺寸比例与平台目标严重不符："
            f"output={output_width}x{output_height}, "
            f"target={target_size['width']}x{target_size['height']}"
        )


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed


def _read_image_dimensions(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        from PIL import Image
    except ImportError:
        return None, None, "未安装 Pillow，已跳过封面尺寸比例校验"

    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:
        return None, None, f"无法读取封面图片尺寸，已跳过比例校验：{exc}"
    return int(width), int(height), None


def _dedupe(items: list[str]) -> list[str]:
    return [item for item in dict.fromkeys(str(item).strip() for item in items) if item]

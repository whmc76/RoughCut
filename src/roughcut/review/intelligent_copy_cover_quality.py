from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ASPECT_RATIO_TOLERANCE = 0.08


def assess_cover_publish_readiness(
    cover_generation_metadata: dict[str, Any] | None,
    request_payload: dict[str, Any] | None,
    output_path: str | Path | None,
    *,
    aspect_ratio_tolerance: float = DEFAULT_ASPECT_RATIO_TOLERANCE,
) -> dict[str, Any]:
    """Assess whether a Codex imagegen cover result is ready for publication."""

    metadata = _image_generation_metadata(cover_generation_metadata)
    request = request_payload if isinstance(request_payload, dict) else {}
    path = Path(output_path) if output_path else None
    blocking_reasons: list[str] = []
    warnings: list[str] = []

    request_status = _normalized_status(request.get("status"))
    metadata_status = _normalized_status(metadata.get("status"))

    if not request:
        blocking_reasons.append("封面 Codex imagegen 请求缺失或不可读")
    _append_status_blockers(
        blocking_reasons,
        status=request_status,
        label="封面 Codex imagegen 请求",
        pending_reason="封面等待 Codex 内置 imagegen 执行完成",
    )
    if metadata_status:
        _append_status_blockers(
            blocking_reasons,
            status=metadata_status,
            label="封面生成元数据",
            pending_reason="封面生成元数据仍标记为等待 Codex 内置 imagegen 执行完成",
        )

    if path is None:
        blocking_reasons.append("封面输出路径缺失")
    elif not path.exists():
        blocking_reasons.append(f"封面输出文件不存在：{path}")
    elif not path.is_file():
        blocking_reasons.append(f"封面输出路径不是文件：{path}")

    if path is not None:
        _check_output_path_matches_request(blocking_reasons, request=request, output_path=path)
        _check_output_path_matches_metadata(blocking_reasons, metadata=metadata, output_path=path)

    target_size = _extract_target_size(request, metadata)
    image_dimensions: dict[str, int] | None = None
    if path is not None and path.exists() and path.is_file():
        _check_stale_output(blocking_reasons, warnings, request=request, output_path=path)
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


def _check_output_path_matches_request(
    blocking_reasons: list[str],
    *,
    request: dict[str, Any],
    output_path: Path,
) -> None:
    recorded = str(request.get("output_path") or "").strip()
    if recorded and Path(recorded) != output_path:
        blocking_reasons.append(f"封面请求 output_path 与待发布文件不一致：{recorded} != {output_path}")


def _check_output_path_matches_metadata(
    blocking_reasons: list[str],
    *,
    metadata: dict[str, Any],
    output_path: Path,
) -> None:
    recorded = str(metadata.get("output_path") or "").strip()
    if recorded and Path(recorded) != output_path:
        blocking_reasons.append(f"封面生成元数据 output_path 与待发布文件不一致：{recorded} != {output_path}")


def _check_stale_output(
    blocking_reasons: list[str],
    warnings: list[str],
    *,
    request: dict[str, Any],
    output_path: Path,
) -> None:
    created_at = _parse_datetime(request.get("created_at"))
    if created_at is None:
        warnings.append("封面请求缺少 created_at，无法确认输出文件是否为本次生成")
        return
    output_mtime = datetime.fromtimestamp(output_path.stat().st_mtime, tz=created_at.tzinfo)
    if output_mtime.timestamp() + 1 < created_at.timestamp():
        blocking_reasons.append("封面输出文件早于本次 Codex imagegen 请求，可能是旧 stale output")


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

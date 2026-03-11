"""
Output package: MP4 + SRT + cover image — one complete set per job.
Naming: {YYYYMMDD}_{original_stem}.{ext}

Cover generation:
- rank multiple candidate frames from the edited video
- export several cover variants for manual selection
- apply a three-line title layout inspired by existing channel thumbnails
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text


def _sanitize(name: str) -> str:
    """Remove chars not safe for filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_output_name(source_name: str, created_at: datetime | None = None) -> str:
    settings = get_settings()
    dt = created_at or datetime.now()
    stem = Path(source_name).stem
    pattern = settings.output_name_pattern
    name = pattern.format(date=dt.strftime("%Y%m%d"), stem=stem)
    return _sanitize(name)


def get_output_dir() -> Path:
    settings = get_settings()
    p = Path(settings.output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def extract_cover_frame(
    video_path: Path,
    output_path: Path,
    *,
    seek_sec: float = 3.0,
    content_profile: dict[str, Any] | None = None,
) -> list[Path]:
    """
    Export one primary cover plus additional ranked variants.

    We rank candidate frames from the edited video so the chosen cover better
    matches the delivered cut, then overlay a three-line title when available.
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration(video_path)
    variant_count = max(1, settings.cover_output_variants)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        if duration > 0:
            candidates = _sample_cover_candidates(
                video_path,
                duration=duration,
                candidate_count=max(settings.cover_candidate_count, variant_count),
                tmpdir=tmp,
            )
        else:
            candidates = []

        if not candidates:
            candidates = [{"seek": seek_sec, "preview": None}]

        ranked_indices = await _rank_cover_candidates(
            candidates,
            content_profile=content_profile,
            variant_count=variant_count,
        )
        selected = [candidates[idx] for idx in ranked_indices[:variant_count] if idx < len(candidates)]
        if not selected:
            selected = [candidates[0]]
        if len(selected) < variant_count:
            chosen_ids = {id(candidate) for candidate in selected}
            for candidate in candidates:
                if id(candidate) in chosen_ids:
                    continue
                selected.append(candidate)
                if len(selected) >= variant_count:
                    break

        title_lines = _resolve_cover_title(content_profile)
        title_lines = await _refine_cover_title_from_candidates(selected, content_profile=content_profile, fallback=title_lines)
        cover_style = (content_profile or {}).get("preset", {}).get("cover_style", "tech_showcase")

        outputs: list[Path] = []
        for i, candidate in enumerate(selected):
            target = output_path if i == 0 else output_path.with_name(f"{output_path.stem}_v{i + 1}{output_path.suffix}")
            await _extract_frame(video_path, target, candidate["seek"])
            if title_lines:
                try:
                    await _overlay_title_layout(target, title_lines, cover_style)
                except Exception:
                    pass
            outputs.append(target)

    return outputs


def _probe_duration(video_path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True,
            timeout=10,
        )
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _sample_cover_candidates(
    video_path: Path,
    *,
    duration: float,
    candidate_count: int,
    tmpdir: Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for i in range(candidate_count):
        seek = duration * (i + 1) / (candidate_count + 1)
        out = tmpdir / f"cand_{i:02d}.jpg"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{seek:.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-update",
                "1",
                "-q:v",
                "4",
                "-vf",
                "scale=768:-2",
                str(out),
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and out.exists():
            candidates.append({"seek": seek, "preview": out})
    return candidates


async def _rank_cover_candidates(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any] | None,
    variant_count: int,
) -> list[int]:
    preview_paths = [candidate["preview"] for candidate in candidates if candidate.get("preview")]
    if preview_paths:
        try:
            profile_text = json.dumps(content_profile or {}, ensure_ascii=False)
            prompt = (
                "你在为中文开箱/评测视频挑封面。请从候选帧里选出最适合做封面的前几名，"
                "优先级标准：主体完整清晰、品牌或盒体信息可见、构图紧凑、情绪强、适合后续叠加大字。"
                "优先选产品正面、包装正面、logo/型号能看出来的画面。"
                "避免只看到手、主体太小、糊帧、无重点、文字会挡住主体的画面。"
                f"\n视频主题参考：{profile_text}"
                f"\n输出 JSON：{{\"best_indices\":[0,1,2]}}，最多返回 {variant_count} 个索引，按优先级排序。"
            )
            content = await complete_with_images(prompt, preview_paths, max_tokens=220, json_mode=True)
            data = json.loads(extract_json_text(content))
            ordered = []
            for raw in data.get("best_indices", []):
                idx = int(raw)
                if 0 <= idx < len(candidates) and idx not in ordered:
                    ordered.append(idx)
            if ordered:
                return ordered
        except Exception:
            pass

    fallback = list(range(len(candidates)))
    return fallback[:variant_count]


async def _refine_cover_title_from_candidates(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any] | None,
    fallback: dict[str, str] | None,
) -> dict[str, str] | None:
    preview_paths = [candidate["preview"] for candidate in candidates if candidate.get("preview")]
    if preview_paths:
        try:
            prompt = (
                "你在给中文开箱/EDC 视频制作封面标题。请结合候选封面画面，优先识别盒体、logo、品牌、系列字样，"
                "给出三段短标题 JSON：{\"top\":\"\",\"main\":\"\",\"bottom\":\"\"}。"
                "要求：\n"
                "1. top 优先品牌或系列，长度 2-12 字。\n"
                "2. main 必须是主体名或产品类型，不要写“产品开箱与上手体验”“升级对比版”这类泛词。\n"
                "3. bottom 是钩子句，长度 6-12 字。\n"
                "4. 如果画面里出现英文品牌，请直接保留品牌英文。"
                f"\n已有上下文：{json.dumps(content_profile or {}, ensure_ascii=False)}"
            )
            content = await complete_with_images(prompt, preview_paths[:3], max_tokens=260, json_mode=True)
            data = json.loads(extract_json_text(content))
            refined = {
                "top": str(data.get("top") or "").strip(),
                "main": str(data.get("main") or "").strip(),
                "bottom": str(data.get("bottom") or "").strip(),
            }
            if _cover_title_is_usable(refined):
                return refined
        except Exception:
            pass
    return fallback


async def _extract_frame(video_path: Path, output_path: Path, seek_sec: float) -> None:
    settings = get_settings()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(seek_sec),
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-update",
                "1",
                "-q:v",
                "2",
                "-vf",
                "scale=1280:-2",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cover extraction failed: {result.stderr[-500:]}")


def _resolve_cover_title(content_profile: dict[str, Any] | None) -> dict[str, str] | None:
    settings = get_settings()
    if settings.cover_title.strip():
        parts = [part.strip() for part in settings.cover_title.split("|")]
        return {
            "top": parts[0] if len(parts) > 0 else "",
            "main": parts[1] if len(parts) > 1 else parts[0],
            "bottom": parts[2] if len(parts) > 2 else "",
        }

    if not content_profile:
        return None
    cover_title = content_profile.get("cover_title")
    if not isinstance(cover_title, dict):
        return None
    if not any(cover_title.get(key) for key in ("top", "main", "bottom")):
        return None
    return {
        "top": str(cover_title.get("top") or "").strip(),
        "main": str(cover_title.get("main") or "").strip(),
        "bottom": str(cover_title.get("bottom") or "").strip(),
    }


def _cover_title_is_usable(title_lines: dict[str, str] | None) -> bool:
    if not title_lines:
        return False
    main = re.sub(r"\s+", "", str(title_lines.get("main") or ""))
    if not main:
        return False
    generic_fragments = (
        "产品开箱",
        "上手体验",
        "升级对比版",
        "开箱体验",
        "产品体验",
        "简单开箱",
    )
    return not any(fragment in main for fragment in generic_fragments)


async def _overlay_title_layout(
    cover_path: Path,
    title_lines: dict[str, str],
    cover_style: str,
) -> None:
    settings = get_settings()
    style = _cover_style_tokens(cover_style, title_lines=title_lines)
    layers: list[str] = []

    fontfile = settings.cover_title_font_path.replace("\\", "/").replace(":", "\\:")
    if title_lines.get("top"):
        layers.append(
            _drawtext(
                text=title_lines["top"],
                fontfile=fontfile,
                fontsize=style["top_size"],
                fontcolor=style["top_fill"],
                bordercolor=style["top_border"],
                borderw=style["top_borderw"],
                x="(w-text_w)/2",
                y=str(style["top_y"]),
            )
        )
    if title_lines.get("main"):
        layers.append(
            _drawtext(
                text=title_lines["main"],
                fontfile=fontfile,
                fontsize=style["main_size"],
                fontcolor=style["main_fill"],
                bordercolor=style["main_border"],
                borderw=style["main_borderw"],
                x="(w-text_w)/2",
                y="(h-text_h)/2-20",
            )
        )
    if title_lines.get("bottom"):
        layers.append(
            _drawtext(
                text=title_lines["bottom"],
                fontfile=fontfile,
                fontsize=style["bottom_size"],
                fontcolor=style["bottom_fill"],
                bordercolor=style["bottom_border"],
                borderw=style["bottom_borderw"],
                x="(w-text_w)/2",
                y="h-text_h-70",
            )
        )

    if not layers:
        return

    tmp = cover_path.with_suffix(".titled.jpg")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["ffmpeg", "-y", "-i", str(cover_path), "-vf", ",".join(layers), str(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        ),
    )
    if result.returncode == 0 and tmp.exists():
        tmp.replace(cover_path)


def _drawtext(
    *,
    text: str,
    fontfile: str,
    fontsize: int,
    fontcolor: str,
    bordercolor: str,
    borderw: int,
    x: str,
    y: str,
) -> str:
    safe_text = _escape_drawtext(text)
    return (
        f"drawtext=text='{safe_text}'"
        f":fontfile='{fontfile}'"
        f":fontsize={fontsize}"
        f":fontcolor={fontcolor}"
        f":borderw={borderw}"
        f":bordercolor={bordercolor}"
        f":shadowcolor=0x000000AA"
        f":shadowx=4:shadowy=4"
        f":x={x}:y={y}"
    )


def _cover_style_tokens(style_name: str, *, title_lines: dict[str, str]) -> dict[str, Any]:
    top_size = _fit_font_size(title_lines.get("top", ""), 104, min_size=82)
    main_size = _fit_font_size(title_lines.get("main", ""), 146, min_size=96)
    bottom_size = _fit_font_size(title_lines.get("bottom", ""), 104, min_size=82)

    if style_name == "collection_drop":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 108, min_size=84),
            "top_fill": "0x52F0FFFF",
            "top_border": "0x0C0527FF",
            "top_borderw": 12,
            "main_size": _fit_font_size(title_lines.get("main", ""), 150, min_size=98),
            "main_fill": "0xFFE9A3FF",
            "main_border": "0xB4201EFF",
            "main_borderw": 14,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 108, min_size=84),
            "bottom_fill": "0xFFF3C7FF",
            "bottom_border": "0xE12E1EFF",
            "bottom_borderw": 10,
            "top_y": 55,
        }
    if style_name == "upgrade_spotlight":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 108, min_size=84),
            "top_fill": "0x67ECFFFF",
            "top_border": "0x170C2FFF",
            "top_borderw": 12,
            "main_size": _fit_font_size(title_lines.get("main", ""), 146, min_size=96),
            "main_fill": "0xF8F8F8FF",
            "main_border": "0x1E1A14FF",
            "main_borderw": 14,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 110, min_size=86),
            "bottom_fill": "0xFFE582FF",
            "bottom_border": "0xFF5A20FF",
            "bottom_borderw": 10,
            "top_y": 55,
        }
    if style_name == "tactical_neon":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 102, min_size=82),
            "top_fill": "0x57DFFFFF",
            "top_border": "0x111111FF",
            "top_borderw": 12,
            "main_size": _fit_font_size(title_lines.get("main", ""), 144, min_size=94),
            "main_fill": "0xF4F4F4FF",
            "main_border": "0x1B1B1BFF",
            "main_borderw": 14,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 102, min_size=82),
            "bottom_fill": "0xFFC15AFF",
            "bottom_border": "0xB1430BFF",
            "bottom_borderw": 10,
            "top_y": 60,
        }
    return {
        "top_size": top_size,
        "top_fill": "0x5DE9FFFF",
        "top_border": "0x120A2DFF",
        "top_borderw": 12,
        "main_size": main_size,
        "main_fill": "0xF6F6F6FF",
        "main_border": "0x1A1A1AFF",
        "main_borderw": 14,
        "bottom_size": bottom_size,
        "bottom_fill": "0xFFDF76FF",
        "bottom_border": "0xD24B10FF",
        "bottom_borderw": 10,
        "top_y": 58,
    }


def _fit_font_size(text: str, base_size: int, *, min_size: int) -> int:
    length = len((text or "").strip())
    if length <= 4:
        return base_size
    if length <= 6:
        return max(min_size, base_size - 10)
    if length <= 8:
        return max(min_size, base_size - 18)
    if length <= 10:
        return max(min_size, base_size - 26)
    return max(min_size, base_size - 34)


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
    )


def write_srt_file(subtitle_items: list[dict], output_path: Path) -> Path:
    lines: list[str] = []
    for i, item in enumerate(subtitle_items, 1):
        start = _srt_time(item["start_time"])
        end = _srt_time(item["end_time"])
        text = item.get("text_final") or item.get("text_norm") or item.get("text_raw", "")
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return output_path


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

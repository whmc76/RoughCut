"""
Output package: one project folder per job, containing MP4 + SRT + cover assets.
Naming: {output_root}/{YYYYMMDD}_{original_stem}/{YYYYMMDD}_{original_stem}.{ext}

Cover generation:
- rank multiple candidate frames from the edited video
- export several cover variants for manual selection
- apply a three-line title layout inspired by existing channel thumbnails
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text

COVER_TITLE_STRATEGIES = [
    {
        "key": "xiaohongshu",
        "label": "小红书吸睛",
        "instruction": "二极管表达，情绪和反差更强，适合种草、惊喜、收藏欲、冲动点击。",
        "default_title_style": "double_banner",
    },
    {
        "key": "bilibili",
        "label": "B站信息流",
        "instruction": "信息更完整，像认真开箱/测评封面，强调主体、版本、升级点。",
        "default_title_style": "tutorial_blueprint",
    },
    {
        "key": "youtube",
        "label": "YouTube开箱",
        "instruction": "品牌 + 主体名更明确，标题更像国际化开箱频道的大字封面。",
        "default_title_style": "chrome_impact",
    },
    {
        "key": "ctr",
        "label": "强CTR爆点",
        "instruction": "优先点击率，强结论、强冲突、强升级感，适合短视频封面。",
        "default_title_style": "comic_boom",
    },
    {
        "key": "brand",
        "label": "品牌高级感",
        "instruction": "更克制、更像品牌视觉或精品海报，强调审美和质感。",
        "default_title_style": "luxury_gold",
    },
]


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


def get_output_project_dir(source_name: str, created_at: datetime | None = None) -> Path:
    project_name = build_output_name(source_name, created_at)
    project_dir = get_output_dir() / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_cover_manifest_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_cover_plans.json")


def get_legacy_cover_manifest_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_plans.json")


def build_cover_variant_output_path(output_path: Path, index: int, strategy_key: str | None = None) -> Path:
    safe_strategy = _sanitize((strategy_key or "generic").lower()).replace(" ", "_") or "generic"
    return output_path.with_name(f"{output_path.stem}_v{index + 1}_{safe_strategy}{output_path.suffix}")


async def extract_cover_frame(
    video_path: Path,
    output_path: Path,
    *,
    seek_sec: float = 3.0,
    content_profile: dict[str, Any] | None = None,
    cover_style: str | None = None,
    title_style: str | None = None,
) -> list[Path]:
    """
    Export one primary cover plus additional ranked variants.

    We rank candidate frames from the edited video so the chosen cover better
    matches the delivered cut, then overlay title plans for manual pick.
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration(video_path)
    variant_count = max(5, settings.cover_output_variants)

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

        fallback_title = _resolve_cover_title(content_profile)
        title_variants = await _generate_cover_title_variants(
            selected,
            content_profile=content_profile,
            fallback=fallback_title,
            variant_count=variant_count,
        )
        resolved_cover_style = (
            str(cover_style).strip()
            if cover_style and str(cover_style).strip() and str(cover_style) != "preset_default"
            else (content_profile or {}).get("preset", {}).get("cover_style", "tech_showcase")
        )
        resolved_title_style = str(title_style or "preset_default").strip() or "preset_default"

        outputs: list[Path] = []
        for i, candidate in enumerate(selected):
            plan = title_variants[i] if i < len(title_variants) else None
            strategy_key = plan.get("strategy_key") if isinstance(plan, dict) else None
            target = build_cover_variant_output_path(output_path, i, strategy_key)
            await _extract_frame(video_path, target, candidate["seek"])
            title_lines = plan.get("title") if isinstance(plan, dict) else fallback_title
            resolved_variant_title_style = resolved_title_style
            if resolved_variant_title_style == "preset_default" and isinstance(plan, dict):
                resolved_variant_title_style = str(plan.get("title_style") or "preset_default")
            if title_lines:
                try:
                    await _overlay_title_layout(target, title_lines, resolved_cover_style, resolved_variant_title_style)
                except Exception:
                    pass
            outputs.append(target)
        if outputs:
            shutil.copy2(outputs[0], output_path)
        _write_cover_variant_manifest(output_path, selected, title_variants, outputs)

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


async def _generate_cover_title_variants(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any] | None,
    fallback: dict[str, str] | None,
    variant_count: int,
) -> list[dict[str, Any] | None]:
    fallback_plan = fallback if _cover_title_is_usable(fallback) else None
    settings = get_settings()
    strategies = COVER_TITLE_STRATEGIES[: max(1, variant_count)]
    if settings.cover_title.strip():
        return [
            {
                "strategy_key": strategy["key"],
                "strategy_label": strategy["label"],
                "title_style": strategy["default_title_style"],
                "title": fallback_plan,
            }
            for strategy in strategies[: max(1, len(candidates))]
        ]

    preview_paths = [candidate["preview"] for candidate in candidates if candidate.get("preview")]
    if preview_paths:
        try:
            strategy_text = "\n".join(
                f"- {idx}. {strategy['label']}：{strategy['instruction']}"
                for idx, strategy in enumerate(strategies)
            )
            prompt = (
                "你在给中文开箱/EDC 视频制作封面候选。现在有多张候选画面，请输出 5 套具有明确传播策略差异的封面标题方案。"
                "每套方案不是简单换词，而是针对不同平台/传播目标单独设计。"
                "要求：\n"
                "1. 每套方案绑定一个 strategy_key 和一个 match_index。\n"
                "2. 请优先让不同策略匹配不同镜头；只有实在不合适才允许复用同一镜头。\n"
                "3. top 优先品牌或系列，长度 2-12 字。\n"
                "4. main 必须是主体名或产品类型，不要写“产品开箱与上手体验”“升级对比版”这类泛词。\n"
                "5. bottom 是钩子句，长度 6-12 字。\n"
                "6. 如果画面里出现英文品牌，请直接保留品牌英文。\n"
                "7. 五套方案必须体现不同风格倾向，不允许只是排列组合。\n"
                f"策略定义：\n{strategy_text}"
                f"\n已有上下文：{json.dumps(content_profile or {}, ensure_ascii=False)}"
                "\n输出 JSON："
                "{\"plans\":[{\"strategy_key\":\"xiaohongshu\",\"match_index\":0,\"top\":\"\",\"main\":\"\",\"bottom\":\"\",\"reason\":\"\"}]}"
            )
            content = await complete_with_images(prompt, preview_paths[:variant_count], max_tokens=700, json_mode=True)
            data = json.loads(extract_json_text(content))
            indexed_plans: dict[int, dict[str, Any]] = {}
            used_strategies: set[str] = set()
            for raw in data.get("plans", []):
                try:
                    idx = int(raw.get("match_index", -1))
                except Exception:
                    continue
                strategy_key = str(raw.get("strategy_key") or "").strip().lower()
                strategy = next((item for item in strategies if item["key"] == strategy_key), None)
                if idx < 0 or idx >= len(candidates) or not strategy or strategy_key in used_strategies:
                    continue
                refined = {
                    "top": str(raw.get("top") or "").strip(),
                    "main": str(raw.get("main") or "").strip(),
                    "bottom": str(raw.get("bottom") or "").strip(),
                }
                refined = _sanitize_generated_cover_title(
                    refined,
                    fallback_plan=fallback_plan,
                    content_profile=content_profile,
                )
                if _cover_title_is_usable(refined):
                    indexed_plans[idx] = {
                        "strategy_key": strategy["key"],
                        "strategy_label": strategy["label"],
                        "reason": str(raw.get("reason") or "").strip(),
                        "title_style": strategy["default_title_style"],
                        "title": refined,
                    }
                    used_strategies.add(strategy_key)
            if indexed_plans:
                plans_by_candidate: list[dict[str, Any] | None] = []
                for idx in range(max(1, len(candidates))):
                    if idx in indexed_plans:
                        plans_by_candidate.append(indexed_plans[idx])
                        continue
                    strategy = strategies[min(idx, len(strategies) - 1)]
                    plans_by_candidate.append(
                        {
                            "strategy_key": strategy["key"],
                            "strategy_label": strategy["label"],
                            "reason": "",
                            "title_style": strategy["default_title_style"],
                            "title": fallback_plan,
                        }
                    )
                return plans_by_candidate
        except Exception:
            pass
    return [
        {
            "strategy_key": strategy["key"],
            "strategy_label": strategy["label"],
            "reason": "",
            "title_style": strategy["default_title_style"],
            "title": fallback_plan,
        }
        for strategy in strategies[: max(1, len(candidates))]
    ]


def _write_cover_variant_manifest(
    output_path: Path,
    selected: list[dict[str, Any]],
    title_variants: list[dict[str, Any] | None],
    outputs: list[Path],
) -> None:
    manifest_path = get_cover_manifest_path(output_path)
    legacy_manifest_path = get_legacy_cover_manifest_path(output_path)
    payload: list[dict[str, Any]] = []
    for idx, target in enumerate(outputs):
        plan = title_variants[idx] if idx < len(title_variants) and isinstance(title_variants[idx], dict) else {}
        payload.append(
            {
                "index": idx + 1,
                "path": str(target),
                "seek_sec": round(float(selected[idx].get("seek", 0.0)), 2) if idx < len(selected) else 0.0,
                "strategy_key": plan.get("strategy_key") or "",
                "strategy_label": plan.get("strategy_label") or "",
                "reason": plan.get("reason") or "",
                "title_style": plan.get("title_style") or "",
                "title": plan.get("title") or None,
            }
        )
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if legacy_manifest_path != manifest_path:
        legacy_manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _sanitize_generated_cover_title(
    title_lines: dict[str, str] | None,
    *,
    fallback_plan: dict[str, str] | None,
    content_profile: dict[str, Any] | None,
) -> dict[str, str] | None:
    if not title_lines:
        return fallback_plan

    normalized = {
        "top": str(title_lines.get("top") or "").strip()[:14],
        "main": str(title_lines.get("main") or "").strip()[:18],
        "bottom": str(title_lines.get("bottom") or "").strip()[:18],
    }
    if not _cover_title_is_usable(normalized):
        return fallback_plan

    allowed_tokens = _collect_cover_guard_tokens(content_profile, fallback_plan)
    if allowed_tokens:
        introduced = _extract_cover_guard_tokens(" ".join(normalized.values())) - allowed_tokens
        if introduced:
            return fallback_plan

    if fallback_plan:
        normalized["top"] = normalized["top"] or str(fallback_plan.get("top") or "").strip()[:14]
        normalized["main"] = normalized["main"] or str(fallback_plan.get("main") or "").strip()[:18]
        normalized["bottom"] = normalized["bottom"] or str(fallback_plan.get("bottom") or "").strip()[:18]

    return normalized


def _collect_cover_guard_tokens(
    content_profile: dict[str, Any] | None,
    fallback_plan: dict[str, str] | None,
) -> set[str]:
    tokens: set[str] = set()
    for key in ("subject_brand", "subject_model", "visible_text"):
        tokens.update(_extract_cover_guard_tokens(str((content_profile or {}).get(key) or "")))
    for value in (fallback_plan or {}).values():
        tokens.update(_extract_cover_guard_tokens(str(value or "")))
    return tokens


def _extract_cover_guard_tokens(text: str) -> set[str]:
    return {
        token.strip().upper()
        for token in re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+-]{1,23})(?![A-Za-z0-9])", str(text or ""))
        if len(token.strip()) >= 2
    }


async def _overlay_title_layout(
    cover_path: Path,
    title_lines: dict[str, str],
    cover_style: str,
    title_style: str,
) -> None:
    settings = get_settings()
    style = _title_style_tokens(title_style, title_lines=title_lines, cover_style=cover_style)
    layers: list[str] = []

    fontfile = settings.cover_title_font_path.replace("\\", "/").replace(":", "\\:")
    for line_key in ("top", "main", "bottom"):
        if not title_lines.get(line_key):
            continue
        line_style = style.get(line_key) or {}
        layers.append(
            _drawtext(
                text=title_lines[line_key],
                fontfile=fontfile,
                fontsize=int(line_style["size"]),
                fontcolor=str(line_style["fill"]),
                bordercolor=str(line_style["border"]),
                borderw=int(line_style["borderw"]),
                x=str(line_style["x"]),
                y=str(line_style["y"]),
                shadowcolor=str(line_style.get("shadowcolor") or "0x000000AA"),
                shadowx=int(line_style.get("shadowx", 4)),
                shadowy=int(line_style.get("shadowy", 4)),
                box=bool(line_style.get("box")),
                boxcolor=str(line_style.get("boxcolor") or "0x00000000"),
                boxborderw=int(line_style.get("boxborderw", 16)),
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
    shadowcolor: str = "0x000000AA",
    shadowx: int = 4,
    shadowy: int = 4,
    box: bool = False,
    boxcolor: str = "0x00000000",
    boxborderw: int = 16,
) -> str:
    safe_text = _escape_drawtext(text)
    parts = [
        f"drawtext=text='{safe_text}'"
        f":fontfile='{fontfile}'",
        f":fontsize={fontsize}",
        f":fontcolor={fontcolor}",
        f":borderw={borderw}",
        f":bordercolor={bordercolor}",
        f":shadowcolor={shadowcolor}",
        f":shadowx={shadowx}:shadowy={shadowy}",
        f":x={x}:y={y}",
    ]
    if box:
        parts.extend(
            [
                ":box=1",
                f":boxcolor={boxcolor}",
                f":boxborderw={boxborderw}",
            ]
        )
    return "".join(parts)


def _title_style_tokens(
    style_name: str,
    *,
    title_lines: dict[str, str],
    cover_style: str,
) -> dict[str, dict[str, Any]]:
    if style_name == "preset_default":
        legacy = _cover_style_tokens(cover_style, title_lines=title_lines)
        return {
            "top": {
                "size": legacy["top_size"],
                "fill": legacy["top_fill"],
                "border": legacy["top_border"],
                "borderw": legacy["top_borderw"],
                "x": "(w-text_w)/2",
                "y": str(legacy["top_y"]),
            },
            "main": {
                "size": legacy["main_size"],
                "fill": legacy["main_fill"],
                "border": legacy["main_border"],
                "borderw": legacy["main_borderw"],
                "x": "(w-text_w)/2",
                "y": "(h-text_h)/2-20",
            },
            "bottom": {
                "size": legacy["bottom_size"],
                "fill": legacy["bottom_fill"],
                "border": legacy["bottom_border"],
                "borderw": legacy["bottom_borderw"],
                "x": "(w-text_w)/2",
                "y": "h-text_h-70",
            },
        }

    top_small = _fit_font_size(title_lines.get("top", ""), 102, min_size=72)
    main_huge = _fit_font_size(title_lines.get("main", ""), 170, min_size=106)
    main_large = _fit_font_size(title_lines.get("main", ""), 154, min_size=98)
    bottom_mid = _fit_font_size(title_lines.get("bottom", ""), 110, min_size=78)

    if style_name == "cyber_logo_stack":
        return {
            "top": {"size": top_small, "fill": "0x68F3FFFF", "border": "0x15131EFF", "borderw": 12, "x": "80", "y": "52", "shadowcolor": "0x1C5DFFFF", "shadowx": 6, "shadowy": 6},
            "main": {"size": main_huge, "fill": "0xF3F5FFFF", "border": "0x2539C4FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-28", "shadowcolor": "0x071018FF", "shadowx": 8, "shadowy": 8},
            "bottom": {"size": bottom_mid, "fill": "0xFFE28AFF", "border": "0xE05A2AFF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-74", "shadowcolor": "0x00000099", "shadowx": 5, "shadowy": 5},
        }
    if style_name == "chrome_impact":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 94, min_size=68), "fill": "0xF2F9FFFF", "border": "0x111111FF", "borderw": 10, "x": "70", "y": "54", "shadowcolor": "0x3852E5FF", "shadowx": 5, "shadowy": 5},
            "main": {"size": main_huge, "fill": "0xF9F9F9FF", "border": "0x2A2017FF", "borderw": 20, "x": "(w-text_w)/2", "y": "(h-text_h)/2-10", "shadowcolor": "0x4B69FFFF", "shadowx": 6, "shadowy": 6},
            "bottom": {"size": bottom_mid, "fill": "0xFFF3B6FF", "border": "0xFF6A2BFF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82", "shadowcolor": "0x00000088", "shadowx": 4, "shadowy": 4},
        }
    if style_name == "festival_badge":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 88, min_size=66), "fill": "0xFFEAB8FF", "border": "0x8A1A1AFF", "borderw": 8, "x": "(w-text_w)/2", "y": "56", "box": True, "boxcolor": "0x7E1515CC", "boxborderw": 20},
            "main": {"size": main_large, "fill": "0xFFF5D7FF", "border": "0xB31616FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-10", "shadowcolor": "0x00000077", "shadowx": 5, "shadowy": 5},
            "bottom": {"size": bottom_mid, "fill": "0xFFE59BFF", "border": "0xC94717FF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82", "box": True, "boxcolor": "0x8E2020B8", "boxborderw": 14},
        }
    if style_name == "double_banner":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 84, min_size=64), "fill": "0xFFFDF7FF", "border": "0x111111FF", "borderw": 6, "x": "70", "y": "62", "box": True, "boxcolor": "0x1E8FE2CC", "boxborderw": 18},
            "main": {"size": main_large, "fill": "0xFFFFFFFF", "border": "0x131313FF", "borderw": 16, "x": "(w-text_w)/2", "y": "(h-text_h)/2-20"},
            "bottom": {"size": bottom_mid, "fill": "0xFFF7DDFF", "border": "0xA92918FF", "borderw": 8, "x": "(w-text_w)/2", "y": "h-text_h-84", "box": True, "boxcolor": "0xE4552CDD", "boxborderw": 18},
        }
    if style_name == "comic_boom":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 96, min_size=68), "fill": "0xFFFACBFF", "border": "0x0F0F0FFF", "borderw": 9, "x": "78", "y": "48"},
            "main": {"size": main_huge, "fill": "0xFFF45AFF", "border": "0x0E0E0EFF", "borderw": 22, "x": "(w-text_w)/2", "y": "(h-text_h)/2-18", "shadowcolor": "0xFF4D5CFF", "shadowx": 6, "shadowy": 6},
            "bottom": {"size": bottom_mid, "fill": "0x7CF7FFFF", "border": "0x111111FF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82"},
        }
    if style_name == "luxury_gold":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 84, min_size=64), "fill": "0xFFF2D8FF", "border": "0x3F2A11FF", "borderw": 6, "x": "(w-text_w)/2", "y": "64"},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 150, min_size=96), "fill": "0xFFF7EAFF", "border": "0x7B5417FF", "borderw": 16, "x": "(w-text_w)/2", "y": "(h-text_h)/2-16", "shadowcolor": "0x30200AFF", "shadowx": 4, "shadowy": 4},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 100, min_size=74), "fill": "0xFFE2A2FF", "border": "0x6B4212FF", "borderw": 8, "x": "(w-text_w)/2", "y": "h-text_h-80"},
        }
    if style_name == "tutorial_blueprint":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 82, min_size=62), "fill": "0xDDF4FFFF", "border": "0x15486AFF", "borderw": 6, "x": "72", "y": "58", "box": True, "boxcolor": "0x103E5ECC", "boxborderw": 14},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 142, min_size=92), "fill": "0xFFFFFFFF", "border": "0x143952FF", "borderw": 14, "x": "72", "y": "(h-text_h)/2-16"},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 88, min_size=68), "fill": "0xE6F8FFFF", "border": "0x236A91FF", "borderw": 6, "x": "72", "y": "h-text_h-88"},
        }
    if style_name == "magazine_clean":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 76, min_size=58), "fill": "0xFFFFFFFF", "border": "0x2B2B2BFF", "borderw": 4, "x": "(w-text_w)/2", "y": "66", "shadowcolor": "0x00000055", "shadowx": 2, "shadowy": 2},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 136, min_size=90), "fill": "0xFFFFFFFF", "border": "0x2B2B2BFF", "borderw": 8, "x": "(w-text_w)/2", "y": "(h-text_h)/2-12", "shadowcolor": "0x00000066", "shadowx": 3, "shadowy": 3},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 86, min_size=66), "fill": "0xFFF6F0FF", "border": "0x504842FF", "borderw": 4, "x": "(w-text_w)/2", "y": "h-text_h-82", "shadowcolor": "0x00000055", "shadowx": 2, "shadowy": 2},
        }
    if style_name == "documentary_stamp":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 72, min_size=56), "fill": "0xF6F1E7FF", "border": "0x3A362DFF", "borderw": 4, "x": "60", "y": "60", "box": True, "boxcolor": "0x20231FB8", "boxborderw": 10},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 124, min_size=84), "fill": "0xF5F2EAFF", "border": "0x23211CFF", "borderw": 10, "x": "60", "y": "h*0.58-text_h", "shadowcolor": "0x00000066", "shadowx": 3, "shadowy": 3},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 76, min_size=58), "fill": "0xE6E1D6FF", "border": "0x4B463EFF", "borderw": 4, "x": "60", "y": "h-text_h-74"},
        }
    if style_name == "neon_night":
        return {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 90, min_size=66), "fill": "0xFFE8F8FF", "border": "0x9324B8FF", "borderw": 9, "x": "78", "y": "50", "shadowcolor": "0x16C7FFFF", "shadowx": 6, "shadowy": 6},
            "main": {"size": main_large, "fill": "0xFFF7FCFF", "border": "0xFF4EA2FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-16", "shadowcolor": "0x283CFFFF", "shadowx": 8, "shadowy": 8},
            "bottom": {"size": bottom_mid, "fill": "0xFFF1A0FF", "border": "0xFF6A35FF", "borderw": 9, "x": "(w-text_w)/2", "y": "h-text_h-82"},
        }
    return _title_style_tokens("preset_default", title_lines=title_lines, cover_style=cover_style)


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
    if style_name == "luxury_blackgold":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 102, min_size=80),
            "top_fill": "0xFFE2A8FF",
            "top_border": "0x0D0B09FF",
            "top_borderw": 10,
            "main_size": _fit_font_size(title_lines.get("main", ""), 144, min_size=96),
            "main_fill": "0xFFF7EAFF",
            "main_border": "0x2A1604FF",
            "main_borderw": 16,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 100, min_size=80),
            "bottom_fill": "0xFFD36CFF",
            "bottom_border": "0x7A4D0FFF",
            "bottom_borderw": 9,
            "top_y": 54,
        }
    if style_name == "retro_poster":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 104, min_size=80),
            "top_fill": "0xFEE6B3FF",
            "top_border": "0x40250DFF",
            "top_borderw": 9,
            "main_size": _fit_font_size(title_lines.get("main", ""), 150, min_size=100),
            "main_fill": "0xFFF4ECFF",
            "main_border": "0xA9442BFF",
            "main_borderw": 15,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 104, min_size=82),
            "bottom_fill": "0xFFF0C7FF",
            "bottom_border": "0x57422FFF",
            "bottom_borderw": 9,
            "top_y": 52,
        }
    if style_name == "creator_vlog":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 98, min_size=78),
            "top_fill": "0xFFFFFFFF",
            "top_border": "0x604B8FFF",
            "top_borderw": 8,
            "main_size": _fit_font_size(title_lines.get("main", ""), 140, min_size=92),
            "main_fill": "0xFFF7FCFF",
            "main_border": "0x55317DFF",
            "main_borderw": 12,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 96, min_size=78),
            "bottom_fill": "0xFFE7F4FF",
            "bottom_border": "0x8861B2FF",
            "bottom_borderw": 8,
            "top_y": 58,
        }
    if style_name == "bold_review":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 104, min_size=82),
            "top_fill": "0xFFFFFFFF",
            "top_border": "0x191919FF",
            "top_borderw": 10,
            "main_size": _fit_font_size(title_lines.get("main", ""), 152, min_size=100),
            "main_fill": "0xFFF8F3FF",
            "main_border": "0x111111FF",
            "main_borderw": 16,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 102, min_size=82),
            "bottom_fill": "0xFFD05CFF",
            "bottom_border": "0xC93A17FF",
            "bottom_borderw": 10,
            "top_y": 56,
        }
    if style_name == "tutorial_card":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 96, min_size=76),
            "top_fill": "0xDFF4FFFF",
            "top_border": "0x173244FF",
            "top_borderw": 8,
            "main_size": _fit_font_size(title_lines.get("main", ""), 138, min_size=92),
            "main_fill": "0xFFFFFFFF",
            "main_border": "0x13232DFF",
            "main_borderw": 12,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 94, min_size=76),
            "bottom_fill": "0xD8F0FFFF",
            "bottom_border": "0x1E6178FF",
            "bottom_borderw": 8,
            "top_y": 50,
        }
    if style_name == "food_magazine":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 98, min_size=76),
            "top_fill": "0xFFF2DBFF",
            "top_border": "0x603923FF",
            "top_borderw": 8,
            "main_size": _fit_font_size(title_lines.get("main", ""), 142, min_size=94),
            "main_fill": "0xFFFDF8FF",
            "main_border": "0xA14A22FF",
            "main_borderw": 13,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 96, min_size=76),
            "bottom_fill": "0xFFF3D2FF",
            "bottom_border": "0x6D4A25FF",
            "bottom_borderw": 8,
            "top_y": 54,
        }
    if style_name == "street_hype":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 106, min_size=82),
            "top_fill": "0xFFF8F4FF",
            "top_border": "0x161616FF",
            "top_borderw": 11,
            "main_size": _fit_font_size(title_lines.get("main", ""), 154, min_size=100),
            "main_fill": "0xFFF7EDFF",
            "main_border": "0xFF4C2FFF",
            "main_borderw": 16,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 104, min_size=82),
            "bottom_fill": "0xFFF18EFF",
            "bottom_border": "0x111111FF",
            "bottom_borderw": 9,
            "top_y": 58,
        }
    if style_name == "minimal_white":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 92, min_size=74),
            "top_fill": "0xF5F7FAFF",
            "top_border": "0x2A3138FF",
            "top_borderw": 5,
            "main_size": _fit_font_size(title_lines.get("main", ""), 132, min_size=90),
            "main_fill": "0xFFFFFFFF",
            "main_border": "0x27303AFF",
            "main_borderw": 8,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 88, min_size=72),
            "bottom_fill": "0xE9EEF2FF",
            "bottom_border": "0x46525EFF",
            "bottom_borderw": 5,
            "top_y": 50,
        }
    if style_name == "cyber_grid":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 102, min_size=80),
            "top_fill": "0x9CF8FFFF",
            "top_border": "0x0D1E25FF",
            "top_borderw": 9,
            "main_size": _fit_font_size(title_lines.get("main", ""), 146, min_size=96),
            "main_fill": "0xF4FFFFFF",
            "main_border": "0x2A46A6FF",
            "main_borderw": 14,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 98, min_size=80),
            "bottom_fill": "0x9BFFCAFF",
            "bottom_border": "0x103D2EFF",
            "bottom_borderw": 8,
            "top_y": 50,
        }
    if style_name == "premium_silver":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 98, min_size=76),
            "top_fill": "0xE7EDF5FF",
            "top_border": "0x414A56FF",
            "top_borderw": 8,
            "main_size": _fit_font_size(title_lines.get("main", ""), 142, min_size=94),
            "main_fill": "0xF7FAFFFF",
            "main_border": "0x545F70FF",
            "main_borderw": 12,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 94, min_size=76),
            "bottom_fill": "0xE7EEF5FF",
            "bottom_border": "0x677385FF",
            "bottom_borderw": 7,
            "top_y": 54,
        }
    if style_name == "comic_pop":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 110, min_size=84),
            "top_fill": "0xFFFBD6FF",
            "top_border": "0x191919FF",
            "top_borderw": 10,
            "main_size": _fit_font_size(title_lines.get("main", ""), 156, min_size=100),
            "main_fill": "0xFFF96BFF",
            "main_border": "0x101010FF",
            "main_borderw": 18,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 106, min_size=84),
            "bottom_fill": "0x7EFBFFFF",
            "bottom_border": "0x101010FF",
            "bottom_borderw": 10,
            "top_y": 58,
        }
    if style_name == "studio_red":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 102, min_size=80),
            "top_fill": "0xFFF0ECFF",
            "top_border": "0x5B1414FF",
            "top_borderw": 9,
            "main_size": _fit_font_size(title_lines.get("main", ""), 148, min_size=96),
            "main_fill": "0xFFF7F5FF",
            "main_border": "0xB01E1EFF",
            "main_borderw": 15,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 100, min_size=80),
            "bottom_fill": "0xFFD39FFF",
            "bottom_border": "0x6C1717FF",
            "bottom_borderw": 8,
            "top_y": 56,
        }
    if style_name == "documentary_frame":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 90, min_size=72),
            "top_fill": "0xF0F1EDFF",
            "top_border": "0x3D423CFF",
            "top_borderw": 5,
            "main_size": _fit_font_size(title_lines.get("main", ""), 128, min_size=88),
            "main_fill": "0xF8F8F4FF",
            "main_border": "0x232723FF",
            "main_borderw": 9,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 86, min_size=70),
            "bottom_fill": "0xD8DDD5FF",
            "bottom_border": "0x414941FF",
            "bottom_borderw": 5,
            "top_y": 48,
        }
    if style_name == "pastel_lifestyle":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 96, min_size=74),
            "top_fill": "0xFFF8FCFF",
            "top_border": "0x8F6D9EFF",
            "top_borderw": 6,
            "main_size": _fit_font_size(title_lines.get("main", ""), 136, min_size=90),
            "main_fill": "0xFFFDFEFF",
            "main_border": "0xA88AC0FF",
            "main_borderw": 10,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 92, min_size=74),
            "bottom_fill": "0xFFF1F8FF",
            "bottom_border": "0xC49AB4FF",
            "bottom_borderw": 6,
            "top_y": 56,
        }
    if style_name == "industrial_orange":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 102, min_size=80),
            "top_fill": "0xFFF3D8FF",
            "top_border": "0x3D250FFF",
            "top_borderw": 8,
            "main_size": _fit_font_size(title_lines.get("main", ""), 146, min_size=96),
            "main_fill": "0xFFF9F3FF",
            "main_border": "0xEF7A11FF",
            "main_borderw": 14,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 98, min_size=80),
            "bottom_fill": "0xFFD792FF",
            "bottom_border": "0x734112FF",
            "bottom_borderw": 8,
            "top_y": 54,
        }
    if style_name == "ecommerce_sale":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 108, min_size=84),
            "top_fill": "0xFFF6D6FF",
            "top_border": "0xFF4D2AFF",
            "top_borderw": 12,
            "main_size": _fit_font_size(title_lines.get("main", ""), 156, min_size=102),
            "main_fill": "0xFFFDF4FF",
            "main_border": "0xD22A17FF",
            "main_borderw": 18,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 108, min_size=84),
            "bottom_fill": "0xFFF18EFF",
            "bottom_border": "0x111111FF",
            "bottom_borderw": 10,
            "top_y": 54,
        }
    if style_name == "price_strike":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 104, min_size=82),
            "top_fill": "0xE4FFF2FF",
            "top_border": "0x178A4BFF",
            "top_borderw": 10,
            "main_size": _fit_font_size(title_lines.get("main", ""), 150, min_size=98),
            "main_fill": "0xF7FFF9FF",
            "main_border": "0x1B713EFF",
            "main_borderw": 15,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 104, min_size=82),
            "bottom_fill": "0xC4FFD4FF",
            "bottom_border": "0x165231FF",
            "bottom_borderw": 8,
            "top_y": 56,
        }
    if style_name == "trailer_dark":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 92, min_size=74),
            "top_fill": "0xD5DEE8FF",
            "top_border": "0x15191FFF",
            "top_borderw": 6,
            "main_size": _fit_font_size(title_lines.get("main", ""), 138, min_size=92),
            "main_fill": "0xF5F8FCFF",
            "main_border": "0x0F1217FF",
            "main_borderw": 12,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 90, min_size=74),
            "bottom_fill": "0xAFC1D5FF",
            "bottom_border": "0x1C2430FF",
            "bottom_borderw": 6,
            "top_y": 48,
        }
    if style_name == "festival_redgold":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 104, min_size=80),
            "top_fill": "0xFFE1A2FF",
            "top_border": "0x7B1212FF",
            "top_borderw": 10,
            "main_size": _fit_font_size(title_lines.get("main", ""), 148, min_size=96),
            "main_fill": "0xFFF6E8FF",
            "main_border": "0xA31919FF",
            "main_borderw": 15,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 100, min_size=80),
            "bottom_fill": "0xFFE8B8FF",
            "bottom_border": "0x7A1C12FF",
            "bottom_borderw": 8,
            "top_y": 54,
        }
    if style_name == "clean_lab":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 94, min_size=74),
            "top_fill": "0xF1F8FFFF",
            "top_border": "0x49667DFF",
            "top_borderw": 5,
            "main_size": _fit_font_size(title_lines.get("main", ""), 134, min_size=90),
            "main_fill": "0xFFFFFFFF",
            "main_border": "0x335163FF",
            "main_borderw": 9,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 90, min_size=74),
            "bottom_fill": "0xE8F7FFFF",
            "bottom_border": "0x62889EFF",
            "bottom_borderw": 5,
            "top_y": 50,
        }
    if style_name == "cinema_teaser":
        return {
            "top_size": _fit_font_size(title_lines.get("top", ""), 94, min_size=74),
            "top_fill": "0xEEF1F6FF",
            "top_border": "0x31353EFF",
            "top_borderw": 6,
            "main_size": _fit_font_size(title_lines.get("main", ""), 136, min_size=90),
            "main_fill": "0xFCFCFCFF",
            "main_border": "0x202226FF",
            "main_borderw": 11,
            "bottom_size": _fit_font_size(title_lines.get("bottom", ""), 90, min_size=74),
            "bottom_fill": "0xD7DCE5FF",
            "bottom_border": "0x393F49FF",
            "bottom_borderw": 6,
            "top_y": 46,
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

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
import logging
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
from roughcut.review.content_profile import _mapped_brand_for_model, _normalize_profile_value, _seed_profile_from_text

logger = logging.getLogger(__name__)

COVER_TITLE_STRATEGIES = [
    {
        "key": "ctr",
        "label": "强CTR爆点",
        "instruction": "优先点击率，强结论、强冲突、强升级感，适合短视频封面。",
        "default_title_style": "comic_boom",
    },
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
        "key": "brand",
        "label": "品牌高级感",
        "instruction": "更克制、更像品牌视觉或精品海报，强调审美和质感。",
        "default_title_style": "luxury_gold",
    },
]

_COVER_SAFE_HORIZONTAL_MARGIN_RATIO = 30 / 128
_COVER_SAFE_VERTICAL_TOP_RATIO = 0.12
_COVER_SAFE_VERTICAL_BOTTOM_RATIO = 0.14
_COVER_SAFE_MIN_INNER_PADDING = 18
_COVER_SAFE_TEXT_WIDTH_RATIO = 31 / 64


def _is_cover_multimodal_fast_fallback_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    if not message:
        return False
    return any(
        token in message
        for token in (
            "429",
            "too many requests",
            "rate limit",
            "timed out",
            "timeout",
            "cooling down",
            "cooldown",
            "connection refused",
            "connecterror",
            "all connection attempts failed",
        )
    )


def _sanitize(name: str) -> str:
    """Remove chars not safe for filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _normalize_output_component(value: str, *, max_length: int = 48) -> str:
    cleaned = _sanitize(str(value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._- ")
    if not cleaned:
        return ""
    return cleaned[:max_length].rstrip("._- ")


def _normalize_compare_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


def _looks_generated_stem(stem: str) -> bool:
    normalized = _normalize_compare_key(stem)
    if not normalized:
        return True
    if normalized.isdigit():
        return True
    if re.fullmatch(r"(img|dji|vid|video|clip|mv|pxl)?\d{5,}", normalized):
        return True
    parts = [part for part in re.split(r"[_\-\s]+", str(stem or "").lower()) if part]
    return bool(parts) and all(part.isdigit() for part in parts)


def _build_output_subject_prefixes(*, brand: str, model: str) -> list[str]:
    parts = [str(part or "").strip() for part in (brand, model) if str(part or "").strip()]
    prefixes: list[str] = []
    for candidate in (
        "".join(parts),
        " ".join(parts),
        "_".join(parts),
        "-".join(parts),
        *(reversed(parts)),
        *parts,
    ):
        value = str(candidate or "").strip()
        if value and value not in prefixes:
            prefixes.append(value)
    return sorted(prefixes, key=len, reverse=True)


def _strip_output_subject_prefix(text: str, *, brand: str, model: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for prefix in _build_output_subject_prefixes(brand=brand, model=model):
        while prefix and cleaned.startswith(prefix):
            remainder = cleaned[len(prefix):].strip(" _-")
            if not remainder:
                return ""
            cleaned = remainder
    return cleaned


def _resolve_output_title_hint(
    source_name: str,
    *,
    content_profile: dict[str, Any] | None = None,
    title_hint: str | None = None,
) -> str:
    stem = Path(source_name).stem
    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject_type = str((content_profile or {}).get("subject_type") or "").strip()
    video_theme = _strip_output_subject_prefix(
        str((content_profile or {}).get("video_theme") or "").strip(),
        brand=brand,
        model=model,
    )
    summary = str((content_profile or {}).get("summary") or (content_profile or {}).get("hook_line") or "").strip()
    cover_title = (content_profile or {}).get("cover_title") if isinstance(content_profile, dict) else None
    cover_title_text = ""
    if isinstance(cover_title, dict):
        cover_title_text = " ".join(
            str(cover_title.get(key) or "").strip()
            for key in ("top", "main", "bottom")
            if str(cover_title.get(key) or "").strip()
        ).strip()
        cover_title_text = _strip_output_subject_prefix(
            cover_title_text,
            brand=brand,
            model=model,
        )

    subject = " ".join(part for part in (brand, model) if part).strip()
    themed_subject = " ".join(part for part in (subject, video_theme) if part).strip()
    subject_fallback = " ".join(part for part in (subject_type, video_theme) if part).strip()
    title_hint = _strip_output_subject_prefix(str(title_hint or "").strip(), brand=brand, model=model)
    source_key = _normalize_compare_key(stem)
    generic_keys = {
        "shipin",
        "chengpian",
        "cujian",
        "zidongjianji",
        "luping",
        "thiscontent",
        "zhetiaoneirong",
    }
    for candidate in (title_hint, themed_subject, subject, subject_fallback, cover_title_text, summary, stem):
        if _candidate_conflicts_with_subject(candidate, brand=brand, model=model):
            continue
        normalized = _normalize_output_component(candidate, max_length=56)
        compare_key = _normalize_compare_key(normalized)
        if not normalized or not compare_key:
            continue
        if compare_key == source_key and _looks_generated_stem(stem):
            continue
        if compare_key.isdigit() or compare_key in generic_keys:
            continue
        return normalized
    return _normalize_output_component(stem, max_length=56) or "output"


def _candidate_conflicts_with_subject(text: str, *, brand: str, model: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or not (brand or model):
        return False
    seeded = _seed_profile_from_text(candidate)
    candidate_brand = str(seeded.get("subject_brand") or "").strip()
    candidate_model = str(seeded.get("subject_model") or "").strip()
    if candidate_brand and brand and _normalize_profile_value(candidate_brand) != _normalize_profile_value(brand):
        return True
    if candidate_model and model and _normalize_profile_value(candidate_model) != _normalize_profile_value(model):
        return True
    mapped_brand = _mapped_brand_for_model(candidate_model or model)
    effective_brand = candidate_brand or brand
    if mapped_brand and effective_brand and _normalize_profile_value(effective_brand) != _normalize_profile_value(mapped_brand):
        return True
    return False


def build_output_name(source_name: str, created_at: datetime | None = None) -> str:
    settings = get_settings()
    dt = created_at or datetime.now()
    stem = Path(source_name).stem
    pattern = settings.output_name_pattern
    name = pattern.format(date=dt.strftime("%Y%m%d"), stem=stem)
    return _sanitize(name)


def get_output_dir() -> Path:
    settings = get_settings()
    configured = str(settings.output_dir or "").strip()
    p = Path(configured or "output")
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_output_project_name(
    source_name: str,
    created_at: datetime | None = None,
    *,
    content_profile: dict[str, Any] | None = None,
    title_hint: str | None = None,
) -> str:
    dt = created_at or datetime.now()
    stem = _normalize_output_component(Path(source_name).stem, max_length=40) or "output"
    title = _resolve_output_title_hint(
        source_name,
        content_profile=content_profile,
        title_hint=title_hint,
    )
    title_key = _normalize_compare_key(title)
    stem_key = _normalize_compare_key(stem)
    label = title or stem
    if stem and stem_key != title_key and _looks_generated_stem(stem):
        label = f"{title}_{stem}" if title else stem
    return _sanitize(f"{dt.strftime('%Y%m%d')}_{label}")


def get_output_project_dir(
    source_name: str,
    created_at: datetime | None = None,
    *,
    content_profile: dict[str, Any] | None = None,
    title_hint: str | None = None,
) -> Path:
    project_name = build_output_project_name(
        source_name,
        created_at,
        content_profile=content_profile,
        title_hint=title_hint,
    )
    project_dir = get_output_dir() / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def resolve_output_orientation_label(width: int | None, height: int | None) -> str:
    safe_width = int(width or 0)
    safe_height = int(height or 0)
    if safe_width <= 0 or safe_height <= 0:
        return "未知方向"
    if safe_height > safe_width:
        return "竖版"
    if safe_width > safe_height:
        return "横版"
    return "方版"


def build_variant_output_path(
    project_dir: Path,
    project_name: str,
    *,
    variant_label: str,
    extension: str,
    width: int | None,
    height: int | None,
) -> Path:
    orientation_label = resolve_output_orientation_label(width, height)
    suffix = extension if str(extension).startswith(".") else f".{extension}"
    filename = _sanitize(f"{project_name}_{orientation_label}_{variant_label}{suffix}")
    return project_dir / filename


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
                anchor_seek=seek_sec,
                candidate_count=max(settings.cover_candidate_count, variant_count),
                tmpdir=tmp,
            )
        else:
            candidates = []

        if not candidates:
            candidates = [{"seek": seek_sec, "preview": None}]

        ranked_candidates = await _rank_cover_candidates(
            candidates,
            content_profile=content_profile,
            variant_count=variant_count,
        )
        selected_rankings = [item for item in ranked_candidates[:variant_count] if int(item.get("index", -1)) < len(candidates)]
        selected = [candidates[int(item["index"])] for item in selected_rankings]
        if not selected:
            selected_rankings = [{"index": 0, "score": 0.0, "reason": "", "source": "fallback"}]
            selected = [candidates[0]]
        if len(selected) < variant_count:
            chosen_indices = {int(item.get("index", -1)) for item in selected_rankings}
            for idx, candidate in enumerate(candidates):
                if idx in chosen_indices:
                    continue
                selected.append(candidate)
                selected_rankings.append(
                    {
                        "index": idx,
                        "score": 0.0,
                        "reason": "",
                        "source": "fallback_fill",
                    }
                )
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
        dimensions = _probe_video_dimensions(video_path)
        is_portrait = bool(dimensions and dimensions[1] > dimensions[0])
        selected, selected_rankings, title_variants = _prioritize_cover_variants(
            selected,
            selected_rankings,
            title_variants,
            is_portrait=is_portrait,
        )

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
        selection_summary = _build_cover_selection_summary(selected_rankings)
        _write_cover_variant_manifest(
            output_path,
            selected,
            title_variants,
            outputs,
            rankings=selected_rankings,
            selection_summary=selection_summary,
        )

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


def _probe_video_dimensions(video_path: Path) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(video_path),
            ],
            capture_output=True,
            timeout=10,
        )
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        for stream in data.get("streams", []):
            if str(stream.get("codec_type") or "").lower() != "video":
                continue
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if width > 0 and height > 0:
                return width, height
    except Exception:
        return None
    return None


def _portrait_cover_strategy_boost(strategy_key: str) -> float:
    boosts = {
        "ctr": 0.22,
        "xiaohongshu": 0.0,
        "bilibili": 0.03,
    }
    return boosts.get(str(strategy_key or "").strip().lower(), 0.0)


def _prioritize_cover_variants(
    selected: list[dict[str, Any]],
    selected_rankings: list[dict[str, Any]],
    title_variants: list[dict[str, Any] | None],
    *,
    is_portrait: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any] | None]]:
    entries: list[dict[str, Any]] = []
    strategy_order = {strategy["key"]: idx for idx, strategy in enumerate(COVER_TITLE_STRATEGIES)}
    for idx, candidate in enumerate(selected):
        ranking = dict(selected_rankings[idx]) if idx < len(selected_rankings) else {"index": idx, "score": 0.0, "reason": ""}
        plan = title_variants[idx] if idx < len(title_variants) else None
        strategy_key = str((plan or {}).get("strategy_key") or "").strip().lower()
        base_score = _normalize_cover_score(ranking.get("score"), fallback=0.0)
        boosted_score = base_score
        if is_portrait:
            boosted_score = _normalize_cover_score(base_score + _portrait_cover_strategy_boost(strategy_key), fallback=base_score)
        ranking["score"] = boosted_score
        entries.append(
            {
                "candidate": candidate,
                "ranking": ranking,
                "plan": plan,
                "sort_score": boosted_score,
                "strategy_rank": strategy_order.get(strategy_key, 999),
                "original_index": idx,
            }
        )

    entries.sort(
        key=lambda item: (
            -float(item["sort_score"]),
            int(item["strategy_rank"]),
            int(item["original_index"]),
        )
    )
    return (
        [item["candidate"] for item in entries],
        [item["ranking"] for item in entries],
        [item["plan"] for item in entries],
    )


def _sample_cover_candidates(
    video_path: Path,
    *,
    duration: float,
    anchor_seek: float,
    candidate_count: int,
    tmpdir: Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for i, seek in enumerate(
        _build_cover_candidate_seeks(
            duration,
            candidate_count=candidate_count,
            anchor_seek=anchor_seek,
        )
    ):
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


def _build_cover_candidate_seeks(
    duration: float,
    *,
    candidate_count: int,
    anchor_seek: float,
) -> list[float]:
    if duration <= 0 or candidate_count <= 0:
        return []

    max_seek = max(0.0, duration - 0.2)
    if max_seek <= 0:
        return [0.0]

    start = max(duration * 0.18, anchor_seek)
    start = min(max_seek, max(0.0, start))

    end = min(duration * 0.88, max_seek)
    preferred_span = max(duration * 0.18, 6.0)
    if end - start < 1.2:
        start = min(max_seek, max(0.0, duration * 0.25))
        end = min(max_seek, max(start + min(preferred_span, max_seek - start), duration * 0.72))

    if end - start < 0.6:
        fallback_seek = round(min(max_seek, max(0.0, anchor_seek)), 2)
        return [fallback_seek]

    step = (end - start) / (candidate_count + 1)
    return [round(start + step * (index + 1), 2) for index in range(candidate_count)]


async def _rank_cover_candidates(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any] | None,
    variant_count: int,
) -> list[dict[str, Any]]:
    preview_paths = [candidate["preview"] for candidate in candidates if candidate.get("preview")]
    if preview_paths:
        try:
            profile_text = json.dumps(content_profile or {}, ensure_ascii=False)
            prompt = (
                "你在为中文开箱/评测视频挑封面。请从候选帧里选出最适合做封面的前几名，"
                "第一优先级是吸引点击：画面要有冲击力、反差感、情绪张力、主体够大、第一眼就想点开。"
                "第二优先级才是图片内容表达：品牌、盒体、logo、型号、软件界面核心区域要尽量可读。"
                "优先选产品正面、包装正面、logo/型号能看出来、主体占画面足够大的画面。"
                "强烈避免任何带大面积字幕条、底部成句字幕、口播字幕、大片说明文案、直播条幅、贴纸文案、烧录文字的画面。"
                "避免只看到手、主体太小、糊帧、无重点、信息虽全但不抓眼、文字会挡住主体的画面。"
                f"\n视频主题参考：{profile_text}"
                "\n输出 JSON："
                "{\"ranked\":[{\"index\":0,\"score\":0.91,\"reason\":\"第一眼最抓人，主体也足够清楚\"}]}"
                f"，最多返回 {max(variant_count, 2)} 个结果，按优先级排序。score 范围 0-1。"
            )
            content = await asyncio.wait_for(
                complete_with_images(prompt, preview_paths, max_tokens=220, json_mode=True),
                timeout=6,
            )
            data = json.loads(extract_json_text(content))
            ordered: list[dict[str, Any]] = []
            seen_indices: set[int] = set()
            for raw in data.get("ranked", []):
                idx = int(raw.get("index", -1))
                if not 0 <= idx < len(candidates) or idx in seen_indices:
                    continue
                ordered.append(
                    {
                        "index": idx,
                        "score": _normalize_cover_score(raw.get("score"), fallback=0.0),
                        "reason": str(raw.get("reason") or "").strip(),
                        "source": "llm_rank",
                    }
                )
                seen_indices.add(idx)
            if ordered:
                return ordered
        except Exception as exc:
            if _is_cover_multimodal_fast_fallback_error(exc):
                logger.warning("Cover ranking degraded to fallback due to multimodal limit: %s", exc)
            pass

    fallback: list[dict[str, Any]] = []
    for idx in range(len(candidates)):
        score = max(0.0, round(0.82 - (idx * 0.06), 3))
        fallback.append({"index": idx, "score": score, "reason": "", "source": "fallback_rank"})
    return fallback[: max(variant_count, 2)]


def _normalize_cover_score(value: Any, *, fallback: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except Exception:
        return round(max(0.0, min(1.0, float(fallback))), 3)


def _build_cover_selection_summary(rankings: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    if not rankings:
        return {
            "enabled": settings.auto_select_cover_variant,
            "review_gap": round(float(settings.cover_selection_review_gap), 3),
            "review_recommended": False,
            "selected_variant_index": None,
            "selected_score": 0.0,
            "runner_up_index": None,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "review_reason": "",
        }

    primary = rankings[0]
    runner_up = rankings[1] if len(rankings) > 1 else None
    primary_score = _normalize_cover_score(primary.get("score"), fallback=0.0)
    runner_up_score = _normalize_cover_score(runner_up.get("score"), fallback=0.0) if runner_up else 0.0
    score_gap = round(max(0.0, primary_score - runner_up_score), 3)
    review_gap = round(max(0.0, min(1.0, float(settings.cover_selection_review_gap))), 3)
    review_recommended = bool(
        settings.auto_select_cover_variant and runner_up is not None and score_gap <= review_gap
    )
    review_reason = "前两张封面分差过小，建议确认首选图。" if review_recommended else ""
    return {
        "enabled": settings.auto_select_cover_variant,
        "review_gap": review_gap,
        "review_recommended": review_recommended,
        "selected_variant_index": 1,
        "selected_score": primary_score,
        "runner_up_index": 2 if runner_up is not None else None,
        "runner_up_score": runner_up_score,
        "score_gap": score_gap,
        "review_reason": review_reason,
    }


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
                "title": _adapt_cover_title_for_strategy(
                    fallback_plan,
                    strategy_key=strategy["key"],
                    content_profile=content_profile,
                ),
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
                "你在给中文短视频制作封面候选。现在有多张候选画面，请输出 5 套具有明确传播策略差异的封面标题方案。"
                "每套方案不是简单换词，而是针对不同平台/传播目标单独设计。"
                "总原则：封面优先吸引眼球，第二优先才是让图片内容表达更清楚。"
                "要求：\n"
                "1. 每套方案绑定一个 strategy_key 和一个 match_index。\n"
                "2. 请优先让不同策略匹配不同镜头；只有实在不合适才允许复用同一镜头。\n"
                "3. top 优先品牌或系列，长度 2-12 字。\n"
                "4. main 必须是主体名或产品类型，不要写“产品开箱与上手体验”“升级对比版”这类泛词。\n"
                "5. bottom 是钩子句，长度 6-12 字，必须有爆点、结果感、反差感或新鲜感，不能只是平铺直叙复述主题。\n"
                "6. 如果画面里出现英文品牌，请直接保留品牌英文。\n"
                "6.1 如果是软件/AI/科技教程，bottom 可以更浮夸，优先使用“强得离谱/直接封神/太炸了/太变态了/直接起飞/产能拉满”这类高点击表达。\n"
                "7. 五套方案必须体现不同风格倾向，不允许只是排列组合。\n"
                f"策略定义：\n{strategy_text}"
                f"\n已有上下文：{json.dumps(content_profile or {}, ensure_ascii=False)}"
                "\n输出 JSON："
                "{\"plans\":[{\"strategy_key\":\"xiaohongshu\",\"match_index\":0,\"top\":\"\",\"main\":\"\",\"bottom\":\"\",\"reason\":\"\"}]}"
            )
            content = await asyncio.wait_for(
                complete_with_images(prompt, preview_paths[:variant_count], max_tokens=700, json_mode=True),
                timeout=8,
            )
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
                        "title": _adapt_cover_title_for_strategy(
                            refined,
                            strategy_key=strategy["key"],
                            content_profile=content_profile,
                        ),
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
                            "title": _adapt_cover_title_for_strategy(
                                fallback_plan,
                                strategy_key=strategy["key"],
                                content_profile=content_profile,
                            ),
                        }
                    )
                return plans_by_candidate
        except Exception as exc:
            if _is_cover_multimodal_fast_fallback_error(exc):
                logger.warning("Cover title generation degraded to fallback due to multimodal limit: %s", exc)
            pass
    return [
        {
            "strategy_key": strategy["key"],
            "strategy_label": strategy["label"],
            "reason": "",
            "title_style": strategy["default_title_style"],
            "title": _adapt_cover_title_for_strategy(
                fallback_plan,
                strategy_key=strategy["key"],
                content_profile=content_profile,
            ),
        }
        for strategy in strategies[: max(1, len(candidates))]
    ]


def _adapt_cover_title_for_strategy(
    title_lines: dict[str, str] | None,
    *,
    strategy_key: str,
    content_profile: dict[str, Any] | None,
) -> dict[str, str] | None:
    if not _cover_title_is_usable(title_lines):
        return title_lines

    adapted = {
        "top": str((title_lines or {}).get("top") or "").strip()[:14],
        "main": str((title_lines or {}).get("main") or "").strip()[:18],
        "bottom": str((title_lines or {}).get("bottom") or "").strip()[:18],
    }
    bottom = adapted["bottom"]
    if not bottom:
        return adapted

    copy_style = str((content_profile or {}).get("copy_style") or "attention_grabbing").strip() or "attention_grabbing"
    subject = str((content_profile or {}).get("subject_model") or (content_profile or {}).get("subject_type") or adapted["main"]).strip()
    if strategy_key == "bilibili":
        adapted["bottom"] = _cover_strategy_bilibili(bottom, subject=subject, copy_style=copy_style)[:18]
    elif strategy_key == "xiaohongshu":
        adapted["bottom"] = _cover_strategy_xiaohongshu(bottom, subject=subject, copy_style=copy_style)[:18]
    elif strategy_key == "ctr":
        adapted["bottom"] = _cover_strategy_ctr(bottom, subject=subject, copy_style=copy_style)[:18]
    elif strategy_key == "brand":
        adapted["bottom"] = _cover_strategy_brand(bottom, subject=subject, copy_style=copy_style)[:18]
    return adapted


def _cover_strategy_bilibili(bottom: str, *, subject: str, copy_style: str) -> str:
    if copy_style == "trusted_expert":
        return f"{subject}重点讲明白" if subject else "重点一次讲明白"
    if copy_style == "premium_editorial":
        return f"{subject}变化拆开看" if subject else "这次变化拆开看"
    if copy_style == "playful_meme":
        return f"{subject}这次真有料" if subject else "这次内容真有料"
    if copy_style == "emotional_story":
        return f"{subject}这次真值吗" if subject else "这次到底值不值"
    if copy_style == "balanced":
        return f"{subject}关键点讲清楚" if subject else "关键点讲清楚"
    return f"{subject}一口气讲透" if subject else "这次一口气讲透"


def _cover_strategy_xiaohongshu(bottom: str, *, subject: str, copy_style: str) -> str:
    if copy_style == "trusted_expert":
        return f"{subject}这几点最值" if subject else "这几点最值得看"
    if copy_style == "premium_editorial":
        return f"{subject}质感太对了" if subject else "这次质感太对了"
    if copy_style == "playful_meme":
        return f"{subject}太会拿捏了" if subject else "这次真的太会了"
    if copy_style == "emotional_story":
        return f"{subject}越看越上头" if subject else "越看越容易上头"
    if copy_style == "balanced":
        return f"{subject}细节很加分" if subject else "细节真的很加分"
    return f"{subject}细节直接封神" if subject else "细节直接封神"


def _cover_strategy_ctr(bottom: str, *, subject: str, copy_style: str) -> str:
    if copy_style == "trusted_expert":
        return f"{subject}先看结论" if subject else "这次先看结论"
    if copy_style == "premium_editorial":
        return f"{subject}这次很能打" if subject else "这次真的很能打"
    if copy_style == "playful_meme":
        return f"{subject}强到离谱" if subject else "这波强到离谱"
    if copy_style == "emotional_story":
        return f"{subject}终于等到了" if subject else "终于等到这一刻"
    if copy_style == "balanced":
        return f"{subject}这次很顶" if subject else "这次真的很顶"
    return f"{subject}这次太炸了" if subject else "这次太炸了"


def _cover_strategy_brand(bottom: str, *, subject: str, copy_style: str) -> str:
    if copy_style == "trusted_expert":
        return f"{subject}判断更稳了" if subject else "这次判断更稳了"
    if copy_style == "premium_editorial":
        return f"{subject}气质拉满" if subject else "整体气质拉满"
    if copy_style == "playful_meme":
        return f"{subject}真有那味了" if subject else "这次真有那味了"
    if copy_style == "emotional_story":
        return f"{subject}很有感觉" if subject else "这次真的很有感觉"
    if copy_style == "balanced":
        return f"{subject}整体更顺眼" if subject else "整体更顺眼了"
    return f"{subject}高级感拉满" if subject else "高级感直接拉满"


def _write_cover_variant_manifest(
    output_path: Path,
    selected: list[dict[str, Any]],
    title_variants: list[dict[str, Any] | None],
    outputs: list[Path],
    *,
    rankings: list[dict[str, Any]] | None = None,
    selection_summary: dict[str, Any] | None = None,
) -> None:
    manifest_path = get_cover_manifest_path(output_path)
    legacy_manifest_path = get_legacy_cover_manifest_path(output_path)
    payload: list[dict[str, Any]] = []
    rankings = rankings or []
    selection_summary = selection_summary or {}
    for idx, target in enumerate(outputs):
        plan = title_variants[idx] if idx < len(title_variants) and isinstance(title_variants[idx], dict) else {}
        ranking = rankings[idx] if idx < len(rankings) and isinstance(rankings[idx], dict) else {}
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
                "score": _normalize_cover_score(ranking.get("score"), fallback=0.0),
                "rank": idx + 1,
                "is_primary": idx == 0,
                "review_recommended": bool(selection_summary.get("review_recommended")) if idx == 0 else False,
                "score_gap_to_next": selection_summary.get("score_gap") if idx == 0 else None,
                "review_reason": selection_summary.get("review_reason") if idx == 0 else "",
            }
        )
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if legacy_manifest_path != manifest_path:
        legacy_manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cover_selection_summary(output_path: Path) -> dict[str, Any] | None:
    manifest_path = get_cover_manifest_path(output_path)
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    primary = next((item for item in payload if item.get("is_primary")), payload[0])
    return {
        "enabled": get_settings().auto_select_cover_variant,
        "review_recommended": bool(primary.get("review_recommended")),
        "selected_variant_index": int(primary.get("index") or 1),
        "selected_score": _normalize_cover_score(primary.get("score"), fallback=0.0),
        "score_gap": _normalize_cover_score(primary.get("score_gap_to_next"), fallback=0.0),
        "review_reason": str(primary.get("review_reason") or "").strip(),
    }


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
        "软件工具",
        "软件教程",
        "功能演示",
        "AI工具",
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
    required_topics = _collect_cover_required_topics(content_profile, fallback_plan)
    if required_topics and not _cover_title_mentions_required_topic(normalized, required_topics):
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


def _collect_cover_required_topics(
    content_profile: dict[str, Any] | None,
    fallback_plan: dict[str, str] | None,
) -> set[str]:
    topics: set[str] = set()
    for key in ("subject_brand", "subject_model", "visible_text", "video_theme"):
        value = str((content_profile or {}).get(key) or "").strip()
        topics.update(_extract_cover_topic_terms(value))
    for value in (fallback_plan or {}).values():
        topics.update(_extract_cover_topic_terms(str(value or "")))
    return topics


def _extract_cover_topic_terms(text: str) -> set[str]:
    topics: set[str] = set()
    raw = str(text or "")
    for token in ("RunningHub", "ComfyUI", "OpenClaw", "无限画布", "工作流", "节点编排", "智能体", "漫剧"):
        if token.lower() in raw.lower():
            topics.add(token)
    return topics


def _cover_title_mentions_required_topic(title_lines: dict[str, str], required_topics: set[str]) -> bool:
    haystack = " ".join(str(value or "") for value in title_lines.values())
    lowered = haystack.lower()
    return any(topic.lower() in lowered for topic in required_topics)


async def _overlay_title_layout(
    cover_path: Path,
    title_lines: dict[str, str],
    cover_style: str,
    title_style: str,
) -> None:
    settings = get_settings()
    style = _title_style_tokens(title_style, title_lines=title_lines, cover_style=cover_style)
    layers = _build_cover_safe_area_layers(title_lines)

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


def _build_cover_safe_area_layers(title_lines: dict[str, str]) -> list[str]:
    del title_lines
    return []


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
    safe_x = str(x).replace(",", "\\,")
    safe_y = str(y).replace(",", "\\,")
    parts = [
        f"drawtext=text='{safe_text}'"
        f":fontfile='{fontfile}'",
        f":fontsize={fontsize}",
        f":fontcolor={fontcolor}",
        f":borderw={borderw}",
        f":bordercolor={bordercolor}",
        f":shadowcolor={shadowcolor}",
        f":shadowx={shadowx}:shadowy={shadowy}",
        f":x={safe_x}:y={safe_y}",
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
        return _apply_cross_platform_safe_zone(
            {
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
        },
            title_lines=title_lines,
        )

    top_small = _fit_font_size(title_lines.get("top", ""), 102, min_size=72)
    main_huge = _fit_font_size(title_lines.get("main", ""), 170, min_size=106)
    main_large = _fit_font_size(title_lines.get("main", ""), 154, min_size=98)
    bottom_mid = _fit_font_size(title_lines.get("bottom", ""), 110, min_size=78)

    if style_name == "cyber_logo_stack":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": top_small, "fill": "0x68F3FFFF", "border": "0x15131EFF", "borderw": 12, "x": "80", "y": "52", "shadowcolor": "0x1C5DFFFF", "shadowx": 6, "shadowy": 6},
            "main": {"size": main_huge, "fill": "0xF3F5FFFF", "border": "0x2539C4FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-28", "shadowcolor": "0x071018FF", "shadowx": 8, "shadowy": 8},
            "bottom": {"size": bottom_mid, "fill": "0xFFE28AFF", "border": "0xE05A2AFF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-74", "shadowcolor": "0x00000099", "shadowx": 5, "shadowy": 5},
        },
            title_lines=title_lines,
        )
    if style_name == "chrome_impact":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 94, min_size=68), "fill": "0xF2F9FFFF", "border": "0x111111FF", "borderw": 10, "x": "70", "y": "54", "shadowcolor": "0x3852E5FF", "shadowx": 5, "shadowy": 5},
            "main": {"size": main_huge, "fill": "0xF9F9F9FF", "border": "0x2A2017FF", "borderw": 20, "x": "(w-text_w)/2", "y": "(h-text_h)/2-10", "shadowcolor": "0x4B69FFFF", "shadowx": 6, "shadowy": 6},
            "bottom": {"size": bottom_mid, "fill": "0xFFF3B6FF", "border": "0xFF6A2BFF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82", "shadowcolor": "0x00000088", "shadowx": 4, "shadowy": 4},
        },
            title_lines=title_lines,
        )
    if style_name == "festival_badge":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 88, min_size=66), "fill": "0xFFEAB8FF", "border": "0x8A1A1AFF", "borderw": 8, "x": "(w-text_w)/2", "y": "56", "box": True, "boxcolor": "0x7E1515CC", "boxborderw": 20},
            "main": {"size": main_large, "fill": "0xFFF5D7FF", "border": "0xB31616FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-10", "shadowcolor": "0x00000077", "shadowx": 5, "shadowy": 5},
            "bottom": {"size": bottom_mid, "fill": "0xFFE59BFF", "border": "0xC94717FF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82", "box": True, "boxcolor": "0x8E2020B8", "boxborderw": 14},
        },
            title_lines=title_lines,
        )
    if style_name == "double_banner":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 84, min_size=64), "fill": "0xFFFDF7FF", "border": "0x111111FF", "borderw": 6, "x": "70", "y": "62", "box": True, "boxcolor": "0x1E8FE2CC", "boxborderw": 18},
            "main": {"size": main_large, "fill": "0xFFFFFFFF", "border": "0x131313FF", "borderw": 16, "x": "(w-text_w)/2", "y": "(h-text_h)/2-20"},
            "bottom": {"size": bottom_mid, "fill": "0xFFF7DDFF", "border": "0xA92918FF", "borderw": 8, "x": "(w-text_w)/2", "y": "h-text_h-84", "box": True, "boxcolor": "0xE4552CDD", "boxborderw": 18},
        },
            title_lines=title_lines,
        )
    if style_name == "comic_boom":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 96, min_size=68), "fill": "0xFFFACBFF", "border": "0x0F0F0FFF", "borderw": 9, "x": "78", "y": "48"},
            "main": {"size": main_huge, "fill": "0xFFF45AFF", "border": "0x0E0E0EFF", "borderw": 22, "x": "(w-text_w)/2", "y": "(h-text_h)/2-18", "shadowcolor": "0xFF4D5CFF", "shadowx": 6, "shadowy": 6},
            "bottom": {"size": bottom_mid, "fill": "0x7CF7FFFF", "border": "0x111111FF", "borderw": 10, "x": "(w-text_w)/2", "y": "h-text_h-82"},
        },
            title_lines=title_lines,
        )
    if style_name == "luxury_gold":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 84, min_size=64), "fill": "0xFFF2D8FF", "border": "0x3F2A11FF", "borderw": 6, "x": "(w-text_w)/2", "y": "64"},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 150, min_size=96), "fill": "0xFFF7EAFF", "border": "0x7B5417FF", "borderw": 16, "x": "(w-text_w)/2", "y": "(h-text_h)/2-16", "shadowcolor": "0x30200AFF", "shadowx": 4, "shadowy": 4},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 100, min_size=74), "fill": "0xFFE2A2FF", "border": "0x6B4212FF", "borderw": 8, "x": "(w-text_w)/2", "y": "h-text_h-80"},
        },
            title_lines=title_lines,
        )
    if style_name == "tutorial_blueprint":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 82, min_size=62), "fill": "0xDDF4FFFF", "border": "0x15486AFF", "borderw": 6, "x": "72", "y": "58", "box": True, "boxcolor": "0x103E5ECC", "boxborderw": 14},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 142, min_size=92), "fill": "0xFFFFFFFF", "border": "0x143952FF", "borderw": 14, "x": "72", "y": "(h-text_h)/2-16"},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 88, min_size=68), "fill": "0xE6F8FFFF", "border": "0x236A91FF", "borderw": 6, "x": "72", "y": "h-text_h-88"},
        },
            title_lines=title_lines,
        )
    if style_name == "magazine_clean":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 76, min_size=58), "fill": "0xFFFFFFFF", "border": "0x2B2B2BFF", "borderw": 4, "x": "(w-text_w)/2", "y": "66", "shadowcolor": "0x00000055", "shadowx": 2, "shadowy": 2},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 136, min_size=90), "fill": "0xFFFFFFFF", "border": "0x2B2B2BFF", "borderw": 8, "x": "(w-text_w)/2", "y": "(h-text_h)/2-12", "shadowcolor": "0x00000066", "shadowx": 3, "shadowy": 3},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 86, min_size=66), "fill": "0xFFF6F0FF", "border": "0x504842FF", "borderw": 4, "x": "(w-text_w)/2", "y": "h-text_h-82", "shadowcolor": "0x00000055", "shadowx": 2, "shadowy": 2},
        },
            title_lines=title_lines,
        )
    if style_name == "documentary_stamp":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 72, min_size=56), "fill": "0xF6F1E7FF", "border": "0x3A362DFF", "borderw": 4, "x": "60", "y": "60", "box": True, "boxcolor": "0x20231FB8", "boxborderw": 10},
            "main": {"size": _fit_font_size(title_lines.get("main", ""), 124, min_size=84), "fill": "0xF5F2EAFF", "border": "0x23211CFF", "borderw": 10, "x": "60", "y": "h*0.58-text_h", "shadowcolor": "0x00000066", "shadowx": 3, "shadowy": 3},
            "bottom": {"size": _fit_font_size(title_lines.get("bottom", ""), 76, min_size=58), "fill": "0xE6E1D6FF", "border": "0x4B463EFF", "borderw": 4, "x": "60", "y": "h-text_h-74"},
        },
            title_lines=title_lines,
        )
    if style_name == "neon_night":
        return _apply_cross_platform_safe_zone(
            {
            "top": {"size": _fit_font_size(title_lines.get("top", ""), 90, min_size=66), "fill": "0xFFE8F8FF", "border": "0x9324B8FF", "borderw": 9, "x": "78", "y": "50", "shadowcolor": "0x16C7FFFF", "shadowx": 6, "shadowy": 6},
            "main": {"size": main_large, "fill": "0xFFF7FCFF", "border": "0xFF4EA2FF", "borderw": 18, "x": "(w-text_w)/2", "y": "(h-text_h)/2-16", "shadowcolor": "0x283CFFFF", "shadowx": 8, "shadowy": 8},
            "bottom": {"size": bottom_mid, "fill": "0xFFF1A0FF", "border": "0xFF6A35FF", "borderw": 9, "x": "(w-text_w)/2", "y": "h-text_h-82"},
        },
            title_lines=title_lines,
        )
    return _title_style_tokens("preset_default", title_lines=title_lines, cover_style=cover_style)


def _apply_cross_platform_safe_zone(
    layout: dict[str, dict[str, Any]],
    *,
    title_lines: dict[str, str],
) -> dict[str, dict[str, Any]]:
    safe_layout: dict[str, dict[str, Any]] = {}
    for line_key, line_style in layout.items():
        style = dict(line_style)
        text = str(title_lines.get(line_key) or "").strip()
        box_padding = int(style.get("boxborderw", 0)) if style.get("box") else 0
        min_size = _cover_min_font_size(line_key)
        style["size"] = _fit_cover_text_to_safe_zone(
            text,
            int(style.get("size", min_size)),
            min_size=min_size,
            box_padding=box_padding,
        )
        style["x"] = _clamp_cover_title_x("(w-text_w)/2", box_padding=box_padding)
        style["y"] = _clamp_cover_title_y(_cover_focus_line_y(line_key), box_padding=box_padding)
        safe_layout[line_key] = style
    return safe_layout


def _cover_focus_line_y(line_key: str) -> str:
    if line_key == "top":
        return "max(h*0.135,54)"
    if line_key == "bottom":
        return "h-text_h-max(h*0.145,82)"
    return "(h-text_h)/2"


def _cover_min_font_size(line_key: str) -> int:
    if line_key == "main":
        return 96
    if line_key == "bottom":
        return 58
    return 64


def _fit_cover_text_to_safe_zone(
    text: str,
    base_size: int,
    *,
    min_size: int,
    box_padding: int = 0,
) -> int:
    cleaned = str(text or "").strip()
    if not cleaned:
        return max(min_size, base_size)
    estimated_units = _estimate_cover_text_units(cleaned)
    usable_width = max(220, int(1280 * _COVER_SAFE_TEXT_WIDTH_RATIO) - (box_padding * 2) - (_COVER_SAFE_MIN_INNER_PADDING * 2))
    estimated_size = int(usable_width / max(estimated_units, 1.0))
    return max(min_size, min(base_size, estimated_size))


def _estimate_cover_text_units(text: str) -> float:
    total = 0.0
    for ch in str(text or ""):
        if ch.isspace():
            total += 0.3
        elif ch.isascii():
            total += 0.62 if ch.isalnum() else 0.45
        else:
            total += 1.0
    return max(total, 1.0)


def _clamp_cover_title_x(x_expr: str, *, box_padding: int = 0) -> str:
    safe_left = f"max(w*{_COVER_SAFE_HORIZONTAL_MARGIN_RATIO:.6f},{_COVER_SAFE_MIN_INNER_PADDING})"
    safe_right = f"w-max(w*{_COVER_SAFE_HORIZONTAL_MARGIN_RATIO:.6f},{_COVER_SAFE_MIN_INNER_PADDING})"
    width_expr = "text_w"
    if box_padding > 0:
        width_expr = f"(text_w+{box_padding * 2})"
    return f"max({safe_left},min({x_expr},{safe_right}-{width_expr}))"


def _clamp_cover_title_y(y_expr: str, *, box_padding: int = 0) -> str:
    safe_top = f"max(h*{_COVER_SAFE_VERTICAL_TOP_RATIO:.3f},42)"
    safe_bottom = f"h-max(h*{_COVER_SAFE_VERTICAL_BOTTOM_RATIO:.3f},46)"
    height_expr = "text_h"
    if box_padding > 0:
        height_expr = f"(text_h+{box_padding * 2})"
    return f"max({safe_top},min({y_expr},{safe_bottom}-{height_expr}))"


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

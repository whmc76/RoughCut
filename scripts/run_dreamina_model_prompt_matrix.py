from __future__ import annotations

import asyncio
import argparse
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import roughcut.config as config_mod
from roughcut.providers.image_generation import generate_edited_cover_image
from roughcut.review.intelligent_copy import (
    OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
    _build_platform_cover_image_prompt,
)


REFERENCE_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\reference-fixed-21.jpg"
)
OUTPUT_DIR = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\dreamina-matrix"
)
LOCAL_PREVIEW_DIR = Path(r"C:/sample-workspace/RoughCut/data/runtime/compare-preview/dreamina-matrix")
TITLE = "美杜莎4双版开箱对比"
WIDTH = 1600
HEIGHT = 900


@dataclass(frozen=True)
class PromptVariant:
    key: str
    label: str
    video_type: str
    product_identity: str
    selling_angle: str
    visual_brief: str
    extra_lines: tuple[str, ...] = ()


VARIANTS: tuple[PromptVariant, ...] = (
    PromptVariant(
        key="balanced_identity",
        label="平衡主体锁定",
        video_type="开箱对比",
        product_identity="MAXACE美杜莎4（顶配与次顶配）",
        selling_angle="双版本同框，先看商品身份，再看结构和版本差异",
        visual_brief=(
            "两件商品必须还是参考图里的同两件；双版同框，主体放大，手持关系真实。"
            "背景保持深色暖金电影感，不要灰白留白；标题居中且完整。"
        ),
        extra_lines=(
            "背景不要灰白、米白、雾白留白，也不要极简电商海报感。",
            "标题做厚重金属大字，信息完整，字形清晰饱满。",
        ),
    ),
    PromptVariant(
        key="epic_poster_fx",
        label="史诗海报特效",
        video_type="开箱对比",
        product_identity="MAXACE美杜莎4（顶配与次顶配）",
        selling_angle="双版本同框，商品真实不改款，重点放在金属质感和版本差异",
        visual_brief=(
            "双版同框，主体大，手持真实，商品全貌完整。"
            "背景必须是暖金/橙金/暗黑金属的史诗电影氛围，带精致电光、火花和能量边缘光。"
            "不要灰白背景，不要廉价霓虹贴纸感。"
        ),
        extra_lines=(
            "特效要精致、细密、围绕主体服务，不要粗糙光污染。",
            "标题必须是成熟短视频封面字：厚重金属、立体高光、边缘精细能量描边。",
            "风格化只能加戏，不能改变商品结构、纹理、比例和开合关系。",
        ),
    ),
)

MODELS: tuple[str, ...] = ("5.0", "4.6", "4.5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run controlled Dreamina model/prompt comparison cases.")
    parser.add_argument("--model", action="append", dest="models", help="Model version(s) to run, e.g. 5.0, 4.6, 4.5.")
    parser.add_argument("--variant", action="append", dest="variants", help="Prompt variant key(s) to run.")
    return parser.parse_args()


def build_prompt(variant: PromptVariant) -> str:
    prompt = _build_platform_cover_image_prompt(
        title=TITLE,
        platform_key="bilibili",
        rules={"cover_style": OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO},
        width=WIDTH,
        height=HEIGHT,
        cover_brief={
            "video_type": variant.video_type,
            "product_identity": variant.product_identity,
            "selling_angle": variant.selling_angle,
            "visual_brief": variant.visual_brief,
        },
    ).strip()
    if variant.extra_lines:
        prompt = f"{prompt}\n" + "\n".join(variant.extra_lines)
    return prompt


async def run_one(*, model: str, variant: PromptVariant) -> dict[str, object]:
    output_name = f"dreamina-{model.replace('.', '_')}-{variant.key}.jpg"
    output_path = OUTPUT_DIR / output_name
    local_output_path = LOCAL_PREVIEW_DIR / output_name
    prompt = build_prompt(variant)
    saved_settings = config_mod._settings
    started = time.perf_counter()
    try:
        config_mod.apply_in_memory_runtime_overrides(
            {
                "intelligent_copy_cover_image_backend": "dreamina_web",
                "intelligent_copy_cover_image_model": model,
            }
        )
        metadata = await generate_edited_cover_image(
            source_image_path=REFERENCE_IMAGE,
            output_path=output_path,
            prompt=prompt,
            width=WIDTH,
            height=HEIGHT,
        )
    finally:
        config_mod._settings = saved_settings
    elapsed = round(time.perf_counter() - started, 3)
    local_output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, local_output_path)
    prompt_path = OUTPUT_DIR / f"dreamina-{model.replace('.', '_')}-{variant.key}.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    return {
        "ok": True,
        "model": model,
        "variant": variant.key,
        "variant_label": variant.label,
        "latency_sec": elapsed,
        "output_path": str(output_path),
        "local_preview_path": str(local_output_path),
        "prompt_path": str(prompt_path),
        "metadata": metadata,
    }


async def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    selected_models = tuple(args.models or MODELS)
    variant_map = {variant.key: variant for variant in VARIANTS}
    selected_variants = tuple(variant_map[key] for key in (args.variants or [variant.key for variant in VARIANTS]) if key in variant_map)
    manifest: dict[str, object] = {
        "reference_image": str(REFERENCE_IMAGE),
        "title": TITLE,
        "canvas": {"width": WIDTH, "height": HEIGHT},
        "selected_models": list(selected_models),
        "selected_variants": [variant.key for variant in selected_variants],
        "runs": [],
    }
    for model in selected_models:
        for variant in selected_variants:
            try:
                result = await run_one(model=model, variant=variant)
            except Exception as exc:
                result = {
                    "ok": False,
                    "model": model,
                    "variant": variant.key,
                    "variant_label": variant.label,
                    "error": str(exc),
                }
            manifest["runs"].append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_path": str(manifest_path), "run_count": len(manifest["runs"])}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from roughcut.providers.image_generation import generate_edited_cover_image
from roughcut.review.intelligent_copy import OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO, _build_platform_cover_image_prompt
import roughcut.config as config_mod


SOURCE_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\reference-fixed-21.jpg"
)
OUTPUT_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\dreamina-reference21-landscape.jpg"
)


async def main() -> None:
    model = str(os.environ.get("DREAMINA_COMPARE_MODEL", "") or os.environ.get("INTELLIGENT_COPY_COVER_IMAGE_MODEL", "") or "5.0").strip()
    output_name = f"dreamina-reference21-landscape-{model.replace('.', '_')}.jpg"
    output_path = OUTPUT_IMAGE.with_name(output_name)
    prompt = _build_platform_cover_image_prompt(
        title="美杜莎4双版开箱对比",
        platform_key="bilibili",
        rules={"cover_style": OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO},
        width=1600,
        height=900,
        cover_brief={
            "video_type": "开箱对比",
            "product_identity": "MAXACE美杜莎4（顶配与次顶配）",
            "selling_angle": "双版本同框，先认出是同两件商品，再看结构和版本差异",
            "visual_brief": (
                "双版同框，主体大，手持真实，商品全貌完整。"
                "背景必须是暖金/橙金/暗黑金属的史诗电影氛围，带精致电光、火花和能量边缘光。"
                "不要灰白背景，不要廉价霓虹贴纸感。"
            ),
        },
    )
    prompt = (
        f"{prompt}\n"
        "特效要精致、细密、围绕主体服务，不要粗糙光污染。\n"
        "标题必须是成熟短视频封面字：厚重金属、立体高光、边缘精细能量描边。\n"
        "风格化只能加戏，不能改变商品结构、纹理、比例和开合关系。"
    )
    saved_settings = config_mod._settings
    try:
        config_mod.apply_in_memory_runtime_overrides(
            {
                "intelligent_copy_cover_image_backend": "dreamina_web",
                "intelligent_copy_cover_image_model": model,
            }
        )
        metadata = await generate_edited_cover_image(
            source_image_path=SOURCE_IMAGE,
            output_path=output_path,
            prompt=prompt,
            width=1600,
            height=900,
        )
    finally:
        config_mod._settings = saved_settings
    print({"model": model, "output_path": str(output_path), **metadata})


if __name__ == "__main__":
    asyncio.run(main())

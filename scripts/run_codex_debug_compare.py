from __future__ import annotations

from pathlib import Path

from roughcut.providers.image_generation import _write_codex_imagegen_request
from roughcut.review.intelligent_copy import PLATFORM_PUBLISH_RULES, _build_platform_cover_image_prompt


SOURCE_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\reference-fixed-21.jpg"
)
OUTPUT_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\codex-reference21-landscape.jpg"
)
REQUEST_PATH = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\codex-reference21-landscape.codex-imagegen.json"
)


def main() -> None:
    prompt = _build_platform_cover_image_prompt(
        title="MAXACE美杜莎4 顶配次顶配开箱",
        platform_key="bilibili",
        rules={**PLATFORM_PUBLISH_RULES["bilibili"], "cover_style": "edc_cinematic_hero"},
        width=1600,
        height=900,
        cover_brief={
            "video_type": "开箱对比",
            "product_identity": "MAXACE美杜莎4 顶配与次顶配，两把真实同款折刀同框",
            "selling_angle": "同框直接看出顶配和次顶配的细节差别，适合做强对比封面",
            "visual_brief": "两把刀都要完整清晰，主体放大，手持真实，突出刀身细节、纹理和版本差异；背景要有暖金史诗氛围、电光火花和速度线，像成熟爆款 EDC 封面",
            "critical_detail_notes": [
                "刀身镜面反光区域是实心金属表面的高光，不是开孔、镂空或缺口。",
                "镜面高光只能增强质感，不能把该位置画成洞或断开的结构。",
            ],
        },
    )
    payload = _write_codex_imagegen_request(
        source_image_path=SOURCE_IMAGE,
        request_path=REQUEST_PATH,
        output_path=OUTPUT_IMAGE,
        prompt=prompt,
        width=1600,
        height=900,
    )
    print(payload["request_path"])


if __name__ == "__main__":
    main()

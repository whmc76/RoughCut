from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

import roughcut.config as config_mod
from roughcut.providers.image_generation import generate_edited_cover_image


REFERENCE_IMAGE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\reference-fixed-21.jpg"
)
OUTPUT_DIR = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\minimal-model-compare"
)
LOCAL_PREVIEW_DIR = Path(r"E:/WorkSpace/RoughCut/data/runtime/compare-preview/minimal-model-compare")
TITLE = "MAXACE 美杜莎4双版开箱对比"
WIDTH = 1600
HEIGHT = 900

MINIMAL_PROMPT = """基于参考图生成封面底图。
封面主题：MAXACE 美杜莎4双版开箱对比
主体：保持参考图里的同两件商品，不改结构，不变形。
画面：主体放大，手持真实，商品全貌完整。
风格：暖金暗色电影感背景，精致电光火花。
要求：不要灰白背景，先保主体一致，再做风格化；不要在图中生成任何文字、logo、水印。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dreamina minimal prompt comparisons across model versions.")
    parser.add_argument("--model", action="append", dest="models", help="Model versions to run, repeatable.")
    return parser.parse_args()


async def run_one(model: str) -> dict[str, object]:
    output_path = OUTPUT_DIR / f"dreamina-minimal-{model.replace('.', '_')}.jpg"
    local_preview_path = LOCAL_PREVIEW_DIR / output_path.name
    prompt_path = OUTPUT_DIR / f"dreamina-minimal-{model.replace('.', '_')}.prompt.txt"
    prompt_path.write_text(MINIMAL_PROMPT, encoding="utf-8")

    saved_settings = config_mod._settings
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
            prompt=MINIMAL_PROMPT,
            width=WIDTH,
            height=HEIGHT,
        )
    finally:
        config_mod._settings = saved_settings

    local_preview_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, local_preview_path)
    return {
        "ok": True,
        "model": model,
        "output_path": str(output_path),
        "local_preview_path": str(local_preview_path),
        "prompt_path": str(prompt_path),
        "metadata": metadata,
    }


async def main() -> None:
    args = parse_args()
    models = args.models or ["4.5", "4.6", "5.0"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "reference_image": str(REFERENCE_IMAGE),
        "title": TITLE,
        "prompt": MINIMAL_PROMPT,
        "models": models,
        "runs": [],
    }
    for model in models:
        try:
            result = await run_one(model)
        except Exception as exc:
            result = {
                "ok": False,
                "model": model,
                "error": str(exc),
            }
        manifest["runs"].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_path": str(manifest_path)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

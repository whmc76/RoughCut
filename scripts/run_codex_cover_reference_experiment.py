from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from roughcut.host.codex_bridge import run_codex_exec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run two Codex cover-generation experiments with different reference-image strategies."
    )
    parser.add_argument("--request", type=Path, required=True, help="Existing *.codex-imagegen.json request file.")
    parser.add_argument("--contact-sheet", type=Path, required=True, help="4-up candidate contact sheet image.")
    parser.add_argument("--out-dir", type=Path, help="Output directory for experiment artifacts.")
    parser.add_argument("--codex-model", default="", help="Override the Codex exec model.")
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_request(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request payload must be an object")
    return payload


def _make_output_dir(request_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        output_dir = explicit.expanduser().resolve()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_dir = request_path.parent / "_reference-experiments" / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _trim_non_black_content(tile: Image.Image) -> Image.Image:
    rgb = tile.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if max(r, g, b) <= 10:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return rgb
    return rgb.crop((min_x, min_y, max_x + 1, max_y + 1))


def _extract_contact_sheet_tiles(contact_sheet_path: Path, output_dir: Path) -> list[Path]:
    image = Image.open(contact_sheet_path).convert("RGB")
    width, height = image.size
    tile_width = width // 2
    tile_height = height // 2
    saved_paths: list[Path] = []
    for row in range(2):
        for col in range(2):
            tile = image.crop(
                (
                    col * tile_width,
                    row * tile_height,
                    (col + 1) * tile_width,
                    (row + 1) * tile_height,
                )
            )
            trimmed = _trim_non_black_content(tile)
            path = output_dir / f"panel-{row * 2 + col + 1}.jpg"
            trimmed.save(path, quality=95)
            saved_paths.append(path)
    return saved_paths


def _build_experiment_prompt(
    *,
    request: dict[str, Any],
    mode: str,
) -> str:
    target_size = request.get("target_size") if isinstance(request.get("target_size"), dict) else {}
    width = int(target_size.get("width") or 1440)
    height = int(target_size.get("height") or 1080)
    titles = request.get("cover_hard_contract") if isinstance(request.get("cover_hard_contract"), dict) else {}
    title_lines = titles.get("required_title_lines") if isinstance(titles.get("required_title_lines"), dict) else {}
    brand = str(title_lines.get("brand") or "MAXACE").strip()
    main = str(title_lines.get("main") or "美杜莎4").strip()
    subtitle = str(title_lines.get("sub") or title_lines.get("subtitle") or "顶配vs次顶配").strip()
    hook = str(title_lines.get("hook") or "双版本开箱").strip()

    reference_instruction = (
        "这次只给你一张四宫格候选图。把它当成同一组主体的多画面参考，综合理解四个画面里的两把刀、开合状态、材质、比例和版本关系。"
        " 不要把编号、黑边、视频字幕、包装文字或杂物原样带进最终封面。"
        if mode == "contact_sheet"
        else "这次给你四张独立参考图。把四张图当成同一组真实主体的多角度参考，综合还原更完整的主体结构、材质和版本差异。"
        " 不要复制任何字幕、包装字、编号或参考图边框。"
    )
    return (
        f"请生成一张 {width}x{height} 比例接近的最终可发布视频封面。\n"
        f"{reference_instruction}\n"
        "任务目标：做出强点击的双版本对比封面，但前提是主体真实、完整、清晰。\n"
        "主体要求：主体是同一品牌同一型号的两个版本，保持真实刀型、双刃结构、金属材质和版本差异，不要凭空改结构。"
        " 允许电影化背景和光效增强，但不要把主体变成插画玩具，不要让背景抢走主体。\n"
        "构图要求：至少让两把刀的关键主体都清楚可辨，优先保留更完整的刀身、刀柄、尾部和版本关系。"
        " 如果需要取舍，优先牺牲背景和杂物，不要牺牲主体完整性。\n"
        f"文字要求：最终位图里只允许出现这四层文字：品牌行「{brand}」；主标题「{main}」；副标题「{subtitle}」；吸睛文案「{hook}」。\n"
        "排版要求：主标题最大，副标题次之，品牌行独立在上方，吸睛文案做成短 badge。"
        " 不要额外添加 slogan、包装字、水印、字幕、按钮、英文乱字或伪 logo。\n"
        "参考图只用于识别主体和版本关系，不能把参考图中的包装盒、卡片、贴纸、手部字幕或背景脏信息原样搬运进最终封面。"
    )


def _build_codex_prompt(*, experiment_prompt: str, output_path: Path) -> str:
    return (
        "Use Codex built-in image_gen or image editing capabilities to create exactly one final bitmap cover.\n"
        "Do not use any external image APIs.\n"
        "Treat all attached images as the full allowed reference pack for the same real product set.\n"
        "Follow this cover brief exactly:\n\n"
        f"{experiment_prompt}\n\n"
        "Hard requirements:\n"
        f"- Save the final bitmap exactly at this path: {output_path}\n"
        "- The bitmap itself must already be the final publishable cover.\n"
        "- Keep the product identity consistent across all references.\n"
        "- Render the requested title text directly in the image.\n"
        "- Do not add extra text, watermarks, pseudo logos, subtitles, panel numbers, or black contact-sheet borders.\n"
        "- Return JSON only after the bitmap exists on disk.\n"
        '- Final response JSON must be: {"status":"completed","output_path":"<exact path>","notes":"short summary"}\n'
    )


def _run_codex(
    *,
    request: dict[str, Any],
    image_paths: list[Path],
    output_path: Path,
    mode: str,
    model_override: str,
) -> dict[str, Any]:
    runner = request.get("codex_runner") if isinstance(request.get("codex_runner"), dict) else {}
    model = str(model_override or runner.get("model") or "").strip()
    experiment_prompt = _build_experiment_prompt(request=request, mode=mode)
    started = time.perf_counter()
    result = run_codex_exec(
        {
            "repo_root": str(_repo_root()),
            "prompt": _build_codex_prompt(experiment_prompt=experiment_prompt, output_path=output_path),
            "images": [str(path) for path in image_paths],
            "model": model,
            "output_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "output_path": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["status", "output_path", "notes"],
                "additionalProperties": False,
            },
        }
    )
    elapsed = round(time.perf_counter() - started, 3)
    if not output_path.exists():
        raise RuntimeError(f"Codex did not write expected output: {output_path}")
    response_payload: dict[str, Any] = {}
    stdout = str(result.get("stdout") or "").strip()
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                response_payload = parsed
        except Exception:
            response_payload = {}
    return {
        "ok": True,
        "mode": mode,
        "model": model or str(runner.get("model") or ""),
        "latency_sec": elapsed,
        "output_path": str(output_path),
        "reference_images": [str(path) for path in image_paths],
        "response": response_payload,
        "prompt": experiment_prompt,
    }


def main() -> int:
    args = parse_args()
    request_path = args.request.expanduser().resolve()
    contact_sheet_path = args.contact_sheet.expanduser().resolve()
    request = _load_request(request_path)
    output_dir = _make_output_dir(request_path, args.out_dir)
    extracted_dir = output_dir / "extracted-panels"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    panel_paths = _extract_contact_sheet_tiles(contact_sheet_path, extracted_dir)

    runs = [
        (
            "contact_sheet",
            [contact_sheet_path],
            output_dir / "contact-sheet-reference.jpg",
        ),
        (
            "multi_panel",
            panel_paths,
            output_dir / "multi-panel-reference.jpg",
        ),
    ]

    manifest: dict[str, Any] = {
        "request_path": str(request_path),
        "contact_sheet_path": str(contact_sheet_path),
        "panel_paths": [str(path) for path in panel_paths],
        "results": {},
    }
    for mode, image_paths, output_path in runs:
        try:
            manifest["results"][mode] = _run_codex(
                request=request,
                image_paths=image_paths,
                output_path=output_path,
                mode=mode,
                model_override=str(args.codex_model or ""),
            )
        except Exception as exc:
            manifest["results"][mode] = {
                "ok": False,
                "mode": mode,
                "reference_images": [str(path) for path in image_paths],
                "error": str(exc),
            }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "manifest_path": str(manifest_path), "results": manifest["results"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

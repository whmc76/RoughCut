from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


SOURCE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\00-highlight-cover-source.jpg"
)
OUTPUT_DIR = Path(
    r"E:\WorkSpace\RoughCut\artifacts\objective-smoke\maxace4-manual-cover-template"
)
FONT_PATH = Path(r"C:\Windows\Fonts\msyhbd.ttc")

TEXT_SPEC = {
    "brand": "MAXACE",
    "main": "美杜莎4",
    "sub": "顶配 VS 次顶配",
    "hook": "双版本开箱",
}

RATIOS = {
    "16_9": (1600, 900),
    "4_3": (1440, 1080),
    "3_4": (1080, 1440),
    "9_16": (1080, 1920),
}


def _fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _fit_cover_blur_fill(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    background = _fit_cover(image, size).filter(ImageFilter.GaussianBlur(max(18, min(size) // 36)))
    scale = min(target_w / image.width, target_h / image.height)
    resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    canvas = background.convert("RGBA")
    foreground = resized.convert("RGBA")
    offset = ((target_w - foreground.width) // 2, (target_h - foreground.height) // 2)
    canvas.alpha_composite(foreground, dest=offset)
    return canvas


def _draw_text_backplate(
    image: Image.Image,
    *,
    xy: tuple[int, int],
    size: tuple[int, int],
    fill: tuple[int, int, int, int],
    blur_radius: int,
) -> None:
    plate = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    x, y = xy
    w, h = size
    draw.rounded_rectangle((x, y, x + w, y + h), radius=max(18, min(w, h) // 8), fill=fill)
    plate = plate.filter(ImageFilter.GaussianBlur(blur_radius))
    image.alpha_composite(plate)


def _gradient_rgba(size: tuple[int, int], top: tuple[int, int, int], middle: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    gradient = Image.new("RGBA", size, (0, 0, 0, 0))
    pixels = gradient.load()
    for y in range(h):
        t = y / max(1, h - 1)
        if t < 0.46:
            p = t / 0.46
            c0, c1 = top, middle
        else:
            p = (t - 0.46) / 0.54
            c0, c1 = middle, bottom
        color = tuple(int(c0[i] * (1 - p) + c1[i] * p) for i in range(3))
        for x in range(w):
            pixels[x, y] = (*color, 255)
    return gradient


def _draw_gradient_text(
    image: Image.Image,
    *,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    gradient: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]],
    stroke_fill: tuple[int, int, int],
    stroke_width: int,
    depth_fill: tuple[int, int, int],
    depth_offset: tuple[int, int],
    glow_fill: tuple[int, int, int, int],
    glow_radius: int,
    shine: bool = True,
) -> None:
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox(xy, text, font=font, stroke_width=stroke_width)
    pad = max(24, stroke_width * 3)
    layer_box = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    layer_size = (layer_box[2] - layer_box[0], layer_box[3] - layer_box[1])
    local_xy = (xy[0] - layer_box[0], xy[1] - layer_box[1])

    glow = Image.new("RGBA", layer_size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.text(local_xy, text, font=font, fill=glow_fill, stroke_width=max(2, stroke_width), stroke_fill=glow_fill)
    glow = glow.filter(ImageFilter.GaussianBlur(glow_radius))
    image.alpha_composite(glow, dest=(layer_box[0], layer_box[1]))

    depth = Image.new("RGBA", layer_size, (0, 0, 0, 0))
    depth_draw = ImageDraw.Draw(depth)
    dx, dy = depth_offset
    depth_draw.text(
        (local_xy[0] + dx, local_xy[1] + dy),
        text,
        font=font,
        fill=depth_fill,
        stroke_width=stroke_width,
        stroke_fill=depth_fill,
    )
    image.alpha_composite(depth, dest=(layer_box[0], layer_box[1]))

    stroke = Image.new("RGBA", layer_size, (0, 0, 0, 0))
    stroke_draw = ImageDraw.Draw(stroke)
    stroke_draw.text(local_xy, text, font=font, fill=stroke_fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    image.alpha_composite(stroke, dest=(layer_box[0], layer_box[1]))

    mask = Image.new("L", layer_size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(local_xy, text, font=font, fill=255)
    fill = _gradient_rgba(layer_size, *gradient)
    fill.putalpha(mask)
    image.alpha_composite(fill, dest=(layer_box[0], layer_box[1]))

    if shine:
        shine_layer = Image.new("RGBA", layer_size, (0, 0, 0, 0))
        shine_draw = ImageDraw.Draw(shine_layer)
        y = int(local_xy[1] + (bbox[3] - bbox[1]) * 0.28)
        shine_draw.line((0, y, layer_size[0], y - int(layer_size[1] * 0.18)), fill=(255, 255, 255, 115), width=max(3, stroke_width // 3))
        shine_layer.putalpha(ImageChops.multiply(shine_layer.getchannel("A"), mask))
        image.alpha_composite(shine_layer, dest=(layer_box[0], layer_box[1]))


def _draw_layered_text(
    image: Image.Image,
    *,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    stroke_fill: tuple[int, int, int],
    stroke_width: int,
    depth_fill: tuple[int, int, int],
    depth_offset: tuple[int, int],
    glow_fill: tuple[int, int, int, int] | None = None,
    glow_radius: int = 0,
    box_color: tuple[int, int, int, int] | None = None,
    box_padding: int = 0,
) -> None:
    if box_color:
        draw = ImageDraw.Draw(image)
        bbox = draw.textbbox(xy, text, font=font, stroke_width=stroke_width)
        draw.rounded_rectangle(
            (
                bbox[0] - box_padding,
                bbox[1] - box_padding,
                bbox[2] + box_padding,
                bbox[3] + box_padding,
            ),
            radius=max(12, box_padding),
            fill=box_color,
        )
    text_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    dx, dy = depth_offset
    draw.text(
        (xy[0] + dx, xy[1] + dy),
        text,
        font=font,
        fill=depth_fill,
        stroke_width=stroke_width,
        stroke_fill=depth_fill,
    )
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    if glow_fill and glow_radius > 0:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.text(
            xy,
            text,
            font=font,
            fill=glow_fill,
            stroke_width=max(2, stroke_width // 2),
            stroke_fill=glow_fill,
        )
        glow = glow.filter(ImageFilter.GaussianBlur(glow_radius))
        image.alpha_composite(glow)
    image.alpha_composite(text_layer)


def _build_fonts(size: tuple[int, int]) -> dict[str, ImageFont.FreeTypeFont]:
    w, h = size
    unit = min(w, h)
    return {
        "brand": ImageFont.truetype(str(FONT_PATH), max(42, unit // 12)),
        "main": ImageFont.truetype(str(FONT_PATH), max(84, unit // 8)),
        "sub": ImageFont.truetype(str(FONT_PATH), max(52, unit // 13)),
        "hook": ImageFont.truetype(str(FONT_PATH), max(48, unit // 15)),
    }


def _layout_for_ratio(ratio_key: str, size: tuple[int, int]) -> dict[str, tuple[int, int] | int | float]:
    w, h = size
    if ratio_key in {"16_9", "4_3"}:
        return {
            "brand_xy": (int(w * 0.05), int(h * 0.05)),
            "main_xy": (int(w * 0.04), int(h * 0.19)),
            "sub_xy": (int(w * 0.05), int(h * 0.40)),
            "hook_xy": (int(w * 0.06), int(h * 0.61)),
            "badge_padding": max(14, min(w, h) // 40),
            "stack_max_width_ratio": 0.30,
            "stack_max_height_ratio": 0.56,
        }
    return {
        "brand_xy": (int(w * 0.07), int(h * 0.05)),
        "main_xy": (int(w * 0.06), int(h * 0.14)),
        "sub_xy": (int(w * 0.07), int(h * 0.31)),
        "hook_xy": (int(w * 0.08), int(h * 0.55)),
        "badge_padding": max(14, min(w, h) // 34),
        "stack_max_width_ratio": 0.33,
        "stack_max_height_ratio": 0.48,
    }


def _text_bbox_size(text: str, font: ImageFont.FreeTypeFont, stroke_width: int) -> tuple[int, int]:
    temp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _resolve_text_scale(
    size: tuple[int, int],
    layout: dict[str, tuple[int, int] | int | float],
) -> float:
    w, h = size
    max_width = int(w * float(layout["stack_max_width_ratio"]))
    max_height = int(h * float(layout["stack_max_height_ratio"]))
    scale = 1.0
    while scale >= 0.66:
        scaled_fonts = _build_fonts((int(w * scale), int(h * scale)))
        main_w, main_h = _text_bbox_size(TEXT_SPEC["main"], scaled_fonts["main"], max(9, min(size) // 70))
        sub_w, sub_h = _text_bbox_size(TEXT_SPEC["sub"], scaled_fonts["sub"], max(7, min(size) // 95))
        hook_w, hook_h = _text_bbox_size(TEXT_SPEC["hook"], scaled_fonts["hook"], max(6, min(size) // 110))
        brand_w, brand_h = _text_bbox_size(TEXT_SPEC["brand"], scaled_fonts["brand"], max(5, min(size) // 160))
        stack_w = max(brand_w, main_w, sub_w, hook_w)
        stack_h = brand_h + main_h + sub_h + hook_h + int(h * 0.08)
        if stack_w <= max_width and stack_h <= max_height:
            return scale
        scale -= 0.05
    return 0.66


def _render_ratio_sample(ratio_key: str, size: tuple[int, int]) -> Path:
    base = Image.open(SOURCE).convert("RGBA")
    source_ratio = base.width / max(1, base.height)
    target_ratio = size[0] / max(1, size[1])
    ratio_gap = abs(source_ratio - target_ratio) / max(source_ratio, target_ratio)
    if ratio_gap >= 0.16:
        cover = _fit_cover_blur_fill(base, size).convert("RGBA")
    else:
        cover = _fit_cover(base, size).convert("RGBA")

    layout = _layout_for_ratio(ratio_key, size)
    text_scale = _resolve_text_scale(size, layout)
    fonts = _build_fonts((int(size[0] * text_scale), int(size[1] * text_scale)))
    w, h = size

    main_xy = layout["main_xy"]
    sub_xy = layout["sub_xy"]
    hook_xy = layout["hook_xy"]
    brand_xy = layout["brand_xy"]
    if text_scale < 0.95:
        shrink_offset = int(h * (1.0 - text_scale) * 0.10)
        main_xy = (main_xy[0], max(0, main_xy[1] - shrink_offset))
        sub_xy = (sub_xy[0], max(0, sub_xy[1] - shrink_offset))
        hook_xy = (hook_xy[0], max(0, hook_xy[1] - shrink_offset))

    _draw_gradient_text(
        cover,
        text=TEXT_SPEC["brand"],
        xy=brand_xy,
        font=fonts["brand"],
        gradient=((255, 255, 220), (255, 211, 86), (221, 119, 21)),
        stroke_fill=(5, 20, 44),
        stroke_width=max(5, min(size) // 160),
        depth_fill=(32, 78, 206),
        depth_offset=(max(4, min(size) // 220), max(4, min(size) // 220)),
        glow_fill=(46, 188, 255, 150),
        glow_radius=max(6, min(size) // 130),
    )
    _draw_gradient_text(
        cover,
        text=TEXT_SPEC["main"],
        xy=main_xy,
        font=fonts["main"],
        gradient=((255, 255, 248), (225, 235, 245), (255, 115, 23)),
        stroke_fill=(4, 16, 28),
        stroke_width=max(9, min(size) // 70),
        depth_fill=(30, 60, 190),
        depth_offset=(max(9, min(size) // 105), max(9, min(size) // 105)),
        glow_fill=(255, 76, 36, 170),
        glow_radius=max(10, min(size) // 95),
    )
    _draw_gradient_text(
        cover,
        text=TEXT_SPEC["sub"],
        xy=sub_xy,
        font=fonts["sub"],
        gradient=((220, 255, 255), (72, 245, 255), (252, 60, 166)),
        stroke_fill=(5, 15, 44),
        stroke_width=max(7, min(size) // 95),
        depth_fill=(183, 24, 113),
        depth_offset=(max(5, min(size) // 170), max(5, min(size) // 170)),
        glow_fill=(56, 172, 255, 150),
        glow_radius=max(8, min(size) // 110),
    )
    _draw_gradient_text(
        cover,
        text=TEXT_SPEC["hook"],
        xy=hook_xy,
        font=fonts["hook"],
        gradient=((255, 255, 216), (255, 201, 74), (255, 89, 18)),
        stroke_fill=(86, 15, 4),
        stroke_width=max(6, min(size) // 110),
        depth_fill=(80, 24, 12),
        depth_offset=(max(4, min(size) // 200), max(4, min(size) // 200)),
        glow_fill=(255, 167, 42, 140),
        glow_radius=max(7, min(size) // 120),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"maxace4-template-{ratio_key}.jpg"
    cover.convert("RGB").save(output_path, quality=95)
    return output_path


def main() -> None:
    outputs = {}
    for ratio_key, size in RATIOS.items():
        outputs[ratio_key] = str(_render_ratio_sample(ratio_key, size))
    summary_path = OUTPUT_DIR / "render-summary.json"
    summary_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

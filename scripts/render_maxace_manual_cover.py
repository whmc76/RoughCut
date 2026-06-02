from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont


REFERENCE = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\reference-fixed-21.jpg"
)
OUTPUT = Path(
    r"E:\WorkSpace\RoughCut\data\runtime\compare-preview\manual-maxace-cover-v3.jpg"
)
SHARED_OUTPUT = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\smart-copy\compare\manual-maxace-cover-v3.jpg"
)
FONT_PATH = Path(r"C:\Windows\Fonts\msyhbd.ttc")
SIZE = (1600, 900)


def _fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _add_vignette(image: Image.Image) -> Image.Image:
    overlay = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(overlay)
    margin = 18
    draw.ellipse(
        (margin, margin, image.width - margin, image.height - margin),
        fill=190,
    )
    blurred = overlay.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGBA", image.size, (0, 0, 0, 0))
    dark.putalpha(ImageChops.invert(blurred))
    return Image.alpha_composite(image.convert("RGBA"), dark)


def _add_warm_glow(image: Image.Image) -> Image.Image:
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((780, 180, 1500, 860), fill=(255, 178, 58, 86))
    draw.ellipse((940, 260, 1540, 860), fill=(255, 108, 18, 62))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    return Image.alpha_composite(image, glow)


def _add_energy(image: Image.Image) -> Image.Image:
    fx = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(fx)
    orange = (255, 191, 73, 235)
    blue = (58, 120, 255, 210)
    for points, width, color in (
        ([(700, 540), (820, 480), (940, 505), (1070, 470), (1200, 500)], 7, blue),
        ([(660, 708), (840, 645), (1020, 690), (1190, 640)], 9, orange),
        ([(760, 360), (870, 315), (980, 360), (1090, 300)], 5, orange),
    ):
        draw.line(points, fill=color, width=width, joint="curve")
    spark_points = [
        (980, 430),
        (1040, 510),
        (1110, 390),
        (1180, 470),
        (1230, 560),
        (1310, 420),
    ]
    for x, y in spark_points:
        draw.line((x - 18, y, x + 18, y), fill=orange, width=4)
        draw.line((x, y - 18, x, y + 18), fill=orange, width=4)
    fx = fx.filter(ImageFilter.GaussianBlur(1.6))
    return Image.alpha_composite(image, fx)


def _build_subject_hero(base_cover: Image.Image) -> Image.Image:
    background = ImageEnhance.Color(base_cover).enhance(1.14)
    background = background.filter(ImageFilter.GaussianBlur(16))
    background = ImageEnhance.Brightness(background).enhance(0.78)
    background = background.convert("RGBA")

    foreground = ImageEnhance.Sharpness(base_cover).enhance(1.45)
    foreground = ImageEnhance.Contrast(foreground).enhance(1.08)
    foreground = foreground.convert("RGBA")

    mask = Image.new("L", base_cover.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((220, 120, 1560, 930), fill=255)
    draw.rounded_rectangle((640, 240, 1590, 900), radius=120, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(34))
    return Image.composite(foreground, background, mask)


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
) -> None:
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


def main() -> None:
    base = Image.open(REFERENCE).convert("RGB")
    cover = _fit_cover(base, SIZE)
    cover = _build_subject_hero(cover)
    cover = ImageEnhance.Color(cover).enhance(1.22)
    cover = ImageEnhance.Contrast(cover).enhance(1.18)
    cover = ImageEnhance.Sharpness(cover).enhance(1.12)
    cover = _add_vignette(cover)
    cover = _add_warm_glow(cover)
    cover = _add_energy(cover)

    top_font = ImageFont.truetype(str(FONT_PATH), 108)
    main_font = ImageFont.truetype(str(FONT_PATH), 178)
    bottom_font = ImageFont.truetype(str(FONT_PATH), 112)

    _draw_layered_text(
        cover,
        text="MAXACE",
        xy=(100, 60),
        font=top_font,
        fill=(255, 214, 116),
        stroke_fill=(25, 22, 18),
        stroke_width=9,
        depth_fill=(17, 58, 196),
        depth_offset=(8, 8),
        glow_fill=(65, 127, 255, 160),
        glow_radius=8,
    )
    _draw_layered_text(
        cover,
        text="美杜莎4",
        xy=(18, 290),
        font=main_font,
        fill=(245, 245, 248),
        stroke_fill=(171, 40, 24),
        stroke_width=18,
        depth_fill=(18, 47, 143),
        depth_offset=(12, 12),
        glow_fill=(255, 96, 70, 120),
        glow_radius=10,
    )
    _draw_layered_text(
        cover,
        text="双版开箱对比",
        xy=(58, 694),
        font=bottom_font,
        fill=(255, 218, 112),
        stroke_fill=(162, 58, 18),
        stroke_width=12,
        depth_fill=(87, 33, 12),
        depth_offset=(8, 8),
        glow_fill=(255, 170, 72, 96),
        glow_radius=8,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    cover.convert("RGB").save(OUTPUT, quality=95)
    SHARED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    cover.convert("RGB").save(SHARED_OUTPUT, quality=95)
    print(OUTPUT)
    print(SHARED_OUTPUT)


if __name__ == "__main__":
    main()

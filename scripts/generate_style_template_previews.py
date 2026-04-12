from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from roughcut.media.subtitles import escape_path_for_ffmpeg_filter, write_ass_file

CANVAS_W = 720
CANVAS_H = 1280
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "frontend" / "public" / "style-template-previews"
COMPARE_TEXT = "重点词一炸 客户立刻看懂"
COMPARE_BACKGROUND = (
    "drawbox=x=0:y=0:w=iw:h=ih:color=0x0a0d13:t=fill,"
    "drawbox=x=56:y=108:w=608:h=422:color=0x111826@0.96:t=fill,"
    "drawbox=x=88:y=148:w=544:h=116:color=0x8fc3ff@0.10:t=fill,"
    "drawbox=x=96:y=306:w=228:h=146:color=0xff9d35@0.10:t=fill,"
    "drawbox=x=372:y=286:w=210:h=182:color=0x0c1119@0.94:t=fill,"
    "drawbox=x=58:y=558:w=604:h=144:color=0x0b1118@0.92:t=fill"
)


TEMPLATES = [
    {
        "slug": "impact-commerce",
        "style_name": "sale_banner",
        "motion_style": "motion_strobe",
        "capture_sec": 1.05,
        "background": (
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x090b10:t=fill,"
            "drawbox=x=52:y=86:w=616:h=378:color=0x2a1210@0.95:t=fill,"
            "drawbox=x=52:y=482:w=616:h=208:color=0x160d0b@0.88:t=fill,"
            "drawbox=x=82:y=132:w=556:h=112:color=0xff7a3a@0.18:t=fill,"
            "drawbox=x=92:y=278:w=282:h=146:color=0xffad5a@0.12:t=fill,"
            "drawbox=x=398:y=276:w=176:h=188:color=0x0f131a@0.92:t=fill,"
            "drawbox=x=430:y=306:w=112:h=124:color=0xe9c97c@0.2:t=fill"
        ),
        "items": [
            {
                "start_time": 0.25,
                "end_time": 1.8,
                "text_final": "这波升级 直接值了",
                "style_name": "sale_banner",
                "motion_style": "motion_strobe",
                "subtitle_section_role": "hook",
                "subtitle_unit_role": "lead",
                "highlight_terms": ["升级", "值了"],
            }
        ],
    },
    {
        "slug": "hardcore-specs",
        "style_name": "keyword_highlight",
        "motion_style": "motion_glitch",
        "capture_sec": 1.12,
        "background": (
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x09101a:t=fill,"
            "drawbox=x=52:y=92:w=616:h=410:color=0x111a29@0.96:t=fill,"
            "drawbox=x=84:y=126:w=552:h=132:color=0x17365f@0.22:t=fill,"
            "drawbox=x=94:y=298:w=246:h=154:color=0x1f8cff@0.14:t=fill,"
            "drawbox=x=366:y=284:w=218:h=194:color=0x0b1016@0.96:t=fill,"
            "drawbox=x=402:y=320:w=144:h=118:color=0xff9d35@0.18:t=fill,"
            "drawbox=x=52:y=534:w=616:h=154:color=0x0d1520@0.92:t=fill"
        ),
        "items": [
            {
                "start_time": 0.3,
                "end_time": 1.8,
                "text_final": "直接上 PRO 参数",
                "style_name": "keyword_highlight",
                "motion_style": "motion_glitch",
                "subtitle_section_role": "detail",
                "subtitle_unit_role": "focus",
                "highlight_terms": ["PRO", "参数"],
            }
        ],
    },
    {
        "slug": "suspense-teaser",
        "style_name": "teaser_glow",
        "motion_style": "motion_echo",
        "capture_sec": 1.18,
        "background": (
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x080a13:t=fill,"
            "drawbox=x=44:y=102:w=632:h=438:color=0x0d1625@0.96:t=fill,"
            "drawbox=x=80:y=144:w=560:h=104:color=0x63d9ff@0.12:t=fill,"
            "drawbox=x=82:y=276:w=278:h=188:color=0x7d5cff@0.12:t=fill,"
            "drawbox=x=384:y=254:w=212:h=236:color=0x101826@0.92:t=fill,"
            "drawbox=x=414:y=296:w=150:h=144:color=0xff82b0@0.12:t=fill,"
            "drawbox=x=44:y=560:w=632:h=138:color=0x0b1018@0.9:t=fill"
        ),
        "items": [
            {
                "start_time": 0.35,
                "end_time": 1.95,
                "text_final": "真正的大招 还在后面",
                "style_name": "teaser_glow",
                "motion_style": "motion_echo",
                "subtitle_section_role": "hook",
                "subtitle_unit_role": "lead",
                "highlight_terms": ["大招", "后面"],
            }
        ],
    },
    {
        "slug": "restrained-explainer",
        "style_name": "amber_news",
        "motion_style": "motion_slide",
        "capture_sec": 1.08,
        "background": (
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x0d1116:t=fill,"
            "drawbox=x=58:y=96:w=604:h=398:color=0x171d27@0.97:t=fill,"
            "drawbox=x=90:y=138:w=540:h=98:color=0xf0b35a@0.1:t=fill,"
            "drawbox=x=90:y=276:w=540:h=176:color=0x273749@0.58:t=fill,"
            "drawbox=x=120:y=320:w=196:h=88:color=0x6f88a3@0.18:t=fill,"
            "drawbox=x=58:y=528:w=604:h=146:color=0x10161d@0.92:t=fill"
        ),
        "items": [
            {
                "start_time": 0.28,
                "end_time": 1.8,
                "text_final": "关键参数 先讲清楚",
                "style_name": "amber_news",
                "motion_style": "motion_slide",
                "subtitle_section_role": "detail",
                "subtitle_unit_role": "setup",
                "highlight_terms": ["关键参数", "讲清楚"],
            }
        ],
    },
]


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def generate_previews() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to generate style template previews")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="roughcut_style_preview_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for template in TEMPLATES:
            ass_path = tmp_root / f"{template['slug']}.ass"
            output_path = OUTPUT_DIR / f"{template['slug']}.png"
            write_ass_file(
                list(template["items"]),
                ass_path,
                style_name=str(template["style_name"]),
                motion_style=str(template["motion_style"]),
                play_res_x=CANVAS_W,
                play_res_y=CANVAS_H,
            )
            vf = f"{template['background']},subtitles='{escape_path_for_ffmpeg_filter(ass_path)}'"
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0a0d13:s={CANVAS_W}x{CANVAS_H}:d=2.4",
                "-vf",
                vf,
                "-ss",
                f"{float(template['capture_sec']):.2f}",
                "-frames:v",
                "1",
                str(output_path),
            ]
            _run(cmd)
            print(f"generated {output_path.relative_to(ROOT)}")

            compare_ass_path = tmp_root / f"compare-{template['slug']}.ass"
            compare_output_path = OUTPUT_DIR / f"compare-{template['slug']}.png"
            compare_item = {
                **template["items"][0],
                "text_final": COMPARE_TEXT,
                "highlight_terms": ["重点词", "立刻看懂"],
            }
            write_ass_file(
                [compare_item],
                compare_ass_path,
                style_name=str(template["style_name"]),
                motion_style=str(template["motion_style"]),
                play_res_x=CANVAS_W,
                play_res_y=CANVAS_H,
            )
            compare_vf = f"{COMPARE_BACKGROUND},subtitles='{escape_path_for_ffmpeg_filter(compare_ass_path)}'"
            compare_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0a0d13:s={CANVAS_W}x{CANVAS_H}:d=2.4",
                "-vf",
                compare_vf,
                "-ss",
                f"{float(template['capture_sec']):.2f}",
                "-frames:v",
                "1",
                str(compare_output_path),
            ]
            _run(compare_cmd)
            print(f"generated {compare_output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    generate_previews()

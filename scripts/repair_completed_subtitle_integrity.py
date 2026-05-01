from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select

from roughcut.db.models import Artifact, Job, RenderOutput, SubtitleItem
from roughcut.db.session import get_session_factory
from roughcut.media.output import write_srt_file
from roughcut.media.subtitle_text import clean_final_subtitle_text
from roughcut.speech.subtitle_segmentation import normalize_display_numbers
from roughcut.speech.transcribe import _normalize_semantic_contamination_text


DEFAULT_STATUSES = ("done", "needs_review")
MEASURE_UNITS = (
    "流明",
    "厘米",
    "毫米",
    "英寸",
    "分钟",
    "小时",
    "秒",
    "毫升",
    "千克",
    "公斤",
    "lm",
    "lumen",
    "lumens",
    "mAh",
    "Ah",
    "Wh",
    "mm",
    "cm",
    "km",
    "kg",
    "mg",
    "ml",
    "GB",
    "MB",
    "TB",
    "fps",
    "Hz",
)
SPLIT_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d+)?|[零〇幺一二两三四五六七八九十百千万]+)\s*$")
UNIT_START_RE = re.compile(
    rf"^\s*(?P<unit>{'|'.join(re.escape(unit) for unit in sorted(MEASURE_UNITS, key=len, reverse=True))})(?P<tail>.*)$",
    re.IGNORECASE,
)
NUMERIC_APPROX_START_RE = re.compile(r"^\s*多(?:的|度|个|只|把|条|件|款|米|厘米|毫米|流明)?")
NOISE_TOKEN_RE = re.compile(
    r"(?:EnvironmentalSounds|Environmental[_\s-]?Sounds?|BackgroundNoise|"
    r"HumanSounds|Human[_\s-]?Sounds?|Sounds?|Noise|Silence|NoSpeech|Music)",
    re.IGNORECASE,
)
MODEL_ALT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:EDC(?:17|23|37))(?:[\s/、，,]+(?:EDC(?:17|23|37))){2,}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
PROTECTED_PHRASE_RESTORATIONS = (
    ("这都画着", "这都画着呢"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply safe subtitle integrity repairs to completed RoughCut jobs.")
    parser.add_argument("--status", action="append", default=[], help="Job status to include. Defaults to done and needs_review.")
    parser.add_argument("--apply", action="store_true", help="Persist DB and sidecar SRT updates. Without this, only reports changes.")
    parser.add_argument("--rewrite-all-srt", action="store_true", help="Rewrite every discovered rendered SRT through the current serializer.")
    parser.add_argument("--output-json", type=Path, default=ROOT / "output" / "completed-subtitle-integrity-repair.json")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _text_of_item(item: SubtitleItem) -> str:
    return str(item.text_final or item.text_norm or item.text_raw or "").strip()


def _category_for_job(job: Job, profile: dict[str, Any] | None) -> str:
    blob = " ".join(
        str(value or "")
        for value in (
            job.source_name,
            (profile or {}).get("subject_domain"),
            (profile or {}).get("subject_type"),
            (profile or {}).get("subject_model"),
            (profile or {}).get("video_theme"),
            (profile or {}).get("summary"),
        )
    ).lower()
    if any(token in blob for token in ("手电", "电筒", "flashlight", "nitecore", "edc17", "edc23", "edc37", "olight", "掠夺者")):
        return "flashlight"
    return ""


def _latest_artifact_payload(artifacts: list[Artifact], artifact_type: str) -> dict[str, Any]:
    candidates = [item for item in artifacts if item.artifact_type == artifact_type and isinstance(item.data_json, dict)]
    if not candidates:
        return {}
    return dict(max(candidates, key=lambda item: (item.created_at, str(item.id))).data_json or {})


def _render_srt_paths(artifacts: list[Artifact], render_outputs: list[RenderOutput]) -> list[str]:
    paths: list[str] = []
    render_payload = _latest_artifact_payload(artifacts, "render_outputs")
    for key in ("packaged_srt", "plain_srt", "ai_effect_srt", "avatar_srt"):
        value = str(render_payload.get(key) or "").strip()
        if value and value not in paths and Path(value).exists():
            paths.append(value)
    for output in render_outputs:
        output_path = str(output.output_path or "").strip()
        if not output_path:
            continue
        srt_path = str(Path(output_path).with_suffix(".srt"))
        if srt_path not in paths and Path(srt_path).exists():
            paths.append(srt_path)
    return paths


def _parse_srt_time(value: str) -> float:
    match = re.match(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})", value.strip())
    if not match:
        return 0.0
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000.0
    )


def _parse_srt_file(path: str) -> list[dict[str, Any]]:
    content = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    entries: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        entries.append(
            {
                "index": int(lines[0]) if lines[0].isdigit() else len(entries) + 1,
                "start_time": _parse_srt_time(start_raw),
                "end_time": _parse_srt_time(end_raw),
                "text": "".join(lines[2:]).strip(),
            }
        )
    return entries


def _leading_measure_piece(text: str) -> tuple[str, str]:
    match = UNIT_START_RE.match(str(text or "").strip())
    if not match:
        return "", str(text or "").strip()
    unit = match.group("unit")
    tail = str(match.group("tail") or "")
    if unit == "厘米" and tail.startswith("的织带"):
        return f"{unit}的织带", tail[len("的织带"):].strip()
    if unit == "毫米" and tail.startswith("的"):
        noun_match = re.match(r"的[\u4e00-\u9fff]{1,4}(?=(?:跟|和|也|是|，|,|。|$))", tail)
        if noun_match:
            return unit + noun_match.group(0), tail[noun_match.end():].strip()
    return unit, tail.strip()


def _normalize_text(text: str, *, category: str) -> str:
    original = str(text or "").strip()
    result = original
    semantic_normalized = _normalize_semantic_contamination_text(result, category_scope=category)
    if semantic_normalized != result:
        result = semantic_normalized
    if category == "flashlight" and MODEL_ALT_RE.search(result):
        result = _normalize_semantic_contamination_text(result, category_scope="flashlight")
    if "1个" in result:
        result = normalize_display_numbers(result)
    if NOISE_TOKEN_RE.search(result):
        result = clean_final_subtitle_text(result)
    for partial, full in PROTECTED_PHRASE_RESTORATIONS:
        if partial in result and full not in result:
            result = result.replace(partial, full)
    return result.strip()


def _repair_entry_sequence(entries: list[dict[str, Any]], *, category: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repaired = [dict(item) for item in entries]
    changes: list[dict[str, Any]] = []

    for item in repaired:
        original = str(item.get("text") or "").strip()
        normalized = _normalize_text(original, category=category)
        if normalized != original:
            item["text"] = normalized
            changes.append({"kind": "normalize_text", "index": item.get("index"), "before": original, "after": normalized})

    for index in range(len(repaired) - 1):
        left = repaired[index]
        right = repaired[index + 1]
        left_text = str(left.get("text") or "").strip()
        right_text = str(right.get("text") or "").strip()
        if not left_text or not right_text or not SPLIT_NUMBER_RE.search(left_text):
            continue
        stolen, remainder = _leading_measure_piece(right_text)
        if not stolen and NUMERIC_APPROX_START_RE.match(right_text):
            stolen = right_text
            remainder = ""
        if not stolen:
            continue
        before_left = left_text
        before_right = right_text
        left["text"] = _normalize_text(f"{left_text}{stolen}", category=category)
        right["text"] = _normalize_text(remainder, category=category)
        right_duration = max(0.0, float(right["end_time"]) - float(right["start_time"]))
        steal_span = min(max(0.35, 0.08 * len(stolen)), max(0.0, right_duration - 0.18))
        if steal_span > 0:
            boundary = round(float(right["start_time"]) + steal_span, 3)
            left["end_time"] = max(float(left["end_time"]), boundary)
            right["start_time"] = min(float(right["end_time"]), boundary)
        changes.append(
            {
                "kind": "repair_numeric_unit_split",
                "index": left.get("index"),
                "before": f"{before_left} | {before_right}",
                "after": f"{left['text']} | {right['text']}",
            }
        )

    return repaired, changes


def _entry_payload_for_srt(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": index + 1,
            "start_time": float(item.get("start_time") or 0.0),
            "end_time": float(item.get("end_time") or 0.0),
            "text_final": str(item.get("text") or "").strip(),
        }
        for index, item in enumerate(entries)
        if str(item.get("text") or "").strip()
    ]


async def main_async() -> int:
    args = parse_args()
    load_env_file(ROOT / ".env")
    statuses = args.status or list(DEFAULT_STATUSES)
    factory = get_session_factory()
    report: dict[str, Any] = {"applied": bool(args.apply), "jobs": []}

    async with factory() as session:
        jobs = (
            await session.execute(
                select(Job)
                .where(Job.status.in_(statuses))
                .order_by(Job.updated_at.desc())
            )
        ).scalars().all()

        for job in jobs:
            subtitles = (
                await session.execute(
                    select(SubtitleItem).where(SubtitleItem.job_id == job.id).order_by(SubtitleItem.item_index)
                )
            ).scalars().all()
            artifacts = (await session.execute(select(Artifact).where(Artifact.job_id == job.id))).scalars().all()
            render_outputs = (await session.execute(select(RenderOutput).where(RenderOutput.job_id == job.id))).scalars().all()
            profile = _latest_artifact_payload(artifacts, "content_profile") or _latest_artifact_payload(artifacts, "content_profile_final")
            category = _category_for_job(job, profile)

            db_entries = [
                {
                    "index": item.item_index,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "text": _text_of_item(item),
                    "_row": item,
                }
                for item in subtitles
            ]
            repaired_db, db_changes = _repair_entry_sequence(db_entries, category=category)
            if args.apply and db_changes:
                for repaired_entry in repaired_db:
                    row = repaired_entry.get("_row")
                    if row is None:
                        continue
                    row.start_time = float(repaired_entry["start_time"])
                    row.end_time = float(repaired_entry["end_time"])
                    repaired_text = str(repaired_entry.get("text") or "").strip()
                    row.text_final = repaired_text
                    row.text_norm = repaired_text
                    if not repaired_text:
                        row.text_raw = ""

            srt_changes: list[dict[str, Any]] = []
            rewritten_srt_paths: list[str] = []
            for srt_path in _render_srt_paths(artifacts, render_outputs):
                entries = _parse_srt_file(srt_path)
                repaired_srt, changes = _repair_entry_sequence(entries, category=category)
                if changes:
                    srt_changes.append({"path": srt_path, "changes": changes})
                if args.apply and (changes or args.rewrite_all_srt):
                    write_srt_file(_entry_payload_for_srt(repaired_srt), Path(srt_path))
                    rewritten_srt_paths.append(srt_path)

            if db_changes or srt_changes or rewritten_srt_paths:
                report["jobs"].append(
                    {
                        "job_id": str(job.id),
                        "source_name": job.source_name,
                        "category": category,
                        "db_changes": db_changes[:80],
                        "srt_changes": srt_changes,
                        "rewritten_srt_paths": rewritten_srt_paths,
                    }
                )

        if args.apply:
            await session.commit()

    report["job_count"] = len(report["jobs"])
    report["db_change_count"] = sum(len(job["db_changes"]) for job in report["jobs"])
    report["srt_file_change_count"] = sum(len(job["srt_changes"]) for job in report["jobs"])
    report["srt_change_count"] = sum(len(file["changes"]) for job in report["jobs"] for file in job["srt_changes"])
    report["rewritten_srt_file_count"] = sum(len(job.get("rewritten_srt_paths") or []) for job in report["jobs"])
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("applied", "job_count", "db_change_count", "srt_file_change_count", "srt_change_count", "rewritten_srt_file_count")}, ensure_ascii=False, indent=2))
    print(f"output_json={args.output_json}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
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

from roughcut.db.models import Artifact, Job, RenderOutput, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.media.output import write_srt_file
from roughcut.speech.subtitle_segmentation import normalize_display_numbers
from roughcut.speech.transcribe import _normalize_semantic_contamination_text


DEFAULT_STATUSES = ("done", "needs_review")
MEASURE_UNITS = (
    "流明",
    "毫米",
    "厘米",
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
INFO_COUNT_NOUNS = (
    "接口",
    "档位",
    "版本",
    "型号",
    "规格",
    "模式",
    "步骤",
    "配色",
    "模块",
    "尺寸",
)
PROTECTED_SHORT_PHRASES = (
    "我懒得看了",
    "懒得看了",
    "我就不说了",
    "这都画着呢",
    "没啥好说的",
)

MODEL_ALT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<first>[A-Za-z]{1,10}[-_/]?\d{1,6})(?:[\s/、，,]+(?P<next>[A-Za-z]{1,10}[-_/]?\d{1,6})){2,}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
MODEL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,10}[-_/]?\d{1,6})(?![A-Za-z0-9])")
SPLIT_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d+)?|[零〇幺一二两三四五六七八九十百千万]+)\s*$")
UNIT_START_RE = re.compile(
    rf"^\s*(?:{'|'.join(re.escape(unit) for unit in sorted(MEASURE_UNITS, key=len, reverse=True))})(?=$|[\u4e00-\u9fffA-Za-z0-9])",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit completed RoughCut subtitle integrity across DB and rendered SRTs.")
    parser.add_argument("--status", action="append", default=[], help="Job status to include. Defaults to done and needs_review.")
    parser.add_argument("--output-json", type=Path, default=ROOT / "output" / "completed-subtitle-integrity-audit.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "output" / "completed-subtitle-integrity-audit.md")
    parser.add_argument(
        "--write-normalized-db-srt",
        action="store_true",
        help="Write current DB subtitle items as SRT files under output/completed-subtitle-integrity-audit/db_srt.",
    )
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


def _text_of_subtitle(item: SubtitleItem) -> str:
    return str(item.text_final or item.text_norm or item.text_raw or "").strip()


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
    file_path = Path(path)
    if not path or not file_path.exists():
        return []
    content = file_path.read_text(encoding="utf-8-sig", errors="replace")
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


def _db_entries(items: list[SubtitleItem]) -> list[dict[str, Any]]:
    return [
        {
            "index": int(item.item_index),
            "start_time": float(item.start_time or 0.0),
            "end_time": float(item.end_time or 0.0),
            "text": _text_of_subtitle(item),
        }
        for item in sorted(items, key=lambda row: row.item_index)
    ]


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
    if any(token in blob for token in ("背包", "双肩包", "机能包", "狐蝠", "foxbat", "boltboat", "收纳", "胸包")):
        return "bag"
    if any(token in blob for token in ("折刀", "刀", "noc", "mt34", "mt33", "s11")):
        return "knife"
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
        if value and value not in paths:
            paths.append(value)
    for output in render_outputs:
        output_path = str(output.output_path or "").strip()
        if not output_path:
            continue
        srt_path = str(Path(output_path).with_suffix(".srt"))
        if srt_path not in paths:
            paths.append(srt_path)
    return paths


def _add_issue(issues: list[dict[str, Any]], *, kind: str, source: str, severity: str, index: int, text: str, detail: str) -> None:
    issues.append(
        {
            "kind": kind,
            "source": source,
            "severity": severity,
            "index": index,
            "text": text,
            "detail": detail,
        }
    )


def _audit_entries(entries: list[dict[str, Any]], *, source: str, category: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    previous_end = -1.0
    for pos, entry in enumerate(entries):
        index = int(entry.get("index") or pos + 1)
        text = str(entry.get("text") or "").strip()
        start = float(entry.get("start_time") or 0.0)
        end = float(entry.get("end_time") or 0.0)
        duration = end - start

        if end <= start:
            _add_issue(issues, kind="invalid_timestamp", source=source, severity="blocking", index=index, text=text, detail=f"{start:.3f}->{end:.3f}")
        if previous_end >= 0.0 and start < previous_end - 0.001:
            _add_issue(issues, kind="timestamp_overlap", source=source, severity="blocking", index=index, text=text, detail=f"start={start:.3f} previous_end={previous_end:.3f}")
        if duration > 8.0 and len(text) > 18:
            _add_issue(issues, kind="long_subtitle_duration", source=source, severity="warning", index=index, text=text, detail=f"duration={duration:.3f}s")
        if duration > 0 and len(text) / max(duration, 0.001) > 15.0:
            _add_issue(issues, kind="high_chars_per_second", source=source, severity="warning", index=index, text=text, detail=f"cps={len(text) / duration:.1f}")
        previous_end = max(previous_end, end)

        match = MODEL_ALT_RE.search(text)
        if match:
            models = [item.upper().replace("_", "").replace("-", "") for item in MODEL_TOKEN_RE.findall(match.group(0))]
            if len(models) >= 3 or len(set(models)) < len(models):
                _add_issue(issues, kind="model_alt_expansion", source=source, severity="blocking", index=index, text=text, detail=match.group(0))

        if re.search(r"(?<![A-Za-z0-9])EDC(?:17|23|37)\s*/\s*$", text, re.IGNORECASE):
            _add_issue(issues, kind="dangling_model_slash", source=source, severity="blocking", index=index, text=text, detail="subtitle ends with model slash")

        if "1个" in text and not any(text[text.find("1个") + 2 :].startswith(noun) for noun in INFO_COUNT_NOUNS):
            normalized = normalize_display_numbers(text)
            if normalized != text:
                _add_issue(issues, kind="natural_quantity_digit", source=source, severity="warning", index=index, text=text, detail=f"normalized={normalized}")

        if category == "flashlight":
            normalized = _normalize_semantic_contamination_text(text, category_scope="flashlight")
            if normalized != text and MODEL_ALT_RE.search(text):
                _add_issue(issues, kind="flashlight_model_candidate_residue", source=source, severity="blocking", index=index, text=text, detail=f"normalized={normalized}")

        if pos + 1 < len(entries):
            next_text = str(entries[pos + 1].get("text") or "").strip()
            if SPLIT_NUMBER_RE.search(text) and UNIT_START_RE.match(next_text):
                _add_issue(
                    issues,
                    kind="numeric_unit_split",
                    source=source,
                    severity="blocking",
                    index=index,
                    text=f"{text} | {next_text}",
                    detail=f"{index}->{entries[pos + 1].get('index')}",
                )
    return issues


def _audit_missing_protected_phrases(transcripts: list[TranscriptSegment], subtitle_entries: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    subtitle_text = "\n".join(str(item.get("text") or "") for item in subtitle_entries)
    for segment in transcripts:
        text = str(segment.text or "")
        for phrase in PROTECTED_SHORT_PHRASES:
            if phrase in text and phrase not in subtitle_text:
                _add_issue(
                    issues,
                    kind="protected_phrase_missing_from_subtitle",
                    source=source,
                    severity="blocking",
                    index=int(segment.segment_index),
                    text=text,
                    detail=phrase,
                )
    return issues


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for issue in issues:
        key = (str(issue.get("kind")), str(issue.get("source")), int(issue.get("index") or 0), str(issue.get("text")))
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


async def _load_jobs(statuses: list[str]) -> list[tuple[Job, list[SubtitleItem], list[TranscriptSegment], list[Artifact], list[RenderOutput]]]:
    factory = get_session_factory()
    async with factory() as session:
        jobs = (
            await session.execute(
                select(Job)
                .where(Job.status.in_(statuses))
                .order_by(Job.updated_at.desc())
            )
        ).scalars().all()
        result = []
        for job in jobs:
            subtitles = (
                await session.execute(
                    select(SubtitleItem).where(SubtitleItem.job_id == job.id).order_by(SubtitleItem.item_index)
                )
            ).scalars().all()
            transcripts = (
                await session.execute(
                    select(TranscriptSegment).where(TranscriptSegment.job_id == job.id).order_by(TranscriptSegment.segment_index)
                )
            ).scalars().all()
            artifacts = (await session.execute(select(Artifact).where(Artifact.job_id == job.id))).scalars().all()
            render_outputs = (await session.execute(select(RenderOutput).where(RenderOutput.job_id == job.id))).scalars().all()
            result.append((job, subtitles, transcripts, artifacts, render_outputs))
        return result


def _write_db_srt(job: Job, entries: list[dict[str, Any]]) -> str:
    output_dir = ROOT / "output" / "completed-subtitle-integrity-audit" / "db_srt"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{job.id}.srt"
    write_srt_file(
        [
            {
                "index": item["index"],
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "text_final": item["text"],
            }
            for item in entries
        ],
        path,
    )
    return str(path)


async def main_async() -> int:
    args = parse_args()
    load_env_file(ROOT / ".env")
    statuses = args.status or list(DEFAULT_STATUSES)
    rows = await _load_jobs(statuses)
    jobs_report: list[dict[str, Any]] = []
    global_counts: Counter[str] = Counter()

    for job, subtitles, transcripts, artifacts, render_outputs in rows:
        profile = _latest_artifact_payload(artifacts, "content_profile") or _latest_artifact_payload(artifacts, "content_profile_final")
        category = _category_for_job(job, profile)
        db_entries = _db_entries(subtitles)
        issues = _audit_entries(db_entries, source="db_subtitles", category=category)
        issues.extend(_audit_missing_protected_phrases(transcripts, db_entries, source="db_subtitles"))

        db_srt_path = _write_db_srt(job, db_entries) if args.write_normalized_db_srt else ""
        srt_reports: list[dict[str, Any]] = []
        for srt_path in _render_srt_paths(artifacts, render_outputs):
            srt_entries = _parse_srt_file(srt_path)
            if not srt_entries:
                continue
            srt_issues = _audit_entries(srt_entries, source=f"srt:{srt_path}", category=category)
            srt_issues.extend(_audit_missing_protected_phrases(transcripts, srt_entries, source=f"srt:{srt_path}"))
            issues.extend(srt_issues)
            srt_reports.append({"path": srt_path, "entry_count": len(srt_entries), "issue_count": len(srt_issues)})

        deduped = _dedupe_issues(issues)
        for issue in deduped:
            global_counts[str(issue.get("kind"))] += 1
        blocking = [item for item in deduped if item.get("severity") == "blocking"]
        warnings = [item for item in deduped if item.get("severity") != "blocking"]
        jobs_report.append(
            {
                "job_id": str(job.id),
                "source_name": job.source_name,
                "status": job.status,
                "category": category,
                "db_subtitle_count": len(db_entries),
                "transcript_count": len(transcripts),
                "db_srt_path": db_srt_path,
                "render_srt": srt_reports,
                "blocking_count": len(blocking),
                "warning_count": len(warnings),
                "issues": deduped[:80],
            }
        )

    report = {
        "statuses": statuses,
        "job_count": len(jobs_report),
        "issue_counts": dict(global_counts),
        "jobs_with_blocking": sum(1 for item in jobs_report if item["blocking_count"]),
        "jobs_with_warnings": sum(1 for item in jobs_report if item["warning_count"]),
        "jobs": jobs_report,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("job_count", "issue_counts", "jobs_with_blocking", "jobs_with_warnings")}, ensure_ascii=False, indent=2))
    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    return 0


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Completed Subtitle Integrity Audit",
        "",
        f"- statuses: {', '.join(report['statuses'])}",
        f"- job_count: {report['job_count']}",
        f"- jobs_with_blocking: {report['jobs_with_blocking']}",
        f"- jobs_with_warnings: {report['jobs_with_warnings']}",
        f"- issue_counts: `{json.dumps(report['issue_counts'], ensure_ascii=False)}`",
        "",
    ]
    for job in report["jobs"]:
        if not job["blocking_count"] and not job["warning_count"]:
            continue
        lines.append(f"## {job['source_name']}")
        lines.append(f"- job_id: `{job['job_id']}`")
        lines.append(f"- status/category: `{job['status']}` / `{job['category']}`")
        lines.append(f"- issues: blocking={job['blocking_count']}, warning={job['warning_count']}")
        for issue in job["issues"][:16]:
            lines.append(
                f"  - [{issue['severity']}] {issue['kind']} @ {issue['source']} #{issue['index']}: {issue['text']} ({issue['detail']})"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())

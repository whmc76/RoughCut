from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_KEYWORDS = [
    "LuckyKiss",
    "KissPod",
    "KISSPORT",
    "益倍萃",
    "含片",
    "益生菌",
    "弹射",
    "零糖",
    "口气",
]
PROFILE_PRIORITY = ["content_profile_final", "content_profile", "content_profile_draft"]
FOOD_SIGNALS = ["luckykiss", "kisspod", "kissport", "含片", "益生菌", "零糖", "口气", "薄荷糖"]
GEAR_SIGNALS = ["工具钳", "战术笔", "弹夹", "装备", "莱德曼", "edc"]
DELIVERABLE_STEPS = ["summary_review", "final_review", "render", "platform_package"]


@dataclass
class TextHit:
    index: int
    start_time: float
    end_time: float
    text: str
    matched_keywords: dict[str, int]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a RoughCut job audit snapshot for transcript, content profile, and step cross-checking."
    )
    parser.add_argument("--job-id", required=True, help="Target RoughCut job UUID.")
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=DEFAULT_KEYWORDS,
        help="Keywords used to flag transcript and subtitle hits.",
    )
    parser.add_argument(
        "--locate-root",
        action="append",
        default=[],
        help="Optional local/shared directory to search for the original source filename.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "output" / "job-audit-snapshot.json",
        help="Where to write the JSON snapshot.",
    )
    return parser.parse_args()


def compact_text(value: Any, limit: int = 220) -> str:
    text_value = " ".join(str(value or "").split())
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 3] + "..."


def keyword_counts(text_value: str, keywords: list[str]) -> dict[str, int]:
    lowered = str(text_value or "").lower()
    matches: dict[str, int] = {}
    for keyword in keywords:
        needle = str(keyword or "").strip().lower()
        if not needle:
            continue
        count = lowered.count(needle)
        if count > 0:
            matches[keyword] = count
    return matches


def locate_source_paths(source_name: str, roots: list[str]) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root)
        if not root.exists():
            continue
        try:
            iterator = root.rglob(source_name)
        except OSError:
            continue
        for candidate in iterator:
            if not candidate.is_file():
                continue
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(resolved)
    matches.sort()
    return matches


def build_hits(
    rows: list[dict[str, Any]],
    *,
    index_key: str,
    text_key: str,
    keywords: list[str],
) -> list[TextHit]:
    hits: list[TextHit] = []
    for row in rows:
        row_text = str(row.get(text_key) or "")
        matches = keyword_counts(row_text, keywords)
        if not matches:
            continue
        hits.append(
            TextHit(
                index=int(row.get(index_key) or 0),
                start_time=float(row.get("start_time") or 0.0),
                end_time=float(row.get("end_time") or 0.0),
                text=row_text,
                matched_keywords=matches,
            )
        )
    return hits


def select_active_profile(artifacts: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    artifact_map = {str(item["artifact_type"]): item for item in artifacts}
    for artifact_type in PROFILE_PRIORITY:
        artifact = artifact_map.get(artifact_type)
        data_json = artifact.get("data_json") if artifact else None
        if isinstance(data_json, dict) and data_json:
            return artifact_type, data_json
    return None, {}


def build_heuristics(
    *,
    active_profile: dict[str, Any],
    transcript_hits: list[TextHit],
    step_map: dict[str, str],
    artifact_counts: dict[str, int],
    keywords: list[str],
) -> dict[str, Any]:
    profile_text = " ".join(
        [
            str(active_profile.get("subject_type") or ""),
            str(active_profile.get("subject_brand") or ""),
            str(active_profile.get("subject_model") or ""),
            str(active_profile.get("summary") or ""),
            str(active_profile.get("video_theme") or ""),
        ]
    ).strip()
    profile_keyword_hits = keyword_counts(profile_text, keywords)
    transcript_blob = " ".join(hit.text for hit in transcript_hits).lower()
    profile_blob = profile_text.lower()
    food_signal_present = any(signal in transcript_blob for signal in FOOD_SIGNALS)
    gear_signal_in_profile = any(signal in profile_blob for signal in GEAR_SIGNALS)
    food_signal_in_profile = any(signal in profile_blob for signal in FOOD_SIGNALS)

    issues: list[str] = []
    if food_signal_present and gear_signal_in_profile and not food_signal_in_profile:
        issues.append("content_profile subjects the video as gear/EDC while transcript evidence points to an ingestible lozenge product")
    if transcript_hits and not profile_keyword_hits:
        issues.append("target product keywords appear in transcript/subtitle evidence but not in the current content_profile summary fields")
    for step_name in DELIVERABLE_STEPS:
        if step_map.get(step_name) not in {"done", "skipped"}:
            issues.append(f"{step_name} has not produced a completed deliverable yet")
    if artifact_counts.get("content_profile_final", 0) == 0:
        issues.append("content_profile_final is missing")

    return {
        "profile_keyword_hits": profile_keyword_hits,
        "food_signal_present": food_signal_present,
        "food_signal_in_profile": food_signal_in_profile,
        "gear_signal_in_profile": gear_signal_in_profile,
        "issues": issues,
    }


async def export_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")

    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:
            job_row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, source_name, source_path, status, created_at, updated_at
                        FROM jobs
                        WHERE id = :job_id
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().first()
            if job_row is None:
                raise RuntimeError(f"Job not found: {args.job_id}")

            step_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT step_name, status, attempt, started_at, finished_at, metadata
                        FROM job_steps
                        WHERE job_id = :job_id
                        ORDER BY started_at NULLS FIRST, finished_at NULLS FIRST, step_name
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()

            artifact_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT artifact_type, created_at, data_json
                        FROM artifacts
                        WHERE job_id = :job_id
                        ORDER BY created_at
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()

            transcript_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT segment_index, start_time, end_time, text
                        FROM transcript_segments
                        WHERE job_id = :job_id
                        ORDER BY segment_index
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()

            subtitle_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT item_index, start_time, end_time, COALESCE(text_final, text_norm, text_raw) AS text
                        FROM subtitle_items
                        WHERE job_id = :job_id
                        ORDER BY item_index
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()

            correction_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT original_span, suggested_span, change_type, confidence, source, auto_applied, human_decision
                        FROM subtitle_corrections
                        WHERE job_id = :job_id
                        ORDER BY confidence DESC, created_at DESC
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()

            review_action_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT target_type, target_id, action, override_text, created_at
                        FROM review_actions
                        WHERE job_id = :job_id
                        ORDER BY created_at
                        """
                    ),
                    {"job_id": args.job_id},
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    transcript_hits = build_hits(
        [dict(row) for row in transcript_rows],
        index_key="segment_index",
        text_key="text",
        keywords=list(args.keywords),
    )
    subtitle_hits = build_hits(
        [dict(row) for row in subtitle_rows],
        index_key="item_index",
        text_key="text",
        keywords=list(args.keywords),
    )
    step_map = {str(row["step_name"]): str(row["status"]) for row in step_rows}
    artifact_counts = Counter(str(row["artifact_type"]) for row in artifact_rows)
    active_profile_type, active_profile = select_active_profile([dict(row) for row in artifact_rows])
    heuristics = build_heuristics(
        active_profile=active_profile,
        transcript_hits=transcript_hits,
        step_map=step_map,
        artifact_counts=dict(artifact_counts),
        keywords=list(args.keywords),
    )

    source_name = str(job_row["source_name"])
    located_paths = locate_source_paths(source_name, list(args.locate_root))

    snapshot = {
        "job": {
            "id": str(job_row["id"]),
            "source_name": source_name,
            "source_path": str(job_row["source_path"]),
            "status": str(job_row["status"]),
            "created_at": str(job_row["created_at"]),
            "updated_at": str(job_row["updated_at"]),
            "located_paths": located_paths,
        },
        "step_status": [
            {
                "step_name": str(row["step_name"]),
                "status": str(row["status"]),
                "attempt": int(row["attempt"] or 0),
                "started_at": str(row["started_at"] or ""),
                "finished_at": str(row["finished_at"] or ""),
                "detail": compact_text((row.get("metadata") or {}).get("detail") if isinstance(row.get("metadata"), dict) else ""),
            }
            for row in step_rows
        ],
        "artifacts": {
            "counts": dict(artifact_counts),
            "active_profile_type": active_profile_type,
            "active_profile_summary": {
                "subject_type": str(active_profile.get("subject_type") or ""),
                "subject_brand": str(active_profile.get("subject_brand") or ""),
                "subject_model": str(active_profile.get("subject_model") or ""),
                "summary": str(active_profile.get("summary") or ""),
                "hook_line": str(active_profile.get("hook_line") or ""),
            },
        },
        "transcript_hits": [asdict(hit) for hit in transcript_hits],
        "subtitle_hits": [asdict(hit) for hit in subtitle_hits],
        "subtitle_corrections": [
            {
                "original_span": str(row["original_span"]),
                "suggested_span": str(row["suggested_span"]),
                "change_type": str(row["change_type"]),
                "confidence": float(row["confidence"] or 0.0),
                "source": str(row["source"] or ""),
                "auto_applied": bool(row["auto_applied"]),
                "human_decision": str(row["human_decision"] or ""),
            }
            for row in correction_rows
        ],
        "review_actions": [
            {
                "target_type": str(row["target_type"]),
                "target_id": str(row["target_id"]),
                "action": str(row["action"]),
                "override_text": str(row["override_text"] or ""),
                "created_at": str(row["created_at"]),
            }
            for row in review_action_rows
        ],
        "heuristics": heuristics,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def main() -> None:
    args = parse_args()
    snapshot = asyncio.run(export_snapshot(args))
    print(
        json.dumps(
            {
                "job_id": snapshot["job"]["id"],
                "source_name": snapshot["job"]["source_name"],
                "status": snapshot["job"]["status"],
                "located_paths": snapshot["job"]["located_paths"],
                "active_profile_type": snapshot["artifacts"]["active_profile_type"],
                "active_profile_summary": snapshot["artifacts"]["active_profile_summary"],
                "transcript_hit_count": len(snapshot["transcript_hits"]),
                "subtitle_hit_count": len(snapshot["subtitle_hits"]),
                "issues": snapshot["heuristics"]["issues"],
                "output_json": str(args.output_json),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from roughcut.api.jobs import _build_manual_editor_readiness
from roughcut.db.models import Job
from roughcut.db.session import get_session_factory

TARGET_RENDER_REASONS = (
    "ffmpeg_render_failed",
    "ffmpeg_packaging_failed",
    "render_ffprobe_failed",
    "avatar_full_track_provider_response_error",
    "avatar_full_track_busy_exhausted",
    "avatar_full_track_slot_timeout",
)


@dataclass(slots=True)
class ManualEditorCandidate:
    job_id: str
    source_name: str
    created_at: str
    job_status: str
    readiness_status: str
    can_open_editor: bool
    can_edit: bool
    current_step: str | None
    missing: list[str]
    detail: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List current real-job candidates for final refactor evidence capture."
    )
    parser.add_argument(
        "--mode",
        choices=("all", "manual_editor", "render_failure"),
        default="all",
        help="Which candidate surface to list.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many recent jobs to inspect.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of text.",
    )
    return parser.parse_args()


def _iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


async def _load_recent_jobs(limit: int) -> list[Job]:
    factory = get_session_factory()
    async with factory() as session:
        rows = await session.execute(
            select(Job)
            .options(selectinload(Job.steps))
            .where(Job.source_name.is_not(None))
            .order_by(Job.created_at.desc())
            .limit(max(1, int(limit or 20)))
        )
        return list(rows.scalars().all())


async def _list_manual_editor_candidates(limit: int) -> list[dict[str, Any]]:
    jobs = await _load_recent_jobs(limit)
    factory = get_session_factory()
    candidates: list[dict[str, Any]] = []
    async with factory() as session:
        for job in jobs:
            readiness = await _build_manual_editor_readiness(job=job, session=session)
            if not readiness.can_open_editor:
                continue
            candidates.append(
                asdict(
                    ManualEditorCandidate(
                        job_id=str(job.id),
                        source_name=str(job.source_name or ""),
                        created_at=_iso8601(job.created_at),
                        job_status=str(job.status or ""),
                        readiness_status=str(readiness.status or ""),
                        can_open_editor=bool(readiness.can_open_editor),
                        can_edit=bool(readiness.can_edit),
                        current_step=readiness.current_step,
                        missing=list(readiness.missing or []),
                        detail=readiness.detail,
                    )
                )
            )
    return candidates


async def _list_render_failure_candidates(limit: int) -> list[dict[str, Any]]:
    factory = get_session_factory()
    sql = text(
        """
WITH recent_jobs AS (
    SELECT id, source_name, created_at
    FROM jobs
    WHERE source_name IS NOT NULL
    ORDER BY created_at DESC
    LIMIT :limit
)
SELECT a.job_id::text AS job_id,
       r.source_name,
       r.created_at AS job_created_at,
       a.artifact_type,
       a.created_at AS artifact_created_at,
       CASE
           WHEN a.data_json::text ILIKE '%ffmpeg_render_failed%' THEN 'ffmpeg_render_failed'
           WHEN a.data_json::text ILIKE '%ffmpeg_packaging_failed%' THEN 'ffmpeg_packaging_failed'
           WHEN a.data_json::text ILIKE '%render_ffprobe_failed%' THEN 'render_ffprobe_failed'
           WHEN a.data_json::text ILIKE '%avatar_full_track_provider_response_error%' THEN 'avatar_full_track_provider_response_error'
           WHEN a.data_json::text ILIKE '%avatar_full_track_busy_exhausted%' THEN 'avatar_full_track_busy_exhausted'
           WHEN a.data_json::text ILIKE '%avatar_full_track_slot_timeout%' THEN 'avatar_full_track_slot_timeout'
           ELSE ''
       END AS matched_reason
FROM recent_jobs r
JOIN artifacts a ON a.job_id = r.id
WHERE a.artifact_type IN ('render_runtime_diagnostics', 'quality_assessment', 'render_outputs')
  AND (
      a.data_json::text ILIKE '%ffmpeg_render_failed%'
   OR a.data_json::text ILIKE '%ffmpeg_packaging_failed%'
   OR a.data_json::text ILIKE '%render_ffprobe_failed%'
   OR a.data_json::text ILIKE '%avatar_full_track_provider_response_error%'
   OR a.data_json::text ILIKE '%avatar_full_track_busy_exhausted%'
   OR a.data_json::text ILIKE '%avatar_full_track_slot_timeout%'
  )
ORDER BY a.created_at DESC
        """
    )
    async with factory() as session:
        rows = (await session.execute(sql, {"limit": max(1, int(limit or 20))})).mappings().all()
        return [
            {
                "job_id": str(row.get("job_id") or ""),
                "source_name": str(row.get("source_name") or ""),
                "job_created_at": _iso8601(row.get("job_created_at")),
                "artifact_type": str(row.get("artifact_type") or ""),
                "artifact_created_at": _iso8601(row.get("artifact_created_at")),
                "matched_reason": str(row.get("matched_reason") or ""),
            }
            for row in rows
            if str(row.get("matched_reason") or "") in TARGET_RENDER_REASONS
        ]


def _render_text(
    *,
    manual_editor_candidates: list[dict[str, Any]] | None = None,
    render_failure_candidates: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    if manual_editor_candidates is not None:
        lines.append(f"## manual_editor_candidates count={len(manual_editor_candidates)}")
        for item in manual_editor_candidates:
            lines.append(
                f"- {item['job_id']} | {item['source_name']} | job_status={item['job_status']} "
                f"| readiness={item['readiness_status']} | can_edit={item['can_edit']}"
            )
    if render_failure_candidates is not None:
        lines.append(f"## render_failure_candidates count={len(render_failure_candidates)}")
        for item in render_failure_candidates:
            lines.append(
                f"- {item['job_id']} | {item['source_name']} | artifact={item['artifact_type']} "
                f"| matched_reason={item['matched_reason']}"
            )
    return "\n".join(lines).strip()


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if args.mode in {"all", "manual_editor"}:
        result["manual_editor_candidates"] = await _list_manual_editor_candidates(args.limit)
    if args.mode in {"all", "render_failure"}:
        result["render_failure_candidates"] = await _list_render_failure_candidates(args.limit)
    return result


def main() -> int:
    args = parse_args()
    result = asyncio.run(_main_async(args))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            _render_text(
                manual_editor_candidates=result.get("manual_editor_candidates"),
                render_failure_candidates=result.get("render_failure_candidates"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

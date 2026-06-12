from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from roughcut.api.jobs import (
    ManualEditorApplyIn,
    _build_manual_editor_readiness,
    _build_manual_editor_session,
    _load_latest_timeline_by_type,
    apply_manual_editor_timeline,
)
from roughcut.db.models import Job
from roughcut.db.session import get_session_factory
from scripts.list_final_evidence_candidates import _list_manual_editor_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture one real manual-editor no-material-change apply sample."
    )
    parser.add_argument("--job-id", default="", help="Explicit job id to use.")
    parser.add_argument(
        "--source-name",
        default="",
        help="Use the latest job with this source name when job id is omitted.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Candidate search window when no explicit job is provided.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run the no-op manual-editor apply. Without this flag, only print the candidate payload.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args()


def _segment_payloads(items: list[Any]) -> list[dict[str, float]]:
    payloads: list[dict[str, float]] = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            raw = item.model_dump(include={"start", "end"})
        else:
            raw = dict(item or {})
        payloads.append(
            {
                "start": round(float(raw.get("start", 0.0) or 0.0), 3),
                "end": round(float(raw.get("end", 0.0) or 0.0), 3),
            }
        )
    return payloads


def _build_no_material_change_request_payload(session_payload: Any) -> dict[str, Any]:
    return {
        "keep_segments": _segment_payloads(list(getattr(session_payload, "base_keep_segments", []) or [])),
        "subtitle_overrides": [],
        "subtitle_replacements": [],
        "video_transform": (
            getattr(session_payload, "base_video_transform", None).model_dump()
            if getattr(session_payload, "base_video_transform", None) is not None
            else None
        ),
        "smart_cut_rules": dict(getattr(session_payload, "smart_cut_rules", None) or {}) or None,
        "video_summary": getattr(session_payload, "base_video_summary", None),
        "base_timeline_id": str(getattr(session_payload, "timeline_id", "") or ""),
        "base_timeline_version": int(getattr(session_payload, "timeline_version", 0) or 0),
        "base_render_plan_version": int(getattr(session_payload, "render_plan_version", 0) or 0),
        "base_subtitle_fingerprint": str(getattr(session_payload, "subtitle_fingerprint", "") or ""),
        "note": "codex_capture_no_material_change",
    }


async def _resolve_job(args: argparse.Namespace) -> Job:
    factory = get_session_factory()
    async with factory() as session:
        normalized_job_id = str(args.job_id or "").strip()
        normalized_source_name = str(args.source_name or "").strip()
        if normalized_job_id:
            job = (
                await session.execute(
                    select(Job).options(selectinload(Job.steps)).where(Job.id == uuid.UUID(normalized_job_id))
                )
            ).scalar_one_or_none()
            if job is None:
                raise RuntimeError(f"job not found: {normalized_job_id}")
            return job
        if normalized_source_name:
            job = (
                await session.execute(
                    select(Job)
                    .options(selectinload(Job.steps))
                    .where(Job.source_name == normalized_source_name)
                    .order_by(Job.created_at.desc())
                )
            ).scalars().first()
            if job is None:
                raise RuntimeError(f"job not found by source_name: {normalized_source_name}")
            return job
        candidates = await _list_manual_editor_candidates(args.limit)
        if not candidates:
            raise RuntimeError("no manual-editor candidates found")
        candidate_job_id = str(candidates[0]["job_id"])
        job = (
            await session.execute(
                select(Job).options(selectinload(Job.steps)).where(Job.id == uuid.UUID(candidate_job_id))
            )
        ).scalar_one_or_none()
        if job is None:
            raise RuntimeError(f"candidate job not found: {candidate_job_id}")
        return job


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    job = await _resolve_job(args)
    factory = get_session_factory()
    async with factory() as session:
        job = (
            await session.execute(
                select(Job).options(selectinload(Job.steps)).where(Job.id == job.id)
            )
        ).scalar_one()
        readiness = await _build_manual_editor_readiness(job=job, session=session)
        session_payload = await _build_manual_editor_session(job=job, session=session)
        request_payload = _build_no_material_change_request_payload(session_payload)
        result: dict[str, Any] = {
            "job_id": str(job.id),
            "source_name": str(job.source_name or ""),
            "readiness_status": str(readiness.status or ""),
            "can_open_editor": bool(readiness.can_open_editor),
            "can_edit": bool(readiness.can_edit),
            "request_payload": request_payload,
            "applied": False,
        }
        if not args.apply:
            return result
        if not readiness.can_edit:
            raise RuntimeError(f"job is not editable: {readiness.detail or readiness.status}")
        apply_request = ManualEditorApplyIn(**request_payload)
        apply_response = await apply_manual_editor_timeline(job.id, apply_request, session=session)
        latest_editorial = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
        latest_render_plan = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
        result["applied"] = True
        result["apply_response"] = apply_response.model_dump()
        result["latest_editorial_manual_editor"] = (
            (((latest_editorial.data_json or {}).get("analysis") or {}).get("manual_editor") or {})
            if latest_editorial is not None and isinstance(latest_editorial.data_json, dict)
            else {}
        )
        result["latest_render_plan_manual_editor"] = (
            ((latest_render_plan.data_json or {}).get("manual_editor") or {})
            if latest_render_plan is not None and isinstance(latest_render_plan.data_json, dict)
            else {}
        )
        return result


def main() -> int:
    args = parse_args()
    result = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "job_id": result.get("job_id"),
                    "source_name": result.get("source_name"),
                    "readiness_status": result.get("readiness_status"),
                    "can_edit": result.get("can_edit"),
                    "applied": result.get("applied"),
                    "apply_response": result.get("apply_response"),
                    "latest_editorial_manual_editor": result.get("latest_editorial_manual_editor"),
                    "latest_render_plan_manual_editor": result.get("latest_render_plan_manual_editor"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

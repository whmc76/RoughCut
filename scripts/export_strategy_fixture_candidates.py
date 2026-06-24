from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("TELEGRAM_REMOTE_REVIEW_ENABLED", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from scripts.build_strategy_replay_fixture_manifest import strategy_required_checks
from roughcut.db.models import Artifact, Job
from roughcut.db.session import get_session_factory
from roughcut.edit.strategy_profile import DEFAULT_STRATEGY_TYPE, normalize_strategy_type
from roughcut.review.content_profile_strategy import attach_content_profile_capability_orchestration


DEFAULT_REQUIRED_STRATEGIES = (
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
)
DEFAULT_PROFILE_ARTIFACT_TYPES = (
    "content_profile_final",
    "downstream_context",
    "content_profile",
    "content_profile_draft",
)
STRATEGY_FIXTURE_CANDIDATES_SCHEMA = "strategy_fixture_candidates.v1"
STRATEGY_CANDIDATE_MANIFEST_SCHEMA = "strategy_candidate_golden_manifest.v1"


def normalize_strategy_fixture_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    strategy_type = normalize_strategy_type(raw.get("strategy_type"))
    if not strategy_type:
        strategy_type = DEFAULT_STRATEGY_TYPE
    job_id = str(raw.get("job_id") or "").strip()
    if not job_id:
        return None
    classification = raw.get("classification") if isinstance(raw.get("classification"), dict) else {}
    pipeline_plan = raw.get("pipeline_plan") if isinstance(raw.get("pipeline_plan"), dict) else {}
    local_asset_inventory = raw.get("local_asset_inventory") if isinstance(raw.get("local_asset_inventory"), dict) else {}
    replay_context = raw.get("replay_context") if isinstance(raw.get("replay_context"), dict) else {}
    real_render_context = raw.get("real_render_context") if isinstance(raw.get("real_render_context"), dict) else {}
    confidence = _float_value(classification.get("confidence"))
    source_name = str(raw.get("source_name") or "").strip()
    status = str(raw.get("status") or "").strip()
    artifact_type = str(raw.get("artifact_type") or "").strip()
    language = str(raw.get("language") or "").strip()
    enabled_features = _string_list(pipeline_plan.get("enabled_features"))
    review_gates = _string_list(pipeline_plan.get("review_gates"))
    tags = [f"strategy:{strategy_type}", "strategy_candidate"]
    if artifact_type:
        tags.append(f"artifact:{artifact_type}")
    replay_safety = _candidate_replay_safety(
        strategy_type=strategy_type,
        source_name=source_name,
        workflow_template=str(raw.get("workflow_template") or "").strip(),
        replay_context=replay_context,
    )
    return {
        "job_id": job_id,
        "artifact_id": str(raw.get("artifact_id") or "").strip(),
        "artifact_type": artifact_type,
        "artifact_created_at": str(raw.get("artifact_created_at") or "").strip(),
        "source_name": source_name,
        "status": status,
        "workflow_template": str(raw.get("workflow_template") or "").strip(),
        "language": language,
        "strategy_type": strategy_type,
        "classification": {
            "primary_type": str(classification.get("primary_type") or "").strip(),
            "production_mode": str(classification.get("production_mode") or "").strip(),
            "content_tags": _string_list(classification.get("content_tags")),
            "media_tags": _string_list(classification.get("media_tags")),
            "editing_signals": _string_list(classification.get("editing_signals")),
            "asset_tags": _string_list(classification.get("asset_tags")),
            "confidence": confidence,
        },
        "pipeline_plan": {
            "enabled_features": enabled_features,
            "review_gates": review_gates,
            "reason_codes": _string_list(pipeline_plan.get("reason_codes")),
            "requires_operator_confirmation": bool(pipeline_plan.get("requires_operator_confirmation")),
        },
        "local_asset_inventory": {
            "primary_video_count": _int_value(local_asset_inventory.get("primary_video_count")),
            "auxiliary_video_count": _int_value(local_asset_inventory.get("auxiliary_video_count")),
            "image_count": _int_value(local_asset_inventory.get("image_count")),
            "audio_count": _int_value(local_asset_inventory.get("audio_count")),
            "multi_material_ready": bool(local_asset_inventory.get("multi_material_ready")),
        },
        "replay_safety": replay_safety,
        "real_render_readiness": _candidate_real_render_readiness(real_render_context),
        "score": _candidate_score(
            confidence=confidence,
            status=status,
            artifact_type=artifact_type,
            enabled_features=enabled_features,
            review_gates=review_gates,
            local_asset_inventory=local_asset_inventory,
            real_render_ready=bool(_candidate_real_render_readiness(real_render_context).get("ready")),
        ),
        "golden_manifest_case": {
            "case_id": _case_id_for_candidate(strategy_type=strategy_type, job_id=job_id, source_name=source_name),
            "scenario": f"strategy fixture candidate for {strategy_type}: {source_name or job_id}",
            "reference_job_id": job_id,
            "enhancement_modes": [],
            **({"language": language} if language else {}),
            "tags": tags,
            "required_checks": strategy_required_checks(strategy_type),
            "risk_hints": {"expected_strategy_type": strategy_type},
            "notes": "Generated by export_strategy_fixture_candidates.py; promote only after the reference job is validated.",
        },
    }


def select_strategy_fixture_candidates(
    candidates: list[dict[str, Any]],
    *,
    required_strategies: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_STRATEGIES,
    per_strategy: int = 1,
    excluded_job_ids: set[str] | None = None,
    excluded_case_ids: set[str] | None = None,
    excluded_source_names: set[str] | None = None,
) -> dict[str, Any]:
    normalized_required = [normalize_strategy_type(item) for item in required_strategies if str(item or "").strip()]
    excluded_job_ids = {str(item or "").strip() for item in (excluded_job_ids or set()) if str(item or "").strip()}
    excluded_case_ids = {str(item or "").strip() for item in (excluded_case_ids or set()) if str(item or "").strip()}
    excluded_source_names = {
        str(item or "").strip().lower() for item in (excluded_source_names or set()) if str(item or "").strip()
    }
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded_candidates: list[dict[str, str]] = []
    for candidate in candidates:
        normalized = normalize_strategy_fixture_candidate(candidate)
        if not normalized:
            continue
        case_id = str((normalized.get("golden_manifest_case") or {}).get("case_id") or "").strip()
        job_id = str(normalized.get("job_id") or "").strip()
        source_name = str(normalized.get("source_name") or "").strip()
        exclusion_reasons: list[str] = []
        if job_id in excluded_job_ids:
            exclusion_reasons.append("excluded_job_id")
        if case_id in excluded_case_ids:
            exclusion_reasons.append("excluded_case_id")
        if source_name.lower() in excluded_source_names:
            exclusion_reasons.append("excluded_source_name")
        if exclusion_reasons:
            excluded_candidates.append(
                {
                    "strategy_type": str(normalized.get("strategy_type") or ""),
                    "case_id": case_id,
                    "job_id": job_id,
                    "source_name": source_name,
                    "reason": ",".join(exclusion_reasons),
                }
            )
            continue
        buckets[str(normalized["strategy_type"])].append(normalized)

    selected: dict[str, list[dict[str, Any]]] = {}
    for strategy_type, items in buckets.items():
        deduped_by_job: dict[str, dict[str, Any]] = {}
        for item in items:
            job_id = str(item.get("job_id") or "")
            current = deduped_by_job.get(job_id)
            if current is None or _float_value(item.get("score")) > _float_value(current.get("score")):
                deduped_by_job[job_id] = item
        selected[strategy_type] = sorted(
            deduped_by_job.values(),
            key=lambda item: (
                bool((item.get("replay_safety") or {}).get("safe")),
                bool((item.get("real_render_readiness") or {}).get("ready")),
                _float_value(item.get("score")),
                str(item.get("artifact_created_at") or ""),
                str(item.get("job_id") or ""),
            ),
            reverse=True,
        )[: max(1, int(per_strategy or 1))]

    covered = sorted(strategy for strategy in normalized_required if selected.get(strategy))
    missing = sorted(strategy for strategy in normalized_required if not selected.get(strategy))
    manifest_jobs: list[dict[str, Any]] = []
    manifest_ready: list[str] = []
    manifest_missing: list[str] = []
    duplicate_reference_conflicts: list[dict[str, Any]] = []
    replay_unsafe_candidates: list[dict[str, Any]] = []
    used_job_ids: set[str] = set()
    manifest_ready_by_strategy: dict[str, bool] = {}
    real_render_ready_by_strategy: dict[str, bool] = {}
    for strategy in normalized_required:
        picked: dict[str, Any] | None = None
        conflicting: list[dict[str, str]] = []
        for candidate in selected.get(strategy, []):
            job_id = str(candidate.get("job_id") or "")
            replay_safety = candidate.get("replay_safety") if isinstance(candidate.get("replay_safety"), dict) else {}
            if not bool(replay_safety.get("safe")):
                replay_unsafe_candidates.append(
                    {
                        "strategy_type": strategy,
                        "reference_job_id": job_id,
                        "case_id": str((candidate.get("golden_manifest_case") or {}).get("case_id") or ""),
                        "reason_codes": _string_list(replay_safety.get("reason_codes")),
                    }
                )
                continue
            if job_id and job_id not in used_job_ids:
                picked = candidate
                break
            if job_id:
                conflicting.append(
                    {
                        "strategy_type": strategy,
                        "reference_job_id": job_id,
                        "case_id": str((candidate.get("golden_manifest_case") or {}).get("case_id") or ""),
                    }
                )
        if picked is None:
            if selected.get(strategy):
                duplicate_reference_conflicts.extend(conflicting)
            manifest_missing.append(strategy)
            manifest_ready_by_strategy[strategy] = False
            real_render_ready_by_strategy[strategy] = False
            continue
        used_job_ids.add(str(picked.get("job_id") or ""))
        manifest_ready.append(strategy)
        manifest_ready_by_strategy[strategy] = True
        real_render_ready_by_strategy[strategy] = bool(
            isinstance(picked.get("real_render_readiness"), dict)
            and picked["real_render_readiness"].get("ready")
        )
        manifest_jobs.append(picked["golden_manifest_case"])
    real_render_ready = [strategy for strategy in normalized_required if real_render_ready_by_strategy.get(strategy)]
    real_render_missing = [strategy for strategy in normalized_required if not real_render_ready_by_strategy.get(strategy)]
    strategy_candidate_summary = {
        strategy: _strategy_candidate_summary(
            selected.get(strategy, []),
            manifest_ready=manifest_ready_by_strategy.get(strategy, False),
            real_render_ready=real_render_ready_by_strategy.get(strategy, False),
        )
        for strategy in normalized_required
    }
    return {
        "schema": STRATEGY_FIXTURE_CANDIDATES_SCHEMA,
        "required_strategy_types": normalized_required,
        "covered_strategy_types": covered,
        "missing_strategy_types": missing,
        "manifest_ready_strategy_types": manifest_ready,
        "manifest_missing_strategy_types": manifest_missing,
        "real_render_ready_strategy_types": real_render_ready,
        "real_render_missing_strategy_types": real_render_missing,
        "duplicate_reference_conflicts": duplicate_reference_conflicts,
        "replay_unsafe_candidates": replay_unsafe_candidates,
        "candidate_count": sum(len(items) for items in selected.values()),
        "excluded_candidate_count": len(excluded_candidates),
        "excluded_candidates": excluded_candidates,
        "strategy_candidate_summary": strategy_candidate_summary,
        "selected_candidates": selected,
        "golden_manifest_jobs": manifest_jobs,
    }


async def export_strategy_fixture_candidates_from_db(
    *,
    limit: int = 500,
    per_strategy: int = 1,
    artifact_types: tuple[str, ...] | list[str] = DEFAULT_PROFILE_ARTIFACT_TYPES,
    required_strategies: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_STRATEGIES,
    excluded_job_ids: set[str] | None = None,
    excluded_case_ids: set[str] | None = None,
    excluded_source_names: set[str] | None = None,
) -> dict[str, Any]:
    session_factory = get_session_factory()
    raw_candidates: list[dict[str, Any]] = []
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Job, Artifact)
                .join(Artifact, Artifact.job_id == Job.id)
                .options(selectinload(Job.steps), selectinload(Job.render_outputs), selectinload(Job.transcript_segments))
                .where(Artifact.artifact_type.in_(list(artifact_types)))
                .order_by(Artifact.created_at.desc())
                .limit(max(1, int(limit or 1)))
            )
        ).all()
        for job, artifact in rows:
            profile = artifact.data_json if isinstance(artifact.data_json, dict) else {}
            if not profile:
                continue
            enriched = attach_content_profile_capability_orchestration(profile, job=job)
            if not isinstance(enriched, dict):
                continue
            orchestration = (
                enriched.get("capability_orchestration")
                if isinstance(enriched.get("capability_orchestration"), dict)
                else {}
            )
            raw_candidates.append(
                {
                    "job_id": str(job.id),
                    "artifact_id": str(artifact.id),
                    "artifact_type": str(artifact.artifact_type or ""),
                    "artifact_created_at": _isoformat(artifact.created_at),
                    "source_name": str(job.source_name or ""),
                    "status": str(job.status or ""),
                    "workflow_template": str(job.workflow_template or ""),
                    "language": _infer_candidate_language(job=job, profile=enriched),
                    "strategy_type": orchestration.get("strategy_type"),
                    "classification": orchestration.get("classification"),
                    "pipeline_plan": orchestration.get("pipeline_plan"),
                    "local_asset_inventory": orchestration.get("local_asset_inventory"),
                    "replay_context": _build_replay_context(job),
                    "real_render_context": _build_real_render_context(job),
                }
            )

    summary = select_strategy_fixture_candidates(
        raw_candidates,
        required_strategies=required_strategies,
        per_strategy=per_strategy,
        excluded_job_ids=excluded_job_ids,
        excluded_case_ids=excluded_case_ids,
        excluded_source_names=excluded_source_names,
    )
    summary["scanned_artifact_count"] = len(raw_candidates)
    summary["profile_artifact_types"] = list(artifact_types)
    return summary


def _candidate_score(
    *,
    confidence: float,
    status: str,
    artifact_type: str,
    enabled_features: list[str],
    review_gates: list[str],
    local_asset_inventory: dict[str, Any],
    real_render_ready: bool = False,
) -> float:
    score = confidence * 100.0
    if status == "done":
        score += 10.0
    if artifact_type in {"content_profile_final", "downstream_context"}:
        score += 8.0
    score += min(len(enabled_features), 6) * 1.5
    score += min(len(review_gates), 4)
    if bool(local_asset_inventory.get("multi_material_ready")):
        score += 3.0
    if real_render_ready:
        score += 12.0
    return round(score, 3)


def _build_real_render_context(job: Job) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    for render_output in list(getattr(job, "render_outputs", []) or []):
        output_path = str(getattr(render_output, "output_path", "") or "").strip()
        status = str(getattr(render_output, "status", "") or "").strip()
        exists = bool(output_path) and Path(output_path).exists()
        outputs.append(
            {
                "output_path": output_path,
                "status": status,
                "exists": exists,
            }
        )
    return {
        "job_status": str(getattr(job, "status", "") or "").strip(),
        "outputs": outputs,
    }


def _candidate_real_render_readiness(real_render_context: dict[str, Any]) -> dict[str, Any]:
    reason_codes: list[str] = []
    job_status = str(real_render_context.get("job_status") or "").strip().lower()
    outputs = [item for item in list(real_render_context.get("outputs") or []) if isinstance(item, dict)]
    ready_outputs = [
        item
        for item in outputs
        if str(item.get("output_path") or "").strip()
        and bool(item.get("exists"))
        and str(item.get("status") or "").strip().lower() in {"done", "partial"}
    ]
    if job_status not in {"done", "partial"}:
        reason_codes.append(f"job_status_not_terminal={job_status or 'unknown'}")
    if not outputs:
        reason_codes.append("render_output_missing")
    elif not ready_outputs:
        reason_codes.append("render_output_not_ready")
    return {
        "ready": bool(ready_outputs),
        "reason_codes": sorted(set(reason_codes)),
        "output_count": len(outputs),
        "ready_output_count": len(ready_outputs),
        "output_paths": [str(item.get("output_path") or "") for item in ready_outputs],
    }


def _build_replay_context(job: Job) -> dict[str, Any]:
    source_contexts: list[dict[str, Any]] = []
    for step in list(getattr(job, "steps", []) or []):
        metadata = getattr(step, "metadata_", None)
        if not isinstance(metadata, dict):
            continue
        source_context = metadata.get("source_context")
        if isinstance(source_context, dict):
            source_contexts.append(dict(source_context))
    merged_source_names: list[str] = []
    strategy_classifications: list[dict[str, Any]] = []
    product_controls: list[dict[str, Any]] = []
    for source_context in source_contexts:
        merged_source_names.extend(_string_list(source_context.get("merged_source_names")))
        classification = source_context.get("strategy_classification") or source_context.get("classification")
        if isinstance(classification, dict):
            strategy_classifications.append(dict(classification))
        controls = source_context.get("product_controls")
        if isinstance(controls, dict):
            product_controls.append(dict(controls))
    packaging_snapshot = getattr(job, "packaging_snapshot_json", None)
    if isinstance(packaging_snapshot, dict):
        merged_source_names.extend(_string_list(packaging_snapshot.get("merged_source_names")))
        metadata = packaging_snapshot.get("metadata") if isinstance(packaging_snapshot.get("metadata"), dict) else {}
        merged_source_names.extend(_string_list(metadata.get("merged_source_names")))
    unique_merged_sources = list(dict.fromkeys(merged_source_names))
    return {
        "source_path": str(getattr(job, "source_path", "") or ""),
        "source_name": str(getattr(job, "source_name", "") or ""),
        "workflow_template": str(getattr(job, "workflow_template", "") or ""),
        "enhancement_modes": _string_list(getattr(job, "enhancement_modes", []) or []),
        "has_packaging_snapshot": isinstance(packaging_snapshot, dict) and bool(packaging_snapshot),
        "merged_source_names": unique_merged_sources,
        "multi_material_ready": len(unique_merged_sources) >= 3,
        "strategy_classifications": strategy_classifications,
        "product_controls": product_controls,
    }


def _infer_candidate_language(*, job: Job, profile: dict[str, Any]) -> str:
    job_language = str(getattr(job, "language", "") or "").strip()
    if job_language and job_language.lower() not in {"zh-cn", "zh_cn", "zh", "chinese", "mandarin", "cn"}:
        return job_language
    samples: list[str] = []
    for row in list(getattr(job, "transcript_segments", []) or [])[:8]:
        text = str(getattr(row, "text", "") or "").strip()
        if text:
            samples.append(text)
    for key in ("transcript_excerpt", "summary", "hook_line"):
        text = str(profile.get(key) or "").strip()
        if text:
            samples.append(text)
    text = " ".join(samples)
    if _looks_english_text(text):
        return "en-US"
    return ""


def _looks_english_text(text: str) -> bool:
    alpha_count = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk_count:
        return False
    words = [part for part in "".join(ch if ch.isalpha() else " " for ch in text).split() if part]
    return alpha_count >= 24 and len(words) >= 4


def _candidate_replay_safety(
    *,
    strategy_type: str,
    source_name: str,
    workflow_template: str,
    replay_context: dict[str, Any],
) -> dict[str, Any]:
    reason_codes: list[str] = []
    replay_tags = _replay_context_tags(replay_context)
    normalized_source_name = source_name.lower()
    normalized_workflow = workflow_template.lower()
    safe = bool(str(replay_context.get("source_path") or "").strip())
    if not safe:
        reason_codes.append("source_path_missing")

    if strategy_type == "step_demonstration":
        if not ({"tutorial", "screen_recording", "step_by_step"} & replay_tags or "tutorial" in normalized_workflow or "tutorial" in normalized_source_name):
            safe = False
            reason_codes.append("step_demonstration_replay_signal_missing")
    elif strategy_type == "experience_and_mood":
        if not ({"vlog", "food", "travel", "experience", "mood"} & replay_tags or "vlog" in normalized_workflow or "vlog" in normalized_source_name):
            safe = False
            reason_codes.append("experience_replay_signal_missing")
    elif strategy_type == "event_highlight":
        if not ({"gameplay", "highlight", "event_highlight"} & replay_tags or "gameplay" in normalized_workflow or "highlight" in normalized_workflow):
            safe = False
            reason_codes.append("event_highlight_replay_signal_missing")
    elif strategy_type == "narrative_assembly":
        if not bool(replay_context.get("multi_material_ready")):
            safe = False
            reason_codes.append("multi_material_replay_context_missing")
        if not (
            {"remix", "script_driven", "digital_human", "material_insert_required", "storyboard_required", "multi_material"} & replay_tags
            or "multi_material" in normalized_workflow
            or "avatar_commentary" in replay_tags
        ):
            safe = False
            reason_codes.append("narrative_replay_signal_missing")

    return {
        "safe": safe,
        "reason_codes": sorted(set(reason_codes)),
        "replay_tags": sorted(replay_tags),
        "merged_source_count": len(_string_list(replay_context.get("merged_source_names"))),
    }


def _replay_context_tags(replay_context: dict[str, Any]) -> set[str]:
    tags: set[str] = set(_string_list(replay_context.get("enhancement_modes")))
    for key in ("workflow_template", "source_name"):
        value = str(replay_context.get(key) or "").strip().lower()
        if value:
            tags.add(value)
            tags.update(_tokenized_tags(value))
    for classification in list(replay_context.get("strategy_classifications") or []):
        if not isinstance(classification, dict):
            continue
        tags.add(str(classification.get("primary_type") or "").strip().lower())
        tags.add(str(classification.get("production_mode") or "").strip().lower())
        for tag_key in ("content_tags", "media_tags", "editing_signals", "asset_tags"):
            tags.update(_string_list(classification.get(tag_key)))
    for controls in list(replay_context.get("product_controls") or []):
        if isinstance(controls, dict):
            tags.add(str(controls.get("edit_mode") or "").strip().lower())
            tags.add(str(controls.get("material_usage") or "").strip().lower())
    tags.discard("")
    return tags


def _tokenized_tags(value: str) -> set[str]:
    normalized = "".join(ch if ch.isalnum() else " " for ch in str(value or "").lower())
    return {part.strip() for part in normalized.split() if part.strip()}


def _strategy_candidate_summary(
    candidates: list[dict[str, Any]],
    *,
    manifest_ready: bool,
    real_render_ready: bool,
) -> dict[str, Any]:
    job_ids = [str(candidate.get("job_id") or "") for candidate in candidates if str(candidate.get("job_id") or "")]
    statuses: dict[str, int] = {}
    artifact_types: dict[str, int] = {}
    for candidate in candidates:
        status = str(candidate.get("status") or "unknown").strip() or "unknown"
        artifact_type = str(candidate.get("artifact_type") or "unknown").strip() or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
        artifact_types[artifact_type] = artifact_types.get(artifact_type, 0) + 1
    return {
        "candidate_count": len(candidates),
        "unique_reference_job_count": len(set(job_ids)),
        "replay_safe_count": sum(
            1
            for candidate in candidates
            if isinstance(candidate.get("replay_safety"), dict) and candidate["replay_safety"].get("safe")
        ),
        "real_render_ready_count": sum(
            1
            for candidate in candidates
            if isinstance(candidate.get("real_render_readiness"), dict)
            and candidate["real_render_readiness"].get("ready")
        ),
        "top_reference_job_ids": job_ids[:5],
        "statuses": dict(sorted(statuses.items())),
        "artifact_types": dict(sorted(artifact_types.items())),
        "manifest_ready": manifest_ready,
        "real_render_ready": real_render_ready,
    }


def _case_id_for_candidate(*, strategy_type: str, job_id: str, source_name: str) -> str:
    source_slug = "".join(
        ch.lower() if ch.isascii() and ch.isalnum() else "_" for ch in source_name
    )[:28].strip("_")
    suffix = job_id.replace("-", "")[:8]
    middle = f"{source_slug}_" if source_slug else ""
    return f"strategy_{strategy_type}_{middle}{suffix}"


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _isoformat(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _parse_csv_values(values: list[str], default: tuple[str, ...]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed or list(default)


def _parse_optional_csv_values(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed


def collect_candidate_exclusions_from_reports(reports: list[dict[str, Any]]) -> dict[str, set[str]]:
    case_ids: set[str] = set()
    job_ids: set[str] = set()
    source_names: set[str] = set()
    for report in reports:
        for row in [item for item in list(report.get("golden_case_rows") or []) if isinstance(item, dict)]:
            if not _row_is_failed_candidate(row):
                continue
            case_id = str(row.get("case_id") or "").strip()
            job_id = str(row.get("reference_job_id") or row.get("job_id") or "").strip()
            evaluation_job_id = str(row.get("evaluation_job_id") or "").strip()
            source_name = str(row.get("source_name") or "").strip()
            if case_id:
                case_ids.add(case_id)
            if job_id:
                job_ids.add(job_id)
            if evaluation_job_id:
                job_ids.add(evaluation_job_id)
            if source_name:
                source_names.add(source_name)
    return {
        "case_ids": case_ids,
        "job_ids": job_ids,
        "source_names": source_names,
    }


def _row_is_failed_candidate(row: dict[str, Any]) -> bool:
    tags = {str(tag or "").strip() for tag in list(row.get("tags") or []) if str(tag or "").strip()}
    if "strategy_candidate" not in tags:
        return False
    status = str(row.get("status") or "").strip().lower()
    if status in {"failed", "error"}:
        return True
    if row.get("required_checks_passed") is False:
        return True
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return "render_subtitle_asr_alignment_blocked" in text or "required_checks_failed" in text


def build_strategy_candidate_golden_manifest(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": STRATEGY_CANDIDATE_MANIFEST_SCHEMA,
        "description": "Replay-safe strategy fixture candidates exported from existing RoughCut jobs.",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source_summary_schema": str(summary.get("schema") or ""),
        "required_strategy_types": list(summary.get("required_strategy_types") or []),
        "manifest_ready_strategy_types": list(summary.get("manifest_ready_strategy_types") or []),
        "real_render_ready_strategy_types": list(summary.get("real_render_ready_strategy_types") or []),
        "jobs": list(summary.get("golden_manifest_jobs") or []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export candidate reference jobs for strategy-specific golden fixtures."
    )
    parser.add_argument("--limit", type=int, default=500, help="Maximum profile artifacts to scan.")
    parser.add_argument("--per-strategy", type=int, default=1, help="Selected candidate count per strategy.")
    parser.add_argument(
        "--required-strategy",
        action="append",
        default=[],
        help="Required strategy type. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--artifact-type",
        action="append",
        default=[],
        help="Profile artifact type to scan. May be repeated or comma-separated.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=None,
        help="Optional golden manifest path containing the selected replay-safe candidate jobs.",
    )
    parser.add_argument(
        "--allow-candidate-only",
        action="store_true",
        help="Exit successfully when every strategy has at least one candidate even if the manifest-ready set is incomplete.",
    )
    parser.add_argument(
        "--require-real-render-ready",
        action="store_true",
        help="Exit successfully only when every required strategy has a selected candidate with an existing render output.",
    )
    parser.add_argument("--exclude-job-id", action="append", default=[], help="Reference/evaluation job id to exclude.")
    parser.add_argument("--exclude-case-id", action="append", default=[], help="Generated case id to exclude.")
    parser.add_argument("--exclude-source-name", action="append", default=[], help="Source file name to exclude.")
    parser.add_argument(
        "--rejection-report",
        action="append",
        default=[],
        type=Path,
        help="Failed candidate batch_report.json whose case/job/source should be excluded from replacement export.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rejection_reports = [json.loads(path.read_text(encoding="utf-8")) for path in list(args.rejection_report or [])]
    report_exclusions = collect_candidate_exclusions_from_reports(rejection_reports)
    excluded_job_ids = set(_parse_optional_csv_values(args.exclude_job_id)) | set(report_exclusions["job_ids"])
    excluded_case_ids = set(_parse_optional_csv_values(args.exclude_case_id)) | set(report_exclusions["case_ids"])
    excluded_source_names = set(_parse_optional_csv_values(args.exclude_source_name)) | set(report_exclusions["source_names"])
    payload = asyncio.run(
        export_strategy_fixture_candidates_from_db(
            limit=args.limit,
            per_strategy=args.per_strategy,
            artifact_types=_parse_csv_values(args.artifact_type, DEFAULT_PROFILE_ARTIFACT_TYPES),
            required_strategies=_parse_csv_values(args.required_strategy, DEFAULT_REQUIRED_STRATEGIES),
            excluded_job_ids=excluded_job_ids,
            excluded_case_ids=excluded_case_ids,
            excluded_source_names=excluded_source_names,
        )
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.manifest_output:
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(
            json.dumps(build_strategy_candidate_golden_manifest(payload), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if payload.get("missing_strategy_types"):
        return 1
    if payload.get("manifest_missing_strategy_types") and not args.allow_candidate_only:
        return 1
    if args.require_real_render_ready and payload.get("real_render_missing_strategy_types"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

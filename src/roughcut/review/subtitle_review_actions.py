from __future__ import annotations

from typing import Any

from roughcut.review.subtitle_consistency import ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT
from roughcut.review.subtitle_term_resolution import ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH

_DECISION_RERUN_CHAINS: dict[str, tuple[str, ...]] = {
    "subtitle_postprocess": (
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
    "subtitle_term_resolution": (
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
    "subtitle_consistency_review": (
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
    "glossary_review": (
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ),
}


def build_decision_action_payload(
    *,
    blocking: bool | None = None,
    review_route: str | None = None,
    review_label: str | None = None,
    recommended_action: str | None = None,
    rerun_start_step: str | None = None,
    issue_codes: list[str] | None = None,
) -> dict[str, Any]:
    normalized_start_step = str(rerun_start_step or "").strip() or None
    return {
        "blocking": blocking,
        "review_route": str(review_route or "").strip() or None,
        "review_label": str(review_label or "").strip() or None,
        "recommended_action": str(recommended_action or "").strip() or None,
        "rerun_start_step": normalized_start_step,
        "rerun_steps": list(_DECISION_RERUN_CHAINS.get(normalized_start_step or "", ())),
        "issue_codes": [str(item).strip() for item in (issue_codes or []) if str(item).strip()],
    }


def build_subtitle_quality_action(data: dict[str, Any]) -> dict[str, Any]:
    blocking = bool(data.get("blocking"))
    blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
    warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    identity_missing = bool(metrics.get("identity_missing"))
    if blocking:
        return build_decision_action_payload(
            blocking=True,
            review_route="subtitle_review",
            review_label="字幕质量复核",
            recommended_action=(
                f"先处理字幕质量阻断：{blocking_reasons[0]}；确认后如需自动回退，从 subtitle_postprocess 起重跑。"
                if blocking_reasons
                else "先处理字幕质量阻断，再决定是否从 subtitle_postprocess 起重跑。"
            ),
            rerun_start_step="subtitle_postprocess",
            issue_codes=["subtitle_quality_blocking"],
        )
    if identity_missing:
        return build_decision_action_payload(
            blocking=True,
            review_route="subtitle_review",
            review_label="字幕身份复核",
            recommended_action="字幕主体身份线索不足，先补确认品牌/型号，再继续信息核对。",
            rerun_start_step="subtitle_postprocess",
            issue_codes=["subtitle_identity_missing"],
        )
    if warning_reasons:
        return build_decision_action_payload(
            blocking=False,
            review_route=None,
            review_label="字幕质量提示",
            recommended_action="如需消除字幕质量提醒，可从 subtitle_postprocess 起重跑。",
            rerun_start_step="subtitle_postprocess",
            issue_codes=["subtitle_quality_warning"],
        )
    return build_decision_action_payload()


def build_subtitle_term_resolution_action(data: dict[str, Any]) -> dict[str, Any]:
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    pending = int(metrics.get("pending_count") or 0)
    if pending > 0:
        return build_decision_action_payload(
            blocking=True,
            review_route="subtitle_review",
            review_label="术语候选确认",
            recommended_action=f"先人工确认 {pending} 条术语候选，再继续后续摘要与成片流程。",
            rerun_start_step="subtitle_term_resolution",
            issue_codes=["subtitle_terms_pending"],
        )
    return build_decision_action_payload()


def build_subtitle_consistency_action(data: dict[str, Any]) -> dict[str, Any]:
    blocking = bool(data.get("blocking"))
    blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
    warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
    if blocking:
        return build_decision_action_payload(
            blocking=True,
            review_route="subtitle_review",
            review_label="一致性冲突复核",
            recommended_action=(
                f"先复核一致性冲突：{blocking_reasons[0]}；确认后如需自动回退，从 subtitle_consistency_review 起重跑。"
                if blocking_reasons
                else "先复核字幕与摘要/文件名的一致性冲突，再决定是否从 subtitle_consistency_review 起重跑。"
            ),
            rerun_start_step="subtitle_consistency_review",
            issue_codes=["subtitle_consistency_blocking"],
        )
    if warning_reasons:
        return build_decision_action_payload(
            blocking=False,
            review_route=None,
            review_label="一致性提示",
            recommended_action="如需消除一致性提醒，可从 subtitle_consistency_review 起重跑。",
            rerun_start_step="subtitle_consistency_review",
            issue_codes=["subtitle_consistency_warning"],
        )
    return build_decision_action_payload()


def build_subtitle_candidate_action(*, pending_count: int) -> dict[str, Any]:
    if pending_count <= 0:
        return build_decision_action_payload()
    return build_decision_action_payload(
        blocking=True,
        review_route="subtitle_review",
        review_label="字幕候选确认",
        recommended_action=f"字幕纠错候选还有 {pending_count} 条待审，先处理人工字幕审核，再继续摘要与成片流程。",
        rerun_start_step="glossary_review",
        issue_codes=["subtitle_terms_pending"],
    )


def build_subtitle_review_context(
    *,
    subtitle_quality_report: dict[str, Any] | None = None,
    subtitle_term_resolution_patch: dict[str, Any] | None = None,
    subtitle_consistency_report: dict[str, Any] | None = None,
    pending_candidate_count: int = 0,
) -> dict[str, str | None]:
    reports = (
        (subtitle_quality_report, build_subtitle_quality_action),
        (subtitle_term_resolution_patch, build_subtitle_term_resolution_action),
        (subtitle_consistency_report, build_subtitle_consistency_action),
    )
    for payload, builder in reports:
        if not isinstance(payload, dict) or not payload:
            continue
        action = builder(payload)
        if action.get("review_route") == "subtitle_review":
            return {
                "step_name": "summary_review",
                "label": "字幕复核",
                "detail": str(action.get("recommended_action") or "").strip() or "先处理字幕复核，再继续信息核对。",
            }

    action = build_subtitle_candidate_action(pending_count=pending_candidate_count)
    if action.get("review_route") == "subtitle_review":
        return {
            "step_name": "summary_review",
            "label": "字幕复核",
            "detail": str(action.get("recommended_action") or "").strip() or "先处理字幕候选，再继续信息核对。",
        }
    return {"step_name": None, "label": None, "detail": None}


def select_latest_subtitle_artifact_payloads(artifacts: list[Any]) -> dict[str, dict[str, Any]]:
    selected: dict[str, tuple[dict[str, Any], Any]] = {}
    for artifact in artifacts or []:
        artifact_type = str(getattr(artifact, "artifact_type", "") or "").strip()
        if artifact_type not in {
            ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
            ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
        }:
            continue
        payload = getattr(artifact, "data_json", None)
        if not isinstance(payload, dict):
            continue
        created_at = getattr(artifact, "created_at", None)
        current = selected.get(artifact_type)
        if current is None or (created_at is not None and (current[1] is None or created_at > current[1])):
            selected[artifact_type] = (dict(payload), created_at)
    return {artifact_type: payload for artifact_type, (payload, _created_at) in selected.items()}

from __future__ import annotations

from typing import Any

ISSUE_RERUN_STEP_OVERRIDES: dict[str, str] = {
    "missing_subtitles": "subtitle_postprocess",
    "subtitle_quality_blocking": "subtitle_postprocess",
    "subtitle_quality_warning": "subtitle_postprocess",
    "subtitle_identity_missing": "subtitle_postprocess",
    "subtitle_terms_pending": "subtitle_term_resolution",
    "subtitle_consistency_blocking": "subtitle_consistency_review",
    "subtitle_consistency_warning": "subtitle_consistency_review",
    "missing_canonical_transcript_layer": "transcript_review",
    "missing_content_profile": "content_profile",
}

AUTO_FIX_STEP_PRIORITY = (
    "subtitle_postprocess",
    "subtitle_term_resolution",
    "subtitle_consistency_review",
    "glossary_review",
    "transcript_review",
    "content_profile",
    "render",
)

STEP_RERUN_CHAINS: dict[str, tuple[str, ...]] = {
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
    "transcript_review": (
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
    "content_profile": ("content_profile", "ai_director", "avatar_commentary", "edit_plan", "render", "final_review", "platform_package"),
    "render": ("render", "final_review", "platform_package"),
    "edit_plan": ("edit_plan", "render", "final_review", "platform_package"),
    "ai_director": ("ai_director", "avatar_commentary", "edit_plan", "render", "final_review", "platform_package"),
    "avatar_commentary": ("avatar_commentary", "edit_plan", "render", "final_review", "platform_package"),
    "platform_package": ("platform_package",),
}

QUALITY_RERUN_STEPS = {
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
}


def rerun_chain_from_step(step_name: str) -> list[str]:
    normalized = str(step_name or "").strip()
    if not normalized:
        return []
    return list(STEP_RERUN_CHAINS.get(normalized, (normalized,)))


def rerun_start_step_for_issue(issue_code: str) -> str | None:
    normalized = str(issue_code or "").strip()
    if not normalized:
        return None
    return ISSUE_RERUN_STEP_OVERRIDES.get(normalized)


def rerun_steps_for_issue_code(issue_code: str) -> list[str]:
    start_step = rerun_start_step_for_issue(issue_code)
    return rerun_chain_from_step(start_step) if start_step else []


def pick_recommended_rerun_steps(issues: list[Any]) -> list[str]:
    candidate_steps = {
        ISSUE_RERUN_STEP_OVERRIDES.get(str(getattr(issue, "code", "") or "").strip(), getattr(issue, "auto_fix_step", None))
        for issue in issues
        if ISSUE_RERUN_STEP_OVERRIDES.get(str(getattr(issue, "code", "") or "").strip(), getattr(issue, "auto_fix_step", None))
    }
    rerun_steps: list[str] = []
    for step_name in AUTO_FIX_STEP_PRIORITY:
        if step_name not in candidate_steps:
            continue
        for chain_step in STEP_RERUN_CHAINS.get(step_name, (step_name,)):
            if chain_step not in rerun_steps:
                rerun_steps.append(chain_step)
    return rerun_steps

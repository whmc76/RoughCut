from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ISSUE_RERUN_STEP_OVERRIDES: dict[str, str] = {
    "missing_subtitles": "subtitle_postprocess",
    "subtitle_quality_blocking": "subtitle_postprocess",
    "subtitle_quality_warning": "subtitle_postprocess",
    "canonical_projection_quality_blocking": "transcript_review",
    "canonical_projection_quality_warning": "transcript_review",
    "subtitle_identity_missing": "subtitle_postprocess",
    "subtitle_terms_pending": "subtitle_term_resolution",
    "subtitle_consistency_blocking": "subtitle_consistency_review",
    "subtitle_consistency_warning": "subtitle_consistency_review",
    "missing_canonical_transcript_layer": "transcript_review",
    "missing_content_profile": "content_profile",
}

AUTO_FIX_STEP_PRIORITY = (
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "subtitle_term_resolution",
    "subtitle_consistency_review",
    "glossary_review",
    "transcript_review",
    "content_profile",
    "edit_plan",
    "chapter_analysis",
    "dialogue_polish",
    "subtitle_translation",
    "avatar_commentary",
    "render",
)

RENDER_RERUN_CHAIN = (
    "render_plain_base",
    "render_packaging_candidates",
    "render_burn_in",
    "render",
)

STEP_RERUN_CHAINS: dict[str, tuple[str, ...]] = {
    "extract_audio": (
        "extract_audio",
        "transcribe",
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "transcribe": (
        "transcribe",
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "subtitle_postprocess": (
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "subtitle_term_resolution": (
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "subtitle_consistency_review": (
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "glossary_review": (
        "glossary_review",
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "transcript_review": (
        "transcript_review",
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "content_profile": (
        "content_profile",
        "summary_review",
        "edit_plan",
        "chapter_analysis",
        "dialogue_polish",
        "subtitle_translation",
        "avatar_commentary",
        *RENDER_RERUN_CHAIN,
    ),
    "subtitle_translation": ("subtitle_translation", "avatar_commentary", *RENDER_RERUN_CHAIN),
    "chapter_analysis": ("chapter_analysis", "dialogue_polish", "subtitle_translation", "avatar_commentary", *RENDER_RERUN_CHAIN),
    "render_plain_base": RENDER_RERUN_CHAIN,
    "render_packaging_candidates": ("render_packaging_candidates", "render_burn_in", "render"),
    "render_burn_in": ("render_burn_in", "render"),
    "render": RENDER_RERUN_CHAIN,
    "edit_plan": ("edit_plan", "chapter_analysis", "dialogue_polish", "subtitle_translation", "avatar_commentary", *RENDER_RERUN_CHAIN),
    "dialogue_polish": ("dialogue_polish", "subtitle_translation", "avatar_commentary", *RENDER_RERUN_CHAIN),
    "avatar_commentary": ("avatar_commentary", *RENDER_RERUN_CHAIN),
}

QUALITY_RERUN_STEPS = {
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "subtitle_term_resolution",
    "subtitle_consistency_review",
    "glossary_review",
    "transcript_review",
    "content_profile",
    "summary_review",
    "edit_plan",
    "chapter_analysis",
    "dialogue_polish",
    "subtitle_translation",
    "avatar_commentary",
    "render_plain_base",
    "render_packaging_candidates",
    "render_burn_in",
    "render",
}

MANUAL_REVIEW_ONLY_ISSUES = frozenset(
    {
        "subtitle_semantic_contamination",
    }
)


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


def has_manual_review_only_issue_codes(issue_codes: Iterable[str] | None) -> bool:
    return any(
        str(issue_code or "").strip() in MANUAL_REVIEW_ONLY_ISSUES
        for issue_code in (issue_codes or [])
    )


def pick_recommended_rerun_steps(issues: list[Any]) -> list[str]:
    if has_manual_review_only_issue_codes(
        str(getattr(issue, "code", "") or "").strip()
        for issue in issues
    ):
        return []
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

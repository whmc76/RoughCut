from pathlib import Path

from scripts.check_agent_docs import (
    DOC_INDEX_PATH,
    STATE_TEMPLATE_PATH,
    validate_agents_text,
    validate_repo_docs,
    validate_state_doc_text,
)


def test_agent_docs_guard_passes_current_repository_state() -> None:
    assert validate_repo_docs() == []


def test_agents_guard_rejects_platform_specific_terms() -> None:
    text = """
# RoughCut Agent Map

This is the entrypoint map for coding agents.
Do not use it as task memory.

See docs/agent-current-state.md and docs/agent-doc-index.md.

## Current Goal

Bilibili cover upload for MAXACE.
""".strip()

    errors = validate_agents_text(text)

    assert any("bilibili" in error.lower() for error in errors)
    assert any("maxace" in error.lower() for error in errors)
    assert any("Current Goal" in error for error in errors)


def test_state_template_and_index_have_required_structure() -> None:
    index_errors = validate_state_doc_text(
        str(DOC_INDEX_PATH),
        DOC_INDEX_PATH.read_text(encoding="utf-8"),
        (
            "# Agent Document Index",
            "## Default Read Path",
            "## State Templates",
            "## Publication Work",
            "## Read Discipline",
        ),
    )
    template_errors = validate_state_doc_text(
        str(STATE_TEMPLATE_PATH),
        STATE_TEMPLATE_PATH.read_text(encoding="utf-8"),
        (
            "# Agent Current State Template",
            "## Current Objective",
            "## Do Not Reopen",
            "## Verification",
        ),
    )

    assert index_errors == []
    assert template_errors == []

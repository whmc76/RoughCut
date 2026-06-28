
from scripts.check_agent_docs import (
    DOC_INDEX_PATH,
    MANUAL_EDITOR_PATH,
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

See README.md and docs/design/INDEX.md.

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
            "# RoughCut Design Docs",
            "## Public Documents",
            "## Notes",
        ),
    )
    manual_editor_errors = validate_state_doc_text(
        str(MANUAL_EDITOR_PATH),
        MANUAL_EDITOR_PATH.read_text(encoding="utf-8"),
        (
            "# Manual Editor Open Source Alignment",
            "## Baseline",
            "## Guardrails",
        ),
    )

    assert index_errors == []
    assert manual_editor_errors == []

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
CURRENT_STATE_PATH = REPO_ROOT / "docs" / "agent-current-state.md"
DOC_INDEX_PATH = REPO_ROOT / "docs" / "agent-doc-index.md"
STATE_TEMPLATE_PATH = REPO_ROOT / "docs" / "agent-current-state-template.md"

MAX_AGENTS_LINES = 80
FORBIDDEN_AGENTS_TERMS = (
    "bilibili",
    "douyin",
    "xiaohongshu",
    "kuaishou",
    "toutiao",
    "youtube",
    "wechat-channels",
    "maxace",
    "edc刀光火工具集",
)
FORBIDDEN_AGENTS_HEADINGS = (
    "## Current Goal",
    "## Current Page State",
    "## Open",
    "## Resolved",
    "## Invalidating Evidence Required",
)
REQUIRED_AGENTS_SNIPPETS = (
    "entrypoint map for coding agents",
    "docs/agent-current-state.md",
    "docs/agent-doc-index.md",
    "Do not use it as task memory",
)
REQUIRED_STATE_HEADINGS = (
    "# Agent Current State",
    "## Current Objective",
    "## Current Workstream",
    "## Open Work",
    "## Resolved Decisions",
    "## Do Not Reopen",
    "## Next Concrete Action",
    "## Verification",
)
REQUIRED_INDEX_HEADINGS = (
    "# Agent Document Index",
    "## Default Read Path",
    "## Publication Work",
    "## Product / Architecture Context",
    "## Read Discipline",
)
REQUIRED_TEMPLATE_HEADINGS = (
    "# Agent Current State Template",
    "## Current Objective",
    "## Current Workstream",
    "## Open Work",
    "## Resolved Decisions",
    "## Do Not Reopen",
    "## Next Concrete Action",
    "## Verification",
    "## Optional Task-Specific Sections",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_required_snippets(name: str, text: str, snippets: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for snippet in snippets:
        if snippet not in text:
            errors.append(f"{name} is missing required text: {snippet!r}")
    return errors


def validate_agents_text(text: str, max_lines: int = MAX_AGENTS_LINES) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    if len(lines) > max_lines:
        errors.append(f"AGENTS.md is too long: {len(lines)} lines > {max_lines}")
    errors.extend(_check_required_snippets("AGENTS.md", text, REQUIRED_AGENTS_SNIPPETS))

    lowered = text.lower()
    for term in FORBIDDEN_AGENTS_TERMS:
        if term in lowered:
            errors.append(f"AGENTS.md contains task-specific or platform-specific term: {term!r}")
    for heading in FORBIDDEN_AGENTS_HEADINGS:
        if heading in text:
            errors.append(f"AGENTS.md contains task-state heading that belongs in a state doc: {heading!r}")
    return errors


def validate_state_doc_text(name: str, text: str, required_headings: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    errors.extend(_check_required_snippets(name, text, required_headings))
    return errors


def validate_repo_docs(root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    required_paths = (
        AGENTS_PATH,
        CURRENT_STATE_PATH,
        DOC_INDEX_PATH,
        STATE_TEMPLATE_PATH,
    )
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required agent doc: {path.relative_to(root)}")
    if errors:
        return errors

    agents_text = _read_text(AGENTS_PATH)
    current_state_text = _read_text(CURRENT_STATE_PATH)
    doc_index_text = _read_text(DOC_INDEX_PATH)
    template_text = _read_text(STATE_TEMPLATE_PATH)

    errors.extend(validate_agents_text(agents_text))
    errors.extend(validate_state_doc_text("docs/agent-current-state.md", current_state_text, REQUIRED_STATE_HEADINGS))
    errors.extend(validate_state_doc_text("docs/agent-doc-index.md", doc_index_text, REQUIRED_INDEX_HEADINGS))
    errors.extend(
        validate_state_doc_text(
            "docs/agent-current-state-template.md",
            template_text,
            REQUIRED_TEMPLATE_HEADINGS,
        )
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check agent doc hygiene and routing structure.")
    parser.parse_args()

    errors = validate_repo_docs()
    if not errors:
        print("agent-docs: ok")
        return 0

    for error in errors:
        print(f"agent-docs: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

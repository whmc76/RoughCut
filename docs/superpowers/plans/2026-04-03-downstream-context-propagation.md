# Downstream Context Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified downstream context artifact so all post-profile stages consume the same resolved research and manual-review conclusions.

**Architecture:** Add a small resolver module that converts the preferred content profile into a resolved downstream profile plus source metadata, persist that as `downstream_context`, and update downstream consumers to prefer it with safe fallback. Keep the resolved profile shape close to existing `content_profile` consumers to minimize code churn.

**Tech Stack:** Python 3.11, pytest, SQLAlchemy async ORM, existing RoughCut pipeline/review modules

---

### Task 1: Add downstream context resolver

**Files:**
- Create: `src/roughcut/review/downstream_context.py`
- Test: `tests/test_downstream_context.py`

- [ ] Write failing resolver tests for manual-review overrides, research flags, and fallback behavior.
- [ ] Run `uv run python -m pytest tests/test_downstream_context.py -q` and verify failure.
- [ ] Implement minimal resolver helpers to build resolved profile and downstream context payload.
- [ ] Run `uv run python -m pytest tests/test_downstream_context.py -q` and verify pass.

### Task 2: Persist downstream context from content profile

**Files:**
- Modify: `src/roughcut/pipeline/steps.py`
- Test: `tests/test_pipeline_steps.py`

- [ ] Add a failing test asserting `run_content_profile` persists `downstream_context`.
- [ ] Run the focused pytest target and verify failure.
- [ ] Implement persistence with draft/final profile flow and safe metadata.
- [ ] Re-run the focused pytest target and verify pass.

### Task 3: Switch downstream pipeline consumers

**Files:**
- Modify: `src/roughcut/pipeline/steps.py`
- Test: `tests/test_pipeline_steps.py`

- [ ] Add failing tests for `run_ai_director`, `run_avatar_commentary`, and `run_edit_plan` preferring resolved downstream profile.
- [ ] Run focused pytest targets and verify failure.
- [ ] Implement a shared loader in pipeline steps and wire the three consumers plus render-facing usage through it.
- [ ] Re-run focused pytest targets and verify pass.

### Task 4: Switch final review selection

**Files:**
- Modify: `src/roughcut/review/telegram_bot.py`
- Test: `tests/test_telegram_review_bot.py`

- [ ] Add a failing test asserting final review selects `downstream_context` ahead of raw content profile artifacts.
- [ ] Run `uv run python -m pytest tests/test_telegram_review_bot.py -q -k downstream_context` and verify failure.
- [ ] Implement selection and keep fallback ordering intact.
- [ ] Re-run the focused pytest target and verify pass.

### Task 5: Verify packaging compatibility

**Files:**
- Modify: `src/roughcut/pipeline/steps.py`
- Test: `tests/test_pipeline_steps.py`

- [ ] Add a failing test asserting `run_platform_package` consumes resolved profile from `downstream_context`.
- [ ] Run the focused pytest target and verify failure.
- [ ] Implement the minimal wiring change and keep existing `platform_copy` logic unchanged.
- [ ] Re-run the focused pytest target and verify pass.

### Task 6: Final verification

**Files:**
- Modify: `src/roughcut/review/downstream_context.py`
- Modify: `src/roughcut/pipeline/steps.py`
- Modify: `src/roughcut/review/telegram_bot.py`
- Modify: `tests/test_downstream_context.py`
- Modify: `tests/test_pipeline_steps.py`
- Modify: `tests/test_telegram_review_bot.py`

- [ ] Run `uv run python -m pytest tests/test_downstream_context.py tests/test_pipeline_steps.py tests/test_telegram_review_bot.py -q`
- [ ] Fix any residual failures with minimal changes.
- [ ] Re-run the same command and verify all pass.

# Settings Provider Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider health checks and manually refreshable model catalogs so transcription, reasoning, and vision fallback models are selected from validated dropdowns instead of free-text inputs.

**Architecture:** Add backend read-only endpoints for service status and model catalogs with provider-aware fetch logic and server-side caching. Extend the settings workspace with these queries, then switch settings panels and summaries to provider/model dropdown flows while preserving saved values that are no longer in the latest catalog.

**Tech Stack:** FastAPI, Pydantic, httpx, React, TanStack Query, Vitest, pytest

---

### Task 1: Backend catalog contracts

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/api/config.py`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/types.ts`
- Test: `E:/WorkSpace/RoughCut/tests/test_config_api.py`

- [ ] Write failing pytest coverage for `GET /config/service-status` and `GET /config/model-catalog` shape.
- [ ] Run the targeted backend tests and confirm they fail on missing routes or fields.
- [ ] Add response models and route stubs in `config.py`, plus matching frontend types.
- [ ] Re-run the targeted backend tests and confirm the route shape passes before provider logic is added.

### Task 2: Provider status and model fetchers

**Files:**
- Create: `E:/WorkSpace/RoughCut/src/roughcut/api/provider_catalog.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/api/config.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_config_api.py`

- [ ] Write failing tests for Ollama status, qwen_asr status, OpenAI refresh, Anthropic refresh, MiniMax refresh, and cache retention on refresh failure.
- [ ] Run the targeted backend tests and confirm the failures match missing fetch logic.
- [ ] Implement provider-aware health probes and catalog fetchers with server-side cache and safe fallbacks.
- [ ] Re-run the targeted backend tests and confirm they pass.

### Task 3: Settings workspace query layer

**Files:**
- Modify: `E:/WorkSpace/RoughCut/frontend/src/api/config.ts`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/useSettingsWorkspace.ts`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/types.ts`
- Test: `E:/WorkSpace/RoughCut/frontend/src/features/settings/useSettingsWorkspace.test.tsx`

- [ ] Write failing Vitest coverage for service status and model catalog queries, including refresh calls.
- [ ] Run the targeted frontend tests and confirm missing API methods or workspace data.
- [ ] Add API methods and query wiring for status and model catalogs.
- [ ] Re-run the targeted frontend tests and confirm they pass.

### Task 4: Settings panel dropdown conversion

**Files:**
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/ModelSettingsPanel.tsx`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/RuntimeSettingsPanel.tsx`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/constants.ts`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/helpers.ts`
- Test: `E:/WorkSpace/RoughCut/frontend/src/features/settings/ModelSettingsPanel.test.tsx`
- Test: `E:/WorkSpace/RoughCut/frontend/src/features/settings/RuntimeSettingsPanel.test.tsx`

- [ ] Write failing Vitest cases for reasoning model dropdowns, fallback model dropdowns, local mode Ollama dropdowns, refresh buttons, and service error states.
- [ ] Run the targeted frontend tests and confirm the current text fields break those expectations.
- [ ] Implement dropdown-backed model selection and read-only address/status display.
- [ ] Re-run the targeted frontend tests and confirm they pass.

### Task 5: Overview and profile summaries

**Files:**
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/SettingsOverviewPanel.tsx`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/configProfiles/ConfigProfileSwitcher.tsx`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/configProfiles/diffPresentation.ts`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/pages/SettingsPage.tsx`
- Test: `E:/WorkSpace/RoughCut/frontend/src/features/settings/SettingsOverviewPanel.test.tsx`
- Test: `E:/WorkSpace/RoughCut/frontend/src/features/configProfiles/ConfigProfileSwitcher.test.tsx`
- Test: `E:/WorkSpace/RoughCut/frontend/src/pages/SettingsPage.test.tsx`

- [ ] Write failing tests for service status summaries and “saved legacy model” display in overview/profile surfaces.
- [ ] Run the targeted frontend tests and confirm the summaries are still based on static text.
- [ ] Update summary and diff formatting to use the new catalog/state data consistently.
- [ ] Re-run the targeted frontend tests and confirm they pass.

### Task 6: Final verification

**Files:**
- Modify: `E:/WorkSpace/RoughCut/tests/test_config_api.py`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/settings/useSettingsWorkspace.test.tsx`

- [ ] Run focused backend tests for config routes.
- [ ] Run focused frontend tests for settings surfaces.
- [ ] Run `pnpm test` in `E:/WorkSpace/RoughCut/frontend`.
- [ ] Run `pnpm typecheck` in `E:/WorkSpace/RoughCut/frontend`.
- [ ] Run the relevant backend pytest command and confirm no regressions in config API coverage.

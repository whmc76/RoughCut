# Review Flow Refactor And Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the recent content-review change set into a maintainable review pipeline that keeps current functionality, improves Telegram/front-end review ergonomics, and reduces the risk of further regressions in `content_profile`.

**Architecture:** Split the current monolithic review flow into three layers: content-profile domain helpers, Telegram review message parsing, and API/UI presentation adapters. Keep existing external entry points stable, but move fast-growing heuristics into focused modules with explicit contracts and regression tests. Use the extracted boundaries to add the missing enhancements requested in the last two days: better keyword/query generation, more reliable Telegram reply interpretation, and consistent UI normalization for review fields.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, pytest, TypeScript, React, TanStack Query, existing RoughCut review/jobs modules

---

## File Structure

**New files and responsibilities**
- `src/roughcut/review/content_profile_keywords.py`: review keyword extraction, seed-term collection, query normalization, and fallback query generation.
- `src/roughcut/review/content_profile_feedback.py`: review-feedback parsing, verification snapshot shaping, feedback application helpers, and payload loading utilities.
- `src/roughcut/review/telegram_review_parsing.py`: Telegram content-profile reply parsing, subtitle/full-line parsing, callback token handling, and shared normalization helpers.
- `frontend/src/features/jobs/contentProfile.ts`: UI-only content-profile normalization, localized video-type labeling, and evidence formatting helpers.

**Existing files to shrink or rewire**
- `src/roughcut/review/content_profile.py`: keep orchestration entry points such as `infer_content_profile`, `enrich_content_profile`, and subtitle-polish flow; remove keyword/feedback helper bulk.
- `src/roughcut/review/telegram_bot.py`: keep bot service orchestration and transport concerns; remove message parsing and field-normalization logic.
- `src/roughcut/api/jobs.py`: keep route handlers; simplify content-profile payload shaping and re-use extracted review helpers.
- `frontend/src/features/jobs/JobContentProfileSection.tsx`: render-only component that consumes normalized UI helpers instead of embedding normalization logic.
- `frontend/src/features/jobs/useJobWorkspace.ts`: keep query/mutation orchestration; move draft/source normalization logic out of the hook when possible.

**Primary test files**
- `tests/test_content_profile.py`
- `tests/test_telegram_review_bot.py`
- `tests/test_api_health.py`
- `frontend/src/features/jobs/useJobWorkspace.test.tsx`
- `frontend/src/features/jobs/JobContentProfileSection.test.tsx`

---

### Task 1: Lock Down The Current Regressions Around Review Keywords And Feedback Payloads

**Files:**
- Modify: `tests/test_content_profile.py`
- Modify: `tests/test_content_profile_ocr.py`

- [ ] **Step 1: Write failing tests for keyword extraction and fallback query behavior**

Add tests that assert:
- keyword extraction preserves mixed Chinese/Latin product tokens such as `DJI Mini 4 Pro`
- duplicate or noisy chunks such as `开箱`/`评测` do not dominate the final keyword list
- semantic search expansions are still used when `search_queries` is empty
- fallback queries remain de-duplicated after normalization

- [ ] **Step 2: Run targeted tests to verify they fail for the expected reason**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_content_profile_ocr.py -q -k "keyword or search_queries or fallback"
```

Expected:
- at least one new failure showing keyword construction and query fallback still depend on the current monolithic helper path

- [ ] **Step 3: Write failing tests for review-feedback shaping**

Add tests that assert:
- review feedback preserves accepted corrections when rebuilding transcript excerpts
- verification snapshots only include normalized, non-empty evidence fragments
- profile feedback cannot silently drop `workflow_mode`, `enhancement_modes`, or `keywords`

- [ ] **Step 4: Run targeted tests to verify the feedback tests fail**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "feedback or transcript excerpt or verification snapshot"
```

Expected:
- new failures identify the old feedback helpers as the only place these behaviors exist

- [ ] **Step 5: Commit**

```bash
git add tests/test_content_profile.py tests/test_content_profile_ocr.py
git commit -m "test: add review keyword and feedback regressions"
```

### Task 2: Extract Keyword And Search-Query Logic From `content_profile.py`

**Files:**
- Create: `src/roughcut/review/content_profile_keywords.py`
- Modify: `src/roughcut/review/content_profile.py`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_content_profile_ocr.py`

- [ ] **Step 1: Write the failing import-level test**

Add a focused test that imports:

```python
from roughcut.review.content_profile_keywords import (
    build_review_keywords,
    collect_review_keyword_seed_terms,
    extract_review_keyword_tokens,
    normalize_query_list,
)
```

Assert that the extracted module is the public home for keyword/query behavior instead of importing underscore helpers from `content_profile.py`.

- [ ] **Step 2: Run the targeted tests to verify the module does not exist yet**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "content_profile_keywords or build_review_keywords"
```

Expected:
- FAIL with import or attribute errors because the new module has not been created yet

- [ ] **Step 3: Implement the keyword/query module with stable wrapper names**

Move these responsibilities into `content_profile_keywords.py`:
- token splitting and long-chunk expansion
- noise filtering and de-duplication
- seed-term collection from profile payloads
- query list normalization and fallback query synthesis

Expose stable helpers named:
- `extract_review_keyword_tokens`
- `collect_review_keyword_seed_terms`
- `build_review_keywords`
- `normalize_query_list`
- `fallback_search_queries_for_profile`

- [ ] **Step 4: Rewire `content_profile.py` to import the new helpers**

Keep existing external behavior unchanged by:
- importing the new helpers into `content_profile.py`
- preserving any legacy underscore wrappers only where old tests or callers still need compatibility
- removing duplicate regex and keyword constants from the orchestration file when the new module owns them

- [ ] **Step 5: Run green verification for keyword/query behavior**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_content_profile_ocr.py -q -k "keyword or search_queries or fallback"
```

Expected:
- all targeted keyword/query tests pass

- [ ] **Step 6: Commit**

```bash
git add src/roughcut/review/content_profile_keywords.py src/roughcut/review/content_profile.py tests/test_content_profile.py tests/test_content_profile_ocr.py
git commit -m "refactor: extract content profile keyword helpers"
```

### Task 3: Extract Review-Feedback Resolution And Application Helpers

**Files:**
- Create: `src/roughcut/review/content_profile_feedback.py`
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/api/jobs.py`
- Test: `tests/test_content_profile.py`

- [ ] **Step 1: Write failing tests for the extracted feedback API**

Add tests that import:

```python
from roughcut.review.content_profile_feedback import (
    apply_content_profile_feedback,
    build_review_feedback_search_queries,
    build_review_feedback_verification_snapshot,
)
```

Assert that:
- accepted corrections affect transcript excerpts deterministically
- verification snapshots only keep normalized non-empty values
- review feedback search queries prefer explicit review edits over stale draft keywords

- [ ] **Step 2: Run targeted tests and verify the extracted API is missing**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "review_feedback or apply_content_profile_feedback"
```

Expected:
- FAIL with import or missing-function errors

- [ ] **Step 3: Implement `content_profile_feedback.py`**

Move these responsibilities out of `content_profile.py`:
- review payload loading helpers
- verification snapshot shaping
- feedback-driven query generation
- feedback application and field merge rules

Keep asynchronous interfaces where the existing API/jobs routes already expect them.

- [ ] **Step 4: Rewire `content_profile.py` and `api/jobs.py` to use the extracted module**

Preserve the current public imports used by API routes and tests, but make the extracted module the canonical implementation.

- [ ] **Step 5: Run green verification for feedback behavior**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "feedback or transcript excerpt or verification snapshot"
```

Expected:
- all targeted feedback tests pass

- [ ] **Step 6: Commit**

```bash
git add src/roughcut/review/content_profile_feedback.py src/roughcut/review/content_profile.py src/roughcut/api/jobs.py tests/test_content_profile.py
git commit -m "refactor: extract content profile feedback helpers"
```

### Task 4: Split Telegram Parsing From Telegram Bot Orchestration And Improve Reply Handling

**Files:**
- Create: `src/roughcut/review/telegram_review_parsing.py`
- Modify: `src/roughcut/review/telegram_bot.py`
- Test: `tests/test_telegram_review_bot.py`

- [ ] **Step 1: Write failing tests for parser extraction and richer reply handling**

Add tests that assert:
- content-profile replies normalize duplicate keywords and drop unknown enhancement modes
- mixed full-subtitle replies like `L1改成...，L2通过` remain order-stable
- callback data parsing rejects malformed references without crashing bot orchestration
- short approval replies still resolve correctly when the review token lives in a replied caption

- [ ] **Step 2: Run targeted Telegram tests to verify red state**

Run:

```bash
uv run python -m pytest tests/test_telegram_review_bot.py -q -k "content_profile_reply or subtitle_review_reply or callback or review_reference"
```

Expected:
- at least one failure shows parsing behavior is still coupled to `telegram_bot.py`

- [ ] **Step 3: Implement `telegram_review_parsing.py`**

Move these responsibilities into the new module:
- review token extraction
- callback token parsing/building
- content-profile reply normalization
- subtitle and full-line reply interpretation
- shared regexes/constants that belong to parsing rather than message transport

- [ ] **Step 4: Rewire `telegram_bot.py` to call the parsing module**

Keep `TelegramReviewBotService` responsible only for:
- loading job/review state
- calling parser helpers
- dispatching API actions
- sending acknowledgements and follow-up review prompts

- [ ] **Step 5: Add one behavior enhancement while the boundary is clean**

Extend content-profile reply parsing so free-form text can safely update:
- `workflow_mode`
- `enhancement_modes`
- `keywords`
- `correction_notes`

without reintroducing duplicate keyword items or unsupported enhancement values.

- [ ] **Step 6: Run green verification for Telegram parsing**

Run:

```bash
uv run python -m pytest tests/test_telegram_review_bot.py -q
```

Expected:
- the Telegram review parser tests pass
- no new failures are introduced in the bot orchestration tests

- [ ] **Step 7: Commit**

```bash
git add src/roughcut/review/telegram_review_parsing.py src/roughcut/review/telegram_bot.py tests/test_telegram_review_bot.py
git commit -m "refactor: extract telegram review parsing"
```

### Task 5: Normalize API And Frontend Content-Profile Presentation

**Files:**
- Create: `frontend/src/features/jobs/contentProfile.ts`
- Modify: `frontend/src/features/jobs/JobContentProfileSection.tsx`
- Modify: `frontend/src/features/jobs/useJobWorkspace.ts`
- Modify: `frontend/src/features/jobs/constants.ts`
- Modify: `frontend/src/types.ts`
- Modify: `src/roughcut/api/jobs.py`
- Test: `frontend/src/features/jobs/JobContentProfileSection.test.tsx`
- Test: `frontend/src/features/jobs/useJobWorkspace.test.tsx`
- Test: `tests/test_api_health.py`

- [ ] **Step 1: Write failing backend and frontend tests for normalized review payloads**

Add tests that assert:
- `/jobs/{id}/content-profile` always returns a stable `content_understanding` block when draft/final payloads exist
- UI video-type display uses normalized labels rather than inferring from summary/hook text
- duplicate keyword arrays are collapsed once in the normalization helper, not ad hoc inside components
- identity evidence labels render consistently from structured support-source keys

- [ ] **Step 2: Run the targeted tests to verify red state**

Run:

```bash
uv run python -m pytest tests/test_api_health.py -q -k "content_profile"
npm --prefix frontend test -- --runInBand JobContentProfileSection useJobWorkspace
```

Expected:
- backend tests fail because response shaping is inconsistent
- frontend tests fail because normalization still lives inside the component/hook

- [ ] **Step 3: Implement `frontend/src/features/jobs/contentProfile.ts`**

Move UI-only logic into pure helpers:
- `getTextValue`
- `normalizeVideoTypeLabel`
- `formatVideoType`
- keyword/source normalization helpers
- identity-evidence label formatters

- [ ] **Step 4: Simplify the component and hook**

Update `JobContentProfileSection.tsx` and `useJobWorkspace.ts` so they consume the new helpers and stop embedding presentation heuristics in render paths.

- [ ] **Step 5: Tighten backend payload shaping**

Update `src/roughcut/api/jobs.py` so `get_content_profile` style responses:
- always run through one payload-normalization path
- avoid rebuilding `content_understanding` differently across routes
- keep front-end field names stable

- [ ] **Step 6: Run green verification for API/UI normalization**

Run:

```bash
uv run python -m pytest tests/test_api_health.py -q -k "content_profile"
npm --prefix frontend test -- --runInBand JobContentProfileSection useJobWorkspace
```

Expected:
- targeted backend and frontend tests pass

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/jobs/contentProfile.ts frontend/src/features/jobs/JobContentProfileSection.tsx frontend/src/features/jobs/useJobWorkspace.ts frontend/src/features/jobs/constants.ts frontend/src/types.ts src/roughcut/api/jobs.py frontend/src/features/jobs/JobContentProfileSection.test.tsx frontend/src/features/jobs/useJobWorkspace.test.tsx tests/test_api_health.py
git commit -m "refactor: normalize content profile review payloads"
```

### Task 6: End-To-End Review Flow Verification And Cleanup

**Files:**
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/review/telegram_bot.py`
- Modify: `src/roughcut/api/jobs.py`
- Modify: `frontend/src/features/jobs/JobContentProfileSection.tsx`
- Modify: `frontend/src/features/jobs/useJobWorkspace.ts`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_telegram_review_bot.py`
- Test: `tests/test_api_health.py`
- Test: `frontend/src/features/jobs/JobContentProfileSection.test.tsx`
- Test: `frontend/src/features/jobs/useJobWorkspace.test.tsx`

- [ ] **Step 1: Remove dead wrappers, duplicate constants, and stale inline comments**

Delete compatibility shims only after all callers have been updated. Keep public entry points intact if they are imported elsewhere in the repo.

- [ ] **Step 2: Run the complete targeted backend review suite**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_content_profile_ocr.py tests/test_telegram_review_bot.py tests/test_api_health.py -q
```

Expected:
- all targeted review-flow backend tests pass

- [ ] **Step 3: Run the complete targeted frontend review suite**

Run:

```bash
npm --prefix frontend test -- --runInBand JobContentProfileSection useJobWorkspace JobsPage
```

Expected:
- content-profile related frontend tests pass without new warnings

- [ ] **Step 4: Run one broader regression sweep around jobs/review integration**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_telegram_review_bot.py tests/test_jobs_final_review_api.py tests/test_telegram_bot.py -q
npm --prefix frontend test -- --runInBand JobQueueTable JobDetailModal JobSummaryReviewOverlay
```

Expected:
- the recent review/job integration surface remains green

- [ ] **Step 5: Commit**

```bash
git add src/roughcut/review/content_profile.py src/roughcut/review/telegram_bot.py src/roughcut/api/jobs.py frontend/src/features/jobs/JobContentProfileSection.tsx frontend/src/features/jobs/useJobWorkspace.ts tests/test_content_profile.py tests/test_telegram_review_bot.py tests/test_api_health.py frontend/src/features/jobs/JobContentProfileSection.test.tsx frontend/src/features/jobs/useJobWorkspace.test.tsx
git commit -m "refactor: harden review flow integration"
```

## Self-Review

- Spec coverage: the plan covers the backend monolith split, Telegram parsing extraction, API/UI normalization, and the user-requested enhancement path for keywords, Telegram replies, and presentation consistency.
- Placeholder scan: no `TBD`, `TODO`, or implicit “write tests later” steps remain; every task names concrete files and commands.
- Type consistency: the plan keeps `content_profile.py`, `telegram_bot.py`, and `api/jobs.py` as stable integration entry points while introducing extracted helper modules with explicit names.

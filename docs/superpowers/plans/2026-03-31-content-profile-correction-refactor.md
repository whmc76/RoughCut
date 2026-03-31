# Content Profile Correction Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild RoughCut's content profile correction flow so identity resolution is driven only by current-video evidence, while historical memory and glossaries are restricted to normalization and review assistance.

**Architecture:** Extract the monolithic `content_profile` identity path into a staged pipeline: evidence collection, candidate extraction, candidate scoring, profile resolution, and post-resolution enrichment. Keep API compatibility by preserving existing top-level entry points while moving identity creation into new focused modules and turning legacy memory/glossary behavior into normalization-only helpers.

**Tech Stack:** Python 3.11, pytest, uv, existing RoughCut review/pipeline modules

---

### Task 1: Add Regression Tests For Cross-Video Pollution And Conservative Empty Fallback

**Files:**
- Modify: `tests/test_content_profile.py`
- Modify: `tests/test_pipeline_steps.py`

- [ ] **Step 1: Write failing tests for identity injection constraints**

Add tests that assert:
- historical memory cannot create `subject_brand`/`subject_model` without current-video token hits
- normalization glossary can canonicalize only when the source token exists in current evidence
- tech-related weak evidence cannot overwrite a resolved physical product identity
- conflicting evidence produces empty identity fields and review-required output

- [ ] **Step 2: Run targeted tests to verify they fail for the expected reason**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "memory or glossary or conflicting or overwrite"
```

Expected:
- at least one new failure showing current logic still injects or preserves unsupported identity

- [ ] **Step 3: Add pipeline-level regression covering conservative fallback**

Add or extend `run_content_profile` tests so a job with insufficient identity evidence still produces a draft but leaves identity empty and marks the review path as pending/manual.

- [ ] **Step 4: Run pipeline regression to verify red state**

Run:

```bash
uv run python -m pytest tests/test_pipeline_steps.py -q -k "content_profile and conservative"
```

Expected:
- new test fails because the current implementation still synthesizes identity too aggressively

- [ ] **Step 5: Commit**

```bash
git add tests/test_content_profile.py tests/test_pipeline_steps.py
git commit -m "test: add content profile identity guard regressions"
```

### Task 2: Extract Current-Video Evidence And Candidate Types

**Files:**
- Create: `src/roughcut/review/content_profile/evidence.py`
- Create: `src/roughcut/review/content_profile/candidates.py`
- Create: `src/roughcut/review/content_profile/__init__.py`
- Modify: `src/roughcut/review/content_profile.py`

- [ ] **Step 1: Write focused failing tests for evidence bundle and candidate extraction**

Add tests that validate:
- evidence bundle preserves source categories and excerpts
- candidate extraction never reads user memory to create new identity candidates
- candidate extraction only emits normalized values when backed by current evidence

- [ ] **Step 2: Run tests and verify they fail due to missing extracted modules or behavior**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "evidence bundle or candidate extraction"
```

Expected:
- failures referencing missing module, missing dataclass, or old identity generation path

- [ ] **Step 3: Implement `EvidenceBundle` and current-evidence collection**

Create focused structures for transcript hits, visible text, source-name tokens, frame hints, and source spans. Keep these functions free of memory/glossary side effects.

- [ ] **Step 4: Implement candidate extraction**

Create candidate builders for brand/model/type/theme with source metadata. Only allow normalization when the raw matched token exists in current evidence.

- [ ] **Step 5: Wire the legacy entry point to build evidence and candidates**

Update the top-level module so existing callers can invoke the new evidence/candidate path without API breakage.

- [ ] **Step 6: Run targeted tests to verify green state**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "evidence bundle or candidate extraction or memory or glossary"
```

Expected:
- targeted tests pass

- [ ] **Step 7: Commit**

```bash
git add src/roughcut/review/content_profile/evidence.py src/roughcut/review/content_profile/candidates.py src/roughcut/review/content_profile/__init__.py src/roughcut/review/content_profile.py tests/test_content_profile.py
git commit -m "refactor: extract content profile evidence and candidates"
```

### Task 3: Replace Heuristic Identity Injection With Candidate Scoring And Resolution

**Files:**
- Create: `src/roughcut/review/content_profile/scoring.py`
- Create: `src/roughcut/review/content_profile/resolve.py`
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/pipeline/steps.py`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_pipeline_steps.py`

- [ ] **Step 1: Write failing tests for scoring and conservative resolution**

Add tests that assert:
- current-video multi-source evidence wins
- single-source weak evidence leaves identity empty
- historical memory contributes zero to candidate scores
- conflicting brand/model/type candidates resolve to empty identity

- [ ] **Step 2: Run tests to verify they fail against current heuristic path**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py -q -k "candidate score or conservative resolution or conflicting"
```

Expected:
- failures show old heuristic path still resolves unsupported identity

- [ ] **Step 3: Implement scoring module**

Score candidates by:
- transcript support
- visual support
- visible text/OCR support
- source-name support
- cross-source consistency
- weak single-source penalties

Assign zero score to memory-only, domain-pack-only, and template-only candidates.

- [ ] **Step 4: Implement resolution module**

Resolve final `subject_brand`, `subject_model`, `subject_type`, and `video_theme` from scored candidates. On conflict or insufficient evidence, emit empty values plus structured reasons.

- [ ] **Step 5: Replace legacy identity resolution path**

Update `infer_content_profile`, `enrich_content_profile`, and `run_content_profile` to use resolved identity output instead of heuristic identity seeding as the source of truth.

- [ ] **Step 6: Run targeted green verification**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py -q -k "content_profile or candidate or conservative"
```

Expected:
- new identity-resolution regressions pass
- existing content-profile pipeline tests remain green except for known unrelated baseline cover-title failures

- [ ] **Step 7: Commit**

```bash
git add src/roughcut/review/content_profile/scoring.py src/roughcut/review/content_profile/resolve.py src/roughcut/review/content_profile.py src/roughcut/pipeline/steps.py tests/test_content_profile.py tests/test_pipeline_steps.py
git commit -m "refactor: rebuild content profile identity resolution"
```

### Task 4: Downgrade Memory And Domain Glossaries To Normalization-Only Inputs

**Files:**
- Modify: `src/roughcut/review/content_profile_memory.py`
- Modify: `src/roughcut/review/domain_glossaries.py`
- Modify: `src/roughcut/review/content_profile.py`
- Test: `tests/test_content_profile.py`

- [ ] **Step 1: Write failing tests for memory and glossary write restrictions**

Add tests that assert:
- memory can canonicalize a token already present in current evidence
- memory cannot create identity when the current evidence lacks that token
- domain glossary packs influence review hints and normalization only, not identity creation

- [ ] **Step 2: Run tests to verify red state**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "memory or domain glossary or canonicalize"
```

Expected:
- failures indicate existing memory/domain logic still writes identity too early

- [ ] **Step 3: Refactor memory usage**

Change memory helpers so they return:
- normalization suggestions
- review hints
- prior-correction metadata

Do not allow them to write `subject_brand`, `subject_model`, `subject_type`, `video_theme`, or `search_queries`.

- [ ] **Step 4: Refactor domain glossary behavior**

Split glossary behavior conceptually into normalization-only and review-only. Prevent domain detection and term packs from injecting concrete identity candidates.

- [ ] **Step 5: Run targeted green verification**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py -q -k "memory or glossary or domain"
```

Expected:
- all new tests pass

- [ ] **Step 6: Commit**

```bash
git add src/roughcut/review/content_profile_memory.py src/roughcut/review/domain_glossaries.py src/roughcut/review/content_profile.py tests/test_content_profile.py
git commit -m "refactor: restrict memory and glossary identity influence"
```

### Task 5: Rebuild Enrichment And Review Gate On Top Of Resolved Identity

**Files:**
- Modify: `src/roughcut/review/content_profile.py`
- Modify: `src/roughcut/pipeline/steps.py`
- Modify: `src/roughcut/api/jobs.py`
- Modify: `src/roughcut/review/telegram_bot.py`
- Test: `tests/test_content_profile.py`
- Test: `tests/test_pipeline_steps.py`
- Test: `tests/test_telegram_review_bot.py`

- [ ] **Step 1: Write failing tests for enrichment isolation and manual-review fallback**

Add tests that assert:
- summary/hook/query generation never backfills missing identity
- review gate treats empty identity as manual-review, not auto-confirm
- API/review rendering still exposes review hints without treating them as resolved facts

- [ ] **Step 2: Run red verification**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py tests/test_telegram_review_bot.py -q -k "review gate or review hints or enrichment"
```

Expected:
- failures show enrichment or review output still depends on old backfill behavior

- [ ] **Step 3: Update enrichment logic**

Ensure `summary`, `hook_line`, `engagement_question`, `search_queries`, and `cover_title` use only resolved identity or conservative empty-state templates.

- [ ] **Step 4: Update review gate and output surfaces**

Make `run_content_profile`, API serializers, and review messaging distinguish:
- resolved identity
- unresolved review hints
- conservative fallback summaries

- [ ] **Step 5: Run targeted green verification**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py tests/test_telegram_review_bot.py -q -k "content_profile or review gate or review hints or enrichment"
```

Expected:
- new regressions pass
- review surfaces remain compatible

- [ ] **Step 6: Commit**

```bash
git add src/roughcut/review/content_profile.py src/roughcut/pipeline/steps.py src/roughcut/api/jobs.py src/roughcut/review/telegram_bot.py tests/test_content_profile.py tests/test_pipeline_steps.py tests/test_telegram_review_bot.py
git commit -m "refactor: rebuild enrichment and review gating on resolved identity"
```

### Task 6: Final Verification And Cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-03-31-content-profile-correction-refactor-design.md` (only if implementation revealed a necessary design delta)
- Modify: `docs/superpowers/plans/2026-03-31-content-profile-correction-refactor.md` (checkbox progress only if desired)

- [ ] **Step 1: Run focused verification suite**

Run:

```bash
uv run python -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py tests/test_telegram_review_bot.py -q
```

Expected:
- all newly added identity/correction regressions pass
- any remaining failures must be called out explicitly as pre-existing or out-of-scope

- [ ] **Step 2: Run broader content-profile-adjacent suite**

Run:

```bash
uv run python -m pytest tests/test_pipeline_quality.py tests/test_usage.py -q
```

Expected:
- no new regressions in quality scoring or usage telemetry around content profile

- [ ] **Step 3: Review diff for forbidden behavior**

Manually confirm the final diff removes or neutralizes:
- hardcoded identity injection from historical test tokens
- memory-created brand/model/type/theme outputs
- domain/template-created identity outputs

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: land content profile correction rebuild"
```

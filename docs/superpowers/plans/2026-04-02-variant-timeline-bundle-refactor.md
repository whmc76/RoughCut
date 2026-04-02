# Variant Timeline Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified variant timeline bundle so render, review, quality, and API all consume the same finalized per-variant timeline data.

**Architecture:** Keep `editorial_timeline` and `render_plan` as rule sources, then have `render` materialize a new bundle artifact containing the finalized timeline for `plain`, `packaged`, `ai_effect`, and `avatar` variants. All downstream consumers must read the bundle instead of recomputing subtitle or overlay timing from mixed sources.

**Tech Stack:** Python, SQLAlchemy artifacts, FFmpeg render pipeline, pytest

---

### Task 1: Define The Unified Variant Timeline Bundle

**Files:**
- Modify: `src/roughcut/pipeline/steps.py`
- Modify: `src/roughcut/api/jobs.py`
- Test: `tests/test_render_output_variants.py`

- [ ] **Step 1: Add the bundle schema builder and helper functions**

Create focused helpers in `src/roughcut/pipeline/steps.py` for:

```python
def _build_variant_timeline_bundle(...)
def _build_variant_timeline_entry(...)
def _build_variant_media_payload(...)
```

Bundle shape must include:

```python
{
    "timeline_rules": {
        "editorial_timeline_id": "...",
        "render_plan_timeline_id": "...",
        "keep_segments": [...],
        "packaging": {...},
        "editing_accents": {...},
    },
    "variants": {
        "plain": {...},
        "packaged": {...},
        "ai_effect": {...},
        "avatar": {...},
    },
}
```

- [ ] **Step 2: Add failing tests for the bundle payload**

Extend `tests/test_render_output_variants.py` with assertions for:

```python
def test_build_variant_timeline_bundle_contains_variants_and_rules(): ...
def test_build_variant_timeline_bundle_preserves_transition_overlap_metadata(): ...
```

- [ ] **Step 3: Run the focused test file and verify failures**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py -v
```

Expected: new bundle tests fail before implementation is complete.

- [ ] **Step 4: Implement the minimal bundle builder**

Store one new artifact alongside `render_outputs`:

```python
Artifact(
    job_id=uuid.UUID(job_id),
    step_id=render_step.id if render_step else None,
    artifact_type="variant_timeline_bundle",
    data_json=bundle_payload,
)
```

- [ ] **Step 5: Re-run the focused tests**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py -v
```

Expected: bundle tests pass.


### Task 2: Make Render Materialize Finalized Variant Timelines

**Files:**
- Modify: `src/roughcut/pipeline/steps.py`
- Test: `tests/test_render_output_variants.py`

- [ ] **Step 1: Write failing tests for finalized variant timing**

Add coverage for:

```python
async def test_packaged_variant_timeline_uses_transition_adjusted_subtitles(...): ...
async def test_ai_effect_variant_timeline_uses_transition_adjusted_overlay_events(...): ...
async def test_plain_variant_timeline_keeps_unadjusted_plain_timing(...): ...
```

- [ ] **Step 2: Verify the tests fail for the expected reason**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py -k "variant_timeline or transition_overlap" -v
```

Expected: failures point to missing finalized variant payloads or incomplete event timing.

- [ ] **Step 3: Replace ad hoc per-consumer timing with a single finalized payload**

Update `run_render()` so it builds variant entries from the already-computed:

```python
remapped_subtitles
packaged_subtitles
final_overlay_accents
ai_effect_overlay_accents
avatar_variant_subtitle_items
```

Each variant entry must include:

```python
{
    "media": {"path": "...", "srt_path": "...", "duration_sec": 0.0, "width": 0, "height": 0},
    "segments": [...],
    "transitions": [...],
    "subtitle_events": [...],
    "overlay_events": {"emphasis_overlays": [...], "sound_effects": [...]},
    "quality_checks": {...},
}
```

- [ ] **Step 4: Keep `render_outputs` as a compatibility index**

Do not remove existing `render_outputs`; instead reduce it to file paths and summary quality fields while making the bundle the timing source of truth.

- [ ] **Step 5: Re-run render-output regression tests**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py -v
```

Expected: all packaged/plain/ai-effect timing tests pass.


### Task 3: Migrate Consumers To Read The Bundle

**Files:**
- Modify: `src/roughcut/review/telegram_bot.py`
- Modify: `src/roughcut/pipeline/quality.py`
- Modify: `src/roughcut/api/jobs.py`
- Test: `tests/test_telegram_review_bot.py`
- Test: `tests/test_pipeline_quality.py`
- Test: `tests/test_jobs_final_review_api.py`

- [ ] **Step 1: Add failing review and quality tests**

Create or extend tests for:

```python
async def test_final_review_uses_packaged_variant_subtitle_events(...): ...
def test_assess_job_quality_prefers_bundle_variant_sync_check(...): ...
def test_job_api_exposes_variant_timeline_summary(...): ...
```

- [ ] **Step 2: Verify those tests fail before migration**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_telegram_review_bot.py tests/test_pipeline_quality.py tests/test_jobs_final_review_api.py -v
```

Expected: failures show old consumers still depend on `SubtitleItem` or legacy `render_outputs` timing.

- [ ] **Step 3: Update final review to read finalized variant data**

`src/roughcut/review/telegram_bot.py` must:
- load `variant_timeline_bundle`
- choose review source variant in priority order `packaged -> avatar -> ai_effect -> plain`
- read preview transcript excerpts from `subtitle_events`
- fall back to `packaged_srt` parsing, then `subtitle_report`, only if the bundle is absent

- [ ] **Step 4: Update quality assessment to read per-variant quality checks**

`src/roughcut/pipeline/quality.py` must:
- prefer `variant_timeline_bundle.variants.packaged.quality_checks`
- keep legacy fallback to `render_outputs` for old jobs

- [ ] **Step 5: Expose bundle-backed variant timing summaries through jobs API**

`src/roughcut/api/jobs.py` must expose a compact variant timing summary, not full raw subtitle payloads, for UI and audit use.

- [ ] **Step 6: Re-run the consumer suites**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_telegram_review_bot.py tests/test_pipeline_quality.py tests/test_jobs_final_review_api.py -v
```

Expected: consumer tests pass on bundle-backed reads.


### Task 4: Add Live Validation And Regression Guard Rails

**Files:**
- Modify: `src/roughcut/api/jobs.py`
- Modify: `src/roughcut/review/telegram_bot.py`
- Modify: `src/roughcut/pipeline/quality.py`
- Test: `tests/test_render_output_variants.py`
- Test: `tests/test_telegram_review_bot.py`
- Test: `tests/test_pipeline_quality.py`

- [ ] **Step 1: Add a live validation helper for bundle consistency**

Create a helper that checks:

```python
def _validate_variant_timeline_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    ...
```

It must verify:
- subtitle events are monotonic
- transition overlap totals match the rendered variant timeline
- quality check source corresponds to the same variant payload

- [ ] **Step 2: Attach validation summary to artifact/API output**

Persist or surface:

```python
{
    "bundle_status": "ok" | "warning",
    "issues": [...],
}
```

- [ ] **Step 3: Run full regression for touched subsystems**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py tests/test_telegram_review_bot.py tests/test_pipeline_quality.py tests/test_jobs_final_review_api.py -v
```

Expected: full regression is green.

- [ ] **Step 4: Execute live test against a real job output**

Use one recent real job and inspect:
- plain variant subtitle timing
- packaged variant subtitle timing
- ai-effect variant subtitle and overlay timing
- final review preview excerpts
- quality summary

Suggested commands:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_render_output_variants.py tests/test_telegram_review_bot.py tests/test_pipeline_quality.py tests/test_jobs_final_review_api.py -v
```

And, if a real job exists in the current runtime, inspect its stored bundle and output files via the existing API/runtime path rather than reimplementing a custom probe script.

- [ ] **Step 5: Record findings and fix any live-only gaps**

If live evaluation finds mismatches not caught by tests, patch the bundle builder or consumer fallback path and rerun the relevant regression command immediately.

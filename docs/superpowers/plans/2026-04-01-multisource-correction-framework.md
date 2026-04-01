# Multi-Source Correction Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-driven subtitle and summary correction framework for RoughCut that combines ASR context biasing, OCR/vision evidence, entity memory, and domain-gated correction without cross-domain contamination.

**Architecture:** Introduce a multi-source evidence layer first, then add durable entity memory and domain-gated correction policy, then rewire content-profile and subtitle pipelines to consume evidence instead of free-form heuristics. Roll out behind feature flags with regression tests and live validation on real EDC samples before broad enablement.

**Tech Stack:** Python, SQLAlchemy, existing RoughCut pipeline/review modules, optional PaddleOCR provider, existing multimodal provider, existing transcription providers, pytest.

---

## Delivery Streams

- Stream A: Foundation and feature flags
- Stream B: OCR artifacts and visual evidence
- Stream C: ASR evidence normalization and alignment metadata
- Stream D: Entity graph and negative memory
- Stream E: Subtitle correction engine refactor
- Stream F: Content profile / summary refactor
- Stream G: Review surfaces, rollout, and validation

## Execution Status

- [x] Stream A / Task 1 landed: feature flags, evidence contracts, correction framework trace, rerun cleanup gating.
- [x] Stream B / Task 2 landed: dedicated OCR provider abstraction, PaddleOCR graceful degradation, OCR aggregation, `content_profile_ocr` artifact persistence.
- [x] Stream C / Task 3 landed: transcript raw evidence contract, provider/model/raw payload normalization, `transcript_evidence` artifact persistence.
- [x] Stream D / Task 4 landed: durable entity graph tables, legacy bridge, alias promotion, negative-memory suppression.
- [x] Stream E / Task 5 landed: subtitle review memory now reads graph-backed confirmed entities, brand alias replacement requires current anchors, negative-memory suppresses unsafe alias forcing, and low-risk brand normalization can auto-apply.
- [x] Stream F / Task 6 landed: identity evidence bundles now include OCR/transcript source labels/graph entities, current-video evidence outranks stale memory, conflicting OCR vs transcript identity resolves conservatively, and summary/theme rebuilds consume resolved entities.
- [~] Stream G / Task 8 backend subset landed: jobs API and Telegram review now expose OCR/transcript evidence, `entity_resolution_trace` hook is present, frontend/live validation remain pending.
- [ ] Stream G / Task 9 pending: baseline vs new-framework live eval and rollout gating.

## Current Parallel Rollout

- Completed: Entity graph schema + persistence helpers + legacy memory bridge.
- Completed: Review/API evidence surfacing for OCR/transcript evidence, with entity-resolution trace hooks available to downstream review surfaces.
- Completed: Subtitle correction and content-profile evidence refactors, followed by focused regression verification (`168 passed` across subtitle/glossary/content-profile/content-profile-memory suites).
- Next: Live sample evaluation and staged rollout gating on real media.

## Parallelization Rules

- Stream A must land first.
- Streams B and C can run in parallel after A.
- Stream D can start after A and should integrate outputs from B/C incrementally.
- Stream E depends on C and D.
- Stream F depends on B, D, and E.
- Stream G starts with A and expands as each stream lands.

### Task 1: Foundation Flags and Evidence Contracts

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/config.py`
- Create: `E:/WorkSpace/RoughCut/src/roughcut/review/evidence_types.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/db/models.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_pipeline_steps.py`

- [ ] Define config flags for `ocr_enabled`, `entity_graph_enabled`, `asr_evidence_enabled`, `research_verifier_enabled`.
- [ ] Add shared evidence dataclasses for `EvidenceHit`, `EntityCandidate`, `EntityObservation`, `OcrFrameResult`, `TranscriptEvidence`.
- [ ] Add artifact naming constants for `content_profile_ocr`, `transcript_evidence`, and `entity_resolution_trace`.
- [ ] Write regression tests that default behavior remains unchanged when flags are off.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline_steps.py -k "flag or artifact"` and verify the new tests pass.

### Task 2: Dedicated OCR Provider and OCR Artifact Persistence

**Files:**
- Create: `E:/WorkSpace/RoughCut/src/roughcut/providers/ocr/base.py`
- Create: `E:/WorkSpace/RoughCut/src/roughcut/providers/ocr/paddleocr_provider.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/factory.py`
- Create: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_ocr.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/pipeline/steps.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_content_profile.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_pipeline_steps.py`

- [ ] Add an OCR provider interface that returns per-frame text lines, confidence, and boxes.
- [ ] Implement a PaddleOCR-backed provider behind config/availability checks so runtime can degrade gracefully if OCR dependencies are absent.
- [ ] Add OCR aggregation helpers that collapse frame-level OCR into normalized subject candidates and raw snippets.
- [ ] Wire OCR into `infer_content_profile()` immediately after frame extraction and before multimodal fusion.
- [ ] Persist OCR output as a dedicated artifact from `run_content_profile()`.
- [ ] Add tests proving OCR evidence is emitted separately from `visible_text` and survives artifact reload.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_content_profile.py tests/test_pipeline_steps.py -k "ocr or content_profile"` and verify pass.

### Task 3: ASR Evidence Normalization and Provider Metadata

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/transcription/base.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/transcription/openai_whisper.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/transcription/qwen_asr_http.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/transcription/funasr_provider.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/providers/transcription/local_whisper.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/speech/transcribe.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/pipeline/steps.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_pipeline_steps.py`

- [ ] Extend transcript result objects to carry normalized provider evidence: optional confidence/logprobs, VAD boundaries, hotword/context list, and alignment placeholders.
- [ ] Normalize provider plan output so downstream code does not branch per provider for metadata access.
- [ ] Capture the actual prompt/context/hotword set used for transcription in transcript artifacts for debugging.
- [ ] Add optional alignment hook points so WhisperX or provider-native alignment can be inserted later without changing pipeline contracts.
- [ ] Add tests proving provider fallback still works and evidence metadata is persisted.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline_steps.py -k "transcribe or provider"` and verify pass.

### Task 4: Durable Entity Graph and Negative Memory

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/db/models.py`
- Create: `E:/WorkSpace/RoughCut/src/roughcut/db/migrations/versions/0010_entity_graph.py`
- Create: `E:/WorkSpace/RoughCut/src/roughcut/review/entity_graph.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_memory.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/api/jobs.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_content_profile_memory.py`

- [ ] Add durable tables for canonical entities, aliases, observations, and rejected mappings.
- [ ] Implement read/write helpers that can derive current `confirmed_entities` from graph state first and legacy corrections second.
- [ ] Persist accepted manual confirmations and accepted correction aliases into the graph with canonical domain keys.
- [ ] Persist rejected or manually overridden mappings as negative observations.
- [ ] Add tests proving domain isolation, alias promotion, and negative-memory suppression.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_content_profile_memory.py -v` and verify pass.

### Task 5: Subtitle Correction Engine Refactor

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/subtitle_memory.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/glossary_engine.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/domain_glossaries.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/pipeline/steps.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_subtitle_memory.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_glossary_engine.py`

- [ ] Split correction policy into token-level normalization, entity-level canonicalization, and style-level polishing.
- [ ] Feed graph aliases and negative memory into `build_subtitle_review_memory()` with strict domain gating.
- [ ] Make entity-level replacement require current-video anchors from ASR/OCR/confirmed identity instead of free-form memory alone.
- [ ] Keep brand/model replacement conservative and line-local; only style-level polishing may be sentence-wide.
- [ ] Add tests proving no cross-domain injection, no unsafe brand forcing, and correct use of confirmed entity anchors.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_subtitle_memory.py tests/test_glossary_engine.py` and verify pass.

### Task 6: Content Profile and Summary Refactor

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_evidence.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_candidates.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_scoring.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile_resolve.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_content_profile.py`

- [ ] Extend identity evidence bundles with OCR-specific evidence and explicit source labels.
- [ ] Reweight entity scoring so OCR and current-video observations outrank stale memory.
- [ ] Make summary/theme generation consume resolved entity graph output and domain-gated transcript evidence, not raw subtitle heuristics alone.
- [ ] Keep `visible_text` as a display field, separate from raw OCR evidence.
- [ ] Add tests for contradictory OCR/transcript cases, memory suppression, and conservative fallback summaries.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_content_profile.py -k "identity or summary or evidence"` and verify pass.

### Task 7: Search Verifier, Not Search Generator

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/content_profile.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/platform_copy.py`
- Test: `E:/WorkSpace/RoughCut/tests/test_content_profile.py`

- [ ] Change search from early-stage profile generation to low-confidence verification only.
- [ ] Trigger research only when entity confidence is below threshold and current evidence conflicts.
- [ ] Ensure search results can raise/lower candidate confidence but cannot create a subject unsupported by current-video evidence.
- [ ] Add tests proving research is off by default and only used as verifier when enabled.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_content_profile.py -k "research or verifier"` and verify pass.

### Task 8: Review Surfaces, APIs, and Debuggability

**Files:**
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/api/jobs.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/api/schemas.py`
- Modify: `E:/WorkSpace/RoughCut/src/roughcut/review/telegram_bot.py`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/types.ts`
- Modify: `E:/WorkSpace/RoughCut/frontend/src/features/jobs/JobContentProfileSection.tsx`
- Test: `E:/WorkSpace/RoughCut/tests/test_telegram_bot.py`

- [ ] Expose OCR snippets, transcript evidence, and entity resolution traces in review APIs.
- [ ] Update Telegram/manual review views so reviewers can see why a brand/model was chosen or suppressed.
- [ ] Add UI fields for OCR evidence and entity confidence, keeping noisy raw text collapsed by default.
- [ ] Add tests for API schema compatibility and bot formatting.
- [ ] Run: `.venv\Scripts\python.exe -m pytest tests/test_telegram_bot.py -v` and verify pass.

### Task 9: Staged Rollout and Live Validation

**Files:**
- Modify: `E:/WorkSpace/RoughCut/tmp_live_fullcut.py`
- Create: `E:/WorkSpace/RoughCut/scripts/live_eval_correction_matrix.py`
- Modify: `E:/WorkSpace/RoughCut/tests/test_pipeline_steps.py`

- [ ] Add a live-eval script that runs the same source through baseline and new framework modes and stores comparable JSON outputs.
- [ ] Define acceptance checks: no cross-domain term pollution, provider trace present, OCR artifact present when enabled, entity confidence trace present, summary grounded in resolved entities.
- [ ] Validate on a fixed sample set from `Y:\EDC系列\未剪辑视频` before flipping any default flags.
- [ ] Keep feature flags off by default until live-eval metrics are acceptable.
- [ ] Run: `.venv\Scripts\python.exe tmp_live_fullcut.py --source-root 'Y:\EDC系列\未剪辑视频' --source-name '20260209-124735.mp4'` and inspect saved report.

## Suggested Execution Order

1. Task 1
2. Task 2 and Task 3 in parallel
3. Task 4
4. Task 5 and Task 6 in parallel after Task 4 scaffolding is stable
5. Task 7
6. Task 8
7. Task 9

## Spec Coverage Check

- Cross-domain isolation: Tasks 4, 5, 6, 9
- OCR/vision evidence landing in correction pipeline: Tasks 2, 6, 8
- Stronger ASR evidence and provider ordering/debugging: Tasks 3, 9
- Manual correction learning and reuse: Tasks 4, 5, 6
- Search used only as verifier: Task 7
- Live validation on real EDC samples: Task 9

## Main Risks to Watch

- `visible_text` is overloaded today; splitting OCR evidence from display text must be done carefully.
- Entity graph can become a third source of truth unless precedence is explicit from day one.
- OCR may over-read background text without subject-region gating.
- Provider metadata support is uneven; evidence contracts must allow partial fields.
- Search must remain verifier-only or it will reintroduce hallucinated subjects.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-01-multisource-correction-framework.md`.

Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints

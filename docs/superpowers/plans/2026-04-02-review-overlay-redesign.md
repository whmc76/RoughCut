# Review Overlay Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current side-panel `needs_review` experience with dedicated full-screen review overlays for `summary_review` and `final_review`.

**Architecture:** Keep the existing job detail modal for non-review states. Route `needs_review` jobs into a dedicated review overlay shell that renders one of two purpose-built pages: summary review reuses content-profile evidence and confirmation flows, while final review foregrounds final approval, quality results, subtitle spot checks, and preview/download actions.

**Tech Stack:** React, TypeScript, React Query, Vitest, Testing Library, existing RoughCut frontend styles.

---

### Task 1: Lock behavior with review-overlay tests

**Files:**
- Create: `frontend/src/features/jobs/JobReviewOverlay.test.tsx`
- Modify: `frontend/src/pages/JobsPage.test.tsx`

- [ ] Write failing tests for summary and final review overlays
- [ ] Verify `needs_review` no longer defaults to the generic detail-panel review layout
- [ ] Verify final review foregrounds quality and subtitle evidence

### Task 2: Build dedicated review overlays

**Files:**
- Create: `frontend/src/features/jobs/JobReviewOverlay.tsx`
- Create: `frontend/src/features/jobs/JobSummaryReviewOverlay.tsx`
- Create: `frontend/src/features/jobs/JobFinalReviewOverlay.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`

- [ ] Add a review overlay shell with a full floating layout
- [ ] Implement summary review page with evidence-first content profile review
- [ ] Implement final review page with explicit final-review header, quality results, subtitle spot check, and top-right preview/download actions

### Task 3: Integrate overlays into jobs flow

**Files:**
- Modify: `frontend/src/pages/JobsPage.tsx`
- Modify: `frontend/src/features/jobs/JobQueueTable.tsx`
- Modify: `frontend/src/api/jobs.ts`
- Modify: `frontend/src/features/jobs/useJobWorkspace.ts`
- Modify: `src/roughcut/api/jobs.py` (only if final-review action API is required)

- [ ] Route `needs_review` jobs to the dedicated overlay instead of the detail modal
- [ ] Clarify queue labels for current review stage
- [ ] Keep config/workflow controls secondary instead of primary in review mode

### Task 4: Verify and tighten wording

**Files:**
- Modify: `frontend/src/i18n.tsx` (if labels are missing)
- Modify: relevant tests from Tasks 1-3

- [ ] Run focused frontend tests
- [ ] Run TypeScript verification
- [ ] Adjust wording only where the tests expose ambiguous review-state text

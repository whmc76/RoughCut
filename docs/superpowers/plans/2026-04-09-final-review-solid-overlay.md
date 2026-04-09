# Final Review Solid Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the final-review overlay with the warm solid review workbench already used by summary review.

**Architecture:** Keep `JobReviewOverlay` as the modal controller, add final-review-specific shell/content surface classes there, then add a focused set of final-review surface/card classes in `JobFinalReviewOverlay` and `styles.css`. Protect the layout with a component test before changing the markup.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, shared `frontend/src/styles.css`

---

### Task 1: Lock the final-review solid structure in tests

**Files:**
- Modify: `frontend/src/features/jobs/JobFinalReviewOverlay.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("renders the final review inside the solid review work surface", () => {
  const { container } = render(
    <JobFinalReviewOverlay
      selectedJob={SAMPLE_JOB}
      report={SAMPLE_REPORT}
      onPreview={vi.fn()}
      onDownload={vi.fn()}
      onOpenFolder={vi.fn()}
    />,
  );

  expect(container.querySelector(".final-review-surface.panel")).toBeInTheDocument();
  expect(container.querySelector(".final-review-action-card")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- JobFinalReviewOverlay.test.tsx`
Expected: FAIL because the new final-review surface classes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
<aside className="panel detail-panel final-review-overlay final-review-surface">
...
<div className="activity-card final-review-action-card">
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- JobFinalReviewOverlay.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/jobs/JobFinalReviewOverlay.test.tsx frontend/src/features/jobs/JobFinalReviewOverlay.tsx
git commit -m "test: lock final review solid overlay structure"
```

### Task 2: Apply the shared warm workbench treatment to final review

**Files:**
- Modify: `frontend/src/features/jobs/JobReviewOverlay.tsx`
- Modify: `frontend/src/features/jobs/JobFinalReviewOverlay.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add final-review shell/content classes in the modal controller**

```tsx
className={[
  "review-overlay-content",
  reviewStep === "final_review" ? "final-review-overlay-content" : "",
].filter(Boolean).join(" ")}
```

- [ ] **Step 2: Add final-review surface and card classes in the overlay body**

```tsx
<aside className="panel detail-panel final-review-overlay final-review-surface">
...
<section className="detail-block final-review-section-card">
```

- [ ] **Step 3: Add CSS for the warm solid surface and unified cards**

```css
.final-review-overlay-content {
  padding: 58px 24px 24px;
  border-radius: 30px;
  background: linear-gradient(...);
}

.final-review-section-card,
.final-review-action-card {
  background: rgba(255, 255, 255, 0.78);
}
```

- [ ] **Step 4: Run focused tests**

Run: `npm test -- JobFinalReviewOverlay.test.tsx JobSummaryReviewOverlay.test.tsx JobsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/jobs/JobReviewOverlay.tsx frontend/src/features/jobs/JobFinalReviewOverlay.tsx frontend/src/styles.css
git commit -m "feat: unify final review overlay surface"
```

### Task 3: Verify the review flow

**Files:**
- Verify only: `frontend/src/features/jobs/JobFinalReviewOverlay.test.tsx`
- Verify only: `frontend/src/features/jobs/JobSummaryReviewOverlay.test.tsx`
- Verify only: `frontend/src/pages/JobsPage.test.tsx`
- Verify only: `frontend/package.json`

- [ ] **Step 1: Run targeted tests**

```bash
npm test -- JobFinalReviewOverlay.test.tsx JobSummaryReviewOverlay.test.tsx JobsPage.test.tsx JobDetailModal.test.tsx
```

- [ ] **Step 2: Run typecheck**

```bash
npm run typecheck
```

- [ ] **Step 3: Confirm expected outcome**

Expected:
- Final-review and summary-review tests both pass.
- Jobs page review routing still passes.
- TypeScript reports no errors.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-09-final-review-solid-overlay-design.md docs/superpowers/plans/2026-04-09-final-review-solid-overlay.md
git commit -m "docs: capture final review overlay redesign"
```

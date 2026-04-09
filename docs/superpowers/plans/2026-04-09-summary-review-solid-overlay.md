# Summary Review Solid Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the summary-review overlay glass treatment with a warm solid work surface while keeping the outer review mask and existing review logic intact.

**Architecture:** Keep `JobReviewOverlay` as the shared modal controller, introduce summary-review-specific surface classes in `JobSummaryReviewOverlay`, and refine shared review overlay CSS so the backdrop becomes a plain translucent mask rather than a blur layer. Lock the intended structure with focused component tests before changing the JSX and styles.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, shared `frontend/src/styles.css`

---

### Task 1: Lock the intended summary-review structure in tests

**Files:**
- Modify: `frontend/src/features/jobs/JobSummaryReviewOverlay.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("renders the summary review inside a dedicated solid work surface", () => {
  const { container } = render(
    <JobSummaryReviewOverlay
      jobId="job_1"
      jobTitle="needs_review.mp4"
      contentProfile={contentProfile}
      contentSource={{ title: "最终标题" }}
      contentDraft={{ title: "草稿标题" }}
      contentKeywords="开箱,升级"
      isConfirmingProfile={false}
      onContentFieldChange={vi.fn()}
      onKeywordsChange={vi.fn()}
      onConfirmProfile={vi.fn()}
    />,
  );

  expect(container.querySelector(".summary-review-surface.panel")).toBeInTheDocument();
  expect(container.querySelector(".summary-review-evidence-card")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- JobSummaryReviewOverlay.test.tsx`
Expected: FAIL because the new summary-review surface classes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
<section className="detail-block summary-review-surface panel">
  ...
  <div className="timeline-item summary-review-evidence-card">
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- JobSummaryReviewOverlay.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/jobs/JobSummaryReviewOverlay.test.tsx frontend/src/features/jobs/JobSummaryReviewOverlay.tsx
git commit -m "test: lock summary review solid overlay structure"
```

### Task 2: Apply the approved warm solid summary-review surface

**Files:**
- Modify: `frontend/src/features/jobs/JobSummaryReviewOverlay.tsx`
- Modify: `frontend/src/features/jobs/JobContentProfileSection.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add summary-review-specific wrappers and classes**

```tsx
<section className="detail-block summary-review-surface panel">
  <div className="summary-review-header">...</div>
  <div className="summary-review-status-card">...</div>
</section>
```

- [ ] **Step 2: Keep the editor inside the same visual system**

```tsx
<section className={["detail-block", reviewMode ? "summary-review-editor" : ""].join(" ")}>
```

- [ ] **Step 3: Add the warm solid overlay CSS**

```css
.review-overlay-backdrop {
  background: rgba(7, 10, 16, 0.64);
  backdrop-filter: none;
}

.summary-review-surface {
  background: linear-gradient(180deg, #f7f2ea, #efe6d9);
}
```

- [ ] **Step 4: Run the focused tests**

Run: `npm test -- JobSummaryReviewOverlay.test.tsx JobFinalReviewOverlay.test.tsx JobsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/jobs/JobSummaryReviewOverlay.tsx frontend/src/features/jobs/JobContentProfileSection.tsx frontend/src/styles.css
git commit -m "feat: solidify summary review overlay"
```

### Task 3: Verify no regression in the jobs review flow

**Files:**
- Verify only: `frontend/src/features/jobs/JobSummaryReviewOverlay.test.tsx`
- Verify only: `frontend/src/features/jobs/JobFinalReviewOverlay.test.tsx`
- Verify only: `frontend/src/pages/JobsPage.test.tsx`
- Verify only: `frontend/package.json`

- [ ] **Step 1: Run the targeted review-flow suite**

```bash
npm test -- JobSummaryReviewOverlay.test.tsx JobFinalReviewOverlay.test.tsx JobsPage.test.tsx
```

- [ ] **Step 2: Run typecheck if the JSX or class additions widen props**

```bash
npm run typecheck
```

- [ ] **Step 3: Confirm the expected outcome**

Expected:
- Summary-review tests pass with the new solid-surface structure.
- Final-review tests still pass.
- Jobs page review-overlay routing tests still pass.
- TypeScript reports no errors.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-09-summary-review-solid-overlay-design.md docs/superpowers/plans/2026-04-09-summary-review-solid-overlay.md
git commit -m "docs: capture summary review overlay redesign"
```

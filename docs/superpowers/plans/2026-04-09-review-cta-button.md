# Review CTA Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the jobs queue review button explicit and visually highlighted when a task is blocked on `summary_review` or `final_review`.

**Architecture:** Keep the behavior local to the jobs queue table. Compute the review CTA copy and activation state from the resolved review step in `JobQueueTable`, then attach focused CSS classes that drive the RGB marquee ring and reduced-motion fallback.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, CSS

---

### Task 1: Lock Down Queue CTA Behavior With Tests

**Files:**
- Modify: `frontend/src/features/jobs/JobQueueTable.test.tsx`
- Modify: `frontend/src/features/jobs/JobQueueTable.tsx`
- Test: `frontend/src/features/jobs/JobQueueTable.test.tsx`

- [ ] **Step 1: Write the failing test for summary review CTA copy and class**

```tsx
expect(screen.getByRole("button", { name: "需要预审核" })).toHaveClass("job-review-cta", "job-review-cta-active");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- JobQueueTable.test.tsx`
Expected: FAIL because the button still renders the old `信息核对` label and has no review CTA class.

- [ ] **Step 3: Write the failing test for final review CTA copy and class**

```tsx
expect(screen.getByRole("button", { name: "需要最终审核" })).toHaveClass("job-review-cta", "job-review-cta-active");
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npm test -- JobQueueTable.test.tsx`
Expected: FAIL because the button still renders `成片审核` and has no review CTA class.

- [ ] **Step 5: Write the failing test for non-review jobs staying unhighlighted**

```tsx
expect(screen.getByRole("button", { name: "jobs.actions.review" })).not.toHaveClass("job-review-cta-active");
```

- [ ] **Step 6: Run test to verify it fails**

Run: `npm test -- JobQueueTable.test.tsx`
Expected: FAIL if the helper logic is not yet split between explicit review states and generic review actions.

### Task 2: Implement Queue CTA State In React

**Files:**
- Modify: `frontend/src/features/jobs/JobQueueTable.tsx`
- Test: `frontend/src/features/jobs/JobQueueTable.test.tsx`

- [ ] **Step 1: Add a helper that returns the review CTA label and highlight state**

```tsx
function reviewActionState(job: Job, t: (key: string) => string) {
  const reviewStep = resolvePendingReviewStep(job);

  if (job.status === "needs_review" && reviewStep?.step_name === "summary_review") {
    return { label: "需要预审核", isHighlighted: true };
  }

  if (job.status === "needs_review" && reviewStep?.step_name === "final_review") {
    return { label: "需要最终审核", isHighlighted: true };
  }

  return { label: t("jobs.actions.review"), isHighlighted: false };
}
```

- [ ] **Step 2: Apply the new helper to the queue action button with focused classes**

```tsx
const reviewAction = reviewActionState(job, t);

<button
  className={classNames(
    "button ghost button-sm",
    "job-review-cta",
    reviewAction.isHighlighted && "job-review-cta-active",
  )}
  type="button"
  onClick={(event) => {
    event.stopPropagation();
    onSelect(job.id);
  }}
>
  {reviewAction.label}
</button>
```

- [ ] **Step 3: Run tests to verify the React behavior passes**

Run: `npm test -- JobQueueTable.test.tsx`
Expected: PASS for the CTA label and class assertions while existing row-action click coverage stays green.

### Task 3: Add RGB Marquee Styling With Reduced-Motion Fallback

**Files:**
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/features/jobs/JobQueueTable.test.tsx`

- [ ] **Step 1: Add the queue review CTA base and active styles**

```css
.job-review-cta {
  position: relative;
  isolation: isolate;
  font-weight: 700;
  transition:
    transform 180ms ease,
    box-shadow 180ms ease,
    color 180ms ease,
    border-color 180ms ease;
}

.job-review-cta-active {
  color: #a63f1f;
  border-color: rgba(45, 106, 106, 0.26);
  background: linear-gradient(180deg, rgba(255, 250, 246, 0.96), rgba(246, 239, 231, 0.94));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.75),
    0 10px 18px rgba(201, 107, 75, 0.14);
}
```

- [ ] **Step 2: Add the RGB marquee ring using pseudo-elements**

```css
.job-review-cta-active::before {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: inherit;
  padding: 1px;
  background: conic-gradient(
    from var(--review-cta-angle, 0deg),
    #ff5f6d,
    #ffc371,
    #4fd1c5,
    #5b8cff,
    #c084fc,
    #ff5f6d
  );
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: review-cta-marquee 2.6s linear infinite;
}
```

- [ ] **Step 3: Add reduced-motion fallback**

```css
@media (prefers-reduced-motion: reduce) {
  .job-review-cta,
  .job-review-cta-active,
  .job-review-cta-active::before {
    animation: none;
    transition: none;
  }
}
```

- [ ] **Step 4: Run tests after styling changes**

Run: `npm test -- JobQueueTable.test.tsx`
Expected: PASS with no behavior regressions from the class-based styling hook.

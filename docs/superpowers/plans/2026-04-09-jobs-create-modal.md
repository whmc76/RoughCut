# Jobs Create Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the jobs creation flow into a floating modal opened from the page header so the queue page no longer requires scrolling to create a task.

**Architecture:** Keep the existing `ConfigProfileSwitcher` and `JobUploadPanel` intact, wrap them in a dedicated create modal component, and let `JobsPage` own only the modal open state plus close-on-success behavior. Update page tests first so the new interaction is locked before implementation.

**Tech Stack:** React, TypeScript, Vitest, React Testing Library, existing app CSS

---

### Task 1: Lock the new interaction in Jobs page tests

**Files:**
- Modify: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Write failing tests for modal-first creation**

Add assertions that:

```tsx
expect(screen.queryByText("config-profile-switcher")).not.toBeInTheDocument();
expect(screen.queryByText("job-upload-panel")).not.toBeInTheDocument();
```

and after clicking the header button:

```tsx
await user.click(screen.getByRole("button", { name: "创建任务" }));
expect(screen.getByRole("dialog", { name: "创建任务" })).toBeInTheDocument();
expect(screen.getByText("config-profile-switcher")).toBeInTheDocument();
expect(screen.getByText("job-upload-panel")).toBeInTheDocument();
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `npm test -- JobsPage.test.tsx --runInBand`

Expected: FAIL because the page still renders the inline create area and does not render the new dialog.

- [ ] **Step 3: Add a success-close expectation**

Extend the mocked upload mutation so it can trigger `onSuccess`, then assert:

```tsx
expect(screen.queryByRole("dialog", { name: "创建任务" })).not.toBeInTheDocument();
```

- [ ] **Step 4: Re-run the focused test and keep it red**

Run: `npm test -- JobsPage.test.tsx --runInBand`

Expected: FAIL until the modal implementation is added.

### Task 2: Implement the create modal and wire Jobs page to it

**Files:**
- Create: `frontend/src/features/jobs/JobCreateModal.tsx`
- Modify: `frontend/src/pages/JobsPage.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add the modal component**

Create a dedicated component that accepts `open`, `onClose`, and `children`, locks body scroll, closes on `Escape`, and renders:

```tsx
<div className="floating-modal-backdrop" onClick={onClose} role="presentation">
  <div className="floating-modal-shell jobs-create-modal-shell" role="dialog" aria-modal="true" aria-label={title}>
    ...
  </div>
</div>
```

- [ ] **Step 2: Switch JobsPage from inline stage to modal**

Replace the inline `jobs-create-stage` block with:

```tsx
<button className="button" onClick={() => setCreateOpen(true)}>
  创建任务
</button>
```

and render the new modal with the existing two modules inside it.

- [ ] **Step 3: Close the modal after successful creation**

Use the upload mutation success callback path from the page so a successful create does:

```tsx
setCreateOpen(false);
```

while preserving the workspace mutation behavior.

- [ ] **Step 4: Add modal-specific styling**

Add a modal content grid and responsive rules so the config switcher and upload panel appear side-by-side on desktop and stacked on smaller screens.

### Task 3: Verify the new interaction end to end

**Files:**
- Modify: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Run the focused page test**

Run: `npm test -- JobsPage.test.tsx --runInBand`

Expected: PASS

- [ ] **Step 2: Run the related jobs feature tests**

Run: `npm test -- JobDetailModal.test.tsx useJobWorkspace.test.tsx --runInBand`

Expected: PASS

- [ ] **Step 3: Run a production build check**

Run: `npm run build`

Expected: build completes with exit code 0

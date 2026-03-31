# Overview And Jobs Page Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all task analysis content to the overview page so the jobs page only handles configuration, job creation, and queue execution.

**Architecture:** Keep page responsibilities explicit at the page and workspace-hook levels. `OverviewPage` and `useOverviewWorkspace` will own usage analysis state and rendering, while `JobsPage` and `useJobWorkspace` will drop unused analysis UI and state. Tests will be updated first so the new ownership is locked before implementation.

**Tech Stack:** React, TypeScript, TanStack Query, Vitest, Testing Library

---

### Task 1: Lock Page Ownership In Tests

**Files:**
- Modify: `frontend/src/pages/OverviewPage.test.tsx`
- Modify: `frontend/src/pages/JobsPage.test.tsx`
- Test: `frontend/src/pages/OverviewPage.test.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("renders the analysis module on the overview page", () => {
  // provide usageSummary data and assert the analysis panel appears
});

it("does not render the analysis module on the jobs page", () => {
  // provide usageSummary data and assert the trend panel/top metrics are absent
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`
Expected: FAIL because the current implementation still renders analysis on the jobs page and does not yet render the full analysis section on the overview page.

- [ ] **Step 3: Write minimal implementation**

```tsx
// Move the analysis section render tree from JobsPage into OverviewPage
// and remove it from JobsPage.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-03-31-overview-jobs-page-split.md frontend/src/pages/OverviewPage.test.tsx frontend/src/pages/JobsPage.test.tsx frontend/src/pages/OverviewPage.tsx frontend/src/pages/JobsPage.tsx
git commit -m "refactor: move jobs analysis to overview"
```

### Task 2: Move Analysis State To The Overview Workspace

**Files:**
- Modify: `frontend/src/features/overview/useOverviewWorkspace.ts`
- Modify: `frontend/src/features/overview/useOverviewWorkspace.test.tsx`
- Modify: `frontend/src/features/jobs/useJobWorkspace.ts`
- Modify: `frontend/src/features/jobs/useJobWorkspace.test.tsx`
- Test: `frontend/src/features/overview/useOverviewWorkspace.test.tsx`
- Test: `frontend/src/features/jobs/useJobWorkspace.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("tracks overview usage trend focus state including selected item name", async () => {
  // assert focus type and focus name drive trend queries
});

it("does not fetch usage analysis in the jobs workspace", async () => {
  // assert listJobs/config queries still run but usage queries do not
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir frontend vitest run src/features/overview/useOverviewWorkspace.test.tsx src/features/jobs/useJobWorkspace.test.tsx`
Expected: FAIL because `useOverviewWorkspace` does not yet manage `usageTrendFocusName` and `useJobWorkspace` still fetches usage analysis.

- [ ] **Step 3: Write minimal implementation**

```tsx
// Add focus-name state and trend filtering to useOverviewWorkspace.
// Remove usageSummary/usageTrend state and invalidation from useJobWorkspace.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir frontend vitest run src/features/overview/useOverviewWorkspace.test.tsx src/features/jobs/useJobWorkspace.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/overview/useOverviewWorkspace.ts frontend/src/features/overview/useOverviewWorkspace.test.tsx frontend/src/features/jobs/useJobWorkspace.ts frontend/src/features/jobs/useJobWorkspace.test.tsx
git commit -m "refactor: move jobs analysis state to overview"
```

### Task 3: Run Regression Verification

**Files:**
- Test: `frontend/src/pages/OverviewPage.test.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx`
- Test: `frontend/src/features/overview/useOverviewWorkspace.test.tsx`
- Test: `frontend/src/features/jobs/useJobWorkspace.test.tsx`

- [ ] **Step 1: Run the focused regression suite**

```bash
pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx src/features/overview/useOverviewWorkspace.test.tsx src/features/jobs/useJobWorkspace.test.tsx
```

- [ ] **Step 2: Confirm expected output**

Expected: PASS for all four test files with no new failures.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-03-31-overview-jobs-page-split.md
git commit -m "test: verify overview and jobs page split"
```

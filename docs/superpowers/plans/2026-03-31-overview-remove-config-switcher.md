# Remove Overview Config Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the clip configuration switcher from the overview page while keeping it available on the jobs page and in job review details.

**Architecture:** Limit the behavior change to the overview page so routing, config profile state, and jobs review flow remain untouched. Protect the change with page-level tests that assert overview no longer mounts the switcher and jobs still does.

**Tech Stack:** React 19, Vitest, Testing Library, TypeScript

---

### Task 1: Lock the page behavior with tests

**Files:**
- Create: `frontend/src/pages/OverviewPage.test.tsx`
- Modify: `frontend/src/pages/JobsPage.test.tsx`
- Test: `frontend/src/pages/OverviewPage.test.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("does not render the config profile switcher on the overview page", () => {
  render(<OverviewPage />);
  expect(screen.queryByText("config-profile-switcher")).not.toBeInTheDocument();
});

it("keeps the config profile switcher on the jobs page", () => {
  render(<JobsPage />);
  expect(screen.getByText("config-profile-switcher")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend vitest run frontend/src/pages/OverviewPage.test.tsx frontend/src/pages/JobsPage.test.tsx`
Expected: FAIL because `OverviewPage` still mounts `ConfigProfileSwitcher`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// OverviewPage.tsx
// remove ConfigProfileSwitcher import and component usage
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir frontend vitest run frontend/src/pages/OverviewPage.test.tsx frontend/src/pages/JobsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-03-31-overview-remove-config-switcher.md frontend/src/pages/OverviewPage.test.tsx frontend/src/pages/JobsPage.test.tsx frontend/src/pages/OverviewPage.tsx
git commit -m "refactor: keep config switcher off overview page"
```

### Task 2: Align overview copy with the new behavior

**Files:**
- Modify: `frontend/src/pages/OverviewPage.tsx`
- Test: `frontend/src/pages/OverviewPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
expect(screen.queryByText(/统一剪辑配置/)).not.toBeInTheDocument();
expect(screen.getByText(/先确认系统当前状态/)).toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend vitest run frontend/src/pages/OverviewPage.test.tsx`
Expected: FAIL because the overview summary still describes the config baseline.

- [ ] **Step 3: Write minimal implementation**

```tsx
summary={[
  { label: "先看全局", value: "任务、服务、用量", detail: "先确认健康度，再进入具体页面" },
  { label: "运行状态", value: "系统可用性", detail: "概览页只负责判断今天是否适合继续处理任务" },
  { label: "常用入口", value: "最近任务与服务状态", detail: "适合快速判断下一步该去哪一页" },
]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir frontend vitest run frontend/src/pages/OverviewPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OverviewPage.tsx frontend/src/pages/OverviewPage.test.tsx
git commit -m "copy: remove overview config baseline messaging"
```

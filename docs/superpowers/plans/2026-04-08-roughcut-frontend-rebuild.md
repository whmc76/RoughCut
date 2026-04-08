# RoughCut Frontend Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the RoughCut frontend into a five-destination editing console with merged creative surfaces, absorbed settings pages, and a new visual shell.

**Architecture:** Keep backend APIs intact while reorganizing the React route shell, page composition, and shared styling primitives. Build the redesign around a new top-level app shell, then recompose existing page features into new page responsibilities instead of rewriting feature logic from scratch.

**Tech Stack:** React 19, React Router, TanStack Query, TypeScript, Vitest, Vite CSS

---

## File Structure Map

**Primary files to modify**

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- `frontend/src/pages/OverviewPage.tsx`
- `frontend/src/pages/JobsPage.tsx`
- `frontend/src/pages/WatchRootsPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`

**Primary files to create**

- `frontend/src/pages/StyleLabPage.tsx`

**Likely supporting files to modify**

- `frontend/src/pages/StyleTemplatesPage.tsx`
- `frontend/src/pages/CreativeModesPage.tsx`
- `frontend/src/pages/CreatorProfilesPage.tsx`
- `frontend/src/pages/PackagingPage.tsx`
- `frontend/src/pages/MemoryPage.tsx`
- `frontend/src/pages/GlossaryPage.tsx`
- `frontend/src/pages/ControlPage.tsx`
- `frontend/src/components/ui/PageHeader.tsx`
- `frontend/src/components/ui/PageSection.tsx`
- `frontend/src/components/ui/PanelHeader.tsx`
- `frontend/src/pages/OverviewPage.test.tsx`
- `frontend/src/pages/JobsPage.test.tsx`
- `frontend/src/pages/SettingsPage.test.tsx`

## Task 1: Rebuild the app shell and route topology

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/pages/OverviewPage.test.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Write the failing route-shell tests**

```tsx
it("shows only the five top-level destinations in the sidebar", async () => {
  renderAppAt("/");
  expect(await screen.findByRole("link", { name: "总览" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "任务" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "监看目录" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "风格实验" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "设置" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Packaging|Style Templates|Creative Modes/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`

Expected: FAIL because the current sidebar still exposes the old route groups and labels.

- [ ] **Step 3: Implement the new shell and route map**

```tsx
const primaryNavigation = [
  { to: "/", label: "总览" },
  { to: "/jobs", label: "任务" },
  { to: "/watch-roots", label: "监看目录" },
  { to: "/style-lab", label: "风格实验" },
  { to: "/settings", label: "设置" },
];
```

- [ ] **Step 4: Update the shell styling to support the new navigation hierarchy**

```css
.app-shell {
  grid-template-columns: 108px minmax(0, 1fr);
}

.sidebar {
  padding: 22px 16px 18px;
}

.nav-link {
  border-radius: 18px;
  min-height: 44px;
}
```

- [ ] **Step 5: Run tests and typecheck**

Run:

- `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`
- `pnpm --dir frontend typecheck`

Expected: Targeted tests pass; typecheck stays green.

## Task 2: Rebuild `总览`, `任务`, and `监看目录` first screens

**Files:**

- Modify: `frontend/src/pages/OverviewPage.tsx`
- Modify: `frontend/src/pages/JobsPage.tsx`
- Modify: `frontend/src/pages/WatchRootsPage.tsx`
- Test: `frontend/src/pages/OverviewPage.test.tsx`
- Test: `frontend/src/pages/JobsPage.test.tsx`

- [ ] **Step 1: Write the failing first-screen behavior tests**

```tsx
it("keeps overview focused on runtime pressure and next actions", async () => {
  render(<OverviewPage />);
  expect(await screen.findByText(/系统状态|运行状态/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /去任务|查看任务/i })).toBeInTheDocument();
  expect(screen.queryByText("第一段")).not.toBeInTheDocument();
});
```

```tsx
it("makes the jobs queue the first-screen primary surface", async () => {
  render(<JobsPage />);
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.queryByText("第一步")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`

Expected: FAIL because the current pages still render explanatory summaries.

- [ ] **Step 3: Implement the overview and jobs first-screen rewrite**

```tsx
<PageHeader
  eyebrow="Overview"
  title="现在该处理什么"
  description={statusMessage}
  actions={<OverviewNextActions />}
/>
```

```tsx
<PageHeader
  eyebrow="Jobs"
  title="任务工作台"
  description="上传、筛选、审核和推进队列。"
  actions={<JobsToolbar />}
/>
```

- [ ] **Step 4: Reframe watch roots as an ingest surface**

```tsx
<PageHeader
  eyebrow="Watch"
  title="监看目录"
  description="看素材入口是否健康，自动链路是否在工作。"
/>
```

- [ ] **Step 5: Run tests and a focused build**

Run:

- `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`
- `pnpm --dir frontend build`

Expected: Targeted page tests pass; frontend build succeeds.

## Task 3: Merge style, creative, and creator profiles into `风格实验`

**Files:**

- Create: `frontend/src/pages/StyleLabPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/StyleTemplatesPage.tsx`
- Modify: `frontend/src/pages/CreativeModesPage.tsx`
- Modify: `frontend/src/pages/CreatorProfilesPage.tsx`

- [ ] **Step 1: Write the failing route and content tests**

```tsx
it("routes /style-lab to a merged creative control surface", async () => {
  renderAppAt("/style-lab");
  expect(await screen.findByText("风格实验")).toBeInTheDocument();
  expect(screen.getByText(/字幕|封面|增强能力/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/JobsPage.test.tsx`

Expected: FAIL because `/style-lab` does not exist yet.

- [ ] **Step 3: Implement the merged page by composing existing feature blocks**

```tsx
export function StyleLabPage() {
  return (
    <section className="page-stack style-lab-page">
      <PageHeader eyebrow="Style Lab" title="风格实验" description="先定气质，再决定增强与角色设定。" />
      <StyleDirectionStage />
      <StylePresetStage />
      <EnhancementStage />
      <CreatorProfileStage />
    </section>
  );
}
```

- [ ] **Step 4: Hide legacy standalone routes from the main shell**

```tsx
<Route path="/style-lab" element={<StyleLabPage />} />
```

- [ ] **Step 5: Run focused verification**

Run:

- `pnpm --dir frontend typecheck`
- `pnpm --dir frontend build`

Expected: Route compiles; merged page builds cleanly.

## Task 4: Absorb packaging, memory, glossary, and control into `设置`

**Files:**

- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/pages/PackagingPage.tsx`
- Modify: `frontend/src/pages/MemoryPage.tsx`
- Modify: `frontend/src/pages/GlossaryPage.tsx`
- Modify: `frontend/src/pages/ControlPage.tsx`
- Test: `frontend/src/pages/SettingsPage.test.tsx`

- [ ] **Step 1: Write the failing settings-surface tests**

```tsx
it("surfaces packaging, glossary, and memory sections inside settings", async () => {
  render(<SettingsPage />);
  expect(await screen.findByText(/输出|Packaging/i)).toBeInTheDocument();
  expect(screen.getByText(/Glossary|术语/i)).toBeInTheDocument();
  expect(screen.getByText(/Memory|记忆/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted settings test to verify it fails**

Run: `pnpm --dir frontend vitest run src/pages/SettingsPage.test.tsx`

Expected: FAIL because those sections still live on separate pages.

- [ ] **Step 3: Recompose settings into summary plus chapters**

```tsx
<PageSection eyebrow="Output" title="输出与包装" description="决定成片默认出口和包装策略。">
  <PackagingSection />
</PageSection>
```

```tsx
<PageSection eyebrow="Knowledge" title="术语与记忆" description="控制术语归一和历史偏好。">
  <GlossarySection />
  <MemorySection />
</PageSection>
```

- [ ] **Step 4: Demote system control to a secondary entry**

```tsx
<Link className="button ghost" to="/control">
  系统维护
</Link>
```

- [ ] **Step 5: Run targeted verification**

Run:

- `pnpm --dir frontend vitest run src/pages/SettingsPage.test.tsx`
- `pnpm --dir frontend typecheck`

Expected: Settings tests pass; no type regressions.

## Task 5: Replace the old card-heavy visual language

**Files:**

- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/components/ui/PageHeader.tsx`
- Modify: `frontend/src/components/ui/PageSection.tsx`
- Modify: `frontend/src/components/ui/PanelHeader.tsx`

- [ ] **Step 1: Write the failing UI expectations where practical**

```tsx
it("does not render explanatory summary strips in page headers", () => {
  render(<PageHeader title="任务工作台" description="..." />);
  expect(screen.queryByText("第一步")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted component tests to verify current mismatch**

Run: `pnpm --dir frontend vitest run src/pages/OverviewPage.test.tsx src/pages/SettingsPage.test.tsx`

Expected: FAIL where tests still depend on the old summary-card shell.

- [ ] **Step 3: Implement the new visual primitives**

```css
:root {
  --bg-base: #0b0d10;
  --bg-olive: #101512;
  --panel-soft: rgba(255, 248, 234, 0.04);
  --accent-amber: #d4a55f;
}
```

```css
.page-hero {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 18px;
}
```

- [ ] **Step 4: Remove obsolete explanatory header affordances**

```tsx
type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
};
```

- [ ] **Step 5: Run final frontend verification**

Run:

- `pnpm --dir frontend typecheck`
- `pnpm --dir frontend build`
- `pnpm --dir frontend test`

Expected:

- `typecheck`: PASS
- `build`: PASS
- `test`: existing known baseline failures may remain only in unrelated `jobs` and `watchRoots` workspace tests unless addressed by the redesign work

## Self-Review

- Spec coverage: app shell, page ownership, creative merge, settings absorption, and visual language each map to a dedicated task.
- Placeholder scan: all tasks include concrete files, commands, and code shapes.
- Type consistency: new top-level route label is consistently `风格实验` and route path is consistently `/style-lab`.

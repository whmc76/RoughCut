import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";

import { I18nProvider } from "../i18n";
import { JobsPage } from "./JobsPage";
import { SettingsPage } from "./SettingsPage";

const jobWorkspaceMock = vi.hoisted(() => vi.fn());
const settingsWorkspaceMock = vi.hoisted(() => vi.fn());

vi.mock("../features/jobs/useJobWorkspace", () => ({
  useJobWorkspace: () => jobWorkspaceMock(),
  resolveJobReviewStep: () => null,
}));

vi.mock("../features/settings/useSettingsWorkspace", () => ({
  useSettingsWorkspace: () => settingsWorkspaceMock(),
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {description ? <p>{description}</p> : null}
      {actions ? <div>{actions}</div> : null}
    </header>
  ),
}));

vi.mock("../components/ui/PageSection", () => ({
  PageSection: ({
    title,
    description,
    children,
    className,
  }: {
    title: string;
    description?: string;
    children?: ReactNode;
    className?: string;
  }) => (
    <section className={className}>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
      {children}
    </section>
  ),
}));

vi.mock("../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title, description }: { title: string; description?: string }) => (
    <div>
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
    </div>
  ),
}));

vi.mock("../features/configProfiles/ConfigProfileSwitcher", () => ({
  ConfigProfileSwitcher: ({ title, description }: { title?: string; description?: string }) => (
    <section>
      <strong>{title ?? "方案"}</strong>
      {description ? <p>{description}</p> : null}
    </section>
  ),
}));

vi.mock("../features/settings/SettingsOverviewPanel", () => ({
  SettingsOverviewPanel: () => <div data-testid="settings-overview-panel">settings overview</div>,
}));

vi.mock("../features/settings/ModelSettingsPanel", () => ({
  ModelSettingsPanel: () => <div data-testid="model-settings-panel">model settings</div>,
}));

vi.mock("../features/settings/QualitySettingsPanel", () => ({
  QualitySettingsPanel: () => <div data-testid="quality-settings-panel">quality settings</div>,
}));

vi.mock("../features/settings/RuntimeSettingsPanel", () => ({
  RuntimeSettingsPanel: () => <div data-testid="runtime-settings-panel">runtime settings</div>,
}));

vi.mock("../features/settings/BotSettingsPanel", () => ({
  BotSettingsPanel: () => <div data-testid="bot-settings-panel">bot settings</div>,
}));

vi.mock("../features/settings/CreativeSettingsPanel", () => ({
  CreativeSettingsPanel: () => <div data-testid="creative-settings-panel">creative settings</div>,
}));

vi.mock("../features/jobs/JobQueueTable", () => ({
  JobQueueTable: () => <div data-testid="job-queue-table">job queue table</div>,
}));

vi.mock("../features/jobs/JobDetailModal", () => ({
  JobDetailModal: ({
    open,
    title,
    children,
    onClose,
  }: {
    open: boolean;
    title?: string;
    children?: ReactNode;
    onClose: () => void;
  }) =>
    open ? (
      <section role="dialog" aria-label={title ?? "任务详情"}>
        <button type="button" onClick={onClose}>
          关闭
        </button>
        {children}
      </section>
    ) : null,
}));

vi.mock("../features/jobs/JobReviewOverlay", () => ({
  JobReviewOverlay: () => null,
}));

vi.mock("../features/jobs/JobDetailPanel", () => ({
  JobDetailPanel: () => <div data-testid="job-detail-panel">job detail panel</div>,
}));

function buildJobWorkspaceMock(overrides: Record<string, unknown> = {}) {
  return {
    selectedJobId: null,
    setSelectedJobId: vi.fn(),
    keyword: "",
    setKeyword: vi.fn(),
    queueFilter: "all",
    setQueueFilter: vi.fn(),
    queueStats: {
      total: 0,
      pending: 0,
      running: 0,
      done: 0,
      attention: 0,
      needsReview: 0,
      failed: 0,
      cancelled: 0,
    },
    upload: {
      files: [],
      language: "zh-CN",
      workflowTemplate: "",
      workflowMode: "standard_edit",
      enhancementModes: [],
      outputDir: "",
      videoDescription: "",
    },
    setUpload: vi.fn(),
    pendingInitialization: {
      language: "zh-CN",
      workflowTemplate: "",
      workflowMode: "standard_edit",
      enhancementModes: [],
      outputDir: "",
      videoDescription: "",
    },
    setPendingInitialization: vi.fn(),
    contentDraft: {},
    setContentDraft: vi.fn(),
    jobs: { isLoading: false, isFetching: false, isError: false, error: null, data: [] },
    detail: { isLoading: false, data: undefined },
    activity: { data: undefined },
    report: { data: undefined },
    tokenUsage: { data: undefined },
    timeline: { data: undefined },
    contentProfile: { data: undefined },
    options: { data: undefined },
    config: { data: undefined },
    packaging: { data: undefined },
    avatarMaterials: { data: undefined },
    refreshAll: vi.fn(),
    openFolder: { isPending: false, mutate: vi.fn() },
    cancelJob: { isPending: false, mutate: vi.fn() },
    restartJob: { isPending: false, mutate: vi.fn() },
    deleteJob: { isPending: false, mutate: vi.fn() },
    uploadJob: { isPending: false, mutate: vi.fn() },
    initializeJob: { isPending: false, mutate: vi.fn() },
    confirmProfile: { isPending: false, mutate: vi.fn() },
    applyReview: { isPending: false, mutate: vi.fn() },
    rerunSubtitleDecision: { isPending: false, mutate: vi.fn() },
    finalReviewDecision: { isPending: false, mutate: vi.fn() },
    filteredJobs: [],
    selectedJob: undefined,
    reviewStep: null,
    contentSource: null,
    contentKeywords: "",
    reviewWorkflowMode: "standard_edit",
    setReviewWorkflowMode: vi.fn(),
    reviewEnhancementModes: [],
    setReviewEnhancementModes: vi.fn(),
    reviewCopyStyle: "attention_grabbing",
    setReviewCopyStyle: vi.fn(),
    jobsPage: 0,
    jobsPageSize: 20,
    hasMoreJobs: false,
    setJobsPage: vi.fn(),
    restartError: null,
    ...overrides,
  };
}

function buildSettingsWorkspaceMock(overrides: Record<string, unknown> = {}) {
  return {
    form: {},
    reset: { isPending: false, mutate: vi.fn() },
    saveState: "idle",
    saveError: null,
    runtimeEnvironment: { data: { output_dir: "output" } },
    serviceStatus: { data: undefined },
    config: { data: undefined },
    configProfiles: { data: undefined },
    options: { data: undefined },
    ...overrides,
  };
}

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.localStorage.setItem("roughcut.ui.locale", "zh-CN");
  document.documentElement.lang = "zh-CN";
  jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock());
  settingsWorkspaceMock.mockReturnValue(buildSettingsWorkspaceMock());
});

afterEach(() => {
  cleanup();
});

describe("JobsPage audit interactions", () => {
  it("opens and closes the create task modal", () => {
    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));
    expect(screen.getByRole("dialog", { name: "创建任务" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭任务详情" }));
    expect(screen.queryByRole("dialog", { name: "创建任务" })).not.toBeInTheDocument();
  });
});

describe("SettingsPage audit interactions", () => {
  it("renders hidden secondary entry points and navigates to a hidden route", () => {
    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/settings"]}>
          <Routes>
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/memory" element={<div>Memory route</div>} />
            <Route path="/glossary" element={<div>Glossary route</div>} />
            <Route path="/control" element={<div>Control route</div>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(screen.getByRole("link", { name: "记忆页" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "词表页" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开控制页" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "记忆页" }));
    expect(screen.getByText("Memory route")).toBeInTheDocument();
  });

  it("does not reset settings when confirm is cancelled", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const workspace = buildSettingsWorkspaceMock();
    settingsWorkspaceMock.mockReturnValue(workspace);

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/settings"]}>
          <SettingsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "重置覆盖" }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(workspace.reset.mutate).not.toHaveBeenCalled();
  });
});

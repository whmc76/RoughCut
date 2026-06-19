import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";

import { I18nProvider } from "../i18n";
import { JobsPage } from "./JobsPage";
import { SettingsPage } from "./SettingsPage";

const jobWorkspaceMock = vi.hoisted(() => vi.fn());
const settingsWorkspaceMock = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({
  getRemixProductionTasks: vi.fn(),
  createRemixProductionTaskJob: vi.fn(),
  startRemixProductionJob: vi.fn(),
}));

vi.mock("../api", () => ({
  api: apiMock,
}));

vi.mock("../features/jobs/useJobWorkspace", () => ({
  useJobWorkspace: (options: unknown) => jobWorkspaceMock(options),
  resolveJobReviewStep: () => null,
  MATERIAL_ENHANCEMENT_OPTIONS: [
    { value: "voice_enhancement", label: "人声增强" },
    { value: "loudness_normalization", label: "响度统一" },
  ],
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
  JobQueueTable: ({ jobs, onOpenRemixProduction }: { jobs?: Array<{ id: string; source_name: string }>; onOpenRemixProduction?: (jobId: string) => void }) => (
    <div data-testid="job-queue-table">
      job queue table
      {(jobs ?? []).map((job) => (
        <button key={job.id} type="button" onClick={() => onOpenRemixProduction?.(job.id)}>
          {job.source_name}
        </button>
      ))}
    </div>
  ),
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
      jobFlowMode: "auto",
      workflowMode: "standard_edit",
      enhancementModes: [],
      selectedSmartCutRuleReasons: [],
      materialEnhancementModes: [],
      selectedAgentCapabilityKeys: [],
      hyperframesOptions: {},
      creatorCardId: "",
      executionMode: "auto",
      platformTargets: [],
      taskBrief: "",
      outputDir: "",
      videoDescription: "",
    },
    setUpload: vi.fn(),
    creatorCards: { data: { items: [] } },
    outputDirHistory: [],
    pendingInitialization: {
      language: "zh-CN",
      workflowTemplate: "",
      jobFlowMode: "auto",
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
    agentPlan: { data: undefined },
    agentDecisions: { data: undefined },
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
    refineAgentPlan: { isPending: false, mutate: vi.fn() },
    applyAgentPlan: { isPending: false, mutate: vi.fn() },
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
  apiMock.getRemixProductionTasks.mockResolvedValue({
    schema: "roughcut.remix.production_tasks.v1",
    id: "jenny_baby_bluey_script_footage_remix_pending_20260619",
    manifest_path: "E:/WorkSpace/RoughCut/data/remix_production_tasks/jenny_baby_bluey_pending.json",
    creator_profile: "jenny_baby",
    task_binding_id: "bluey_script_footage_remix",
    source_root: "F:/布鲁伊育儿节目",
    created_at: "2026-06-19",
    selection_policy: {},
    execution: {
      command: "python -m roughcut.cli remix script-footage --production-manifest data/remix_production_tasks/jenny_baby_bluey_pending.json",
      pending_episode_csv: "2,3",
      pending_count: 2,
      blocked_missing_script_count: 1,
    },
    summary: {
      task_count: 2,
      pending_count: 2,
      blocked_missing_script_count: 0,
      completed_by_user_count: 1,
      pending_file_missing_count: 0,
    },
    completed_by_user: [{ status: "done", season: 2, episode: 1, title: "跳舞模式" }],
    pending_tasks: [
      { status: "pending", season: 2, episode: 2, title: "仓储超市", script_path: "F:/布鲁伊育儿节目/布鲁伊第二季新风格育儿文案_第1-5集.md" },
      { status: "pending", season: 2, episode: 3, title: "羽毛魔杖", script_path: "F:/布鲁伊育儿节目/布鲁伊第二季新风格育儿文案_第1-5集.md" },
    ],
    blocked_missing_script_tasks: [],
    tasks: [],
  });
  apiMock.createRemixProductionTaskJob.mockResolvedValue({ id: "00000000-0000-0000-0000-000000000002" });
  apiMock.startRemixProductionJob.mockResolvedValue({
    job_id: "00000000-0000-0000-0000-000000000001",
    status: "started",
    detail: "started",
    command: [],
  });
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

    fireEvent.click(screen.getByRole("button", { name: "原片剪辑" }));
    expect(screen.getByRole("dialog", { name: "原片剪辑" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭任务详情" }));
    expect(screen.queryByRole("dialog", { name: "原片剪辑" })).not.toBeInTheDocument();
  });

  it("filters the shared task list by film remix tasks", async () => {
    const setQueueFilter = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setQueueFilter,
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "影视二创" })[1]);
    expect(setQueueFilter).toHaveBeenCalledWith("all");
    await waitFor(() => {
      expect(jobWorkspaceMock).toHaveBeenLastCalledWith(expect.objectContaining({
        taskKindFilter: "remix_production",
        additionalJobs: [],
      }));
    });
    await waitFor(() => expect(apiMock.createRemixProductionTaskJob).toHaveBeenCalledWith(2, 2));
    expect(apiMock.createRemixProductionTaskJob).toHaveBeenCalledWith(2, 3);
    expect(screen.queryByRole("dialog", { name: "影视二创" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("任务说明")).not.toBeInTheDocument();
  });

  it("opens the film remix create modal from the header action", () => {
    const setUpload = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setUpload,
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [
            { value: "remix_auto_commentary", label: "影视二创 · 自动精简解说" },
            { value: "remix_llm_plan", label: "影视二创 · 智能方案编排" },
            { value: "script_footage_remix", label: "影视二创 · 按脚本文案讲解插入" },
          ],
          enhancement_modes: [
            { value: "ai_effects", label: "智能剪辑特效" },
            { value: "multi_platform_adaptation", label: "多平台版本适配" },
          ],
          smart_cut_rules: [],
          capability_catalog: [],
        },
      },
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "影视二创" })[0]);

    expect(screen.getByRole("dialog", { name: "影视二创" })).toBeInTheDocument();
    expect(screen.getByText("影视二创模式")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /自动精简解说/ })).toHaveClass("is-active");
    expect(setUpload).toHaveBeenCalledWith(expect.any(Function));
  });

  it("opens the manual editor after creating a smart assist task", () => {
    const uploadJobMutate = vi.fn((_variables, options?: { onSuccess?: (job: { id: string }) => void }) => {
      options?.onSuccess?.({ id: "smart-job-1" });
    });
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      upload: {
        files: [new File(["video"], "demo.mp4", { type: "video/mp4" })],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "smart_assist",
        workflowMode: "standard_edit",
        enhancementModes: [],
        selectedSmartCutRuleReasons: [],
        materialEnhancementModes: [],
        selectedAgentCapabilityKeys: [],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "auto",
        platformTargets: [],
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      uploadJob: { isPending: false, mutate: uploadJobMutate },
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <Routes>
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/:jobId/manual-editor" element={<div>Manual editor route</div>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "原片剪辑" }));
    fireEvent.click(screen.getByRole("button", { name: "上传并创建任务" }));

    expect(uploadJobMutate).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Manual editor route")).toBeInTheDocument();
  });

  it("renders selectable smart cut rules and Agent capabilities in the create task modal", () => {
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      upload: {
        files: [],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "auto",
        workflowMode: "standard_edit",
        enhancementModes: ["multi_platform_adaptation"],
        selectedSmartCutRuleReasons: ["filler_word"],
        materialEnhancementModes: ["voice_enhancement"],
        selectedAgentCapabilityKeys: ["speech_density_trim"],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "auto",
        platformTargets: [],
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
          enhancement_modes: [{ value: "multi_platform_adaptation", label: "多平台版本适配" }],
          smart_cut_rules: [
            {
              reason: "filler_word",
              kind: "filler",
              risk_level: "low",
              match_surface_layer: "raw",
              label: "规则候选：口头填充音",
              auto_apply_in_auto_mode: true,
              frontend_managed_auto_cut: true,
              speech_explicit_cut: true,
              speech_review_cut: false,
              pause_cut: false,
              multimodal_review_cut: false,
              llm_review_cut: false,
            },
          ],
          capability_catalog: [
            {
              key: "speech_density_trim",
              label: "智能自动剪辑",
              layer: "editorial",
              description: "Single editorial authority for speech cleanup, pacing compression, and low-risk smart delete candidates.",
            },
          ],
        },
      },
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "原片剪辑" }));

    expect(screen.queryByLabelText("去水词/语气词")).not.toBeInTheDocument();
    expect(screen.getByLabelText("智能自动剪辑")).toBeChecked();
    expect(screen.getByText("智能自动剪辑的唯一剪辑入口；手动编辑器只暴露语气词、重复、停顿阈值和智能删减等参数覆盖。")).toBeInTheDocument();
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

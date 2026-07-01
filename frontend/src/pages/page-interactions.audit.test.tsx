// @vitest-environment jsdom

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
  getJobDownloadFiles: vi.fn(),
  jobRenderedFileUrl: vi.fn(),
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
  JobQueueTable: ({
    jobs = [],
  }: {
    jobs?: Array<{ id: string; status?: string }>;
  }) => (
    <div data-testid="job-queue-table">
      job queue table
      {jobs.map((job) => (
        job.status === "done" ? (
          <span key={job.id}>
            <a href={`/final-review?job=${encodeURIComponent(job.id)}`}>去审看</a>
          </span>
        ) : null
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
      autoGeneratePublicationMaterials: false,
      platformTargets: [],
      translationTargetLanguage: "auto",
      taskBrief: "",
      outputDir: "",
      videoDescription: "",
    },
    setUpload: vi.fn(),
    createTaskDefaultsByEntryMode: {
      source_edit: {
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
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      film_remix: {
        files: [],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "auto",
        workflowMode: "remix_auto_commentary",
        enhancementModes: [],
        selectedSmartCutRuleReasons: [],
        materialEnhancementModes: [],
        selectedAgentCapabilityKeys: [],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "auto",
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      smart_director: {
        files: [],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "auto",
        workflowMode: "smart_director",
        enhancementModes: [],
        selectedSmartCutRuleReasons: [],
        materialEnhancementModes: [],
        selectedAgentCapabilityKeys: [],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "plan_first",
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
    },
    hasStoredCreateTaskPreferencesByEntryMode: {
      source_edit: false,
      film_remix: false,
      smart_director: false,
    },
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
    confirmStrategyReviewGates: { isPending: false, mutate: vi.fn() },
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
    id: "example_script_footage_remix_pending",
    manifest_path: "C:/sample-workspace/RoughCut/data/remix_production_tasks/example_remix_pending.json",
    creator_profile: "demo_creator",
    task_binding_id: "example_script_footage_remix",
    source_root: "C:/sample-remix-source",
    created_at: "2026-06-19",
    selection_policy: {},
    execution: {
      command: "python -m roughcut.cli remix script-footage --production-manifest data/remix_production_tasks/example_remix_pending.json",
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
      { status: "pending", season: 2, episode: 2, title: "仓储超市", script_path: "C:/sample-remix-source/示例动画第二季新风格育儿文案_第1-5集.md" },
      { status: "pending", season: 2, episode: 3, title: "羽毛魔杖", script_path: "C:/sample-remix-source/示例动画第二季新风格育儿文案_第1-5集.md" },
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
  apiMock.getJobDownloadFiles.mockResolvedValue({ job_id: "job-1", files: [] });
  apiMock.jobRenderedFileUrl.mockImplementation((jobId: string, variant = "auto") => `/media/${jobId}/${variant}.mp4`);
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
          <Routes>
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/final-review" element={<div data-testid="final-review-route">成片审看路由</div>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));
    expect(screen.getByRole("dialog", { name: "全能剪辑" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭任务详情" }));
    expect(screen.queryByRole("dialog", { name: "全能剪辑" })).not.toBeInTheDocument();
  });

  it("opens the smart director create modal from the red header action", () => {
    const setUpload = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({ setUpload }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    const smartDirectorButton = screen.getAllByRole("button", { name: "智能导演" })
      .find((button) => button.classList.contains("jobs-header-smart-director-button"));
    if (!smartDirectorButton) throw new Error("Smart director header button not found");
    expect(smartDirectorButton).toHaveClass("jobs-header-smart-director-button");
    fireEvent.click(smartDirectorButton);

    expect(screen.getByRole("dialog", { name: "智能导演" })).toBeInTheDocument();
    expect(screen.getByLabelText("一句话创意与成片要求")).toBeInTheDocument();
    const updateUpload = setUpload.mock.calls[0][0] as (value: Record<string, unknown>) => Record<string, unknown>;
    expect(updateUpload({
      files: [],
      taskBrief: "",
      videoDescription: "",
    })).toEqual(expect.objectContaining({
      workflowMode: "smart_director",
      jobFlowMode: "auto",
      executionMode: "plan_first",
      autoGeneratePublicationMaterials: false,
    }));
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

    fireEvent.click(screen.getAllByRole("button", { name: "解说二创" })[1]);
    expect(setQueueFilter).toHaveBeenCalledWith("all");
    await waitFor(() => {
      expect(jobWorkspaceMock).toHaveBeenLastCalledWith(expect.objectContaining({
        taskKindFilter: "remix_production",
        additionalJobs: [],
      }));
    });
    await waitFor(() => expect(apiMock.createRemixProductionTaskJob).toHaveBeenCalledWith(2, 2));
    expect(apiMock.createRemixProductionTaskJob).toHaveBeenCalledWith(2, 3);
    expect(screen.queryByRole("dialog", { name: "解说二创" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("任务说明")).not.toBeInTheDocument();
  });

  it("passes publication and clip status filters to the jobs workspace", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "已发布" }));
    await waitFor(() => {
      expect(jobWorkspaceMock).toHaveBeenLastCalledWith(expect.objectContaining({
        publicationFilter: "published",
        clipStatusFilter: "all",
      }));
    });

    fireEvent.click(screen.getByRole("button", { name: "剪辑完成" }));

    expect(setQueueFilter).toHaveBeenCalledWith("all");
    await waitFor(() => {
      expect(jobWorkspaceMock).toHaveBeenLastCalledWith(expect.objectContaining({
        publicationFilter: "published",
        clipStatusFilter: "done",
      }));
    });
  });

  it("keeps materialized film remix jobs visible outside the current jobs page", async () => {
    apiMock.getRemixProductionTasks.mockResolvedValueOnce({
      schema: "roughcut.remix.production_tasks.v1",
      id: "example_script_footage_remix_pending",
      manifest_path: "C:/sample-workspace/RoughCut/data/remix_production_tasks/example_remix_pending.json",
      creator_profile: "demo_creator",
      task_binding_id: "example_script_footage_remix",
      source_root: "C:/sample-remix-source",
      created_at: "2026-06-19",
      selection_policy: {},
      execution: { pending_count: 1, blocked_missing_script_count: 0 },
      summary: {
        task_count: 1,
        pending_count: 1,
        blocked_missing_script_count: 0,
        completed_by_user_count: 0,
        pending_file_missing_count: 0,
      },
      completed_by_user: [],
      pending_tasks: [
        {
          status: "pending",
          season: 2,
          episode: 4,
          title: "避球",
          script_path: "C:/sample-remix-source/示例动画第二季新风格育儿文案_第1-5集.md",
          job_id: "b5944520-3507-4acf-a463-0c0ef32e08b4",
          job_status: "pending",
          job_updated_at: "2026-06-19T02:11:17.636109+08:00",
          job_progress_percent: 0,
        },
      ],
      blocked_missing_script_tasks: [],
      tasks: [
        {
          status: "pending",
          season: 2,
          episode: 4,
          title: "避球",
          script_path: "C:/sample-remix-source/示例动画第二季新风格育儿文案_第1-5集.md",
          job_id: "b5944520-3507-4acf-a463-0c0ef32e08b4",
          job_status: "pending",
          job_updated_at: "2026-06-19T02:11:17.636109+08:00",
          job_progress_percent: 0,
        },
      ],
    });

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(jobWorkspaceMock).toHaveBeenLastCalledWith(expect.objectContaining({
        additionalJobs: [
          expect.objectContaining({
            id: "b5944520-3507-4acf-a463-0c0ef32e08b4",
            source_name: "S02E04 · 避球",
            queue_task_kind: "remix_production",
            workflow_mode: "script_footage_remix",
          }),
        ],
      }));
    });
    expect(apiMock.createRemixProductionTaskJob).not.toHaveBeenCalled();
  });

  it("surfaces production handoff as the first jobs workflow", async () => {
    apiMock.getJobDownloadFiles.mockResolvedValueOnce({
      job_id: "job-1",
      files: [
        {
          id: "enhanced_mp4",
          label: "增强成片",
          filename: "final-enhanced.mp4",
          kind: "video",
          size_bytes: 1048576,
          recommended: true,
        },
      ],
    });
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      queueStats: {
        total: 3,
        pending: 1,
        running: 1,
        done: 1,
        attention: 1,
        needsReview: 1,
        failed: 0,
        cancelled: 0,
      },
      filteredJobs: [
        {
          id: "job-1",
          source_name: "成片测试.mp4",
          status: "done",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          job_flow_mode: "auto",
          enhancement_modes: [],
          progress_percent: 100,
          publication_summary: "B站和视频号待发布",
          created_at: "2026-06-29T10:00:00Z",
          updated_at: "2026-06-29T10:30:00Z",
          steps: [],
        },
        {
          id: "job-2",
          source_name: "生产中.mp4",
          status: "running",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          job_flow_mode: "auto",
          enhancement_modes: [],
          progress_percent: 42,
          created_at: "2026-06-29T09:00:00Z",
          updated_at: "2026-06-29T10:20:00Z",
          steps: [],
        },
        {
          id: "job-3",
          source_name: "待核对.mp4",
          status: "needs_review",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          job_flow_mode: "auto",
          enhancement_modes: [],
          progress_percent: 80,
          created_at: "2026-06-29T08:00:00Z",
          updated_at: "2026-06-29T10:10:00Z",
          steps: [],
        },
      ],
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <JobsPage />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(screen.getByLabelText("制片队列工作台")).toBeInTheDocument();
    expect(screen.getByText("Production Queue")).toBeInTheDocument();
    expect(screen.getByText("生产状态带")).toBeInTheDocument();
    expect(screen.getByText("完成输出")).toBeInTheDocument();
    expect(screen.getByText("成片测试.mp4")).toBeInTheDocument();

    const finalReviewLink = screen.getByRole("link", { name: "审看完成输出" });
    expect(finalReviewLink).toHaveAttribute("href", "/final-review?job=job-1");
    expect(apiMock.getJobDownloadFiles).not.toHaveBeenCalled();
  });

  it("routes completed queue jobs to final review without queue-level publication or download actions", async () => {
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      filteredJobs: [
        {
          id: "job-1",
          source_name: "成片测试.mp4",
          status: "done",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          job_flow_mode: "auto",
          enhancement_modes: [],
          progress_percent: 100,
          created_at: "2026-06-29T10:00:00Z",
          updated_at: "2026-06-29T10:30:00Z",
          steps: [],
        },
      ],
    }));

    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/jobs"]}>
          <Routes>
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/final-review" element={<div data-testid="final-review-route">成片审看路由</div>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(screen.getByRole("link", { name: "去审看" })).toHaveAttribute("href", "/final-review?job=job-1");
    expect(screen.queryByRole("link", { name: "发布交接" })).not.toBeInTheDocument();
    expect(apiMock.getJobDownloadFiles).not.toHaveBeenCalled();
    expect(apiMock.jobRenderedFileUrl).not.toHaveBeenCalled();
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
            { value: "remix_auto_commentary", label: "解说二创 · 自动精简解说" },
            { value: "remix_llm_plan", label: "解说二创 · 智能方案编排" },
            { value: "script_footage_remix", label: "解说二创 · 按脚本文案讲解插入" },
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

    fireEvent.click(screen.getAllByRole("button", { name: "解说二创" })[0]);

    expect(screen.getByRole("dialog", { name: "解说二创" })).toBeInTheDocument();
    expect(screen.getByText("解说二创模式")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建任务" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始剪辑" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /自动精简解说/ })).toHaveClass("is-active");
    expect(setUpload).toHaveBeenCalledWith(expect.any(Function));
    const updateUpload = setUpload.mock.calls[0][0] as (value: Record<string, unknown>) => Record<string, unknown>;
    const nextUpload = updateUpload({
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
      autoGeneratePublicationMaterials: false,
      platformTargets: [],
      translationTargetLanguage: "auto",
      taskBrief: "",
      outputDir: "",
      videoDescription: "",
    });
    expect(nextUpload.workflowMode).toBe("remix_auto_commentary");
    expect(nextUpload.enhancementModes).toEqual(["ai_effects"]);
  });

  it("restores the previous film remix create-task scheme without re-adding defaults", () => {
    const setUpload = vi.fn();
    const previousFilmRemixScheme = {
      files: [],
      language: "zh-CN",
      workflowTemplate: "",
      jobFlowMode: "auto",
      workflowMode: "script_footage_remix",
      enhancementModes: [],
      selectedSmartCutRuleReasons: [],
      materialEnhancementModes: ["voice_enhancement"],
      selectedAgentCapabilityKeys: ["multi_material_assembly"],
      hyperframesOptions: { subtitle_emphasis: false, unified_subtitle_style: true },
      creatorCardId: "creator-1",
      executionMode: "plan_first",
      autoGeneratePublicationMaterials: false,
      platformTargets: [],
      translationTargetLanguage: "auto",
      taskBrief: "",
      outputDir: "D:/renders",
      videoDescription: "",
    };
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setUpload,
      createTaskDefaultsByEntryMode: {
        source_edit: previousFilmRemixScheme,
        film_remix: previousFilmRemixScheme,
      },
      hasStoredCreateTaskPreferencesByEntryMode: {
        source_edit: false,
        film_remix: true,
      },
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [
            { value: "remix_auto_commentary", label: "解说二创 · 自动精简解说" },
            { value: "script_footage_remix", label: "解说二创 · 按脚本文案讲解插入" },
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

    fireEvent.click(screen.getAllByRole("button", { name: "解说二创" })[0]);

    const updateUpload = setUpload.mock.calls[0][0] as (value: Record<string, unknown>) => Record<string, unknown>;
    const nextUpload = updateUpload({
      ...previousFilmRemixScheme,
      files: [new File(["video"], "demo.mp4", { type: "video/mp4" })],
      taskBrief: "保留当前任务文案",
      videoDescription: "保留当前任务文案",
    });
    expect(nextUpload.workflowMode).toBe("script_footage_remix");
    expect(nextUpload.enhancementModes).toEqual([]);
    expect(nextUpload.selectedAgentCapabilityKeys).toEqual(["multi_material_assembly"]);
    expect(nextUpload.hyperframesOptions).toEqual({ subtitle_emphasis: false, unified_subtitle_style: true });
    expect(nextUpload.files).toHaveLength(1);
    expect(nextUpload.taskBrief).toBe("保留当前任务文案");
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
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
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

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));
    fireEvent.click(screen.getByRole("button", { name: "开始剪辑" }));

    expect(uploadJobMutate).toHaveBeenCalledTimes(1);
    expect(uploadJobMutate).toHaveBeenCalledWith(
      { createEntryMode: "source_edit", startMode: "immediate" },
      expect.any(Object),
    );
    expect(screen.getByText("Manual editor route")).toBeInTheDocument();
  });

  it("creates a queued task without starting when using the create-task button", () => {
    const uploadJobMutate = vi.fn((_variables, options?: { onSuccess?: (job: { id: string }) => void }) => {
      options?.onSuccess?.({ id: "queued-job-1" });
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
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
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

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));
    expect(screen.getByRole("button", { name: "创建任务" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始剪辑" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    expect(uploadJobMutate).toHaveBeenCalledWith(
      { createEntryMode: "source_edit", startMode: "manual" },
      expect.any(Object),
    );
    expect(screen.queryByText("Manual editor route")).not.toBeInTheDocument();
  });

  it("renders selectable smart cut rules and Agent capabilities in the create task modal", () => {
    const setUpload = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setUpload,
      upload: {
        files: [],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "auto",
        workflowMode: "standard_edit",
        enhancementModes: ["multi_platform_adaptation"],
        selectedSmartCutRuleReasons: ["filler_word", "catchphrase_phrase", "silence", "pause"],
        materialEnhancementModes: ["voice_enhancement"],
        selectedAgentCapabilityKeys: ["speech_density_trim"],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "auto",
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
          enhancement_modes: [
            { value: "multi_platform_adaptation", label: "多平台版本适配" },
            { value: "ai_effects", label: "智能剪辑特效" },
          ],
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
            {
              reason: "catchphrase_phrase",
              kind: "catchphrase",
              risk_level: "low",
              match_surface_layer: "raw",
              label: "规则候选：口头禅",
              auto_apply_in_auto_mode: true,
              frontend_managed_auto_cut: true,
              speech_explicit_cut: false,
              speech_review_cut: false,
              pause_cut: false,
              multimodal_review_cut: false,
              llm_review_cut: false,
            },
            {
              reason: "silence",
              kind: "pause",
              risk_level: "low",
              match_surface_layer: "raw",
              label: "规则候选：停顿",
              auto_apply_in_auto_mode: true,
              frontend_managed_auto_cut: true,
              speech_explicit_cut: false,
              speech_review_cut: true,
              pause_cut: true,
              multimodal_review_cut: false,
              llm_review_cut: false,
            },
            {
              reason: "pause",
              kind: "pause",
              risk_level: "low",
              match_surface_layer: "raw",
              label: "规则候选：停顿",
              auto_apply_in_auto_mode: true,
              frontend_managed_auto_cut: false,
              speech_explicit_cut: false,
              speech_review_cut: false,
              pause_cut: true,
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

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));

    expect(screen.queryByLabelText("智能剪辑特效")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("多平台版本适配")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("智能自动剪辑")).not.toBeInTheDocument();
    expect(screen.getByText("选择需要启用的成片能力；自动剪辑细项可单独选择。")).toBeInTheDocument();
    expect(screen.getByLabelText("语气词与口头禅")).toBeChecked();
    expect(screen.getByLabelText("停顿与节奏收边")).toBeChecked();
    expect(screen.queryByLabelText("口头填充音")).not.toBeInTheDocument();
    expect(screen.queryAllByLabelText("停顿")).toHaveLength(0);

    fireEvent.click(screen.getByLabelText("语气词与口头禅"));

    expect(setUpload).toHaveBeenCalledWith(expect.objectContaining({
      selectedAgentCapabilityKeys: ["speech_density_trim"],
      selectedSmartCutRuleReasons: ["silence", "pause"],
    }));
  });

  it("toggles automatic publication material generation from the create task modal", () => {
    const setUpload = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setUpload,
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
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "auto",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
          enhancement_modes: [],
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

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));
    fireEvent.click(screen.getByLabelText("自动生成发布物料"));

    expect(setUpload).toHaveBeenCalledWith(expect.objectContaining({
      autoGeneratePublicationMaterials: true,
    }));
  });

  it("shows a second-language selector when subtitle translation is enabled", () => {
    const setUpload = vi.fn();
    jobWorkspaceMock.mockReturnValue(buildJobWorkspaceMock({
      setUpload,
      upload: {
        files: [],
        language: "zh-CN",
        workflowTemplate: "",
        jobFlowMode: "auto",
        workflowMode: "standard_edit",
        enhancementModes: ["multilingual_translation"],
        selectedSmartCutRuleReasons: [],
        materialEnhancementModes: [],
        selectedAgentCapabilityKeys: [],
        hyperframesOptions: {},
        creatorCardId: "",
        executionMode: "auto",
        autoGeneratePublicationMaterials: false,
        platformTargets: [],
        translationTargetLanguage: "ja-JP",
        taskBrief: "",
        outputDir: "",
        videoDescription: "",
      },
      options: {
        data: {
          job_languages: [{ value: "zh-CN", label: "简体中文" }],
          workflow_templates: [{ value: "", label: "自动匹配" }],
          workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
          enhancement_modes: [{ value: "multilingual_translation", label: "多语言翻译" }],
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

    fireEvent.click(screen.getByRole("button", { name: "全能剪辑" }));

    expect(screen.getByLabelText("生成字幕译文")).toBeChecked();
    expect(screen.getByLabelText("字幕第二语言")).toHaveValue("ja-JP");
    expect(screen.getByRole("option", { name: "自动（英文/中文）" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("字幕第二语言"), { target: { value: "ko-KR" } });

    expect(setUpload).toHaveBeenCalledWith(expect.objectContaining({
      translationTargetLanguage: "ko-KR",
    }));
  });
});
describe("SettingsPage audit interactions", () => {
  it("renders unified secondary entry points and navigates to the knowledge calibration route", () => {
    renderWithQueryClient(
      <I18nProvider>
        <MemoryRouter initialEntries={["/settings"]}>
          <Routes>
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/terms-memory" element={<div>Terms memory route</div>} />
            <Route path="/control" element={<div>Control route</div>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(screen.getAllByRole("link", { name: "打开术语与记忆" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "打开服务控制" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("link", { name: "打开术语与记忆" })[0]);
    expect(screen.getByText("Terms memory route")).toBeInTheDocument();
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

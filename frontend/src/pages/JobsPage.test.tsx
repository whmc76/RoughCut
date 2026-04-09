import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { JobsPage } from "./JobsPage";

const mockUseJobWorkspace = vi.fn();
const mockJobDetailModal = vi.fn();
const mockJobReviewOverlay = vi.fn();

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
  getCurrentUiLocale: () => "zh-CN",
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, actions }: { title: string; actions?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  ),
}));

vi.mock("../components/ui/PageSection", () => ({
  PageSection: ({ title, children, className }: { title: string; children: ReactNode; className?: string }) => (
    <section className={className ?? ""}>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}));

vi.mock("../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title }: { title: string }) => <strong>{title}</strong>,
}));

vi.mock("../components/ui/StatCard", () => ({
  StatCard: ({ label, value }: { label: string; value: string | number }) => (
    <div>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  ),
}));

vi.mock("../features/configProfiles/ConfigProfileSwitcher", () => ({
  ConfigProfileSwitcher: () => <div>config-profile-switcher</div>,
}));

vi.mock("../features/jobs/JobUploadPanel", () => ({
  JobUploadPanel: ({ onSubmit }: { onSubmit: () => void }) => (
    <div>
      <div>job-upload-panel</div>
      <button type="button" onClick={onSubmit}>
        submit-job
      </button>
    </div>
  ),
}));

vi.mock("../features/jobs/JobQueueTable", () => ({
  JobQueueTable: ({
    jobs,
    onSelect,
    onOpenReview,
  }: {
    jobs?: Array<{ id: string; source_name: string }>;
    onSelect?: (jobId: string) => void;
    onOpenReview?: (jobId: string) => void;
  }) => (
    <div>
      <div>job-queue-table</div>
      {jobs?.map((job) => (
        <div key={job.id}>
          <button type="button" onClick={() => onSelect?.(job.id)}>
            {`select-${job.source_name}`}
          </button>
          <button type="button" onClick={() => onOpenReview?.(job.id)}>
            {`review-${job.source_name}`}
          </button>
        </div>
      ))}
    </div>
  ),
}));

vi.mock("../features/jobs/JobDetailPanel", () => ({
  JobDetailPanel: () => <div>job-detail-panel</div>,
}));

vi.mock("../features/jobs/JobDetailModal", () => ({
  JobDetailModal: ({ children, open }: { children: ReactNode; open: boolean }) => {
    mockJobDetailModal({ open });
    return open ? <div data-testid="job-detail-modal">{children}</div> : null;
  },
}));

vi.mock("../features/jobs/JobReviewOverlay", () => ({
  JobReviewOverlay: ({ open, reviewStep }: { open: boolean; reviewStep?: string | null }) => {
    mockJobReviewOverlay({ open, reviewStep });
    return open ? <div data-testid="job-review-overlay">{reviewStep}</div> : null;
  },
}));

vi.mock("../features/jobs/JobsUsageTrendPanel", () => ({
  JobsUsageTrendPanel: () => <div>usage-trend-panel</div>,
}));

vi.mock("../features/jobs/useJobWorkspace", () => ({
  useJobWorkspace: () => mockUseJobWorkspace(),
}));

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    keyword: "",
    setKeyword: vi.fn(),
    refreshAll: vi.fn(),
    usageSummary: { data: undefined },
    usageTrend: { data: [] },
    usageTrendDays: 7,
    usageTrendFocusType: "all",
    usageTrendFocusName: "",
    setUsageTrendDays: vi.fn(),
    setUsageTrendFocusType: vi.fn(),
    setUsageTrendFocusName: vi.fn(),
    options: { data: undefined },
    upload: {},
    setUpload: vi.fn(),
    uploadJob: { mutate: vi.fn(), isPending: false },
    filteredJobs: [],
    jobs: { isLoading: false, isError: false, error: null },
    selectedJobId: null,
    selectedJob: undefined,
    detail: { isLoading: false },
    activity: { data: undefined },
    report: { data: undefined },
    tokenUsage: { data: undefined },
    timeline: { data: undefined },
    contentProfile: { data: undefined },
    config: { data: undefined },
    packaging: { data: undefined },
    avatarMaterials: { data: undefined },
    contentSource: undefined,
    contentDraft: { keywords: [] },
    contentKeywords: [],
    reviewEnhancementModes: [],
    confirmProfile: { mutate: vi.fn(), isPending: false },
    applyReview: { mutate: vi.fn(), isPending: false },
    finalReviewDecision: { mutate: vi.fn(), isPending: false },
    cancelJob: { mutate: vi.fn(), isPending: false },
    restartJob: { mutate: vi.fn(), isPending: false },
    deleteJob: { mutate: vi.fn(), isPending: false },
    setSelectedJobId: vi.fn(),
    setContentDraft: vi.fn(),
    openFolder: { mutate: vi.fn(), isPending: false },
    ...overrides,
  };
}

describe("JobsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("keeps the queue surface visible while create modules stay hidden by default", () => {
    mockUseJobWorkspace.mockReturnValue(buildWorkspace());

    const { container } = render(<JobsPage />);
    const createButton = screen.getByRole("button", { name: "创建任务" });
    const refreshButton = screen.getByRole("button", { name: "jobs.page.refresh" });

    expect(container.querySelector(".jobs-command-deck")).toBeInTheDocument();
    expect(container.querySelector(".jobs-queue-stage")).toBeInTheDocument();
    expect(container.querySelector(".jobs-header-toolbar")).toBeInTheDocument();
    expect(container.querySelector(".jobs-header-search-input")).toBeInTheDocument();
    expect(refreshButton).toHaveClass("jobs-header-subtle-button");
    expect(refreshButton).not.toHaveClass("ghost");
    expect(createButton).toHaveClass("primary", "jobs-header-create-button");
    expect(screen.getByText("job-queue-table")).toBeInTheDocument();
    expect(screen.queryByText("config-profile-switcher")).not.toBeInTheDocument();
    expect(screen.queryByText("job-upload-panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "创建任务" })).not.toBeInTheDocument();
  });

  it("does not render the old summary strip or instructional copy on the jobs page", () => {
    mockUseJobWorkspace.mockReturnValue(buildWorkspace());

    render(<JobsPage />);

    expect(screen.queryByText("第一步")).not.toBeInTheDocument();
    expect(screen.queryByText("第二步")).not.toBeInTheDocument();
    expect(screen.queryByText("第三步")).not.toBeInTheDocument();
    expect(screen.queryByText("创建任务与设置默认参数")).not.toBeInTheDocument();
    expect(screen.queryByText("跟进任务队列与审核详情")).not.toBeInTheDocument();
  });

  it("opens the create modal from the header button", () => {
    mockUseJobWorkspace.mockReturnValue(buildWorkspace());

    const { container } = render(<JobsPage />);

    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    expect(screen.getByText("任务列表")).toBeInTheDocument();
    expect(screen.getByText("需要处理")).toBeInTheDocument();
    expect(container.querySelector(".jobs-command-deck")).toBeInTheDocument();
    expect(container.querySelector(".jobs-active-band")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "创建任务" })).toBeInTheDocument();
    expect(screen.getByText("剪辑方案 + 创建任务")).toBeInTheDocument();
    expect(screen.getByText("config-profile-switcher")).toBeInTheDocument();
    expect(screen.getByText("job-upload-panel")).toBeInTheDocument();
  });

  it("closes the create modal after a successful job creation", () => {
    const uploadMutate = vi.fn((_: unknown, options?: { onSuccess?: (job: { id: string }) => void }) => {
      options?.onSuccess?.({ id: "job-created-1" });
    });

    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        uploadJob: { mutate: uploadMutate, isPending: false },
      }),
    );

    render(<JobsPage />);

    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));
    expect(screen.getByRole("dialog", { name: "创建任务" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "submit-job" }));

    expect(uploadMutate).toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "创建任务" })).not.toBeInTheDocument();
  });

  it("does not render the analysis module on the jobs page", () => {
    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        usageSummary: {
          data: {
            job_count: 2,
            jobs_with_telemetry: 1,
            total_calls: 5,
            total_prompt_tokens: 3200,
            total_completion_tokens: 900,
            total_tokens: 4100,
            cache: {
              total_entries: 2,
              hits: 1,
              misses: 1,
              hit_rate: 0.5,
              avoided_calls: 1,
              steps_with_hits: 1,
              hits_with_usage_baseline: 1,
              saved_prompt_tokens: 2400,
              saved_completion_tokens: 700,
              saved_total_tokens: 3100,
              saved_tokens_hit_rate: 1,
            },
            top_steps: [],
            top_models: [],
            top_providers: [],
          },
        },
      }),
    );

    render(<JobsPage />);

    expect(screen.queryByText("usage-trend-panel")).not.toBeInTheDocument();
    expect(screen.queryByText("jobs.summary.topSteps")).not.toBeInTheDocument();
    expect(screen.getByText("任务列表")).toBeInTheDocument();
  });

  it("opens final-review jobs in the dedicated review overlay only from the review action button", () => {
    const setSelectedJobId = vi.fn();

    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        filteredJobs: [
          {
            id: "job-review-1",
            source_name: "needs_review.mp4",
            content_subject: "测试主题",
            content_summary: "测试摘要",
            status: "needs_review",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-02T02:00:00Z",
            updated_at: "2026-04-02T02:10:00Z",
            steps: [
              {
                id: "final-step",
                step_name: "final_review",
                status: "pending",
                attempt: 0,
                started_at: null,
                finished_at: null,
                error_message: null,
              },
            ],
          },
        ],
        selectedJobId: "job-review-1",
        selectedJob: {
          id: "job-review-1",
          source_name: "needs_review.mp4",
          content_subject: "测试主题",
          content_summary: "测试摘要",
          status: "needs_review",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T02:00:00Z",
          updated_at: "2026-04-02T02:10:00Z",
          steps: [],
        },
        activity: {
          data: {
            current_step: {
              step_name: "final_review",
              label: "成片审核",
              status: "pending",
              detail: "等待审核成片后继续。",
            },
          },
        },
        setSelectedJobId,
      }),
    );

    render(<JobsPage />);
    fireEvent.click(screen.getByRole("button", { name: "review-needs_review.mp4" }));

    expect(setSelectedJobId).toHaveBeenCalledWith("job-review-1");
    expect(screen.getByTestId("job-review-overlay")).toHaveTextContent("final_review");
    expect(screen.queryByTestId("job-detail-modal")).not.toBeInTheDocument();
    expect(mockJobReviewOverlay).toHaveBeenCalled();
  });

  it("opens the detail modal when clicking a needs_review task row", () => {
    const setSelectedJobId = vi.fn();

    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        filteredJobs: [
          {
            id: "job-review-3",
            source_name: "summary-review.mp4",
            content_subject: "测试主题",
            content_summary: "测试摘要",
            status: "needs_review",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-02T02:00:00Z",
            updated_at: "2026-04-02T02:10:00Z",
            steps: [
              {
                id: "summary-step",
                step_name: "summary_review",
                status: "pending",
                attempt: 0,
                started_at: null,
                finished_at: null,
                error_message: null,
              },
            ],
          },
        ],
        selectedJobId: "job-review-3",
        selectedJob: {
          id: "job-review-3",
          source_name: "summary-review.mp4",
          content_subject: "测试主题",
          content_summary: "测试摘要",
          status: "needs_review",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T02:00:00Z",
          updated_at: "2026-04-02T02:10:00Z",
          steps: [
            {
              id: "summary-step",
              step_name: "summary_review",
              status: "pending",
              attempt: 0,
              started_at: null,
              finished_at: null,
              error_message: null,
            },
          ],
        },
        activity: {
          data: {
            current_step: {
              step_name: "summary_review",
              label: "信息核对",
              status: "pending",
              detail: "等待校对内容信息后继续。",
            },
          },
        },
        setSelectedJobId,
      }),
    );

    render(<JobsPage />);
    fireEvent.click(screen.getByRole("button", { name: "select-summary-review.mp4" }));

    expect(setSelectedJobId).toHaveBeenCalledWith("job-review-3");
    expect(screen.getByTestId("job-detail-modal")).toBeInTheDocument();
    expect(screen.queryByTestId("job-review-overlay")).not.toBeInTheDocument();
  });

  it("opens the dedicated review overlay only from the review action button", () => {
    const setSelectedJobId = vi.fn();

    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        filteredJobs: [
          {
            id: "job-review-4",
            source_name: "summary-review-action.mp4",
            content_subject: "测试主题",
            content_summary: "测试摘要",
            status: "needs_review",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-02T02:00:00Z",
            updated_at: "2026-04-02T02:10:00Z",
            steps: [
              {
                id: "summary-step",
                step_name: "summary_review",
                status: "pending",
                attempt: 0,
                started_at: null,
                finished_at: null,
                error_message: null,
              },
            ],
          },
        ],
        selectedJobId: "job-review-4",
        selectedJob: {
          id: "job-review-4",
          source_name: "summary-review-action.mp4",
          content_subject: "测试主题",
          content_summary: "测试摘要",
          status: "needs_review",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T02:00:00Z",
          updated_at: "2026-04-02T02:10:00Z",
          steps: [
            {
              id: "summary-step",
              step_name: "summary_review",
              status: "pending",
              attempt: 0,
              started_at: null,
              finished_at: null,
              error_message: null,
            },
          ],
        },
        activity: {
          data: {
            current_step: {
              step_name: "summary_review",
              label: "信息核对",
              status: "pending",
              detail: "等待校对内容信息后继续。",
            },
          },
        },
        setSelectedJobId,
      }),
    );

    render(<JobsPage />);
    fireEvent.click(screen.getByRole("button", { name: "review-summary-review-action.mp4" }));

    expect(setSelectedJobId).toHaveBeenCalledWith("job-review-4");
    expect(screen.getByTestId("job-review-overlay")).toHaveTextContent("summary_review");
    expect(screen.queryByTestId("job-detail-modal")).not.toBeInTheDocument();
  });

  it("keeps pending jobs out of the dedicated review overlay even with summary review step", () => {
    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        selectedJobId: "job-review-2",
        selectedJob: {
          id: "job-review-2",
          source_name: "pending-review.mp4",
          content_subject: "测试主题",
          content_summary: "测试摘要",
          status: "pending",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T02:00:00Z",
          updated_at: "2026-04-02T02:10:00Z",
          steps: [
            {
              id: "summary-step",
              step_name: "summary_review",
              status: "pending",
              attempt: 0,
              started_at: null,
              finished_at: null,
              error_message: null,
            },
          ],
        },
        activity: {
          data: {
            current_step: {
              step_name: "summary_review",
              label: "信息核对",
              status: "pending",
              detail: "等待校对内容信息后继续。",
            },
          },
        },
      }),
    );

    render(<JobsPage />);

    expect(screen.getByTestId("job-detail-modal")).toBeInTheDocument();
    expect(screen.queryByTestId("job-review-overlay")).not.toBeInTheDocument();
  });

  it("keeps non-review jobs in the standard detail modal flow", () => {
    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
        selectedJobId: "job-running-1",
        selectedJob: {
          id: "job-running-1",
          source_name: "running.mp4",
          content_subject: "测试主题",
          content_summary: "测试摘要",
          status: "processing",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T02:00:00Z",
          updated_at: "2026-04-02T02:10:00Z",
          steps: [],
        },
      }),
    );

    render(<JobsPage />);

    expect(screen.getByTestId("job-detail-modal")).toBeInTheDocument();
    expect(screen.queryByTestId("job-review-overlay")).not.toBeInTheDocument();
  });
});

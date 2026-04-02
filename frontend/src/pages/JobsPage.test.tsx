import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

import { JobsPage } from "./JobsPage";

const mockUseJobWorkspace = vi.fn();
const mockJobDetailModal = vi.fn();
const mockJobReviewOverlay = vi.fn();

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
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
  PageSection: ({ title, children }: { title: string; children: ReactNode }) => (
    <section>
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
  JobUploadPanel: () => <div>job-upload-panel</div>,
}));

vi.mock("../features/jobs/JobQueueTable", () => ({
  JobQueueTable: () => <div>job-queue-table</div>,
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

  it("keeps the config profile switcher on the jobs page", () => {
    mockUseJobWorkspace.mockReturnValue(buildWorkspace());

    render(<JobsPage />);

    expect(screen.getByText("config-profile-switcher")).toBeInTheDocument();
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
  });

  it("routes needs_review jobs into the dedicated review overlay instead of the detail modal", () => {
    mockUseJobWorkspace.mockReturnValue(
      buildWorkspace({
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
      }),
    );

    render(<JobsPage />);

    expect(screen.getByTestId("job-review-overlay")).toHaveTextContent("final_review");
    expect(screen.queryByTestId("job-detail-modal")).not.toBeInTheDocument();
    expect(mockJobReviewOverlay).toHaveBeenCalled();
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

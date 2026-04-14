import { fireEvent, render, screen } from "@testing-library/react";

import { JobQueueTable } from "./JobQueueTable";

const { mockContentProfileThumbnailUrl } = vi.hoisted(() => ({
  mockContentProfileThumbnailUrl: vi.fn(() => "/thumb.png"),
}));

vi.mock("../../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
  getCurrentUiLocale: () => "zh-CN",
  translate: (_locale: string, key: string) => key,
}));

vi.mock("../../api", () => ({
  api: {
    contentProfileThumbnailUrl: mockContentProfileThumbnailUrl,
  },
}));

function buildJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    source_name: "sample.mp4",
    content_subject: "测试主题",
    content_summary: "测试摘要",
    status: "needs_review",
    language: "zh-CN",
    workflow_mode: "standard_edit",
    enhancement_modes: [],
    auto_review_mode_enabled: false,
    auto_review_status: null,
    auto_review_summary: null,
    auto_review_reasons: [],
    created_at: "2026-04-02T02:00:00Z",
    updated_at: "2026-04-02T02:10:00Z",
    progress_percent: 86,
    steps: [],
    ...overrides,
  };
}

describe("JobQueueTable", () => {
  beforeEach(() => {
    mockContentProfileThumbnailUrl.mockClear();
    mockContentProfileThumbnailUrl.mockReturnValue("/thumb.png");
  });

  it("shows final-review jobs as 最终核对 in the status column", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            steps: [
              { id: "s1", step_name: "final_review", status: "pending", attempt: 0, started_at: null, finished_at: null, error_message: null },
            ],
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByText("最终核对")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需要最终审核" })).toHaveClass("job-review-cta", "job-review-cta-active");
  });

  it("shows summary-review jobs as 预审核 in the status column", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-2",
            steps: [
              { id: "s2", step_name: "summary_review", status: "pending", attempt: 0, started_at: null, finished_at: null, error_message: null },
            ],
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByText("预审核")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需要预审核" })).toHaveClass("job-review-cta", "job-review-cta-active");
  });

  it("keeps quality-stage needs_review jobs on the final-review path", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-final-stage",
            quality_score: 92.4,
            quality_grade: "A",
            quality_summary: "剪辑已经进入终审，重点检查成片质量。",
            steps: [
              { id: "s5", step_name: "summary_review", status: "done", attempt: 0, started_at: null, finished_at: null, error_message: null },
              { id: "s6", step_name: "final_review", status: "pending", attempt: 0, started_at: null, finished_at: null, error_message: null },
            ],
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByText("最终核对")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需要最终审核" })).toHaveClass("job-review-cta", "job-review-cta-active");
  });

  it("keeps non-review jobs on the generic review action without highlight", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-3",
            status: "running",
            steps: [
              { id: "s3", step_name: "transcribe", status: "running", attempt: 0, started_at: null, finished_at: null, error_message: null },
            ],
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "jobs.actions.review" })).toHaveClass("job-review-cta");
    expect(screen.getByRole("button", { name: "jobs.actions.review" })).not.toHaveClass("job-review-cta-active");
  });

  it("keeps existing row actions clickable", () => {
    const onSelect = vi.fn();
    const onOpenFolder = vi.fn();

    render(
      <JobQueueTable
        jobs={[
          buildJob({
            steps: [
              { id: "s4", step_name: "final_review", status: "pending", attempt: 0, started_at: null, finished_at: null, error_message: null },
            ],
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={onSelect}
        onOpenFolder={onOpenFolder}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "jobs.actions.openFolder" }));
    expect(onOpenFolder).toHaveBeenCalledWith("job-1");
  });

  it("adds updated_at as the thumbnail cache-busting version", () => {
    render(
      <JobQueueTable
        jobs={[buildJob({ updated_at: "2026-04-09T03:21:00Z" })]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(mockContentProfileThumbnailUrl).toHaveBeenCalledWith("job-1", 0, "2026-04-09T03:21:00Z");
  });

  it("shows auto-review as enabled with the blocking summary when it has not taken effect", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-auto-review-blocked",
            status: "processing",
            enhancement_modes: ["auto_review"],
            auto_review_mode_enabled: true,
            auto_review_status: "blocked",
            auto_review_summary: "已启用，但本次命中人工复核条件，未自动放行。",
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getAllByText("自动审核已启用").length).toBeGreaterThan(0);
    expect(screen.getByText("已启用，但本次命中人工复核条件，未自动放行。")).toBeInTheDocument();
  });

  it("shows auto-review as applied after the summary review has been auto-confirmed", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-auto-review-applied",
            status: "processing",
            enhancement_modes: ["auto_review"],
            auto_review_mode_enabled: true,
            auto_review_status: "applied",
            auto_review_summary: "已自动确认预审核并继续执行。",
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getAllByText("自动审核已生效").length).toBeGreaterThan(0);
    expect(screen.getByText("已自动确认预审核并继续执行。")).toBeInTheDocument();
  });

  it("surfaces filename-derived descriptions as a separate labeled hint in the queue", () => {
    render(
      <JobQueueTable
        jobs={[
          buildJob({
            id: "job-filename-hint",
            status: "processing",
            content_summary: null,
            content_subject: null,
            video_description: "任务说明依据文件名：狐蝠工业 FXX1小副包 开箱测评。\n重点保留近景细节和开合手感。",
          }),
        ]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByText("重点保留近景细节和开合手感。")).toBeInTheDocument();
    expect(screen.getByText("jobs.queue.filenameDerivedBadge")).toBeInTheDocument();
    expect(screen.getByText("狐蝠工业 FXX1小副包 开箱测评。")).toBeInTheDocument();
  });
});

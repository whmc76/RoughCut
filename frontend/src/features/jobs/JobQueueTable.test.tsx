import { fireEvent, render, screen } from "@testing-library/react";

import { JobQueueTable } from "./JobQueueTable";

vi.mock("../../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
  getCurrentUiLocale: () => "zh-CN",
  translate: (_locale: string, key: string) => key,
}));

vi.mock("../../api", () => ({
  api: {
    contentProfileThumbnailUrl: () => "/thumb.png",
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
    created_at: "2026-04-02T02:00:00Z",
    updated_at: "2026-04-02T02:10:00Z",
    progress_percent: 86,
    steps: [],
    ...overrides,
  };
}

describe("JobQueueTable", () => {
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
});

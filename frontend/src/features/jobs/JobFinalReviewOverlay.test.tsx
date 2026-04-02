import { fireEvent, render, screen } from "@testing-library/react";

import { JobFinalReviewOverlay } from "./JobFinalReviewOverlay";

const SAMPLE_JOB = {
  id: "job-final-1",
  source_name: "final_cut.mp4",
  status: "needs_review",
  language: "zh-CN",
  workflow_mode: "standard_edit",
  enhancement_modes: ["avatar_commentary"],
  created_at: "2026-04-02T02:00:00Z",
  updated_at: "2026-04-02T02:10:00Z",
  steps: [],
  quality_score: 87.5,
  quality_grade: "A-",
  quality_summary: "整体稳定，仅有少量术语不一致。",
  quality_issue_codes: ["subtitle_timing", "terminology"],
};

const SAMPLE_REPORT = {
  job_id: "job-final-1",
  generated_at: "2026-04-02T02:05:00Z",
  total_subtitle_items: 12,
  total_corrections: 3,
  corrections_by_type: {
    terminology: 2,
    timing: 1,
  },
  pending_count: 2,
  accepted_count: 1,
  rejected_count: 0,
  items: [
    {
      index: 1,
      start: 0,
      end: 2,
      text_raw: "这里是第一句原文",
      text_norm: "这里是第一句原文",
      text_final: "这里是第一句成稿",
      corrections: [
        {
          id: "corr-1",
          original: "第一句原文",
          suggested: "第一句成稿",
          type: "terminology",
          confidence: 0.93,
        },
      ],
    },
    {
      index: 2,
      start: 2,
      end: 5,
      text_raw: "这里是第二句原文",
      text_norm: "这里是第二句原文",
      text_final: null,
      corrections: [],
    },
    {
      index: 3,
      start: 5,
      end: 8,
      text_raw: "这里是第三句原文",
      text_norm: "这里是第三句规范化",
      text_final: "这里是第三句定稿",
      corrections: [
        {
          id: "corr-2",
          original: "第三句原文",
          suggested: "第三句定稿",
          type: "timing",
          confidence: 0.81,
        },
      ],
    },
  ],
};

describe("JobFinalReviewOverlay", () => {
  it("shows the final-review quality summary, subtitle spot-check, and action buttons", async () => {
    const onPreview = vi.fn();
    const onDownload = vi.fn();
    const onOpenFolder = vi.fn();
    const onToggleRejectReason = vi.fn();
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onRejectNoteChange = vi.fn();
    const onApplySubtitleReview = vi.fn();

    render(
      <JobFinalReviewOverlay
        selectedJob={SAMPLE_JOB}
        report={SAMPLE_REPORT}
        previewSrc="/api/v1/jobs/job-final-1/download/file?variant=packaged"
        isPreviewOpen
        selectedRejectReasons={["字幕问题"]}
        onPreview={onPreview}
        onDownload={onDownload}
        onOpenFolder={onOpenFolder}
        onToggleRejectReason={onToggleRejectReason}
        onRejectNoteChange={onRejectNoteChange}
        onApplySubtitleReview={onApplySubtitleReview}
        onApprove={onApprove}
        onReject={onReject}
      />,
    );

    expect(screen.getByRole("heading", { name: "最终审核" })).toBeInTheDocument();
    expect(screen.getByText("评分")).toBeInTheDocument();
    expect(screen.getByText("87.5")).toBeInTheDocument();
    expect(screen.getByText("A-")).toBeInTheDocument();
    expect(screen.getByText("整体稳定，仅有少量术语不一致。")).toBeInTheDocument();
    expect(screen.getByText("subtitle_timing")).toBeInTheDocument();
    expect(screen.getByText("terminology")).toBeInTheDocument();

    expect(screen.getByText("字幕抽检")).toBeInTheDocument();
    expect(screen.getByText("#1 这里是第一句成稿")).toBeInTheDocument();
    expect(screen.getByText("原文：这里是第一句原文")).toBeInTheDocument();
    expect(screen.getByText(/这里是第三句定稿/)).toBeInTheDocument();
    expect(screen.getByText("字幕总数")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("问题分类")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "字幕问题" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("final-review-preview-player")).toHaveAttribute("src", "/api/v1/jobs/job-final-1/download/file?variant=packaged");

    fireEvent.click(screen.getByRole("button", { name: "打开成片" }));
    fireEvent.click(screen.getByRole("button", { name: "下载" }));
    fireEvent.click(screen.getByRole("button", { name: "打开文件夹" }));
    fireEvent.click(screen.getByRole("button", { name: "封面包装" }));
    fireEvent.click(screen.getAllByRole("button", { name: "通过字幕" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "退回字幕" })[0]);

    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(onOpenFolder).toHaveBeenCalledTimes(1);
    expect(onToggleRejectReason).toHaveBeenCalledWith("封面包装");
    expect(onApplySubtitleReview).toHaveBeenNthCalledWith(1, "corr-1", "accepted");
    expect(onApplySubtitleReview).toHaveBeenNthCalledWith(2, "corr-1", "rejected");
  });

  it("keeps workflow details secondary and renders fallbacks when quality or report data is absent", () => {
    render(
      <JobFinalReviewOverlay
        selectedJob={{
          id: "job-final-2",
          source_name: "fallback.mp4",
          status: "needs_review",
          language: "zh-CN",
          workflow_mode: "standard_edit",
          enhancement_modes: [],
          created_at: "2026-04-02T03:00:00Z",
          updated_at: "2026-04-02T03:05:00Z",
          steps: [],
        }}
        onPreview={vi.fn()}
        onDownload={vi.fn()}
        onOpenFolder={vi.fn()}
        onRejectNoteChange={vi.fn()}
        onApplySubtitleReview={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText("暂无质量结果")).toBeInTheDocument();
    expect(screen.getByText("暂无字幕报告")).toBeInTheDocument();
    expect(screen.getByText("standard_edit · 无增强")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开成片" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开文件夹" })).toBeInTheDocument();
    expect(screen.queryByTestId("final-review-preview-player")).not.toBeInTheDocument();
  });
});

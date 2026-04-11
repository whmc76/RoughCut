import { fireEvent, render, screen } from "@testing-library/react";

import { JobFinalReviewOverlay } from "./JobFinalReviewOverlay";

const SAMPLE_JOB = {
  id: "job-final-1",
  source_name: "final_cut.mp4",
  content_subject: "AI创作工具",
  content_summary: "这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。",
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
  timeline_diagnostics: {
    review_recommended: true,
    review_reasons: ["存在贴近高能量保留段的 cut，建议复核边界。", "Hook 段存在高能量保留片段。"],
    high_risk_cut_count: 2,
    high_energy_keep_count: 1,
    llm_reviewed: true,
    llm_candidate_count: 3,
    llm_restored_cut_count: 1,
    llm_provider: "minimax",
    llm_summary: "恢复了 1 个展示型误删。",
  },
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
  it("renders the final review inside the solid review work surface", () => {
    const { container } = render(
      <JobFinalReviewOverlay
        selectedJob={SAMPLE_JOB}
        report={SAMPLE_REPORT}
        onPreview={vi.fn()}
        onDownload={vi.fn()}
        onOpenFolder={vi.fn()}
      />,
    );

    expect(container.querySelector(".final-review-surface.panel")).toBeInTheDocument();
    expect(container.querySelector(".final-review-action-card")).toBeInTheDocument();
  });

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
    expect(screen.getByText("摘要与主题")).toBeInTheDocument();
    expect(screen.getByText("AI创作工具")).toBeInTheDocument();
    expect(screen.getByText("这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。")).toBeInTheDocument();
    expect(screen.getByText("字幕速览")).toBeInTheDocument();
    expect(screen.getByText("评分")).toBeInTheDocument();
    expect(screen.getByText("87.5")).toBeInTheDocument();
    expect(screen.getByText("A-")).toBeInTheDocument();
    expect(screen.getByText("整体稳定，仅有少量术语不一致。")).toBeInTheDocument();
    expect(screen.getByText("subtitle_timing")).toBeInTheDocument();
    expect(screen.getByText("terminology")).toBeInTheDocument();
    expect(screen.getByText("剪辑诊断")).toBeInTheDocument();
    expect(screen.getByText("高风险 Cut")).toBeInTheDocument();
    expect(screen.getByText("人工复核建议")).toBeInTheDocument();
    expect(screen.getByText("存在贴近高能量保留段的 cut，建议复核边界。")).toBeInTheDocument();
    expect(screen.getByText("LLM 复核摘要")).toBeInTheDocument();
    expect(screen.getByText("minimax · 恢复 1 个 cut")).toBeInTheDocument();
    expect(screen.getByText("已复核 3 个高风险 cut：恢复了 1 个展示型误删。")).toBeInTheDocument();

    expect(screen.getByText("字幕抽检")).toBeInTheDocument();
    expect(screen.getByText("#1 这里是第一句成稿")).toBeInTheDocument();
    expect(screen.getByText("原文：这里是第一句原文")).toBeInTheDocument();
    expect(screen.getAllByText(/这里是第三句定稿/).length).toBeGreaterThan(0);
    expect(screen.getByText("字幕总数")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("问题分类")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "字幕问题" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("final-review-preview-player")).toHaveAttribute("src", "/api/v1/jobs/job-final-1/download/file?variant=packaged");
    expect(screen.getByTestId("final-review-preview-frame")).toBeInTheDocument();

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

  it("renders the preview by default whenever a packaged video is available", () => {
    render(
      <JobFinalReviewOverlay
        selectedJob={SAMPLE_JOB}
        previewSrc="/api/v1/jobs/job-final-1/download/file?variant=packaged"
        onPreview={vi.fn()}
        onDownload={vi.fn()}
        onOpenFolder={vi.fn()}
      />,
    );

    expect(screen.getByTestId("final-review-preview-player")).toHaveAttribute("src", "/api/v1/jobs/job-final-1/download/file?variant=packaged");
    expect(screen.getByTestId("final-review-preview-frame")).toBeInTheDocument();
    expect(screen.getByText("AI创作工具")).toBeInTheDocument();
  });
});

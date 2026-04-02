import { render, screen } from "@testing-library/react";

import type { ContentProfileReview } from "../../types";
import { JobSummaryReviewOverlay } from "./JobSummaryReviewOverlay";

const mockJobContentProfileSection = vi.fn();

vi.mock("./JobContentProfileSection", () => ({
  JobContentProfileSection: (props: Record<string, unknown>) => {
    mockJobContentProfileSection(props);
    return <div data-testid="job-content-profile-section" />;
  },
}));

const contentProfile: ContentProfileReview = {
  job_id: "job_1",
  status: "needs_review",
  review_step_status: "pending",
  review_step_detail: "首次品牌/型号证据不足，需人工确认后再继续。",
  review_reasons: ["首次品牌/型号证据不足，已退化为保守摘要"],
  blocking_reasons: ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
  identity_review: {
    required: true,
    reason: "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
  },
  workflow_mode: "standard_edit",
  enhancement_modes: [],
  draft: { title: "草稿标题" },
  final: { title: "最终标题" },
  memory: {},
};

describe("JobSummaryReviewOverlay", () => {
  beforeEach(() => {
    mockJobContentProfileSection.mockClear();
  });

  it("foregrounds the decision summary before the evidence editor", () => {
    render(
      <JobSummaryReviewOverlay
        jobId="job_1"
        jobTitle="needs_review.mp4"
        contentProfile={contentProfile}
        contentSource={{ title: "最终标题" }}
        contentDraft={{ title: "草稿标题" }}
        contentKeywords="开箱,升级"
        isConfirmingProfile={false}
        onContentFieldChange={vi.fn()}
        onKeywordsChange={vi.fn()}
        onConfirmProfile={vi.fn()}
      />,
    );

    expect(screen.getByText("摘要核对")).toBeInTheDocument();
    expect(screen.getByText("needs_review.mp4")).toBeInTheDocument();
    expect(screen.getByText("首次品牌/型号证据不足，需人工确认后再继续。")).toBeInTheDocument();
    expect(screen.getByText("核对原因")).toBeInTheDocument();
    expect(screen.getByText("首次品牌/型号证据不足，已退化为保守摘要")).toBeInTheDocument();
    expect(screen.getByText("开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认摘要并继续执行" })).toBeInTheDocument();
    expect(screen.getByTestId("job-content-profile-section")).toBeInTheDocument();
    expect(mockJobContentProfileSection).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: "job_1",
        reviewMode: true,
        isSaving: false,
      }),
    );
    expect(
      screen.getByRole("button", { name: "确认摘要并继续执行" }).compareDocumentPosition(
        screen.getByTestId("job-content-profile-section"),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

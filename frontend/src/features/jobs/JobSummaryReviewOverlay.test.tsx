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
  ocr_evidence: {
    visible_text: "狐蝠工业 FXX1小副包 开箱",
    frame_count: 3,
    line_count: 2,
    raw_snippets: [{ text: "FXX1小副包" }],
  },
  transcript_evidence: {
    provider: "qwen3_asr",
    model: "qwen3-asr-1.7b",
    prompt: "请优先识别品牌与型号。",
    segments: [{ text: "这期开箱狐蝠工业 FXX1小副包。" }],
  },
  entity_resolution_trace: {
    summary: "当前画面文字与转写都更支持机能包，不支持手电。",
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

  it("renders the summary review inside a dedicated solid work surface", () => {
    const { container } = render(
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

    expect(container.querySelector(".summary-review-surface.panel")).toBeInTheDocument();
    expect(container.querySelector(".summary-review-evidence-card")).toBeInTheDocument();
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

  it("surfaces OCR and transcript evidence before the editor", () => {
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

    expect(screen.getByText("画面与识别证据")).toBeInTheDocument();
    expect(screen.getByText("狐蝠工业 FXX1小副包 开箱")).toBeInTheDocument();
    expect(screen.getByText("3 帧 / 2 行")).toBeInTheDocument();
    expect(screen.getByText("qwen3_asr / qwen3-asr-1.7b")).toBeInTheDocument();
    expect(screen.getByText("请优先识别品牌与型号。")).toBeInTheDocument();
    expect(screen.getByText("这期开箱狐蝠工业 FXX1小副包。")).toBeInTheDocument();
    expect(screen.getByText("当前画面文字与转写都更支持机能包，不支持手电。")).toBeInTheDocument();
  });
});

describe("JobContentProfileSection", () => {
  async function renderActualSection(
    contentSource: Record<string, unknown> | null,
    contentDraft: Record<string, unknown> = {},
    contentProfile?: ContentProfileReview,
  ) {
    const { JobContentProfileSection } = await vi.importActual<typeof import("./JobContentProfileSection")>(
      "./JobContentProfileSection",
    );

    render(
      <JobContentProfileSection
        jobId="job_1"
        contentProfile={contentProfile}
        contentSource={contentSource}
        contentDraft={contentDraft}
        contentKeywords=""
        isSaving={false}
        onFieldChange={vi.fn()}
        onKeywordsChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
  }

  it("keeps the core editable content_profile fields visible when no nested understanding is present", async () => {
    await renderActualSection({
      subject_type: "legacy_subject",
      video_theme: "legacy_theme",
      hook_line: "legacy_hook",
      visible_text: "legacy_visible_text",
      summary: "legacy_summary",
      engagement_question: "legacy_question",
    });

    expect(screen.getByDisplayValue("legacy_theme")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_hook")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_summary")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_question")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("legacy_subject")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("legacy_visible_text")).not.toBeInTheDocument();
  });

  it("prefers review-page flat fields over nested content_understanding fields", async () => {
    await renderActualSection({
      video_type: "commentary",
      subject_type: "legacy_subject",
      video_theme: "legacy_theme",
      hook_line: "legacy_hook",
      summary: "legacy_summary",
      engagement_question: "legacy_question",
      content_understanding: {
        video_type: "tutorial",
        primary_subject: "nested_subject",
        video_theme: "nested_theme",
        hook_line: "nested_hook",
        summary: "nested_summary",
        question: "nested_question",
      },
    });

    expect(screen.getByDisplayValue("legacy_theme")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_hook")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_summary")).toBeInTheDocument();
    expect(screen.getByDisplayValue("legacy_question")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("commentary");
    expect(screen.queryByDisplayValue("nested_subject")).not.toBeInTheDocument();
  });

  it("falls back to nested content_understanding fields when review-page fields are missing", async () => {
    await renderActualSection({
      subject_type: "legacy_subject",
      content_understanding: {
        primary_subject: "nested_subject",
        video_theme: "nested_theme",
        hook_line: "nested_hook",
        summary: "nested_summary",
        question: "nested_question",
      },
    });

    expect(screen.getByDisplayValue("nested_theme")).toBeInTheDocument();
    expect(screen.getByDisplayValue("nested_hook")).toBeInTheDocument();
    expect(screen.getByDisplayValue("nested_summary")).toBeInTheDocument();
    expect(screen.getByDisplayValue("nested_question")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("nested_subject")).not.toBeInTheDocument();
  });
});

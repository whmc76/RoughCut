import { render, screen } from "@testing-library/react";

import type { ContentProfileReview } from "../../types";
import {
  formatIdentityEvidenceSources,
  formatVideoType,
  getTextValue,
  normalizeKeywordList,
  normalizeVideoTypeLabel,
} from "./contentProfile";
import { JobContentProfileSection } from "./JobContentProfileSection";

describe("contentProfile helpers", () => {
  it("normalizes text, video-type labels, and keyword arrays", () => {
    expect(getTextValue("  开箱  ")).toBe("开箱");
    expect(normalizeVideoTypeLabel(" tutorial ", "zh-CN")).toBe("教程");
    expect(formatVideoType(["", "tutorial"], "zh-CN")).toBe("教程");
    expect(normalizeKeywordList(["VLOG", "vlog", " vlog ", "开箱"])).toEqual(["VLOG", "开箱"]);
  });

  it("formats support-source labels from structured identity keys", () => {
    expect(
      formatIdentityEvidenceSources([
        "subtitle_snippets",
        "source_name_terms",
        "visible_text_terms",
        "evidence_terms",
        "source_name_terms",
      ]),
    ).toEqual(["字幕", "文件名", "画面文字", "外部证据"]);
  });
});

describe("JobContentProfileSection", () => {
  function renderSection(contentSource: Record<string, unknown>, contentProfile?: ContentProfileReview) {
    return render(
      <JobContentProfileSection
        jobId="job_1"
        contentProfile={contentProfile}
        contentSource={contentSource}
        contentDraft={{}}
        contentKeywords=""
        isSaving={false}
        showThumbnails={false}
        onFieldChange={vi.fn()}
        onKeywordsChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
  }

  it("uses normalized video-type labels instead of inferring from summary/hook text", () => {
    renderSection({
      subject_type: "",
      summary: "这是一条开箱视频",
      hook_line: "先开箱再展示细节",
      content_understanding: {
        video_type: "",
        summary: "开箱画面很多",
        hook_line: "开箱先看细节",
      },
    });

    expect(screen.getByDisplayValue("待补充")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("开箱")).not.toBeInTheDocument();
  });

  it("renders identity evidence labels consistently from structured support-source keys", () => {
    renderSection(
      {
        subject_type: "教程",
      },
      {
        job_id: "job_1",
        status: "needs_review",
        review_step_status: "pending",
        workflow_mode: "standard_edit",
        enhancement_modes: [],
        ocr_evidence: {},
        transcript_evidence: {},
        entity_resolution_trace: {},
        draft: {},
        final: {},
        memory: {},
        identity_review: {
          required: true,
          support_sources: [
            "subtitle_snippets",
            "source_name_terms",
            "visible_text_terms",
            "evidence_terms",
            "source_name_terms",
          ],
          evidence_bundle: {
            candidate_brand: "LEATHERMAN",
          },
        },
      },
    );

    expect(screen.getByText("支撑来源：字幕、文件名、画面文字、外部证据")).toBeInTheDocument();
  });
});

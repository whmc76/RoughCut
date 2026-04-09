import { fireEvent, render, screen } from "@testing-library/react";

import type { ContentProfileReview } from "../../types";
import {
  formatIdentityEvidenceSources,
  formatVideoType,
  getTextValue,
  normalizeKeywordList,
  normalizeVideoTypeValue,
  normalizeVideoTypeLabel,
} from "./contentProfile";
import { JobContentProfileSection } from "./JobContentProfileSection";

describe("contentProfile helpers", () => {
  it("normalizes text, video-type labels, and keyword arrays", () => {
    expect(getTextValue("  开箱  ")).toBe("开箱");
    expect(normalizeVideoTypeValue(" tutorial ")).toBe("tutorial");
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

  it("deduplicates support-source labels after normalization", () => {
    expect(formatIdentityEvidenceSources(["transcript", "subtitle_snippets", "source_name", "source_name_terms"])).toEqual([
      "字幕",
      "文件名",
    ]);
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

  it("uses a localized video-type dropdown instead of showing the raw enum value", () => {
    renderSection({
      content_understanding: {
        video_type: "unboxing",
        primary_subject: "EDC机能包",
      },
    });

    expect(screen.getByRole("combobox", { name: "视频类型" })).toHaveValue("unboxing");
    expect(screen.getByDisplayValue("开箱")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unboxing")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("EDC机能包")).not.toBeInTheDocument();
  });

  it("emits canonical video_type values from the dropdown", () => {
    const onFieldChange = vi.fn();

    render(
      <JobContentProfileSection
        jobId="job_1"
        contentSource={{
          content_understanding: {
            video_type: "unboxing",
          },
        }}
        contentDraft={{}}
        contentKeywords=""
        isSaving={false}
        showThumbnails={false}
        onFieldChange={onFieldChange}
        onKeywordsChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "视频类型" }), {
      target: { value: "tutorial" },
    });

    expect(onFieldChange).toHaveBeenCalledWith("video_type", "tutorial");
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

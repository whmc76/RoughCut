import { render, screen } from "@testing-library/react";

import type { ContentProfileReview } from "../../types";
import { JobContentProfileSection } from "./JobContentProfileSection";

const mockContentProfileHelpers = vi.hoisted(() => ({
  formatVideoType: vi.fn(() => "开箱"),
  formatIdentityEvidenceSources: vi.fn(() => ["字幕", "文件名", "画面文字", "外部证据"]),
  formatIdentityEvidenceGlossaryAliases: vi.fn(() => ["品牌：鸿福", "型号：F叉二一小副包"]),
}));

vi.mock("./contentProfile", async () => {
  const actual = await vi.importActual<typeof import("./contentProfile")>("./contentProfile");
  return {
    ...actual,
    formatVideoType: mockContentProfileHelpers.formatVideoType,
    formatIdentityEvidenceSources: mockContentProfileHelpers.formatIdentityEvidenceSources,
    formatIdentityEvidenceGlossaryAliases: mockContentProfileHelpers.formatIdentityEvidenceGlossaryAliases,
  };
});

vi.mock("../../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: "zh-CN",
  }),
  getCurrentUiLocale: () => "zh-CN",
  translate: (_locale: string, key: string) => key,
}));

vi.mock("../../api", () => ({
  api: {
    contentProfileThumbnailUrl: () => "/thumb.png",
  },
}));

vi.mock("../../utils", () => ({
  statusLabel: (status: string) => status,
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
    evidence_strength: "weak",
    support_sources: ["transcript", "source_name", "visible_text", "evidence"],
    evidence_bundle: {
      candidate_brand: "狐蝠工业",
      candidate_model: "FXX1小副包",
      matched_subtitle_snippets: ["[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。"],
      matched_glossary_aliases: { brand: ["鸿福"], model: ["F叉二一小副包"] },
      matched_source_name_terms: ["鸿福", "F叉二一小副包"],
      matched_visible_text_terms: ["狐蝠工业"],
      matched_evidence_terms: [],
    },
  },
  ocr_evidence: {},
  transcript_evidence: {},
  entity_resolution_trace: {},
  workflow_mode: "standard_edit",
  enhancement_modes: ["avatar_commentary"],
  draft: { title: "草稿标题" },
  final: { title: "最终标题" },
  memory: {},
};

describe("JobContentProfileSection", () => {
  beforeEach(() => {
    mockContentProfileHelpers.formatVideoType.mockClear();
    mockContentProfileHelpers.formatIdentityEvidenceSources.mockClear();
    mockContentProfileHelpers.formatIdentityEvidenceGlossaryAliases.mockClear();
  });

  it("normalizes helper outputs for video types, keywords, and evidence labels", async () => {
    const helpers = await vi.importActual<typeof import("./contentProfile")>("./contentProfile");

    expect(helpers.getTextValue("  开箱  ")).toBe("开箱");
    expect(helpers.normalizeVideoTypeLabel("开箱体验", "zh-CN")).toBe("开箱");
    expect(helpers.formatVideoType(["", "开箱体验"], "zh-CN")).toBe("开箱");
    expect(helpers.normalizeKeywordList(["VLOG", "vlog", " vlog ", "开箱"])).toEqual(["VLOG", "开箱"]);
    expect(helpers.formatIdentityEvidenceSourceLabel("source_name")).toBe("文件名");
    expect(helpers.formatIdentityEvidenceSources(["transcript", "source_name", "visible_text", "evidence"])).toEqual([
      "字幕",
      "文件名",
      "画面文字",
      "外部证据",
    ]);
    expect(
      helpers.formatIdentityEvidenceGlossaryAliases({
        matched_glossary_aliases: {
          brand: ["鸿福"],
          model: ["F叉二一小副包"],
        },
      }),
    ).toEqual(["品牌：鸿福", "型号：F叉二一小副包"]);
  });

  it("uses shared helpers to render normalized video type and identity evidence labels", () => {
    render(
      <JobContentProfileSection
        jobId="job_1"
        contentProfile={contentProfile}
        contentSource={{
          content_understanding: {
            video_type: "开箱体验",
            primary_subject: "EDC机能包",
            video_theme: "开箱与上手",
            summary: "摘要",
            hook_line: "钩子",
            engagement_question: "问题",
          },
        }}
        contentDraft={{}}
        contentKeywords="VLOG, 开箱"
        isSaving={false}
        onFieldChange={vi.fn()}
        onKeywordsChange={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(mockContentProfileHelpers.formatVideoType).toHaveBeenCalled();
    expect(mockContentProfileHelpers.formatIdentityEvidenceSources).toHaveBeenCalledWith([
      "transcript",
      "source_name",
      "visible_text",
      "evidence",
    ]);
    expect(mockContentProfileHelpers.formatIdentityEvidenceGlossaryAliases).toHaveBeenCalled();
    expect(screen.getByDisplayValue("开箱")).toBeInTheDocument();
    expect(screen.getByText("支撑来源：字幕、文件名、画面文字、外部证据")).toBeInTheDocument();
    expect(screen.getByText("命中词表别名：品牌：鸿福；型号：F叉二一小副包")).toBeInTheDocument();
  });
});

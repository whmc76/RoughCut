import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { ContentProfileReview, Job, JobActivity, JobTimeline, Report, TokenUsageReport } from "../../types";
import { normalizeKeywordList } from "./contentProfile";
import { useJobWorkspace } from "./useJobWorkspace";

const mockApi = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getJobsUsageSummary: vi.fn(),
  getJobsUsageTrend: vi.fn(),
  getConfigOptions: vi.fn(),
  getConfig: vi.fn(),
  getPackaging: vi.fn(),
  getAvatarMaterials: vi.fn(),
  getJob: vi.fn(),
  getJobActivity: vi.fn(),
  getJobReport: vi.fn(),
  getJobTokenUsage: vi.fn(),
  getJobTimeline: vi.fn(),
  getContentProfile: vi.fn(),
  warmContentProfileThumbnails: vi.fn(),
  patchConfig: vi.fn(),
  patchPackagingConfig: vi.fn(),
  openJobFolder: vi.fn(),
  cancelJob: vi.fn(),
  restartJob: vi.fn(),
  createJob: vi.fn(),
  confirmContentProfile: vi.fn(),
  finalReviewDecision: vi.fn(),
  applyReview: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_JOBS: Job[] = [
  {
    id: "job_1",
    source_name: "product_upgrade.mp4",
    content_subject: "品牌升级版拆解",
    content_summary: "升级版开箱和细节拆解",
    status: "done",
    language: "zh-CN",
    workflow_template: "edc_tactical",
    workflow_mode: "standard_edit",
    enhancement_modes: ["avatar_commentary"],
    file_hash: "hash1",
    error_message: null,
    created_at: "2026-03-12T10:00:00Z",
    updated_at: "2026-03-12T10:20:00Z",
    steps: [],
  },
  {
    id: "job_2",
    source_name: "workflow_setup.mp4",
    content_subject: "工作流配置",
    content_summary: "讲解目录扫描和设置保存",
    status: "running",
    language: "zh-CN",
    workflow_template: "tutorial_standard",
    workflow_mode: "standard_edit",
    enhancement_modes: ["ai_director"],
    file_hash: "hash2",
    error_message: null,
    created_at: "2026-03-12T11:00:00Z",
    updated_at: "2026-03-12T11:05:00Z",
    steps: [],
  },
];

const SAMPLE_ACTIVITY: JobActivity = {
  job_id: "job_1",
  status: "done",
  current_step: null,
  render: null,
  decisions: [],
  events: [],
};

const SAMPLE_REVIEW_JOB: Job = {
  ...SAMPLE_JOBS[0],
  status: "needs_review",
};

const SAMPLE_REPORT: Report = {
  job_id: "job_1",
  generated_at: "2026-03-12T10:21:00Z",
  total_subtitle_items: 10,
  total_corrections: 2,
  corrections_by_type: { glossary: 2 },
  pending_count: 0,
  accepted_count: 2,
  rejected_count: 0,
  items: [],
};

const SAMPLE_TIMELINE: JobTimeline = {
  id: "timeline_1",
  version: 3,
  data: { cuts: 12 },
};

const SAMPLE_TOKEN_USAGE: TokenUsageReport = {
  job_id: "job_1",
  has_telemetry: true,
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
  steps: [
    {
      step_name: "content_profile",
      label: "摘要",
      calls: 3,
      prompt_tokens: 2400,
      completion_tokens: 700,
      total_tokens: 3100,
      last_updated_at: "2026-03-12T10:18:00Z",
      cache_entries: [
        {
          name: "content_profile",
          namespace: "content_profile.infer",
          key: "cache-key-1",
          hit: true,
          usage_baseline: {
            calls: 3,
            prompt_tokens: 2400,
            completion_tokens: 700,
            total_tokens: 3100,
          },
        },
      ],
      operations: [
        {
          operation: "content_profile.visual_transcript_fuse",
          calls: 1,
          prompt_tokens: 1200,
          completion_tokens: 300,
          total_tokens: 1500,
        },
      ],
    },
  ],
  models: [
    {
      model: "MiniMax-M2.7-highspeed",
      provider: "minimax",
      kind: "reasoning",
      calls: 5,
      prompt_tokens: 3200,
      completion_tokens: 900,
      total_tokens: 4100,
    },
  ],
};

const SAMPLE_PROFILE: ContentProfileReview = {
  job_id: "job_1",
  status: "needs_review",
  review_step_status: "pending",
  review_step_detail: "首次品牌/型号证据不足，需人工确认后再继续。",
  review_reasons: ["首次品牌/型号证据不足，已退化为保守摘要"],
  blocking_reasons: ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
  identity_review: {
    required: true,
    first_seen_brand: true,
    first_seen_model: true,
    conservative_summary: true,
    support_sources: ["transcript", "source_name"],
    evidence_strength: "weak",
    reason: "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
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
  draft: {
    title: "草稿标题",
    keywords: ["开箱", "升级"],
  },
  final: {
    title: "最终标题",
    keywords: ["开箱", "升级", "限定"],
  },
  memory: {},
};

const SAMPLE_PROFILE_NO_KEYWORDS: ContentProfileReview = {
  ...SAMPLE_PROFILE,
  draft: {
    title: "草稿标题",
  },
  final: {
    title: "最终标题",
    search_queries: ["VLOG", "vlog", " vlog ", "开箱"],
  },
};

describe("useJobWorkspace", () => {
  beforeEach(() => {
    mockApi.listJobs.mockResolvedValue(SAMPLE_JOBS);
    mockApi.getJobsUsageSummary.mockResolvedValue({
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
    });
    mockApi.getJobsUsageTrend.mockResolvedValue({
      days: 7,
      focus_type: null,
      focus_name: null,
      points: [
        {
          date: "2026-03-12",
          label: "03-12",
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
          top_entry: { dimension: "step", name: "content_profile", label: "摘要", total_tokens: 3100 },
          top_step: { step_name: "content_profile", label: "摘要", total_tokens: 3100 },
        },
      ],
    });
    mockApi.getConfigOptions.mockResolvedValue({
      job_languages: [{ value: "zh-CN", label: "简体中文" }],
      workflow_templates: [{ value: "", label: "自动匹配" }],
      workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
      enhancement_modes: [{ value: "avatar_commentary", label: "数字人解说" }, { value: "ai_director", label: "AI 导演" }],
      creative_mode_catalog: { workflow_modes: [], enhancement_modes: [] },
      transcription_models: {},
      multimodal_fallback_providers: [],
      search_providers: [],
      search_fallback_providers: [],
    });
    mockApi.getConfig.mockResolvedValue({
      default_job_workflow_mode: "standard_edit",
      default_job_enhancement_modes: ["avatar_commentary"],
      voice_provider: "runninghub",
      voice_clone_api_key_set: true,
      voice_clone_voice_id: "voice_demo",
      avatar_presenter_id: "presenter_demo.mp4",
    });
    mockApi.getPackaging.mockResolvedValue({
      assets: {},
      config: {
        insert_asset_ids: [],
        music_asset_ids: [],
        insert_selection_mode: "manual",
        insert_position_mode: "llm",
        music_selection_mode: "random",
        music_loop_mode: "loop_single",
        subtitle_style: "clean_box",
        subtitle_motion_style: "motion_static",
        smart_effect_style: "smart_effect_rhythm",
        cover_style: "preset_default",
        title_style: "preset_default",
        copy_style: "attention_grabbing",
        music_volume: 0.22,
        watermark_position: "top_right",
        watermark_opacity: 0.82,
        watermark_scale: 0.16,
        avatar_overlay_position: "bottom_right",
        avatar_overlay_scale: 0.28,
        avatar_overlay_corner_radius: 26,
        avatar_overlay_border_width: 4,
        avatar_overlay_border_color: "#F4E4B8",
        enabled: true,
      },
    });
    mockApi.getAvatarMaterials.mockResolvedValue({
      provider: "heygem",
      training_api_available: true,
      intake_mode: "guided_processing",
      summary: "summary",
      sections: [],
      profiles: [],
    });
    mockApi.getJob.mockResolvedValue(SAMPLE_JOBS[0]);
    mockApi.getJobActivity.mockResolvedValue(SAMPLE_ACTIVITY);
    mockApi.getJobReport.mockResolvedValue(SAMPLE_REPORT);
    mockApi.getJobTokenUsage.mockResolvedValue(SAMPLE_TOKEN_USAGE);
    mockApi.getJobTimeline.mockResolvedValue(SAMPLE_TIMELINE);
    mockApi.getContentProfile.mockResolvedValue(SAMPLE_PROFILE);
    mockApi.warmContentProfileThumbnails.mockResolvedValue(undefined);
    mockApi.openJobFolder.mockResolvedValue({});
    mockApi.patchConfig.mockResolvedValue({});
    mockApi.patchPackagingConfig.mockResolvedValue({});
    mockApi.cancelJob.mockResolvedValue({});
    mockApi.restartJob.mockResolvedValue({});
    mockApi.createJob.mockResolvedValue(SAMPLE_JOBS[1]);
    mockApi.confirmContentProfile.mockResolvedValue({
      workflow_mode: "standard_edit",
      enhancement_modes: ["avatar_commentary"],
      final: {
        title: "确认后的标题",
        keywords: ["教程", "配置"],
      },
    });
    mockApi.finalReviewDecision.mockResolvedValue({
      job_id: "job_1",
      decision: "approve",
      job_status: "processing",
      review_step_status: "done",
      rerun_triggered: false,
      note: null,
    });
    mockApi.applyReview.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("filters jobs by keyword across source and content fields", async () => {
    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    await waitFor(() => expect(result.current.jobs.data).toEqual(SAMPLE_JOBS));
    expect(result.current.filteredJobs.map((job) => job.id)).toEqual(["job_2", "job_1"]);

    act(() => {
      result.current.setKeyword("升级");
    });

    expect(result.current.filteredJobs.map((job) => job.id)).toEqual(["job_1"]);
  });

  it("hydrates content draft from selected profile and confirms edits", async () => {
    mockApi.getJob.mockResolvedValue(SAMPLE_REVIEW_JOB);

    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    act(() => {
      result.current.setSelectedJobId("job_1");
    });

    await waitFor(() => expect(result.current.contentProfile.data).toEqual(SAMPLE_PROFILE));
    expect(result.current.tokenUsage.data).toBeUndefined();
    expect(mockApi.getJobTokenUsage).not.toHaveBeenCalled();
    await waitFor(() => expect(result.current.contentDraft).toEqual(SAMPLE_PROFILE.final));
    expect(result.current.contentKeywords).toBe("开箱, 升级, 限定");

    act(() => {
      result.current.setContentDraft({
        title: "人工调整标题",
        keywords: ["教程", "配置"],
      });
    });

    await act(async () => {
      await result.current.confirmProfile.mutateAsync();
    });

    expect(mockApi.confirmContentProfile).toHaveBeenCalledWith("job_1", {
      title: "人工调整标题",
      keywords: ["教程", "配置"],
      workflow_mode: "standard_edit",
      enhancement_modes: ["avatar_commentary"],
      copy_style: "attention_grabbing",
    });
    expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith({
      copy_style: "attention_grabbing",
    });
    expect(result.current.contentDraft).toEqual({
      title: "确认后的标题",
      keywords: ["教程", "配置"],
    });
    expect(mockApi.patchConfig).toHaveBeenCalledWith({
      default_job_workflow_mode: "standard_edit",
      default_job_enhancement_modes: ["avatar_commentary"],
    });
  });

  it("uses source search_queries when keywords are missing and keeps confirm payload populated", async () => {
    mockApi.getJob.mockResolvedValue(SAMPLE_REVIEW_JOB);
    mockApi.getContentProfile.mockResolvedValueOnce(SAMPLE_PROFILE_NO_KEYWORDS);

    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    act(() => {
      result.current.setSelectedJobId("job_1");
    });

    await waitFor(() => expect(result.current.contentProfile.data).toEqual(SAMPLE_PROFILE_NO_KEYWORDS));
    expect(result.current.contentKeywords).toBe("VLOG, 开箱");

    act(() => {
      result.current.setContentDraft({
        title: "人工调整标题",
      });
    });

    await act(async () => {
      await result.current.confirmProfile.mutateAsync();
    });

    expect(mockApi.confirmContentProfile).toHaveBeenCalledWith("job_1", {
      title: "人工调整标题",
      keywords: ["VLOG", "开箱"],
      workflow_mode: "standard_edit",
      enhancement_modes: ["avatar_commentary"],
      copy_style: "attention_grabbing",
    });
  });

  it("updates upload defaults when inherited config defaults change", async () => {
    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    await waitFor(() => expect(result.current.upload.enhancementModes).toEqual(["avatar_commentary"]));

    mockApi.getConfig.mockResolvedValue({
      default_job_workflow_mode: "standard_edit",
      default_job_enhancement_modes: ["ai_director"],
      voice_provider: "runninghub",
      voice_clone_api_key_set: true,
      voice_clone_voice_id: "voice_demo",
      avatar_presenter_id: "presenter_demo.mp4",
    });

    await act(async () => {
      await result.current.config.refetch();
    });

    await waitFor(() => expect(result.current.upload.enhancementModes).toEqual(["ai_director"]));
  });

  it("does not fetch usage analysis in the jobs workspace", async () => {
    renderHookWithQueryClient(() => useJobWorkspace());

    await waitFor(() => expect(mockApi.listJobs).toHaveBeenCalled());
    await waitFor(() => expect(mockApi.getConfigOptions).toHaveBeenCalled());

    expect(mockApi.getJobsUsageSummary).not.toHaveBeenCalled();
    expect(mockApi.getJobsUsageTrend).not.toHaveBeenCalled();
  });
});

describe("contentProfile keyword normalization", () => {
  it("deduplicates keyword arrays once and preserves order", () => {
    expect(normalizeKeywordList(["开箱", "开箱", " 教程 ", "", "教程", "配置"])).toEqual(["开箱", "教程", "配置"]);
  });
});

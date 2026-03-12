import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { ContentProfileReview, Job, JobActivity, JobTimeline, Report } from "../../types";
import { useJobWorkspace } from "./useJobWorkspace";

const mockApi = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getConfigOptions: vi.fn(),
  getJob: vi.fn(),
  getJobActivity: vi.fn(),
  getJobReport: vi.fn(),
  getJobTimeline: vi.fn(),
  getContentProfile: vi.fn(),
  openJobFolder: vi.fn(),
  cancelJob: vi.fn(),
  restartJob: vi.fn(),
  createJob: vi.fn(),
  confirmContentProfile: vi.fn(),
  applyReview: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_JOBS: Job[] = [
  {
    id: "job_1",
    source_name: "fas_upgrade.mp4",
    content_subject: "FAST加帕 城六崩卫版",
    content_summary: "升级版开箱和细节拆解",
    status: "done",
    language: "zh-CN",
    channel_profile: "edc_tactical",
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
    channel_profile: "ops",
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

const SAMPLE_PROFILE: ContentProfileReview = {
  job_id: "job_1",
  status: "needs_review",
  review_step_status: "pending",
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

describe("useJobWorkspace", () => {
  beforeEach(() => {
    mockApi.listJobs.mockResolvedValue(SAMPLE_JOBS);
    mockApi.getConfigOptions.mockResolvedValue({
      job_languages: [{ value: "zh-CN", label: "简体中文" }],
      channel_profiles: [{ value: "", label: "自动匹配" }],
      transcription_models: {},
      multimodal_fallback_providers: [],
      search_providers: [],
      search_fallback_providers: [],
    });
    mockApi.getJob.mockResolvedValue(SAMPLE_JOBS[0]);
    mockApi.getJobActivity.mockResolvedValue(SAMPLE_ACTIVITY);
    mockApi.getJobReport.mockResolvedValue(SAMPLE_REPORT);
    mockApi.getJobTimeline.mockResolvedValue(SAMPLE_TIMELINE);
    mockApi.getContentProfile.mockResolvedValue(SAMPLE_PROFILE);
    mockApi.openJobFolder.mockResolvedValue({});
    mockApi.cancelJob.mockResolvedValue({});
    mockApi.restartJob.mockResolvedValue({});
    mockApi.createJob.mockResolvedValue(SAMPLE_JOBS[1]);
    mockApi.confirmContentProfile.mockResolvedValue({
      final: {
        title: "确认后的标题",
        keywords: ["教程", "配置"],
      },
    });
    mockApi.applyReview.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("filters jobs by keyword across source and content fields", async () => {
    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    await waitFor(() => expect(result.current.jobs.data).toEqual(SAMPLE_JOBS));

    act(() => {
      result.current.setKeyword("升级");
    });

    expect(result.current.filteredJobs.map((job) => job.id)).toEqual(["job_1"]);
  });

  it("hydrates content draft from selected profile and confirms edits", async () => {
    const { result } = renderHookWithQueryClient(() => useJobWorkspace());

    act(() => {
      result.current.setSelectedJobId("job_1");
    });

    await waitFor(() => expect(result.current.contentProfile.data).toEqual(SAMPLE_PROFILE));
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
    });
    expect(result.current.contentDraft).toEqual({
      title: "确认后的标题",
      keywords: ["教程", "配置"],
    });
  });
});

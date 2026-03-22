import { waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { GlossaryTerm, Job, ServiceStatus, WatchRoot } from "../../types";
import { useOverviewWorkspace } from "./useOverviewWorkspace";

const mockApi = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getJobsUsageSummary: vi.fn(),
  getJobsUsageTrend: vi.fn(),
  listWatchRoots: vi.fn(),
  listGlossary: vi.fn(),
  getControlStatus: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_JOBS: Job[] = [
  {
    id: "job_1",
    source_name: "done.mp4",
    content_subject: null,
    content_summary: null,
    status: "done",
    language: "zh-CN",
    channel_profile: null,
    workflow_mode: "standard_edit",
    enhancement_modes: [],
    file_hash: null,
    error_message: null,
    created_at: "2026-03-12T10:00:00Z",
    updated_at: "2026-03-12T10:10:00Z",
    steps: [],
  },
  {
    id: "job_2",
    source_name: "running.mp4",
    content_subject: null,
    content_summary: null,
    status: "running",
    language: "zh-CN",
    channel_profile: null,
    workflow_mode: "standard_edit",
    enhancement_modes: ["avatar_commentary"],
    file_hash: null,
    error_message: null,
    created_at: "2026-03-12T10:20:00Z",
    updated_at: "2026-03-12T10:30:00Z",
    steps: [],
  },
  {
    id: "job_3",
    source_name: "processing.mp4",
    content_subject: null,
    content_summary: null,
    status: "processing",
    language: "zh-CN",
    channel_profile: null,
    workflow_mode: "standard_edit",
    enhancement_modes: ["ai_director"],
    file_hash: null,
    error_message: null,
    created_at: "2026-03-12T10:40:00Z",
    updated_at: "2026-03-12T10:50:00Z",
    steps: [],
  },
];

const SAMPLE_ROOTS: WatchRoot[] = [
  {
    id: "root_1",
    path: "D:/watch/source",
    channel_profile: "edc",
    enabled: true,
    scan_mode: "fast",
    created_at: "2026-03-12T10:00:00Z",
  },
];

const SAMPLE_GLOSSARY: GlossaryTerm[] = [
  {
    id: "term_1",
    scope_type: "global",
    scope_value: "",
    wrong_forms: ["gpt4"],
    correct_form: "GPT-4",
    category: "model",
    context_hint: null,
    created_at: "2026-03-12T10:00:00Z",
  },
  {
    id: "term_2",
    scope_type: "domain",
    scope_value: "gear",
    wrong_forms: ["fas"],
    correct_form: "FAS",
    category: "brand",
    context_hint: null,
    created_at: "2026-03-12T10:01:00Z",
  },
];

const SAMPLE_SERVICES: ServiceStatus = {
  checked_at: "2026-03-12T10:00:00Z",
  services: {
    api: true,
    worker: true,
  },
};

describe("useOverviewWorkspace", () => {
  beforeEach(() => {
    mockApi.listJobs.mockResolvedValue(SAMPLE_JOBS);
    mockApi.getJobsUsageSummary.mockResolvedValue({
      job_count: 3,
      jobs_with_telemetry: 2,
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
          job_count: 3,
          jobs_with_telemetry: 2,
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
          top_entry: { dimension: "step", name: "content_profile", label: "内容摘要", total_tokens: 3100 },
          top_step: { step_name: "content_profile", label: "内容摘要", total_tokens: 3100 },
        },
      ],
    });
    mockApi.listWatchRoots.mockResolvedValue(SAMPLE_ROOTS);
    mockApi.listGlossary.mockResolvedValue(SAMPLE_GLOSSARY);
    mockApi.getControlStatus.mockResolvedValue(SAMPLE_SERVICES);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("aggregates dashboard statistics from loaded queries", async () => {
    const { result } = renderHookWithQueryClient(() => useOverviewWorkspace());

    await waitFor(() => expect(result.current.jobs.data).toEqual(SAMPLE_JOBS));
    await waitFor(() =>
      expect(result.current.stats).toEqual({
        jobs: 3,
        running: 2,
        watchRoots: 1,
        glossary: 2,
      }),
    );
    expect(result.current.usageSummary.data?.total_tokens).toBe(4100);
    expect(result.current.usageTrend.data?.points[0]?.label).toBe("03-12");
    expect(result.current.services.data).toEqual(SAMPLE_SERVICES);
  });
});

import { waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { GlossaryTerm, Job, ServiceStatus, WatchRoot } from "../../types";
import { useOverviewWorkspace } from "./useOverviewWorkspace";

const mockApi = vi.hoisted(() => ({
  listJobs: vi.fn(),
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
    wrong_forms: ["gpt4"],
    correct_form: "GPT-4",
    category: "model",
    context_hint: null,
    created_at: "2026-03-12T10:00:00Z",
  },
  {
    id: "term_2",
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
    expect(result.current.services.data).toEqual(SAMPLE_SERVICES);
  });
});

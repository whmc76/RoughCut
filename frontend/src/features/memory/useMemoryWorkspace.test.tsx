import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { ContentProfileMemoryStats } from "../../types";
import { useMemoryWorkspace } from "./useMemoryWorkspace";

const mockApi = vi.hoisted(() => ({
  getMemoryStats: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_GLOBAL_STATS: ContentProfileMemoryStats = {
  scope: "global",
  subject_domain: null,
  subject_domains: ["edc", "software"],
  total_corrections: 10,
  total_keywords: 24,
  field_preferences: {},
  keyword_preferences: [],
  recent_corrections: [],
  cloud: {
    words: [{ label: "升级", count: 4 }],
  },
};

const SAMPLE_CHANNEL_STATS: ContentProfileMemoryStats = {
  ...SAMPLE_GLOBAL_STATS,
  scope: "channel",
  subject_domain: "edc",
  total_corrections: 7,
};

describe("useMemoryWorkspace", () => {
  beforeEach(() => {
    mockApi.getMemoryStats.mockImplementation((subjectDomain?: string) =>
      Promise.resolve(subjectDomain ? SAMPLE_CHANNEL_STATS : SAMPLE_GLOBAL_STATS),
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads global memory stats and refetches when subject domain changes", async () => {
    const { result } = renderHookWithQueryClient(() => useMemoryWorkspace());

    await waitFor(() => expect(result.current.stats.data).toEqual(SAMPLE_GLOBAL_STATS));
    expect(mockApi.getMemoryStats).toHaveBeenCalledWith(undefined);

    act(() => {
      result.current.setSubjectDomain("edc");
    });

    await waitFor(() => expect(result.current.stats.data).toEqual(SAMPLE_CHANNEL_STATS));
    expect(mockApi.getMemoryStats).toHaveBeenLastCalledWith("edc");
  });
});

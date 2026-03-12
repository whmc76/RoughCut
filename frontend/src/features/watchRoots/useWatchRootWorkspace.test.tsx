import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { WatchInventoryStatus, WatchRoot } from "../../types";
import { useWatchRootWorkspace } from "./useWatchRootWorkspace";

const mockApi = vi.hoisted(() => ({
  listWatchRoots: vi.fn(),
  getInventoryStatus: vi.fn(),
  createWatchRoot: vi.fn(),
  updateWatchRoot: vi.fn(),
  deleteWatchRoot: vi.fn(),
  startInventoryScan: vi.fn(),
  enqueueInventory: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_ROOTS: WatchRoot[] = [
  {
    id: "root_1",
    path: "D:/videos/source",
    channel_profile: "edc_tactical",
    enabled: true,
    scan_mode: "fast",
    created_at: "2026-03-12T10:00:00Z",
  },
  {
    id: "root_2",
    path: "D:/videos/backup",
    channel_profile: null,
    enabled: false,
    scan_mode: "precise",
    created_at: "2026-03-12T11:00:00Z",
  },
];

const SAMPLE_INVENTORY: WatchInventoryStatus = {
  root_path: "D:/videos/source",
  scan_mode: "fast",
  status: "idle",
  started_at: "2026-03-12T10:01:00Z",
  updated_at: "2026-03-12T10:01:00Z",
  finished_at: "2026-03-12T10:01:03Z",
  total_files: 3,
  processed_files: 3,
  pending_count: 2,
  deduped_count: 1,
  current_file: null,
  current_phase: null,
  current_file_size_bytes: null,
  current_file_processed_bytes: null,
  error: null,
  inventory: {
    pending: [],
    deduped: [],
  },
};

describe("useWatchRootWorkspace", () => {
  beforeEach(() => {
    mockApi.listWatchRoots.mockResolvedValue(SAMPLE_ROOTS);
    mockApi.getInventoryStatus.mockResolvedValue(SAMPLE_INVENTORY);
    mockApi.createWatchRoot.mockResolvedValue(SAMPLE_ROOTS[0]);
    mockApi.updateWatchRoot.mockResolvedValue(SAMPLE_ROOTS[0]);
    mockApi.deleteWatchRoot.mockResolvedValue({});
    mockApi.startInventoryScan.mockResolvedValue({});
    mockApi.enqueueInventory.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("auto-selects the first root and hydrates the edit form", async () => {
    const { result } = renderHookWithQueryClient(() => useWatchRootWorkspace());

    await waitFor(() => expect(result.current.selectedRootId).toBe("root_1"));
    expect(result.current.form).toEqual({
      path: "D:/videos/source",
      channel_profile: "edc_tactical",
      enabled: true,
      scan_mode: "fast",
    });
  });

  it("enqueues selected pending items for the active root and clears selection", async () => {
    const { result } = renderHookWithQueryClient(() => useWatchRootWorkspace());

    await waitFor(() => expect(result.current.selectedRootId).toBe("root_1"));

    act(() => {
      result.current.setSelectedPending(["a.mp4", "b.mp4"]);
    });

    await act(async () => {
      await result.current.enqueue.mutateAsync(false);
    });

    expect(mockApi.enqueueInventory).toHaveBeenCalledWith("root_1", ["a.mp4", "b.mp4"], false);
    expect(result.current.selectedPending).toEqual([]);
  });
});

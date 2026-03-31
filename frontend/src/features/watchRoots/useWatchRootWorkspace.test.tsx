import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { WatchInventoryStatus, WatchRoot } from "../../types";
import { useWatchRootWorkspace } from "./useWatchRootWorkspace";

const mockApi = vi.hoisted(() => ({
  listWatchRoots: vi.fn(),
  getConfigOptions: vi.fn(),
  getInventoryStatus: vi.fn(),
  createWatchRoot: vi.fn(),
  updateWatchRoot: vi.fn(),
  deleteWatchRoot: vi.fn(),
  startInventoryScan: vi.fn(),
  enqueueInventory: vi.fn(),
  mergeInventory: vi.fn(),
  getSmartMergeGroups: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_ROOTS: WatchRoot[] = [
  {
    id: "root_1",
    path: "D:/videos/source",
    workflow_template: "edc_tactical",
    enabled: true,
    scan_mode: "fast",
    created_at: "2026-03-12T10:00:00Z",
  },
  {
    id: "root_2",
    path: "D:/videos/backup",
    workflow_template: null,
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
    mockApi.getConfigOptions.mockResolvedValue({
      job_languages: [{ value: "zh-CN", label: "简体中文" }],
      workflow_templates: [{ value: "", label: "自动匹配" }, { value: "edc_tactical", label: "EDC 战术版模板 (edc_tactical)" }],
      workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
      enhancement_modes: [],
      creative_mode_catalog: { workflow_modes: [], enhancement_modes: [] },
      transcription_models: {},
      multimodal_fallback_providers: [],
      search_providers: [],
      search_fallback_providers: [],
    });
    mockApi.getInventoryStatus.mockResolvedValue(SAMPLE_INVENTORY);
    mockApi.createWatchRoot.mockResolvedValue(SAMPLE_ROOTS[0]);
    mockApi.updateWatchRoot.mockImplementation(async (rootId: string, body: Partial<WatchRoot>) => ({
      ...SAMPLE_ROOTS.find((root) => root.id === rootId)!,
      ...body,
    }));
    mockApi.deleteWatchRoot.mockResolvedValue({});
    mockApi.startInventoryScan.mockResolvedValue({});
    mockApi.enqueueInventory.mockResolvedValue({});
    mockApi.mergeInventory.mockResolvedValue({});
    mockApi.getSmartMergeGroups.mockResolvedValue({ source_count: 0, groups: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("auto-selects the first root and hydrates the edit form", async () => {
    const { result } = renderHookWithQueryClient(() => useWatchRootWorkspace());

    await waitFor(() => expect(result.current.selectedRootId).toBe("root_1"));
    expect(result.current.form).toEqual({
      path: "D:/videos/source",
      workflow_template: "edc_tactical",
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

  it("merges selected pending items for the active root and clears selection", async () => {
    const { result } = renderHookWithQueryClient(() => useWatchRootWorkspace());

    await waitFor(() => expect(result.current.selectedRootId).toBe("root_1"));

    act(() => {
      result.current.setSelectedPending(["a.mp4", "b.mp4"]);
    });

    await act(async () => {
      await result.current.merge.mutateAsync();
    });

    expect(mockApi.mergeInventory).toHaveBeenCalledWith("root_1", ["a.mp4", "b.mp4"]);
    expect(result.current.selectedPending).toEqual([]);
  });

  it("autosaves edits for the selected root", async () => {
    const { result } = renderHookWithQueryClient(() => useWatchRootWorkspace());

    await waitFor(() => expect(result.current.selectedRootId).toBe("root_1"));

    act(() => {
      result.current.setForm((prev) => ({
        ...prev,
        path: "D:/videos/source-updated",
      }));
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    await waitFor(() =>
      expect(mockApi.updateWatchRoot).toHaveBeenCalledWith(
        "root_1",
        expect.objectContaining({ path: "D:/videos/source-updated" }),
      ),
    );
    await waitFor(() => expect(result.current.updateState).toBe("saved"));
  });
});

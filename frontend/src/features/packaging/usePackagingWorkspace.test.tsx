import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { PackagingLibrary } from "../../types";
import { usePackagingWorkspace } from "./usePackagingWorkspace";

const mockApi = vi.hoisted(() => ({
  getPackaging: vi.fn(),
  patchPackagingConfig: vi.fn(),
  deletePackagingAsset: vi.fn(),
  uploadPackagingAsset: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_LIBRARY: PackagingLibrary = {
  assets: {
    intro: [],
    outro: [],
    insert: [],
    music: [],
    watermark: [],
  },
  config: {
    intro_asset_id: null,
    outro_asset_id: null,
    insert_asset_id: null,
    insert_asset_ids: ["insert_1"],
    insert_selection_mode: "manual",
    insert_position_mode: "llm",
    watermark_asset_id: null,
    music_asset_ids: ["music_1"],
    music_selection_mode: "random",
    music_loop_mode: "loop_all",
    subtitle_style: "clean_box",
    subtitle_motion_style: "motion_static",
    smart_effect_style: "smart_effect_rhythm",
    cover_style: "tech_display",
    title_style: "follow_strategy",
    copy_style: "attention_grabbing",
    music_volume: 0.4,
    watermark_position: "top_right",
    watermark_opacity: 0.6,
    watermark_scale: 0.18,
    avatar_overlay_position: "bottom_right",
    avatar_overlay_scale: 0.28,
    avatar_overlay_corner_radius: 26,
    avatar_overlay_border_width: 4,
    avatar_overlay_border_color: "#F4E4B8",
    enabled: true,
  },
};

describe("usePackagingWorkspace", () => {
  beforeEach(() => {
    mockApi.getPackaging.mockResolvedValue(SAMPLE_LIBRARY);
    mockApi.patchPackagingConfig.mockResolvedValue(SAMPLE_LIBRARY.config);
    mockApi.deletePackagingAsset.mockResolvedValue({});
    mockApi.uploadPackagingAsset.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("merges pool values when toggling a packaging asset", async () => {
    const { result } = renderHookWithQueryClient(() =>
      usePackagingWorkspace([
        { key: "insert" },
        { key: "music" },
      ]),
    );

    await waitFor(() => expect(result.current.packaging.data?.config.insert_asset_ids).toEqual(["insert_1"]));

    act(() => {
      result.current.togglePool("insert_asset_ids", "insert_2", true);
    });

    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith({
        insert_asset_ids: ["insert_1", "insert_2"],
      }),
    );
  });
});

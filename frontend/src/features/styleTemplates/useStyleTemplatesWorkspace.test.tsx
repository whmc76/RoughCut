import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { PackagingLibrary } from "../../types";
import { useStyleTemplatesWorkspace } from "./useStyleTemplatesWorkspace";

const mockApi = vi.hoisted(() => ({
  getPackaging: vi.fn(),
  patchPackagingConfig: vi.fn(),
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
    insert_asset_ids: [],
    insert_selection_mode: "manual",
    insert_position_mode: "llm",
    watermark_asset_id: null,
    music_asset_ids: [],
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

describe("useStyleTemplatesWorkspace", () => {
  beforeEach(() => {
    mockApi.getPackaging.mockResolvedValue(SAMPLE_LIBRARY);
    mockApi.patchPackagingConfig.mockResolvedValue(SAMPLE_LIBRARY.config);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("toggles group state by section-scoped key", async () => {
    const { result } = renderHookWithQueryClient(() => useStyleTemplatesWorkspace());

    await waitFor(() => expect(result.current.packaging.data).toEqual(SAMPLE_LIBRARY));

    act(() => {
      result.current.toggleGroup("subtitle", "shortvideo");
    });
    expect(result.current.openGroups["subtitle:shortvideo"]).toBe(true);

    act(() => {
      result.current.toggleGroup("subtitle", "shortvideo");
    });
    expect(result.current.openGroups["subtitle:shortvideo"]).toBe(false);
  });

  it("persists style selection through packaging config mutation", async () => {
    const { result } = renderHookWithQueryClient(() => useStyleTemplatesWorkspace());

    await waitFor(() => expect(result.current.packaging.data?.config.subtitle_style).toBe("clean_box"));

    await act(async () => {
      await result.current.saveConfig.mutateAsync({ subtitle_style: "bold_yellow_outline" });
    });

    expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith({
      subtitle_style: "bold_yellow_outline",
    });
  });
});

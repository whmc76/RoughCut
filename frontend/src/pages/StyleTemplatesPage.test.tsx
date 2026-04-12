import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { createTestQueryClient } from "../test/renderWithQueryClient";
import type { PackagingLibrary } from "../types";
import { StyleTemplatesPage } from "./StyleTemplatesPage";

const mockStyleWorkspace = vi.hoisted(() => ({
  packaging: { data: null as PackagingLibrary | null, isLoading: false },
  saveConfig: { mutate: vi.fn(), isPending: false },
}));

vi.mock("../features/styleTemplates/useStyleTemplatesWorkspace", () => ({
  useStyleTemplatesWorkspace: () => mockStyleWorkspace,
}));

const SAMPLE_PACKAGING: PackagingLibrary = {
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
    music_loop_mode: "loop_single",
    subtitle_style: "sale_banner",
    subtitle_motion_style: "motion_strobe",
    smart_effect_style: "smart_effect_punch",
    cover_style: "ecommerce_sale",
    title_style: "double_banner",
    copy_style: "attention_grabbing",
    music_volume: 0.12,
    watermark_position: "top_left",
    watermark_opacity: 0.82,
    watermark_scale: 0.16,
    avatar_overlay_position: "top_right",
    avatar_overlay_scale: 0.18,
    avatar_overlay_corner_radius: 26,
    avatar_overlay_border_width: 4,
    avatar_overlay_border_color: "#F4E4B8",
    export_resolution_mode: "source",
    export_resolution_preset: "1080p",
    enabled: true,
  },
};

function renderPage() {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StyleTemplatesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StyleTemplatesPage", () => {
  beforeEach(() => {
    mockStyleWorkspace.packaging.data = SAMPLE_PACKAGING;
    mockStyleWorkspace.packaging.isLoading = false;
    mockStyleWorkspace.saveConfig.isPending = false;
    mockStyleWorkspace.saveConfig.mutate.mockReset();
  });

  it("renders real preview bundles and applies the selected bundle config", () => {
    renderPage();

    expect(screen.getByAltText("爆点带货 字幕真实效果图")).toBeInTheDocument();
    expect(screen.getAllByText("真实渲染")).toHaveLength(4);
    expect(screen.getAllByText("当前方案")).toHaveLength(2);

    const hardcoreCard = screen.getByText("硬核参数").closest("article");
    expect(hardcoreCard).not.toBeNull();
    fireEvent.click(within(hardcoreCard as HTMLElement).getByRole("button", { name: "套用这套" }));

    expect(mockStyleWorkspace.saveConfig.mutate).toHaveBeenCalledWith({
      subtitle_style: "keyword_highlight",
      subtitle_motion_style: "motion_glitch",
      smart_effect_style: "smart_effect_glitch",
      cover_style: "clean_lab",
      title_style: "tutorial_blueprint",
      copy_style: "trusted_expert",
    });
  });

  it("switches into same-copy compare mode and opens the preview dialog", () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "切到同句对照" }));

    expect(screen.getByText("同一句样句：重点词一炸，客户立刻看懂")).toBeInTheDocument();
    expect(screen.getByAltText("爆点带货 同句真实对照图")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "放大查看" })[0]);

    expect(screen.getByRole("dialog", { name: "爆点带货 真实效果图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "回到成片图" })).toBeInTheDocument();
  });
});

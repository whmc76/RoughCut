import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import type { AvatarMaterialLibrary, Config, PackagingLibrary } from "../../types";
import { api } from "../../api";
import { createTestQueryClient } from "../../test/renderWithQueryClient";
import { JobReviewConfigSection } from "./JobReviewConfigSection";

vi.mock("../../api", () => ({
  api: {
    getConfigProfiles: vi.fn(),
    getRuntimeEnvironment: vi.fn(),
    activateConfigProfile: vi.fn(),
    createConfigProfile: vi.fn(),
    updateConfigProfile: vi.fn(),
    deleteConfigProfile: vi.fn(),
  },
}));

const baseConfig: Partial<Config> = {
  default_job_workflow_mode: "standard_edit",
  default_job_enhancement_modes: ["avatar_commentary"],
  avatar_presenter_id: "",
};

const packaging: PackagingLibrary = {
  assets: {},
  config: {
    insert_asset_ids: [],
    music_asset_ids: [],
    insert_selection_mode: "manual",
    insert_position_mode: "llm",
    music_selection_mode: "random",
    music_loop_mode: "loop_single",
    subtitle_style: "bold_yellow_outline",
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
};

function renderSection(avatarMaterials?: Partial<AvatarMaterialLibrary>, config?: Partial<Config>) {
  const queryClient = createTestQueryClient();
  vi.mocked(api.getConfigProfiles).mockResolvedValue({
    active_profile_id: null,
    active_profile_dirty: false,
    active_profile_dirty_keys: [],
    active_profile_dirty_details: [],
    profiles: [],
  });
  vi.mocked(api.getRuntimeEnvironment).mockResolvedValue({
    openai_base_url: "https://api.openai.com/v1",
    openai_auth_mode: "api_key",
    openai_api_key_helper: "",
    anthropic_base_url: "https://api.anthropic.com",
    anthropic_auth_mode: "api_key",
    anthropic_api_key_helper: "",
    minimax_base_url: "https://api.minimaxi.com/v1",
    minimax_api_host: "https://api.minimaxi.com",
    ollama_base_url: "http://127.0.0.1:11434",
    avatar_api_base_url: "http://127.0.0.1:49202",
    avatar_training_api_base_url: "http://127.0.0.1:49204",
    voice_clone_api_base_url: "http://127.0.0.1:49204",
    output_dir: "output",
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <JobReviewConfigSection
        enhancementModes={["avatar_commentary"]}
        packaging={packaging}
        avatarMaterials={avatarMaterials as AvatarMaterialLibrary | undefined}
        config={{ ...baseConfig, ...config } as Config}
      />
    </QueryClientProvider>,
  );
}

describe("JobReviewConfigSection", () => {
  it("shows avatar mode as ready when a preview-ready profile can be auto-selected", () => {
    renderSection({
      profiles: [
        {
          id: "profile_1",
          display_name: "店播数字人A",
          presenter_alias: null,
          notes: null,
          profile_dir: "data/avatar_materials/profiles/profile_1",
          training_status: "ready_for_manual_training",
          training_provider: "heygem",
          training_api_available: true,
          next_action: "ready",
          capability_status: { preview: "ready" },
          blocking_issues: [],
          warnings: [],
          created_at: "2026-03-13T00:00:00Z",
          files: [],
          preview_runs: [],
        },
      ],
    });

    expect(screen.getByText(/未显式绑定 avatar_presenter_id，但已有可用数字人档案：店播数字人A/)).toBeTruthy();
  });

  it("warns that avatar commentary will degrade gracefully when no presenter source is available", () => {
    renderSection({ profiles: [] });

    expect(screen.getByText("待补")).toBeTruthy();
    expect(screen.getByText(/本次任务会退回普通成片，不会生成数字人口播画中画/)).toBeTruthy();
  });

  it("keeps only config switching and review checks in the review card", () => {
    renderSection({ profiles: [] });

    expect(screen.getByText("方案与审核")).toBeTruthy();
    expect(screen.getByText("方案")).toBeTruthy();
    expect(screen.getByText("审核就绪检查")).toBeTruthy();
    expect(screen.queryByText("工作流模式")).toBeNull();
    expect(screen.queryByText("包装素材清单")).toBeNull();
    expect(screen.queryByText("风格模板清单")).toBeNull();
  });
});

import { render, screen } from "@testing-library/react";

import type { AvatarMaterialLibrary, Config, PackagingLibrary, SelectOption } from "../../types";
import { JobReviewConfigSection } from "./JobReviewConfigSection";

const workflowOptions: SelectOption[] = [{ value: "standard_edit", label: "标准成片" }];
const enhancementOptions: SelectOption[] = [{ value: "avatar_commentary", label: "数字人解说" }];

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
  return render(
    <JobReviewConfigSection
      workflowMode="standard_edit"
      enhancementModes={["avatar_commentary"]}
      workflowOptions={workflowOptions}
      enhancementOptions={enhancementOptions}
      copyStyle="attention_grabbing"
      packaging={packaging}
      avatarMaterials={avatarMaterials as AvatarMaterialLibrary | undefined}
      config={{ ...baseConfig, ...config } as Config}
      onWorkflowModeChange={() => {}}
      onEnhancementModesChange={() => {}}
      onCopyStyleChange={() => {}}
    />,
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

    expect(screen.getByText(/未显式绑定 avatar_presenter_id，但已有可用数字人档案：店播数字人A/)).toBeInTheDocument();
  });

  it("warns that avatar commentary will degrade gracefully when no presenter source is available", () => {
    renderSection({ profiles: [] });

    expect(screen.getByText("待补")).toBeInTheDocument();
    expect(screen.getByText(/本次任务会退回普通成片，不会生成数字人口播画中画/)).toBeInTheDocument();
  });
});

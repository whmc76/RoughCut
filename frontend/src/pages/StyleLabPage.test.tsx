import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { createTestQueryClient } from "../test/renderWithQueryClient";
import type { AvatarMaterialLibrary, Config, ConfigOptions, PackagingLibrary } from "../types";
import { StyleLabPage } from "./StyleLabPage";

const mockApi = vi.hoisted(() => ({
  getConfigOptions: vi.fn(),
  getConfig: vi.fn(),
  getAvatarMaterials: vi.fn(),
  patchConfig: vi.fn(),
  patchPackagingConfig: vi.fn(),
}));

const mockStyleWorkspace = vi.hoisted(() => ({
  packaging: { data: null as PackagingLibrary | null, isLoading: false },
  saveConfig: { mutate: vi.fn(), isPending: false },
}));

vi.mock("../api", () => ({
  api: mockApi,
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
    music_loop_mode: "loop_all",
    subtitle_style: "clean_box",
    subtitle_motion_style: "motion_static",
    smart_effect_style: "smart_effect_rhythm",
    cover_style: "tech_showcase",
    title_style: "tutorial_blueprint",
    copy_style: "trusted_expert",
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

const SAMPLE_CONFIG: Config = {
  persistence: {
    settings_store: "db",
    profiles_store: "db",
    packaging_store: "db",
    legacy_override_file_present: false,
    legacy_profiles_file_present: false,
    legacy_packaging_manifest_present: false,
  },
  transcription_provider: "openai",
  transcription_model: "whisper",
  transcription_dialect: "auto",
  llm_mode: "performance",
  reasoning_provider: "openai",
  reasoning_model: "gpt-5",
  local_reasoning_model: "qwen",
  local_vision_model: "qwen-vl",
  multimodal_fallback_provider: "openai",
  multimodal_fallback_model: "gpt-4o",
  search_provider: "auto",
  search_fallback_provider: "searxng",
  model_search_helper: "auto",
  qwen_asr_api_base_url: "",
  avatar_provider: "heygem",
  avatar_api_key_set: true,
  avatar_presenter_id: "",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.28,
  voice_provider: "indextts2",
  voice_clone_api_key_set: true,
  voice_clone_voice_id: "",
  director_rewrite_strength: 0.55,
  ollama_api_key_set: false,
  openai_api_key_set: true,
  anthropic_api_key_set: false,
  minimax_api_key_set: false,
  minimax_coding_plan_api_key_set: false,
  max_upload_size_mb: 100,
  max_video_duration_sec: 600,
  ffmpeg_timeout_sec: 600,
  allowed_extensions: [".mp4"],
  preferred_ui_language: "zh-CN",
  telegram_agent_enabled: false,
  telegram_agent_claude_enabled: false,
  telegram_agent_claude_command: "",
  telegram_agent_claude_model: "",
  telegram_agent_codex_command: "",
  telegram_agent_codex_model: "",
  telegram_agent_acp_command: "",
  telegram_agent_task_timeout_sec: 0,
  telegram_agent_result_max_chars: 0,
  telegram_agent_state_dir: "",
  acp_bridge_backend: "",
  acp_bridge_fallback_backend: "",
  acp_bridge_claude_model: "",
  acp_bridge_codex_command: "",
  acp_bridge_codex_model: "",
  telegram_remote_review_enabled: false,
  telegram_bot_api_base_url: "",
  telegram_bot_token_set: false,
  telegram_bot_chat_id: "",
  default_job_workflow_mode: "standard_edit",
  default_job_enhancement_modes: [],
  fact_check_enabled: false,
  auto_confirm_content_profile: false,
  content_profile_review_threshold: 0,
  content_profile_auto_review_min_accuracy: 0,
  content_profile_auto_review_min_samples: 0,
  auto_accept_glossary_corrections: false,
  glossary_correction_review_threshold: 0,
  auto_select_cover_variant: false,
  cover_selection_review_gap: 0,
  packaging_selection_review_gap: 0,
  packaging_selection_min_score: 0,
  subtitle_filler_cleanup_enabled: false,
  quality_auto_rerun_enabled: false,
  quality_auto_rerun_below_score: 0,
  quality_auto_rerun_max_attempts: 0,
  override_keys: [],
  session_secret_keys: [],
  profile_bindable_keys: [],
  overrides: {},
};

const SAMPLE_OPTIONS: ConfigOptions = {
  job_languages: [],
  workflow_templates: [],
  workflow_modes: [{ value: "standard_edit", label: "标准剪辑" }],
  enhancement_modes: [{ value: "avatar_commentary", label: "数字人解说" }],
  transcription_dialects: [],
  avatar_providers: [],
  voice_providers: [],
  creative_mode_catalog: {
    workflow_modes: [
      {
        key: "standard_edit",
        kind: "workflow",
        status: "active",
        title: "标准剪辑",
        tagline: "直接出片",
        summary: "直接输出主成片。",
        suitable_for: ["通用"],
        pipeline_outline: ["输入", "处理", "输出"],
        delivery_scope: "主成片",
      },
    ],
    enhancement_modes: [
      {
        key: "avatar_commentary",
        kind: "enhancement",
        status: "active",
        title: "数字人解说",
        tagline: "画面叠加",
        summary: "叠加到主成片，可形成含数字人的增强版输出。",
        suitable_for: ["解说"],
        pipeline_outline: ["输入", "处理", "叠加"],
        providers: ["heygem"],
        delivery_scope: "增强版",
      },
    ],
  },
  transcription_models: {},
  multimodal_fallback_providers: [],
  search_providers: [],
  search_fallback_providers: [],
};

const SAMPLE_AVATAR_MATERIALS: AvatarMaterialLibrary = {
  provider: "heygem",
  training_api_available: true,
  preview_service_available: true,
  intake_mode: "manual",
  warnings: [],
  summary: "profiles",
  sections: [],
  profiles: [
    {
      id: "profile-a",
      display_name: "主讲人 A",
      presenter_alias: "A",
      notes: "",
      creator_profile: {
        identity: { public_name: "A" },
        positioning: { expertise: ["教程", "测评"] },
        publishing: { primary_platform: "B站" },
      },
      profile_dashboard: {
        completeness_score: 80,
        section_status: { materials: true },
        material_counts: { speaking_videos: 1, portrait_photos: 0, voice_samples: 0 },
        strengths: [],
        next_steps: [],
      },
      profile_dir: "/profiles/a",
      training_status: "ready_for_manual_training",
      training_provider: "heygem",
      training_api_available: true,
      next_action: "可直接启用",
      capability_status: {},
      blocking_issues: [],
      warnings: [],
      created_at: "2026-04-08T00:00:00Z",
      files: [
        {
          id: "file-a",
          original_name: "host-a.mp4",
          stored_name: "host-a.mp4",
          kind: "video",
          role: "speaking_video",
          role_label: "讲话视频",
          pipeline_target: "heygem_avatar",
          content_type: "video/mp4",
          size_bytes: 1,
          path: "/profiles/host-a.mp4",
          created_at: "2026-04-08T00:00:00Z",
          probe: null,
          artifacts: null,
          checks: [],
        },
      ],
      preview_runs: [],
    },
  ],
};

function renderPage() {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StyleLabPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StyleLabPage", () => {
  beforeEach(() => {
    mockStyleWorkspace.packaging.data = SAMPLE_PACKAGING;
    mockApi.getConfigOptions.mockResolvedValue(SAMPLE_OPTIONS);
    mockApi.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mockApi.getAvatarMaterials.mockResolvedValue(SAMPLE_AVATAR_MATERIALS);
    mockApi.patchConfig.mockResolvedValue(SAMPLE_CONFIG);
    mockApi.patchPackagingConfig.mockResolvedValue(SAMPLE_PACKAGING.config);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the merged control surface without summary cards", async () => {
    const { container } = renderPage();

    expect(await screen.findByRole("button", { name: "粗黄描边" })).toBeInTheDocument();
    expect(container.querySelector(".style-lab-page")).toBeInTheDocument();
    expect(container.querySelector(".style-lab-hero")).toBeInTheDocument();
    expect(container.querySelector(".style-lab-surface")).toBeInTheDocument();
    expect(container.querySelector(".style-lab-presenter-stage")).toBeInTheDocument();
    expect(screen.getByText("模式和增强")).toBeInTheDocument();
    expect(screen.getByText("字幕、标题、文案、封面")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看包装" })).toHaveAttribute("href", "/packaging");
    expect(screen.queryByText("第一段")).not.toBeInTheDocument();
    expect(screen.queryByText("第二段")).not.toBeInTheDocument();
    expect(screen.queryByText("第三段")).not.toBeInTheDocument();
  });

  it("saves style selections through the packaging workspace", async () => {
    renderPage();

    const subtitleButton = await screen.findByRole("button", { name: "粗黄描边" });
    fireEvent.click(subtitleButton);

    expect(mockStyleWorkspace.saveConfig.mutate).toHaveBeenCalledWith({ subtitle_style: "bold_yellow_outline" });
  });

  it("toggles enhancement modes and activates creator defaults", async () => {
    renderPage();

    const enhancementButton = await screen.findByRole("button", { name: "启用" });
    fireEvent.click(enhancementButton);

    await waitFor(() => {
      expect(mockApi.patchConfig).toHaveBeenCalledWith({ default_job_enhancement_modes: ["avatar_commentary"] });
    });

    const presenterLabel = await screen.findByText("主讲人 A");
    fireEvent.click(presenterLabel.closest("button") ?? presenterLabel);

    await waitFor(() => {
      expect(mockApi.patchConfig).toHaveBeenCalledWith({ avatar_presenter_id: "/profiles/host-a.mp4" });
    });
  });
});

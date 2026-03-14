import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Config, ConfigOptions } from "../../types";
import { CreativeSettingsPanel } from "./CreativeSettingsPanel";
import type { SettingsForm } from "./constants";

const mockApi = vi.hoisted(() => ({
  getAvatarMaterials: vi.fn(),
  getPackaging: vi.fn(),
  patchPackagingConfig: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_CONFIG: Config = {
  transcription_provider: "openai",
  transcription_model: "gpt-4o-transcribe",
  llm_mode: "performance",
  reasoning_provider: "openai",
  reasoning_model: "gpt-4.1",
  local_reasoning_model: "qwen3:8b",
  local_vision_model: "qwen2.5vl:7b",
  multimodal_fallback_provider: "openai",
  multimodal_fallback_model: "gpt-4.1-mini",
  search_provider: "auto",
  search_fallback_provider: "openai",
  model_search_helper: "gpt-4.1-mini",
  openai_base_url: "https://api.openai.com/v1",
  openai_auth_mode: "api_key",
  openai_api_key_helper: "",
  avatar_provider: "heygem",
  avatar_api_base_url: "http://127.0.0.1:49202",
  avatar_training_api_base_url: "http://127.0.0.1:49204",
  avatar_api_key_set: false,
  avatar_presenter_id: "",
  avatar_layout_template: "picture_in_picture_left",
  avatar_safe_margin: 0.1,
  avatar_overlay_scale: 0.22,
  anthropic_base_url: "https://api.anthropic.com",
  anthropic_auth_mode: "api_key",
  anthropic_api_key_helper: "",
  minimax_base_url: "https://api.minimaxi.com/v1",
  minimax_api_host: "https://api.minimaxi.com",
  voice_provider: "indextts2",
  voice_clone_api_base_url: "http://127.0.0.1:49204",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "",
  director_rewrite_strength: 0.55,
  ollama_api_key_set: false,
  openai_api_key_set: false,
  anthropic_api_key_set: false,
  minimax_api_key_set: false,
  minimax_coding_plan_api_key_set: false,
  ollama_base_url: "http://127.0.0.1:11434",
  max_upload_size_mb: 2048,
  max_video_duration_sec: 7200,
  ffmpeg_timeout_sec: 600,
  allowed_extensions: [".mp4"],
  output_dir: "data/output",
  default_job_workflow_mode: "standard_edit",
  default_job_enhancement_modes: ["avatar_commentary"],
  fact_check_enabled: true,
  auto_confirm_content_profile: true,
  content_profile_review_threshold: 0.72,
  auto_accept_glossary_corrections: true,
  glossary_correction_review_threshold: 0.9,
  auto_select_cover_variant: true,
  cover_selection_review_gap: 0.08,
  packaging_selection_review_gap: 0.08,
  packaging_selection_min_score: 0.6,
  overrides: {},
};

const SAMPLE_OPTIONS: ConfigOptions = {
  job_languages: [{ value: "zh-CN", label: "简体中文" }],
  channel_profiles: [{ value: "", label: "自动匹配" }],
  workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
  enhancement_modes: [{ value: "avatar_commentary", label: "数字人解说" }],
  avatar_providers: [{ value: "heygem", label: "heygem" }],
  voice_providers: [{ value: "indextts2", label: "indextts2" }],
  creative_mode_catalog: {
    workflow_modes: [],
    enhancement_modes: [],
  },
  transcription_models: {
    openai: ["gpt-4o-transcribe"],
  },
  multimodal_fallback_providers: [{ value: "openai", label: "OpenAI" }],
  search_providers: [{ value: "auto", label: "自动选择" }],
  search_fallback_providers: [{ value: "openai", label: "OpenAI" }],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const onChange = vi.fn();
  const form: SettingsForm = {
    avatar_provider: SAMPLE_CONFIG.avatar_provider,
    avatar_api_base_url: SAMPLE_CONFIG.avatar_api_base_url,
    avatar_training_api_base_url: SAMPLE_CONFIG.avatar_training_api_base_url,
    avatar_presenter_id: SAMPLE_CONFIG.avatar_presenter_id,
    avatar_layout_template: SAMPLE_CONFIG.avatar_layout_template,
    avatar_safe_margin: SAMPLE_CONFIG.avatar_safe_margin,
    avatar_overlay_scale: SAMPLE_CONFIG.avatar_overlay_scale,
    avatar_overlay_corner_radius: 26,
    avatar_overlay_border_width: 4,
    avatar_overlay_border_color: "#F4E4B8",
    voice_provider: SAMPLE_CONFIG.voice_provider,
    voice_clone_api_base_url: SAMPLE_CONFIG.voice_clone_api_base_url,
    voice_clone_voice_id: SAMPLE_CONFIG.voice_clone_voice_id,
    director_rewrite_strength: SAMPLE_CONFIG.director_rewrite_strength,
  };
  render(
    <QueryClientProvider client={queryClient}>
      <CreativeSettingsPanel form={form} config={SAMPLE_CONFIG} options={SAMPLE_OPTIONS} onChange={onChange} />
    </QueryClientProvider>,
  );
  return { onChange };
}

describe("CreativeSettingsPanel", () => {
  beforeEach(() => {
    mockApi.getAvatarMaterials.mockResolvedValue({ profiles: [] });
    mockApi.getPackaging.mockResolvedValue({
      assets: {},
      config: {
        intro_asset_id: null,
        outro_asset_id: null,
        insert_asset_id: null,
        insert_asset_ids: [],
        insert_selection_mode: "manual",
        insert_position_mode: "llm",
        watermark_asset_id: null,
        music_asset_ids: [],
        music_selection_mode: "manual",
        music_loop_mode: "loop_single",
        subtitle_style: "bubble_pop",
        subtitle_motion_style: "karaoke",
        smart_effect_style: "smart_effect_rhythm",
        cover_style: "ctr",
        title_style: "sharp",
        copy_style: "hook_first",
        music_volume: 0.2,
        watermark_position: "top_right",
        watermark_opacity: 0.9,
        watermark_scale: 0.2,
        avatar_overlay_position: "top_left",
        avatar_overlay_scale: 0.22,
        avatar_overlay_corner_radius: 26,
        avatar_overlay_border_width: 4,
        avatar_overlay_border_color: "#F4E4B8",
        export_resolution_mode: "specified",
        export_resolution_preset: "1080p",
        enabled: true,
      },
    });
    mockApi.patchPackagingConfig.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("writes avatar positioning and size schemes back to packaging config", async () => {
    const { onChange } = renderPanel();

    await waitFor(() => expect(mockApi.getPackaging).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("数字人解说定位方案"), {
      target: { value: "brand_safe_top_right" },
    });
    fireEvent.change(screen.getByLabelText("数字人解说尺寸方案"), {
      target: { value: "focus" },
    });

    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith(
        expect.objectContaining({ avatar_overlay_position: "top_right" }),
      ),
    );
    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith(
        expect.objectContaining({ avatar_overlay_scale: 0.26 }),
      ),
    );
    expect(onChange).toHaveBeenCalledWith("avatar_safe_margin", 0.1);
    expect(onChange).toHaveBeenCalledWith("avatar_overlay_scale", 0.26);
  });

  it("writes avatar overlay corner and border styles back to packaging config", async () => {
    renderPanel();

    await waitFor(() => expect(mockApi.getPackaging).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("数字人圆角"), {
      target: { value: "32" },
    });
    fireEvent.change(screen.getByLabelText("数字人边框宽度"), {
      target: { value: "6" },
    });
    fireEvent.change(screen.getByLabelText("数字人边框颜色"), {
      target: { value: "#FFFFFF" },
    });

    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith(
        expect.objectContaining({ avatar_overlay_corner_radius: 32 }),
      ),
    );
    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith(
        expect.objectContaining({ avatar_overlay_border_width: 6 }),
      ),
    );
    await waitFor(() =>
      expect(mockApi.patchPackagingConfig).toHaveBeenCalledWith(
        expect.objectContaining({ avatar_overlay_border_color: "#FFFFFF" }),
      ),
    );
  });
});

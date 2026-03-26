import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { Config, ConfigOptions, ConfigProfiles } from "../../types";
import { useSettingsWorkspace } from "./useSettingsWorkspace";

const mockApi = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getConfigOptions: vi.fn(),
  getConfigProfiles: vi.fn(),
  patchConfig: vi.fn(),
  resetConfig: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_CONFIG: Config = {
  persistence: {
    settings_store: "database",
    profiles_store: "database",
    packaging_store: "database",
    legacy_override_file_present: false,
    legacy_profiles_file_present: false,
    legacy_packaging_manifest_present: false,
  },
  transcription_provider: "openai",
  transcription_model: "gpt-4o-transcribe",
  transcription_dialect: "mandarin",
  llm_mode: "performance",
  preferred_ui_language: "zh-CN",
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
  qwen_asr_api_base_url: "http://127.0.0.1:18096",
  avatar_provider: "heygem",
  avatar_api_base_url: "https://api.heygem.com",
  avatar_training_api_base_url: "http://127.0.0.1:18180",
  avatar_api_key_set: false,
  avatar_presenter_id: "presenter_demo",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.24,
  anthropic_base_url: "https://api.anthropic.com",
  anthropic_auth_mode: "api_key",
  anthropic_api_key_helper: "",
  minimax_base_url: "https://api.minimax.chat",
  minimax_api_host: "https://api.minimaxi.com",
  voice_provider: "indextts2",
  voice_clone_api_base_url: "http://127.0.0.1:49204",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "voice_demo",
  director_rewrite_strength: 0.55,
  ollama_base_url: "http://127.0.0.1:11434",
  openai_api_key_set: true,
  anthropic_api_key_set: false,
  minimax_api_key_set: false,
  minimax_coding_plan_api_key_set: false,
  ollama_api_key_set: false,
  max_upload_size_mb: 2048,
  max_video_duration_sec: 7200,
  ffmpeg_timeout_sec: 600,
  allowed_extensions: [".mp4"],
  output_dir: "data/output",
  telegram_agent_enabled: true,
  telegram_agent_claude_enabled: true,
  telegram_agent_claude_command: "claude",
  telegram_agent_claude_model: "opus",
  telegram_agent_codex_command: "codex",
  telegram_agent_codex_model: "gpt-5.4-mini",
  telegram_agent_acp_command: "python scripts/acp_bridge.py",
  telegram_agent_task_timeout_sec: 900,
  telegram_agent_result_max_chars: 3500,
  telegram_agent_state_dir: "data/telegram-agent",
  acp_bridge_backend: "codex",
  acp_bridge_fallback_backend: "claude",
  acp_bridge_claude_model: "opus",
  acp_bridge_codex_command: "codex",
  acp_bridge_codex_model: "gpt-5.4-mini",
  telegram_remote_review_enabled: true,
  telegram_bot_api_base_url: "https://api.telegram.org",
  telegram_bot_token_set: false,
  telegram_bot_chat_id: "123456789",
  default_job_workflow_mode: "standard_edit",
  default_job_enhancement_modes: ["avatar_commentary"],
  fact_check_enabled: true,
  auto_confirm_content_profile: true,
  content_profile_review_threshold: 0.72,
  content_profile_auto_review_min_accuracy: 0.9,
  content_profile_auto_review_min_samples: 20,
  auto_accept_glossary_corrections: true,
  glossary_correction_review_threshold: 0.9,
  auto_select_cover_variant: true,
  cover_selection_review_gap: 0.08,
  packaging_selection_review_gap: 0.08,
  packaging_selection_min_score: 0.6,
  subtitle_filler_cleanup_enabled: true,
  quality_auto_rerun_enabled: true,
  quality_auto_rerun_below_score: 75,
  quality_auto_rerun_max_attempts: 1,
  override_keys: [],
  session_secret_keys: [],
  profile_bindable_keys: ["transcription_provider", "quality_auto_rerun_enabled"],
  overrides: {},
};

const SAMPLE_OPTIONS: ConfigOptions = {
  job_languages: [{ value: "zh-CN", label: "简体中文" }],
  channel_profiles: [{ value: "", label: "自动匹配" }],
  workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
  enhancement_modes: [
    { value: "avatar_commentary", label: "数字人解说" },
    { value: "ai_director", label: "AI 导演" },
  ],
  transcription_dialects: [
    { value: "mandarin", label: "普通话" },
    { value: "beijing", label: "北京话" },
  ],
  avatar_providers: [
    { value: "heygem", label: "heygem" },
  ],
  voice_providers: [
    { value: "indextts2", label: "indextts2" },
    { value: "runninghub", label: "runninghub" },
  ],
  creative_mode_catalog: {
    workflow_modes: [],
    enhancement_modes: [],
  },
  transcription_models: {
    openai: ["gpt-4o-transcribe"],
    local_whisper: ["large-v3"],
  },
  multimodal_fallback_providers: [
    { value: "openai", label: "OpenAI" },
    { value: "ollama", label: "Ollama" },
  ],
  search_providers: [
    { value: "auto", label: "自动选择" },
    { value: "openai", label: "OpenAI" },
  ],
  search_fallback_providers: [
    { value: "openai", label: "OpenAI" },
    { value: "searxng", label: "SearXNG" },
  ],
};

const SAMPLE_CONFIG_PROFILES: ConfigProfiles = {
  active_profile_id: "profile_active",
  active_profile_dirty: false,
  active_profile_dirty_keys: [],
  active_profile_dirty_details: [],
  profiles: [
    {
      id: "profile_active",
      name: "标准方案",
      description: "适合默认测评口播和自动复跑阈值基线",
      created_at: "2026-03-26T08:00:00Z",
      updated_at: "2026-03-26T09:30:00Z",
      is_active: true,
      is_dirty: false,
      dirty_keys: [],
      dirty_details: [],
      llm_mode: "cloud",
      transcription_provider: "openai",
      transcription_model: "gpt-4o-transcribe",
      transcription_dialect: "mandarin",
      reasoning_provider: "openai",
      reasoning_model: "gpt-4.1",
      workflow_mode: "standard_edit",
      enhancement_modes: ["avatar_commentary"],
      auto_confirm_content_profile: true,
      content_profile_review_threshold: 0.72,
      packaging_selection_min_score: 0.6,
      quality_auto_rerun_enabled: true,
      quality_auto_rerun_below_score: 75,
      copy_style: "attention_grabbing",
      cover_style: "preset_default",
      title_style: "preset_default",
      subtitle_style: "bold_yellow_outline",
      smart_effect_style: "smart_effect_rhythm",
      avatar_presenter_id: "presenter_demo",
      packaging_enabled: true,
      insert_pool_size: 0,
      music_pool_size: 0,
    },
  ],
};

describe("useSettingsWorkspace", () => {
  beforeEach(() => {
    mockApi.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mockApi.getConfigOptions.mockResolvedValue(SAMPLE_OPTIONS);
    mockApi.getConfigProfiles.mockResolvedValue(SAMPLE_CONFIG_PROFILES);
    mockApi.patchConfig.mockImplementation(async (payload: Record<string, unknown>) => ({
      ...SAMPLE_CONFIG,
      ...payload,
    }));
    mockApi.resetConfig.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("hydrates form from config and strips empty secret fields during autosave", async () => {
    const { result } = renderHookWithQueryClient(() => useSettingsWorkspace());

    await waitFor(() => expect(result.current.config.data).toEqual(SAMPLE_CONFIG));
    await waitFor(() => expect(result.current.form.max_upload_size_mb).toBe(2048));
    expect("openai_base_url" in result.current.form).toBe(false);
    expect("avatar_api_base_url" in result.current.form).toBe(false);
    expect("voice_clone_api_base_url" in result.current.form).toBe(false);
    expect("output_dir" in result.current.form).toBe(false);

    act(() => {
      result.current.setForm((prev) => ({
        ...prev,
        max_upload_size_mb: 4096,
        openai_api_key: "  ",
        anthropic_api_key: "",
      }));
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 700));
    });

    await waitFor(() =>
      expect(mockApi.patchConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          max_upload_size_mb: 4096,
        }),
      ),
    );
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("openai_api_key");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("anthropic_api_key");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("openai_base_url");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("avatar_api_base_url");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("voice_clone_api_base_url");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("output_dir");
    await waitFor(() => expect(result.current.saveState).toBe("saved"));
  });

  it("hydrates Telegram agent Codex and ACP settings into the form", async () => {
    const { result } = renderHookWithQueryClient(() => useSettingsWorkspace());

    await waitFor(() => expect(result.current.config.data).toEqual(SAMPLE_CONFIG));
    await waitFor(() => expect(result.current.configProfiles.data).toEqual(SAMPLE_CONFIG_PROFILES));
    await waitFor(() => expect(result.current.form.telegram_agent_codex_model).toBe("gpt-5.4-mini"));

    expect(result.current.form.telegram_agent_enabled).toBe(true);
    expect(result.current.form.telegram_agent_codex_command).toBe("codex");
    expect(result.current.form.acp_bridge_backend).toBe("codex");
    expect(result.current.form.acp_bridge_fallback_backend).toBe("claude");
  });
});

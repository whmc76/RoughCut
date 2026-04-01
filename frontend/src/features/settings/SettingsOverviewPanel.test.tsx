import { render, screen } from "@testing-library/react";

import type { Config, ConfigProfiles, RuntimeEnvironment } from "../../types";
import { SettingsOverviewPanel } from "./SettingsOverviewPanel";
import type { SettingsForm } from "./constants";

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
  qwen_asr_api_base_url: "http://127.0.0.1:18096",
  avatar_provider: "heygem",
  avatar_api_key_set: false,
  avatar_presenter_id: "presenter_demo",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.22,
  voice_provider: "indextts2",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "voice_demo",
  director_rewrite_strength: 0.55,
  ollama_api_key_set: false,
  openai_api_key_set: true,
  anthropic_api_key_set: false,
  minimax_api_key_set: false,
  minimax_coding_plan_api_key_set: false,
  max_upload_size_mb: 2048,
  max_video_duration_sec: 7200,
  ffmpeg_timeout_sec: 600,
  allowed_extensions: [".mp4"],
  telegram_agent_enabled: false,
  telegram_agent_claude_enabled: false,
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
  telegram_remote_review_enabled: false,
  telegram_bot_api_base_url: "https://api.telegram.org",
  telegram_bot_token_set: false,
  telegram_bot_chat_id: "",
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

const SAMPLE_RUNTIME_ENVIRONMENT: RuntimeEnvironment = {
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
  output_dir: "data/output",
};

const SAMPLE_FORM: SettingsForm = {
  transcription_provider: "openai",
  transcription_model: "gpt-4o-transcribe",
  transcription_dialect: "mandarin",
  llm_mode: "performance",
  reasoning_provider: "openai",
  reasoning_model: "gpt-4.1-mini",
  search_provider: "auto",
  search_fallback_provider: "openai",
  qwen_asr_api_base_url: "http://127.0.0.1:18096",
  avatar_provider: "heygem",
  avatar_presenter_id: "presenter_demo",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.22,
  voice_provider: "indextts2",
  voice_clone_voice_id: "voice_demo",
  director_rewrite_strength: 0.55,
  max_upload_size_mb: 2048,
  max_video_duration_sec: 7200,
  ffmpeg_timeout_sec: 600,
  fact_check_enabled: true,
  auto_confirm_content_profile: true,
  content_profile_review_threshold: 0.72,
  packaging_selection_min_score: 0.6,
  quality_auto_rerun_enabled: true,
  quality_auto_rerun_below_score: 75,
};

const SAMPLE_PROFILES: ConfigProfiles = {
  active_profile_id: "profile_active",
  active_profile_dirty: true,
  active_profile_dirty_keys: ["reasoning_model", "packaging.copy_style"],
  active_profile_dirty_details: [
    {
      key: "reasoning_model",
      saved_value: "gpt-4.1",
      current_value: "gpt-4.1-mini",
    },
    {
      key: "packaging.copy_style",
      saved_value: "trusted_expert",
      current_value: "attention_grabbing",
    },
  ],
  profiles: [
    {
      id: "profile_active",
      name: "标准方案",
      description: "适合默认测评口播和自动复跑阈值基线",
      created_at: "2026-03-26T08:00:00Z",
      updated_at: "2026-03-26T09:30:00Z",
      is_active: true,
      is_dirty: true,
      dirty_keys: ["reasoning_model", "packaging.copy_style"],
      dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
        {
          key: "packaging.copy_style",
          saved_value: "trusted_expert",
          current_value: "attention_grabbing",
        },
      ],
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
      copy_style: "trusted_expert",
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

describe("SettingsOverviewPanel", () => {
  it("shows active profile drift summary on the settings overview", () => {
    render(
      <SettingsOverviewPanel
        form={SAMPLE_FORM}
        config={SAMPLE_CONFIG}
        runtimeEnvironment={SAMPLE_RUNTIME_ENVIRONMENT}
        configProfiles={SAMPLE_PROFILES}
      />,
    );

    expect(screen.getByText("生产与方案")).toBeTruthy();
    expect(screen.getByText("标准方案")).toBeTruthy();
    expect(screen.getByText(/当前设置与方案存在 2 项差异/)).toBeTruthy();
    expect(screen.getByText(/设置 database · 方案 database · 包装 database/)).toBeTruthy();
    expect(screen.getByText(/事实核查未接入/)).toBeTruthy();
    expect(screen.getByText("推理模型")).toBeTruthy();
    expect(screen.getByText(/gpt-4.1 -> gpt-4.1-mini/)).toBeTruthy();
    expect(screen.getByText("文案风格")).toBeTruthy();
    expect(screen.getByText(/trusted_expert -> attention_grabbing/)).toBeTruthy();
  });
});

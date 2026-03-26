import { render, screen } from "@testing-library/react";

import type { Config, RuntimeEnvironment } from "../../types";
import { RuntimeSettingsPanel } from "./RuntimeSettingsPanel";
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
  transcription_provider: "qwen_asr",
  transcription_model: "qwen3-asr-1.7b",
  transcription_dialect: "beijing",
  llm_mode: "performance",
  reasoning_provider: "minimax",
  reasoning_model: "MiniMax-M2.7-highspeed",
  local_reasoning_model: "qwen3.5:9b",
  local_vision_model: "",
  multimodal_fallback_provider: "ollama",
  multimodal_fallback_model: "",
  search_provider: "auto",
  search_fallback_provider: "searxng",
  model_search_helper: "",
  qwen_asr_api_base_url: "http://127.0.0.1:18096",
  avatar_provider: "heygem",
  avatar_api_key_set: false,
  avatar_presenter_id: "",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.18,
  voice_provider: "indextts2",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "",
  director_rewrite_strength: 0.55,
  ollama_api_key_set: false,
  openai_api_key_set: false,
  anthropic_api_key_set: false,
  minimax_api_key_set: true,
  minimax_coding_plan_api_key_set: true,
  max_upload_size_mb: 2048,
  max_video_duration_sec: 7200,
  ffmpeg_timeout_sec: 600,
  allowed_extensions: [".mp4"],
  preferred_ui_language: "zh-CN",
  telegram_agent_enabled: false,
  telegram_agent_claude_enabled: false,
  telegram_agent_claude_command: "claude",
  telegram_agent_claude_model: "opus",
  telegram_agent_codex_command: "codex",
  telegram_agent_codex_model: "gpt-5.4-mini",
  telegram_agent_acp_command: "",
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
  default_job_enhancement_modes: [],
  fact_check_enabled: false,
  auto_confirm_content_profile: false,
  content_profile_review_threshold: 0.9,
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
  session_secret_keys: ["minimax_api_key"],
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
  output_dir: "output",
};

describe("RuntimeSettingsPanel", () => {
  it("shows only the active provider credentials", () => {
    const form: SettingsForm = {
      transcription_provider: SAMPLE_CONFIG.transcription_provider,
      llm_mode: SAMPLE_CONFIG.llm_mode,
      reasoning_provider: SAMPLE_CONFIG.reasoning_provider,
      search_provider: SAMPLE_CONFIG.search_provider,
      search_fallback_provider: SAMPLE_CONFIG.search_fallback_provider,
      minimax_api_key: "",
      max_upload_size_mb: SAMPLE_CONFIG.max_upload_size_mb,
      max_video_duration_sec: SAMPLE_CONFIG.max_video_duration_sec,
      ffmpeg_timeout_sec: SAMPLE_CONFIG.ffmpeg_timeout_sec,
    };

    render(
      <RuntimeSettingsPanel
        form={form}
        config={SAMPLE_CONFIG}
        runtimeEnvironment={SAMPLE_RUNTIME_ENVIRONMENT}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("接入与限制")).toBeTruthy();
    expect(screen.getByText("连接与鉴权细节")).toBeTruthy();
    expect(screen.getByText("运行环境状态")).toBeTruthy();
    expect(screen.getByText("凭据来源：当前会话")).toBeTruthy();
    expect(screen.getAllByText(/MiniMax · 当前会话/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("MiniMax API Key")).toBeTruthy();
    expect(screen.queryByLabelText("OpenAI API Key")).toBeNull();
    expect(screen.queryByLabelText("Anthropic API Key")).toBeNull();
  });
});

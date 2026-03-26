import { render, screen } from "@testing-library/react";

import type { Config } from "../../types";
import { QualitySettingsPanel } from "./QualitySettingsPanel";
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
  avatar_presenter_id: "",
  avatar_layout_template: "picture_in_picture_right",
  avatar_safe_margin: 0.08,
  avatar_overlay_scale: 0.22,
  voice_provider: "indextts2",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "",
  director_rewrite_strength: 0.55,
  ollama_api_key_set: false,
  openai_api_key_set: false,
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
  profile_bindable_keys: ["fact_check_enabled", "quality_auto_rerun_enabled"],
  overrides: {},
};

describe("QualitySettingsPanel", () => {
  it("shows only active strategy fields inside advanced disclosure", () => {
    const form: SettingsForm = {
      fact_check_enabled: true,
      auto_confirm_content_profile: false,
      auto_accept_glossary_corrections: false,
      auto_select_cover_variant: false,
      subtitle_filler_cleanup_enabled: true,
      quality_auto_rerun_enabled: false,
      packaging_selection_min_score: 0.6,
    };

    render(<QualitySettingsPanel form={form} config={SAMPLE_CONFIG} onChange={vi.fn()} />);

    expect(screen.getByText("阈值与复跑策略")).toBeInTheDocument();
    expect(screen.getByText(/画像手动确认/)).toBeInTheDocument();
    expect(screen.queryByLabelText("内容画像确认阈值")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("术语修正确认阈值")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("封面复核间隔")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("触发复跑分数线")).not.toBeInTheDocument();
    expect(screen.getByLabelText("包装最低通过分")).toHaveValue(0.6);
  });

  it("reveals thresholds when corresponding automation switches are enabled", () => {
    const form: SettingsForm = {
      fact_check_enabled: true,
      auto_confirm_content_profile: true,
      content_profile_review_threshold: 0.72,
      content_profile_auto_review_min_accuracy: 0.88,
      content_profile_auto_review_min_samples: 12,
      auto_accept_glossary_corrections: true,
      glossary_correction_review_threshold: 0.82,
      auto_select_cover_variant: true,
      cover_selection_review_gap: 0.05,
      packaging_selection_review_gap: 0.07,
      packaging_selection_min_score: 0.66,
      subtitle_filler_cleanup_enabled: true,
      quality_auto_rerun_enabled: true,
      quality_auto_rerun_below_score: 78,
      quality_auto_rerun_max_attempts: 2,
    };

    render(<QualitySettingsPanel form={form} config={SAMPLE_CONFIG} onChange={vi.fn()} />);

    expect(screen.getByLabelText("内容画像确认阈值")).toHaveValue(0.72);
    expect(screen.getByLabelText("术语修正确认阈值")).toHaveValue(0.82);
    expect(screen.getByLabelText("封面复核间隔")).toHaveValue(0.05);
    expect(screen.getByLabelText("触发复跑分数线")).toHaveValue(78);
    expect(screen.getByText(/复跑 < 78/)).toBeInTheDocument();
  });
});

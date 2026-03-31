import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { SettingsForm } from "./constants";

const EMPTY_SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "minimax_api_key", "minimax_coding_plan_api_key", "ollama_api_key", "telegram_bot_token"] as const;
const CREATIVE_SECRET_KEYS = ["avatar_api_key", "voice_clone_api_key"] as const;

function buildSettingsForm(config: NonNullable<ReturnType<typeof api.getConfig> extends Promise<infer T> ? T : never>): SettingsForm {
  return {
    transcription_provider: config.transcription_provider,
    transcription_model: config.transcription_model,
    transcription_dialect: config.transcription_dialect,
    llm_mode: config.llm_mode,
    reasoning_provider: config.reasoning_provider,
    reasoning_model: config.reasoning_model,
    local_reasoning_model: config.local_reasoning_model,
    local_vision_model: config.local_vision_model,
    multimodal_fallback_provider: config.multimodal_fallback_provider,
    multimodal_fallback_model: config.multimodal_fallback_model,
    search_provider: config.search_provider,
    search_fallback_provider: config.search_fallback_provider,
    model_search_helper: config.model_search_helper,
    qwen_asr_api_base_url: config.qwen_asr_api_base_url,
    avatar_provider: config.avatar_provider,
    avatar_presenter_id: config.avatar_presenter_id,
    avatar_layout_template: config.avatar_layout_template,
    avatar_safe_margin: config.avatar_safe_margin,
    avatar_overlay_scale: config.avatar_overlay_scale,
    voice_provider: config.voice_provider,
    voice_clone_voice_id: config.voice_clone_voice_id,
    director_rewrite_strength: config.director_rewrite_strength,
    openai_api_key: "",
    avatar_api_key: "",
    anthropic_api_key: "",
    minimax_api_key: "",
    minimax_coding_plan_api_key: "",
    ollama_api_key: "",
    voice_clone_api_key: "",
    max_upload_size_mb: config.max_upload_size_mb,
    max_video_duration_sec: config.max_video_duration_sec,
    ffmpeg_timeout_sec: config.ffmpeg_timeout_sec,
    fact_check_enabled: config.fact_check_enabled,
    auto_confirm_content_profile: config.auto_confirm_content_profile,
    content_profile_review_threshold: config.content_profile_review_threshold,
    content_profile_auto_review_min_accuracy: config.content_profile_auto_review_min_accuracy,
    content_profile_auto_review_min_samples: config.content_profile_auto_review_min_samples,
    auto_accept_glossary_corrections: config.auto_accept_glossary_corrections,
    glossary_correction_review_threshold: config.glossary_correction_review_threshold,
    auto_select_cover_variant: config.auto_select_cover_variant,
    cover_selection_review_gap: config.cover_selection_review_gap,
    packaging_selection_review_gap: config.packaging_selection_review_gap,
    packaging_selection_min_score: config.packaging_selection_min_score,
    subtitle_filler_cleanup_enabled: config.subtitle_filler_cleanup_enabled,
    quality_auto_rerun_enabled: config.quality_auto_rerun_enabled,
    quality_auto_rerun_below_score: config.quality_auto_rerun_below_score,
    quality_auto_rerun_max_attempts: config.quality_auto_rerun_max_attempts,
    telegram_agent_enabled: config.telegram_agent_enabled,
    telegram_agent_claude_enabled: config.telegram_agent_claude_enabled,
    telegram_agent_claude_command: config.telegram_agent_claude_command,
    telegram_agent_claude_model: config.telegram_agent_claude_model,
    telegram_agent_codex_command: config.telegram_agent_codex_command,
    telegram_agent_codex_model: config.telegram_agent_codex_model,
    telegram_agent_acp_command: config.telegram_agent_acp_command,
    telegram_agent_task_timeout_sec: config.telegram_agent_task_timeout_sec,
    telegram_agent_result_max_chars: config.telegram_agent_result_max_chars,
    telegram_agent_state_dir: config.telegram_agent_state_dir,
    acp_bridge_backend: config.acp_bridge_backend,
    acp_bridge_fallback_backend: config.acp_bridge_fallback_backend,
    acp_bridge_claude_model: config.acp_bridge_claude_model,
    acp_bridge_codex_command: config.acp_bridge_codex_command,
    acp_bridge_codex_model: config.acp_bridge_codex_model,
    telegram_remote_review_enabled: config.telegram_remote_review_enabled,
    telegram_bot_api_base_url: config.telegram_bot_api_base_url,
    telegram_bot_token: "",
    telegram_bot_chat_id: config.telegram_bot_chat_id,
  };
}

function sanitizeSettingsForm(form: SettingsForm): Record<string, string | number | boolean> {
  const payload = { ...form };
  for (const key of [...EMPTY_SECRET_KEYS, ...CREATIVE_SECRET_KEYS]) {
    if (!String(payload[key] ?? "").trim()) {
      delete payload[key];
    }
  }
  return payload;
}

export function useSettingsWorkspace() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const runtimeEnvironment = useQuery({ queryKey: ["config-environment"], queryFn: api.getRuntimeEnvironment });
  const serviceStatus = useQuery({ queryKey: ["config-service-status"], queryFn: api.getServiceStatus });
  const options = useQuery({ queryKey: ["config-options"], queryFn: api.getConfigOptions });
  const configProfiles = useQuery({ queryKey: ["config-profiles"], queryFn: api.getConfigProfiles });
  const [form, setForm] = useState<SettingsForm>({});
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const lastPersistedRef = useRef<string>("");
  const requestVersionRef = useRef(0);
  const preserveSavedStateRef = useRef(false);

  useEffect(() => {
    if (config.data) {
      const nextForm = buildSettingsForm(config.data);
      lastPersistedRef.current = JSON.stringify(sanitizeSettingsForm(nextForm));
      setForm(nextForm);
      setSaveState(preserveSavedStateRef.current ? "saved" : "idle");
      preserveSavedStateRef.current = false;
      setSaveError(null);
    }
  }, [config.data]);

  const save = useMutation({
    mutationFn: (payload: Record<string, string | number | boolean>) => api.patchConfig(payload),
  });

  const reset = useMutation({
    mutationFn: api.resetConfig,
    onSuccess: async () => {
      requestVersionRef.current += 1;
      setSaveState("idle");
      setSaveError(null);
      await queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  useEffect(() => {
    if (!config.data) return;
    const payload = sanitizeSettingsForm(form);
    const signature = JSON.stringify(payload);
    if (signature === lastPersistedRef.current) {
      return;
    }

    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const timer = window.setTimeout(() => {
      setSaveState("saving");
      setSaveError(null);
      save.mutate(payload, {
        onSuccess: (nextConfig) => {
          if (requestVersion !== requestVersionRef.current) return;
          const nextForm = buildSettingsForm(nextConfig);
          lastPersistedRef.current = JSON.stringify(sanitizeSettingsForm(nextForm));
          preserveSavedStateRef.current = true;
          queryClient.setQueryData(["config"], nextConfig);
          setSaveState("saved");
          setSaveError(null);
        },
        onError: (error) => {
          if (requestVersion !== requestVersionRef.current) return;
          setSaveState("error");
          setSaveError(error instanceof Error ? error.message : String(error));
        },
      });
    }, 600);

    return () => window.clearTimeout(timer);
  }, [config.data, form, queryClient, save]);

  return {
    config,
    runtimeEnvironment,
    serviceStatus,
    configProfiles,
    options,
    form,
    setForm,
    save,
    saveState,
    saveError,
    reset,
  };
}

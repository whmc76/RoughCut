import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { SettingsForm } from "./constants";

const EMPTY_SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "minimax_api_key", "minimax_coding_plan_api_key", "ollama_api_key", "telegram_bot_token"] as const;
const CREATIVE_SECRET_KEYS = ["avatar_api_key", "voice_clone_api_key"] as const;

function normalizeBundledForm(form: SettingsForm): SettingsForm {
  const nextForm = { ...form };
  nextForm.llm_routing_mode = String(nextForm.llm_routing_mode ?? "bundled").trim() || "bundled";
  nextForm.hybrid_analysis_provider = String(nextForm.hybrid_analysis_provider ?? "openai").trim() || "openai";
  nextForm.hybrid_analysis_model = String(nextForm.hybrid_analysis_model ?? "gpt-5.4-mini").trim() || "gpt-5.4-mini";
  nextForm.hybrid_analysis_search_mode = String(nextForm.hybrid_analysis_search_mode ?? "entity_gated").trim() || "entity_gated";
  nextForm.hybrid_copy_provider = String(nextForm.hybrid_copy_provider ?? "minimax").trim() || "minimax";
  nextForm.hybrid_copy_model = String(nextForm.hybrid_copy_model ?? "MiniMax-M2.7-highspeed").trim() || "MiniMax-M2.7-highspeed";
  nextForm.hybrid_copy_search_mode = String(nextForm.hybrid_copy_search_mode ?? "follow_provider").trim() || "follow_provider";
  nextForm.search_provider = "auto";
  nextForm.search_fallback_provider = String(nextForm.search_fallback_provider ?? "searxng").trim() || "searxng";
  nextForm.multimodal_fallback_provider = String(nextForm.multimodal_fallback_provider ?? "ollama").trim() || "ollama";
  nextForm.model_search_helper = String(nextForm.model_search_helper ?? "").trim();
  return nextForm;
}

function buildSettingsForm(config: NonNullable<ReturnType<typeof api.getConfig> extends Promise<infer T> ? T : never>): SettingsForm {
  return normalizeBundledForm({
    transcription_provider: config.transcription_provider,
    transcription_model: config.transcription_model,
    transcription_dialect: config.transcription_dialect,
    llm_mode: config.llm_mode,
    llm_routing_mode: config.llm_routing_mode ?? "bundled",
    reasoning_provider: config.reasoning_provider,
    reasoning_model: config.reasoning_model,
    local_reasoning_model: config.local_reasoning_model,
    local_vision_model: config.local_vision_model,
    hybrid_analysis_provider: config.hybrid_analysis_provider ?? "openai",
    hybrid_analysis_model: config.hybrid_analysis_model ?? "gpt-5.4-mini",
    hybrid_analysis_search_mode: config.hybrid_analysis_search_mode ?? "entity_gated",
    hybrid_copy_provider: config.hybrid_copy_provider ?? "minimax",
    hybrid_copy_model: config.hybrid_copy_model ?? "MiniMax-M2.7-highspeed",
    hybrid_copy_search_mode: config.hybrid_copy_search_mode ?? "follow_provider",
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
  });
}

function sanitizeSettingsForm(form: SettingsForm): Record<string, string | number | boolean> {
  const payload = { ...normalizeBundledForm(form) };
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
    mutationFn: async () => {
      await Promise.all([api.resetConfig(), api.resetPackagingConfig()]);
    },
    onSuccess: async () => {
      requestVersionRef.current += 1;
      setSaveState("idle");
      setSaveError(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["packaging"] }),
      ]);
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

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { SettingsForm } from "./constants";

const EMPTY_SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "minimax_api_key", "minimax_coding_plan_api_key", "ollama_api_key"] as const;
const CREATIVE_SECRET_KEYS = ["avatar_api_key", "voice_clone_api_key"] as const;

function buildSettingsForm(config: NonNullable<ReturnType<typeof api.getConfig> extends Promise<infer T> ? T : never>): SettingsForm {
  return {
    transcription_provider: config.transcription_provider,
    transcription_model: config.transcription_model,
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
    openai_base_url: config.openai_base_url,
    openai_auth_mode: config.openai_auth_mode,
    openai_api_key_helper: config.openai_api_key_helper,
    avatar_provider: config.avatar_provider,
    avatar_api_base_url: config.avatar_api_base_url,
    avatar_training_api_base_url: config.avatar_training_api_base_url,
    avatar_presenter_id: config.avatar_presenter_id,
    avatar_layout_template: config.avatar_layout_template,
    avatar_safe_margin: config.avatar_safe_margin,
    avatar_overlay_scale: config.avatar_overlay_scale,
    anthropic_base_url: config.anthropic_base_url,
    anthropic_auth_mode: config.anthropic_auth_mode,
    anthropic_api_key_helper: config.anthropic_api_key_helper,
    minimax_base_url: config.minimax_base_url,
    minimax_api_host: config.minimax_api_host,
    voice_provider: config.voice_provider,
    voice_clone_api_base_url: config.voice_clone_api_base_url,
    voice_clone_voice_id: config.voice_clone_voice_id,
    director_rewrite_strength: config.director_rewrite_strength,
    ollama_base_url: config.ollama_base_url,
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
    output_dir: config.output_dir,
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
  const options = useQuery({ queryKey: ["config-options"], queryFn: api.getConfigOptions });
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
    options,
    form,
    setForm,
    save,
    saveState,
    saveError,
    reset,
  };
}

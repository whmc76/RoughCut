import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { SettingsForm } from "./constants";

export function useSettingsWorkspace() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const options = useQuery({ queryKey: ["config-options"], queryFn: api.getConfigOptions });
  const [form, setForm] = useState<SettingsForm>({});

  useEffect(() => {
    if (config.data) {
      setForm({
        transcription_provider: config.data.transcription_provider,
        transcription_model: config.data.transcription_model,
        llm_mode: config.data.llm_mode,
        reasoning_provider: config.data.reasoning_provider,
        reasoning_model: config.data.reasoning_model,
        local_reasoning_model: config.data.local_reasoning_model,
        local_vision_model: config.data.local_vision_model,
        multimodal_fallback_provider: config.data.multimodal_fallback_provider,
        multimodal_fallback_model: config.data.multimodal_fallback_model,
        search_provider: config.data.search_provider,
        search_fallback_provider: config.data.search_fallback_provider,
        model_search_helper: config.data.model_search_helper,
        openai_base_url: config.data.openai_base_url,
        openai_auth_mode: config.data.openai_auth_mode,
        openai_api_key_helper: config.data.openai_api_key_helper,
        anthropic_base_url: config.data.anthropic_base_url,
        anthropic_auth_mode: config.data.anthropic_auth_mode,
        anthropic_api_key_helper: config.data.anthropic_api_key_helper,
        minimax_base_url: config.data.minimax_base_url,
        ollama_base_url: config.data.ollama_base_url,
        openai_api_key: "",
        anthropic_api_key: "",
        minimax_api_key: "",
        ollama_api_key: "",
        max_upload_size_mb: config.data.max_upload_size_mb,
        max_video_duration_sec: config.data.max_video_duration_sec,
        ffmpeg_timeout_sec: config.data.ffmpeg_timeout_sec,
        output_dir: config.data.output_dir,
      });
    }
  }, [config.data]);

  const save = useMutation({
    mutationFn: () => {
      const payload = { ...form };
      for (const key of ["openai_api_key", "anthropic_api_key", "minimax_api_key", "ollama_api_key"] as const) {
        if (!String(payload[key] ?? "").trim()) {
          delete payload[key];
        }
      }
      return api.patchConfig(payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  const reset = useMutation({
    mutationFn: api.resetConfig,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  return {
    config,
    options,
    form,
    setForm,
    save,
    reset,
  };
}

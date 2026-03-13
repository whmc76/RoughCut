import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { Config, ConfigOptions } from "../../types";
import { useSettingsWorkspace } from "./useSettingsWorkspace";

const mockApi = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getConfigOptions: vi.fn(),
  patchConfig: vi.fn(),
  resetConfig: vi.fn(),
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
  avatar_provider: "mock",
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
  voice_provider: "edge",
  voice_clone_api_base_url: "https://www.runninghub.cn",
  voice_clone_api_key_set: false,
  voice_clone_voice_id: "voice_demo",
  director_rewrite_strength: 0.55,
  ollama_base_url: "http://127.0.0.1:11434",
  openai_api_key_set: true,
  anthropic_api_key_set: false,
  minimax_api_key_set: false,
  ollama_api_key_set: false,
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
  enhancement_modes: [
    { value: "avatar_commentary", label: "数字人解说" },
    { value: "ai_director", label: "AI 导演" },
  ],
  avatar_providers: [
    { value: "mock", label: "mock" },
    { value: "heygem", label: "heygem" },
  ],
  voice_providers: [
    { value: "edge", label: "edge" },
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

describe("useSettingsWorkspace", () => {
  beforeEach(() => {
    mockApi.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mockApi.getConfigOptions.mockResolvedValue(SAMPLE_OPTIONS);
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
    await waitFor(() => expect(result.current.form.output_dir).toBe("data/output"));

    act(() => {
      result.current.setForm((prev) => ({
        ...prev,
        output_dir: "D:/RoughCut/output",
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
          output_dir: "D:/RoughCut/output",
        }),
      ),
    );
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("openai_api_key");
    expect(mockApi.patchConfig.mock.calls[0][0]).not.toHaveProperty("anthropic_api_key");
    await waitFor(() => expect(result.current.saveState).toBe("saved"));
  });
});

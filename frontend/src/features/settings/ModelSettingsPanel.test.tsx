import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "../../api";
import { createTestQueryClient } from "../../test/renderWithQueryClient";
import type { ConfigOptions, ProviderServiceStatus, RuntimeEnvironment } from "../../types";
import { ModelSettingsPanel } from "./ModelSettingsPanel";
import type { SettingsForm } from "./constants";

vi.mock("../../api", () => ({
  api: {
    getModelCatalog: vi.fn(),
  },
}));

const SAMPLE_OPTIONS: ConfigOptions = {
  job_languages: [{ value: "zh-CN", label: "简体中文" }],
  workflow_templates: [{ value: "", label: "自动匹配" }],
  workflow_modes: [{ value: "standard_edit", label: "标准成片" }],
  enhancement_modes: [{ value: "avatar_commentary", label: "数字人解说" }],
  transcription_dialects: [
    { value: "mandarin", label: "普通话" },
    { value: "beijing", label: "北京话" },
  ],
  avatar_providers: [{ value: "heygem", label: "heygem" }],
  voice_providers: [{ value: "indextts2", label: "indextts2" }],
  creative_mode_catalog: {
    workflow_modes: [],
    enhancement_modes: [],
  },
  transcription_models: {
    openai: ["gpt-4o-transcribe"],
    qwen_asr: ["qwen3-asr-1.7b"],
  },
  multimodal_fallback_providers: [
    { value: "ollama", label: "Ollama" },
    { value: "openai", label: "OpenAI" },
  ],
  search_providers: [
    { value: "auto", label: "自动选择" },
    { value: "model", label: "模型代理" },
  ],
  search_fallback_providers: [
    { value: "searxng", label: "SearXNG" },
    { value: "model", label: "模型代理" },
  ],
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

const SAMPLE_SERVICE_STATUS: ProviderServiceStatus = {
  checked_at: "2026-03-31T12:00:00Z",
  services: {
    ollama: { name: "ollama", base_url: "http://127.0.0.1:11434", status: "ok", error: null },
    qwen_asr: { name: "qwen_asr", base_url: "http://127.0.0.1:18096", status: "ok", error: null },
  },
};

function renderPanel(form: SettingsForm) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ModelSettingsPanel
        form={form}
        options={SAMPLE_OPTIONS}
        runtimeEnvironment={SAMPLE_RUNTIME_ENVIRONMENT}
        serviceStatus={SAMPLE_SERVICE_STATUS}
        onChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ModelSettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getModelCatalog).mockImplementation(async ({ provider, kind, refresh }) => {
      if (provider === "qwen_asr") {
        return {
          provider,
          kind,
          models: ["qwen3-asr-1.7b"],
          source: refresh ? "live" : "cache",
          refreshed_at: "2026-03-31T12:00:00Z",
          status: "ok",
          error: null,
        };
      }
      if (provider === "minimax") {
        return {
          provider,
          kind,
          models: ["MiniMax-M2.7-highspeed", "MiniMax-M2.5"],
          source: refresh ? "live" : "cache",
          refreshed_at: "2026-03-31T12:00:00Z",
          status: "ok",
          error: null,
        };
      }
      return {
        provider,
        kind,
        models: ["qwen3:8b", "qwen2.5vl:7b"],
        source: refresh ? "live" : "cache",
        refreshed_at: "2026-03-31T12:00:00Z",
        status: "ok",
        error: null,
      };
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows qwen asr endpoint and model dropdown when qwen provider is active", async () => {
    const form: SettingsForm = {
      transcription_provider: "qwen_asr",
      transcription_model: "qwen3-asr-1.7b",
      transcription_dialect: "beijing",
      qwen_asr_api_base_url: "http://127.0.0.1:18096",
      llm_mode: "performance",
      reasoning_provider: "minimax",
      reasoning_model: "MiniMax-M2.7-highspeed",
      search_provider: "auto",
      search_fallback_provider: "searxng",
    };

    renderPanel(form);

    expect(screen.getByText("转写")).toBeInTheDocument();
    expect(screen.getByText("推理")).toBeInTheDocument();
    expect(screen.getByText("搜索")).toBeInTheDocument();
    expect(screen.getAllByText("Qwen ASR (local)").length).toBeGreaterThan(0);
    expect(screen.getByText("转写、推理与搜索细节")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/服务地址：http:\/\/127.0.0.1:18096/)).toBeInTheDocument());
    expect(screen.getByLabelText("转写模型")).toHaveValue("qwen3-asr-1.7b");
    expect(screen.getByRole("button", { name: "刷新转写模型" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新转写模型" }));
    await waitFor(() =>
      expect(api.getModelCatalog).toHaveBeenCalledWith({ provider: "qwen_asr", kind: "transcription", refresh: true }),
    );
  });

  it("switches local mode to ollama model dropdowns instead of text inputs", async () => {
    const form: SettingsForm = {
      transcription_provider: "openai",
      transcription_model: "gpt-4o-transcribe",
      transcription_dialect: "mandarin",
      llm_mode: "local",
      local_reasoning_model: "qwen3.5:9b",
      local_vision_model: "qwen2.5vl:7b",
      search_provider: "auto",
      search_fallback_provider: "searxng",
    };

    renderPanel(form);

    expect(screen.getByText("本地模式")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("本地推理模型")).toHaveValue("qwen3.5:9b"));
    expect(screen.getByLabelText("本地视觉模型")).toHaveValue("qwen2.5vl:7b");
    expect(screen.getByText(/Ollama 服务：http:\/\/127.0.0.1:11434/)).toBeInTheDocument();
    expect(screen.queryByLabelText("推理 Provider")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("视觉回退 Provider")).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";

import type { ConfigOptions } from "../../types";
import { ModelSettingsPanel } from "./ModelSettingsPanel";
import type { SettingsForm } from "./constants";

const SAMPLE_OPTIONS: ConfigOptions = {
  job_languages: [{ value: "zh-CN", label: "简体中文" }],
  channel_profiles: [{ value: "", label: "自动匹配" }],
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

describe("ModelSettingsPanel", () => {
  it("shows qwen asr endpoint when qwen provider is active", () => {
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

    render(<ModelSettingsPanel form={form} options={SAMPLE_OPTIONS} onChange={vi.fn()} />);

    expect(screen.getByText("转写")).toBeInTheDocument();
    expect(screen.getByText("推理")).toBeInTheDocument();
    expect(screen.getByText("搜索")).toBeInTheDocument();
    expect(screen.getByText("转写、推理与搜索细节")).toBeInTheDocument();
    expect(screen.getByLabelText("Qwen ASR 服务地址")).toHaveValue("http://127.0.0.1:18096");
    expect(screen.getByLabelText("推理 Provider")).toBeInTheDocument();
  });

  it("switches to local-only fields in local llm mode", () => {
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

    render(<ModelSettingsPanel form={form} options={SAMPLE_OPTIONS} onChange={vi.fn()} />);

    expect(screen.getByText("本地模式")).toBeInTheDocument();
    expect(screen.getByLabelText("本地推理模型")).toHaveValue("qwen3.5:9b");
    expect(screen.queryByLabelText("推理 Provider")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("视觉回退 Provider")).not.toBeInTheDocument();
  });
});

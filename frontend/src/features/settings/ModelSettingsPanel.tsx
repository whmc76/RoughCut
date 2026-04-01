import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { ConfigOptions, ProviderServiceStatus, RuntimeEnvironment } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { LLM_MODE_OPTIONS, REASONING_PROVIDER_OPTIONS } from "./constants";
import {
  getActiveReasoningModel,
  getActiveReasoningProvider,
  getProviderLabel,
  getProviderStatusLabel,
  getSearchSummary,
  getTranscriptionProviderLabel,
} from "./helpers";

type ModelSettingsPanelProps = {
  form: SettingsForm;
  options?: ConfigOptions;
  runtimeEnvironment?: RuntimeEnvironment;
  serviceStatus?: ProviderServiceStatus;
  onChange: (key: string, value: string | number | boolean) => void;
};

function buildModelOptions(models: string[], currentValue: string) {
  const baseOptions = models.map((model) => ({ value: model, label: model }));
  if (currentValue && !models.includes(currentValue)) {
    return [{ value: currentValue, label: `${currentValue}（已保存旧模型）` }, ...baseOptions];
  }
  if (!baseOptions.length) {
    return [{ value: currentValue || "", label: currentValue ? `${currentValue}（已保存旧模型）` : "暂无可用模型" }];
  }
  return baseOptions;
}

export function ModelSettingsPanel({ form, options, runtimeEnvironment, serviceStatus, onChange }: ModelSettingsPanelProps) {
  const queryClient = useQueryClient();
  const llmMode = String(form.llm_mode ?? "performance");
  const transcriptionProvider = String(form.transcription_provider ?? "");
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const activeReasoningModel = getActiveReasoningModel(form);
  const searchProvider = String(form.search_provider ?? "auto");
  const searchFallbackProvider = String(form.search_fallback_provider ?? "searxng");
  const transcriptionDialects = options?.transcription_dialects ?? [{ value: "mandarin", label: "普通话" }];
  const multimodalFallbackProviders = options?.multimodal_fallback_providers ?? [{ value: "ollama", label: "Ollama" }];
  const searchProviders = options?.search_providers ?? [{ value: "auto", label: "自动选择" }];
  const searchFallbackProviders = options?.search_fallback_providers ?? [{ value: "searxng", label: "SearXNG" }];
  const transcriptionProviderOptions = Object.keys(options?.transcription_models ?? {}).map((provider) => ({
    value: provider,
    label: getTranscriptionProviderLabel(provider),
  }));
  const modelDetailsOpen =
    transcriptionProvider === "qwen3_asr" ||
    llmMode === "local" ||
    searchProvider !== "auto" ||
    searchFallbackProvider === "model" ||
    Boolean(String(form.model_search_helper ?? "").trim());
  const transcriptionCatalog = useQuery({
    queryKey: ["config-model-catalog", "transcription", transcriptionProvider],
    queryFn: () => api.getModelCatalog({ provider: transcriptionProvider, kind: "transcription" }),
    enabled: Boolean(transcriptionProvider),
  });
  const reasoningCatalogProvider = llmMode === "local" ? "ollama" : activeReasoningProvider;
  const reasoningCatalog = useQuery({
    queryKey: ["config-model-catalog", "reasoning", reasoningCatalogProvider],
    queryFn: () => api.getModelCatalog({ provider: reasoningCatalogProvider, kind: "reasoning" }),
    enabled: Boolean(reasoningCatalogProvider),
  });
  const fallbackProvider = String(form.multimodal_fallback_provider ?? "");
  const fallbackCatalog = useQuery({
    queryKey: ["config-model-catalog", "vision_fallback", fallbackProvider],
    queryFn: () => api.getModelCatalog({ provider: fallbackProvider, kind: "vision_fallback" }),
    enabled: llmMode === "performance" && Boolean(fallbackProvider),
  });
  const transcriptionModels = transcriptionCatalog.data?.models ?? options?.transcription_models?.[transcriptionProvider] ?? [];
  const reasoningModels = reasoningCatalog.data?.models ?? [];
  const fallbackModels = fallbackCatalog.data?.models ?? [];
  const qwenStatus = serviceStatus?.services.qwen3_asr;
  const ollamaStatus = serviceStatus?.services.ollama;
  const qwenBaseUrl = qwenStatus?.base_url || String(form.qwen_asr_api_base_url ?? "");
  const qwenStatusLabel = qwenStatus ? getProviderStatusLabel(qwenStatus.status) : "";
  const ollamaBaseUrl = ollamaStatus?.base_url || String(runtimeEnvironment?.ollama_base_url ?? "");
  const ollamaStatusLabel = ollamaStatus ? getProviderStatusLabel(ollamaStatus.status) : "";
  const refreshCatalog = async (provider: string, kind: string) => {
    const next = await api.getModelCatalog({ provider, kind, refresh: true });
    queryClient.setQueryData(["config-model-catalog", kind, provider], next);
  };

  return (
    <section className="panel">
      <PanelHeader title="转写与推理" description="基础链路只保留当前会参与运行的字段。" />
      <div className="form-stack">
        <div className="settings-overview-grid">
          <article className="settings-overview-card">
            <span className="settings-overview-label">转写</span>
            <strong>{getTranscriptionProviderLabel(transcriptionProvider)}</strong>
            <div className="muted">
              {String(form.transcription_model ?? "未设置")}
              {form.transcription_dialect ? ` · ${String(form.transcription_dialect)}` : ""}
            </div>
          </article>
          <article className="settings-overview-card">
            <span className="settings-overview-label">推理</span>
            <strong>{llmMode === "local" ? "本地模式" : "云端模式"}</strong>
            <div className="muted">
              {getProviderLabel(activeReasoningProvider)} · {activeReasoningModel || "未设置模型"}
            </div>
          </article>
          <article className="settings-overview-card">
            <span className="settings-overview-label">搜索</span>
            <strong>{getSearchSummary(form)}</strong>
            <div className="muted">
              {String(form.model_search_helper ?? "").trim() ? `辅助模型 ${String(form.model_search_helper)}` : "仅在需要时启用模型代理搜索"}
            </div>
          </article>
        </div>
        <SelectField
          label="LLM 模式"
          value={String(form.llm_mode ?? "")}
          onChange={(event) => onChange("llm_mode", event.target.value)}
          options={LLM_MODE_OPTIONS.map((mode) => ({ value: mode, label: mode }))}
        />
        <details className="settings-disclosure" open={modelDetailsOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>转写、推理与搜索细节</strong>
              <div className="muted">
                {getTranscriptionProviderLabel(transcriptionProvider)} · {getProviderLabel(activeReasoningProvider)} · {getSearchSummary(form)}
              </div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <div className="form-stack">
              <section className="settings-subsection">
                <div className="settings-subsection-head">
                  <strong>转写链路</strong>
                  <span className="muted">{getTranscriptionProviderLabel(transcriptionProvider)}</span>
                </div>
                <div className="form-stack">
                  <SelectField
                    label="转写 Provider"
                    value={String(form.transcription_provider ?? "")}
                    onChange={(event) => onChange("transcription_provider", event.target.value)}
                    options={transcriptionProviderOptions}
                  />
                  <SelectField
                    label="转写模型"
                    value={String(form.transcription_model ?? "")}
                    onChange={(event) => onChange("transcription_model", event.target.value)}
                    options={buildModelOptions(transcriptionModels, String(form.transcription_model ?? ""))}
                  />
                  <button
                    type="button"
                    className="button ghost button-sm"
                    onClick={() => void refreshCatalog(transcriptionProvider, "transcription")}
                  >
                    刷新转写模型
                  </button>
                  <SelectField
                    label="转写方言"
                    value={String(form.transcription_dialect ?? "mandarin")}
                    onChange={(event) => onChange("transcription_dialect", event.target.value)}
                    options={transcriptionDialects}
                  />
                  {transcriptionProvider === "qwen3_asr" && (
                    <div className="muted">
                      服务地址：{qwenBaseUrl}
                      {qwenStatusLabel ? ` · ${qwenStatusLabel}` : ""}
                      {qwenStatus?.error ? ` · ${qwenStatus.error}` : ""}
                    </div>
                  )}
                </div>
              </section>
              <section className="settings-subsection">
                <div className="settings-subsection-head">
                  <strong>推理链路</strong>
                  <span className="muted">{llmMode === "local" ? "本地模型" : getProviderLabel(activeReasoningProvider)}</span>
                </div>
                <div className="form-stack">
                  {llmMode === "performance" ? (
                    <>
                      <SelectField
                        label="推理 Provider"
                        value={String(form.reasoning_provider ?? "")}
                        onChange={(event) => onChange("reasoning_provider", event.target.value)}
                        options={REASONING_PROVIDER_OPTIONS.map((provider) => ({ value: provider, label: getProviderLabel(provider) }))}
                      />
                      <SelectField
                        label="推理模型"
                        value={String(form.reasoning_model ?? "")}
                        onChange={(event) => onChange("reasoning_model", event.target.value)}
                        options={buildModelOptions(reasoningModels, String(form.reasoning_model ?? ""))}
                      />
                      <button
                        type="button"
                        className="button ghost button-sm"
                        onClick={() => void refreshCatalog(reasoningCatalogProvider, "reasoning")}
                      >
                        刷新推理模型
                      </button>
                      <SelectField
                        label="视觉回退 Provider"
                        value={String(form.multimodal_fallback_provider ?? "")}
                        onChange={(event) => onChange("multimodal_fallback_provider", event.target.value)}
                        options={multimodalFallbackProviders}
                      />
                      <SelectField
                        label="视觉回退模型"
                        value={String(form.multimodal_fallback_model ?? "")}
                        onChange={(event) => onChange("multimodal_fallback_model", event.target.value)}
                        options={buildModelOptions(fallbackModels, String(form.multimodal_fallback_model ?? ""))}
                      />
                      <button
                        type="button"
                        className="button ghost button-sm"
                        onClick={() => void refreshCatalog(fallbackProvider, "vision_fallback")}
                      >
                        刷新视觉回退模型
                      </button>
                    </>
                  ) : (
                    <>
                      <SelectField
                        label="本地推理模型"
                        value={String(form.local_reasoning_model ?? "")}
                        onChange={(event) => onChange("local_reasoning_model", event.target.value)}
                        options={buildModelOptions(reasoningModels, String(form.local_reasoning_model ?? ""))}
                      />
                      <SelectField
                        label="本地视觉模型"
                        value={String(form.local_vision_model ?? "")}
                        onChange={(event) => onChange("local_vision_model", event.target.value)}
                        options={buildModelOptions(reasoningModels, String(form.local_vision_model ?? ""))}
                      />
                      <button
                        type="button"
                        className="button ghost button-sm"
                        onClick={() => void refreshCatalog("ollama", "reasoning")}
                      >
                        检测 Ollama / 刷新模型
                      </button>
                      <div className="muted">
                        Ollama 服务：{ollamaBaseUrl}
                        {ollamaStatusLabel ? ` · ${ollamaStatusLabel}` : ""}
                        {ollamaStatus?.error ? ` · ${ollamaStatus.error}` : ""}
                      </div>
                      <div className="muted">本地模式下推理固定走 {getProviderLabel(activeReasoningProvider)}，不会使用云端回退 Provider。</div>
                    </>
                  )}
                </div>
              </section>
              <section className="settings-subsection">
                <div className="settings-subsection-head">
                  <strong>搜索链路</strong>
                  <span className="muted">{getSearchSummary(form)}</span>
                </div>
                <div className="form-stack">
                  <SelectField
                    label="搜索 Provider"
                    value={searchProvider}
                    onChange={(event) => onChange("search_provider", event.target.value)}
                    options={searchProviders}
                  />
                  {searchProvider === "auto" && (
                    <SelectField
                      label="搜索回退 Provider"
                      value={searchFallbackProvider}
                      onChange={(event) => onChange("search_fallback_provider", event.target.value)}
                      options={searchFallbackProviders}
                    />
                  )}
                  {(searchProvider === "model" || (searchProvider === "auto" && searchFallbackProvider === "model")) && (
                    <TextField
                      label="搜索辅助模型"
                      value={String(form.model_search_helper ?? "")}
                      onChange={(event) => onChange("model_search_helper", event.target.value)}
                    />
                  )}
                </div>
              </section>
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}

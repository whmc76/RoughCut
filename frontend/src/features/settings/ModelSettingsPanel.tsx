import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type {
  Config,
  ConfigOptions,
  ProviderCheckResult,
  ProviderServiceStatus,
  ProviderServiceStatusEntry,
  RuntimeEnvironment,
} from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { REASONING_PROVIDER_OPTIONS } from "./constants";
import {
  getActiveReasoningModel,
  getActiveReasoningProvider,
  getCredentialSourceLabel,
  getHybridSearchModeLabel,
  getLlmRoutingMode,
  getProviderLabel,
  formatProviderDetail,
  getProviderStatusLabel,
  getRoutingSummary,
  getSearchSummary,
  getTranscriptionProviderLabel,
  isLocalTranscriptionProvider,
} from "./helpers";

type ModelSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  options?: ConfigOptions;
  runtimeEnvironment?: RuntimeEnvironment;
  serviceStatus?: ProviderServiceStatus;
  onChange: (key: string, value: string | number | boolean) => void;
};

type ProviderCardDescriptor = {
  key: string;
  title: string;
  subtitle: string;
  tone: "cloud" | "local" | "route";
  status: string;
  detail: string;
  baseUrl: string;
  checkedAt?: string;
  credentialSource?: string;
  refreshActions: Array<{ provider: string; kind: string; label: string }>;
  secretField?:
    | {
        key: "openai_api_key" | "anthropic_api_key" | "minimax_api_key" | "ollama_api_key";
        label: string;
        placeholder: string;
      }
    | undefined;
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

function readFormString(form: SettingsForm, key: string, fallback = "") {
  return String(form[key] ?? fallback).trim();
}

function getBaseUrl(provider: string, runtimeEnvironment: RuntimeEnvironment | undefined, form: SettingsForm): string {
  switch (provider) {
    case "openai":
      return String(runtimeEnvironment?.openai_base_url ?? "");
    case "anthropic":
      return String(runtimeEnvironment?.anthropic_base_url ?? "");
    case "minimax":
      return String(runtimeEnvironment?.minimax_base_url ?? "");
    case "ollama":
      return String(runtimeEnvironment?.ollama_base_url ?? "");
    case "local_http_asr":
      return readFormString(form, "local_asr_api_base_url");
    default:
      return "";
  }
}

function getProviderServiceEntry(provider: string, serviceStatus: ProviderServiceStatus | undefined): ProviderServiceStatusEntry | undefined {
  return serviceStatus?.services[provider];
}

function getProviderCredentialSource(provider: string, config: Config | undefined, runtimeEnvironment: RuntimeEnvironment | undefined) {
  if (provider === "openai") {
    return getCredentialSourceLabel(config, {
      mode: String(runtimeEnvironment?.openai_auth_mode ?? "api_key"),
      helperCommand: String(runtimeEnvironment?.openai_api_key_helper ?? ""),
      keySet: Boolean(config?.openai_api_key_set),
      overrideKey: "openai_api_key",
    });
  }
  if (provider === "anthropic") {
    return getCredentialSourceLabel(config, {
      mode: String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key"),
      helperCommand: String(runtimeEnvironment?.anthropic_api_key_helper ?? ""),
      keySet: Boolean(config?.anthropic_api_key_set),
      overrideKey: "anthropic_api_key",
    });
  }
  if (provider === "minimax") {
    return getCredentialSourceLabel(config, {
      keySet: Boolean(config?.minimax_api_key_set),
      overrideKey: "minimax_api_key",
    });
  }
  if (provider === "ollama" || provider === "local_http_asr") {
    return "本地服务";
  }
  if (provider === "faster_whisper" || provider === "funasr") {
    return "本地内嵌";
  }
  if (provider === "searxng") {
    return "搜索回退";
  }
  return "";
}

function getProviderSecretField(provider: string, config: Config | undefined): ProviderCardDescriptor["secretField"] {
  if (provider === "openai") {
    return {
      key: "openai_api_key",
      label: "OpenAI API Key",
      placeholder: config?.openai_api_key_set ? "已设置，留空则不更新" : "留空则不更新",
    };
  }
  if (provider === "anthropic") {
    return {
      key: "anthropic_api_key",
      label: "Anthropic API Key",
      placeholder: config?.anthropic_api_key_set ? "已设置，留空则不更新" : "留空则不更新",
    };
  }
  if (provider === "minimax") {
    return {
      key: "minimax_api_key",
      label: "MiniMax API Key",
      placeholder: config?.minimax_api_key_set ? "已设置，留空则不更新" : "留空则不更新",
    };
  }
  if (provider === "ollama") {
    return {
      key: "ollama_api_key",
      label: "Ollama API Key",
      placeholder: config?.ollama_api_key_set ? "已设置，留空则不更新" : "通常可留空",
    };
  }
  return undefined;
}

function getProviderBaseDetail(provider: string, runtimeEnvironment: RuntimeEnvironment | undefined, form: SettingsForm) {
  const baseUrl = getBaseUrl(provider, runtimeEnvironment, form);
  if (provider === "faster_whisper" || provider === "funasr") {
    return "本地运行，不依赖独立 HTTP 服务。";
  }
  if (provider === "searxng") {
    return "当前作为搜索回退使用。";
  }
  if (provider === "ollama" || provider === "local_http_asr") {
    return baseUrl ? "本地服务已接入，可直接检测连通性。" : "本地服务地址未配置。";
  }
  return baseUrl ? "云端 Provider 已配置，建议检测凭据与模型列表。" : "当前未配置服务地址。";
}

function getProviderTone(provider: string): ProviderCardDescriptor["tone"] {
  if (provider === "ollama" || provider === "local_http_asr" || provider === "faster_whisper" || provider === "funasr") {
    return "local";
  }
  if (provider === "searxng" || provider === "search-route") {
    return "route";
  }
  return "cloud";
}

function formatCheckTime(value: string | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function getProviderSummary(
  provider: string,
  serviceEntry: ProviderServiceStatusEntry | undefined,
  lastCheck: ProviderCheckResult | undefined,
  runtimeEnvironment: RuntimeEnvironment | undefined,
  form: SettingsForm,
) {
  if (lastCheck) {
    const detail = lastCheck.models.length ? `${lastCheck.detail || "检测完成"} · ${lastCheck.models.length} 个模型` : lastCheck.detail || "检测完成";
    return {
      status: getProviderStatusLabel(lastCheck.status),
      detail,
      baseUrl: lastCheck.base_url,
      checkedAt: lastCheck.checked_at,
    };
  }
  if (serviceEntry) {
    return {
      status: getProviderStatusLabel(serviceEntry.status),
      detail: serviceEntry.error ? serviceEntry.error : getProviderBaseDetail(provider, runtimeEnvironment, form),
      baseUrl: serviceEntry.base_url,
    };
  }
  return {
    status: isLocalTranscriptionProvider(provider) ? "本地链路" : "待检测",
    detail: getProviderBaseDetail(provider, runtimeEnvironment, form),
    baseUrl: getBaseUrl(provider, runtimeEnvironment, form),
  };
}

export function ModelSettingsPanel({ form, config, options, runtimeEnvironment, serviceStatus, onChange }: ModelSettingsPanelProps) {
  const queryClient = useQueryClient();
  const [lastChecks, setLastChecks] = useState<Record<string, ProviderCheckResult>>({});
  const llmMode = readFormString(form, "llm_mode", "performance");
  const llmRoutingMode = getLlmRoutingMode(form);
  const transcriptionProvider = readFormString(form, "transcription_provider");
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const activeReasoningModel = getActiveReasoningModel(form);
  const llmBackupEnabled = Boolean(form.llm_backup_enabled ?? true);
  const backupReasoningProvider = readFormString(form, "backup_reasoning_provider", "openai");
  const backupSearchProvider = readFormString(form, "backup_search_provider", "auto");
  const backupSearchFallbackProvider = readFormString(form, "backup_search_fallback_provider", "openai");
  const hybridAnalysisProvider = readFormString(form, "hybrid_analysis_provider", "openai");
  const hybridCopyProvider = readFormString(form, "hybrid_copy_provider", "openai");
  const hybridAnalysisSearchMode = readFormString(form, "hybrid_analysis_search_mode", "entity_gated");
  const hybridCopySearchMode = readFormString(form, "hybrid_copy_search_mode", "follow_provider");
  const searchFallbackProvider = readFormString(form, "search_fallback_provider", "openai");
  const transcriptionDialects = options?.transcription_dialects ?? [{ value: "mandarin", label: "普通话" }];
  const multimodalFallbackProviders = options?.multimodal_fallback_providers ?? [{ value: "ollama", label: "Ollama" }];
  const searchProviders = options?.search_providers ?? [{ value: "auto", label: "自动选择" }];
  const searchFallbackProviders = options?.search_fallback_providers ?? [{ value: "searxng", label: "SearXNG" }];
  const transcriptionProviderOptions = Object.keys(options?.transcription_models ?? {}).map((provider) => ({
    value: provider,
    label: getTranscriptionProviderLabel(provider),
  }));

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
  const fallbackProvider = readFormString(form, "multimodal_fallback_provider");
  const fallbackCatalog = useQuery({
    queryKey: ["config-model-catalog", "vision_fallback", fallbackProvider],
    queryFn: () => api.getModelCatalog({ provider: fallbackProvider, kind: "vision_fallback" }),
    enabled: llmMode === "performance" && Boolean(fallbackProvider),
  });
  const hybridAnalysisCatalog = useQuery({
    queryKey: ["config-model-catalog", "hybrid_analysis", hybridAnalysisProvider],
    queryFn: () => api.getModelCatalog({ provider: hybridAnalysisProvider, kind: "reasoning" }),
    enabled: llmMode === "performance" && Boolean(hybridAnalysisProvider),
  });
  const hybridCopyCatalog = useQuery({
    queryKey: ["config-model-catalog", "hybrid_copy", hybridCopyProvider],
    queryFn: () => api.getModelCatalog({ provider: hybridCopyProvider, kind: "reasoning" }),
    enabled: llmMode === "performance" && Boolean(hybridCopyProvider),
  });
  const backupReasoningCatalog = useQuery({
    queryKey: ["config-model-catalog", "backup_reasoning", backupReasoningProvider],
    queryFn: () => api.getModelCatalog({ provider: backupReasoningProvider, kind: "reasoning" }),
    enabled: llmMode === "performance" && llmBackupEnabled && Boolean(backupReasoningProvider),
  });
  const backupVisionCatalog = useQuery({
    queryKey: ["config-model-catalog", "backup_vision", backupReasoningProvider],
    queryFn: () => api.getModelCatalog({ provider: backupReasoningProvider, kind: "vision_fallback" }),
    enabled: llmMode === "performance" && llmBackupEnabled && Boolean(backupReasoningProvider),
  });
  const transcriptionModels = transcriptionCatalog.data?.models ?? options?.transcription_models?.[transcriptionProvider] ?? [];
  const reasoningModels = reasoningCatalog.data?.models ?? [];
  const fallbackModels = fallbackCatalog.data?.models ?? [];
  const hybridAnalysisModels = hybridAnalysisCatalog.data?.models ?? [];
  const hybridCopyModels = hybridCopyCatalog.data?.models ?? [];
  const backupReasoningModels = backupReasoningCatalog.data?.models ?? [];
  const backupVisionModels = backupVisionCatalog.data?.models ?? [];

  const refreshCatalog = async (provider: string, kind: string) => {
    const next = await api.getModelCatalog({ provider, kind, refresh: true });
    queryClient.setQueryData(["config-model-catalog", kind, provider], next);
  };

  const providerCheck = useMutation({
    mutationFn: (provider: string) => api.checkProvider(provider),
    onSuccess: (result) => {
      setLastChecks((prev) => ({ ...prev, [result.provider]: result }));
      void queryClient.invalidateQueries({ queryKey: ["config-service-status"] });
    },
  });

  const providerCards = useMemo(() => {
    const orderedProviders: string[] = [];
    const pushUnique = (value: string) => {
      if (!value || orderedProviders.includes(value)) return;
      orderedProviders.push(value);
    };

    pushUnique(transcriptionProvider);
    pushUnique(activeReasoningProvider);
    pushUnique(searchFallbackProvider);
    if (llmBackupEnabled) {
      pushUnique(backupReasoningProvider);
      pushUnique(backupSearchFallbackProvider);
    }
    if (llmMode === "performance" && llmRoutingMode === "hybrid_performance") {
      pushUnique(hybridAnalysisProvider);
      pushUnique(hybridCopyProvider);
    }

    const cards: ProviderCardDescriptor[] = orderedProviders.map((provider) => {
      const serviceEntry = getProviderServiceEntry(provider, serviceStatus);
      const summary = getProviderSummary(provider, serviceEntry, lastChecks[provider], runtimeEnvironment, form);
      const refreshActions: ProviderCardDescriptor["refreshActions"] = [];

      if (provider === transcriptionProvider) {
        refreshActions.push({ provider, kind: "transcription", label: "刷新转写模型" });
      }
      if (provider === reasoningCatalogProvider) {
        refreshActions.push({ provider, kind: "reasoning", label: llmMode === "local" ? "检测 Ollama / 刷新模型" : "刷新推理模型" });
      }

      return {
        key: provider,
        title: provider === transcriptionProvider ? getTranscriptionProviderLabel(provider) : getProviderLabel(provider),
        subtitle:
          provider === transcriptionProvider
            ? `当前转写 Provider`
            : provider === activeReasoningProvider
              ? llmMode === "local"
                ? `当前本地推理 Provider`
                : `当前推理 Provider`
              : provider === searchFallbackProvider
                ? "搜索回退链路"
                : "当前活跃 Provider",
        tone: getProviderTone(provider),
        status: summary.status,
        detail: summary.detail,
        baseUrl: summary.baseUrl,
        checkedAt: summary.checkedAt,
        credentialSource: getProviderCredentialSource(provider, config, runtimeEnvironment),
        refreshActions,
        secretField: getProviderSecretField(provider, config),
      };
    });

    cards.push({
      key: "search-route",
      title: "搜索路由",
      subtitle: "当前搜索策略",
      tone: "route",
      status: "自动跟随",
      detail: getSearchSummary(form),
      baseUrl: "",
      credentialSource: "按推理 Provider 自动路由",
      refreshActions: [],
    });

    return cards;
  }, [
    activeReasoningProvider,
    backupReasoningProvider,
    backupSearchFallbackProvider,
    config,
    form,
    hybridAnalysisProvider,
    hybridCopyProvider,
    lastChecks,
    llmBackupEnabled,
    llmMode,
    llmRoutingMode,
    reasoningCatalogProvider,
    runtimeEnvironment,
    searchFallbackProvider,
    serviceStatus,
    transcriptionProvider,
  ]);

  return (
    <section className="panel settings-core-panel">
      <PanelHeader title="核心链路配置" description="把配置、Provider 卡、检测动作、混合路由和模型刷新放到同一块里。" />
      <div className="settings-provider-deck-head">
        <div>
          <strong>活跃 Provider</strong>
          <div className="muted">
            当前链路：转写 {getTranscriptionProviderLabel(transcriptionProvider)} · {getRoutingSummary(form)} · 搜索 {getSearchSummary(form)}
          </div>
        </div>
      </div>
      <div className="settings-provider-deck">
        {providerCards.map((card) => {
          const isCheckable = ["openai", "anthropic", "minimax", "ollama", "local_http_asr"].includes(card.key);
          const checkPending = providerCheck.isPending && providerCheck.variables === card.key;
          const secretField = card.secretField;
          return (
            <article key={card.key} className={`settings-provider-card tone-${card.tone} ${isCheckable ? "actionable" : "informational"}`}>
              <div className="settings-provider-card-head">
                <div>
                  <span className="settings-overview-label">{card.subtitle}</span>
                  <strong>{card.title}</strong>
                </div>
                <span className={`status-pill ${card.status.includes("正常") || card.status.includes("自动") ? "done" : card.status.includes("不可达") || card.status.includes("失败") ? "failed" : "processing"}`}>
                  {card.status}
                </span>
              </div>
              <div className="settings-provider-card-copy">
                <div className="settings-provider-summary">{formatProviderDetail(card.detail)}</div>
                <div className="settings-provider-meta">
                  {card.credentialSource ? (
                    <div className="settings-provider-meta-row">
                      <span>凭据来源</span>
                      <strong>{card.credentialSource}</strong>
                    </div>
                  ) : null}
                  {card.baseUrl ? (
                    <div className="settings-provider-meta-row">
                      <span>服务地址</span>
                      <strong>{card.baseUrl}</strong>
                    </div>
                  ) : null}
                  {card.checkedAt ? (
                    <div className="settings-provider-meta-row">
                      <span>最近检测</span>
                      <strong>{formatCheckTime(card.checkedAt)}</strong>
                    </div>
                  ) : null}
                </div>
              </div>
              {secretField ? (
                <TextField
                  label={secretField.label}
                  type="password"
                  value={String(form[secretField.key] ?? "")}
                  onChange={(event) => onChange(secretField.key, event.target.value)}
                  placeholder={secretField.placeholder}
                />
              ) : null}
              <div className="settings-provider-actions">
                {isCheckable ? (
                  <button
                    type="button"
                    className="button button-sm"
                    onClick={() => providerCheck.mutate(card.key)}
                    disabled={checkPending}
                  >
                    {checkPending ? `检测 ${card.title} 中` : `检测 ${card.title}`}
                  </button>
                ) : null}
                {card.refreshActions.map((action) => (
                  <button
                    key={`${action.provider}-${action.kind}`}
                    type="button"
                    className="button ghost button-sm"
                    onClick={() => void refreshCatalog(action.provider, action.kind)}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </article>
          );
        })}
      </div>

      <div className="settings-chain-grid">
        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">混合模式</span>
              <strong>任务路由</strong>
            </div>
            <div className="muted">
              {llmMode === "local"
                ? "本地模式下固定 bundled"
                : llmRoutingMode === "hybrid_performance"
                  ? `摘要/字幕 ${getProviderLabel(hybridAnalysisProvider)} · 文案 ${getProviderLabel(hybridCopyProvider)}`
                  : "所有能力跟随主 Provider"}
            </div>
          </div>
          <div className="settings-chain-card-body form-grid three-up">
            <SelectField
              label="路由模式"
              value={llmRoutingMode}
              onChange={(event) => onChange("llm_routing_mode", event.target.value)}
              options={[
                { value: "bundled", label: "Bundled" },
                { value: "hybrid_performance", label: "Hybrid Performance" },
              ]}
            />
            {llmMode === "local" ? (
              <div className="settings-chain-note muted">本地模式下不启用高性能混合路由，所有推理和视觉都走本地 Provider。</div>
            ) : llmRoutingMode === "hybrid_performance" ? (
              <>
                <SelectField
                  label="摘要/字幕 Provider"
                  value={hybridAnalysisProvider}
                  onChange={(event) => onChange("hybrid_analysis_provider", event.target.value)}
                  options={REASONING_PROVIDER_OPTIONS.map((provider) => ({ value: provider, label: getProviderLabel(provider) }))}
                />
                <SelectField
                  label="摘要/字幕模型"
                  value={String(form.hybrid_analysis_model ?? "")}
                  onChange={(event) => onChange("hybrid_analysis_model", event.target.value)}
                  options={buildModelOptions(hybridAnalysisModels, String(form.hybrid_analysis_model ?? ""))}
                />
                <SelectField
                  label="摘要/字幕搜索"
                  value={hybridAnalysisSearchMode}
                  onChange={(event) => onChange("hybrid_analysis_search_mode", event.target.value)}
                  options={[
                    { value: "off", label: "关闭" },
                    { value: "entity_gated", label: "主体明确时启用" },
                    { value: "follow_provider", label: "始终跟随链路" },
                  ]}
                />
                <SelectField
                  label="平台文案 Provider"
                  value={hybridCopyProvider}
                  onChange={(event) => onChange("hybrid_copy_provider", event.target.value)}
                  options={REASONING_PROVIDER_OPTIONS.map((provider) => ({ value: provider, label: getProviderLabel(provider) }))}
                />
                <SelectField
                  label="平台文案模型"
                  value={String(form.hybrid_copy_model ?? "")}
                  onChange={(event) => onChange("hybrid_copy_model", event.target.value)}
                  options={buildModelOptions(hybridCopyModels, String(form.hybrid_copy_model ?? ""))}
                />
                <SelectField
                  label="平台文案搜索"
                  value={hybridCopySearchMode}
                  onChange={(event) => onChange("hybrid_copy_search_mode", event.target.value)}
                  options={[
                    { value: "off", label: "关闭" },
                    { value: "entity_gated", label: "主体明确时启用" },
                    { value: "follow_provider", label: "始终跟随链路" },
                  ]}
                />
                <div className="settings-chain-note muted">
                  高性能混合默认建议：摘要/字幕走 {getProviderLabel(hybridAnalysisProvider)}，搜索 {getHybridSearchModeLabel(hybridAnalysisSearchMode)}；平台文案走 {getProviderLabel(hybridCopyProvider)}，搜索 {getHybridSearchModeLabel(hybridCopySearchMode)}。视觉理解会自动跟随各自链路 Provider。
                </div>
              </>
            ) : (
              <div className="settings-chain-note muted">Bundled 模式下，摘要、字幕、视觉和搜索统一跟随主推理 Provider，只保留搜索与视觉兜底链路。</div>
            )}
          </div>
        </section>

        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">转写</span>
              <strong>转写链路</strong>
            </div>
            <div className="muted">
              {getTranscriptionProviderLabel(transcriptionProvider)} · {String(form.transcription_model ?? "未设置")}
            </div>
          </div>
          <div className="settings-chain-card-body form-grid three-up">
            <SelectField
              label="转写 Provider"
              value={transcriptionProvider}
              onChange={(event) => onChange("transcription_provider", event.target.value)}
              options={transcriptionProviderOptions}
            />
            <SelectField
              label="转写模型"
              value={String(form.transcription_model ?? "")}
              onChange={(event) => onChange("transcription_model", event.target.value)}
              options={buildModelOptions(transcriptionModels, String(form.transcription_model ?? ""))}
            />
            <SelectField
              label="转写方言"
              value={String(form.transcription_dialect ?? "mandarin")}
              onChange={(event) => onChange("transcription_dialect", event.target.value)}
              options={transcriptionDialects}
            />
          </div>
        </section>

        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">推理</span>
              <strong>推理链路</strong>
            </div>
            <div className="muted">
              {llmMode === "local" ? "本地模式" : getProviderLabel(activeReasoningProvider)} · {activeReasoningModel || "未设置模型"}
            </div>
          </div>
          <div className="settings-chain-card-body form-grid three-up">
            <SelectField
              label="LLM 模式"
              value={llmMode}
              onChange={(event) => onChange("llm_mode", event.target.value)}
              options={[
                { value: "performance", label: "performance" },
                { value: "local", label: "local" },
              ]}
            />
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
                <SelectField
                  label="视觉兜底 Provider"
                  value={String(form.multimodal_fallback_provider ?? "")}
                  onChange={(event) => onChange("multimodal_fallback_provider", event.target.value)}
                  options={multimodalFallbackProviders}
                />
              <SelectField
                  label="视觉兜底模型"
                  value={String(form.multimodal_fallback_model ?? "")}
                  onChange={(event) => onChange("multimodal_fallback_model", event.target.value)}
                  options={buildModelOptions(fallbackModels, String(form.multimodal_fallback_model ?? ""))}
                />
                <CheckboxField
                  label="主链路失败时自动切换到备用方案"
                  checked={llmBackupEnabled}
                  onChange={(event) => onChange("llm_backup_enabled", event.target.checked)}
                  className="settings-chain-note"
                />
                {llmBackupEnabled ? (
                  <>
                    <SelectField
                      label="备用推理 Provider"
                      value={backupReasoningProvider}
                      onChange={(event) => onChange("backup_reasoning_provider", event.target.value)}
                      options={REASONING_PROVIDER_OPTIONS.map((provider) => ({ value: provider, label: getProviderLabel(provider) }))}
                    />
                    <SelectField
                      label="备用推理模型"
                      value={String(form.backup_reasoning_model ?? "")}
                      onChange={(event) => onChange("backup_reasoning_model", event.target.value)}
                      options={buildModelOptions(backupReasoningModels, String(form.backup_reasoning_model ?? ""))}
                    />
                    <SelectField
                      label="备用视觉模型"
                      value={String(form.backup_vision_model ?? "")}
                      onChange={(event) => onChange("backup_vision_model", event.target.value)}
                      options={buildModelOptions(backupVisionModels, String(form.backup_vision_model ?? ""))}
                    />
                    <SelectField
                      label="备用搜索 Provider"
                      value={backupSearchProvider}
                      onChange={(event) => onChange("backup_search_provider", event.target.value)}
                      options={searchProviders}
                    />
                    <SelectField
                      label="备用搜索回退"
                      value={backupSearchFallbackProvider}
                      onChange={(event) => onChange("backup_search_fallback_provider", event.target.value)}
                      options={searchFallbackProviders}
                    />
                    {backupSearchProvider === "model" || backupSearchFallbackProvider === "model" ? (
                      <TextField
                        label="备用搜索辅助模型"
                        value={String(form.backup_model_search_helper ?? "")}
                        onChange={(event) => onChange("backup_model_search_helper", event.target.value)}
                      />
                    ) : null}
                    <div className="settings-chain-note muted">
                      备用方案会把推理、视觉和搜索切到同一套链路。当前默认值是 OpenAI / Codex 兼容链路，主模型失败后回落到 gpt-5.4-mini。
                    </div>
                  </>
                ) : null}
                <div className="settings-chain-note muted">主视觉理解始终跟随当前推理 Provider，只有兜底链路可单独配置。</div>
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
              </>
            )}
          </div>
        </section>

        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">搜索</span>
              <strong>搜索链路</strong>
            </div>
            <div className="muted">{getSearchSummary(form)}</div>
          </div>
          <div className="settings-chain-card-body form-grid three-up">
            <div className="settings-chain-note muted">主搜索始终跟随当前推理 Provider：{getProviderLabel(activeReasoningProvider)}。</div>
            <SelectField
              label="搜索回退 Provider"
              value={searchFallbackProvider}
              onChange={(event) => onChange("search_fallback_provider", event.target.value)}
              options={searchFallbackProviders}
            />
            {searchFallbackProvider === "model" ? (
              <TextField
                label="搜索辅助模型"
                value={String(form.model_search_helper ?? "")}
                onChange={(event) => onChange("model_search_helper", event.target.value)}
              />
            ) : (
              <div className="settings-chain-note muted">仅在启用模型代理搜索时需要辅助模型。</div>
            )}
          </div>
        </section>
      </div>
    </section>
  );
}

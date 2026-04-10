import type { Config } from "../../types";
import type { SettingsForm } from "./constants";

export const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  heygem: "HeyGem",
  indextts2: "IndexTTS2",
  minimax: "MiniMax",
  model: "模型代理",
  ollama: "Ollama",
  openai: "OpenAI",
  qwen3_asr: "Qwen3 ASR",
  runninghub: "RunningHub",
  searxng: "SearXNG",
};

export const TRANSCRIPTION_PROVIDER_LABELS: Record<string, string> = {
  funasr: "FunASR (local)",
  faster_whisper: "Faster Whisper (local)",
  openai: "OpenAI (api)",
  qwen3_asr: "Qwen3 ASR (local)",
};

function readString(form: SettingsForm, key: string, fallback = ""): string {
  return String(form[key] ?? fallback).trim();
}

export function getLlmRoutingMode(form: SettingsForm): string {
  return readString(form, "llm_routing_mode", "bundled");
}

export function isHybridRoutingEnabled(form: SettingsForm): boolean {
  return readString(form, "llm_mode", "performance") === "performance" && getLlmRoutingMode(form) === "hybrid_performance";
}

export function getProviderLabel(value: string): string {
  return PROVIDER_LABELS[value] ?? (value || "未设置");
}

export function getTranscriptionProviderLabel(value: string): string {
  return TRANSCRIPTION_PROVIDER_LABELS[value] ?? getProviderLabel(value);
}

export function isLocalTranscriptionProvider(value: string): boolean {
  return value === "funasr" || value === "faster_whisper" || value === "qwen3_asr";
}

export function getProviderStatusLabel(status: string): string {
  switch (status) {
    case "ok":
      return "状态正常";
    case "configured":
      return "已配置";
    case "unauthorized":
      return "鉴权失败";
    case "unreachable":
      return "不可达";
    case "not_configured":
      return "未配置";
    default:
      return status || "未知状态";
  }
}

export function formatProviderDetail(detail: string): string {
  const normalized = String(detail ?? "").trim();
  if (!normalized) {
    return "暂无检测信息";
  }
  const lower = normalized.toLowerCase();
  if (lower === "credential is missing") {
    return "未配置凭据，暂时无法完成连通性检查。";
  }
  if (lower.startsWith("http 401") || lower.startsWith("http 403")) {
    return "鉴权失败，请检查 API Key 或上游权限。";
  }
  if (lower.startsWith("http 404")) {
    return "服务可达，但模型列表接口返回 404。";
  }
  if (lower.includes("connection refused")) {
    return "连接被拒绝，请确认服务已启动并监听当前地址。";
  }
  if (lower.includes("timed out")) {
    return "请求超时，请检查网络或上游响应速度。";
  }
  return normalized;
}

export function getActiveReasoningProvider(form: SettingsForm): string {
  return readString(form, "llm_mode", "performance") === "local" ? "ollama" : readString(form, "reasoning_provider");
}

export function getActiveReasoningModel(form: SettingsForm): string {
  return readString(form, "llm_mode", "performance") === "local"
    ? readString(form, "local_reasoning_model")
    : readString(form, "reasoning_model");
}

export function getOverrideKeys(config?: Config): string[] {
  return config?.override_keys ?? Object.keys(config?.overrides ?? {});
}

export function hasRuntimeOverride(config: Config | undefined, key: string): boolean {
  return getOverrideKeys(config).includes(key);
}

export function hasSessionSecret(config: Config | undefined, key: string): boolean {
  return (config?.session_secret_keys ?? []).includes(key);
}

export function getCredentialSourceLabel(
  config: Config | undefined,
  {
    mode,
    helperCommand,
    keySet,
    overrideKey,
  }: {
  mode?: string;
  helperCommand?: string;
  keySet: boolean;
  overrideKey: string;
  },
) {
  if (hasSessionSecret(config, overrideKey)) {
    return "当前会话";
  }
  if (mode && mode !== "api_key" && String(helperCommand ?? "").trim()) {
    return "helper 命令";
  }
  if (keySet && hasRuntimeOverride(config, overrideKey)) {
    return "运行时覆盖";
  }
  if (keySet) {
    return ".env / 启动环境";
  }
  return "未配置";
}

export function getSearchSummary(form: SettingsForm): string {
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const fallbackProvider = readString(form, "search_fallback_provider", "searxng");
  return `自动跟随 ${getProviderLabel(activeReasoningProvider)}，失败回退 ${getProviderLabel(fallbackProvider)}`;
}

export function getHybridSearchModeLabel(value: string): string {
  switch (value) {
    case "off":
      return "关闭";
    case "entity_gated":
      return "主体明确时启用";
    case "follow_provider":
      return "跟随链路";
    default:
      return value || "未设置";
  }
}

export function getRoutingSummary(form: SettingsForm): string {
  if (!isHybridRoutingEnabled(form)) {
    return `Bundled · 推理 ${getProviderLabel(getActiveReasoningProvider(form))}`;
  }
  const analysisProvider = readString(form, "hybrid_analysis_provider", "openai");
  const copyProvider = readString(form, "hybrid_copy_provider", "minimax");
  return `Hybrid · 摘要/字幕 ${getProviderLabel(analysisProvider)} · 文案 ${getProviderLabel(copyProvider)}`;
}

import type { Config } from "../../types";
import type { SettingsForm } from "./constants";

export const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  heygem: "HeyGem",
  indextts2: "IndexTTS2",
  minimax: "MiniMax",
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
  const searchProvider = readString(form, "search_provider", "auto");
  if (searchProvider !== "auto") {
    return getProviderLabel(searchProvider);
  }
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const fallbackProvider = readString(form, "search_fallback_provider", "searxng");
  return `自动跟随 ${getProviderLabel(activeReasoningProvider)}，失败回退 ${getProviderLabel(fallbackProvider)}`;
}

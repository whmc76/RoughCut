import type { Config, RuntimeEnvironment } from "../../types";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { getActiveReasoningProvider, getCredentialSourceLabel, getProviderLabel } from "./helpers";

const DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1";
const DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com";
const DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1";
const DEFAULT_MINIMAX_API_HOST = "https://api.minimaxi.com";
const DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const DEFAULT_OUTPUT_DIR = "output";

type RuntimeSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  runtimeEnvironment?: RuntimeEnvironment;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function RuntimeSettingsPanel({ form, config, runtimeEnvironment, onChange }: RuntimeSettingsPanelProps) {
  const transcriptionProvider = String(form.transcription_provider ?? "");
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const searchProvider = String(form.search_provider ?? "auto");
  const searchFallbackProvider = String(form.search_fallback_provider ?? "searxng");
  const usesOpenAI = transcriptionProvider === "openai" || activeReasoningProvider === "openai" || searchProvider === "openai";
  const usesAnthropic = activeReasoningProvider === "anthropic" || searchProvider === "anthropic";
  const usesMiniMax = activeReasoningProvider === "minimax" || searchProvider === "minimax";
  const usesOllama = activeReasoningProvider === "ollama" || searchProvider === "ollama";
  const openAiCredentialSource = getCredentialSourceLabel(config, {
    mode: String(runtimeEnvironment?.openai_auth_mode ?? "api_key"),
    helperCommand: String(runtimeEnvironment?.openai_api_key_helper ?? ""),
    keySet: Boolean(config?.openai_api_key_set),
    overrideKey: "openai_api_key",
  });
  const anthropicCredentialSource = getCredentialSourceLabel(config, {
    mode: String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key"),
    helperCommand: String(runtimeEnvironment?.anthropic_api_key_helper ?? ""),
    keySet: Boolean(config?.anthropic_api_key_set),
    overrideKey: "anthropic_api_key",
  });
  const minimaxCredentialSource = getCredentialSourceLabel(config, {
    keySet: Boolean(config?.minimax_api_key_set),
    overrideKey: "minimax_api_key",
  });
  const openAiUsesHelper = String(runtimeEnvironment?.openai_auth_mode ?? "api_key") !== "api_key";
  const anthropicUsesHelper = String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key") !== "api_key";
  const openAiBaseUrl = String(runtimeEnvironment?.openai_base_url ?? DEFAULT_OPENAI_BASE_URL).trim();
  const anthropicBaseUrl = String(runtimeEnvironment?.anthropic_base_url ?? DEFAULT_ANTHROPIC_BASE_URL).trim();
  const minimaxBaseUrl = String(runtimeEnvironment?.minimax_base_url ?? DEFAULT_MINIMAX_BASE_URL).trim();
  const minimaxApiHost = String(runtimeEnvironment?.minimax_api_host ?? DEFAULT_MINIMAX_API_HOST).trim();
  const ollamaBaseUrl = String(runtimeEnvironment?.ollama_base_url ?? DEFAULT_OLLAMA_BASE_URL).trim();
  const voiceCloneApiBaseUrl = String(runtimeEnvironment?.voice_clone_api_base_url ?? "").trim();
  const activeProviders = [
    usesOpenAI ? `OpenAI · ${openAiCredentialSource}` : "",
    usesAnthropic ? `Anthropic · ${anthropicCredentialSource}` : "",
    usesMiniMax ? `MiniMax · ${minimaxCredentialSource}` : "",
    usesOllama ? "Ollama · 本地服务" : "",
  ].filter(Boolean);
  const providerDetailsOpen =
    activeProviders.length <= 1 ||
    (usesOpenAI && (openAiCredentialSource === "未配置" || openAiUsesHelper)) ||
    (usesAnthropic && (anthropicCredentialSource === "未配置" || anthropicUsesHelper)) ||
    (usesMiniMax && minimaxCredentialSource === "未配置");
  const maxUploadSizeMb = Number(form.max_upload_size_mb ?? 2048);
  const maxVideoDurationSec = Number(form.max_video_duration_sec ?? 7200);
  const ffmpegTimeoutSec = Number(form.ffmpeg_timeout_sec ?? 600);
  const runtimeLimitsSummary = `上传 ${maxUploadSizeMb} MB · 视频 ${maxVideoDurationSec} 秒 · FFmpeg ${ffmpegTimeoutSec} 秒`;
  const runtimeLimitsOpen = maxUploadSizeMb !== 2048 || maxVideoDurationSec !== 7200 || ffmpegTimeoutSec !== 600;
  const outputDir = String(runtimeEnvironment?.output_dir ?? DEFAULT_OUTPUT_DIR).trim() || DEFAULT_OUTPUT_DIR;
  const environmentSummary = [
    `输出 ${outputDir}`,
    openAiUsesHelper ? `OpenAI ${String(runtimeEnvironment?.openai_auth_mode ?? "api_key")}` : "云端接入已分层",
    voiceCloneApiBaseUrl ? "创意服务已接入" : "创意服务未配置",
  ].join(" · ");
  const environmentDetailsOpen =
    outputDir !== DEFAULT_OUTPUT_DIR ||
    openAiUsesHelper ||
    anthropicUsesHelper ||
    minimaxBaseUrl !== DEFAULT_MINIMAX_BASE_URL ||
    minimaxApiHost !== DEFAULT_MINIMAX_API_HOST ||
    ollamaBaseUrl !== DEFAULT_OLLAMA_BASE_URL;
  const reasoningSummary =
    searchProvider === "auto"
      ? `推理 ${getProviderLabel(activeReasoningProvider)} · 搜索自动跟随，失败回退 ${getProviderLabel(searchFallbackProvider)}`
      : `推理 ${getProviderLabel(activeReasoningProvider)} · 搜索固定走 ${getProviderLabel(searchProvider)}`;

  return (
    <section className="panel">
      <PanelHeader title="当前 LLM 接入" description="只显示当前会生效的接入项。" />
      <div className="form-stack">
        <div className="settings-overview-grid">
          <article className="settings-overview-card">
            <span className="settings-overview-label">接入与限制</span>
            <strong>{activeProviders.length} 个实际使用中的 Provider</strong>
            <div className="muted">{activeProviders.join(" · ")}</div>
            <div className="muted">{reasoningSummary}</div>
            <div className="muted">{runtimeLimitsSummary}</div>
          </article>
        </div>
        <details className="settings-disclosure" open={providerDetailsOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>连接与鉴权细节</strong>
              <div className="muted">{activeProviders.join(" · ")}</div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <div className="form-stack">
              {usesOpenAI && (
                <div className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>OpenAI</strong>
                    <span className="muted">凭据来源：{openAiCredentialSource}</span>
                  </div>
                  <div className="form-stack">
                    <TextField
                      label="OpenAI API Key"
                      type="password"
                      value={String(form.openai_api_key ?? "")}
                      onChange={(event) => onChange("openai_api_key", event.target.value)}
                      placeholder={config?.openai_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
                    />
                    <div className="muted">
                      连接参数改为启动环境管理，详见运行环境状态。
                      {openAiUsesHelper ? ` 当前模式 ${String(runtimeEnvironment?.openai_auth_mode ?? "api_key")}。` : ""}
                      当前地址：{openAiBaseUrl}
                    </div>
                  </div>
                </div>
              )}
              {usesAnthropic && (
                <div className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>Anthropic</strong>
                    <span className="muted">凭据来源：{anthropicCredentialSource}</span>
                  </div>
                  <div className="form-stack">
                    <TextField
                      label="Anthropic API Key"
                      type="password"
                      value={String(form.anthropic_api_key ?? "")}
                      onChange={(event) => onChange("anthropic_api_key", event.target.value)}
                      placeholder={config?.anthropic_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
                    />
                    <div className="muted">
                      连接参数改为启动环境管理，详见运行环境状态。
                      {anthropicUsesHelper ? ` 当前模式 ${String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key")}。` : ""}
                      当前地址：{anthropicBaseUrl}
                    </div>
                  </div>
                </div>
              )}
              {usesMiniMax && (
                <div className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>MiniMax</strong>
                    <span className="muted">凭据来源：{minimaxCredentialSource}</span>
                  </div>
                  <div className="form-stack">
                    <TextField
                      label="MiniMax API Key"
                      type="password"
                      value={String(form.minimax_api_key ?? "")}
                      onChange={(event) => onChange("minimax_api_key", event.target.value)}
                      placeholder={config?.minimax_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
                    />
                    <div className="muted">连接参数改为启动环境管理，详见运行环境状态。当前地址：{minimaxBaseUrl} · {minimaxApiHost}</div>
                  </div>
                </div>
              )}
              {usesOllama && (
                <div className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>Ollama</strong>
                    <span className="muted">本地推理服务</span>
                  </div>
                  <div className="form-stack">
                    <TextField
                      label="Ollama API Key"
                      type="password"
                      value={String(form.ollama_api_key ?? "")}
                      onChange={(event) => onChange("ollama_api_key", event.target.value)}
                      placeholder={config?.ollama_api_key_set ? "已设置，留空则不更新" : "通常可留空"}
                    />
                    <div className="muted">连接参数改为启动环境管理，详见运行环境状态。当前地址：{ollamaBaseUrl}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </details>
        {(transcriptionProvider === "local_whisper" || transcriptionProvider === "funasr") && (
          <div className="notice">转写走本地 {getProviderLabel(transcriptionProvider)}，不依赖云端 API key。</div>
        )}
        <details className="settings-disclosure" open={environmentDetailsOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>运行环境状态</strong>
              <div className="muted">{environmentSummary}</div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <div className="form-stack">
              <div className="muted">OpenAI：{openAiBaseUrl} · {String(runtimeEnvironment?.openai_auth_mode ?? "api_key")}</div>
              <div className="muted">Anthropic：{anthropicBaseUrl} · {String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key")}</div>
              <div className="muted">MiniMax：{minimaxBaseUrl} · Host {minimaxApiHost}</div>
              <div className="muted">Ollama：{ollamaBaseUrl}</div>
              <div className="muted">数字人：{String(runtimeEnvironment?.avatar_api_base_url ?? "未设置")}</div>
              <div className="muted">数字人训练 / TTS：{String(runtimeEnvironment?.avatar_training_api_base_url ?? "未设置")}</div>
              <div className="muted">语音：{voiceCloneApiBaseUrl || "未设置"}</div>
              <div className="muted">输出目录：{outputDir}</div>
            </div>
          </div>
        </details>
        <details className="settings-disclosure" open={runtimeLimitsOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>上传与执行限制</strong>
              <div className="muted">{runtimeLimitsSummary}</div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <div className="field-row">
              <TextField
                label="最大上传大小 MB"
                type="number"
                value={String(maxUploadSizeMb)}
                onChange={(event) => onChange("max_upload_size_mb", Number(event.target.value))}
              />
              <TextField
                label="最长视频秒数"
                type="number"
                value={String(maxVideoDurationSec)}
                onChange={(event) => onChange("max_video_duration_sec", Number(event.target.value))}
              />
            </div>
            <TextField
              label="FFmpeg 超时秒数"
              type="number"
              value={String(ffmpegTimeoutSec)}
              onChange={(event) => onChange("ffmpeg_timeout_sec", Number(event.target.value))}
            />
          </div>
        </details>
      </div>
    </section>
  );
}

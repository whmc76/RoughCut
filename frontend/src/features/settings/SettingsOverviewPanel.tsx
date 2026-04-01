import type { Config, ConfigProfiles, ProviderServiceStatus, RuntimeEnvironment } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import {
  getActiveReasoningModel,
  getActiveReasoningProvider,
  getCredentialSourceLabel,
  getProviderLabel,
  getProviderStatusLabel,
  getSearchSummary,
  getTranscriptionProviderLabel,
} from "./helpers";
import { formatDirtyDetailValue, formatDirtyKeyLabel } from "../configProfiles/diffPresentation";

type SettingsOverviewPanelProps = {
  form: SettingsForm;
  config?: Config;
  runtimeEnvironment?: RuntimeEnvironment;
  serviceStatus?: ProviderServiceStatus;
  configProfiles?: ConfigProfiles;
};

export function SettingsOverviewPanel({ form, config, runtimeEnvironment, serviceStatus, configProfiles }: SettingsOverviewPanelProps) {
  const transcriptionProvider = String(form.transcription_provider ?? "");
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const activeReasoningModel = getActiveReasoningModel(form);
  const profileBindableCount = config?.profile_bindable_keys.length ?? 0;
  const activeProfile = configProfiles?.profiles.find((profile) => profile.is_active) ?? null;
  const dirtyDetails = configProfiles?.active_profile_dirty_details ?? [];
  const factCheckEnabled = Boolean(form.fact_check_enabled);
  const autoConfirmEnabled = Boolean(form.auto_confirm_content_profile);
  const rerunEnabled = Boolean(form.quality_auto_rerun_enabled);
  const legacyFlags = [
    config?.persistence.legacy_override_file_present ? "roughcut_config.json" : "",
    config?.persistence.legacy_profiles_file_present ? "roughcut_config_profiles.json" : "",
    config?.persistence.legacy_packaging_manifest_present ? "packaging/manifest.json" : "",
  ].filter(Boolean);
  const activeCredentialSource =
    activeReasoningProvider === "openai"
      ? getCredentialSourceLabel(config, {
          mode: String(runtimeEnvironment?.openai_auth_mode ?? "api_key"),
          helperCommand: String(runtimeEnvironment?.openai_api_key_helper ?? ""),
          keySet: Boolean(config?.openai_api_key_set),
          overrideKey: "openai_api_key",
        })
      : activeReasoningProvider === "anthropic"
        ? getCredentialSourceLabel(config, {
            mode: String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key"),
            helperCommand: String(runtimeEnvironment?.anthropic_api_key_helper ?? ""),
            keySet: Boolean(config?.anthropic_api_key_set),
            overrideKey: "anthropic_api_key",
          })
        : activeReasoningProvider === "minimax"
          ? getCredentialSourceLabel(config, {
              keySet: Boolean(config?.minimax_api_key_set),
              overrideKey: "minimax_api_key",
            })
          : "本地服务";
  const executionSummary = [
    `转写 ${getTranscriptionProviderLabel(transcriptionProvider)} / ${String(form.transcription_model ?? "未设置")}`,
    `推理 ${getProviderLabel(activeReasoningProvider)} / ${activeReasoningModel || "未设置模型"}`,
    `搜索 ${getSearchSummary(form)}`,
  ];
  const strategySummary = [
    factCheckEnabled ? "事实核查未接入（当前值为开启）" : "事实核查未接入",
    autoConfirmEnabled
      ? `画像自动确认 ${Number(form.content_profile_review_threshold ?? 0.9).toFixed(2)}`
      : "画像人工确认",
    rerunEnabled ? `低分复跑 < ${Number(form.quality_auto_rerun_below_score ?? 75)}` : "低分复跑关闭",
  ];
  const storageSummary = `设置 ${config?.persistence.settings_store ?? "database"} · 方案 ${config?.persistence.profiles_store ?? "database"} · 包装 ${config?.persistence.packaging_store ?? "database"}`;
  const activeLocalStatus =
    transcriptionProvider === "qwen3_asr"
      ? serviceStatus?.services.qwen3_asr
      : activeReasoningProvider === "ollama"
        ? serviceStatus?.services.ollama
        : null;
  const profileStatus = configProfiles?.active_profile_dirty
    ? `当前设置与方案存在 ${dirtyDetails.length || configProfiles.active_profile_dirty_keys.length} 项差异`
    : activeProfile
      ? "当前设置与激活方案一致"
      : "尚未保存任何配置方案";

  return (
    <section className="panel">
      <PanelHeader title="当前生效配置" description="只看当前运行状态，不回显密钥。" />
      <div className="settings-overview-grid">
        <article className="settings-overview-card">
          <span className="settings-overview-label">执行链路</span>
          <strong>
            {getTranscriptionProviderLabel(transcriptionProvider)} + {getProviderLabel(activeReasoningProvider)}
          </strong>
          <div className="muted">{executionSummary.join(" · ")}</div>
        </article>
        <article className="settings-overview-card">
          <span className="settings-overview-label">凭据来源</span>
          <strong>{activeCredentialSource}</strong>
          <div className="muted">
            当前推理 Provider：{getProviderLabel(activeReasoningProvider)}
            {activeReasoningModel ? ` · ${activeReasoningModel}` : ""}
          </div>
        </article>
        <article className="settings-overview-card">
          <span className="settings-overview-label">生产与方案</span>
          <strong>{activeProfile ? activeProfile.name : `${profileBindableCount} 项可绑定到方案`}</strong>
          <div className="muted">{strategySummary.join(" · ")}</div>
          <div className="muted">{profileStatus}</div>
          <div className="muted">{storageSummary}</div>
          {activeLocalStatus ? <div className="muted">本地服务：{getProviderStatusLabel(activeLocalStatus.status)}</div> : null}
        </article>
      </div>
      <div className="notice top-gap">
        当前推理凭据来源：{activeCredentialSource}。API key 不回显，重新输入才会覆盖。
      </div>
      {configProfiles?.active_profile_dirty ? (
        <div className="notice top-gap">
          <div>当前设置已偏离激活方案，以下为差异摘要。</div>
          <div className="config-profile-diff-list compact-top">
            {dirtyDetails.map((item) => (
              <div key={item.key} className="config-profile-diff-row">
                <span className="status-pill failed config-profile-summary-tag">{formatDirtyKeyLabel(item.key)}</span>
                <div className="muted">
                  {formatDirtyDetailValue(item.key, item.saved_value)} -&gt; {formatDirtyDetailValue(item.key, item.current_value)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {legacyFlags.length ? (
        <div className="notice top-gap">
          检测到遗留文件：{legacyFlags.join("、")}。当前以数据库为准。
        </div>
      ) : (
        <div className="notice top-gap">当前配置、方案和包装都已走数据库持久化。</div>
      )}
    </section>
  );
}

import type { Config, ConfigProfiles, ProviderServiceStatus, RuntimeEnvironment } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import {
  getActiveReasoningModel,
  getActiveReasoningProvider,
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

function buildServiceSummary(serviceStatus?: ProviderServiceStatus) {
  const entries = Object.entries(serviceStatus?.services ?? {});
  if (!entries.length) {
    return { title: "还没有状态数据", detail: "连接后会显示可用链路。" };
  }
  const okCount = entries.filter(([, entry]) => entry.status === "ok" || entry.status === "configured").length;
  const highlights = entries
    .slice(0, 3)
    .map(([name, entry]) => `${getProviderLabel(name)} ${getProviderStatusLabel(entry.status)}`)
    .join(" · ");
  return {
    title: `${okCount} / ${entries.length} 条链路可用`,
    detail: highlights,
  };
}

export function SettingsOverviewPanel({ form, config, runtimeEnvironment, serviceStatus, configProfiles }: SettingsOverviewPanelProps) {
  const transcriptionProvider = String(form.transcription_provider ?? "");
  const activeReasoningProvider = getActiveReasoningProvider(form);
  const activeReasoningModel = getActiveReasoningModel(form);
  const activeProfile = configProfiles?.profiles.find((profile) => profile.is_active) ?? null;
  const dirtyDetails = configProfiles?.active_profile_dirty_details ?? [];
  const serviceSummary = buildServiceSummary(serviceStatus);
  const executionSummary = [
    `转写 ${getTranscriptionProviderLabel(transcriptionProvider)} / ${String(form.transcription_model ?? "未设置")}`,
    `推理 ${getProviderLabel(activeReasoningProvider)} / ${activeReasoningModel || "未设置模型"}`,
    `搜索 ${getSearchSummary(form)}`,
  ];
  const storageSummary = `设置 ${config?.persistence.settings_store ?? "database"} · 方案 ${config?.persistence.profiles_store ?? "database"} · 包装 ${config?.persistence.packaging_store ?? "database"}`;
  const profileSummary = configProfiles?.active_profile_dirty
    ? `当前设置偏离激活方案 ${dirtyDetails.length || configProfiles.active_profile_dirty_keys.length} 项`
    : activeProfile
      ? "当前设置与激活方案一致"
      : "尚未保存任何配置方案";
  const environmentSummary = [
    `OpenAI ${String(runtimeEnvironment?.openai_auth_mode ?? "api_key")}`,
    `Anthropic ${String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key")}`,
    `输出 ${String(runtimeEnvironment?.output_dir ?? "output")}`,
  ].join(" · ");

  return (
    <section className="panel settings-summary-panel">
      <PanelHeader title="当前状态" description="这里显示模型、服务和当前方案。" />
      <div className="settings-summary-grid">
        <article className="settings-command-card">
          <span className="settings-overview-label">模型组合</span>
          <strong>{getTranscriptionProviderLabel(transcriptionProvider)} + {getProviderLabel(activeReasoningProvider)}</strong>
          <div className="muted">{executionSummary.join(" · ")}</div>
        </article>
        <article className="settings-command-card">
          <span className="settings-overview-label">服务</span>
          <strong>{serviceSummary.title}</strong>
          <div className="muted">{serviceSummary.detail}</div>
          <div className="muted">{environmentSummary}</div>
        </article>
        <article className="settings-command-card">
          <span className="settings-overview-label">当前方案</span>
          <strong>{activeProfile ? activeProfile.name : "未绑定方案"}</strong>
          <div className="muted">{profileSummary}</div>
          <div className="muted">{storageSummary}</div>
        </article>
      </div>
      {configProfiles?.active_profile_dirty ? (
        <div className="notice top-gap">
          <div>当前设置已偏离激活方案，以下是差异摘要。</div>
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
      <div className="notice top-gap">当前设置已经保存到数据库。</div>
    </section>
  );
}

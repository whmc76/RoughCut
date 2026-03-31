import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { BotSettingsPanel } from "../features/settings/BotSettingsPanel";
import { CreativeSettingsPanel } from "../features/settings/CreativeSettingsPanel";
import { useI18n } from "../i18n";
import { ModelSettingsPanel } from "../features/settings/ModelSettingsPanel";
import { RuntimeSettingsPanel } from "../features/settings/RuntimeSettingsPanel";
import { SettingsOverviewPanel } from "../features/settings/SettingsOverviewPanel";
import { QualitySettingsPanel } from "../features/settings/QualitySettingsPanel";
import { getActiveReasoningProvider, getProviderLabel, getSearchSummary } from "../features/settings/helpers";
import { useSettingsWorkspace } from "../features/settings/useSettingsWorkspace";

export function SettingsPage() {
  const { t } = useI18n();
  const workspace = useSettingsWorkspace();
  const activeReasoningProvider = getActiveReasoningProvider(workspace.form);
  const advancedCreativeSummary = `${String(workspace.form.avatar_provider ?? "未设置")} + ${String(workspace.form.voice_provider ?? "未设置")}`;
  const telegramEnabled = Boolean(workspace.form.telegram_remote_review_enabled) || Boolean(workspace.form.telegram_agent_enabled);
  const advancedSectionOpen = telegramEnabled;
  const runtimeSectionOpen = telegramEnabled;
  const advancedSummary = [advancedCreativeSummary, telegramEnabled ? "Telegram / Agent 已启用" : "Telegram / Agent 未启用"].join(" · ");
  const runtimeSummary = [
    `推理 ${getProviderLabel(activeReasoningProvider)}`,
    getSearchSummary(workspace.form),
    telegramEnabled ? "Telegram / Agent 已启用" : "Telegram / Agent 未启用",
  ].join(" · ");
  const saveTone =
    workspace.saveState === "saving" ? "running" : workspace.saveState === "error" ? "failed" : workspace.saveState === "saved" ? "done" : "";
  const saveLabel =
    workspace.saveState === "saving"
      ? t("autosave.saving")
      : workspace.saveState === "error"
        ? t("autosave.error")
        : workspace.saveState === "saved"
          ? t("autosave.saved")
          : t("autosave.idle");

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("settings.page.eyebrow")}
        title={t("settings.page.title")}
        description={t("settings.page.description")}
        summary={[
          { label: "基础优先", value: "总览、模型、质量", detail: "先稳定核心产出，再打开更深层的接入设置" },
          { label: "高级收敛", value: "运行接入与工程能力", detail: "Telegram、Agent 和数字人配置放到后段，避免首屏过载" },
          { label: "保存方式", value: "自动保存", detail: "状态会直接反映当前配置是否已经落盘" },
        ]}
        actions={
          <>
            <button className="button ghost" onClick={() => workspace.reset.mutate()} disabled={workspace.reset.isPending}>
              {workspace.reset.isPending ? t("settings.page.resetting") : t("settings.page.reset")}
            </button>
            <span className={`status-pill ${saveTone}`}>{saveLabel}</span>
          </>
        }
      />
      {workspace.saveError && <div className="notice top-gap">{workspace.saveError}</div>}

      <PageSection
        eyebrow="核心"
        title="先稳定核心产出设置"
        description="优先处理总览、模型和质量，这些配置直接决定任务默认表现。"
      >
        <div className="panel-grid">
          <SettingsOverviewPanel
            form={workspace.form}
            config={workspace.config.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            configProfiles={workspace.configProfiles.data}
          />
          <ModelSettingsPanel
            form={workspace.form}
            options={workspace.options.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
          />
          <QualitySettingsPanel form={workspace.form} config={workspace.config.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
        </div>
      </PageSection>

      <PageSection
        eyebrow="接入"
        title="接入、自动化与高级工程能力"
        description="接入层和自动化能力放在后段，只在需要联动外部服务或增强能力时展开。"
      >
        <details className="settings-disclosure settings-page-runtime" open={runtimeSectionOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>接入与执行设置</strong>
              <div className="muted">{runtimeSummary}</div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <RuntimeSettingsPanel
              form={workspace.form}
              config={workspace.config.data}
              runtimeEnvironment={workspace.runtimeEnvironment.data}
              serviceStatus={workspace.serviceStatus.data}
              onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
            />
            <details className="settings-disclosure settings-page-advanced" open={advancedSectionOpen}>
              <summary className="settings-disclosure-trigger">
                <div>
                  <strong>高级工程设置</strong>
                  <div className="muted">{advancedSummary}</div>
                </div>
              </summary>
              <div className="settings-disclosure-body">
                <PanelHeader title="高级设置" description="数字人、Telegram 和工程执行细节。" />
                <div className="accordion-stack">
                  <details className="settings-disclosure">
                    <summary className="settings-disclosure-trigger">
                      <div>
                        <strong>增强能力</strong>
                        <div className="muted">数字人、配音、画中画</div>
                      </div>
                    </summary>
                    <div className="settings-disclosure-body">
                      <CreativeSettingsPanel
                        form={workspace.form}
                        config={workspace.config.data}
                        runtimeEnvironment={workspace.runtimeEnvironment.data}
                        options={workspace.options.data}
                        onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
                      />
                    </div>
                  </details>
                  <details className="settings-disclosure" open={telegramEnabled}>
                    <summary className="settings-disclosure-trigger">
                      <div>
                        <strong>Telegram 与 Agent</strong>
                        <div className="muted">远程审核与工程执行</div>
                      </div>
                    </summary>
                    <div className="settings-disclosure-body">
                      <BotSettingsPanel
                        form={workspace.form}
                        config={workspace.config.data}
                        onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
                      />
                    </div>
                  </details>
                </div>
              </div>
            </details>
          </div>
        </details>
      </PageSection>
    </section>
  );
}

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
  const telegramReviewEnabled = Boolean(workspace.form.telegram_remote_review_enabled);
  const telegramAgentEnabled = Boolean(workspace.form.telegram_agent_enabled);
  const automationSummary = [
    `${String(workspace.form.avatar_provider ?? "未设置")} + ${String(workspace.form.voice_provider ?? "未设置")}`,
    telegramReviewEnabled ? "Telegram 审核已启用" : "Telegram 审核关闭",
    telegramAgentEnabled ? "Telegram Agent 已启用" : "Telegram Agent 关闭",
  ].join(" · ");
  const environmentSummary = [
    `推理 ${getProviderLabel(activeReasoningProvider)}`,
    getSearchSummary(workspace.form),
    `输出 ${String(workspace.runtimeEnvironment.data?.output_dir ?? "output")}`,
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
    <section className="page-stack settings-page">
      <PageHeader
        eyebrow={t("settings.page.eyebrow")}
        title={t("settings.page.title")}
        description={t("settings.page.description")}
        summary={[
          { label: "核心链路", value: "转写 / 推理 / 搜索", detail: "配置、Provider 状态和检测动作在同一章完成" },
          { label: "质量策略", value: "审核 / 复跑 / 默认行为", detail: "把影响产出的规则与接入概念分开" },
          { label: "扩展自动化", value: "环境 / 数字人 / Telegram", detail: "保留工程能力，但不再藏在模糊的接入区" },
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
      {workspace.saveError ? <div className="notice top-gap">{workspace.saveError}</div> : null}

      <PageSection
        eyebrow="Core"
        title="核心链路与 Provider"
        description="先决定转写、推理和搜索如何跑，再直接看到每个 Provider 的状态、凭据来源和检测结果。"
      >
        <div className="settings-section-stack">
          <SettingsOverviewPanel
            form={workspace.form}
            config={workspace.config.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            configProfiles={workspace.configProfiles.data}
          />
          <ModelSettingsPanel
            form={workspace.form}
            config={workspace.config.data}
            options={workspace.options.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
          />
        </div>
      </PageSection>

      <PageSection
        eyebrow="Quality"
        title="质量与默认策略"
        description="把审核阈值、低分复跑和默认规则单独放一章，避免和 Provider 配置相互干扰。"
      >
        <QualitySettingsPanel
          form={workspace.form}
          config={workspace.config.data}
          onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
        />
      </PageSection>

      <PageSection
        eyebrow="Automation"
        title="扩展与自动化"
        description="运行环境、数字人和 Telegram/Agent 放在后段，但保持语义明确，不再用一个大而空的接入模块承载。"
      >
        <div className="settings-section-stack">
          <RuntimeSettingsPanel
            form={workspace.form}
            config={workspace.config.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
          />
          <section className="panel settings-extension-panel">
            <PanelHeader title="数字人与配音能力" description={environmentSummary} />
            <CreativeSettingsPanel
              form={workspace.form}
              config={workspace.config.data}
              runtimeEnvironment={workspace.runtimeEnvironment.data}
              options={workspace.options.data}
              onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
            />
          </section>
          <section className="panel settings-extension-panel">
            <PanelHeader title="Telegram 与 Agent 自动化" description={automationSummary} />
            <BotSettingsPanel
              form={workspace.form}
              config={workspace.config.data}
              onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
            />
          </section>
        </div>
      </PageSection>
    </section>
  );
}

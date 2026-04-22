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
import { getActiveReasoningProvider, getProviderLabel, getRoutingSummary, getSearchSummary, isHybridRoutingEnabled } from "../features/settings/helpers";
import { useSettingsWorkspace } from "../features/settings/useSettingsWorkspace";
import { Link } from "react-router-dom";

export function SettingsPage() {
  const { t } = useI18n();
  const workspace = useSettingsWorkspace();
  const activeReasoningProvider = getActiveReasoningProvider(workspace.form);
  const telegramReviewEnabled = Boolean(workspace.form.telegram_remote_review_enabled);
  const telegramAgentEnabled = Boolean(workspace.form.telegram_agent_enabled);
  const packagingReviewGap = Number(workspace.form.packaging_selection_review_gap ?? 0.08);
  const packagingMinScore = Number(workspace.form.packaging_selection_min_score ?? 0.6);
  const glossaryThreshold = Number(workspace.form.glossary_correction_review_threshold ?? 0.9);
  const outputDir = String(workspace.runtimeEnvironment.data?.output_dir ?? "output");
  const hybridEnabled = isHybridRoutingEnabled(workspace.form);
  const summaryCards = [
    {
      label: "执行设置",
      value: `${getRoutingSummary(workspace.form)} · ${getSearchSummary(workspace.form)}`,
      detail: `主推理 ${getProviderLabel(activeReasoningProvider)}，搜索 ${getSearchSummary(workspace.form)}，输出 ${outputDir}`,
    },
    {
      label: "包装设置",
      value: `复核间隔 ${packagingReviewGap.toFixed(2)} · 最低分 ${packagingMinScore.toFixed(2)} · 术语 ${glossaryThreshold.toFixed(2)}`,
      detail: "素材和输出规则。",
    },
    {
      label: "记忆与词表",
      value: "偏差记录 · 词条",
      detail: "分开管理。",
      action: (
        <div className="toolbar">
          <Link className="button ghost" to="/memory">
            记忆页
          </Link>
          <Link className="button ghost" to="/glossary">
            词表页
          </Link>
        </div>
      ),
    },
    {
      label: "控制页",
      value: "状态 / 停机",
      detail: "单独查看状态和停机。",
      action: (
        <Link className="button ghost" to="/control">
          打开控制页
        </Link>
      ),
    },
  ];
  const automationSummary = [
    `${String(workspace.form.avatar_provider ?? "未设置")} + ${String(workspace.form.voice_provider ?? "未设置")}`,
    telegramReviewEnabled ? "Telegram 审核已启用" : "Telegram 审核关闭",
    telegramAgentEnabled ? "远程控制已启用" : "远程控制关闭",
  ].join(" · ");
  const environmentSummary = [
    hybridEnabled ? getRoutingSummary(workspace.form) : `推理 ${getProviderLabel(activeReasoningProvider)}`,
    getSearchSummary(workspace.form),
    `输出路径 ${outputDir}`,
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
    <section className="page-stack settings-page settings-architecture-page">
      <PageHeader
        title={t("settings.page.title")}
        description={t("settings.page.description")}
        actions={
          <>
            <button
              className="button ghost"
              type="button"
              onClick={() => {
                if (window.confirm("确认恢复默认设置？当前未保存或已保存的配置改动可能会被覆盖。")) {
                  workspace.reset.mutate();
                }
              }}
              disabled={workspace.reset.isPending}
            >
              {workspace.reset.isPending ? t("settings.page.resetting") : t("settings.page.reset")}
            </button>
            <span className={`status-pill ${saveTone}`}>{saveLabel}</span>
          </>
        }
      />
      {workspace.saveError ? <div className="notice top-gap">{workspace.saveError}</div> : null}

      <section className="settings-architecture-deck">
        <div className="settings-architecture-lead">
          <h3>常用设置</h3>
          <p>这里只放最常改的项目。</p>
        </div>
        <div className="settings-overview-grid">
          {summaryCards.map((card) => (
            <article key={card.label} className="settings-command-card">
              <span className="settings-overview-label">{card.label}</span>
              <strong>{card.value}</strong>
              <div className="muted">{card.detail}</div>
              {card.action ? <div className="top-gap">{card.action}</div> : null}
            </article>
          ))}
        </div>
      </section>

      <PageSection
        className="settings-stage settings-stage-core settings-stage-core-grid"
        title="模型与执行"
        description="调整转写、模型和搜索。"
      >
        <div className="settings-core-stack">
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
        className="settings-stage settings-stage-quality settings-stage-quality-grid"
        title="质量与输出"
        description="调整审核阈值、包装复核和术语规则。"
      >
        <QualitySettingsPanel
          form={workspace.form}
          config={workspace.config.data}
          onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
        />
      </PageSection>

      <PageSection
        className="settings-stage settings-stage-automation settings-stage-automation-grid"
        title="运行与通知"
        description="调整运行环境、数字人和通知。"
      >
        <div className="settings-automation-stack">
          <RuntimeSettingsPanel
            form={workspace.form}
            config={workspace.config.data}
            runtimeEnvironment={workspace.runtimeEnvironment.data}
            serviceStatus={workspace.serviceStatus.data}
            onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
          />
          <div className="settings-automation-grid">
            <section className="settings-extension-shell settings-extension-shell-creative">
              <PanelHeader title="数字人与配音" description={environmentSummary} />
              <CreativeSettingsPanel
                form={workspace.form}
                config={workspace.config.data}
                runtimeEnvironment={workspace.runtimeEnvironment.data}
                options={workspace.options.data}
                onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
              />
            </section>
            <section className="settings-extension-shell settings-extension-shell-bot">
              <PanelHeader title="Telegram" description={automationSummary} />
              <BotSettingsPanel
                form={workspace.form}
                config={workspace.config.data}
                onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
              />
            </section>
          </div>
        </div>
      </PageSection>

      <PageSection
        className="settings-stage settings-stage-automation settings-stage-links"
        title="相关页面"
        description="记忆、词表和控制页。"
      >
        <div className="settings-link-grid">
          <article className="settings-command-card">
            <span className="settings-overview-label">记忆</span>
            <strong>偏差和偏好</strong>
            <div className="muted">查看长期偏差和偏好。</div>
            <div className="top-gap">
              <Link className="button ghost" to="/memory">
                查看记忆
              </Link>
            </div>
          </article>
          <article className="settings-command-card">
            <span className="settings-overview-label">词表</span>
            <strong>术语和导入</strong>
            <div className="muted">编辑词条和导入规则。</div>
            <div className="top-gap">
              <Link className="button ghost" to="/glossary">
                查看词表
              </Link>
            </div>
          </article>
        </div>
        <div className="top-gap">
          <Link className="button ghost" to="/control">
            查看控制页
          </Link>
        </div>
      </PageSection>
    </section>
  );
}

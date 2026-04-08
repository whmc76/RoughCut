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
  const summaryCards = [
    {
      label: "执行链路",
      value: `${getProviderLabel(activeReasoningProvider)} · ${getSearchSummary(workspace.form)}`,
      detail: `推理 ${getProviderLabel(activeReasoningProvider)}，输出 ${outputDir}`,
    },
    {
      label: "包装策略",
      value: `复核间隔 ${packagingReviewGap.toFixed(2)} · 最低分 ${packagingMinScore.toFixed(2)} · 术语 ${glossaryThreshold.toFixed(2)}`,
      detail: "包装和术语阈值已经并入本页的质量章节",
      action: (
        <Link className="button ghost" to="/packaging">
          打开包装页
        </Link>
      ),
    },
    {
      label: "记忆与词表",
      value: "记忆统计 · 术语维护",
      detail: "反馈闭环留在记忆页，词条编辑留在词表页",
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
      label: "维护入口",
      value: "Control",
      detail: "服务状态和停机动作只保留为次级入口",
      action: (
        <Link className="button ghost" to="/control">
          打开 Control
        </Link>
      ),
    },
  ];
  const automationSummary = [
    `${String(workspace.form.avatar_provider ?? "未设置")} + ${String(workspace.form.voice_provider ?? "未设置")}`,
    telegramReviewEnabled ? "Telegram 审核已启用" : "Telegram 审核关闭",
    telegramAgentEnabled ? "Telegram Agent 已启用" : "Telegram Agent 关闭",
  ].join(" · ");
  const environmentSummary = [
    `推理 ${getProviderLabel(activeReasoningProvider)}`,
    getSearchSummary(workspace.form),
    `输出 ${outputDir}`,
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
        eyebrow={t("settings.page.eyebrow")}
        title={t("settings.page.title")}
        description={t("settings.page.description")}
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

      <section className="settings-architecture-deck">
        <div className="settings-architecture-lead">
          <div className="page-eyebrow">概览</div>
          <h3>当前设置面</h3>
          <p>先看执行链路、包装策略、记忆词表和维护入口，再进入下面的配置章节。</p>
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
        eyebrow="Core"
        title="核心链路与 Provider"
        description="先决定转写、推理和搜索如何跑，再直接看到每个 Provider 的状态、凭据来源和检测结果。"
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
        eyebrow="Quality"
        title="输出、术语与复跑"
        description="把审核阈值、包装复核、术语确认和低分复跑放在同一章，避免和 Provider 配置相互干扰。"
      >
        <QualitySettingsPanel
          form={workspace.form}
          config={workspace.config.data}
          onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
        />
      </PageSection>

      <PageSection
        className="settings-stage settings-stage-automation settings-stage-automation-grid"
        eyebrow="Automation"
        title="扩展与自动化"
        description="运行环境、数字人和 Telegram/Agent 放在后段，但保持语义明确，不再用一个大而空的接入模块承载。"
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
              <PanelHeader title="数字人与配音能力" description={environmentSummary} />
              <CreativeSettingsPanel
                form={workspace.form}
                config={workspace.config.data}
                runtimeEnvironment={workspace.runtimeEnvironment.data}
                options={workspace.options.data}
                onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
              />
            </section>
            <section className="settings-extension-shell settings-extension-shell-bot">
              <PanelHeader title="Telegram 与 Agent 自动化" description={automationSummary} />
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
        eyebrow="维护"
        title="相关页面与系统控制"
        description="包装、记忆和词表仍保留独立页面，Control 只作为次级维护入口。"
      >
        <div className="settings-link-grid">
          <article className="settings-command-card">
            <span className="settings-overview-label">包装素材</span>
            <strong>策略与素材池</strong>
            <div className="muted">包装页面继续管理素材池，但它的默认策略由本页的质量章节控制。</div>
            <div className="top-gap">
              <Link className="button ghost" to="/packaging">
                查看包装页
              </Link>
            </div>
          </article>
          <article className="settings-command-card">
            <span className="settings-overview-label">行为记忆</span>
            <strong>纠错统计与偏好</strong>
            <div className="muted">记忆页面继续查看长期偏差，设置页只保留它的入口和上下文。</div>
            <div className="top-gap">
              <Link className="button ghost" to="/memory">
                查看记忆页
              </Link>
            </div>
          </article>
          <article className="settings-command-card">
            <span className="settings-overview-label">术语词表</span>
            <strong>术语维护与导入</strong>
            <div className="muted">词表页继续编辑词条，本页只保留自动接受阈值和入口。</div>
            <div className="top-gap">
              <Link className="button ghost" to="/glossary">
                查看词表页
              </Link>
            </div>
          </article>
        </div>
        <div className="top-gap">
          <Link className="button ghost" to="/control">
            查看 Control
          </Link>
        </div>
      </PageSection>
    </section>
  );
}

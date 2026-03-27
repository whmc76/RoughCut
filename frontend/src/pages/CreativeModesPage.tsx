import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useI18n } from "../i18n";
import type { CreativeModeDefinition } from "../types";

export function CreativeModesPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: ["config-options", "creative-modes"], queryFn: api.getConfigOptions });
  const config = useQuery({ queryKey: ["config", "creative-modes"], queryFn: api.getConfig });
  const saveEnhancementModes = useMutation({
    mutationFn: (modes: string[]) => api.patchConfig({ default_job_enhancement_modes: modes }),
    onSuccess: (data) => {
      queryClient.setQueryData(["config", "creative-modes"], data);
      queryClient.setQueryData(["config"], data);
      void queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
  const catalog = options.data?.creative_mode_catalog;
  const activeEnhancementModes = config.data?.default_job_enhancement_modes ?? [];

  const toggleEnhancementMode = (modeKey: string) => {
    const nextModes = activeEnhancementModes.includes(modeKey)
      ? activeEnhancementModes.filter((item) => item !== modeKey)
      : [...activeEnhancementModes, modeKey];
    saveEnhancementModes.mutate(nextModes);
  };

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("creative.page.eyebrow")}
        title={t("creative.page.title")}
        description={t("creative.page.description")}
        summary={[
          { label: "先分清类型", value: "主流程模式 / 增强能力", detail: "工作流决定产出路径，增强项决定附加能力" },
          { label: "重点决策", value: "只激活真正常用的增强项", detail: "默认配置越少，任务创建越稳定" },
          { label: "阅读方式", value: "先看输出方式再看供应商", detail: "避免只看名字，不清楚它实际影响什么" },
        ]}
        actions={<Link className="button primary" to="/creator-profiles">{t("creative.page.openCreatorProfiles")}</Link>}
      />

      {!catalog && <section className="panel">{t("creative.page.loading")}</section>}

      {catalog && (
        <>
          <PageSection
            eyebrow="主流程"
            title="决定任务的基本产出路径"
            description="主流程模式决定任务按什么方式生成主成片，属于任务创建时的第一决策。"
          >
            <section className="panel">
              <PanelHeader title={t("creative.section.workflow")} description={t("creative.section.workflowDescription")} />
              <div className="mode-card-grid">
                {catalog.workflow_modes.map((mode) => (
                  <CreativeModeCard key={mode.key} mode={mode} />
                ))}
              </div>
            </section>
          </PageSection>

          <PageSection
            eyebrow="增强"
            title="补充默认增强能力"
            description="增强项只在确实常用时才建议激活，避免每个新任务默认挂太多非必要能力。"
          >
            <section className="panel">
              <PanelHeader title={t("creative.section.enhancement")} description={t("creative.section.enhancementDescription")} />
              <div className="mode-card-grid">
                {catalog.enhancement_modes.map((mode) => (
                  <CreativeModeCard
                    key={mode.key}
                    mode={mode}
                    active={activeEnhancementModes.includes(mode.key)}
                    saving={saveEnhancementModes.isPending}
                    onToggleActive={() => toggleEnhancementMode(mode.key)}
                  />
                ))}
              </div>
            </section>
          </PageSection>
        </>
      )}
    </section>
  );
}

type CreativeModeCardProps = {
  mode: CreativeModeDefinition;
  active?: boolean;
  saving?: boolean;
  onToggleActive?: () => void;
};

function CreativeModeCard({ mode, active = false, saving = false, onToggleActive }: CreativeModeCardProps) {
  const { t } = useI18n();
  const outputMode = describeModeOutput(mode);

  return (
    <article className="mode-card">
      <div className="mode-card-header">
        <div>
          <strong>{mode.title}</strong>
          <div className="muted compact-top">{mode.tagline}</div>
        </div>
        <span className={`mode-chip ${mode.status === "planned" ? "planned" : ""}`}>
          {mode.status === "planned" ? t("creative.status.planned") : t("creative.status.active")}
        </span>
      </div>
      <p className="muted">{mode.summary}</p>
      <div className="mode-card-section">
        <span className="stat-label">{t("creative.card.suitableFor")}</span>
        <div className="mode-chip-list compact-top">
          {mode.suitable_for.map((item) => (
            <span key={item} className="mode-chip subtle">
              {item}
            </span>
          ))}
        </div>
      </div>
      <div className="mode-card-section">
        <span className="stat-label">{t("creative.card.pipeline")}</span>
        <div className="list-stack compact-top">
          {mode.pipeline_outline.map((item, index) => (
            <div key={`${mode.key}-${index}`} className="mode-list-item">
              <span className="mode-list-index">{index + 1}</span>
              <span>{item}</span>
            </div>
          ))}
        </div>
      </div>
      {mode.providers?.length ? (
        <div className="mode-card-section">
          <span className="stat-label">{t("creative.card.providers")}</span>
          <div className="mode-chip-list compact-top">
            {mode.providers.map((item) => (
              <span key={item} className="mode-chip subtle">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mode-card-section">
        <span className="stat-label">{t("creative.card.delivery")}</span>
        <div className="muted compact-top">{mode.delivery_scope || mode.default_delivery || "—"}</div>
      </div>
      <div className="mode-card-section">
        <span className="stat-label">输出方式</span>
        <div className="muted compact-top">{outputMode}</div>
      </div>
      {mode.kind === "enhancement" ? (
        <div className="toolbar">
          <button className={active ? "button primary" : "button ghost"} type="button" disabled={saving} onClick={onToggleActive}>
            {active ? "已激活到配置" : saving ? "保存中..." : "激活到配置"}
          </button>
        </div>
      ) : null}
    </article>
  );
}

function describeModeOutput(mode: CreativeModeDefinition): string {
  if (mode.kind === "workflow") {
    if (mode.key === "standard_edit") return "直接输出主成片。";
    if (mode.key === "long_text_to_video") return "规划中，当前还没有实际输出。";
    return "按工作流直接产出主输出。";
  }

  if (mode.key === "avatar_commentary") return "叠加到主成片，可形成含数字人的增强版输出。";
  if (mode.key === "ai_director") return "改写解说与配音后回写主流程，影响主成片输出。";
  if (mode.key === "multilingual_translation") return "当前产出字幕翻译等辅助产物，不单独导出新成片。";
  if (mode.key === "auto_review") return "只改变审核放行方式，不产生额外视频输出。";
  if (mode.key === "multi_platform_adaptation") return "当前主要写入平台适配配置，尚未自动分叉导出多平台成片。";
  if (mode.key === "ai_effects") return "当前主要完成配置挂载，暂未接入稳定的视频特效输出。";

  return "当前输出方式待补充。";
}

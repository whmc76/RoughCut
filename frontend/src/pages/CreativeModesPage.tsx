import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { AvatarMaterialPanel } from "../features/avatarMaterials/AvatarMaterialPanel";
import { useI18n } from "../i18n";

export function CreativeModesPage() {
  const { t } = useI18n();
  const options = useQuery({ queryKey: ["config-options", "creative-modes"], queryFn: api.getConfigOptions });
  const catalog = options.data?.creative_mode_catalog;

  return (
    <section>
      <PageHeader
        eyebrow={t("creative.page.eyebrow")}
        title={t("creative.page.title")}
        description={t("creative.page.description")}
      />

      {!catalog && <section className="panel">{t("creative.page.loading")}</section>}

      {catalog && (
        <>
          <section className="panel">
            <PanelHeader title={t("creative.section.workflow")} description={t("creative.section.workflowDescription")} />
            <div className="mode-card-grid">
              {catalog.workflow_modes.map((mode) => (
                <CreativeModeCard key={mode.key} mode={mode} />
              ))}
            </div>
          </section>

          <section className="panel top-gap">
            <PanelHeader title={t("creative.section.enhancement")} description={t("creative.section.enhancementDescription")} />
            <div className="mode-card-grid">
              {catalog.enhancement_modes.map((mode) => (
                <CreativeModeCard key={mode.key} mode={mode} />
              ))}
            </div>
          </section>

          <AvatarMaterialPanel />
        </>
      )}
    </section>
  );
}

type CreativeModeCardProps = {
  mode: {
    key: string;
    title: string;
    tagline: string;
    summary: string;
    status: string;
    suitable_for: string[];
    pipeline_outline: string[];
    providers?: string[];
    delivery_scope?: string;
    default_delivery?: string;
  };
};

function CreativeModeCard({ mode }: CreativeModeCardProps) {
  const { t } = useI18n();

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
    </article>
  );
}

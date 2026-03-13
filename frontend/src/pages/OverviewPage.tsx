import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useI18n } from "../i18n";
import { StatCard } from "../components/ui/StatCard";
import { useOverviewWorkspace } from "../features/overview/useOverviewWorkspace";
import { formatDate, statusLabel } from "../utils";

export function OverviewPage() {
  const { t } = useI18n();
  const workspace = useOverviewWorkspace();

  return (
    <section>
      <PageHeader eyebrow={t("overview.page.eyebrow")} title={t("overview.page.title")} description={t("overview.page.description")} />

      <div className="stats-grid">
        <StatCard label={t("overview.stats.jobs")} value={workspace.stats.jobs} />
        <StatCard label={t("overview.stats.running")} value={workspace.stats.running} />
        <StatCard label={t("overview.stats.watchRoots")} value={workspace.stats.watchRoots} />
        <StatCard label={t("overview.stats.glossary")} value={workspace.stats.glossary} />
      </div>

      <div className="panel-grid two-up">
        <section className="panel">
          <PanelHeader title={t("overview.recent.title")} description={t("overview.recent.description")} actions={<Link className="text-link" to="/jobs">{t("overview.recent.viewAll")}</Link>} />
          <div className="list-stack">
            {workspace.jobs.isLoading && <EmptyState message={t("overview.recent.loading")} />}
            {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
            {workspace.jobs.data?.slice(0, 6).map((job) => (
              <article key={job.id} className="list-card">
                <div>
                  <div className="row-title">{job.source_name}</div>
                  <div className="muted">{job.content_summary || job.content_subject || t("overview.recent.noSummary")}</div>
                </div>
                <div className="row-meta">
                  <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                  <span>{formatDate(job.updated_at)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <PanelHeader title={t("overview.services.title")} description={t("overview.services.description")} actions={<Link className="text-link" to="/control">{t("overview.services.open")}</Link>} />
          <div className="service-grid">
            {Object.entries(workspace.services.data?.services ?? {}).map(([key, online]) => (
              <article key={key} className="service-card">
                <span>{key}</span>
                <strong className={online ? "status-ok" : "status-off"}>{online ? t("overview.services.online") : t("overview.services.offline")}</strong>
              </article>
            ))}
            {!workspace.services.data && !workspace.services.isLoading && <EmptyState message={t("overview.services.empty")} />}
          </div>
        </section>
      </div>
    </section>
  );
}

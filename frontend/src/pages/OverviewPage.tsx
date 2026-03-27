import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useI18n } from "../i18n";
import { StatCard } from "../components/ui/StatCard";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
import { JobsUsageTrendPanel } from "../features/jobs/JobsUsageTrendPanel";
import { useOverviewWorkspace } from "../features/overview/useOverviewWorkspace";
import { formatDate, statusLabel } from "../utils";

function renderRuntimeTone(status: string | undefined) {
  return status === "ready" || status === "held" || status === "free" ? "status-ok" : "status-off";
}

export function OverviewPage() {
  const { t } = useI18n();
  const workspace = useOverviewWorkspace();
  const runtime = workspace.services.data?.runtime;

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("overview.page.eyebrow")}
        title={t("overview.page.title")}
        description={t("overview.page.description")}
        summary={[
          { label: "先看全局", value: "任务、服务、用量", detail: "先确认健康度，再进入具体页面" },
          { label: "配置基线", value: "统一剪辑配置", detail: "顶部切换会影响后续新任务默认参数" },
          { label: "常用入口", value: "最近任务与服务状态", detail: "适合快速判断下一步该去哪一页" },
        ]}
      />
      <PageSection
        eyebrow="运行"
        title="先确认系统当前状态"
        description="这一段只负责判断今天系统是否可用，以及新任务会继承哪套配置。"
      >
        <ConfigProfileSwitcher />

        <div className="stats-grid">
          <StatCard label={t("overview.stats.jobs")} value={workspace.stats.jobs} />
          <StatCard label={t("overview.stats.running")} value={workspace.stats.running} />
          <StatCard label={t("overview.stats.watchRoots")} value={workspace.stats.watchRoots} />
          <StatCard label={t("overview.stats.glossary")} value={workspace.stats.glossary} />
        </div>

        {workspace.usageSummary.data && (
          <>
            <div className="stats-grid compact">
              <StatCard label={t("jobs.summary.totalTokens")} value={workspace.usageSummary.data.total_tokens.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.totalCalls")} value={workspace.usageSummary.data.total_calls.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.savedTokens")} value={workspace.usageSummary.data.cache.saved_total_tokens.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.cacheHitRate")} value={`${Math.round((workspace.usageSummary.data.cache.hit_rate || 0) * 100)}%`} compact />
            </div>

            <JobsUsageTrendPanel
              title={t("jobs.summary.trendTitle")}
              description={t("jobs.summary.trendDescription")}
              trend={workspace.usageTrend.data}
              actions={
                <div className="usage-trend-actions">
                  <div className="mode-chip-list">
                    {[7, 30].map((days) => (
                      <button
                        key={days}
                        className={`mode-chip filter-chip ${workspace.usageTrendDays === days ? "selected" : ""}`}
                        onClick={() => workspace.setUsageTrendDays(days)}
                      >
                        {days}d
                      </button>
                    ))}
                  </div>
                  <div className="mode-chip-list">
                    {[
                      { value: "all", label: t("jobs.summary.allDimensions") },
                      { value: "step", label: t("jobs.summary.dimensionSteps") },
                      { value: "model", label: t("jobs.summary.dimensionModels") },
                      { value: "provider", label: t("jobs.summary.dimensionProviders") },
                    ].map((dimension) => (
                      <button
                        key={dimension.value}
                        className={`mode-chip filter-chip ${workspace.usageTrendFocusType === dimension.value ? "selected" : ""}`}
                        onClick={() => workspace.setUsageTrendFocusType(dimension.value)}
                      >
                        {dimension.label}
                      </button>
                    ))}
                  </div>
                </div>
              }
            />
          </>
        )}
      </PageSection>

      <PageSection
        eyebrow="入口"
        title="从这里继续进入具体工作"
        description="最近任务和服务状态保留在一屏内，方便快速判断下一步应该进任务页还是系统页。"
      >
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
              {runtime?.readiness_status && (
                <article className="service-card">
                  <span>runtime ready</span>
                  <strong className={renderRuntimeTone(runtime.readiness_status)}>{runtime.readiness_status}</strong>
                </article>
              )}
              {runtime?.orchestrator_lock?.status && (
                <article className="service-card">
                  <span>orchestrator lock</span>
                  <strong className={renderRuntimeTone(runtime.orchestrator_lock.status)}>{runtime.orchestrator_lock.status}</strong>
                </article>
              )}
              {!workspace.services.data && !workspace.services.isLoading && <EmptyState message={t("overview.services.empty")} />}
            </div>
            {runtime && (
              <div className="top-gap muted">
                {runtime.orchestrator_lock?.detail ?? "未返回 orchestrator lock 详情。"}
              </div>
            )}
          </section>
        </div>
      </PageSection>
    </section>
  );
}

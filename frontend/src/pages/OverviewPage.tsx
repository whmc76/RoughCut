import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useI18n } from "../i18n";
import { StatCard } from "../components/ui/StatCard";
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
  const activeJobs = (workspace.jobs.data ?? []).filter((job) => job.status === "running" || job.status === "processing" || job.status === "needs_review").slice(0, 3);
  const recentRoots = workspace.watchRoots.data?.slice(0, 3) ?? [];
  const serviceEntries = Object.entries(workspace.services.data?.services ?? {});
  const usageTrendStepOptions = workspace.usageSummary.data?.top_steps.slice(0, 5) ?? [];
  const usageTrendModelOptions = workspace.usageSummary.data?.top_models.slice(0, 5) ?? [];
  const usageTrendProviderOptions = workspace.usageSummary.data?.top_providers.slice(0, 5) ?? [];
  const usageTrendFocusOptions =
    workspace.usageTrendFocusType === "step"
      ? usageTrendStepOptions.map((step) => ({ name: step.step_name, label: step.label }))
      : workspace.usageTrendFocusType === "model"
        ? usageTrendModelOptions.map((model) => ({ name: model.model, label: model.model }))
        : workspace.usageTrendFocusType === "provider"
          ? usageTrendProviderOptions.map((provider) => ({ name: provider.provider, label: provider.provider }))
          : [];

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("overview.page.eyebrow")}
        title={t("overview.page.title")}
        description={t("overview.page.description")}
      />
      <PageSection eyebrow={t("overview.triage.eyebrow")} title={t("overview.triage.title")}>
        <div className="panel-grid two-up">
          <section className="panel">
            <PanelHeader
              title={t("overview.triage.jobs.title")}
              description={t("overview.triage.jobs.description")}
              actions={<Link className="text-link" to="/jobs">{t("overview.triage.jobs.cta")}</Link>}
            />
            <div className="stats-grid compact">
              <StatCard label={t("overview.stats.jobs")} value={workspace.stats.jobs} compact />
              <StatCard label={t("overview.stats.running")} value={workspace.stats.running} compact />
              <StatCard label={t("overview.stats.watchRoots")} value={workspace.stats.watchRoots} compact />
              <StatCard label={t("overview.stats.glossary")} value={workspace.stats.glossary} compact />
            </div>
            <div className="list-stack">
              {workspace.jobs.isLoading && <EmptyState message={t("overview.recent.loading")} />}
              {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
              {!workspace.jobs.isLoading && !workspace.jobs.isError && activeJobs.length === 0 ? (
                <EmptyState message={t("overview.recent.noSummary")} />
              ) : null}
              {activeJobs.map((job) => (
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

          <div className="list-stack">
            <section className="panel">
              <PanelHeader
                title={t("overview.triage.watchRoots.title")}
                description={t("overview.triage.watchRoots.description")}
                actions={<Link className="text-link" to="/watch-roots">{t("overview.triage.watchRoots.cta")}</Link>}
              />
              <div className="stats-grid compact">
                <StatCard label={t("overview.stats.watchRoots")} value={workspace.stats.watchRoots} compact />
                <StatCard label={t("overview.stats.glossary")} value={workspace.stats.glossary} compact />
              </div>
              <div className="list-stack">
                {recentRoots.length ? (
                  recentRoots.map((root) => (
                    <article key={root.id} className="list-card">
                      <div>
                        <div className="row-title">{root.path}</div>
                        <div className="muted">{root.workflow_template || "—"}</div>
                      </div>
                      <div className="row-meta">
                        <span className={`status-chip ${root.enabled ? "done" : "cancelled"}`}>{root.enabled ? "enabled" : "disabled"}</span>
                        <span>{root.scan_mode}</span>
                      </div>
                    </article>
                  ))
                ) : (
                  <EmptyState message={t("watch.list.empty")} />
                )}
              </div>
            </section>

            <section className="panel">
              <PanelHeader
                title={t("overview.triage.system.title")}
                description={t("overview.triage.system.description")}
                actions={<Link className="text-link" to="/control">{t("overview.triage.system.cta")}</Link>}
              />
              <div className="service-grid">
                {serviceEntries.map(([key, online]) => (
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
              {runtime ? <div className="top-gap muted">{runtime.orchestrator_lock?.detail ?? "未返回 orchestrator lock 详情。"}</div> : null}
            </section>
          </div>
        </div>
      </PageSection>

      {workspace.usageSummary.data && (
        <PageSection eyebrow={t("overview.signals.eyebrow")} title={t("overview.signals.title")}>
          <>
            <div className="stats-grid compact">
              <StatCard label={t("jobs.summary.totalTokens")} value={workspace.usageSummary.data.total_tokens.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.totalCalls")} value={workspace.usageSummary.data.total_calls.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.savedTokens")} value={workspace.usageSummary.data.cache.saved_total_tokens.toLocaleString()} compact />
              <StatCard label={t("jobs.summary.cacheHitRate")} value={`${Math.round((workspace.usageSummary.data.cache.hit_rate || 0) * 100)}%`} compact />
            </div>

            <div className="panel-grid two-up">
              <section className="panel">
                <PanelHeader title={t("jobs.summary.topSteps")} description={t("jobs.summary.topStepsDescription")} />
                <div className="timeline-list">
                  {workspace.usageSummary.data.top_steps.slice(0, 5).map((step) => (
                    <div key={step.step_name} className="timeline-item">
                      <div className="toolbar">
                        <strong>{step.label}</strong>
                        <span className="status-pill pending">{step.total_tokens.toLocaleString()}</span>
                      </div>
                      <div className="muted">
                        {t("jobs.summary.stepBreakdown")}
                        {`: ${step.jobs.toLocaleString()} / ${step.calls.toLocaleString()} / ${step.cache_hits.toLocaleString()}`}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <PanelHeader title={t("jobs.summary.cachePanel")} description={t("jobs.summary.cachePanelDescription")} />
                <div className="stats-grid compact">
                  <StatCard label={t("jobs.summary.consideredJobs")} value={workspace.usageSummary.data.job_count.toLocaleString()} compact />
                  <StatCard label={t("jobs.summary.jobsWithTelemetry")} value={workspace.usageSummary.data.jobs_with_telemetry.toLocaleString()} compact />
                  <StatCard label={t("jobs.summary.avoidedCalls")} value={workspace.usageSummary.data.cache.avoided_calls.toLocaleString()} compact />
                  <StatCard label={t("jobs.summary.savedTokensCoverage")} value={`${Math.round((workspace.usageSummary.data.cache.saved_tokens_hit_rate || 0) * 100)}%`} compact />
                </div>
                <div className="timeline-list">
                  <div className="timeline-item">
                    <strong>{t("jobs.summary.cacheHits")}</strong>
                    <span>{workspace.usageSummary.data.cache.hits.toLocaleString()}</span>
                  </div>
                  <div className="timeline-item">
                    <strong>{t("jobs.summary.cacheMisses")}</strong>
                    <span>{workspace.usageSummary.data.cache.misses.toLocaleString()}</span>
                  </div>
                  <div className="timeline-item">
                    <strong>{t("jobs.summary.stepsWithHits")}</strong>
                    <span>{workspace.usageSummary.data.cache.steps_with_hits.toLocaleString()}</span>
                  </div>
                  <div className="timeline-item">
                    <strong>{t("jobs.summary.savedTokens")}</strong>
                    <span>{workspace.usageSummary.data.cache.saved_total_tokens.toLocaleString()}</span>
                  </div>
                  <div className="timeline-item">
                    <strong>{t("jobs.summary.baselineHits")}</strong>
                    <span>{workspace.usageSummary.data.cache.hits_with_usage_baseline.toLocaleString()}</span>
                  </div>
                </div>
              </section>
            </div>

            <div className="panel-grid two-up">
              <section className="panel">
                <PanelHeader title={t("jobs.summary.topModels")} description={t("jobs.summary.topModelsDescription")} />
                <div className="timeline-list">
                  {workspace.usageSummary.data.top_models.slice(0, 5).map((model) => (
                    <div key={model.model} className="timeline-item">
                      <div className="toolbar">
                        <strong>{model.model}</strong>
                        <span className="status-pill pending">{model.total_tokens.toLocaleString()}</span>
                      </div>
                      <div className="muted">
                        {model.provider || "—"}
                        {` / ${model.calls.toLocaleString()} / ${model.jobs.toLocaleString()}`}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <PanelHeader title={t("jobs.summary.topProviders")} description={t("jobs.summary.topProvidersDescription")} />
                <div className="timeline-list">
                  {workspace.usageSummary.data.top_providers.slice(0, 5).map((provider) => (
                    <div key={provider.provider} className="timeline-item">
                      <div className="toolbar">
                        <strong>{provider.provider}</strong>
                        <span className="status-pill pending">{provider.total_tokens.toLocaleString()}</span>
                      </div>
                      <div className="muted">{`${provider.calls.toLocaleString()} / ${provider.jobs.toLocaleString()}`}</div>
                    </div>
                  ))}
                </div>
              </section>
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
                        onClick={() => {
                          workspace.setUsageTrendFocusType(dimension.value);
                          workspace.setUsageTrendFocusName("");
                        }}
                      >
                        {dimension.label}
                      </button>
                    ))}
                  </div>
                  <div className="mode-chip-list">
                    <button
                      className={`mode-chip filter-chip ${workspace.usageTrendFocusName === "" ? "selected" : ""}`}
                      onClick={() => workspace.setUsageTrendFocusName("")}
                    >
                      {workspace.usageTrendFocusType === "model"
                        ? t("jobs.summary.allModels")
                        : workspace.usageTrendFocusType === "provider"
                          ? t("jobs.summary.allProviders")
                          : t("jobs.summary.allSteps")}
                    </button>
                    {usageTrendFocusOptions.map((option) => (
                      <button
                        key={option.name}
                        className={`mode-chip filter-chip ${workspace.usageTrendFocusName === option.name ? "selected" : ""}`}
                        onClick={() => workspace.setUsageTrendFocusName(option.name)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              }
            />
          </>
        </PageSection>
      )}
    </section>
  );
}

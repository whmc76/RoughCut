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
  const blockedServices = serviceEntries.filter(([, online]) => !online);
  const reviewJobs = activeJobs.filter((job) => job.status === "needs_review");
  const disabledRoots = recentRoots.filter((root) => !root.enabled);
  const mastheadTitle = blockedServices.length
    ? "需要先处理运行问题"
    : reviewJobs.length
      ? `${reviewJobs.length} 个任务待审核`
      : disabledRoots.length
        ? `${disabledRoots.length} 个目录待处理`
        : "当前运行正常";
  const deckLead = blockedServices.length
    ? t("overview.deck.runtimeIssue")
    : reviewJobs.length
      ? t("overview.deck.reviewReady")
      : disabledRoots.length
        ? t("overview.deck.watchReady")
        : t("overview.deck.runtimeReady");
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
    <section className="page-stack overview-page">
      <PageHeader title={t("overview.page.title")} description={t("overview.page.description")} />
      <section className="overview-masthead" data-testid="overview-masthead">
        <div className="overview-masthead-copy">
          <h3>{mastheadTitle}</h3>
          <p>{deckLead}</p>
        </div>
        <div className="overview-masthead-signals">
          <article className="overview-masthead-signal">
            <span>{t("overview.deck.queueLabel")}</span>
            <strong>{workspace.stats.jobs}</strong>
          </article>
          <article className="overview-masthead-signal">
            <span>{t("overview.deck.reviewLabel")}</span>
            <strong>{reviewJobs.length}</strong>
          </article>
          <article className="overview-masthead-signal">
            <span>{t("overview.deck.watchLabel")}</span>
            <strong>{workspace.stats.watchRoots}</strong>
          </article>
          <article className="overview-masthead-signal">
            <span>{t("overview.deck.runtimeLabel")}</span>
            <strong>{serviceEntries.length}</strong>
          </article>
        </div>
      </section>

      <section className="overview-decision-surface" data-testid="overview-decision-surface">
        <div className="overview-activity-feed" data-testid="overview-activity-feed">
          <div className="overview-surface-head">
            <span>{t("overview.deck.actions")}</span>
            <strong>{reviewJobs.length ? reviewJobs.length : activeJobs.length}</strong>
          </div>
          {workspace.jobs.isLoading && <EmptyState message={t("overview.recent.loading")} />}
          {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
          {!workspace.jobs.isLoading && !workspace.jobs.isError && activeJobs.length === 0 ? (
            <EmptyState message={t("overview.deck.empty")} />
          ) : null}
          {activeJobs.map((job, index) => (
            <article key={job.id} className="overview-job-row" data-testid="overview-job-row">
              <div className="overview-job-row-index">{`${index + 1}`.padStart(2, "0")}</div>
              <div className="overview-job-row-copy">
                <strong>{job.source_name}</strong>
                <p>{job.content_summary || job.content_subject || t("overview.recent.noSummary")}</p>
              </div>
              <div className="overview-job-row-meta">
                <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                <span>{formatDate(job.updated_at)}</span>
              </div>
            </article>
          ))}
        </div>

        <aside className="overview-action-rail" data-testid="overview-action-rail">
          <section className="overview-action-block">
            <div className="overview-surface-head">
              <span>快速入口</span>
              <strong>{reviewJobs.length ? `${reviewJobs.length} 待处理` : "查看页面"}</strong>
            </div>
            <Link className="overview-action-link" to="/jobs">
              <span className="overview-action-index">01</span>
              <div>
                <strong>{t("overview.focus.jobs.title")}</strong>
                <p>{t("overview.triage.jobs.description")}</p>
              </div>
            </Link>
            <Link className="overview-action-link" to="/watch-roots">
              <span className="overview-action-index">02</span>
              <div>
                <strong>{t("overview.focus.watch.title")}</strong>
                <p>{t("overview.triage.watchRoots.description")}</p>
              </div>
            </Link>
            <Link className="overview-action-link" to="/control">
              <span className="overview-action-index">03</span>
              <div>
                <strong>{t("overview.focus.runtime.title")}</strong>
                <p>{t("overview.triage.system.description")}</p>
              </div>
            </Link>
          </section>

          <section className="overview-runtime-panel">
            <div className="overview-surface-head">
              <span>运行状态</span>
              <strong>{serviceEntries.length}</strong>
            </div>
            {serviceEntries.length ? (
              <div className="overview-runtime-list">
                {serviceEntries.map(([key, online]) => (
                  <article key={key} className="overview-runtime-row">
                    <span>{key}</span>
                    <strong className={online ? "status-ok" : "status-off"}>{online ? t("overview.services.online") : t("overview.services.offline")}</strong>
                  </article>
                ))}
                {runtime?.readiness_status ? (
                  <article className="overview-runtime-row">
                    <span>runtime ready</span>
                    <strong className={renderRuntimeTone(runtime.readiness_status)}>{runtime.readiness_status}</strong>
                  </article>
                ) : null}
                {runtime?.orchestrator_lock?.status ? (
                  <article className="overview-runtime-row">
                    <span>orchestrator lock</span>
                    <strong className={renderRuntimeTone(runtime.orchestrator_lock.status)}>{runtime.orchestrator_lock.status}</strong>
                  </article>
                ) : null}
              </div>
            ) : !workspace.services.isLoading ? (
              <EmptyState message={t("overview.focus.runtime.empty")} />
            ) : null}
            {runtime ? <p className="overview-runtime-note">{runtime.orchestrator_lock?.detail ?? t("overview.focus.runtime.lock")}</p> : null}
          </section>
        </aside>
      </section>

      <section className="overview-analysis-band" data-testid="overview-analysis-band">
        <section className="overview-analysis-column">
          <PanelHeader
            title={t("overview.focus.watch.title")}
            description={t("overview.focus.watch.description")}
            actions={<Link className="text-link" to="/watch-roots">{t("overview.triage.watchRoots.cta")}</Link>}
          />
          <div className="overview-analysis-list">
            {recentRoots.length ? (
              recentRoots.map((root) => (
                <article key={root.id} className="overview-analysis-row">
                  <div className="overview-focus-copy">
                    <strong>{root.path}</strong>
                    <p>{root.workflow_template || "—"}</p>
                  </div>
                  <div className="overview-focus-meta">
                    <span className={`status-chip ${root.enabled ? "done" : "cancelled"}`}>{root.enabled ? "enabled" : "disabled"}</span>
                    <span>{root.scan_mode}</span>
                  </div>
                </article>
              ))
            ) : (
              <EmptyState message={t("overview.focus.watch.empty")} />
            )}
          </div>
        </section>

        <section className="overview-analysis-column">
          <PanelHeader
            title="最近任务"
            description="只保留最新需要看的任务。"
            actions={<Link className="text-link" to="/jobs">{t("overview.triage.jobs.cta")}</Link>}
          />
          <div className="overview-analysis-list">
            {activeJobs.length ? (
              activeJobs.map((job) => (
                <article key={job.id} className="overview-analysis-row">
                  <div className="overview-focus-copy">
                    <strong>{job.source_name}</strong>
                    <p>{job.content_summary || job.content_subject || t("overview.recent.noSummary")}</p>
                  </div>
                  <div className="overview-focus-meta">
                    <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                    <span>{formatDate(job.updated_at)}</span>
                  </div>
                </article>
              ))
            ) : (
              <EmptyState message={t("overview.focus.jobs.empty")} />
            )}
          </div>
        </section>
      </section>

      {workspace.usageSummary.data && (
        <PageSection className="overview-telemetry-band" title={t("overview.signals.title")}>
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

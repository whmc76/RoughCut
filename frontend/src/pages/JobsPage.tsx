import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { StatCard } from "../components/ui/StatCard";
import { useI18n } from "../i18n";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobDetailModal } from "../features/jobs/JobDetailModal";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobsUsageTrendPanel } from "../features/jobs/JobsUsageTrendPanel";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import { useJobWorkspace } from "../features/jobs/useJobWorkspace";

export function JobsPage() {
  const { t } = useI18n();
  const workspace = useJobWorkspace();
  const usageTrendStepOptions = workspace.usageSummary.data?.top_steps.slice(0, 5) ?? [];
  const usageTrendModelOptions = workspace.usageSummary.data?.top_models.slice(0, 5) ?? [];
  const usageTrendProviderOptions = workspace.usageSummary.data?.top_providers.slice(0, 5) ?? [];
  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const channelProfileOptions = workspace.options.data?.channel_profiles ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];
  const usageTrendFocusOptions =
    workspace.usageTrendFocusType === "step"
      ? usageTrendStepOptions.map((step) => ({ name: step.step_name, label: step.label }))
      : workspace.usageTrendFocusType === "model"
        ? usageTrendModelOptions.map((model) => ({ name: model.model, label: model.model }))
        : workspace.usageTrendFocusType === "provider"
          ? usageTrendProviderOptions.map((provider) => ({ name: provider.provider, label: provider.provider }))
          : [];

  return (
    <section>
      <PageHeader
        eyebrow={t("jobs.page.eyebrow")}
        title={t("jobs.page.title")}
        description={t("jobs.page.description")}
        actions={
          <>
            <input className="input" value={workspace.keyword} onChange={(event) => workspace.setKeyword(event.target.value)} placeholder={t("jobs.page.searchPlaceholder")} />
            <button className="button ghost" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
          </>
        }
      />

      <JobUploadPanel
        upload={workspace.upload}
        languageOptions={languageOptions}
        channelProfileOptions={channelProfileOptions}
        workflowModeOptions={workflowModeOptions}
        enhancementOptions={enhancementOptions}
        onChange={workspace.setUpload}
        onSubmit={() => workspace.uploadJob.mutate()}
        isSubmitting={workspace.uploadJob.isPending}
      />

      {workspace.usageSummary.data && (
        <>
          <div className="stats-grid top-gap">
            <StatCard label={t("jobs.summary.totalTokens")} value={workspace.usageSummary.data.total_tokens.toLocaleString()} />
            <StatCard label={t("jobs.summary.totalCalls")} value={workspace.usageSummary.data.total_calls.toLocaleString()} />
            <StatCard label={t("jobs.summary.savedTokens")} value={workspace.usageSummary.data.cache.saved_total_tokens.toLocaleString()} />
            <StatCard
              label={t("jobs.summary.cacheHitRate")}
              value={`${Math.round((workspace.usageSummary.data.cache.hit_rate || 0) * 100)}%`}
            />
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

          <div className="top-gap panel-grid two-up">
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

          <div className="top-gap">
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
          </div>
        </>
      )}

      <div className="top-gap">
        <JobQueueTable
          jobs={workspace.filteredJobs}
          selectedJobId={workspace.selectedJobId}
          isLoading={workspace.jobs.isLoading}
          errorMessage={workspace.jobs.isError ? (workspace.jobs.error as Error).message : undefined}
          isOpeningFolder={workspace.openFolder.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          onSelect={workspace.setSelectedJobId}
          onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
          onCancel={(jobId) => workspace.cancelJob.mutate(jobId)}
          onRestart={(jobId) => workspace.restartJob.mutate(jobId)}
          onDelete={(jobId) => workspace.deleteJob.mutate(jobId)}
        />
      </div>

      <JobDetailModal
        open={Boolean(workspace.selectedJobId)}
        title={workspace.selectedJob?.source_name}
        onClose={() => workspace.setSelectedJobId(null)}
      >
        <JobDetailPanel
          className="detail-panel-modal"
          selectedJobId={workspace.selectedJobId}
          selectedJob={workspace.selectedJob}
          isLoading={workspace.detail.isLoading}
          activity={workspace.activity.data}
          report={workspace.report.data}
          tokenUsage={workspace.tokenUsage.data}
          timeline={workspace.timeline.data}
          contentProfile={workspace.contentProfile.data}
          config={workspace.config.data}
          options={workspace.options.data}
          packaging={workspace.packaging.data}
          avatarMaterials={workspace.avatarMaterials.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          reviewWorkflowMode={workspace.reviewWorkflowMode}
          reviewEnhancementModes={workspace.reviewEnhancementModes}
          reviewCopyStyle={workspace.reviewCopyStyle}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          onContentFieldChange={(field, value) => workspace.setContentDraft((prev) => ({ ...prev, [field]: value }))}
          onKeywordsChange={(value) =>
            workspace.setContentDraft((prev) => ({
              ...prev,
              keywords: value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            }))
          }
          onReviewWorkflowModeChange={workspace.setReviewWorkflowMode}
          onReviewEnhancementModesChange={workspace.setReviewEnhancementModes}
          onReviewCopyStyleChange={workspace.setReviewCopyStyle}
          onConfirmProfile={() => workspace.confirmProfile.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && workspace.cancelJob.mutate(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && workspace.restartJob.mutate(workspace.selectedJob.id)}
          onDelete={() => workspace.selectedJob && workspace.deleteJob.mutate(workspace.selectedJob.id)}
          onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        />
      </JobDetailModal>
    </section>
  );
}

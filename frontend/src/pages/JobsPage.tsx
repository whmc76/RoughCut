import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { StatCard } from "../components/ui/StatCard";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
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
    <section className="page-stack">
      <PageHeader
        eyebrow={t("jobs.page.eyebrow")}
        title={t("jobs.page.title")}
        description={t("jobs.page.description")}
        summary={[
          { label: "第一步", value: "上传并创建任务", detail: "语言、模式和增强项都在这里一次选完" },
          { label: "第二步", value: "筛选并跟进队列", detail: "搜索、状态和详情面板集中在任务表格" },
          { label: "第三步", value: "复盘用量", detail: "只在需要时查看模型、步骤和缓存消耗" },
        ]}
        actions={
          <>
            <input className="input" value={workspace.keyword} onChange={(event) => workspace.setKeyword(event.target.value)} placeholder={t("jobs.page.searchPlaceholder")} />
            <button className="button ghost" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
          </>
        }
      />

      <PageSection
        eyebrow="创建"
        title="创建任务与设置默认参数"
        description="新任务的语言、工作流、增强项和当前配置基线都在这一段完成，不需要先滚到队列表尾。"
      >
        <ConfigProfileSwitcher
          description="任务创建和审核确认都会继承这里激活的剪辑配置，数字人卡片只是其中一个配置模块，切换后新任务默认参数会立刻跟随。"
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
      </PageSection>

      <PageSection
        eyebrow="执行"
        title="跟进任务队列与审核详情"
        description="搜索、打开详情、重跑、取消和删除都集中在这里，优先保证处理链路顺畅。"
      >
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
      </PageSection>

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
          packaging={workspace.packaging.data}
          avatarMaterials={workspace.avatarMaterials.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          reviewEnhancementModes={workspace.reviewEnhancementModes}
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
          onConfirmProfile={() => workspace.confirmProfile.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && workspace.cancelJob.mutate(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && workspace.restartJob.mutate(workspace.selectedJob.id)}
          onDelete={() => workspace.selectedJob && workspace.deleteJob.mutate(workspace.selectedJob.id)}
          onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        />
      </JobDetailModal>

      {workspace.usageSummary.data && (
        <PageSection
          eyebrow="分析"
          title="需要时再看资源与用量"
          description="用量分析放到队列之后，只在复盘成本、排查异常或优化默认配置时查看。"
        >
          <div className="stats-grid">
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
        </PageSection>
      )}
    </section>
  );
}

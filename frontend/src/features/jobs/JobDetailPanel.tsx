import type { AvatarMaterialLibrary, Config, ContentProfileReview, Job, JobActivity, JobTimeline, PackagingLibrary, Report, TokenUsageReport } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import { JobContentProfileSection } from "./JobContentProfileSection";
import { JobSubtitleReportSection } from "./JobSubtitleReportSection";
import { JobReviewConfigSection } from "./JobReviewConfigSection";
import { stepLabel, workflowModeLabel, enhancementModeLabel } from "./constants";

type JobDetailPanelProps = {
  selectedJobId: string | null;
  className?: string;
  selectedJob?: Job;
  isLoading: boolean;
  activity?: JobActivity;
  report?: Report;
  tokenUsage?: TokenUsageReport;
  timeline?: JobTimeline;
  contentProfile?: ContentProfileReview;
  config?: Config;
  packaging?: PackagingLibrary;
  avatarMaterials?: AvatarMaterialLibrary;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  reviewEnhancementModes: string[];
  isConfirmingProfile: boolean;
  isApplyingReview: boolean;
  isCancelling: boolean;
  isRestarting: boolean;
  isDeleting: boolean;
  onContentFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onConfirmProfile: () => void;
  onOpenFolder: () => void;
  onCancel: () => void;
  onRestart: () => void;
  onDelete: () => void;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
};

export function JobDetailPanel({
  selectedJobId,
  className,
  selectedJob,
  isLoading,
  activity,
  report,
  tokenUsage,
  timeline,
  contentProfile,
  config,
  packaging,
  avatarMaterials,
  contentSource,
  contentDraft,
  contentKeywords,
  reviewEnhancementModes,
  isConfirmingProfile,
  isApplyingReview,
  isCancelling,
  isRestarting,
  isDeleting,
  onContentFieldChange,
  onKeywordsChange,
  onConfirmProfile,
  onOpenFolder,
  onCancel,
  onRestart,
  onDelete,
  onApplyReview,
}: JobDetailPanelProps) {
  const { t } = useI18n();
  const isReviewMode = selectedJob?.status === "needs_review";
  const topUsageSteps = [...(tokenUsage?.steps ?? [])].sort((a, b) => b.total_tokens - a.total_tokens).slice(0, 3);
  const topUsageModels = [...(tokenUsage?.models ?? [])].sort((a, b) => b.total_tokens - a.total_tokens).slice(0, 3);
  const topUsageOperations = [...(topUsageSteps[0]?.operations ?? [])].sort((a, b) => b.total_tokens - a.total_tokens).slice(0, 3);
  const topCacheSteps = [...(tokenUsage?.steps ?? [])].filter((step) => step.cache_entries.some((entry) => entry.hit)).slice(0, 3);
  const getSavedTokensForStep = (stepName: string) =>
    (tokenUsage?.steps.find((step) => step.step_name === stepName)?.cache_entries ?? [])
      .filter((entry) => entry.hit)
      .reduce((sum, entry) => sum + (entry.usage_baseline?.total_tokens ?? 0), 0);
  const formatUsageBreakdown = (promptTokens: number, completionTokens: number, calls: number) =>
    `${t("jobs.detail.tokenUsage.promptTokens")} ${promptTokens.toLocaleString()} / ${t("jobs.detail.tokenUsage.completionTokens")} ${completionTokens.toLocaleString()} / ${t("jobs.detail.tokenUsage.calls")} ${calls.toLocaleString()}`;
  const avatarDecision = activity?.decisions?.find((item) => item.kind === "avatar_commentary");
  const avatarHeadlineStatus = avatarDecision?.status ?? selectedJob?.avatar_delivery_status ?? null;
  const avatarHeadlineSummary = avatarDecision?.summary ?? selectedJob?.avatar_delivery_summary ?? null;
  const avatarEnabled = Boolean(selectedJob?.enhancement_modes.includes("avatar_commentary"));
  const downloadLabel = avatarEnabled
    ? avatarHeadlineStatus === "done"
      ? t("jobs.actions.downloadVideo.avatarIncluded")
      : avatarHeadlineStatus === "failed"
      ? t("jobs.actions.downloadVideo.avatarFallback")
      : t("jobs.actions.downloadVideo")
    : t("jobs.actions.downloadVideo");
  const downloadHint = avatarEnabled
    ? avatarHeadlineStatus === "done"
      ? t("jobs.actions.downloadHint.avatarIncluded")
      : avatarHeadlineStatus === "failed"
      ? t("jobs.actions.downloadHint.avatarFallback")
      : avatarHeadlineSummary || t("jobs.actions.downloadHint.standard")
    : t("jobs.actions.downloadHint.standard");

  return (
    <aside className={classNames("panel detail-panel", className)}>
      {!selectedJobId && <EmptyState message={t("jobs.detail.empty")} />}
      {selectedJobId && isLoading && <EmptyState message={t("jobs.detail.loading")} />}
      {selectedJob && (
        <>
          <PanelHeader
            title={selectedJob.source_name}
            description={selectedJob.id}
            actions={
              <div className="form-stack compact-top">
                <span className={`status-chip ${selectedJob.status}`}>{statusLabel(selectedJob.status)}</span>
                {avatarHeadlineSummary ? (
                  <span className={`status-pill ${avatarHeadlineStatus || "pending"}`}>
                    数字人：{avatarHeadlineSummary}
                  </span>
                ) : null}
              </div>
            }
          />

          <div className="detail-actions">
            <button className="button ghost" onClick={onOpenFolder}>
              {t("jobs.actions.openFolder")}
            </button>
            <a className="button ghost" href={`/api/v1/jobs/${selectedJob.id}/download`} target="_blank" rel="noreferrer">
              {downloadLabel}
            </a>
            <button
              className="button ghost"
              disabled={selectedJob.status === "done" || selectedJob.status === "failed" || selectedJob.status === "cancelled" || isCancelling}
              onClick={onCancel}
            >
              {isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
            </button>
            <button className="button primary" onClick={onRestart} disabled={isRestarting}>
              {isRestarting ? t("jobs.actions.restarting") : t("jobs.actions.restart")}
            </button>
            <button className="button danger" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
            </button>
          </div>
          <div className="muted compact-top">{downloadHint}</div>

          {!isReviewMode && (
            <section className="detail-block">
              <div className="detail-key">{t("jobs.detail.creativeMode")}</div>
              <div className="mode-chip-list">
                <span className="mode-chip">{workflowModeLabel(selectedJob.workflow_mode)}</span>
                {selectedJob.enhancement_modes.length ? (
                  selectedJob.enhancement_modes.map((mode) => (
                    <span key={mode} className="mode-chip subtle">
                      {enhancementModeLabel(mode)}
                    </span>
                  ))
                ) : (
                  <span className="muted">{t("jobs.detail.noEnhancements")}</span>
                )}
              </div>
            </section>
          )}

          {isReviewMode ? (
            <JobReviewConfigSection
              config={config}
              packaging={packaging}
              avatarMaterials={avatarMaterials}
              enhancementModes={reviewEnhancementModes}
            />
          ) : (
            <>
              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.currentActivity")}</div>
                {activity?.current_step ? (
                  <div className="activity-card">
                    <strong>{activity.current_step.label}</strong>
                    <div className="muted">{activity.current_step.detail || "—"}</div>
                    {typeof activity.current_step.progress === "number" && (
                      <div className="progress-bar">
                        <span style={{ width: `${Math.round(activity.current_step.progress * 100)}%` }} />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="muted">{t("jobs.detail.noActivity")}</div>
                )}
              </section>

              {!!activity?.decisions?.length && (
                <section className="detail-block">
                  <div className="detail-key">{t("jobs.detail.decisions")}</div>
                  <div className="timeline-list">
                    {activity.decisions.map((decision, index) => (
                      <div key={`${decision.kind}-${index}`} className="timeline-item">
                        <div className="toolbar">
                          <strong>{decision.title}</strong>
                          <span className={`status-pill ${decision.status}`}>{statusLabel(decision.status)}</span>
                        </div>
                        <div>{decision.summary}</div>
                        {decision.detail && <div className="muted">{decision.detail}</div>}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.stepStatus")}</div>
                <div className="steps-list">
                  {selectedJob.steps.map((step) => (
                    <div key={step.id} className="step-row">
                      <span>{stepLabel(step.step_name)}</span>
                      <span className={`status-chip ${step.status}`}>{statusLabel(step.status)}</span>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          <JobContentProfileSection
            jobId={selectedJob.id}
            contentProfile={contentProfile}
            contentSource={contentSource}
            contentDraft={contentDraft}
            contentKeywords={contentKeywords}
            isSaving={isConfirmingProfile}
            reviewMode={isReviewMode}
            onFieldChange={onContentFieldChange}
            onKeywordsChange={onKeywordsChange}
            onConfirm={onConfirmProfile}
          />

          {!isReviewMode && (
            <>
              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.tokenUsage")}</div>
                {tokenUsage?.has_telemetry ? (
                  <>
                    <div className="token-usage-grid">
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.totalTokens")}</div>
                        <strong>{tokenUsage.total_tokens.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.promptTokens")}</div>
                        <strong>{tokenUsage.total_prompt_tokens.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.completionTokens")}</div>
                        <strong>{tokenUsage.total_completion_tokens.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.calls")}</div>
                        <strong>{tokenUsage.total_calls.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.cacheHits")}</div>
                        <strong>{tokenUsage.cache.hits.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.cacheHitRate")}</div>
                        <strong>{Math.round((tokenUsage.cache.hit_rate || 0) * 100)}%</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.avoidedCalls")}</div>
                        <strong>{tokenUsage.cache.avoided_calls.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.savedTokens")}</div>
                        <strong>{tokenUsage.cache.saved_total_tokens.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.savedTokenCoverage")}</div>
                        <strong>{Math.round((tokenUsage.cache.saved_tokens_hit_rate || 0) * 100)}%</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.baselineHits")}</div>
                        <strong>{tokenUsage.cache.hits_with_usage_baseline.toLocaleString()}</strong>
                      </div>
                      <div className="activity-card">
                        <div className="muted">{t("jobs.detail.tokenUsage.stepsWithHits")}</div>
                        <strong>{tokenUsage.cache.steps_with_hits.toLocaleString()}</strong>
                      </div>
                    </div>

                    <div className="token-usage-columns top-gap">
                      <div className="timeline-list">
                        <div className="token-usage-subtitle">{t("jobs.detail.tokenUsage.topSteps")}</div>
                        {topUsageSteps.map((step) => (
                          <div key={step.step_name} className="timeline-item">
                            <div className="toolbar">
                              <strong>{step.label}</strong>
                              <span className="status-pill pending">{step.total_tokens.toLocaleString()}</span>
                            </div>
                            <div className="muted">
                              {formatUsageBreakdown(step.prompt_tokens, step.completion_tokens, step.calls)}
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="timeline-list">
                        <div className="token-usage-subtitle">{t("jobs.detail.tokenUsage.topOperations")}</div>
                        {topUsageOperations.length ? (
                          topUsageOperations.map((operation) => (
                            <div key={operation.operation} className="timeline-item">
                              <div className="toolbar">
                                <strong>{operation.operation}</strong>
                                <span className="status-pill pending">{operation.total_tokens.toLocaleString()}</span>
                              </div>
                              <div className="muted">
                                {formatUsageBreakdown(operation.prompt_tokens, operation.completion_tokens, operation.calls)}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="muted">{t("jobs.detail.tokenUsage.noOperations")}</div>
                        )}
                      </div>

                      <div className="timeline-list">
                        <div className="token-usage-subtitle">{t("jobs.detail.tokenUsage.cacheSteps")}</div>
                        {topCacheSteps.length ? (
                          topCacheSteps.map((step) => (
                            <div key={`${step.step_name}-cache`} className="timeline-item">
                              <div className="toolbar">
                                <strong>{step.label}</strong>
                                <span className="status-pill done">
                                  {step.cache_entries.filter((entry) => entry.hit).length.toLocaleString()}
                                </span>
                              </div>
                              <div className="muted">
                                {step.cache_entries
                                  .filter((entry) => entry.hit)
                                  .map((entry) => entry.name)
                                  .join(" / ")}
                                {` / ${t("jobs.detail.tokenUsage.savedTokens")} ${getSavedTokensForStep(step.step_name).toLocaleString()}`}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="muted">{t("jobs.detail.tokenUsage.noCacheHits")}</div>
                        )}
                      </div>

                      <div className="timeline-list">
                        <div className="token-usage-subtitle">{t("jobs.detail.tokenUsage.topModels")}</div>
                        {topUsageModels.map((model) => (
                          <div key={`${model.provider ?? "unknown"}-${model.model}-${model.kind ?? "reasoning"}`} className="timeline-item">
                            <div className="toolbar">
                              <strong>{model.model}</strong>
                              <span className="status-pill pending">{model.total_tokens.toLocaleString()}</span>
                            </div>
                            <div className="muted">{[model.provider, model.kind].filter(Boolean).join(" / ") || "unknown"}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="notice">{t("jobs.detail.tokenUsage.empty")}</div>
                )}
              </section>

              <JobSubtitleReportSection report={report} isApplying={isApplyingReview} onApplyReview={onApplyReview} />

              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.timeline")}</div>
                <div className="timeline-list">
                  {activity?.events?.slice(0, 8).map((event, index) => (
                    <div key={`${event.timestamp}-${index}`} className="timeline-item">
                      <div className="muted">{formatDate(event.timestamp)}</div>
                      <strong>{event.title}</strong>
                      <div className="muted">{event.detail || event.status}</div>
                    </div>
                  ))}
                </div>
                <details className="top-gap">
                  <summary>{t("jobs.detail.timelineJson")}</summary>
                  <pre className="json-preview">{JSON.stringify(timeline?.data ?? {}, null, 2)}</pre>
                </details>
              </section>
            </>
          )}
        </>
      )}
    </aside>
  );
}

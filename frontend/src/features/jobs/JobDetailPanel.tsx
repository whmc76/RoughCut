import type { AvatarMaterialLibrary, Config, ContentProfileReview, Job, JobActivity, JobTimeline, PackagingLibrary, Report, TokenUsageReport } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import { JobContentProfileSection } from "./JobContentProfileSection";
import { JobSubtitleReportSection } from "./JobSubtitleReportSection";
import { JobReviewConfigSection } from "./JobReviewConfigSection";
import { getRestartUnavailableReason, isRestartableJobStatus, stepLabel, workflowModeLabel, enhancementModeLabel } from "./constants";

type ActivityEvent = NonNullable<JobActivity["events"]>[number];

const STUCK_DIAGNOSTIC_TITLE_HINTS = ["卡住诊断", "stuck", "stuck_step", "stuck-step", "stuck diagnostic", "stuck-diagnostic"];

function isStuckDiagnosticEvent(event: ActivityEvent): boolean {
  const title = (event.title || "").toLowerCase();
  return event.type === "artifact" && STUCK_DIAGNOSTIC_TITLE_HINTS.some((hint) => title.includes(hint));
}

function resolveEventSeverity(event: ActivityEvent): string {
  if (event.type === "error") return "failed";
  if (event.type === "cancelled") return "cancelled";
  if (event.status === "failed" || event.status === "cancelled") return event.status;
  if (isStuckDiagnosticEvent(event)) return "failed";
  return event.status || "pending";
}

function isFailureEvent(event: ActivityEvent): boolean {
  const status = resolveEventSeverity(event);
  return status === "failed" || status === "cancelled" || isStuckDiagnosticEvent(event);
}

function resolveEventSeverityClass(event: ActivityEvent): string {
  const status = resolveEventSeverity(event);
  if (status === "running" || status === "processing") return "running";
  if (status === "cancelled") return "cancelled";
  if (status === "failed") return "failed";
  if (status === "done") return "done";
  return "pending";
}

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
  const currentStep = activity?.current_step;
  const timelineEvents = activity?.events ?? [];
  const timelineEventEntries = timelineEvents.map((event, index) => ({ event, index }));
  const criticalEvents = timelineEventEntries.filter(({ event }) => isFailureEvent(event));
  const visibleTimelineEntries = criticalEvents.length
    ? timelineEventEntries
    : timelineEventEntries.slice(
        0,
        selectedJob?.status === "failed" || selectedJob?.status === "cancelled" ? 20 : 8,
      );
  const hasTerminalFailure =
    selectedJob?.status === "failed" ||
    selectedJob?.status === "cancelled" ||
    currentStep?.status === "failed" ||
    currentStep?.status === "cancelled";
  const latestFailureTimelineIndex = criticalEvents.length ? criticalEvents[0].index : -1;
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
  const jumpToTimelineEvent = (index: number) => {
    const target = document.getElementById(`timeline-event-${index}`);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

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
            <button
              className="button primary"
              onClick={onRestart}
              disabled={isRestarting || !isRestartableJobStatus(selectedJob.status)}
              title={isRestartableJobStatus(selectedJob.status) ? undefined : t(getRestartUnavailableReason(selectedJob.status))}
            >
              {isRestarting
                ? t("jobs.actions.restarting")
                : isRestartableJobStatus(selectedJob.status) ? t("jobs.actions.restart") : t("jobs.actions.restartUnavailable")}
            </button>
            <button className="button danger" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
            </button>
          </div>
          <div className="muted compact-top">{downloadHint}</div>

          {selectedJob?.error_message ? (
            <section className="detail-block">
              <div className="detail-key">{t("jobs.detail.jobIssue")}</div>
              <article className="activity-card activity-alert">
                <div className="toolbar">
                  <span className={`status-pill ${selectedJob.status}`}>{statusLabel(selectedJob.status)}</span>
                  <span className="muted">{formatDate(selectedJob.updated_at)}</span>
                </div>
                <div>{selectedJob.error_message}</div>
              </article>
            </section>
          ) : null}

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
                {currentStep ? (
                  <div className="activity-card">
                    <div className="toolbar">
                      <strong>{currentStep.label}</strong>
                      <span className={classNames("status-pill", currentStep.status)}>{statusLabel(currentStep.status)}</span>
                    </div>
                    <div className={classNames("muted", hasTerminalFailure ? "muted-strong" : "")}>{currentStep.detail || "—"}</div>
                    {typeof currentStep.progress === "number" && (
                      <div className="progress-bar">
                        <span style={{ width: `${Math.round(currentStep.progress * 100)}%` }} />
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
                    <div
                      key={step.id}
                      className={classNames(
                        "step-row",
                        step.status === "failed" && "step-row-error",
                        step.status === "cancelled" && "step-row-error",
                        step.status === "running" && "step-row-running",
                      )}
                    >
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
                {criticalEvents.length > 0 ? (
                  <>
                    <div className="detail-key error-events-head">
                      <span>{t("jobs.detail.errorEvents")}</span>
                      <span className="event-count-badge">{criticalEvents.length}</span>
                      <button type="button" className="button button-sm ghost" onClick={() => jumpToTimelineEvent(latestFailureTimelineIndex)}>
                        {t("jobs.detail.jumpToLatestFailure")}
                      </button>
                    </div>
                    <div className="timeline-list">
                      {criticalEvents.map(({ event, index }) => (
                        <div
                          key={`${event.timestamp}-${event.title}-${event.type}-${index}`}
                          className={classNames(
                            "timeline-item",
                            "event-failed",
                            isStuckDiagnosticEvent(event) && "event-diagnostic",
                          )}
                        >
                          <div className="toolbar">
                            <span className="muted">{formatDate(event.timestamp)}</span>
                            <span className={classNames("status-pill", resolveEventSeverityClass(event))}>
                              {statusLabel(resolveEventSeverity(event))}
                            </span>
                          </div>
                          <strong>{event.title}</strong>
                          <div className={classNames("muted", isStuckDiagnosticEvent(event) && "muted-strong")}>
                            {event.detail || event.status}
                          </div>
                          <div className="toolbar">
                            <span className="muted">{formatDate(event.timestamp)}</span>
                            <button type="button" className="button button-sm ghost" onClick={() => jumpToTimelineEvent(index)}>
                              {t("jobs.detail.jumpToTimeline")}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
              </section>

              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.timeline")}</div>
                <div className="timeline-list">
                  {visibleTimelineEvents.map((event, index) => (
                    <div
                      key={`${event.timestamp}-${index}`}
                      className={classNames(
                        "timeline-item",
                        `event-${resolveEventSeverityClass(event)}`,
                        isStuckDiagnosticEvent(event) && "event-diagnostic",
                      )}
                    >
                      <div className="muted">{formatDate(event.timestamp)}</div>
                      <div className="toolbar">
                        <strong>{event.title}</strong>
                        <span className={classNames("status-pill", resolveEventSeverityClass(event))}>
                          {statusLabel(resolveEventSeverity(event))}
                        </span>
                      </div>
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

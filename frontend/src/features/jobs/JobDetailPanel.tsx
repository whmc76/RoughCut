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

type StepActivityItem = {
  id: string;
  title: string;
  detail?: string | null;
  status: string;
  timestamp?: string | null;
  toneClass: string;
};

function resolveItemToneClass(status: string): string {
  if (status === "running" || status === "processing" || status === "started") return "running";
  if (status === "cancelled") return "cancelled";
  if (status === "failed") return "failed";
  if (status === "done") return "done";
  return "pending";
}

type JobDetailPanelProps = {
  selectedJobId: string | null;
  className?: string;
  flowOnly?: boolean;
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
  flowOnly = false,
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
  const showReviewConfig = isReviewMode && !flowOnly;
  const showFlowSections = !isReviewMode || flowOnly;
  const currentStep = activity?.current_step;
  const timelineEvents = activity?.events ?? [];
  const hasTerminalFailure =
    selectedJob?.status === "failed" ||
    selectedJob?.status === "cancelled" ||
    currentStep?.status === "failed" ||
    currentStep?.status === "cancelled";
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
  const stepEntries = selectedJob?.steps ?? [];
  const stepLabelEntries = stepEntries
    .map((step) => ({ stepName: step.step_name, label: stepLabel(step.step_name) }))
    .sort((left, right) => right.label.length - left.label.length);
  const fallbackStepName =
    currentStep?.step_name
    ?? stepEntries.find((step) => step.status === "running" || step.status === "failed" || step.status === "cancelled")?.step_name
    ?? null;
  const resolveStepNameForText = (text: string) => {
    for (const entry of stepLabelEntries) {
      if (text.includes(entry.label)) return entry.stepName;
    }
    if (text.includes("时间线")) return "edit_plan";
    if (text.includes("渲染")) return "render";
    if (text.includes("数字人")) return "avatar_commentary";
    if (text.includes("任务失败") || text.includes("任务已取消")) return fallbackStepName;
    return null;
  };
  const stepItemsMap = new Map<string, StepActivityItem[]>();
  const pushStepItem = (stepName: string | null, item: StepActivityItem) => {
    if (!stepName) return;
    const next = stepItemsMap.get(stepName) ?? [];
    next.push(item);
    stepItemsMap.set(stepName, next);
  };

  timelineEvents.forEach((event, index) => {
    const matchedStepName = resolveStepNameForText(`${event.title || ""} ${event.detail || ""}`);
    pushStepItem(matchedStepName, {
      id: `event-${index}-${event.timestamp || "na"}`,
      title: event.title,
      detail: event.detail,
      status: resolveEventSeverity(event),
      timestamp: event.timestamp,
      toneClass: resolveEventSeverityClass(event),
    });
  });

  (activity?.decisions ?? []).forEach((decision, index) => {
    const matchedStepName =
      resolveStepNameForText(`${decision.title || ""} ${decision.summary || ""} ${decision.detail || ""}`)
      ?? (decision.kind === "avatar_commentary" ? "avatar_commentary" : decision.kind === "edit_plan" ? "edit_plan" : null);
    pushStepItem(matchedStepName, {
      id: `decision-${index}-${decision.kind}`,
      title: decision.title,
      detail: decision.detail || decision.summary,
      status: decision.status,
      timestamp: decision.updated_at,
      toneClass: resolveItemToneClass(decision.status),
    });
  });

  const currentStepProgressPercent =
    typeof currentStep?.progress === "number" ? Math.round(currentStep.progress * 100) : null;

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

          {showFlowSections && (
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

          {showReviewConfig ? (
            <JobReviewConfigSection
              config={config}
              packaging={packaging}
              avatarMaterials={avatarMaterials}
              enhancementModes={reviewEnhancementModes}
            />
          ) : showFlowSections ? (
            <>
              <section className="detail-block">
                <div className="detail-key">{t("jobs.detail.stepStatus")}</div>
                <div className="steps-list">
                  {selectedJob.steps.map((step) => {
                    const stepItems = [...(stepItemsMap.get(step.step_name) ?? [])].sort((left, right) =>
                      String(right.timestamp || "").localeCompare(String(left.timestamp || "")),
                    );
                    const isCurrentStep = currentStep?.step_name === step.step_name;
                    const hasRunningProgress = isCurrentStep && currentStepProgressPercent !== null;
                    const summaryText =
                      isCurrentStep && currentStep?.detail
                        ? currentStep.detail
                        : stepItems[0]?.detail || step.error_message || null;

                    return (
                      <details
                        key={step.id}
                        open={isCurrentStep}
                        className={classNames(
                          "step-row",
                          isCurrentStep && "step-row-current",
                          step.status === "failed" && "step-row-error",
                          step.status === "cancelled" && "step-row-error",
                          step.status === "running" && "step-row-running",
                        )}
                      >
                        <summary className="step-row-head">
                          <div className="step-row-title">
                            <strong>{stepLabel(step.step_name)}</strong>
                            {summaryText ? (
                              <div className={classNames("muted", hasTerminalFailure && isCurrentStep ? "muted-strong" : "")}>
                                {summaryText}
                              </div>
                            ) : null}
                          </div>
                          <span className={`status-chip ${step.status}`}>{statusLabel(step.status)}</span>
                        </summary>
                        <div className="step-row-body">
                          {hasRunningProgress ? (
                            <div className="progress-bar step-row-progress">
                              <span style={{ width: `${currentStepProgressPercent}%` }} />
                            </div>
                          ) : null}
                          {stepItems.length ? (
                            <div className="step-event-list">
                              {stepItems.slice(0, 4).map((item) => (
                                <article
                                  key={item.id}
                                  className={classNames(
                                    "step-event-card",
                                    item.toneClass === "failed" && "event-failed",
                                    item.toneClass === "cancelled" && "event-cancelled",
                                    item.toneClass === "running" && "event-running",
                                    item.title.includes("卡住诊断") && "event-diagnostic",
                                  )}
                                >
                                  <div className="toolbar">
                                    <strong>{item.title}</strong>
                                    <span className={classNames("status-pill", item.toneClass)}>{statusLabel(item.status)}</span>
                                  </div>
                                  {item.timestamp ? <div className="muted">{formatDate(item.timestamp)}</div> : null}
                                  {item.detail ? <div className="muted">{item.detail}</div> : null}
                                </article>
                              ))}
                            </div>
                          ) : (
                            <div className="muted compact-top">暂无步骤事件。</div>
                          )}
                        </div>
                      </details>
                    );
                  })}
                </div>
              </section>
            </>
          ) : null}

          {!flowOnly ? (
            <JobContentProfileSection
              jobId={selectedJob.id}
              thumbnailVersion={selectedJob.updated_at}
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
          ) : null}

          {showFlowSections && (
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

              {!flowOnly ? (
                <JobSubtitleReportSection report={report} isApplying={isApplyingReview} onApplyReview={onApplyReview} />
              ) : null}
            </>
          )}
        </>
      )}
    </aside>
  );
}

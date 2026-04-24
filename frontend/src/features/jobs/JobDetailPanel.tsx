import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import type {
  AvatarMaterialLibrary,
  Config,
  ContentProfileReview,
  Job,
  JobActivity,
  JobManualEditPreviewAssets,
  JobManualEditSession,
  JobManualEditApplyPayload,
  JobTimeline,
  PackagingLibrary,
  PublicationPlan,
  Report,
  TokenUsageReport,
} from "../../types";
import type { SelectOption } from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import { JobContentProfileSection } from "./JobContentProfileSection";
import { JobManualEditSection } from "./JobManualEditSection";
import { JobSubtitleDiagnosticsSection } from "./JobSubtitleDiagnosticsSection";
import { JobSubtitleReportSection } from "./JobSubtitleReportSection";
import { JobReviewConfigSection } from "./JobReviewConfigSection";
import {
  autoReviewBadgeLabel,
  autoReviewTone,
  enhancementModeLabel,
  getRestartUnavailableReason,
  isRestartableJobStatus,
  stepLabel,
  workflowModeLabel,
} from "./constants";

type ActivityEvent = NonNullable<JobActivity["events"]>[number];
const FILENAME_DESCRIPTION_PREFIX_RE = /^(?:任务说明依据文件名|Task description from filename)[:：]\s*/i;

function splitVideoDescription(value: string | null | undefined): {
  filenameDescription: string | null;
  manualDescription: string | null;
} {
  const text = String(value ?? "").trim();
  if (!text) {
    return {
      filenameDescription: null,
      manualDescription: null,
    };
  }
  const lines = text
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) {
    return {
      filenameDescription: null,
      manualDescription: null,
    };
  }
  const firstLine = lines[0] ?? "";
  if (!FILENAME_DESCRIPTION_PREFIX_RE.test(firstLine)) {
    return {
      filenameDescription: null,
      manualDescription: text,
    };
  }
  const filenameDescription = firstLine.replace(FILENAME_DESCRIPTION_PREFIX_RE, "").trim() || null;
  const manualDescription = lines.slice(1).join("\n").trim() || null;
  return {
    filenameDescription,
    manualDescription,
  };
}

const STUCK_DIAGNOSTIC_TITLE_HINTS = ["卡住诊断", "stuck", "stuck_step", "stuck-step", "stuck diagnostic", "stuck-diagnostic"];
const PUBLISHABLE_CREDENTIAL_STATUSES = new Set(["logged_in", "available", "verified"]);

function isStuckDiagnosticEvent(event: ActivityEvent): boolean {
  const title = (event.title || "").toLowerCase();
  return event.type === "artifact" && STUCK_DIAGNOSTIC_TITLE_HINTS.some((hint) => title.includes(hint));
}

function hasActivePublicationCredential(profile: NonNullable<AvatarMaterialLibrary["profiles"]>[number]): boolean {
  const credentials = profile.creator_profile?.publishing?.platform_credentials ?? [];
  return credentials.some(
    (item) =>
      item.enabled !== false &&
      (item.adapter ?? "browser_agent") === "browser_agent" &&
      PUBLISHABLE_CREDENTIAL_STATUSES.has(item.status),
  );
}

function publicationAttemptStatusLabel(status: string) {
  if (status === "queued") return "已排队";
  if (status === "draft_created") return "草稿已创建";
  if (status === "scheduled_pending") return "已预约";
  if (status === "published") return "已发布";
  if (status === "failed") return "失败";
  return status || "待处理";
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
  eventType?: string | null;
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
  manualEditor?: JobManualEditSession;
  manualEditorAssets?: JobManualEditPreviewAssets;
  contentProfile?: ContentProfileReview;
  config?: Config;
  packaging?: PackagingLibrary;
  avatarMaterials?: AvatarMaterialLibrary;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  reviewEnhancementModes: string[];
  languageOptions: SelectOption[];
  workflowTemplateOptions: SelectOption[];
  workflowModeOptions: SelectOption[];
  enhancementOptions: SelectOption[];
  pendingInitialization: {
    language: string;
    workflowTemplate: string;
    workflowMode: string;
    enhancementModes: string[];
    outputDir: string;
    videoDescription: string;
  };
  isConfirmingProfile: boolean;
  isInitializing: boolean;
  isApplyingReview: boolean;
  isTriggeringSubtitleRerun?: boolean;
  pendingRerunStartStep?: string | null;
  pendingRerunIssueCode?: string | null;
  isCancelling: boolean;
  isRestarting: boolean;
  isDeleting: boolean;
  isApplyingManualEditor?: boolean;
  onContentFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onPendingInitializationChange: (value: {
    language: string;
    workflowTemplate: string;
    workflowMode: string;
    enhancementModes: string[];
    outputDir: string;
    videoDescription: string;
  }) => void;
  onConfirmProfile: () => void;
  onInitialize: () => void;
  onOpenFolder: () => void;
  onCancel: () => void;
  onRestart: () => void;
  onDelete: () => void;
  onApplyManualEditor?: (payload: JobManualEditApplyPayload) => void;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
  onTriggerSubtitleRerun?: (decision: NonNullable<JobActivity["decisions"]>[number]) => void;
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
  manualEditor,
  manualEditorAssets,
  contentProfile,
  config,
  packaging,
  avatarMaterials,
  contentSource,
  contentDraft,
  contentKeywords,
  reviewEnhancementModes,
  languageOptions,
  workflowTemplateOptions,
  workflowModeOptions,
  enhancementOptions,
  pendingInitialization,
  isConfirmingProfile,
  isInitializing,
  isApplyingReview,
  isTriggeringSubtitleRerun = false,
  pendingRerunStartStep = null,
  pendingRerunIssueCode = null,
  isCancelling,
  isRestarting,
  isDeleting,
  isApplyingManualEditor = false,
  onContentFieldChange,
  onKeywordsChange,
  onPendingInitializationChange,
  onConfirmProfile,
  onInitialize,
  onOpenFolder,
  onCancel,
  onRestart,
  onDelete,
  onApplyManualEditor,
  onApplyReview,
  onTriggerSubtitleRerun,
}: JobDetailPanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const isReviewMode = selectedJob?.status === "needs_review";
  const isAwaitingInitialization = Boolean(selectedJob?.awaiting_initialization || selectedJob?.status === "awaiting_init");
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
  const mergedSourceNames = selectedJob?.merged_source_names ?? [];
  const isMergedTask = mergedSourceNames.length > 1;
  const { filenameDescription, manualDescription } = splitVideoDescription(selectedJob?.video_description);
  const avatarEnabled = Boolean(selectedJob?.enhancement_modes.includes("avatar_commentary"));
  const autoReviewVisible = Boolean(selectedJob?.auto_review_mode_enabled);
  const autoReviewReasons = selectedJob?.auto_review_reasons ?? [];
  const publicationProfiles = useMemo(
    () => (avatarMaterials?.profiles ?? []).filter((profile) => hasActivePublicationCredential(profile)),
    [avatarMaterials?.profiles],
  );
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState("");
  useEffect(() => {
    if (!publicationProfiles.length) {
      setSelectedPublicationProfileId("");
      return;
    }
    setSelectedPublicationProfileId((current) =>
      publicationProfiles.some((profile) => profile.id === current) ? current : publicationProfiles[0]?.id ?? "",
    );
  }, [publicationProfiles]);
  const publicationQueryKey = ["job-publication-plan", selectedJob?.id ?? "", selectedPublicationProfileId] as const;
  const publicationPlan = useQuery<PublicationPlan>({
    queryKey: publicationQueryKey,
    queryFn: () => api.getJobPublicationPlan(selectedJob!.id, selectedPublicationProfileId || null),
    enabled: Boolean(selectedJob?.id && selectedJob.status === "done"),
  });
  const publishMutation = useMutation({
    mutationFn: () => api.publishJob(selectedJob!.id, { creator_profile_id: selectedPublicationProfileId || null }),
    onSuccess: (data) => {
      queryClient.setQueryData(publicationQueryKey, data);
    },
  });
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
  const stepItemsMap = new Map<string, StepActivityItem[]>();
  const pushStepItem = (stepName: string | null, item: StepActivityItem) => {
    if (!stepName) return;
    const next = stepItemsMap.get(stepName) ?? [];
    next.push(item);
    stepItemsMap.set(stepName, next);
  };

  timelineEvents.forEach((event, index) => {
    pushStepItem(event.step_name ?? null, {
      id: `event-${index}-${event.timestamp || "na"}`,
      title: event.title,
      detail: event.detail,
      status: resolveEventSeverity(event),
      timestamp: event.timestamp,
      toneClass: resolveEventSeverityClass(event),
      eventType: event.type,
    });
  });

  (activity?.decisions ?? []).forEach((decision, index) => {
    pushStepItem(decision.step_name ?? null, {
      id: `decision-${index}-${decision.kind}`,
      title: decision.title,
      detail: decision.detail || decision.summary,
      status: decision.status,
      timestamp: decision.updated_at,
      toneClass: resolveItemToneClass(decision.status),
      eventType: "decision",
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
            <button type="button" className="button ghost" onClick={onOpenFolder}>
              {t("jobs.actions.openFolder")}
            </button>
            <a className="button ghost" href={`/api/v1/jobs/${selectedJob.id}/download`} target="_blank" rel="noreferrer">
              {downloadLabel}
            </a>
            <button
              type="button"
              className="button ghost"
              disabled={selectedJob.status === "done" || selectedJob.status === "failed" || selectedJob.status === "cancelled" || isCancelling}
              onClick={onCancel}
            >
              {isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
            </button>
            <button
              type="button"
              className="button primary"
              onClick={isAwaitingInitialization ? onInitialize : onRestart}
              disabled={
                isAwaitingInitialization
                  ? isInitializing || !pendingInitialization.videoDescription.trim()
                  : isRestarting || !isRestartableJobStatus(selectedJob.status)
              }
              title={
                isAwaitingInitialization
                  ? undefined
                  : isRestartableJobStatus(selectedJob.status) ? undefined : t(getRestartUnavailableReason(selectedJob.status))
              }
            >
              {isAwaitingInitialization
                ? (isInitializing ? t("jobs.init.submitting") : t("jobs.init.submit"))
                : isRestarting
                  ? t("jobs.actions.restarting")
                  : isRestartableJobStatus(selectedJob.status) ? t("jobs.actions.restart") : t("jobs.actions.restartUnavailable")}
            </button>
            <button type="button" className="button danger" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
            </button>
          </div>
          <div className="muted compact-top">{downloadHint}</div>

          {selectedJob.status === "done" ? (
            <section className="detail-block">
              <div className="detail-key">一键发布</div>
              <div className="activity-card">
                <div className="toolbar">
                  <div>
                    <strong>发布到已登录凭据平台</strong>
                    <div className="muted compact-top">使用平台文案包和本地成片创建 browser-agent 发布任务。</div>
                  </div>
                  <span className={`status-pill ${publicationPlan.data?.publish_ready ? "done" : "pending"}`}>
                    {publicationPlan.data?.publish_ready ? "可发布" : "待补齐"}
                  </span>
                </div>

                <div className="form-grid two-up compact-top">
                  <label>
                    <span>创作者凭据</span>
                    <select
                      className="input"
                      value={selectedPublicationProfileId}
                      onChange={(event) => setSelectedPublicationProfileId(event.target.value)}
                      disabled={!publicationProfiles.length}
                    >
                      {!publicationProfiles.length ? <option value="">没有可用发布凭据</option> : null}
                      {publicationProfiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.display_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="toolbar toolbar-bottom">
                    <button
                      className="button primary"
                      type="button"
                      disabled={!publicationPlan.data?.publish_ready || publishMutation.isPending}
                      onClick={() => publishMutation.mutate()}
                    >
                      {publishMutation.isPending ? "提交中..." : "发布到绑定平台"}
                    </button>
                  </div>
                </div>

                {publicationPlan.isLoading ? <div className="muted compact-top">正在检查发布准入...</div> : null}
                {publicationPlan.data?.blocked_reasons?.length ? (
                  <div className="list-stack compact-top">
                    {publicationPlan.data.blocked_reasons.map((reason) => (
                      <div key={reason} className="notice">{reason}</div>
                    ))}
                  </div>
                ) : null}
                {publicationPlan.data?.warnings?.length ? (
                  <div className="list-stack compact-top">
                    {publicationPlan.data.warnings.map((warning) => (
                      <div key={warning} className="activity-card">{warning}</div>
                    ))}
                  </div>
                ) : null}
                {publicationPlan.data?.targets?.length ? (
                  <div className="mode-chip-list compact-top">
                    {publicationPlan.data.targets.map((target) => (
                      <span className="mode-chip subtle" key={target.platform}>
                        {target.platform_label} · {target.account_label}
                      </span>
                    ))}
                  </div>
                ) : null}
                {publishMutation.error ? <div className="notice compact-top">{String(publishMutation.error)}</div> : null}
                {publicationPlan.data?.existing_attempts?.length ? (
                  <div className="timeline-list top-gap">
                    {publicationPlan.data.existing_attempts.slice(0, 4).map((attempt) => (
                      <div className="timeline-item" key={attempt.id}>
                        <div className="toolbar">
                          <strong>{attempt.platform_label || attempt.platform}</strong>
                          <span className={`status-pill ${attempt.status === "failed" ? "failed" : attempt.status === "published" ? "done" : "running"}`}>
                            {publicationAttemptStatusLabel(attempt.status)}
                          </span>
                        </div>
                        <div className="muted">
                          {attempt.account_label} · {attempt.operator_summary || attempt.run_status || "等待运行器处理"}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          {isMergedTask ? (
            <section className="detail-block">
              <div className="detail-key">{t("jobs.detail.sourceBundle")}</div>
              <div className="mode-chip-list">
                <span className="mode-chip">{t("jobs.detail.mergedTask")}</span>
                <span className="mode-chip subtle">
                  {t("jobs.detail.mergedTaskCount").replace("{count}", String(mergedSourceNames.length))}
                </span>
              </div>
              <div className="job-merged-source-list compact-top">
                {mergedSourceNames.map((sourceName) => (
                  <span key={sourceName} className="job-merged-source-item muted">
                    {sourceName}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {filenameDescription || manualDescription ? (
            <section className="detail-block">
              <div className="detail-key">{t("jobs.detail.videoDescription")}</div>
              {filenameDescription ? (
                <article className="activity-card">
                  <div className="toolbar">
                    <strong>{t("jobs.detail.filenameDerivedDescription")}</strong>
                    <span className="status-pill pending">{t("jobs.detail.filenameDerivedBadge")}</span>
                  </div>
                  <div>{filenameDescription}</div>
                </article>
              ) : null}
              {manualDescription ? (
                <article className={classNames("activity-card", filenameDescription && "compact-top")}>
                  <div className="toolbar">
                    <strong>{filenameDescription ? t("jobs.detail.manualDescription") : t("jobs.detail.videoDescription")}</strong>
                  </div>
                  <div>{manualDescription}</div>
                </article>
              ) : null}
            </section>
          ) : null}

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

          <section className="detail-block">
            <div className="detail-key">{t("jobs.detail.creativeMode")}</div>
            <div className="mode-chip-list">
              <span className="mode-chip">{workflowModeLabel(selectedJob.workflow_mode)}</span>
              {selectedJob.enhancement_modes.length ? (
                selectedJob.enhancement_modes.map((mode) => (
                  <span key={mode} className="mode-chip subtle">
                    {mode === "auto_review" ? autoReviewBadgeLabel(selectedJob) : enhancementModeLabel(mode)}
                  </span>
                ))
              ) : (
                <span className="muted">{t("jobs.detail.noEnhancements")}</span>
              )}
            </div>
            {autoReviewVisible ? (
              <div className="compact-top">
                <span className={`status-pill ${autoReviewTone(selectedJob.auto_review_status)}`}>
                  {autoReviewBadgeLabel(selectedJob)}
                </span>
                {selectedJob.auto_review_summary ? (
                  <div className="muted compact-top">{selectedJob.auto_review_summary}</div>
                ) : null}
                {autoReviewReasons.length ? (
                  <div className="timeline-list top-gap">
                    {autoReviewReasons.slice(0, 4).map((reason) => (
                      <div key={reason} className="timeline-item">
                        {reason}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          <JobSubtitleDiagnosticsSection
            activity={activity}
            job={selectedJob}
            isTriggeringRerun={isTriggeringSubtitleRerun}
            pendingRerunStartStep={pendingRerunStartStep}
            pendingRerunIssueCode={pendingRerunIssueCode}
            onTriggerRerun={onTriggerSubtitleRerun}
          />

          {showReviewConfig ? (
            <JobReviewConfigSection
              config={config}
              packaging={packaging}
              avatarMaterials={avatarMaterials}
              enhancementModes={reviewEnhancementModes}
            />
          ) : isAwaitingInitialization ? (
            <section className="detail-block">
              <div className="detail-key">{t("jobs.init.title")}</div>
              <div className="muted compact-top">{t("jobs.init.description")}</div>
              <div className="form-grid three-up compact-top">
                <SelectField
                  label={t("jobs.upload.language")}
                  value={pendingInitialization.language}
                  onChange={(event) => onPendingInitializationChange({ ...pendingInitialization, language: event.target.value })}
                  options={languageOptions}
                />
                <SelectField
                  label={t("jobs.upload.workflowTemplate")}
                  value={pendingInitialization.workflowTemplate}
                  onChange={(event) => onPendingInitializationChange({ ...pendingInitialization, workflowTemplate: event.target.value })}
                  options={workflowTemplateOptions}
                />
                <label>
                  <span>{t("jobs.upload.outputDir")}</span>
                  <input
                    className="input"
                    type="text"
                    value={pendingInitialization.outputDir}
                    onChange={(event) => onPendingInitializationChange({ ...pendingInitialization, outputDir: event.target.value })}
                  />
                </label>
                <SelectField
                  label={t("jobs.upload.workflowMode")}
                  value={pendingInitialization.workflowMode}
                  onChange={(event) => onPendingInitializationChange({ ...pendingInitialization, workflowMode: event.target.value })}
                  options={workflowModeOptions}
                />
              </div>
              <div className="upload-enhancement-panel compact-top">
                <div className="stat-label">{t("jobs.upload.enhancements")}</div>
                <div className="checklist-grid compact-top">
                  {enhancementOptions.map((option) => {
                    const checked = pendingInitialization.enhancementModes.includes(option.value);
                    return (
                      <CheckboxField
                        key={option.value}
                        label={option.label}
                        checked={checked}
                        onChange={(event) =>
                          onPendingInitializationChange({
                            ...pendingInitialization,
                            enhancementModes: event.target.checked
                              ? [...pendingInitialization.enhancementModes, option.value]
                              : pendingInitialization.enhancementModes.filter((item) => item !== option.value),
                          })}
                      />
                    );
                  })}
                </div>
              </div>
              <label className="compact-top">
                <span>{t("jobs.upload.videoDescription")}</span>
                <textarea
                  className="input"
                  rows={5}
                  value={pendingInitialization.videoDescription}
                  onChange={(event) => onPendingInitializationChange({ ...pendingInitialization, videoDescription: event.target.value })}
                  placeholder={t("jobs.upload.videoDescriptionPlaceholder")}
                />
              </label>
            </section>
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
                                    item.eventType === "review_action" && "event-rerun",
                                    item.title.includes("卡住诊断") && "event-diagnostic",
                                  )}
                                >
                                  <div className="toolbar">
                                    <div className="toolbar">
                                      <strong>{item.title}</strong>
                                      {item.eventType === "review_action" ? (
                                        <span className="status-pill pending">重跑请求</span>
                                      ) : null}
                                    </div>
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

          {!flowOnly && !isAwaitingInitialization ? (
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

          {showFlowSections && !isAwaitingInitialization && (
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

              {manualEditor ? (
                <JobManualEditSection
                  job={selectedJob}
                  session={manualEditor}
                  previewAssets={manualEditorAssets}
                  saving={isApplyingManualEditor}
                  onApply={onApplyManualEditor}
                />
              ) : null}
            </>
          )}
        </>
      )}
    </aside>
  );
}

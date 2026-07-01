import type { Job } from "../../types";
import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import { resolveJobReviewStep } from "./useJobWorkspace";
import {
  autoReviewBadgeLabel,
  autoReviewTone,
  enhancementModeLabel,
  formatCutEvidenceSummary,
  getRestartUnavailableReason,
  isRestartableJobStatus,
  jobFlowModeLabel,
  jobStatusLabel,
  jobStatusTone,
  stepLabel,
  workflowModeLabel,
} from "./constants";

type JobActionIconName =
  | "alert"
  | "chevron-left"
  | "chevron-right"
  | "download"
  | "folder"
  | "pen"
  | "play"
  | "refresh"
  | "rocket"
  | "scissors"
  | "spinner"
  | "trash"
  | "x";

const FILENAME_DESCRIPTION_PREFIX_RE = /^(?:任务说明依据文件名|Task description from filename)[:：]\s*/i;

function JobActionIcon({ name }: { name: JobActionIconName }) {
  const commonProps = {
    className: "job-action-icon",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "alert":
      return (
        <svg {...commonProps}>
          <path d="M10.3 3.4 2.4 17.1a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.4a2 2 0 0 0-3.4 0Z" />
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
        </svg>
      );
    case "chevron-left":
      return (
        <svg {...commonProps}>
          <path d="m15 18-6-6 6-6" />
        </svg>
      );
    case "chevron-right":
      return (
        <svg {...commonProps}>
          <path d="m9 18 6-6-6-6" />
        </svg>
      );
    case "download":
      return (
        <svg {...commonProps}>
          <path d="M12 3v12" />
          <path d="m7 10 5 5 5-5" />
          <path d="M5 21h14" />
        </svg>
      );
    case "folder":
      return (
        <svg {...commonProps}>
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        </svg>
      );
    case "pen":
      return (
        <svg {...commonProps}>
          <path d="m16 4 4 4" />
          <path d="M14 6 5 15l-1 5 5-1 9-9" />
        </svg>
      );
    case "play":
      return (
        <svg {...commonProps}>
          <path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none" />
        </svg>
      );
    case "refresh":
      return (
        <svg {...commonProps}>
          <path d="M20 12a8 8 0 0 1-13.5 5.8" />
          <path d="M4 12A8 8 0 0 1 17.5 6.2" />
          <path d="M17 2v5h5" />
          <path d="M7 22v-5H2" />
        </svg>
      );
    case "rocket":
      return (
        <svg {...commonProps}>
          <path d="M4.5 16.5c-1 1-1.5 2.5-1.5 4.5 2 0 3.5-.5 4.5-1.5" />
          <path d="M9 15 4 10l6-1 5-5c2.5-2.5 5-2 6-1-1 1-1.5 3.5-4 6l-5 5-1 6-5-5Z" />
          <path d="M15 9h.01" />
        </svg>
      );
    case "scissors":
      return (
        <svg {...commonProps}>
          <path d="m14 7-8.5 8.5" />
          <path d="m14 17-8.5-8.5" />
          <circle cx="4.5" cy="6.5" r="2.5" />
          <circle cx="4.5" cy="17.5" r="2.5" />
          <path d="M15 7h6" />
          <path d="M15 17h6" />
        </svg>
      );
    case "spinner":
      return (
        <svg {...commonProps}>
          <path d="M21 12a9 9 0 0 1-9 9" />
          <path d="M12 3a9 9 0 0 1 9 9" opacity="0.35" />
          <path d="M3 12a9 9 0 0 1 9-9" opacity="0.2" />
        </svg>
      );
    case "trash":
      return (
        <svg {...commonProps}>
          <path d="M3 6h18" />
          <path d="M8 6V4h8v2" />
          <path d="M19 6 18 20H6L5 6" />
          <path d="M10 11v5" />
          <path d="M14 11v5" />
        </svg>
      );
    case "x":
      return (
        <svg {...commonProps}>
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      );
  }
}

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
  return {
    filenameDescription: firstLine.replace(FILENAME_DESCRIPTION_PREFIX_RE, "").trim() || null,
    manualDescription: lines.slice(1).join("\n").trim() || null,
  };
}

function resolvePendingReviewStep(job: Job) {
  const reviewStep = resolveJobReviewStep(job);
  if (reviewStep === "final_review") {
    return job.steps.find((step) => step.step_name === "final_review" && step.status !== "done") ?? null;
  }
  if (reviewStep === "summary_review") {
    return job.steps.find((step) => step.step_name === "summary_review" && step.status !== "done") ?? null;
  }
  return job.steps.find((step) => (step.step_name === "summary_review" || step.step_name === "final_review") && step.status === "pending")
    ?? job.steps.find((step) => (step.step_name === "summary_review" || step.step_name === "final_review") && step.status !== "done")
    ?? null;
}

function reviewActionLabel(job: Job, t: (key: string) => string) {
  if (job.status !== "needs_review") return "";
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") return "处理成片异常";
  if (reviewStep?.step_name === "summary_review") return "处理内容异常";
  return "处理异常";
}

function isHighlightedReviewAction(job: Job) {
  if (job.status !== "needs_review") return false;
  const reviewStep = resolvePendingReviewStep(job);
  return reviewStep?.step_name === "summary_review" || reviewStep?.step_name === "final_review";
}

function reviewStatusLabel(job: Job): string {
  if (job.status !== "needs_review") return jobStatusLabel(job);
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") return "成片异常";
  if (reviewStep?.step_name === "summary_review") return "内容异常";
  return jobStatusLabel(job);
}

function hasJobStarted(job: Job) {
  if (job.status === "running" || job.status === "processing" || job.status === "awaiting_manual_edit" || job.status === "needs_review") return true;
  return job.steps.some((step) => Boolean(step.started_at));
}

function isTerminalJob(job: Job) {
  return job.status === "done" || job.status === "failed" || job.status === "cancelled";
}

function queueSummaryText(job: Job, t: (key: string) => string) {
  const { manualDescription, filenameDescription } = splitVideoDescription(job.video_description);
  if (job.awaiting_manual_edit) {
    return "等待手动调整";
  }
  if (job.status !== "needs_review") {
    return job.content_summary || job.content_subject || manualDescription || filenameDescription || t("jobs.queue.noSummary");
  }
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") {
    return "成片异常待处理";
  }
  return "内容异常待处理";
}

function enhancementBadgeLabel(job: Job, mode: string) {
  if (mode === "auto_review") return autoReviewBadgeLabel(job);
  return enhancementModeLabel(mode);
}

function awaitingManualEditLabel(job: Job, t: (key: string) => string): string | null {
  return job.awaiting_manual_edit ? t("jobs.queue.awaitingManualEdit") : null;
}

function canOpenManualEditorFromQueue(job: Job) {
  if (job.status === "awaiting_init" || job.status === "failed" || job.status === "cancelled") {
    return false;
  }
  return job.steps.some((step) => step.step_name === "edit_plan" && step.status === "done");
}

function isRemixProductionJob(job: Job) {
  return job.queue_task_kind === "remix_production";
}

function isPublicationJob(job: Job) {
  return job.queue_task_kind === "publication";
}

function isSmartDirectorJob(job: Job) {
  return job.queue_task_kind === "smart_director";
}

function taskKindLabel(job: Job) {
  if (isPublicationJob(job)) return "发布任务";
  if (isRemixProductionJob(job)) return "解说二创";
  if (isSmartDirectorJob(job)) return "智能导演";
  return "剪辑任务";
}

function JobQueueThumbnail({ job }: { job: Job }) {
  const thumbnailVersion = job.queue_thumbnail_version || job.updated_at;
  const contentThumbnailUrl = api.contentProfileThumbnailUrl(job.id, 0, thumbnailVersion);
  const coverThumbnailUrl = api.jobCoverThumbnailUrl(job.id, thumbnailVersion);
  const [source, setSource] = useState<"cover" | "content_profile" | "fallback">(
    job.queue_thumbnail_source === "cover" ? "cover" : "content_profile",
  );
  const thumbnailUrl = source === "cover" ? coverThumbnailUrl : contentThumbnailUrl;

  if (source === "fallback") {
    return (
      <div className="job-queue-thumb job-queue-thumb-fallback visible" aria-hidden="true">
        无封面
      </div>
    );
  }

  return (
    <>
      <img
        className="job-queue-thumb"
        src={thumbnailUrl}
        alt={job.source_name}
        loading="lazy"
        decoding="async"
        onError={() => {
          setSource((current) => (current === "cover" ? "content_profile" : "fallback"));
        }}
      />
      <div className="job-queue-thumb job-queue-thumb-fallback" aria-hidden="true">
        无封面
      </div>
    </>
  );
}

type JobQueueTableProps = {
  jobs: Job[];
  selectedJobId: string | null;
  isLoading: boolean;
  errorMessage?: string;
  currentPage?: number;
  pageSize?: number;
  hasMore?: boolean;
  isFetchingPage?: boolean;
  onPageChange?: (page: number) => void;
  isCancelling?: boolean;
  isRestarting?: boolean;
  isStartingRemixProduction?: boolean;
  isDeleting?: boolean;
  headerActions?: ReactNode;
  onSelect: (jobId: string) => void;
  onOpenReview?: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onStartRemixProduction?: (jobId: string, force?: boolean) => void;
  onDelete: (jobId: string) => void;
};

export function JobQueueTable({
  jobs,
  selectedJobId,
  isLoading,
  currentPage,
  pageSize,
  hasMore,
  isFetchingPage,
  errorMessage,
  isCancelling,
  isRestarting,
  isStartingRemixProduction,
  isDeleting,
  headerActions,
  onSelect,
  onOpenReview,
  onCancel,
  onRestart,
  onStartRemixProduction,
  onDelete,
  onPageChange,
}: JobQueueTableProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const canGoPrev = (currentPage ?? 0) > 0 && !isFetchingPage;
  const canGoNext = Boolean(hasMore) && !isFetchingPage;
  const prefetchManualEditor = (jobId: string) => {
    void queryClient.fetchQuery({
      queryKey: ["job-manual-editor-readiness", jobId],
      queryFn: () => api.getJobManualEditorReadiness(jobId),
      staleTime: 5_000,
    })
      .then((readiness) => {
        if (!readiness.can_open_editor) return;
        void queryClient.prefetchQuery({
          queryKey: ["job-manual-editor", jobId],
          queryFn: () => api.getJobManualEditor(jobId),
          staleTime: 15_000,
        });
      })
      .catch(() => {
        // Hover prefetch is opportunistic; the manual editor page surfaces real errors.
      });
  };

  return (
    <section className="panel">
      <PanelHeader
        title={t("jobs.queue.title")}
        description={`#${jobs.length}${currentPage !== undefined ? ` · 第 ${currentPage + 1} 页` : ""}`}
        actions={headerActions}
      />
      <div className="table-wrap">
        <table className="data-table job-queue-table">
          <colgroup>
            <col className="queue-col-file" />
            <col className="queue-col-status" />
            <col className="queue-col-steps" />
            <col className="queue-col-updated" />
            <col className="queue-col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>{t("jobs.queue.file")}</th>
              <th>{t("jobs.queue.status")}</th>
              <th>{t("jobs.queue.steps")}</th>
              <th>{t("jobs.queue.updatedAt")}</th>
              <th>{t("jobs.queue.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5}><EmptyState message={t("jobs.queue.loading")} /></td>
              </tr>
            )}
            {errorMessage && (
              <tr>
                <td colSpan={5}><EmptyState message={errorMessage} tone="error" /></td>
              </tr>
            )}
            {!isLoading && !errorMessage && jobs.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <EmptyState message="当前没有匹配的任务。可以先创建新任务，或调整上方搜索条件。" />
                </td>
              </tr>
            )}
            {jobs.map((job) => {
              const isPublicationTask = isPublicationJob(job);
              const isRemixTask = isRemixProductionJob(job);
              const isSmartDirectorTask = isSmartDirectorJob(job);
              const showReviewAction = job.status === "needs_review";
              const highlightedReviewAction = isHighlightedReviewAction(job);
              const showPreview = job.status === "done";
              const showCancel = !isRemixTask && hasJobStarted(job) && !isTerminalJob(job);
              const manualEditStatus = awaitingManualEditLabel(job, t);
              const manualEditorReady = canOpenManualEditorFromQueue(job);
              const hasCutEvidenceSummary = Boolean(formatCutEvidenceSummary(job.timeline_diagnostics));

              return (
                <tr
                  key={job.id}
                  className={classNames(
                    selectedJobId === job.id && "selected-row",
                    isPublicationTask && "job-row-publication",
                    isRemixTask && "job-row-remix-production",
                    isSmartDirectorTask && "job-row-smart-director",
                  )}
                  onClick={() => onSelect(job.id)}
                >
                  <td>
                    <div className="job-file-cell">
                      <JobQueueThumbnail job={job} />
                      <div className="job-file-copy">
                        <div className="row-title job-queue-title">{job.source_name}</div>
                        <div className="muted line-clamp-1 job-queue-summary">{queueSummaryText(job, t)}</div>
                        <div className="mode-chip-list job-queue-primary-tags">
                          <span className={classNames(
                            "mode-chip",
                            job.queue_task_kind === "publication" ? "publication" : "planned",
                            isSmartDirectorTask && "smart-director",
                          )}>
                            {taskKindLabel(job)}
                          </span>
                          <span className="mode-chip planned">{jobFlowModeLabel(job.job_flow_mode || "auto")}</span>
                          <span className="mode-chip">{workflowModeLabel(job.workflow_mode)}</span>
                          {job.enhancement_modes.map((mode) => (
                            <span key={mode} className="mode-chip subtle">
                              {enhancementBadgeLabel(job, mode)}
                            </span>
                          ))}
                          {job.auto_review_mode_enabled && job.auto_review_summary ? (
                            <span className={`status-pill ${autoReviewTone(job.auto_review_status)}`}>
                              {autoReviewBadgeLabel(job)}
                            </span>
                          ) : null}
                          {hasCutEvidenceSummary ? <span className="status-pill pending">剪辑证据</span> : null}
                          {job.avatar_delivery_summary ? (
                            <span className={`status-pill ${job.avatar_delivery_status || "pending"}`}>数字人</span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="form-stack compact-top job-queue-status-stack">
                      <span className={`status-chip ${jobStatusTone(job)}`}>{reviewStatusLabel(job)}</span>
                      {isPublicationTask ? <span className="status-pill publication">发布任务</span> : null}
                      {isRemixTask ? <span className="status-pill pending">解说二创</span> : null}
                      {manualEditStatus ? (
                        <span className="status-pill pending">{manualEditStatus}</span>
                      ) : null}
                      {job.publication_summary ? <span className="muted line-clamp-1">{job.publication_summary}</span> : null}
                      <span className="muted">{job.progress_percent ?? 0}%</span>
                    </div>
                  </td>
                  <td>
                    <div className="step-mini-list">
                      {job.steps.slice(0, 4).map((step) => (
                        <span key={step.id} className={`status-pill ${step.status}`}>
                          {stepLabel(step.step_name)}
                        </span>
                      ))}
                      {job.steps.length > 4 && <span className="muted">+{job.steps.length - 4}</span>}
                    </div>
                  </td>
                  <td>{formatDate(job.updated_at)}</td>
                  <td>
                    <div className="job-queue-actions">
                      {showPreview ? (
                        <Link
                          className="button ghost button-sm job-icon-button job-preview-cta"
                          to={`/final-review?job=${encodeURIComponent(job.id)}`}
                          aria-label="去审看"
                          title="去审看"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <JobActionIcon name="play" />
                        </Link>
                      ) : null}
                      {showReviewAction ? (
                        <button
                          className={classNames(
                            "button ghost button-sm job-icon-button",
                            "job-review-cta",
                            highlightedReviewAction && "job-review-cta-active",
                          )}
                          type="button"
                          aria-label={reviewActionLabel(job, t)}
                          title={reviewActionLabel(job, t)}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenReview?.(job.id);
                          }}
                        >
                          <JobActionIcon name="alert" />
                        </button>
                      ) : null}
                      {isRemixTask && ["pending", "failed", "cancelled", "done"].includes(job.status) ? (
                        <button
                          className="button primary button-sm job-action-text-button job-restart-cta"
                          type="button"
                          disabled={isStartingRemixProduction}
                          aria-label={isStartingRemixProduction ? "启动中" : job.status === "pending" ? "开始" : t("jobs.actions.restart")}
                          title={isStartingRemixProduction ? "启动中" : job.status === "pending" ? "开始" : t("jobs.actions.restart")}
                          onClick={(event) => {
                            event.stopPropagation();
                            onStartRemixProduction?.(job.id, job.status !== "pending");
                          }}
                        >
                          {job.status === "pending" ? "START" : "RESTART"}
                        </button>
                      ) : null}
                      {!isPublicationTask && !isRemixTask ? (
                        <Link
                          className={classNames(
                            "button button-sm job-icon-button",
                            manualEditorReady ? "job-manual-edit-cta" : "ghost",
                          )}
                          to={`/jobs/${job.id}/manual-editor`}
                          aria-label="手动调整"
                          title="手动调整"
                          onMouseEnter={() => prefetchManualEditor(job.id)}
                          onFocus={() => prefetchManualEditor(job.id)}
                          onClick={(event) => event.stopPropagation()}
                        >
                          <JobActionIcon name="scissors" />
                        </Link>
                      ) : null}
                      {showCancel ? (
                        <button
                          className="button ghost button-sm job-icon-button job-cancel-cta"
                          type="button"
                          disabled={isCancelling}
                          aria-label={isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
                          title={isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
                          onClick={(event) => {
                            event.stopPropagation();
                            onCancel(job.id);
                          }}
                        >
                          <JobActionIcon name={isCancelling ? "spinner" : "x"} />
                        </button>
                      ) : null}
                      {!isRemixTask ? (
                        <>
                          <button
                            className="button primary button-sm job-action-text-button job-restart-cta"
                            type="button"
                            disabled={isRestarting || !isRestartableJobStatus(job.status)}
                            aria-label={
                              isRestarting
                                ? t("jobs.actions.restarting")
                                : isRestartableJobStatus(job.status) ? t("jobs.actions.restart") : t("jobs.actions.restartUnavailable")
                            }
                            onClick={(event) => {
                              event.stopPropagation();
                              onRestart(job.id);
                            }}
                            title={
                              isRestarting
                                ? t("jobs.actions.restarting")
                                : isRestartableJobStatus(job.status) ? t("jobs.actions.restart") : t(getRestartUnavailableReason(job.status))
                            }
                          >
                            RESTART
                          </button>
                          <button
                            className="button danger button-sm job-icon-button job-delete-cta"
                            type="button"
                            disabled={isDeleting}
                            aria-label={isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
                            title={isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
                            onClick={(event) => {
                              event.stopPropagation();
                              onDelete(job.id);
                            }}
                          >
                            <JobActionIcon name={isDeleting ? "spinner" : "trash"} />
                          </button>
                        </>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {currentPage !== undefined && pageSize !== undefined && onPageChange ? (
        <div className="toolbar top-gap">
          <div className="muted">{`每页 ${pageSize} 条，当前 ${jobs.length} 条`}</div>
          <div className="toolbar">
            <button
              className="button ghost button-sm job-icon-button"
              type="button"
              disabled={!canGoPrev}
              aria-label="上一页"
              title="上一页"
              onClick={() => onPageChange(currentPage - 1)}
            >
              <JobActionIcon name="chevron-left" />
            </button>
            <button
              className="button button-sm job-icon-button"
              type="button"
              disabled={!canGoNext}
              aria-label="下一页"
              title="下一页"
              onClick={() => onPageChange(currentPage + 1)}
            >
              <JobActionIcon name="chevron-right" />
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

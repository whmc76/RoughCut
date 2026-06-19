import type { Job } from "../../types";
import { useState } from "react";
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

function isLocalOutputJob(job: Job) {
  return Boolean(job.output_dir?.trim());
}

function hasJobStarted(job: Job) {
  if (job.status === "running" || job.status === "processing" || job.status === "awaiting_manual_edit" || job.status === "needs_review") return true;
  return job.steps.some((step) => Boolean(step.started_at));
}

function isTerminalJob(job: Job) {
  return job.status === "done" || job.status === "failed" || job.status === "cancelled";
}

function reviewPreviewText(job: Job, t: (key: string) => string) {
  const { manualDescription, filenameDescription } = splitVideoDescription(job.video_description);
  const cutEvidenceSummary = formatCutEvidenceSummary(job.timeline_diagnostics);
  if (job.awaiting_manual_edit) {
    return job.review_detail || "智能辅助模式预处理已完成。当前百分比不是渲染进度；任务仍在等待手动调整页正式提交渲染。";
  }
  if (job.status !== "needs_review") {
    return job.content_summary || job.content_subject || manualDescription || filenameDescription || t("jobs.queue.noSummary");
  }
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") {
    return job.quality_summary || cutEvidenceSummary || job.review_detail || "成片质量门发现异常，处理后继续生成平台文案。";
  }
  return job.content_summary || job.content_subject || job.review_detail || "内容异常门发现阻塞问题，处理后继续剪辑与渲染。";
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

function taskKindLabel(job: Job) {
  if (isPublicationJob(job)) return "发布任务";
  if (isRemixProductionJob(job)) return "影视二创";
  return "剪辑任务";
}

function JobQueueThumbnail({ job }: { job: Job }) {
  const contentThumbnailUrl = api.contentProfileThumbnailUrl(job.id, 0, job.updated_at);
  const coverThumbnailUrl = api.jobCoverThumbnailUrl(job.id, job.updated_at);
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
  isOpeningFolder?: boolean;
  isCancelling?: boolean;
  isRestarting?: boolean;
  isStartingRemixProduction?: boolean;
  isDeleting?: boolean;
  onSelect: (jobId: string) => void;
  onOpenReview?: (jobId: string) => void;
  onPublish?: (jobId: string) => void;
  onPreview?: (jobId: string) => void;
  onOpenFolder: (jobId: string) => void;
  onDownload: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onStartRemixProduction?: (jobId: string, force?: boolean) => void;
  onDelete: (jobId: string) => void;
  onOpenRemixProduction?: (jobId: string) => void;
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
  isOpeningFolder,
  isCancelling,
  isRestarting,
  isStartingRemixProduction,
  isDeleting,
  onSelect,
  onOpenReview,
  onPublish,
  onPreview,
  onOpenFolder,
  onDownload,
  onCancel,
  onRestart,
  onStartRemixProduction,
  onDelete,
  onOpenRemixProduction,
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
              const showReviewAction = job.status === "needs_review";
              const highlightedReviewAction = isHighlightedReviewAction(job);
              const { filenameDescription } = splitVideoDescription(job.video_description);
              const cutEvidenceSummary = formatCutEvidenceSummary(job.timeline_diagnostics);
              const showPreview = job.status === "done";
              const showOpenFolder = job.status === "done";
              const showDownload = job.status === "done" && !isLocalOutputJob(job);
              const showCancel = !isRemixTask && hasJobStarted(job) && !isTerminalJob(job);
              const manualEditStatus = awaitingManualEditLabel(job, t);
              const manualEditorReady = canOpenManualEditorFromQueue(job);

              return (
                <tr
                  key={job.id}
                  className={classNames(
                    selectedJobId === job.id && "selected-row",
                    isPublicationTask && "job-row-publication",
                    isRemixTask && "job-row-remix-production",
                  )}
                  onClick={() => onSelect(job.id)}
                >
                  <td>
                    <div className="job-file-cell">
                      <JobQueueThumbnail job={job} />
                      <div className="job-file-copy">
                        <div className="row-title">{job.source_name}</div>
                        <div className="muted line-clamp-2">{reviewPreviewText(job, t)}</div>
                        {job.status !== "needs_review" && filenameDescription ? (
                          <div className="compact-top">
                            <span className="status-pill pending">{t("jobs.queue.filenameDerivedBadge")}</span>
                            <span className="muted"> {filenameDescription}</span>
                          </div>
                        ) : null}
                        <div className="mode-chip-list compact-top">
                          <span className={classNames("mode-chip", job.queue_task_kind === "publication" ? "publication" : "planned")}>
                            {taskKindLabel(job)}
                          </span>
                          <span className="mode-chip planned">{jobFlowModeLabel(job.job_flow_mode || "auto")}</span>
                          <span className="mode-chip">{workflowModeLabel(job.workflow_mode)}</span>
                          {job.enhancement_modes.map((mode) => (
                            <span key={mode} className="mode-chip subtle">
                              {enhancementBadgeLabel(job, mode)}
                            </span>
                          ))}
                        </div>
                        {job.auto_review_mode_enabled && job.auto_review_summary ? (
                          <div className="compact-top">
                            <span className={`status-pill ${autoReviewTone(job.auto_review_status)}`}>
                              {autoReviewBadgeLabel(job)}
                            </span>
                            <span className="muted"> {job.auto_review_summary}</span>
                          </div>
                        ) : null}
                        {cutEvidenceSummary ? (
                          <div className="compact-top">
                            <span className="status-pill pending">剪辑证据</span>
                            <span className="muted"> {cutEvidenceSummary}</span>
                          </div>
                        ) : null}
                        {job.avatar_delivery_summary ? (
                          <div className="compact-top">
                            <span className={`status-pill ${job.avatar_delivery_status || "pending"}`}>
                              数字人
                            </span>
                            <span className="muted"> {job.avatar_delivery_summary}</span>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="form-stack compact-top">
                      <span className={`status-chip ${jobStatusTone(job)}`}>{reviewStatusLabel(job)}</span>
                      {isPublicationTask ? <span className="status-pill publication">发布任务</span> : null}
                      {isRemixTask ? <span className="status-pill pending">影视二创</span> : null}
                      {manualEditStatus ? (
                        <span className="status-pill pending">{manualEditStatus}</span>
                      ) : null}
                      {job.publication_summary ? <span className="muted">{job.publication_summary}</span> : null}
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
                      {showReviewAction ? (
                        <button
                          className={classNames(
                            "button ghost button-sm",
                            "job-review-cta",
                            highlightedReviewAction && "job-review-cta-active",
                          )}
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenReview?.(job.id);
                          }}
                        >
                          {reviewActionLabel(job, t)}
                        </button>
                      ) : null}
                      {job.status === "done" && !isPublicationTask ? (
                        <button
                          className="button button-sm job-publish-cta"
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onPublish?.(job.id);
                          }}
                        >
                          <span className="job-publish-cta-rgb-mark" aria-hidden="true" />
                          <span>一键发布</span>
                        </button>
                      ) : null}
                      {isRemixTask ? (
                        <button
                          className="button button-sm"
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenRemixProduction?.(job.id);
                          }}
                        >
                          查看队列
                        </button>
                      ) : null}
                      {isRemixTask && ["pending", "failed", "cancelled", "done"].includes(job.status) ? (
                        <button
                          className="button primary button-sm job-restart-cta"
                          type="button"
                          disabled={isStartingRemixProduction}
                          onClick={(event) => {
                            event.stopPropagation();
                            onStartRemixProduction?.(job.id, job.status !== "pending");
                          }}
                        >
                          {isStartingRemixProduction
                            ? "启动中"
                            : job.status === "pending" ? "开始" : t("jobs.actions.restart")}
                        </button>
                      ) : null}
                      {!isPublicationTask && !isRemixTask ? (
                        <Link
                          className={classNames(
                            "button button-sm",
                            manualEditorReady ? "job-manual-edit-cta" : "ghost",
                          )}
                          to={`/jobs/${job.id}/manual-editor`}
                          onMouseEnter={() => prefetchManualEditor(job.id)}
                          onFocus={() => prefetchManualEditor(job.id)}
                          onClick={(event) => event.stopPropagation()}
                        >
                          手动调整
                        </Link>
                      ) : null}
                      {showPreview ? (
                        <button
                          className="button ghost button-sm"
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onPreview?.(job.id);
                          }}
                        >
                          {t("jobs.actions.preview")}
                        </button>
                      ) : null}
                      {showOpenFolder ? (
                        <button
                          className="button ghost button-sm"
                          type="button"
                          disabled={isOpeningFolder}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenFolder(job.id);
                          }}
                        >
                          {t("jobs.actions.openFolder")}
                        </button>
                      ) : null}
                      {showDownload ? (
                        <button
                          className="button ghost button-sm"
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onDownload(job.id);
                          }}
                        >
                          {t("jobs.actions.download")}
                        </button>
                      ) : null}
                      {showCancel ? (
                        <button
                          className="button ghost button-sm"
                          type="button"
                          disabled={isCancelling}
                          onClick={(event) => {
                            event.stopPropagation();
                            onCancel(job.id);
                          }}
                        >
                          {isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
                        </button>
                      ) : null}
                      {!isRemixTask ? (
                        <>
                          <button
                            className="button primary button-sm job-restart-cta"
                            type="button"
                            disabled={isRestarting || !isRestartableJobStatus(job.status)}
                            onClick={(event) => {
                              event.stopPropagation();
                              onRestart(job.id);
                            }}
                            title={isRestartableJobStatus(job.status) ? undefined : t(getRestartUnavailableReason(job.status))}
                          >
                            {isRestarting
                              ? t("jobs.actions.restarting")
                              : isRestartableJobStatus(job.status) ? t("jobs.actions.restart") : t("jobs.actions.restartUnavailable")}
                          </button>
                          <button
                            className="button danger button-sm"
                            type="button"
                            disabled={isDeleting}
                            onClick={(event) => {
                              event.stopPropagation();
                              onDelete(job.id);
                            }}
                          >
                            {isDeleting ? t("jobs.actions.deleting") : t("jobs.actions.delete")}
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
              className="button ghost button-sm"
              type="button"
              disabled={!canGoPrev}
              onClick={() => onPageChange(currentPage - 1)}
            >
              上一页
            </button>
            <button
              className="button button-sm"
              type="button"
              disabled={!canGoNext}
              onClick={() => onPageChange(currentPage + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

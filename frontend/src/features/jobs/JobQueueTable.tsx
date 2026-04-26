import type { Job } from "../../types";
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
  if (job.status === "running" || job.status === "processing" || job.status === "needs_review") return true;
  return job.steps.some((step) => Boolean(step.started_at));
}

function isTerminalJob(job: Job) {
  return job.status === "done" || job.status === "failed" || job.status === "cancelled";
}

function reviewPreviewText(job: Job, t: (key: string) => string) {
  const { manualDescription, filenameDescription } = splitVideoDescription(job.video_description);
  const cutEvidenceSummary = formatCutEvidenceSummary(job.timeline_diagnostics);
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
  isDeleting?: boolean;
  onSelect: (jobId: string) => void;
  onOpenReview?: (jobId: string) => void;
  onPublish?: (jobId: string) => void;
  onOpenFolder: (jobId: string) => void;
  onDownload: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onRestart: (jobId: string) => void;
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
  isOpeningFolder,
  isCancelling,
  isRestarting,
  isDeleting,
  onSelect,
  onOpenReview,
  onPublish,
  onOpenFolder,
  onDownload,
  onCancel,
  onRestart,
  onDelete,
  onPageChange,
}: JobQueueTableProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const canGoPrev = (currentPage ?? 0) > 0 && !isFetchingPage;
  const canGoNext = Boolean(hasMore) && !isFetchingPage;
  const prefetchManualEditor = (jobId: string) => {
    void queryClient.prefetchQuery({
      queryKey: ["job-manual-editor", jobId],
      queryFn: () => api.getJobManualEditor(jobId),
      staleTime: 15_000,
    });
  };
  const warmManualEditorAssets = (jobId: string) => {
    void queryClient.prefetchQuery({
      queryKey: ["job-manual-editor-assets", jobId],
      queryFn: () => api.warmJobManualEditorAssets(jobId),
      staleTime: 10_000,
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
              const showReviewAction = job.status === "needs_review";
              const highlightedReviewAction = isHighlightedReviewAction(job);
              const { filenameDescription } = splitVideoDescription(job.video_description);
              const cutEvidenceSummary = formatCutEvidenceSummary(job.timeline_diagnostics);
              const showOpenFolder = job.status === "done" && isLocalOutputJob(job);
              const showDownload = job.status === "done" && !isLocalOutputJob(job);
              const showCancel = hasJobStarted(job) && !isTerminalJob(job);

              return (
                <tr key={job.id} className={classNames(selectedJobId === job.id && "selected-row")} onClick={() => onSelect(job.id)}>
                  <td>
                    <div className="job-file-cell">
                      <img
                        className="job-queue-thumb"
                        src={api.contentProfileThumbnailUrl(job.id, 0, job.updated_at)}
                        alt={job.source_name}
                        loading="lazy"
                        decoding="async"
                        onLoad={(event) => {
                          event.currentTarget.style.display = "";
                          event.currentTarget.nextElementSibling?.classList.remove("visible");
                        }}
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                          event.currentTarget.nextElementSibling?.classList.add("visible");
                        }}
                      />
                      <div className="job-queue-thumb job-queue-thumb-fallback" aria-hidden="true">
                        {t("jobs.queue.noThumbnail")}
                      </div>
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
                      {job.status === "done" ? (
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
                      <Link
                        className="button button-sm job-manual-edit-cta"
                        to={`/jobs/${job.id}/manual-editor`}
                        onMouseEnter={() => prefetchManualEditor(job.id)}
                        onFocus={() => prefetchManualEditor(job.id)}
                        onPointerDown={() => {
                          prefetchManualEditor(job.id);
                          warmManualEditorAssets(job.id);
                        }}
                        onClick={(event) => event.stopPropagation()}
                      >
                        手动调整
                      </Link>
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

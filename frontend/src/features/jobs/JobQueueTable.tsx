import type { Job } from "../../types";
import { api } from "../../api";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import {
  autoReviewBadgeLabel,
  autoReviewTone,
  enhancementModeLabel,
  getRestartUnavailableReason,
  isRestartableJobStatus,
  stepLabel,
  workflowModeLabel,
} from "./constants";

function resolvePendingReviewStep(job: Job) {
  return job.steps.find((step) => (step.step_name === "summary_review" || step.step_name === "final_review") && step.status === "pending")
    ?? job.steps.find((step) => (step.step_name === "summary_review" || step.step_name === "final_review") && step.status !== "done")
    ?? null;
}

function reviewActionLabel(job: Job, t: (key: string) => string) {
  if (job.status !== "needs_review") return t("jobs.actions.review");
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") return "需要最终审核";
  if (reviewStep?.step_name === "summary_review") return "需要预审核";
  return "打开审核";
}

function isHighlightedReviewAction(job: Job) {
  if (job.status !== "needs_review") return false;
  const reviewStep = resolvePendingReviewStep(job);
  return reviewStep?.step_name === "summary_review" || reviewStep?.step_name === "final_review";
}

function reviewStatusLabel(job: Job): string {
  if (job.status !== "needs_review") return statusLabel(job.status);
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") return "最终核对";
  if (reviewStep?.step_name === "summary_review") return "预审核";
  return statusLabel(job.status);
}

function reviewPreviewText(job: Job, t: (key: string) => string) {
  if (job.status !== "needs_review") {
    return job.content_summary || job.content_subject || t("jobs.queue.noSummary");
  }
  const reviewStep = resolvePendingReviewStep(job);
  if (reviewStep?.step_name === "final_review") {
    return job.quality_summary || "等待审核成片后继续。";
  }
  return job.content_summary || job.content_subject || "等待信息核对后继续。";
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
  onOpenFolder: (jobId: string) => void;
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
  onOpenFolder,
  onCancel,
  onRestart,
  onDelete,
  onPageChange,
}: JobQueueTableProps) {
  const { t } = useI18n();
  const canGoPrev = (currentPage ?? 0) > 0 && !isFetchingPage;
  const canGoNext = Boolean(hasMore) && !isFetchingPage;

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
              const highlightedReviewAction = isHighlightedReviewAction(job);

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
                      <span className={`status-chip ${job.status}`}>{reviewStatusLabel(job)}</span>
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
                      <button
                        className={classNames(
                          "button ghost button-sm",
                          "job-review-cta",
                          highlightedReviewAction && "job-review-cta-active",
                        )}
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (job.status === "needs_review") {
                            onOpenReview?.(job.id);
                            return;
                          }
                          onSelect(job.id);
                        }}
                      >
                        {reviewActionLabel(job, t)}
                      </button>
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
                      <a
                        className="button ghost button-sm"
                        href={`/api/v1/jobs/${job.id}/download`}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {t("jobs.actions.download")}
                      </a>
                      <button
                        className="button ghost button-sm"
                        type="button"
                        disabled={job.status === "done" || job.status === "failed" || job.status === "cancelled" || isCancelling}
                        onClick={(event) => {
                          event.stopPropagation();
                          onCancel(job.id);
                        }}
                      >
                        {isCancelling ? t("jobs.actions.cancelling") : t("jobs.actions.cancel")}
                      </button>
                      <button
                        className="button primary button-sm"
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

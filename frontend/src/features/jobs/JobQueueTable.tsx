import type { Job } from "../../types";
import { api } from "../../api";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames, formatDate, statusLabel } from "../../utils";
import { enhancementModeLabel, stepLabel, workflowModeLabel } from "./constants";

type JobQueueTableProps = {
  jobs: Job[];
  selectedJobId: string | null;
  isLoading: boolean;
  errorMessage?: string;
  isOpeningFolder?: boolean;
  isCancelling?: boolean;
  isRestarting?: boolean;
  isDeleting?: boolean;
  onSelect: (jobId: string) => void;
  onOpenFolder: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onDelete: (jobId: string) => void;
};

export function JobQueueTable({
  jobs,
  selectedJobId,
  isLoading,
  errorMessage,
  isOpeningFolder,
  isCancelling,
  isRestarting,
  isDeleting,
  onSelect,
  onOpenFolder,
  onCancel,
  onRestart,
  onDelete,
}: JobQueueTableProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader title={t("jobs.queue.title")} description={`#${jobs.length}`} />
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
            {jobs.map((job) => (
              <tr key={job.id} className={classNames(selectedJobId === job.id && "selected-row")} onClick={() => onSelect(job.id)}>
                <td>
                  <div className="job-file-cell">
                    <img
                      className="job-queue-thumb"
                      src={api.contentProfileThumbnailUrl(job.id, 0)}
                      alt={job.source_name}
                      loading="lazy"
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
                      <div className="muted line-clamp-2">{job.content_summary || job.content_subject || t("jobs.queue.noSummary")}</div>
                      <div className="mode-chip-list compact-top">
                        <span className="mode-chip">{workflowModeLabel(job.workflow_mode)}</span>
                        {job.enhancement_modes.map((mode) => (
                          <span key={mode} className="mode-chip subtle">
                            {enhancementModeLabel(mode)}
                          </span>
                        ))}
                      </div>
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
                    <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
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
                      className="button ghost button-sm"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect(job.id);
                      }}
                    >
                      {job.status === "needs_review" ? "核对配置" : t("jobs.actions.review")}
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
                      disabled={isRestarting}
                      onClick={(event) => {
                        event.stopPropagation();
                        onRestart(job.id);
                      }}
                    >
                      {isRestarting ? t("jobs.actions.restarting") : t("jobs.actions.restart")}
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
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

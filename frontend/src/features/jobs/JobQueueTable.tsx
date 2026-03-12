import type { Job } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { classNames, formatDate, statusLabel } from "../../utils";
import { stepLabel } from "./constants";

type JobQueueTableProps = {
  jobs: Job[];
  selectedJobId: string | null;
  isLoading: boolean;
  errorMessage?: string;
  onSelect: (jobId: string) => void;
};

export function JobQueueTable({ jobs, selectedJobId, isLoading, errorMessage, onSelect }: JobQueueTableProps) {
  return (
    <section className="panel">
      <PanelHeader title="任务队列" description={`共 ${jobs.length} 条`} />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>文件</th>
              <th>状态</th>
              <th>步骤</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={4}><EmptyState message="正在加载..." /></td>
              </tr>
            )}
            {errorMessage && (
              <tr>
                <td colSpan={4}><EmptyState message={errorMessage} tone="error" /></td>
              </tr>
            )}
            {jobs.map((job) => (
              <tr key={job.id} className={classNames(selectedJobId === job.id && "selected-row")} onClick={() => onSelect(job.id)}>
                <td>
                  <div className="row-title">{job.source_name}</div>
                  <div className="muted line-clamp-2">{job.content_summary || job.content_subject || "暂无摘要"}</div>
                </td>
                <td>
                  <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

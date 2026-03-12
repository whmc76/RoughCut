import type { ContentProfileReview, Job, JobActivity, JobTimeline, Report } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { formatDate, statusLabel } from "../../utils";
import { JobContentProfileSection } from "./JobContentProfileSection";
import { JobSubtitleReportSection } from "./JobSubtitleReportSection";
import { stepLabel } from "./constants";

type JobDetailPanelProps = {
  selectedJobId: string | null;
  selectedJob?: Job;
  isLoading: boolean;
  activity?: JobActivity;
  report?: Report;
  timeline?: JobTimeline;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isConfirmingProfile: boolean;
  isApplyingReview: boolean;
  isCancelling: boolean;
  isRestarting: boolean;
  onContentFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onConfirmProfile: () => void;
  onOpenFolder: () => void;
  onCancel: () => void;
  onRestart: () => void;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
};

export function JobDetailPanel({
  selectedJobId,
  selectedJob,
  isLoading,
  activity,
  report,
  timeline,
  contentProfile,
  contentSource,
  contentDraft,
  contentKeywords,
  isConfirmingProfile,
  isApplyingReview,
  isCancelling,
  isRestarting,
  onContentFieldChange,
  onKeywordsChange,
  onConfirmProfile,
  onOpenFolder,
  onCancel,
  onRestart,
  onApplyReview,
}: JobDetailPanelProps) {
  return (
    <aside className="panel detail-panel">
      {!selectedJobId && <EmptyState message="选择一条任务后显示详情" />}
      {selectedJobId && isLoading && <EmptyState message="加载详情中..." />}
      {selectedJob && (
        <>
          <PanelHeader title={selectedJob.source_name} description={selectedJob.id} actions={<span className={`status-chip ${selectedJob.status}`}>{statusLabel(selectedJob.status)}</span>} />

          <div className="detail-actions">
            <button className="button ghost" onClick={onOpenFolder}>
              打开文件夹
            </button>
            <a className="button ghost" href={`/api/v1/jobs/${selectedJob.id}/download`} target="_blank" rel="noreferrer">
              下载成片
            </a>
            <button
              className="button ghost"
              disabled={selectedJob.status === "done" || selectedJob.status === "failed" || selectedJob.status === "cancelled" || isCancelling}
              onClick={onCancel}
            >
              {isCancelling ? "取消中..." : "取消"}
            </button>
            <button className="button primary" onClick={onRestart} disabled={isRestarting}>
              {isRestarting ? "重启中..." : "重新开始"}
            </button>
          </div>

          <section className="detail-block">
            <div className="detail-key">当前活动</div>
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
              <div className="muted">暂无活动步骤</div>
            )}
          </section>

          <section className="detail-block">
            <div className="detail-key">步骤状态</div>
            <div className="steps-list">
              {selectedJob.steps.map((step) => (
                <div key={step.id} className="step-row">
                  <span>{stepLabel(step.step_name)}</span>
                  <span className={`status-chip ${step.status}`}>{statusLabel(step.status)}</span>
                </div>
              ))}
            </div>
          </section>

          <JobContentProfileSection
            jobId={selectedJob.id}
            contentProfile={contentProfile}
            contentSource={contentSource}
            contentDraft={contentDraft}
            contentKeywords={contentKeywords}
            isSaving={isConfirmingProfile}
            onFieldChange={onContentFieldChange}
            onKeywordsChange={onKeywordsChange}
            onConfirm={onConfirmProfile}
          />

          <JobSubtitleReportSection report={report} isApplying={isApplyingReview} onApplyReview={onApplyReview} />

          <section className="detail-block">
            <div className="detail-key">时间线与事件</div>
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
              <summary>查看剪辑时间线 JSON</summary>
              <pre className="json-preview">{JSON.stringify(timeline?.data ?? {}, null, 2)}</pre>
            </details>
          </section>
        </>
      )}
    </aside>
  );
}

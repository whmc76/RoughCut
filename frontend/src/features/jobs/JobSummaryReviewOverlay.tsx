import type { ContentProfileReview } from "../../types";
import { JobContentProfileSection } from "./JobContentProfileSection";

type JobSummaryReviewOverlayProps = {
  jobId: string;
  jobTitle: string;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isConfirmingProfile: boolean;
  reviewStepStatus?: string | null;
  reviewDetail?: string | null;
  reviewReasons?: string[];
  blockingReasons?: string[];
  onContentFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onConfirmProfile: () => void;
};

function uniqueStrings(values: Array<string | null | undefined>) {
  return [...new Set(values.filter((value): value is string => Boolean(value && value.trim())))];
}

export function JobSummaryReviewOverlay({
  jobId,
  jobTitle,
  contentProfile,
  contentSource,
  contentDraft,
  contentKeywords,
  isConfirmingProfile,
  reviewStepStatus,
  reviewDetail,
  reviewReasons,
  blockingReasons,
  onContentFieldChange,
  onKeywordsChange,
  onConfirmProfile,
}: JobSummaryReviewOverlayProps) {
  const summaryReasons = uniqueStrings([
    ...(reviewReasons ?? contentProfile?.review_reasons ?? []),
    ...(blockingReasons ?? contentProfile?.blocking_reasons ?? []),
    contentProfile?.identity_review?.reason,
  ]);
  const stepStatus = reviewStepStatus ?? contentProfile?.review_step_status ?? "pending";
  const stepDetail = reviewDetail ?? contentProfile?.review_step_detail ?? contentProfile?.identity_review?.reason ?? "";

  return (
    <section className="detail-block">
      <div className="detail-key">摘要核对</div>
      <div className="timeline-item">
        <div className="toolbar">
          <div>
            <strong>{jobTitle}</strong>
            <div className="muted">任务 {jobId}</div>
          </div>
          <span className={`status-pill ${stepStatus}`}>{stepStatus}</span>
        </div>

        {stepDetail ? <div className="top-gap">{stepDetail}</div> : null}

        {summaryReasons.length ? (
          <div className="top-gap">
            <div className="muted">核对原因</div>
            <div className="timeline-list">
              {summaryReasons.map((reason) => (
                <div key={reason} className="timeline-item">
                  {reason}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="toolbar top-gap">
          <button className="button primary" onClick={onConfirmProfile} disabled={isConfirmingProfile}>
            {isConfirmingProfile ? "正在保存..." : "确认摘要并继续执行"}
          </button>
        </div>
      </div>

      <JobContentProfileSection
        jobId={jobId}
        contentProfile={contentProfile}
        contentSource={contentSource}
        contentDraft={contentDraft}
        contentKeywords={contentKeywords}
        isSaving={isConfirmingProfile}
        reviewMode
        onFieldChange={onContentFieldChange}
        onKeywordsChange={onKeywordsChange}
        onConfirm={onConfirmProfile}
      />
    </section>
  );
}

import { api } from "../../api";
import type { ContentProfileReview } from "../../types";
import { JobContentProfileSection } from "./JobContentProfileSection";

type JobSummaryReviewOverlayProps = {
  jobId: string;
  jobTitle: string;
  thumbnailVersion?: string | null;
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

function uniqueNonEmptyStrings(values: Array<string | null | undefined>) {
  return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))];
}

export function JobSummaryReviewOverlay({
  jobId,
  jobTitle,
  thumbnailVersion,
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
  const ocrEvidence = contentProfile?.ocr_evidence ?? {};
  const transcriptEvidence = contentProfile?.transcript_evidence ?? {};
  const entityResolutionTrace = contentProfile?.entity_resolution_trace ?? {};
  const ocrSummary = String(ocrEvidence.visible_text || "").trim();
  const ocrDetail = uniqueNonEmptyStrings([
    ocrEvidence.frame_count ? `${ocrEvidence.frame_count} 帧` : "",
    ocrEvidence.line_count ? `${ocrEvidence.line_count} 行` : "",
  ]).join(" / ");
  const transcriptSummary = uniqueNonEmptyStrings([
    transcriptEvidence.provider ? String(transcriptEvidence.provider) : "",
    transcriptEvidence.model ? String(transcriptEvidence.model) : "",
  ]).join(" / ");
  const transcriptPrompt = String(transcriptEvidence.prompt || transcriptEvidence.context || transcriptEvidence.hotword || "").trim();
  const transcriptSnippet = String(
    transcriptEvidence.segments?.find?.((item: { text?: string }) => String(item?.text || "").trim())?.text || "",
  ).trim();
  const traceSummary = String(entityResolutionTrace.summary || entityResolutionTrace.detail || entityResolutionTrace.trace || "").trim();
  const hasEvidence = Boolean(ocrSummary || transcriptSummary || transcriptPrompt || transcriptSnippet || traceSummary);
  const stepStatus = reviewStepStatus ?? contentProfile?.review_step_status ?? "pending";
  const stepDetail = reviewDetail ?? contentProfile?.review_step_detail ?? contentProfile?.identity_review?.reason ?? "";

  return (
    <section className="detail-block summary-review-surface panel">
      <div className="detail-key">内容异常处理</div>
      <div className="summary-review-status-card">
        <div className="toolbar summary-review-heading">
          <div>
            <strong>{jobTitle}</strong>
            <div className="muted">任务 {jobId}</div>
          </div>
          <span className={`status-pill ${stepStatus}`}>{stepStatus}</span>
        </div>

        {stepDetail ? <div className="top-gap summary-review-lead">{stepDetail}</div> : null}

        {hasEvidence ? (
          <div className="top-gap summary-review-evidence">
            <div className="detail-key">画面与识别证据</div>
            <div className="thumbnail-strip top-gap">
              {[0, 1, 2].map((index) => (
                <img
                  key={index}
                  className="profile-thumb"
                  loading="lazy"
                  decoding="async"
                  src={api.contentProfileThumbnailUrl(jobId, index, thumbnailVersion)}
                  alt={`review-thumbnail-${index}`}
                />
              ))}
            </div>
            <div className="timeline-list top-gap">
              {ocrSummary ? (
                <div className="timeline-item summary-review-evidence-card">
                  <strong>OCR 文字</strong>
                  <div>{ocrSummary}</div>
                  {ocrDetail ? <div className="muted">{ocrDetail}</div> : null}
                </div>
              ) : null}
              {transcriptSummary ? (
                <div className="timeline-item summary-review-evidence-card">
                  <strong>转写证据</strong>
                  <div>{transcriptSummary}</div>
                  {transcriptPrompt ? <div className="muted">{transcriptPrompt}</div> : null}
                  {transcriptSnippet ? <div className="muted">{transcriptSnippet}</div> : null}
                </div>
              ) : null}
              {traceSummary ? (
                <div className="timeline-item summary-review-evidence-card">
                  <strong>解析轨迹</strong>
                  <div>{traceSummary}</div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {summaryReasons.length ? (
          <div className="top-gap summary-review-reasons">
            <div className="muted">异常原因</div>
            <div className="timeline-list">
              {summaryReasons.map((reason) => (
                <div key={reason} className="timeline-item summary-review-evidence-card">
                  {reason}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="toolbar top-gap summary-review-actions">
          <button type="button" className="button primary" onClick={onConfirmProfile} disabled={isConfirmingProfile}>
            {isConfirmingProfile ? "正在保存..." : "确认修正并继续执行"}
          </button>
        </div>
      </div>

        <JobContentProfileSection
          jobId={jobId}
          thumbnailVersion={thumbnailVersion}
          contentProfile={contentProfile}
          contentSource={contentSource}
        contentDraft={contentDraft}
        contentKeywords={contentKeywords}
        isSaving={isConfirmingProfile}
        showThumbnails={false}
        reviewMode
        onFieldChange={onContentFieldChange}
        onKeywordsChange={onKeywordsChange}
        onConfirm={onConfirmProfile}
      />
    </section>
  );
}

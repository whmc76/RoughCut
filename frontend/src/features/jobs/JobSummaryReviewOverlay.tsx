import { api } from "../../api";
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

function uniqueNonEmptyStrings(values: Array<string | null | undefined>) {
  return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))];
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

        {hasEvidence ? (
          <div className="top-gap">
            <div className="detail-key">画面与识别证据</div>
            <div className="thumbnail-strip top-gap">
              {[0, 1, 2].map((index) => (
                <img key={index} className="profile-thumb" src={api.contentProfileThumbnailUrl(jobId, index)} alt={`review-thumbnail-${index}`} />
              ))}
            </div>
            <div className="timeline-list top-gap">
              {ocrSummary ? (
                <div className="timeline-item">
                  <strong>OCR 文字</strong>
                  <div>{ocrSummary}</div>
                  {ocrDetail ? <div className="muted">{ocrDetail}</div> : null}
                </div>
              ) : null}
              {transcriptSummary ? (
                <div className="timeline-item">
                  <strong>转写证据</strong>
                  <div>{transcriptSummary}</div>
                  {transcriptPrompt ? <div className="muted">{transcriptPrompt}</div> : null}
                  {transcriptSnippet ? <div className="muted">{transcriptSnippet}</div> : null}
                </div>
              ) : null}
              {traceSummary ? (
                <div className="timeline-item">
                  <strong>解析轨迹</strong>
                  <div>{traceSummary}</div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

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

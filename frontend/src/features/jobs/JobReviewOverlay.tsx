import { useEffect, useState } from "react";

import type { ContentProfileReview, Job, JobActivity, Report } from "../../types";
import { useI18n } from "../../i18n";
import { JobFinalReviewOverlay } from "./JobFinalReviewOverlay";
import { JobSummaryReviewOverlay } from "./JobSummaryReviewOverlay";

export type JobReviewStep = "summary_review" | "final_review";

type JobReviewOverlayProps = {
  open: boolean;
  reviewStep: JobReviewStep;
  selectedJob?: Job;
  activity?: JobActivity;
  report?: Report;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isConfirmingProfile: boolean;
  isApplyingReview: boolean;
  isSubmittingFinalReview?: boolean;
  onContentFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onConfirmProfile: () => void;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
  onApproveFinalReview?: () => void;
  onRejectFinalReview?: (note: string) => void;
  onOpenFolder: () => void;
  onClose: () => void;
};

export function JobReviewOverlay({
  open,
  reviewStep,
  selectedJob,
  activity,
  report,
  contentProfile,
  contentSource,
  contentDraft,
  contentKeywords,
  isConfirmingProfile,
  isApplyingReview,
  isSubmittingFinalReview = false,
  onContentFieldChange,
  onKeywordsChange,
  onConfirmProfile,
  onApplyReview,
  onApproveFinalReview,
  onRejectFinalReview,
  onOpenFolder,
  onClose,
}: JobReviewOverlayProps) {
  const { t } = useI18n();
  const [rejectNote, setRejectNote] = useState("");
  const [selectedRejectReasons, setSelectedRejectReasons] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || reviewStep !== "final_review") {
      setRejectNote("");
      setSelectedRejectReasons([]);
    }
  }, [open, reviewStep, selectedJob?.id]);

  if (!open || !selectedJob) return null;

  const download = () => {
    window.open(`/api/v1/jobs/${selectedJob.id}/download`, "_blank", "noopener,noreferrer");
  };

  const previewSrc = `/api/v1/jobs/${selectedJob.id}/download/file?variant=packaged`;

  const openPreview = () => {
    window.open(previewSrc, "_blank", "noopener,noreferrer");
  };

  const toggleRejectReason = (reason: string) => {
    setSelectedRejectReasons((current) =>
      current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason],
    );
  };

  const handleRejectFinalReview = () => {
    const detail = rejectNote.trim();
    const structuredPrefix = selectedRejectReasons.length ? `问题分类：${selectedRejectReasons.join("、")}` : "";
    const note = [structuredPrefix, detail].filter(Boolean).join("；");
    if (!note.trim()) {
      window.alert("请输入退回修改说明。");
      return;
    }
    onRejectFinalReview?.(note);
  };

  return (
    <div className="floating-modal-backdrop review-overlay-backdrop" onClick={onClose} role="presentation">
      <div className="floating-modal-shell review-overlay-shell" role="dialog" aria-modal="true" aria-label={selectedJob.source_name} onClick={(event) => event.stopPropagation()}>
        <button className="button ghost floating-modal-close" type="button" onClick={onClose} aria-label={t("jobs.modal.closeAria")}>
          {t("jobs.modal.close")}
        </button>

        <section className="review-overlay-content">
          {reviewStep === "summary_review" ? (
            <JobSummaryReviewOverlay
              jobId={selectedJob.id}
              jobTitle={selectedJob.source_name}
              contentProfile={contentProfile}
              contentSource={contentSource}
              contentDraft={contentDraft}
              contentKeywords={contentKeywords}
              isConfirmingProfile={isConfirmingProfile}
              reviewStepStatus={contentProfile?.review_step_status ?? activity?.current_step?.status ?? null}
              reviewDetail={contentProfile?.review_step_detail ?? activity?.current_step?.detail ?? null}
              reviewReasons={contentProfile?.review_reasons}
              blockingReasons={contentProfile?.blocking_reasons}
              onContentFieldChange={onContentFieldChange}
              onKeywordsChange={onKeywordsChange}
              onConfirmProfile={onConfirmProfile}
            />
          ) : (
            <JobFinalReviewOverlay
              selectedJob={selectedJob}
              report={report}
              reviewDetail={activity?.current_step?.detail ?? null}
              rejectNote={rejectNote}
              previewSrc={previewSrc}
              selectedRejectReasons={selectedRejectReasons}
              isOpeningFolder={false}
              isDownloading={false}
              isPreviewing={false}
              isSubmittingDecision={isSubmittingFinalReview}
              isApplyingSubtitleReview={isApplyingReview}
              onPreview={openPreview}
              onDownload={download}
              onOpenFolder={onOpenFolder}
              onRejectNoteChange={setRejectNote}
              onToggleRejectReason={toggleRejectReason}
              onApplySubtitleReview={onApplyReview}
              onApprove={onApproveFinalReview}
              onReject={handleRejectFinalReview}
            />
          )}
        </section>
      </div>
    </div>
  );
}

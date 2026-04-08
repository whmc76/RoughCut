import { useState } from "react";
import type { CSSProperties } from "react";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
import { JobDetailModal } from "../features/jobs/JobDetailModal";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobReviewOverlay } from "../features/jobs/JobReviewOverlay";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import { useJobWorkspace } from "../features/jobs/useJobWorkspace";
import { useI18n } from "../i18n";
import { formatDate, statusLabel } from "../utils";

const jobsPageStyle: CSSProperties = {
  display: "grid",
  gap: 18,
  padding: "4px 0 0",
};

const jobsIntroStyle: CSSProperties = {
  display: "grid",
  gap: 18,
  padding: 28,
  borderRadius: 30,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  background:
    "radial-gradient(circle at 12% 18%, rgba(115, 154, 255, 0.18), transparent 28%), radial-gradient(circle at 84% 12%, rgba(107, 220, 197, 0.12), transparent 26%), linear-gradient(180deg, rgba(8, 11, 18, 0.97), rgba(6, 8, 12, 0.93))",
  boxShadow: "0 28px 68px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.03)",
};

const jobsIntroTopStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.15fr) minmax(280px, 0.85fr)",
  gap: 18,
  alignItems: "end",
};

const jobsLeadStyle: CSSProperties = {
  display: "grid",
  gap: 10,
  maxWidth: 760,
};

const jobsLeadTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: "clamp(28px, 3vw, 46px)",
  lineHeight: 0.98,
  letterSpacing: "-0.05em",
};

const jobsLeadTextStyle: CSSProperties = {
  margin: 0,
  color: "rgba(244, 239, 231, 0.66)",
  fontSize: 15,
  lineHeight: 1.55,
};

const jobsSignalStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 12,
};

const jobsSignalCardStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  minHeight: 88,
  padding: 16,
  borderRadius: 18,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  background: "rgba(255, 255, 255, 0.03)",
};

const jobsSignalLabelStyle: CSSProperties = {
  color: "rgba(244, 239, 231, 0.56)",
  fontSize: 10,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
};

const jobsSignalValueStyle: CSSProperties = {
  alignSelf: "end",
  fontSize: 28,
  lineHeight: 1,
  letterSpacing: "-0.05em",
};

const jobsWorkbenchStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.48fr) minmax(314px, 0.72fr)",
  gap: 18,
  alignItems: "start",
};

const jobsQueueStageStyle: CSSProperties = {
  display: "grid",
  gap: 16,
  padding: 24,
  borderRadius: 28,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  background:
    "linear-gradient(180deg, rgba(12, 15, 20, 0.94), rgba(8, 10, 14, 0.9))",
  boxShadow: "0 24px 56px rgba(0, 0, 0, 0.2)",
};

const jobsQueueHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  alignItems: "start",
};

const jobsQueueKickerStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  maxWidth: 680,
};

const jobsQueueTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: 20,
  letterSpacing: "-0.03em",
};

const jobsQueueDescriptionStyle: CSSProperties = {
  margin: 0,
  color: "rgba(244, 239, 231, 0.66)",
  lineHeight: 1.5,
};

const jobsQueueMetaStyle: CSSProperties = {
  display: "flex",
  gap: 10,
  justifyContent: "flex-end",
  alignItems: "center",
  flexWrap: "wrap",
  color: "rgba(244, 239, 231, 0.56)",
  fontSize: 11,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
};

const jobsRailStyle: CSSProperties = {
  display: "grid",
  gap: 18,
};

const jobsRailPanelStyle: CSSProperties = {
  display: "grid",
  gap: 14,
  padding: 22,
  borderRadius: 26,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  background:
    "linear-gradient(180deg, rgba(12, 14, 17, 0.96), rgba(7, 9, 12, 0.9))",
};

const jobsRailTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: 18,
  letterSpacing: "-0.03em",
};

const jobsRailDescriptionStyle: CSSProperties = {
  margin: 0,
  color: "rgba(244, 239, 231, 0.66)",
  lineHeight: 1.5,
};

const jobsActiveListStyle: CSSProperties = {
  display: "grid",
  gap: 12,
};

const jobsActiveRowStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 14,
  padding: "14px 0",
  borderTop: "1px solid rgba(255, 255, 255, 0.08)",
};

const jobsActiveRowFirstStyle: CSSProperties = {
  ...jobsActiveRowStyle,
  borderTop: 0,
  paddingTop: 0,
};

const jobsActiveCopyStyle: CSSProperties = {
  display: "grid",
  gap: 5,
  minWidth: 0,
};

const jobsActiveMetaStyle: CSSProperties = {
  display: "grid",
  justifyItems: "end",
  gap: 6,
  color: "rgba(244, 239, 231, 0.56)",
  fontSize: 12,
  flexShrink: 0,
};

const jobsCreationBandStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 0.72fr) minmax(0, 1.28fr)",
  gap: 18,
  alignItems: "start",
};

const jobsCreationShellStyle: CSSProperties = {
  display: "grid",
  gap: 14,
  padding: 20,
  borderRadius: 28,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  background:
    "linear-gradient(180deg, rgba(12, 14, 16, 0.95), rgba(7, 9, 11, 0.9))",
};

const jobsCreationTitleStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const jobsCreationTitleTextStyle: CSSProperties = {
  margin: 0,
  fontSize: 18,
  letterSpacing: "-0.03em",
};

const jobsCreationDescriptionStyle: CSSProperties = {
  margin: 0,
  color: "rgba(244, 239, 231, 0.66)",
  lineHeight: 1.5,
};

export function JobsPage() {
  const { t } = useI18n();
  const workspace = useJobWorkspace();
  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];
  const activeJobs = workspace.filteredJobs
    .filter((job) => job.status === "running" || job.status === "processing" || job.status === "needs_review")
    .slice(0, 4);
  const isReviewContext =
    workspace.activity.data?.current_step?.status === "needs_review" || workspace.selectedJob?.status === "needs_review";
  const activeReviewStep =
    workspace.activity.data?.current_step?.step_name === "summary_review" || workspace.activity.data?.current_step?.step_name === "final_review"
      ? workspace.activity.data.current_step.step_name
      : workspace.selectedJob?.steps.find(
        (step) =>
          (step.step_name === "summary_review" || step.step_name === "final_review")
          && step.status !== "done",
      )?.step_name;
  const reviewStep = activeReviewStep === "final_review" ? "final_review" : "summary_review";
  const isReviewJob = Boolean(workspace.selectedJobId && isReviewContext && activeReviewStep);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [reviewNoticeTone, setReviewNoticeTone] = useState<"success" | "error">("success");

  const showReviewNotice = (tone: "success" | "error", message: string) => {
    setReviewNoticeTone(tone);
    setReviewNotice(message);
    window.setTimeout(() => {
      setReviewNotice((current) => (current === message ? null : current));
    }, 5000);
  };

  const closeReviewOverlay = (shouldClearNotice = true) => {
    if (isReviewJob) workspace.setSelectedJobId(null);
    if (shouldClearNotice) {
      setReviewNotice(null);
    }
  };

  const confirmReviewProfile = () => {
    workspace.confirmProfile.mutate(undefined, {
      onSuccess: async () => {
        showReviewNotice("success", "摘要核对已确认，任务继续执行中，已返回队列。");
        await workspace.refreshAll();
        closeReviewOverlay(false);
      },
      onError: (error) => {
        showReviewNotice(
          "error",
          error instanceof Error
            ? error.message
            : `摘要核对提交失败：${String(error) || "请稍后重试。"}`,
        );
      },
    });
  };

  const reviewNoticeClass = reviewNoticeTone === "error" ? "notice top-gap notice-error" : "notice top-gap";

  return (
    <section className="page-stack jobs-page" style={jobsPageStyle}>
      <PageHeader
        eyebrow={t("jobs.page.eyebrow")}
        title={t("jobs.page.title")}
        description={t("jobs.page.description")}
        actions={
          <>
            <input
              className="input"
              value={workspace.keyword}
              onChange={(event) => workspace.setKeyword(event.target.value)}
              placeholder={t("jobs.page.searchPlaceholder")}
            />
            <button className="button ghost" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
          </>
        }
      />

      <section className="jobs-intro-plate" style={jobsIntroStyle}>
        <div style={jobsIntroTopStyle}>
          <div style={jobsLeadStyle}>
            <div className="page-eyebrow">{t("jobs.page.eyebrow")}</div>
            <h3 style={jobsLeadTitleStyle}>{t("jobs.page.queueTitle")}</h3>
            <p style={jobsLeadTextStyle}>{t("jobs.page.description")}</p>
          </div>
          <div style={jobsQueueMetaStyle}>
            <span>{t("jobs.page.activeWorkTitle")}</span>
            <strong>{activeJobs.length}</strong>
            <span>{t("jobs.page.selectedJob")}</span>
            <strong>{workspace.selectedJob?.source_name || "—"}</strong>
          </div>
        </div>
        <div style={jobsSignalStripStyle}>
          <article style={jobsSignalCardStyle}>
            <span style={jobsSignalLabelStyle}>{t("jobs.page.activeWorkRunning")}</span>
            <strong style={jobsSignalValueStyle}>{activeJobs.length}</strong>
          </article>
          <article style={jobsSignalCardStyle}>
            <span style={jobsSignalLabelStyle}>{t("jobs.page.activeWorkTotal")}</span>
            <strong style={jobsSignalValueStyle}>{workspace.jobs.data?.length ?? 0}</strong>
          </article>
          <article style={jobsSignalCardStyle}>
            <span style={jobsSignalLabelStyle}>{t("jobs.page.selectedJob")}</span>
            <strong style={jobsSignalValueStyle}>{workspace.selectedJob ? "1" : "0"}</strong>
          </article>
          <article style={jobsSignalCardStyle}>
            <span style={jobsSignalLabelStyle}>{t("jobs.page.createEyebrow")}</span>
            <strong style={jobsSignalValueStyle}>{uploadReadyLabel(workspace.upload.file?.name)}</strong>
          </article>
        </div>
      </section>

      {workspace.restartError ? (
        <div className="notice">
          {t("jobs.actions.restartFailed").replace("{error}", workspace.restartError)}
        </div>
      ) : null}
      {reviewNotice ? <div className={reviewNoticeClass}>{reviewNotice}</div> : null}

      <div className="jobs-workbench-shell" style={jobsWorkbenchStyle}>
        <section className="jobs-queue-stage" style={jobsQueueStageStyle}>
          <div style={jobsQueueHeaderStyle}>
            <div style={jobsQueueKickerStyle}>
              <div className="page-eyebrow">{t("jobs.page.queueEyebrow")}</div>
              <h3 style={jobsQueueTitleStyle}>{t("jobs.page.queueTitle")}</h3>
              <p style={jobsQueueDescriptionStyle}>
                {t("jobs.queue.title")} {workspace.filteredJobs.length ? `· ${workspace.filteredJobs.length} ${t("jobs.page.queueTitle")}` : ""}
              </p>
            </div>
            <div style={jobsQueueMetaStyle}>
              <span>{t("jobs.page.activeWorkTitle")}</span>
              <strong>{workspace.filteredJobs.length}</strong>
            </div>
          </div>

          <JobQueueTable
            jobs={workspace.filteredJobs}
            selectedJobId={workspace.selectedJobId}
            isLoading={workspace.jobs.isLoading}
            currentPage={workspace.jobsPage}
            pageSize={workspace.jobsPageSize}
            hasMore={workspace.hasMoreJobs}
            isFetchingPage={workspace.jobs.isFetching}
            onPageChange={(page) => workspace.setJobsPage(Math.max(0, page))}
            errorMessage={workspace.jobs.isError ? (workspace.jobs.error as Error).message : undefined}
            isOpeningFolder={workspace.openFolder.isPending}
            isCancelling={workspace.cancelJob.isPending}
            isRestarting={workspace.restartJob.isPending}
            isDeleting={workspace.deleteJob.isPending}
            onSelect={workspace.setSelectedJobId}
            onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
            onCancel={(jobId) => workspace.cancelJob.mutate(jobId)}
            onRestart={(jobId) => workspace.restartJob.mutate(jobId)}
            onDelete={(jobId) => workspace.deleteJob.mutate(jobId)}
          />
        </section>

        <aside className="jobs-live-rail" style={jobsRailStyle}>
          <section className="jobs-urgent-rail" style={jobsRailPanelStyle}>
            <div>
              <div className="page-eyebrow">{t("jobs.page.activeWorkTitle")}</div>
              <h3 style={jobsRailTitleStyle}>{t("jobs.page.activeWorkDescription")}</h3>
              <p style={jobsRailDescriptionStyle}>{t("jobs.page.activeWorkDescription")}</p>
            </div>
            <div className="stats-grid compact">
              <StatCard label={t("jobs.page.activeWorkRunning")} value={activeJobs.length} compact />
              <StatCard label={t("jobs.page.activeWorkTotal")} value={workspace.jobs.data?.length ?? 0} compact />
              <StatCard label={t("jobs.page.selectedJob")} value={workspace.selectedJob?.source_name || "—"} compact />
            </div>
            <div style={jobsActiveListStyle}>
              {activeJobs.length ? (
                activeJobs.map((job, index) => (
                  <article
                    key={job.id}
                    style={index === 0 ? jobsActiveRowFirstStyle : jobsActiveRowStyle}
                  >
                    <div style={jobsActiveCopyStyle}>
                      <div className="row-title">{job.source_name}</div>
                      <div className="muted">{job.content_summary || job.content_subject || t("jobs.queue.noSummary")}</div>
                    </div>
                    <div style={jobsActiveMetaStyle}>
                      <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                      <span>{formatDate(job.updated_at)}</span>
                    </div>
                  </article>
                ))
              ) : (
                <EmptyState message={t("jobs.page.activeWorkEmpty")} />
              )}
            </div>
          </section>

          <section className="jobs-creation-band" style={jobsCreationBandStyle}>
            <div className="jobs-creation-profile" style={jobsCreationShellStyle}>
              <div style={jobsCreationTitleStyle}>
                <div className="page-eyebrow">{t("jobs.page.createEyebrow")}</div>
                <h3 style={jobsCreationTitleTextStyle}>{t("jobs.page.profileSwitcherDescription")}</h3>
                <p style={jobsCreationDescriptionStyle}>{t("jobs.page.profileSwitcherDescription")}</p>
              </div>
              <ConfigProfileSwitcher compact description={t("jobs.page.profileSwitcherDescription")} />
            </div>

            <div className="jobs-upload-slot" style={jobsCreationShellStyle}>
              <div style={jobsCreationTitleStyle}>
                <div className="page-eyebrow">{t("jobs.page.createTitle")}</div>
                <h3 style={jobsCreationTitleTextStyle}>{t("jobs.upload.title")}</h3>
                <p style={jobsCreationDescriptionStyle}>{t("jobs.upload.description")}</p>
              </div>
              <JobUploadPanel
                upload={workspace.upload}
                languageOptions={languageOptions}
                workflowTemplateOptions={workflowTemplateOptions}
                workflowModeOptions={workflowModeOptions}
                enhancementOptions={enhancementOptions}
                onChange={workspace.setUpload}
                onSubmit={() => workspace.uploadJob.mutate()}
                isSubmitting={workspace.uploadJob.isPending}
              />
            </div>
          </section>
        </aside>
      </div>

      <JobReviewOverlay
        open={Boolean(workspace.selectedJobId && isReviewJob)}
        reviewStep={reviewStep}
        selectedJob={workspace.selectedJob}
        activity={workspace.activity.data}
        report={workspace.report.data}
        contentProfile={workspace.contentProfile.data}
        contentSource={workspace.contentSource}
        contentDraft={workspace.contentDraft}
        contentKeywords={workspace.contentKeywords}
        isConfirmingProfile={workspace.confirmProfile.isPending}
        isApplyingReview={workspace.applyReview.isPending}
        isSubmittingFinalReview={workspace.finalReviewDecision.isPending}
        onContentFieldChange={(field, value) => workspace.setContentDraft((prev) => ({ ...prev, [field]: value }))}
        onKeywordsChange={(value) =>
          workspace.setContentDraft((prev) => ({
            ...prev,
            keywords: value
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
          }))
        }
        onConfirmProfile={confirmReviewProfile}
        onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        onApproveFinalReview={() => workspace.finalReviewDecision.mutate({ decision: "approve" })}
        onRejectFinalReview={(note) => workspace.finalReviewDecision.mutate({ decision: "reject", note })}
        onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
        onClose={() => closeReviewOverlay()}
      />

      <JobDetailModal
        open={Boolean(workspace.selectedJobId && !isReviewJob)}
        title={workspace.selectedJob?.source_name}
        onClose={() => workspace.setSelectedJobId(null)}
      >
        <JobDetailPanel
          className="detail-panel-modal"
          selectedJobId={workspace.selectedJobId}
          selectedJob={workspace.selectedJob}
          isLoading={workspace.detail.isLoading}
          activity={workspace.activity.data}
          report={workspace.report.data}
          tokenUsage={workspace.tokenUsage.data}
          timeline={workspace.timeline.data}
          contentProfile={workspace.contentProfile.data}
          config={workspace.config.data}
          packaging={workspace.packaging.data}
          avatarMaterials={workspace.avatarMaterials.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          reviewEnhancementModes={workspace.reviewEnhancementModes}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          onContentFieldChange={(field, value) => workspace.setContentDraft((prev) => ({ ...prev, [field]: value }))}
          onKeywordsChange={(value) =>
            workspace.setContentDraft((prev) => ({
              ...prev,
              keywords: value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            }))
          }
          onConfirmProfile={() => workspace.confirmProfile.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && workspace.cancelJob.mutate(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && workspace.restartJob.mutate(workspace.selectedJob.id)}
          onDelete={() => workspace.selectedJob && workspace.deleteJob.mutate(workspace.selectedJob.id)}
          onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        />
      </JobDetailModal>
    </section>
  );
}

function uploadReadyLabel(fileName?: string) {
  if (!fileName) return "0";
  return fileName.length > 20 ? `${fileName.slice(0, 17)}…` : fileName;
}

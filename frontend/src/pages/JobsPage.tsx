import { useState } from "react";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
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
    <section className="page-stack jobs-page">
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

      <section className="jobs-workbench">
        {workspace.restartError ? (
          <div className="notice">
            {t("jobs.actions.restartFailed").replace("{error}", workspace.restartError)}
          </div>
        ) : null}
        {reviewNotice ? <div className={reviewNoticeClass}>{reviewNotice}</div> : null}

        <PageSection className="jobs-queue-lane" eyebrow={t("jobs.page.queueEyebrow")} title={t("jobs.page.queueTitle")}>
          <div className="jobs-workbench-grid">
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

            <aside className="jobs-urgent-rail">
              <PanelHeader title={t("jobs.page.activeWorkTitle")} description={t("jobs.page.activeWorkDescription")} />
              <div className="stats-grid compact">
                <StatCard label={t("jobs.page.activeWorkRunning")} value={activeJobs.length} compact />
                <StatCard label={t("jobs.page.activeWorkTotal")} value={workspace.jobs.data?.length ?? 0} compact />
                <StatCard label={t("jobs.page.selectedJob")} value={workspace.selectedJob?.source_name || "—"} compact />
              </div>
              <div className="list-stack">
                {activeJobs.length ? (
                  activeJobs.map((job) => (
                    <article key={job.id} className="jobs-urgent-row">
                      <div>
                        <div className="row-title">{job.source_name}</div>
                        <div className="muted">{job.content_summary || job.content_subject || t("jobs.queue.noSummary")}</div>
                      </div>
                      <div className="row-meta">
                        <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                        <span>{formatDate(job.updated_at)}</span>
                      </div>
                    </article>
                  ))
                ) : (
                  <EmptyState message={t("jobs.page.activeWorkEmpty")} />
                )}
              </div>
            </aside>
          </div>
        </PageSection>

        <PageSection className="jobs-creation-bay" eyebrow={t("jobs.page.createEyebrow")} title={t("jobs.page.createTitle")}>
          <div className="jobs-creation-grid">
            <section className="jobs-creation-profile">
              <ConfigProfileSwitcher compact description={t("jobs.page.profileSwitcherDescription")} />
            </section>

            <section className="jobs-creation-upload">
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
            </section>
          </div>
        </PageSection>
      </section>

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

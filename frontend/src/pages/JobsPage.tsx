import { useState } from "react";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
import { JobCreateModal } from "../features/jobs/JobCreateModal";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobReviewOverlay } from "../features/jobs/JobReviewOverlay";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import { useJobWorkspace } from "../features/jobs/useJobWorkspace";
import { useI18n } from "../i18n";
import { formatDate, statusLabel } from "../utils";

export function JobsPage() {
  const { t } = useI18n();
  const workspace = useJobWorkspace();
  const [createOpen, setCreateOpen] = useState(false);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [reviewNoticeTone, setReviewNoticeTone] = useState<"success" | "error">("success");
  const [reviewOverlayOpen, setReviewOverlayOpen] = useState(false);

  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];

  const reviewJobs = workspace.filteredJobs.filter((job) => job.status === "needs_review");
  const runningJobs = workspace.filteredJobs.filter((job) => job.status === "running" || job.status === "processing");
  const activeJobs = workspace.filteredJobs
    .filter((job) => job.status === "running" || job.status === "processing" || job.status === "needs_review")
    .slice(0, 3);

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
  const showReviewOverlay = Boolean(reviewOverlayOpen && workspace.selectedJobId && isReviewContext && activeReviewStep);

  const openJobReview = (jobId: string) => {
    setReviewOverlayOpen(true);
    workspace.setSelectedJobId(jobId);
  };

  const showReviewNotice = (tone: "success" | "error", message: string) => {
    setReviewNoticeTone(tone);
    setReviewNotice(message);
    window.setTimeout(() => {
      setReviewNotice((current) => (current === message ? null : current));
    }, 5000);
  };

  const closeReviewOverlay = (shouldClearNotice = true) => {
    if (showReviewOverlay) {
      setReviewOverlayOpen(false);
      workspace.setSelectedJobId(null);
    }
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
        title={t("jobs.page.title")}
        description={t("jobs.page.description")}
        actions={
          <div className="jobs-header-toolbar">
            <input
              className="input jobs-header-search-input"
              value={workspace.keyword}
              onChange={(event) => workspace.setKeyword(event.target.value)}
              placeholder={t("jobs.page.searchPlaceholder")}
            />
            <button className="button jobs-header-subtle-button" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
            <button className="button primary jobs-header-create-button" onClick={() => setCreateOpen(true)}>
              创建任务
            </button>
          </div>
        }
      />

      <section className="jobs-command-deck">
        <article className="jobs-command-card">
          <span>队列</span>
          <strong>{workspace.filteredJobs.length}</strong>
          <p>当前列表</p>
        </article>
        <article className="jobs-command-card">
          <span>待审核</span>
          <strong>{reviewJobs.length}</strong>
          <p>优先处理</p>
        </article>
        <article className="jobs-command-card">
          <span>运行中</span>
          <strong>{runningJobs.length}</strong>
          <p>正在处理</p>
        </article>
        <article className="jobs-command-card">
          <span>待上传</span>
          <strong>{uploadReadyLabel(workspace.upload.file?.name)}</strong>
          <p>选好素材后创建</p>
        </article>
      </section>

      <section className="jobs-queue-stage">
        <div className="jobs-stage-head">
          <div>
            <h3>任务列表</h3>
            <p>{workspace.filteredJobs.length ? `${workspace.filteredJobs.length} 个任务` : "当前没有任务"}</p>
          </div>
          <div className="jobs-stage-meta">
            <span>当前选中</span>
            <strong>{workspace.selectedJob?.source_name || "—"}</strong>
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
          onSelect={(jobId) => {
            setReviewOverlayOpen(false);
            workspace.setSelectedJobId(jobId);
          }}
          onOpenReview={openJobReview}
          onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
          onCancel={(jobId) => workspace.cancelJob.mutate(jobId)}
          onRestart={(jobId) => workspace.restartJob.mutate(jobId)}
          onDelete={(jobId) => workspace.deleteJob.mutate(jobId)}
        />
      </section>

      {workspace.restartError ? (
        <div className="notice">
          {t("jobs.actions.restartFailed").replace("{error}", workspace.restartError)}
        </div>
      ) : null}
      {reviewNotice ? <div className={reviewNoticeClass}>{reviewNotice}</div> : null}

      {activeJobs.length ? (
        <section className="jobs-active-band">
          <div className="jobs-stage-head">
            <div>
              <h3>需要处理</h3>
              <p>运行中和待审核任务在这里。</p>
            </div>
            <div className="jobs-stage-meta">
              <span>当前数量</span>
              <strong>{activeJobs.length}</strong>
            </div>
          </div>
          <div className="jobs-active-grid">
            {activeJobs.map((job) => (
              <article key={job.id} className="jobs-active-card">
                <div className="jobs-active-copy">
                  <strong>{job.source_name}</strong>
                  <p>{job.content_summary || job.content_subject || t("jobs.queue.noSummary")}</p>
                </div>
                <div className="jobs-active-meta">
                  <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                  <span>{formatDate(job.updated_at)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <section className="jobs-active-band">
          <div className="jobs-stage-head">
            <div>
              <h3>需要处理</h3>
              <p>当前没有运行中或待审核任务。</p>
            </div>
          </div>
          <EmptyState message={t("jobs.page.activeWorkEmpty")} />
        </section>
      )}

      <JobCreateModal open={createOpen} onClose={() => setCreateOpen(false)}>
        <section className="jobs-create-modal-content">
          <div className="jobs-stage-head">
            <div>
              <h3>创建任务</h3>
              <p>先选剪辑方案，再上传素材创建新任务。</p>
            </div>
            <div className="jobs-stage-meta">
              <span>创建流程</span>
              <strong>剪辑方案 + 创建任务</strong>
            </div>
          </div>

          <div className="jobs-create-modal-grid">
            <section className="jobs-create-modal-panel">
              <ConfigProfileSwitcher
                compact
                title="剪辑方案"
                description="这里决定新任务默认按哪套方案创建。"
              />
            </section>

            <section className="jobs-create-modal-panel">
              <JobUploadPanel
                upload={workspace.upload}
                languageOptions={languageOptions}
                workflowTemplateOptions={workflowTemplateOptions}
                workflowModeOptions={workflowModeOptions}
                enhancementOptions={enhancementOptions}
                onChange={workspace.setUpload}
                onSubmit={() =>
                  workspace.uploadJob.mutate(undefined, {
                    onSuccess: () => setCreateOpen(false),
                  })
                }
                isSubmitting={workspace.uploadJob.isPending}
              />
            </section>
          </div>
        </section>
      </JobCreateModal>

      <JobReviewOverlay
        open={showReviewOverlay}
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
        onContentFieldChange={(field, value) =>
          workspace.setContentDraft((prev) => {
            if (field !== "video_type") {
              return { ...prev, [field]: value };
            }
            const previousUnderstanding =
              typeof prev.content_understanding === "object" && !Array.isArray(prev.content_understanding)
                ? (prev.content_understanding as Record<string, unknown>)
                : {};
            return {
              ...prev,
              video_type: value,
              content_understanding: {
                ...previousUnderstanding,
                video_type: value,
              },
            };
          })
        }
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
    </section>
  );
}

function uploadReadyLabel(fileName?: string) {
  if (!fileName) return "未选择素材";
  return fileName.length > 20 ? `${fileName.slice(0, 17)}…` : fileName;
}

import { useRef, useState } from "react";

import { PageHeader } from "../components/ui/PageHeader";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
import { JobCreateModal } from "../features/jobs/JobCreateModal";
import { JobDetailModal } from "../features/jobs/JobDetailModal";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobReviewOverlay } from "../features/jobs/JobReviewOverlay";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import type { JobQueueFilter } from "../features/jobs/useJobWorkspace";
import { resolveJobReviewStep, type JobReviewStep, useJobWorkspace } from "../features/jobs/useJobWorkspace";
import { useI18n } from "../i18n";
import { classNames } from "../utils";

const QUEUE_FILTER_META: Record<JobQueueFilter, { label: string; description: string }> = {
  all: { label: "全部任务", description: "当前搜索范围内的全部任务。" },
  pending: { label: "排队中", description: "等待进入执行链路的任务。" },
  running: { label: "运行中", description: "正在执行中的任务。" },
  done: { label: "已完成", description: "已完成并可继续查看结果的任务。" },
  attention: { label: "待处理事项", description: "失败、待核对、已取消等需要人工介入的任务。" },
};

export function JobsPage() {
  const { t } = useI18n();
  const [createOpen, setCreateOpen] = useState(false);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [reviewNoticeTone, setReviewNoticeTone] = useState<"success" | "error">("success");
  const [pendingSubtitleRerun, setPendingSubtitleRerun] = useState<{ rerunStartStep: string | null; issueCode: string | null } | null>(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [reviewOverlayOpen, setReviewOverlayOpen] = useState(false);
  const [reviewStepOverride, setReviewStepOverride] = useState<JobReviewStep | null>(null);
  const queueStageRef = useRef<HTMLElement | null>(null);
  const workspace = useJobWorkspace({ isCreateOpen: createOpen });
  const selectedReviewJob =
    workspace.filteredJobs.find((job) => job.id === workspace.selectedJobId)
    ?? workspace.selectedJob;

  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];
  const queueFilterMeta = QUEUE_FILTER_META[workspace.queueFilter];

  const reviewStep = reviewStepOverride ?? workspace.reviewStep ?? resolveJobReviewStep(selectedReviewJob, workspace.activity.data);
  const activeReviewStep: JobReviewStep = reviewStep ?? "summary_review";
  const isReviewContext = selectedReviewJob?.status === "needs_review" && reviewStep !== null;
  const showDetailModal = Boolean(detailModalOpen && workspace.selectedJobId);
  const showReviewOverlay = Boolean(reviewOverlayOpen && workspace.selectedJobId && isReviewContext && reviewStep);
  const triggerSubtitleRerun = (decision: { issue_codes?: string[]; rerun_start_step?: string | null }) => {
    const issueCode = decision.issue_codes?.[0] || null;
    const rerunStartStep = decision.rerun_start_step || null;
    setPendingSubtitleRerun({ issueCode, rerunStartStep });
    workspace.rerunSubtitleDecision.mutate(
      {
        issueCode: issueCode || undefined,
        rerunStartStep: rerunStartStep || undefined,
      },
      {
        onSuccess: (result) => {
          showReviewNotice(
            "success",
            result.detail?.trim() || `已请求从 ${rerunStartStep || "推荐起点"} 重跑，任务会在调度器接管后继续。`,
          );
        },
        onError: (error) => {
          setPendingSubtitleRerun(null);
          showReviewNotice(
            "error",
            error instanceof Error
              ? error.message
              : `字幕重跑触发失败：${String(error) || "请稍后重试。"}`,
          );
        },
      },
    );
  };

  const openJobReview = (jobId: string) => {
    const queuedJob = workspace.filteredJobs.find((job) => job.id === jobId) ?? (workspace.selectedJob?.id === jobId ? workspace.selectedJob : null);
    setDetailModalOpen(false);
    setReviewStepOverride(resolveJobReviewStep(queuedJob));
    setReviewOverlayOpen(true);
    workspace.setSelectedJobId(jobId);
  };

  const openJobDetail = (jobId: string) => {
    setReviewOverlayOpen(false);
    setReviewStepOverride(null);
    setDetailModalOpen(true);
    workspace.setSelectedJobId(jobId);
  };

  const resolveJobName = (jobId: string) =>
    workspace.filteredJobs.find((job) => job.id === jobId)?.source_name
    ?? (workspace.selectedJob?.id === jobId ? workspace.selectedJob.source_name : null)
    ?? t("jobs.actions.targetFallback");

  const confirmAndRestartJob = (jobId: string) => {
    const message = t("jobs.actions.restartConfirm").replace("{name}", resolveJobName(jobId));
    if (!window.confirm(message)) return;
    workspace.restartJob.mutate(jobId);
  };

  const confirmAndCancelJob = (jobId: string) => {
    const message = `确认取消任务「${resolveJobName(jobId)}」？`;
    if (!window.confirm(message)) return;
    workspace.cancelJob.mutate(jobId);
  };

  const confirmAndDeleteJob = (jobId: string) => {
    const message = t("jobs.actions.deleteConfirm").replace("{name}", resolveJobName(jobId));
    if (!window.confirm(message)) return;
    workspace.deleteJob.mutate(jobId);
  };

  const confirmAndApplyReview = (targetId: string, action: "accepted" | "rejected") => {
    if (action === "rejected" && !window.confirm("确认退回这条字幕修正？")) {
      return;
    }
    workspace.applyReview.mutate({ targetId, action });
  };

  const confirmAndRejectFinalReview = (note: string) => {
    if (!window.confirm("确认退回最终审核？")) {
      return;
    }
    workspace.finalReviewDecision.mutate({ decision: "reject", note });
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
    setReviewStepOverride(null);
    setPendingSubtitleRerun(null);
    if (shouldClearNotice) {
      setReviewNotice(null);
    }
  };

  const closeDetailModal = () => {
    if (showDetailModal) {
      setDetailModalOpen(false);
      workspace.setSelectedJobId(null);
    }
    setReviewStepOverride(null);
    setPendingSubtitleRerun(null);
  };

  const focusQueue = (filter: JobQueueFilter) => {
    workspace.setQueueFilter(filter);
    queueStageRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
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
            <button type="button" className="button jobs-header-subtle-button" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
            <button type="button" className="button primary jobs-header-create-button" onClick={() => setCreateOpen(true)}>
              创建任务
            </button>
          </div>
        }
      />

      <section className="jobs-dashboard-row">
        <article className="jobs-dashboard-card">
          <div className="jobs-dashboard-head">
            <div>
              <span className="jobs-dashboard-eyebrow">任务队列仪表盘</span>
              <h3>把任务流转和处理压力收在一个面板里</h3>
            </div>
            <p>{workspace.keyword.trim() ? `搜索“${workspace.keyword.trim()}”后的统计` : "当前页任务队列统计"}</p>
          </div>
          <div className="jobs-dashboard-metrics">
            {[
              { key: "all" as const, label: "队列总数", value: workspace.queueStats.total, hint: "当前列表" },
              { key: "pending" as const, label: "排队中", value: workspace.queueStats.pending, hint: "等待执行" },
              { key: "running" as const, label: "运行中", value: workspace.queueStats.running, hint: "正在处理" },
              { key: "done" as const, label: "已完成", value: workspace.queueStats.done, hint: "可回看结果" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                className={classNames("jobs-dashboard-metric", workspace.queueFilter === item.key && "is-active")}
                onClick={() => focusQueue(item.key)}
              >
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <p>{item.hint}</p>
              </button>
            ))}
          </div>
        </article>

        <button
          type="button"
          className={classNames("jobs-attention-card", workspace.queueFilter === "attention" && "is-active")}
          onClick={() => focusQueue("attention")}
        >
          <span className="jobs-dashboard-eyebrow">待处理事项</span>
          <strong>{workspace.queueStats.attention}</strong>
          <p>失败、待核对、已取消等需要人工介入的任务统一从这里进入。</p>
          <div className="jobs-attention-breakdown">
            <span>待核对 {workspace.queueStats.needsReview}</span>
            <span>失败 {workspace.queueStats.failed}</span>
            <span>取消 {workspace.queueStats.cancelled}</span>
          </div>
        </button>
      </section>

      <section className="jobs-queue-stage" ref={queueStageRef}>
        <div className="jobs-stage-head">
          <div>
            <h3>任务列表</h3>
            <p>
              {workspace.filteredJobs.length
                ? `${queueFilterMeta.label} · ${workspace.filteredJobs.length} 个任务`
                : `${queueFilterMeta.label} · 当前没有任务`}
            </p>
          </div>
          <div className="jobs-stage-meta">
            <span>当前筛选</span>
            <strong>{queueFilterMeta.label}</strong>
            <button
              type="button"
              className="button ghost button-sm"
              onClick={() => focusQueue("all")}
              disabled={workspace.queueFilter === "all"}
            >
              查看全部
            </button>
          </div>
        </div>
        <p className="jobs-queue-stage-note">{queueFilterMeta.description}</p>

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
          onSelect={openJobDetail}
          onOpenReview={openJobReview}
          onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
          onCancel={confirmAndCancelJob}
          onRestart={confirmAndRestartJob}
          onDelete={confirmAndDeleteJob}
        />
      </section>

      {workspace.restartError ? (
        <div className="notice">
          {t("jobs.actions.restartFailed").replace("{error}", workspace.restartError)}
        </div>
      ) : null}
      {reviewNotice ? <div className={reviewNoticeClass}>{reviewNotice}</div> : null}

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

      <JobDetailModal
        open={showDetailModal}
        title={workspace.selectedJob?.source_name}
        onClose={closeDetailModal}
      >
        <JobDetailPanel
          selectedJobId={workspace.selectedJobId}
          className="detail-panel-modal"
          flowOnly
          selectedJob={workspace.selectedJob}
          isLoading={workspace.detail.isLoading}
          activity={workspace.activity.data}
          report={workspace.report.data}
          tokenUsage={workspace.tokenUsage.data}
          timeline={workspace.timeline.data}
          manualEditor={workspace.manualEditor.data}
          manualEditorAssets={workspace.manualEditorAssets.data}
          contentProfile={workspace.contentProfile.data}
          config={workspace.config.data}
          packaging={workspace.packaging.data}
          avatarMaterials={workspace.avatarMaterials.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          reviewEnhancementModes={workspace.reviewEnhancementModes}
          languageOptions={languageOptions}
          workflowTemplateOptions={workflowTemplateOptions}
          workflowModeOptions={workflowModeOptions}
          enhancementOptions={enhancementOptions}
          pendingInitialization={workspace.pendingInitialization}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isInitializing={workspace.initializeJob.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isTriggeringSubtitleRerun={workspace.rerunSubtitleDecision.isPending}
          pendingRerunStartStep={pendingSubtitleRerun?.rerunStartStep ?? null}
          pendingRerunIssueCode={pendingSubtitleRerun?.issueCode ?? null}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          isApplyingManualEditor={workspace.applyManualEditor.isPending}
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
          onPendingInitializationChange={workspace.setPendingInitialization}
          onConfirmProfile={confirmReviewProfile}
          onInitialize={() => workspace.initializeJob.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && confirmAndCancelJob(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && confirmAndRestartJob(workspace.selectedJob.id)}
          onDelete={() => workspace.selectedJob && confirmAndDeleteJob(workspace.selectedJob.id)}
          onApplyManualEditor={(payload) => workspace.applyManualEditor.mutate(payload)}
          onApplyReview={confirmAndApplyReview}
          onTriggerSubtitleRerun={triggerSubtitleRerun}
        />
      </JobDetailModal>

      <JobReviewOverlay
        open={showReviewOverlay}
        reviewStep={activeReviewStep}
        selectedJob={selectedReviewJob}
        activity={workspace.activity.data}
        report={workspace.report.data}
        contentProfile={workspace.contentProfile.data}
        contentSource={workspace.contentSource}
        contentDraft={workspace.contentDraft}
        contentKeywords={workspace.contentKeywords}
        isConfirmingProfile={workspace.confirmProfile.isPending}
        isApplyingReview={workspace.applyReview.isPending}
        isTriggeringSubtitleRerun={workspace.rerunSubtitleDecision.isPending}
        pendingRerunStartStep={pendingSubtitleRerun?.rerunStartStep ?? null}
        pendingRerunIssueCode={pendingSubtitleRerun?.issueCode ?? null}
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
        onApplyReview={confirmAndApplyReview}
        onTriggerSubtitleRerun={triggerSubtitleRerun}
        onApproveFinalReview={() => workspace.finalReviewDecision.mutate({ decision: "approve" })}
        onRejectFinalReview={confirmAndRejectFinalReview}
        onOpenFolder={() => selectedReviewJob && workspace.openFolder.mutate(selectedReviewJob.id)}
        onClose={() => closeReviewOverlay()}
      />
    </section>
  );
}

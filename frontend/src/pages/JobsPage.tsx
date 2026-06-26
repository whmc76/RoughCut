import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { JobCreateModal } from "../features/jobs/JobCreateModal";
import { JobDetailModal } from "../features/jobs/JobDetailModal";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobDownloadDialog } from "../features/jobs/JobDownloadDialog";
import { JobPublicationPanel } from "../features/jobs/JobPublicationPanel";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobReviewOverlay } from "../features/jobs/JobReviewOverlay";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import type { JobCreateEntryMode } from "../features/jobs/constants";
import type { JobClipStatusFilter, JobPublicationFilter, JobQueueFilter } from "../features/jobs/useJobWorkspace";
import type { Job, RemixProductionTask } from "../types";
import { MATERIAL_ENHANCEMENT_OPTIONS, resolveJobReviewStep, type JobReviewStep, type JobTaskKindFilter, useJobWorkspace } from "../features/jobs/useJobWorkspace";
import { useI18n } from "../i18n";
import { classNames } from "../utils";

const TASK_KIND_FILTER_META: Array<{ key: JobTaskKindFilter; label: string }> = [
  { key: "all", label: "全部标签" },
  { key: "edit", label: "剪辑任务" },
  { key: "remix_production", label: "影视二创" },
  { key: "publication", label: "发布任务" },
];

const PUBLICATION_FILTER_META: Array<{ key: JobPublicationFilter; label: string }> = [
  { key: "all", label: "发布不限" },
  { key: "published", label: "已发布" },
  { key: "unpublished", label: "未发布" },
];

const CLIP_STATUS_FILTER_META: Array<{ key: JobClipStatusFilter; label: string }> = [
  { key: "all", label: "剪辑状态不限" },
  { key: "pending", label: "待处理" },
  { key: "processing", label: "处理中" },
  { key: "done", label: "剪辑完成" },
];

function remixTaskLabel(task: RemixProductionTask) {
  return `S${String(task.season).padStart(2, "0")}E${String(task.episode).padStart(2, "0")} · ${task.title}`;
}

function remixProductionTaskToJob(task: RemixProductionTask, manifestCreatedAt?: string): Job | null {
  if (!task.job_id) return null;
  const updatedAt = task.job_updated_at || manifestCreatedAt || new Date(0).toISOString();
  return {
    id: task.job_id,
    source_name: remixTaskLabel(task),
    video_description: task.script_path || task.source_video_path || "",
    task_brief: "Demo Creator · 示例动画育儿二创正式生产任务",
    content_subject: task.title,
    content_summary: task.script_path || task.source_video_path || "",
    queue_task_kind: "remix_production",
    queue_thumbnail_source: "cover",
    status: task.job_status || task.status || "pending",
    language: "zh-CN",
    workflow_template: null,
    job_flow_mode: "auto",
    workflow_mode: "script_footage_remix",
    enhancement_modes: [],
    output_dir: task.output_path ? task.output_path.replace(/[\\/][^\\/]*$/, "") : null,
    error_message: task.blocker || null,
    progress_percent: task.job_progress_percent,
    created_at: manifestCreatedAt || updatedAt,
    updated_at: updatedAt,
    steps: [
      {
        id: `${task.job_id}:script_footage_remix`,
        step_name: "script_footage_remix",
        status: task.job_status || task.status || "pending",
        attempt: 0,
        started_at: null,
        finished_at: task.job_status === "done" ? updatedAt : null,
        error_message: task.blocker || null,
      },
    ],
  };
}

export function JobsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [remixProductionOpen, setRemixProductionOpen] = useState(false);
  const [createEntryMode, setCreateEntryMode] = useState<JobCreateEntryMode>("source_edit");
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);
  const [reviewNoticeTone, setReviewNoticeTone] = useState<"success" | "error">("success");
  const [pendingSubtitleRerun, setPendingSubtitleRerun] = useState<{ rerunStartStep: string | null; issueCode: string | null } | null>(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [publicationJobId, setPublicationJobId] = useState<string | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [downloadJobId, setDownloadJobId] = useState<string | null>(null);
  const [reviewOverlayOpen, setReviewOverlayOpen] = useState(false);
  const [reviewStepOverride, setReviewStepOverride] = useState<JobReviewStep | null>(null);
  const [taskKindFilter, setTaskKindFilter] = useState<JobTaskKindFilter>("all");
  const [publicationFilter, setPublicationFilter] = useState<JobPublicationFilter>("all");
  const [clipStatusFilter, setClipStatusFilter] = useState<JobClipStatusFilter>("all");
  const queueStageRef = useRef<HTMLElement | null>(null);
  const remixTaskCreationAttemptedRef = useRef(false);
  const remixProductionTasks = useQuery({
    queryKey: ["remix-production-tasks"],
    queryFn: () => api.getRemixProductionTasks(),
    staleTime: 15_000,
  });
  const remixQueueJobs = useMemo(
    () => (remixProductionTasks.data?.tasks ?? [])
      .map((task) => remixProductionTaskToJob(task, remixProductionTasks.data?.created_at))
      .filter((job): job is Job => Boolean(job)),
    [remixProductionTasks.data],
  );
  const workspace = useJobWorkspace({
    isCreateOpen: createOpen,
    additionalJobs: remixQueueJobs,
    taskKindFilter,
    publicationFilter,
    clipStatusFilter,
  });
  const createMissingRemixProductionJobs = useMutation({
    mutationFn: async (tasks: RemixProductionTask[]) => {
      const created = [];
      for (const task of tasks) {
        created.push(await api.createRemixProductionTaskJob(task.season, task.episode));
      }
      return created;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["remix-production-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] }),
      ]);
    },
  });
  const startRemixProductionJob = useMutation({
    mutationFn: (payload: { jobId: string; force?: boolean }) => api.startRemixProductionJob(payload.jobId, Boolean(payload.force)),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["remix-production-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] }),
      ]);
    },
  });

  useEffect(() => {
    if (!remixProductionTasks.data || remixTaskCreationAttemptedRef.current) return;
    const missingJobTasks = (remixProductionTasks.data.pending_tasks ?? []).filter((task) => !task.job_id);
    if (!missingJobTasks.length) return;
    remixTaskCreationAttemptedRef.current = true;
    createMissingRemixProductionJobs.mutate(missingJobTasks);
  }, [createMissingRemixProductionJobs, remixProductionTasks.data]);
  const selectedReviewJob =
    workspace.filteredJobs.find((job) => job.id === workspace.selectedJobId)
    ?? workspace.selectedJob;

  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];

  const reviewStep = reviewStepOverride ?? workspace.reviewStep ?? resolveJobReviewStep(selectedReviewJob, workspace.activity.data);
  const activeReviewStep: JobReviewStep = reviewStep ?? "summary_review";
  const isReviewContext = selectedReviewJob?.status === "needs_review" && reviewStep !== null;
  const showDetailModal = Boolean(detailModalOpen && workspace.selectedJobId);
  const publicationJob = workspace.filteredJobs.find((job) => job.id === publicationJobId)
    ?? (workspace.selectedJob?.id === publicationJobId ? workspace.selectedJob : null);
  const downloadJob = workspace.filteredJobs.find((job) => job.id === downloadJobId)
    ?? (workspace.selectedJob?.id === downloadJobId ? workspace.selectedJob : null);
  const previewJob = workspace.filteredJobs.find((job) => job.id === previewJobId)
    ?? (workspace.selectedJob?.id === previewJobId ? workspace.selectedJob : null);
  const showPublicationModal = Boolean(publicationJobId && publicationJob);
  const showPreviewModal = Boolean(previewJobId && previewJob);
  const showReviewOverlay = Boolean(reviewOverlayOpen && workspace.selectedJobId && isReviewContext && reviewStep);
  const createModalTitle = createEntryMode === "film_remix" ? "影视二创" : "原片剪辑";
  const remixSummary = remixProductionTasks.data?.summary;
  const remixPendingTasks = remixProductionTasks.data?.pending_tasks ?? [];

  const openCreateModal = (mode: JobCreateEntryMode) => {
    setCreateEntryMode(mode);
    if (mode === "film_remix") {
      workspace.setUpload((prev) => ({
        ...prev,
        jobFlowMode: "auto",
        executionMode: "auto",
        workflowMode: prev.taskBrief.trim() ? "remix_llm_plan" : "remix_auto_commentary",
        enhancementModes: Array.from(new Set([...prev.enhancementModes, "ai_effects", "multi_platform_adaptation"])),
        selectedAgentCapabilityKeys: prev.selectedAgentCapabilityKeys.length
          ? prev.selectedAgentCapabilityKeys
          : ["highlight_window_selection", "multi_material_assembly", "chapter_cards", "local_audio_cues", "speech_density_trim"],
      }));
    }
    setCreateOpen(true);
  };

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
    setPublicationJobId(null);
    setDetailModalOpen(false);
    setReviewStepOverride(resolveJobReviewStep(queuedJob));
    setReviewOverlayOpen(true);
    workspace.setSelectedJobId(jobId);
  };

  const openJobDetail = (jobId: string) => {
    setPublicationJobId(null);
    setReviewOverlayOpen(false);
    setReviewStepOverride(null);
    setDetailModalOpen(true);
    workspace.setSelectedJobId(jobId);
  };

  const openJobPublication = (jobId: string) => {
    setDetailModalOpen(false);
    setReviewOverlayOpen(false);
    setReviewStepOverride(null);
    setPublicationJobId(jobId);
  };

  const openJobPreview = (jobId: string) => {
    setDetailModalOpen(false);
    setReviewOverlayOpen(false);
    setReviewStepOverride(null);
    setPublicationJobId(null);
    setPreviewJobId(jobId);
  };

  const openJobDownload = (jobId: string) => {
    setDownloadJobId(jobId);
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
    if (!window.confirm("确认按这条异常意见重跑或暂停任务？")) {
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

  const openRemixProductionQueue = () => {
    setRemixProductionOpen(true);
    void remixProductionTasks.refetch();
  };

  const startRemixProduction = (jobId: string, force = false) => {
    startRemixProductionJob.mutate({ jobId, force });
  };

  const confirmReviewProfile = () => {
    workspace.confirmProfile.mutate(undefined, {
      onSuccess: async () => {
        showReviewNotice("success", "内容异常已确认，任务继续执行中，已返回队列。");
        await workspace.refreshAll();
        closeReviewOverlay(false);
      },
      onError: (error) => {
        showReviewNotice(
          "error",
          error instanceof Error
            ? error.message
            : `内容异常提交失败：${String(error) || "请稍后重试。"}`,
        );
      },
    });
  };

  const submitCreateJob = () =>
    workspace.uploadJob.mutate(undefined, {
      onSuccess: (job) => {
        const shouldOpenManualEditor = workspace.upload.jobFlowMode === "smart_assist";
        setCreateOpen(false);
        if (shouldOpenManualEditor) {
          navigate(`/jobs/${job.id}/manual-editor`);
        }
      },
    });

  const reviewNoticeClass = reviewNoticeTone === "error" ? "notice top-gap notice-error" : "notice top-gap";

  return (
    <section className="page-stack jobs-page">
      <PageHeader
        title={t("jobs.page.title")}
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
            <button type="button" className="button jobs-header-source-edit-button" onClick={() => openCreateModal("source_edit")}>
              原片剪辑
            </button>
            <button type="button" className="button primary jobs-header-create-button" onClick={() => openCreateModal("film_remix")}>
              影视二创
            </button>
          </div>
        }
      />

      <section className="jobs-dashboard-row">
        <article className="jobs-dashboard-card">
          <div className="jobs-dashboard-head">
            <div>
              <span className="jobs-dashboard-eyebrow">队列概览</span>
              <h3>任务队列</h3>
            </div>
            {workspace.keyword.trim() ? <p>{`搜索“${workspace.keyword.trim()}”`}</p> : null}
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
          <div className="jobs-attention-breakdown">
            <span>待核对 {workspace.queueStats.needsReview}</span>
            <span>失败 {workspace.queueStats.failed}</span>
            <span>取消 {workspace.queueStats.cancelled}</span>
          </div>
        </button>
      </section>

      <section className="jobs-queue-stage" ref={queueStageRef}>
        <div className="jobs-queue-filter-panel" aria-label="任务列表筛选">
          <div className="jobs-filter-row">
            <span className="jobs-filter-label">任务标签</span>
            <div className="jobs-task-kind-filter" aria-label="任务标签筛选">
              {TASK_KIND_FILTER_META.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={classNames("mode-chip-button", taskKindFilter === item.key && "is-active")}
                  onClick={() => {
                    setTaskKindFilter(item.key);
                    workspace.setQueueFilter("all");
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="jobs-filter-row">
            <span className="jobs-filter-label">发布状态</span>
            <div className="jobs-task-kind-filter" aria-label="发布状态筛选">
              {PUBLICATION_FILTER_META.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={classNames("mode-chip-button", publicationFilter === item.key && "is-active")}
                  onClick={() => setPublicationFilter(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="jobs-filter-row">
            <span className="jobs-filter-label">剪辑状态</span>
            <div className="jobs-task-kind-filter" aria-label="剪辑状态筛选">
              {CLIP_STATUS_FILTER_META.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={classNames("mode-chip-button", clipStatusFilter === item.key && "is-active")}
                  onClick={() => {
                    setClipStatusFilter(item.key);
                    workspace.setQueueFilter("all");
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {taskKindFilter === "remix_production" ? (
          <p className="jobs-queue-stage-note">
            Demo Creator · 示例动画育儿二创：待生产 {remixSummary?.pending_count ?? 0} 集，路径缺失 {remixSummary?.pending_file_missing_count ?? 0}。
          </p>
        ) : null}

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
          isStartingRemixProduction={startRemixProductionJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          onSelect={openJobDetail}
          onOpenReview={openJobReview}
          onPublish={openJobPublication}
          onPreview={openJobPreview}
          onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
          onDownload={openJobDownload}
          onCancel={confirmAndCancelJob}
          onRestart={confirmAndRestartJob}
          onStartRemixProduction={startRemixProduction}
          onDelete={confirmAndDeleteJob}
          onOpenRemixProduction={openRemixProductionQueue}
        />
      </section>

      {workspace.restartError ? (
        <div className="notice">
          {t("jobs.actions.restartFailed").replace("{error}", workspace.restartError)}
        </div>
      ) : null}
      {workspace.openFolder.isError ? (
        <div className="notice notice-error">
          打开文件夹失败：{workspace.openFolder.error instanceof Error ? workspace.openFolder.error.message : "系统没有返回具体原因。"}
        </div>
      ) : null}
      {reviewNotice ? <div className={reviewNoticeClass}>{reviewNotice}</div> : null}

      <JobCreateModal
        open={remixProductionOpen}
        title="影视二创生产清单"
        onClose={() => setRemixProductionOpen(false)}
      >
        <section className="jobs-create-modal-content jobs-remix-production-modal-content">
          <div className="jobs-stage-head">
            <div>
              <h3>Demo Creator · 示例动画正式生产队列</h3>
              <p>待生产剧集可批量启动，路径缺失的条目需先补齐素材。</p>
            </div>
            <div className="jobs-stage-meta">
              <span>待生产</span>
              <strong>{remixSummary?.pending_count ?? 0} 集</strong>
            </div>
          </div>

          {remixProductionTasks.isError ? (
            <div className="notice notice-error">
              读取失败：{remixProductionTasks.error instanceof Error ? remixProductionTasks.error.message : "未知错误"}
            </div>
          ) : null}

          <div className="jobs-remix-production-command">
            <span>正式生产命令</span>
            <code>{remixProductionTasks.data?.execution.command || "正在读取..."}</code>
          </div>

          <div className="jobs-remix-production-grid single">
            <section className="jobs-remix-production-panel">
              <div className="jobs-remix-production-panel-head">
                <strong>待生产任务</strong>
                <span>{remixPendingTasks.length} 集</span>
              </div>
              <div className="jobs-remix-production-task-list">
                {remixPendingTasks.map((task) => (
                  <article key={`${task.season}-${task.episode}`} className="jobs-remix-production-task">
                    <strong>{remixTaskLabel(task)}</strong>
                    <span>{task.script_path}</span>
                  </article>
                ))}
                {!remixPendingTasks.length && !remixProductionTasks.isLoading ? (
                  <p className="muted">当前没有待生产任务。</p>
                ) : null}
              </div>
            </section>
          </div>
        </section>
      </JobCreateModal>

      <JobCreateModal
        open={createOpen}
        title={createModalTitle}
        onClose={() => setCreateOpen(false)}
        actions={
          <button
            type="button"
            className="button primary jobs-create-submit-button"
            disabled={workspace.upload.files.length === 0 || workspace.uploadJob.isPending}
            onClick={submitCreateJob}
          >
            {workspace.uploadJob.isPending ? t("jobs.upload.submitting") : t("jobs.upload.submit")}
          </button>
        }
      >
        <section className="jobs-create-modal-content">
          <div className="jobs-create-modal-grid">
            <section className="jobs-create-modal-panel">
              <JobUploadPanel
                upload={workspace.upload}
                languageOptions={languageOptions}
                workflowTemplateOptions={workflowTemplateOptions}
                workflowModeOptions={workflowModeOptions}
                enhancementOptions={enhancementOptions}
                materialEnhancementOptions={MATERIAL_ENHANCEMENT_OPTIONS}
                smartCutRules={workspace.options.data?.smart_cut_rules ?? []}
                capabilityCatalog={workspace.options.data?.capability_catalog ?? []}
                outputDirHistory={workspace.outputDirHistory}
                creatorCards={workspace.creatorCards.data?.items ?? []}
                agentMode
                createEntryMode={createEntryMode}
                onChange={workspace.setUpload}
              />
            </section>
          </div>
        </section>
      </JobCreateModal>

      <JobCreateModal
        open={showPublicationModal}
        title="一键发布"
        onClose={() => setPublicationJobId(null)}
      >
        <section className="jobs-create-modal-content">
          <div className="jobs-stage-head">
            <div>
              <h3>一键发布</h3>
              <p>配置平台参数、定时发布和合集栏目，然后提交到 browser-agent。</p>
            </div>
            <div className="jobs-stage-meta">
              <span>发布任务</span>
              <strong>{publicationJob?.status === "done" ? "可配置" : "不可发布"}</strong>
            </div>
          </div>
          {publicationJob ? (
            <JobPublicationPanel job={publicationJob} onCancel={() => setPublicationJobId(null)} />
          ) : null}
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
          agentPlan={workspace.agentPlan.data}
          agentDecisions={workspace.agentDecisions.data}
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
          languageOptions={languageOptions}
          workflowTemplateOptions={workflowTemplateOptions}
          workflowModeOptions={workflowModeOptions}
          enhancementOptions={enhancementOptions}
          pendingInitialization={workspace.pendingInitialization}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isInitializing={workspace.initializeJob.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isConfirmingStrategyGates={workspace.confirmStrategyReviewGates.isPending}
          isRefiningAgentPlan={workspace.refineAgentPlan.isPending}
          isApplyingAgentPlan={workspace.applyAgentPlan.isPending}
          isTriggeringSubtitleRerun={workspace.rerunSubtitleDecision.isPending}
          pendingRerunStartStep={pendingSubtitleRerun?.rerunStartStep ?? null}
          pendingRerunIssueCode={pendingSubtitleRerun?.issueCode ?? null}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
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
          onConfirmStrategyGates={(gateIds) => workspace.confirmStrategyReviewGates.mutate({ gateIds })}
          onInitialize={() => workspace.initializeJob.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onDownload={() => workspace.selectedJob && openJobDownload(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && confirmAndCancelJob(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && confirmAndRestartJob(workspace.selectedJob.id)}
          onDelete={() => workspace.selectedJob && confirmAndDeleteJob(workspace.selectedJob.id)}
          onApplyReview={confirmAndApplyReview}
          onRefineAgentPlan={(prompt, target) => workspace.refineAgentPlan.mutate({ prompt, target })}
          onApplyAgentPlan={(payload) => workspace.applyAgentPlan.mutate(payload)}
          onTriggerSubtitleRerun={triggerSubtitleRerun}
        />
      </JobDetailModal>

      <JobCreateModal
        open={showPreviewModal}
        title={previewJob?.source_name ?? "成片预览"}
        onClose={() => setPreviewJobId(null)}
      >
        <section className="jobs-create-modal-content job-video-preview-modal">
          <div className="jobs-stage-head">
            <div>
              <h3>成片预览</h3>
              <p>{previewJob?.source_name}</p>
            </div>
            <div className="jobs-stage-meta">
              <span>状态</span>
              <strong>{previewJob?.status === "done" ? "可播放" : "不可播放"}</strong>
            </div>
          </div>
          {previewJob ? (
            <>
              <video
                key={previewJob.id}
                className="job-video-preview-player"
                src={api.jobRenderedFileUrl(previewJob.id)}
                controls
                preload="metadata"
                playsInline
              />
              <div className="toolbar job-video-preview-actions">
                <button
                  className="button ghost button-sm"
                  type="button"
                  onClick={() => window.open(api.jobRenderedFileUrl(previewJob.id), "_blank", "noopener,noreferrer")}
                >
                  新窗口打开
                </button>
                <button
                  className="button button-sm"
                  type="button"
                  onClick={() => setDownloadJobId(previewJob.id)}
                >
                  {t("jobs.actions.download")}
                </button>
              </div>
            </>
          ) : null}
        </section>
      </JobCreateModal>

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
        isConfirmingStrategyGates={workspace.confirmStrategyReviewGates.isPending}
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
        onConfirmStrategyGates={(gateIds) => workspace.confirmStrategyReviewGates.mutate({ gateIds })}
        onApplyReview={confirmAndApplyReview}
        onTriggerSubtitleRerun={triggerSubtitleRerun}
        onApproveFinalReview={() => workspace.finalReviewDecision.mutate({ decision: "approve" })}
        onRejectFinalReview={confirmAndRejectFinalReview}
        onOpenFolder={() => selectedReviewJob && workspace.openFolder.mutate(selectedReviewJob.id)}
        onClose={() => closeReviewOverlay()}
      />

      <JobDownloadDialog
        open={Boolean(downloadJobId && downloadJob)}
        job={downloadJob}
        onClose={() => setDownloadJobId(null)}
      />
    </section>
  );
}

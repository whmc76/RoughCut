import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { Job, JobActivity } from "../../types";
import { normalizeKeywordList } from "./contentProfile";
import type { UploadForm } from "./constants";

const EMPTY_UPLOAD: UploadForm = {
  files: [],
  language: "zh-CN",
  workflowTemplate: "",
  workflowMode: "standard_edit",
  enhancementModes: [],
  outputDir: "",
  videoDescription: "",
};

type PendingInitializationForm = Omit<UploadForm, "files">;

const EMPTY_PENDING_INITIALIZATION: PendingInitializationForm = {
  language: "zh-CN",
  workflowTemplate: "",
  workflowMode: "standard_edit",
  enhancementModes: [],
  outputDir: "",
  videoDescription: "",
};

const JOBS_PAGE_SIZE = 20;

const JOB_STATUS_GROUP_PRIORITY: Record<string, number> = {
  awaiting_init: 1,
  needs_review: 0,
  running: 1,
  processing: 1,
  pending: 1,
};

export type JobQueueFilter = "all" | "pending" | "running" | "done" | "attention";

type UseJobWorkspaceOptions = {
  isCreateOpen?: boolean;
};

export type JobReviewStep = "summary_review" | "final_review";

type ReviewSignalJob = Pick<Job, "quality_score" | "quality_grade" | "quality_summary" | "quality_issue_codes" | "timeline_diagnostics">;
type ReviewStepJob = ReviewSignalJob & Pick<Job, "status" | "steps" | "review_step">;

function hasFinalReviewSignals(job?: ReviewSignalJob | null) {
  if (!job) return false;
  return Boolean(
    job.quality_score != null
      || job.quality_grade?.trim()
      || job.quality_summary?.trim()
      || (job.quality_issue_codes ?? []).some(Boolean)
      || job.timeline_diagnostics,
  );
}

export function resolveJobReviewStep(job?: ReviewStepJob | null, activity?: Pick<JobActivity, "current_step" | "review_step"> | null): JobReviewStep | null {
  const explicitReviewStep = activity?.review_step ?? job?.review_step;
  if (explicitReviewStep === "summary_review" || explicitReviewStep === "final_review") {
    return explicitReviewStep;
  }

  const currentStepName = activity?.current_step?.step_name;
  if (currentStepName === "summary_review" || currentStepName === "final_review") {
    return currentStepName;
  }

  if (!job || job.status !== "needs_review") return null;

  const reviewSteps = job.steps.filter((step) => step.step_name === "summary_review" || step.step_name === "final_review");
  const finalReviewStep = reviewSteps.find((step) => step.step_name === "final_review" && step.status !== "done");
  const summaryReviewStep = reviewSteps.find((step) => step.step_name === "summary_review" && step.status !== "done");

  if (finalReviewStep && (hasFinalReviewSignals(job) || !summaryReviewStep)) {
    return "final_review";
  }

  if (summaryReviewStep) {
    return "summary_review";
  }

  if (finalReviewStep) {
    return "final_review";
  }

  if (hasFinalReviewSignals(job)) {
    return "final_review";
  }

  return null;
}

function isRunningJob(status: string) {
  return status === "running" || status === "processing";
}

function isPendingJob(status: string) {
  return status === "pending" || status === "awaiting_init";
}

function isAttentionJob(status: string) {
  return status === "needs_review" || status === "failed" || status === "cancelled";
}

function matchesQueueFilter(status: string, filter: JobQueueFilter) {
  if (filter === "all") return true;
  if (filter === "pending") return isPendingJob(status);
  if (filter === "running") return isRunningJob(status);
  if (filter === "done") return status === "done";
  if (filter === "attention") return isAttentionJob(status);
  return true;
}

function sameStringArray(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

function compareJobs(a: { status: string; updated_at: string }, b: { status: string; updated_at: string }) {
  const groupGap = (JOB_STATUS_GROUP_PRIORITY[a.status] ?? 2) - (JOB_STATUS_GROUP_PRIORITY[b.status] ?? 2);
  if (groupGap !== 0) return groupGap;
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

export function useJobWorkspace({ isCreateOpen = false }: UseJobWorkspaceOptions = {}) {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [queueFilter, setQueueFilter] = useState<JobQueueFilter>("all");
  const [jobsPage, setJobsPage] = useState(0);
  const [upload, setUpload] = useState<UploadForm>(EMPTY_UPLOAD);
  const [pendingInitialization, setPendingInitialization] = useState<PendingInitializationForm>(EMPTY_PENDING_INITIALIZATION);
  const [contentDraft, setContentDraft] = useState<Record<string, unknown>>({});
  const [reviewWorkflowMode, setReviewWorkflowMode] = useState("standard_edit");
  const [reviewEnhancementModes, setReviewEnhancementModes] = useState<string[]>([]);
  const [reviewCopyStyle, setReviewCopyStyle] = useState("attention_grabbing");
  const [restartError, setRestartError] = useState<string | null>(null);
  const previousUploadDefaultsRef = useRef({
    workflowMode: EMPTY_UPLOAD.workflowMode,
    enhancementModes: EMPTY_UPLOAD.enhancementModes,
  });

  const jobs = useQuery({
    queryKey: ["jobs", JOBS_PAGE_SIZE, jobsPage],
    queryFn: () => api.listJobs(JOBS_PAGE_SIZE, jobsPage * JOBS_PAGE_SIZE),
    refetchInterval: 8_000,
  });
  const detail = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api.getJob(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });
  const selectedJobPreview = jobs.data?.find((job) => job.id === selectedJobId) ?? null;
  const activity = useQuery({
    queryKey: ["job-activity", selectedJobId],
    queryFn: () => api.getJobActivity(selectedJobId!),
    enabled: Boolean(selectedJobId),
    refetchInterval: selectedJobId ? 5_000 : false,
  });
  const selectedJobSnapshot = detail.data ?? selectedJobPreview;
  const reviewStep = resolveJobReviewStep(selectedJobSnapshot, activity.data);
  const isReviewJob = selectedJobSnapshot?.status === "needs_review";
  const isSummaryReviewJob = isReviewJob && reviewStep === "summary_review";
  const isFinalReviewJob = isReviewJob && reviewStep === "final_review";
  const isAwaitingInitializationJob = selectedJobSnapshot?.status === "awaiting_init";
  const selectedJobStatus = selectedJobSnapshot?.status ?? null;
  const options = useQuery({
    queryKey: ["config-options"],
    queryFn: api.getConfigOptions,
    enabled: isCreateOpen || isAwaitingInitializationJob,
  });
  const config = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    enabled: isCreateOpen || isSummaryReviewJob,
  });
  const packaging = useQuery({
    queryKey: ["packaging"],
    queryFn: api.getPackaging,
    enabled: isSummaryReviewJob,
  });
  const avatarMaterials = useQuery({
    queryKey: ["avatar-materials"],
    queryFn: api.getAvatarMaterials,
    enabled: isSummaryReviewJob,
  });
  const shouldLoadReport = Boolean(selectedJobSnapshot) && (selectedJobStatus !== "needs_review" || isFinalReviewJob);
  const shouldLoadTokenUsage = Boolean(selectedJobSnapshot) && (selectedJobStatus !== "needs_review" || isFinalReviewJob);
  const shouldLoadTimeline = Boolean(selectedJobSnapshot) && (selectedJobStatus !== "needs_review" || isFinalReviewJob);
  const report = useQuery({
    queryKey: ["job-report", selectedJobId],
    queryFn: () => api.getJobReport(selectedJobId!),
    enabled: shouldLoadReport,
  });
  const tokenUsage = useQuery({
    queryKey: ["job-token-usage", selectedJobId],
    queryFn: () => api.getJobTokenUsage(selectedJobId!),
    enabled: shouldLoadTokenUsage,
    refetchInterval: selectedJobId ? 5_000 : false,
  });
  const timeline = useQuery({
    queryKey: ["job-timeline", selectedJobId],
    queryFn: () => api.getJobTimeline(selectedJobId!),
    enabled: shouldLoadTimeline,
  });
  const contentProfile = useQuery({
    queryKey: ["job-content-profile", selectedJobId],
    queryFn: () => api.getContentProfile(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });
  const selectedJob = detail.data;
  const contentFallbackSource = (contentProfile.data?.final ?? contentProfile.data?.draft ?? null) as Record<string, unknown> | null;
  const contentSource = isSummaryReviewJob
    ? (contentProfile.data?.draft ?? contentProfile.data?.final ?? null)
    : (contentProfile.data?.final ?? contentProfile.data?.draft ?? null);
  const contentDraftKeywords = normalizeKeywordList(contentDraft.keywords);
  const contentSourceKeywords = normalizeKeywordList(
    contentSource?.keywords ?? contentFallbackSource?.keywords,
  );
  const contentSourceSearchQueries = normalizeKeywordList(
    (contentSource as Record<string, unknown> | null)?.search_queries ?? contentFallbackSource?.search_queries,
  );
  const inheritedUploadDefaults: UploadForm = useMemo(
    () => ({
      ...EMPTY_UPLOAD,
      workflowMode: config.data?.default_job_workflow_mode ?? EMPTY_UPLOAD.workflowMode,
      enhancementModes: config.data?.default_job_enhancement_modes ?? EMPTY_UPLOAD.enhancementModes,
    }),
    [config.data?.default_job_workflow_mode, config.data?.default_job_enhancement_modes],
  );

  useEffect(() => {
    setContentDraft(
      isSummaryReviewJob
        ? (contentProfile.data?.draft ?? contentProfile.data?.final ?? {})
        : (contentProfile.data?.final ?? contentProfile.data?.draft ?? {}),
    );
  }, [contentProfile.data, isSummaryReviewJob]);

  useEffect(() => {
    if (!selectedJobId || !isAwaitingInitializationJob || !detail.data) {
      setPendingInitialization(EMPTY_PENDING_INITIALIZATION);
      return;
    }
    setPendingInitialization({
      language: detail.data.language || "zh-CN",
      workflowTemplate: detail.data.workflow_template || "",
      workflowMode: detail.data.workflow_mode || "standard_edit",
      enhancementModes: detail.data.enhancement_modes || [],
      outputDir: detail.data.output_dir || "",
      videoDescription: detail.data.video_description || "",
    });
  }, [detail.data, isAwaitingInitializationJob, selectedJobId]);

  useEffect(() => {
    if (!selectedJobId || !isSummaryReviewJob) return;
    void api.warmContentProfileThumbnails(selectedJobId);
  }, [selectedJobId, isSummaryReviewJob]);

  useEffect(() => {
    setJobsPage(0);
  }, [keyword, queueFilter]);

  useEffect(() => {
    const previousDefaults = previousUploadDefaultsRef.current;
    const nextDefaults = {
      workflowMode: inheritedUploadDefaults.workflowMode,
      enhancementModes: inheritedUploadDefaults.enhancementModes,
    };

    setUpload((prev) => {
      const followsPreviousDefaults =
        prev.workflowMode === previousDefaults.workflowMode
        && sameStringArray(prev.enhancementModes, previousDefaults.enhancementModes);

      return followsPreviousDefaults
        ? {
          ...prev,
          workflowMode: nextDefaults.workflowMode,
          enhancementModes: nextDefaults.enhancementModes,
        }
        : prev;
    });

    previousUploadDefaultsRef.current = nextDefaults;
  }, [inheritedUploadDefaults]);

  useEffect(() => {
    if (!selectedJobId) return;
    setReviewWorkflowMode(
      contentProfile.data?.workflow_mode
      ?? detail.data?.workflow_mode
      ?? config.data?.default_job_workflow_mode
      ?? "standard_edit",
    );
    setReviewEnhancementModes(
      contentProfile.data?.enhancement_modes
      ?? detail.data?.enhancement_modes
      ?? config.data?.default_job_enhancement_modes
      ?? [],
    );
    setReviewCopyStyle(
      String(
        (contentProfile.data?.final as Record<string, unknown> | undefined)?.copy_style
        ?? (contentProfile.data?.draft as Record<string, unknown> | undefined)?.copy_style
        ?? packaging.data?.config.copy_style
        ?? "attention_grabbing",
      ),
    );
  }, [
    selectedJobId,
    contentProfile.data?.workflow_mode,
    contentProfile.data?.enhancement_modes,
    detail.data?.workflow_mode,
    detail.data?.enhancement_modes,
    config.data?.default_job_workflow_mode,
    config.data?.default_job_enhancement_modes,
    contentProfile.data?.final,
      contentProfile.data?.draft,
      packaging.data?.config.copy_style,
    ]);

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] });
    if (selectedJobId) {
      void queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-activity", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-token-usage", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-report", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-timeline", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-content-profile", selectedJobId] });
    }
  };

  const openFolder = useMutation({
    mutationFn: async (jobId: string) => api.openJobFolder(jobId),
  });
  const cancelJob = useMutation({
    mutationFn: async (jobId: string) => api.cancelJob(jobId),
    onSuccess: refreshAll,
  });
  const restartJob = useMutation({
    mutationFn: async (jobId: string) => api.restartJob(jobId),
    onMutate: () => {
      setRestartError(null);
    },
    onSuccess: async () => {
      setRestartError(null);
      await refreshAll();
    },
    onError: (error) => {
      setRestartError(error instanceof Error ? error.message : String(error));
    },
  });
  const deleteJob = useMutation({
    mutationFn: async (jobId: string) => api.deleteJob(jobId),
    onSuccess: async (_, jobId) => {
      if (selectedJobId === jobId) {
        setSelectedJobId(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] });
      await queryClient.removeQueries({ queryKey: ["job", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-activity", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-token-usage", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-report", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-timeline", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-content-profile", jobId] });
    },
  });
  const uploadJob = useMutation({
    mutationFn: async () =>
      api.createJob(
        upload.files,
        upload.language,
        upload.workflowTemplate || undefined,
        upload.workflowMode,
        upload.enhancementModes,
        upload.outputDir,
        upload.videoDescription,
      ),
    onSuccess: async (job) => {
      setUpload(inheritedUploadDefaults);
      setSelectedJobId(job.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] }),
      ]);
    },
  });
  const initializeJob = useMutation({
    mutationFn: async () =>
      api.initializeJob(selectedJobId!, {
        language: pendingInitialization.language,
        workflow_template: pendingInitialization.workflowTemplate || undefined,
        workflow_mode: pendingInitialization.workflowMode,
        enhancement_modes: pendingInitialization.enhancementModes,
        output_dir: pendingInitialization.outputDir || undefined,
        video_description: pendingInitialization.videoDescription,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-activity", selectedJobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-content-profile", selectedJobId] }),
      ]);
    },
  });
  const confirmProfile = useMutation({
    mutationFn: async () => {
      await api.patchConfig({
        default_job_workflow_mode: reviewWorkflowMode,
        default_job_enhancement_modes: reviewEnhancementModes,
      });
      await api.patchPackagingConfig({ copy_style: reviewCopyStyle });
      const mergedKeywords =
        "keywords" in contentDraft
          ? normalizeKeywordList(contentDraft.keywords)
          : contentSourceSearchQueries.length
            ? contentSourceSearchQueries
            : contentSourceKeywords;
      return api.confirmContentProfile(selectedJobId!, {
        ...contentDraft,
        keywords: mergedKeywords,
        workflow_mode: reviewWorkflowMode,
        enhancement_modes: reviewEnhancementModes,
        copy_style: reviewCopyStyle,
      });
    },
    onSuccess: async (result) => {
      setContentDraft(result.final ?? {});
      setReviewWorkflowMode(result.workflow_mode);
      setReviewEnhancementModes(result.enhancement_modes ?? []);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs-usage-trend"] }),
        queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-content-profile", selectedJobId] }),
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["packaging"] }),
      ]);
    },
  });
  const applyReview = useMutation({
    mutationFn: async (payload: { targetId: string; action: "accepted" | "rejected" }) =>
      api.applyReview(selectedJobId!, [{ target_type: "subtitle_correction", target_id: payload.targetId, action: payload.action }]),
    onSuccess: refreshAll,
  });
  const rerunSubtitleDecision = useMutation({
    mutationFn: async (payload: { issueCode?: string; rerunStartStep?: string; note?: string }) =>
      api.rerunJob(selectedJobId!, {
        issue_code: payload.issueCode,
        rerun_start_step: payload.rerunStartStep,
        note: payload.note,
      }),
    onSuccess: refreshAll,
  });
  const finalReviewDecision = useMutation({
    mutationFn: async (payload: { decision: "approve" | "reject"; note?: string }) =>
      api.finalReviewDecision(selectedJobId!, payload),
    onSuccess: refreshAll,
  });

  const searchMatchedJobs = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    const visibleJobs = !needle
      ? jobs.data ?? []
      : (jobs.data ?? []).filter((job) =>
        [job.source_name, job.content_subject, job.content_summary, job.video_description, job.status].some((field) =>
          String(field ?? "").toLowerCase().includes(needle),
        ),
    );
    return [...visibleJobs].sort(compareJobs);
  }, [jobs.data, keyword]);
  const queueStats = useMemo(() => ({
    total: searchMatchedJobs.length,
    pending: searchMatchedJobs.filter((job) => isPendingJob(job.status)).length,
    running: searchMatchedJobs.filter((job) => isRunningJob(job.status)).length,
    done: searchMatchedJobs.filter((job) => job.status === "done").length,
    attention: searchMatchedJobs.filter((job) => isAttentionJob(job.status)).length,
    needsReview: searchMatchedJobs.filter((job) => job.status === "needs_review").length,
    failed: searchMatchedJobs.filter((job) => job.status === "failed").length,
    cancelled: searchMatchedJobs.filter((job) => job.status === "cancelled").length,
  }), [searchMatchedJobs]);
  const filteredJobs = useMemo(
    () => searchMatchedJobs.filter((job) => matchesQueueFilter(job.status, queueFilter)),
    [queueFilter, searchMatchedJobs],
  );
  const hasMoreJobs = (jobs.data?.length ?? 0) === JOBS_PAGE_SIZE;
  const contentKeywordsList =
    contentDraftKeywords.length
      ? contentDraftKeywords
      : contentSourceKeywords.length
      ? contentSourceKeywords
      : contentSourceSearchQueries;
  const contentKeywords = contentKeywordsList.join(", ");

  return {
    selectedJobId,
    setSelectedJobId,
    keyword,
    setKeyword,
    queueFilter,
    setQueueFilter,
    queueStats,
    upload,
    setUpload,
    pendingInitialization,
    setPendingInitialization,
    contentDraft,
    setContentDraft,
    jobs,
    detail,
    activity,
    report,
    tokenUsage,
    timeline,
    contentProfile,
    options,
    config,
    packaging,
    avatarMaterials,
    refreshAll,
    openFolder,
    cancelJob,
    restartJob,
    deleteJob,
    uploadJob,
    initializeJob,
    confirmProfile,
    applyReview,
    rerunSubtitleDecision,
    finalReviewDecision,
    filteredJobs,
    selectedJob,
    reviewStep,
    contentSource,
    contentKeywords,
      reviewWorkflowMode,
      setReviewWorkflowMode,
      reviewEnhancementModes,
      setReviewEnhancementModes,
      reviewCopyStyle,
      setReviewCopyStyle,
      jobsPage,
      jobsPageSize: JOBS_PAGE_SIZE,
      hasMoreJobs,
      setJobsPage,
      restartError,
  };
}

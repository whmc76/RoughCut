import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { UploadForm } from "./constants";

const EMPTY_UPLOAD: UploadForm = {
  file: null,
  language: "zh-CN",
  workflowTemplate: "",
  workflowMode: "standard_edit",
  enhancementModes: [],
  outputDir: "",
};

const JOBS_PAGE_SIZE = 20;

const JOB_STATUS_GROUP_PRIORITY: Record<string, number> = {
  needs_review: 0,
  running: 1,
  processing: 1,
  pending: 1,
};

function sameStringArray(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

function normalizeKeywordList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const normalized: string[] = [];
  for (const item of value) {
    const normalizedItem = String(item ?? "").trim();
    if (normalizedItem && !normalized.includes(normalizedItem)) {
      normalized.push(normalizedItem);
    }
  }
  return normalized;
}

function compareJobs(a: { status: string; updated_at: string }, b: { status: string; updated_at: string }) {
  const groupGap = (JOB_STATUS_GROUP_PRIORITY[a.status] ?? 2) - (JOB_STATUS_GROUP_PRIORITY[b.status] ?? 2);
  if (groupGap !== 0) return groupGap;
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

export function useJobWorkspace() {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [jobsPage, setJobsPage] = useState(0);
  const [upload, setUpload] = useState<UploadForm>(EMPTY_UPLOAD);
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
  const options = useQuery({ queryKey: ["config-options"], queryFn: api.getConfigOptions });
  const config = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const packaging = useQuery({ queryKey: ["packaging"], queryFn: api.getPackaging });
  const avatarMaterials = useQuery({ queryKey: ["avatar-materials"], queryFn: api.getAvatarMaterials });
  const detail = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api.getJob(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });
  const activity = useQuery({
    queryKey: ["job-activity", selectedJobId],
    queryFn: () => api.getJobActivity(selectedJobId!),
    enabled: Boolean(selectedJobId),
    refetchInterval: selectedJobId ? 5_000 : false,
  });
  const isReviewMode = detail.data?.status === "needs_review";
  const isFinalReviewStep = (detail.data?.steps ?? []).some(
    (step) => step.step_name === "final_review" && step.status !== "done",
  ) || activity.data?.current_step?.step_name === "final_review";
  const shouldLoadReport = Boolean(selectedJobId) && (!isReviewMode || isFinalReviewStep);
  const shouldLoadTokenUsage = Boolean(selectedJobId) && Boolean(detail.data) && !isReviewMode;
  const shouldLoadTimeline = Boolean(selectedJobId) && !isReviewMode;
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
    enabled: Boolean(selectedJobId) && isReviewMode,
  });
  const selectedJob = detail.data;
  const contentSource = contentProfile.data?.final ?? contentProfile.data?.draft ?? null;
  const contentDraftKeywords = normalizeKeywordList(contentDraft.keywords);
  const contentSourceKeywords = normalizeKeywordList(contentSource?.keywords);
  const contentSourceSearchQueries = normalizeKeywordList((contentSource as Record<string, unknown> | null)?.search_queries);
  const inheritedUploadDefaults: UploadForm = useMemo(
    () => ({
      ...EMPTY_UPLOAD,
      workflowMode: config.data?.default_job_workflow_mode ?? EMPTY_UPLOAD.workflowMode,
      enhancementModes: config.data?.default_job_enhancement_modes ?? EMPTY_UPLOAD.enhancementModes,
    }),
    [config.data?.default_job_workflow_mode, config.data?.default_job_enhancement_modes],
  );

  useEffect(() => {
    setContentDraft(contentProfile.data?.final ?? contentProfile.data?.draft ?? {});
  }, [contentProfile.data]);

  useEffect(() => {
    if (!selectedJobId || !isReviewMode) return;
    void api.warmContentProfileThumbnails(selectedJobId);
  }, [selectedJobId, isReviewMode]);

  useEffect(() => {
    setJobsPage(0);
  }, [keyword]);

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
        upload.file!,
        upload.language,
        upload.workflowTemplate || undefined,
        upload.workflowMode,
        upload.enhancementModes,
        upload.outputDir,
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
  const finalReviewDecision = useMutation({
    mutationFn: async (payload: { decision: "approve" | "reject"; note?: string }) =>
      api.finalReviewDecision(selectedJobId!, payload),
    onSuccess: refreshAll,
  });

  const filteredJobs = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    const visibleJobs = !needle
      ? jobs.data ?? []
      : (jobs.data ?? []).filter((job) =>
        [job.source_name, job.content_subject, job.content_summary, job.status].some((field) =>
          String(field ?? "").toLowerCase().includes(needle),
        ),
    );
    return [...visibleJobs].sort(compareJobs);
  }, [jobs.data, keyword]);
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
    upload,
    setUpload,
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
    confirmProfile,
    applyReview,
    finalReviewDecision,
    filteredJobs,
    selectedJob,
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

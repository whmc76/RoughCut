import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { UploadForm } from "./constants";

const EMPTY_UPLOAD: UploadForm = {
  file: null,
  language: "zh-CN",
  channelProfile: "",
  workflowMode: "standard_edit",
  enhancementModes: [],
};

const JOB_STATUS_GROUP_PRIORITY: Record<string, number> = {
  needs_review: 0,
  running: 1,
  processing: 1,
  pending: 1,
};

function compareJobs(a: { status: string; updated_at: string }, b: { status: string; updated_at: string }) {
  const groupGap = (JOB_STATUS_GROUP_PRIORITY[a.status] ?? 2) - (JOB_STATUS_GROUP_PRIORITY[b.status] ?? 2);
  if (groupGap !== 0) return groupGap;
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

export function useJobWorkspace() {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [usageTrendDays, setUsageTrendDays] = useState(7);
  const [usageTrendFocusType, setUsageTrendFocusType] = useState("all");
  const [usageTrendFocusName, setUsageTrendFocusName] = useState("");
  const [upload, setUpload] = useState<UploadForm>(EMPTY_UPLOAD);
  const [contentDraft, setContentDraft] = useState<Record<string, unknown>>({});
  const [reviewWorkflowMode, setReviewWorkflowMode] = useState("standard_edit");
  const [reviewEnhancementModes, setReviewEnhancementModes] = useState<string[]>([]);
  const [reviewCopyStyle, setReviewCopyStyle] = useState("attention_grabbing");
  const uploadDefaultsHydrated = useRef(false);

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs, refetchInterval: 8_000 });
  const usageSummary = useQuery({ queryKey: ["jobs-usage-summary", 60], queryFn: () => api.getJobsUsageSummary(60), refetchInterval: 12_000 });
  const usageTrend = useQuery({
    queryKey: ["jobs-usage-trend", usageTrendDays, 120, usageTrendFocusType, usageTrendFocusName],
    queryFn: () =>
      api.getJobsUsageTrend(
        usageTrendDays,
        120,
        usageTrendFocusType !== "all" ? usageTrendFocusType : undefined,
        usageTrendFocusName || undefined,
      ),
    refetchInterval: 12_000,
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
  const report = useQuery({
    queryKey: ["job-report", selectedJobId],
    queryFn: () => api.getJobReport(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });
  const tokenUsage = useQuery({
    queryKey: ["job-token-usage", selectedJobId],
    queryFn: () => api.getJobTokenUsage(selectedJobId!),
    enabled: Boolean(selectedJobId),
    refetchInterval: selectedJobId ? 5_000 : false,
  });
  const timeline = useQuery({
    queryKey: ["job-timeline", selectedJobId],
    queryFn: () => api.getJobTimeline(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });
  const contentProfile = useQuery({
    queryKey: ["job-content-profile", selectedJobId],
    queryFn: () => api.getContentProfile(selectedJobId!),
    enabled: Boolean(selectedJobId),
  });

  useEffect(() => {
    setContentDraft(contentProfile.data?.final ?? contentProfile.data?.draft ?? {});
  }, [contentProfile.data]);

  useEffect(() => {
    if (!config.data || uploadDefaultsHydrated.current) return;
    setUpload((prev) => ({
      ...prev,
      workflowMode: config.data.default_job_workflow_mode || prev.workflowMode,
      enhancementModes: config.data.default_job_enhancement_modes ?? prev.enhancementModes,
    }));
    uploadDefaultsHydrated.current = true;
  }, [config.data]);

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
    onSuccess: refreshAll,
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
        upload.channelProfile || undefined,
        upload.workflowMode,
        upload.enhancementModes,
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
      return api.confirmContentProfile(selectedJobId!, {
        ...contentDraft,
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

  const selectedJob = detail.data;
  const contentSource = contentProfile.data?.final ?? contentProfile.data?.draft ?? null;
  const contentKeywords = Array.isArray(contentDraft.keywords ?? contentSource?.keywords)
    ? ((contentDraft.keywords ?? contentSource?.keywords) as string[]).join(", ")
    : "";
  const inheritedUploadDefaults: UploadForm = {
    ...EMPTY_UPLOAD,
    workflowMode: config.data?.default_job_workflow_mode ?? EMPTY_UPLOAD.workflowMode,
    enhancementModes: config.data?.default_job_enhancement_modes ?? EMPTY_UPLOAD.enhancementModes,
  };

  return {
    selectedJobId,
    setSelectedJobId,
    keyword,
    setKeyword,
    usageTrendDays,
    setUsageTrendDays,
    usageTrendFocusType,
    setUsageTrendFocusType,
    usageTrendFocusName,
    setUsageTrendFocusName,
    upload,
    setUpload,
    contentDraft,
    setContentDraft,
    jobs,
    usageSummary,
    usageTrend,
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
  };
}

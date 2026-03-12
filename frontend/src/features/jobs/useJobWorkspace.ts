import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { UploadForm } from "./constants";

const EMPTY_UPLOAD: UploadForm = { file: null, language: "zh-CN", channelProfile: "" };

export function useJobWorkspace() {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [upload, setUpload] = useState<UploadForm>(EMPTY_UPLOAD);
  const [contentDraft, setContentDraft] = useState<Record<string, unknown>>({});

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs, refetchInterval: 8_000 });
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

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    if (selectedJobId) {
      void queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-activity", selectedJobId] });
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
  const uploadJob = useMutation({
    mutationFn: async () => api.createJob(upload.file!, upload.language, upload.channelProfile || undefined),
    onSuccess: async (job) => {
      setUpload(EMPTY_UPLOAD);
      setSelectedJobId(job.id);
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const confirmProfile = useMutation({
    mutationFn: async () => api.confirmContentProfile(selectedJobId!, contentDraft),
    onSuccess: async (result) => {
      setContentDraft(result.final ?? {});
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-content-profile", selectedJobId] }),
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
    if (!needle) return jobs.data ?? [];
    return (jobs.data ?? []).filter((job) =>
      [job.source_name, job.content_subject, job.content_summary, job.status].some((field) =>
        String(field ?? "").toLowerCase().includes(needle),
      ),
    );
  }, [jobs.data, keyword]);

  const selectedJob = detail.data;
  const contentSource = contentProfile.data?.final ?? contentProfile.data?.draft ?? null;
  const contentKeywords = Array.isArray(contentDraft.keywords ?? contentSource?.keywords)
    ? ((contentDraft.keywords ?? contentSource?.keywords) as string[]).join(", ")
    : "";

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
    timeline,
    contentProfile,
    refreshAll,
    openFolder,
    cancelJob,
    restartJob,
    uploadJob,
    confirmProfile,
    applyReview,
    filteredJobs,
    selectedJob,
    contentSource,
    contentKeywords,
  };
}

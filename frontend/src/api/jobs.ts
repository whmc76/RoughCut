import type { ContentProfileReview, Job, JobActivity, JobTimeline, JobsUsageSummary, JobsUsageTrend, Report, TokenUsageReport } from "../types";
import { apiPath, request, requestForm } from "./core";

export const jobsApi = {
  listJobs: () => request<Job[]>("/jobs"),
  getJobsUsageSummary: (limit = 60) => request<JobsUsageSummary>(`/jobs/usage-summary?limit=${limit}`),
  getJobsUsageTrend: (days = 7, limit = 120, focusType?: string, focusName?: string) =>
    request<JobsUsageTrend>(
      `/jobs/usage-trend?days=${days}&limit=${limit}${focusType ? `&focus_type=${encodeURIComponent(focusType)}` : ""}${focusName ? `&focus_name=${encodeURIComponent(focusName)}` : ""}`,
    ),
  createJob: async (
    file: File,
    language: string,
    workflowTemplate?: string,
    workflowMode?: string,
    enhancementModes: string[] = [],
  ) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", language);
    if (workflowTemplate) formData.append("workflow_template", workflowTemplate);
    if (workflowMode) formData.append("workflow_mode", workflowMode);
    enhancementModes.forEach((mode) => formData.append("enhancement_modes", mode));
    return requestForm<Job>("/jobs", formData);
  },
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  getJobActivity: (jobId: string) => request<JobActivity>(`/jobs/${jobId}/activity`),
  getJobTokenUsage: (jobId: string) => request<TokenUsageReport>(`/jobs/${jobId}/token-usage`),
  getJobReport: (jobId: string) => request<Report>(`/jobs/${jobId}/report`),
  getJobTimeline: (jobId: string) => request<JobTimeline>(`/jobs/${jobId}/timeline`),
  getContentProfile: (jobId: string) => request<ContentProfileReview>(`/jobs/${jobId}/content-profile`),
  confirmContentProfile: (jobId: string, body: Record<string, unknown>) =>
    request<ContentProfileReview>(`/jobs/${jobId}/content-profile/confirm`, { method: "POST", body: JSON.stringify(body) }),
  applyReview: (jobId: string, actions: Array<{ target_type: string; target_id: string; action: string; override_text?: string }>) =>
    request<{ applied: number }>(`/jobs/${jobId}/review/apply`, { method: "POST", body: JSON.stringify({ actions }) }),
  contentProfileThumbnailUrl: (jobId: string, index: number) => apiPath(`/jobs/${jobId}/content-profile/thumbnail?index=${index}`),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  restartJob: (jobId: string) => request<Job>(`/jobs/${jobId}/restart`, { method: "POST" }),
  deleteJob: (jobId: string) => request<void>(`/jobs/${jobId}`, { method: "DELETE" }),
  openJobFolder: (jobId: string) => request<{ path: string; kind: string }>(`/jobs/${jobId}/open-folder`, { method: "POST" }),
};

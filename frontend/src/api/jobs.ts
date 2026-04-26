import type {
  ContentProfileReview,
  Job,
  JobActivity,
  JobManualEditApplyPayload,
  JobManualEditApplyResponse,
  JobManualEditPreviewAssets,
  JobManualEditSession,
  JobTimeline,
  JobsUsageSummary,
  JobsUsageTrend,
  PublicationPlan,
  PublicationPlatformPublishOptions,
  Report,
  TokenUsageReport,
} from "../types";
import { apiPath, request, requestForm } from "./core";

type FinalReviewDecision = "approve" | "reject";

type FinalReviewDecisionResponse = {
  job_id: string;
  decision: FinalReviewDecision;
  job_status: string;
  review_step_status: string;
  rerun_triggered: boolean;
  note?: string | null;
};

type JobRerunResponse = {
  job_id: string;
  job_status: string;
  rerun_start_step: string;
  rerun_steps: string[];
  issue_codes: string[];
  note?: string | null;
  detail?: string | null;
};

export const jobsApi = {
  listJobs: (limit = 50, offset = 0) =>
    request<Job[]>(`/jobs?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  getJobsUsageSummary: (limit = 60) => request<JobsUsageSummary>(`/jobs/usage-summary?limit=${limit}`),
  getJobsUsageTrend: (days = 7, limit = 120, focusType?: string, focusName?: string) =>
    request<JobsUsageTrend>(
      `/jobs/usage-trend?days=${days}&limit=${limit}${focusType ? `&focus_type=${encodeURIComponent(focusType)}` : ""}${focusName ? `&focus_name=${encodeURIComponent(focusName)}` : ""}`,
    ),
  createJob: async (
    files: File[],
    language: string,
    workflowTemplate?: string,
    workflowMode?: string,
    enhancementModes: string[] = [],
    outputDir?: string,
    videoDescription?: string,
  ) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    formData.append("language", language);
    if (workflowTemplate) formData.append("workflow_template", workflowTemplate);
    if (workflowMode) formData.append("workflow_mode", workflowMode);
    if (outputDir?.trim()) formData.append("output_dir", outputDir.trim());
    if (videoDescription?.trim()) formData.append("video_description", videoDescription.trim());
    enhancementModes.forEach((mode) => formData.append("enhancement_modes", mode));
    return requestForm<Job>("/jobs", formData);
  },
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  getJobActivity: (jobId: string) => request<JobActivity>(`/jobs/${jobId}/activity`),
  getJobTokenUsage: (jobId: string) => request<TokenUsageReport>(`/jobs/${jobId}/token-usage`),
  getJobReport: (jobId: string) => request<Report>(`/jobs/${jobId}/report`),
  getJobTimeline: (jobId: string) => request<JobTimeline>(`/jobs/${jobId}/timeline`),
  getJobManualEditor: (jobId: string) => request<JobManualEditSession>(`/jobs/${jobId}/manual-editor`),
  getJobManualEditorAssets: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets`),
  getJobManualEditorAssetsStatus: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets/status`),
  warmJobManualEditorAssets: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets/warm`, { method: "POST" }),
  applyJobManualEditor: (jobId: string, body: JobManualEditApplyPayload) =>
    request<JobManualEditApplyResponse>(`/jobs/${jobId}/manual-editor/apply`, { method: "POST", body: JSON.stringify(body) }),
  getContentProfile: (jobId: string) => request<ContentProfileReview>(`/jobs/${jobId}/content-profile`),
  confirmContentProfile: (jobId: string, body: Record<string, unknown>) =>
    request<ContentProfileReview>(`/jobs/${jobId}/content-profile/confirm`, { method: "POST", body: JSON.stringify(body) }),
  finalReviewDecision: (jobId: string, body: { decision: FinalReviewDecision; note?: string }) =>
    request<FinalReviewDecisionResponse>(`/jobs/${jobId}/final-review`, { method: "POST", body: JSON.stringify(body) }),
  getJobPublicationPlan: (jobId: string, creatorProfileId?: string | null) =>
    request<PublicationPlan>(
      `/jobs/${jobId}/publication/plan${creatorProfileId ? `?creator_profile_id=${encodeURIComponent(creatorProfileId)}` : ""}`,
    ),
  publishJob: (
    jobId: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>(`/jobs/${jobId}/publication/publish`, { method: "POST", body: JSON.stringify(body) }),
  rerunJob: (jobId: string, body: { issue_code?: string; rerun_start_step?: string; note?: string }) =>
    request<JobRerunResponse>(`/jobs/${jobId}/rerun`, { method: "POST", body: JSON.stringify(body) }),
  initializeJob: (
    jobId: string,
    body: {
      language: string;
      workflow_template?: string;
      workflow_mode: string;
      enhancement_modes: string[];
      output_dir?: string;
      video_description: string;
    },
  ) => request<Job>(`/jobs/${jobId}/initialize`, { method: "POST", body: JSON.stringify(body) }),
  applyReview: (jobId: string, actions: Array<{ target_type: string; target_id: string; action: string; override_text?: string }>) =>
    request<{ applied: number }>(`/jobs/${jobId}/review/apply`, { method: "POST", body: JSON.stringify({ actions }) }),
  contentProfileThumbnailUrl: (jobId: string, index: number, version?: string | null) =>
    apiPath(`/jobs/${jobId}/content-profile/thumbnail?index=${index}${version ? `&v=${encodeURIComponent(version)}` : ""}`),
  warmContentProfileThumbnails: (jobId: string) => request<{ status: string; job_id: string }>(`/jobs/${jobId}/content-profile/thumbnails/warm`, {
    method: "POST",
  }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  restartJob: (jobId: string) => request<Job>(`/jobs/${jobId}/restart`, { method: "POST" }),
  deleteJob: (jobId: string) => request<void>(`/jobs/${jobId}`, { method: "DELETE" }),
  openJobFolder: (jobId: string) => request<{ path: string; kind: string }>(`/jobs/${jobId}/open-folder`, { method: "POST" }),
};

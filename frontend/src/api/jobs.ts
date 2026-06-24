import type {
  ContentProfileReview,
  JobAgentDecision,
  JobAgentPlan,
  Job,
  JobActivity,
  JobDownloadFiles,
  JobManualEditApplyPayload,
  JobManualEditApplyResponse,
  JobManualEditDraftResponse,
  JobManualEditPreviewAssets,
  JobManualEditorReadiness,
  JobManualRotationDetectResponse,
  JobManualEditSession,
  JobTimeline,
  JobsUsageSummary,
  JobsUsageTrend,
  PublicationPlan,
  PublicationPlatformPublishOptions,
  Report,
  RemixProductionTasks,
  StrategyReviewGates,
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

type JobDownloadBlob = {
  blob: Blob;
  filename: string;
};

function fallbackManualEditorReadiness(
  jobId: string,
  detail?: string,
  status: JobManualEditorReadiness["status"] = "preprocessing",
  canOpenEditor = false,
): JobManualEditorReadiness {
  return {
    job_id: jobId,
    status,
    can_open_editor: canOpenEditor,
    can_edit: canOpenEditor,
    progress_percent: canOpenEditor ? 100 : 0,
    current_step: null,
    detail: detail || "正在生成手动调整所需信息。",
    required_steps: [],
    missing: [],
  };
}

async function fallbackReadinessFromManualEditorSession(jobId: string): Promise<JobManualEditorReadiness> {
  const response = await fetch(apiPath(`/jobs/${jobId}/manual-editor`), {
    headers: { "Content-Type": "application/json" },
  });
  if (response.ok) {
    return fallbackManualEditorReadiness(jobId, "后端尚未提供准备状态接口，但手动调整工作区已可打开。", "ready", true);
  }
  if (response.status === 404) {
    return fallbackManualEditorReadiness(jobId, "正在等待手动调整预处理完成。");
  }
  const payload = await response.json().catch(() => ({ detail: response.statusText }));
  throw new Error(String(payload.detail || response.statusText || "Manual editor readiness failed"));
}

function parseDownloadFilename(header: string | null, fallback: string) {
  if (!header) return fallback;
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const plainMatch = header.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] || fallback;
}

async function requestDownloadZip(jobId: string, fileIds: string[]): Promise<JobDownloadBlob> {
  const response = await fetch(apiPath(`/jobs/${jobId}/download/zip`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(String(payload.detail || response.statusText || "Download failed"));
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(response.headers.get("Content-Disposition"), "roughcut_outputs.zip"),
  };
}

export const jobsApi = {
  listJobs: (limit = 50, offset = 0) =>
    request<Job[]>(`/jobs?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  getRemixProductionTasks: () => request<RemixProductionTasks>("/jobs/remix-production/tasks"),
  createRemixProductionTaskJob: (season: number, episode: number) =>
    request<Job>("/jobs/remix-production/tasks/job", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ season, episode }),
    }),
  startRemixProductionJob: (jobId: string, force = false) =>
    request<{ job_id: string; status: string; detail: string; command: string[] }>(
      `/jobs/remix-production/jobs/${jobId}/start${force ? "?force=true" : ""}`,
      { method: "POST" },
    ),
  getJobsUsageSummary: (limit = 60) => request<JobsUsageSummary>(`/jobs/usage-summary?limit=${limit}`),
  getJobsUsageTrend: (days = 7, limit = 120, focusType?: string, focusName?: string) =>
    request<JobsUsageTrend>(
      `/jobs/usage-trend?days=${days}&limit=${limit}${focusType ? `&focus_type=${encodeURIComponent(focusType)}` : ""}${focusName ? `&focus_name=${encodeURIComponent(focusName)}` : ""}`,
    ),
  createJob: async (
    files: File[],
    language: string,
    workflowTemplate?: string,
    jobFlowMode?: string,
    workflowMode?: string,
    enhancementModes: string[] = [],
    selectedSmartCutRuleReasons: string[] = [],
    materialEnhancementModes: string[] = [],
    selectedAgentCapabilityKeys: string[] = [],
    hyperframesOptions: Record<string, boolean> = {},
    outputDir?: string,
    videoDescription?: string,
    creatorCardId?: string,
    taskBrief?: string,
    executionMode?: string,
    platformTargets: string[] = [],
  ) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    formData.append("language", language);
    if (workflowTemplate) formData.append("workflow_template", workflowTemplate);
    if (jobFlowMode) formData.append("job_flow_mode", jobFlowMode);
    if (workflowMode) formData.append("workflow_mode", workflowMode);
    if (outputDir?.trim()) formData.append("output_dir", outputDir.trim());
    if (videoDescription?.trim()) formData.append("video_description", videoDescription.trim());
    if (creatorCardId) formData.append("creator_card_id", creatorCardId);
    if (taskBrief?.trim()) formData.append("task_brief", taskBrief.trim());
    if (executionMode) formData.append("execution_mode", executionMode);
    formData.append("smart_cut_rule_reasons", JSON.stringify(selectedSmartCutRuleReasons));
    formData.append("material_enhancement_modes", JSON.stringify(materialEnhancementModes));
    formData.append("agent_capability_keys", JSON.stringify(selectedAgentCapabilityKeys));
    formData.append("hyperframes_options", JSON.stringify(hyperframesOptions));
    platformTargets.forEach((platform) => formData.append("platform_targets", platform));
    enhancementModes.forEach((mode) => formData.append("enhancement_modes", mode));
    return requestForm<Job>("/jobs", formData);
  },
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  getJobActivity: (jobId: string) => request<JobActivity>(`/jobs/${jobId}/activity`),
  getJobAgentPlan: (jobId: string) => request<JobAgentPlan>(`/jobs/${jobId}/agent-plan`),
  refineJobAgentPlan: (jobId: string, body: { prompt: string; target?: string }) =>
    request<JobAgentPlan>(`/jobs/${jobId}/agent-plan/refine`, { method: "POST", body: JSON.stringify(body) }),
  applyJobAgentPlan: (
    jobId: string,
    body: { selected_strategy_id?: string; selected_visual_plan_id?: string; selected_publication_profile_id?: string },
  ) => request<JobAgentPlan>(`/jobs/${jobId}/agent-plan/apply`, { method: "POST", body: JSON.stringify(body) }),
  getJobAgentDecisions: (jobId: string) => request<JobAgentDecision[]>(`/jobs/${jobId}/agent-decisions`),
  getJobTokenUsage: (jobId: string) => request<TokenUsageReport>(`/jobs/${jobId}/token-usage`),
  getJobReport: (jobId: string) => request<Report>(`/jobs/${jobId}/report`),
  getJobTimeline: (jobId: string) => request<JobTimeline>(`/jobs/${jobId}/timeline`),
  getJobManualEditorReadiness: async (jobId: string) => {
    const response = await fetch(apiPath(`/jobs/${jobId}/manual-editor/readiness`), {
      headers: { "Content-Type": "application/json" },
    });
    if (response.status === 404) {
      return fallbackReadinessFromManualEditorSession(jobId);
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(String(payload.detail || response.statusText || "Manual editor readiness failed"));
    }
    return response.json() as Promise<JobManualEditorReadiness>;
  },
  getJobManualEditor: (jobId: string) => request<JobManualEditSession>(`/jobs/${jobId}/manual-editor`),
  getJobManualEditorAssets: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets`),
  getJobManualEditorAssetsStatus: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets/status`),
  warmJobManualEditorAssets: (jobId: string) => request<JobManualEditPreviewAssets>(`/jobs/${jobId}/manual-editor/assets/warm`, { method: "POST" }),
  saveJobManualEditorDraft: (jobId: string, body: JobManualEditApplyPayload) =>
    request<JobManualEditDraftResponse>(`/jobs/${jobId}/manual-editor/draft`, { method: "POST", body: JSON.stringify(body) }),
  detectJobManualEditorRotation: (jobId: string) =>
    request<JobManualRotationDetectResponse>(`/jobs/${jobId}/manual-editor/rotation/detect`, { method: "POST" }),
  applyJobManualEditor: (jobId: string, body: JobManualEditApplyPayload) =>
    request<JobManualEditApplyResponse>(`/jobs/${jobId}/manual-editor/apply`, { method: "POST", body: JSON.stringify(body) }),
  getContentProfile: (jobId: string) => request<ContentProfileReview>(`/jobs/${jobId}/content-profile`),
  confirmContentProfile: (jobId: string, body: Record<string, unknown>) =>
    request<ContentProfileReview>(`/jobs/${jobId}/content-profile/confirm`, { method: "POST", body: JSON.stringify(body) }),
  confirmStrategyReviewGates: (jobId: string, body: { gate_ids?: string[]; status?: string; note?: string } = {}) =>
    request<StrategyReviewGates>(`/jobs/${jobId}/strategy-review-gates/confirm`, { method: "POST", body: JSON.stringify(body) }),
  finalReviewDecision: (jobId: string, body: { decision: FinalReviewDecision; note?: string }) =>
    request<FinalReviewDecisionResponse>(`/jobs/${jobId}/final-review`, { method: "POST", body: JSON.stringify(body) }),
  getJobPublicationPlan: (jobId: string, creatorProfileId?: string | null) =>
    request<PublicationPlan>(
      `/jobs/${jobId}/publication/plan${creatorProfileId ? `?creator_profile_id=${encodeURIComponent(creatorProfileId)}` : ""}`,
    ),
  prepareJobPublicationMaterials: (
    jobId: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>(`/jobs/${jobId}/publication/materials`, { method: "POST", body: JSON.stringify(body) }),
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
      job_flow_mode: string;
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
  jobCoverThumbnailUrl: (jobId: string, version?: string | null) =>
    apiPath(`/jobs/${jobId}/cover-thumbnail${version ? `?v=${encodeURIComponent(version)}` : ""}`),
  warmContentProfileThumbnails: (jobId: string) => request<{ status: string; job_id: string }>(`/jobs/${jobId}/content-profile/thumbnails/warm`, {
    method: "POST",
  }),
  jobRenderedFileUrl: (jobId: string, variant: "packaged" | "plain" = "packaged") =>
    apiPath(`/jobs/${jobId}/download/file?variant=${encodeURIComponent(variant)}&disposition=inline`),
  getJobDownloadFiles: (jobId: string) => request<JobDownloadFiles>(`/jobs/${jobId}/download/files`),
  downloadJobFiles: requestDownloadZip,
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  restartJob: (jobId: string) => request<Job>(`/jobs/${jobId}/restart`, { method: "POST" }),
  deleteJob: (jobId: string) => request<void>(`/jobs/${jobId}`, { method: "DELETE" }),
  openJobFolder: (jobId: string) => request<{ path: string; kind: string }>(`/jobs/${jobId}/open-folder`, { method: "POST" }),
};

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { CapabilityDefinition, Job, JobActivity, SelectOption } from "../../types";
import { maybeNotify } from "../../utils/browserNotifications";
import { normalizeKeywordList } from "./contentProfile";
import type { UploadForm } from "./constants";

const EMPTY_UPLOAD: UploadForm = {
  files: [],
  language: "zh-CN",
  workflowTemplate: "",
  jobFlowMode: "auto",
  workflowMode: "standard_edit",
  enhancementModes: [],
  selectedSmartCutRuleReasons: [],
  materialEnhancementModes: [],
  selectedAgentCapabilityKeys: [],
  hyperframesOptions: {
    smart_effects: true,
    subtitle_emphasis: true,
    sound_cues: true,
    progress_bar: true,
    chapter_cards: true,
    unified_subtitle_style: true,
  },
  creatorCardId: "",
  executionMode: "auto",
  platformTargets: [],
  taskBrief: "",
  outputDir: "",
  videoDescription: "",
};

type PendingInitializationForm = {
  language: string;
  workflowTemplate: string;
  jobFlowMode: string;
  workflowMode: string;
  enhancementModes: string[];
  outputDir: string;
  videoDescription: string;
};

const EMPTY_PENDING_INITIALIZATION: PendingInitializationForm = {
  language: "zh-CN",
  workflowTemplate: "",
  jobFlowMode: "auto",
  workflowMode: "standard_edit",
  enhancementModes: [],
  outputDir: "",
  videoDescription: "",
};

const JOBS_PAGE_SIZE = 20;
const OUTPUT_DIR_HISTORY_STORAGE_KEY = "roughcut.jobs.outputDirHistory";
const CREATE_TASK_PREFERENCES_STORAGE_KEY = "roughcut.jobs.createTaskPreferences";
const OUTPUT_DIR_HISTORY_LIMIT = 8;
export const MATERIAL_ENHANCEMENT_OPTIONS: SelectOption[] = [
  { value: "voice_enhancement", label: "人声增强" },
  { value: "loudness_normalization", label: "响度统一" },
];

const JOB_STATUS_GROUP_PRIORITY: Record<string, number> = {
  awaiting_init: 1,
  needs_review: 0,
  awaiting_manual_edit: 0,
  running: 1,
  processing: 1,
  pending: 1,
};
const JOB_NOTIFY_TAG_PREFIX = "roughcut-job-status";
const JOB_STATUS_NOTIFY = {
  completed: "done",
  needsReview: "needs_review",
  manualEdit: "awaiting_manual_edit",
};
const JOB_TYPE_LABEL: Record<string, string> = {
  publication: "发布任务",
  remix_production: "影视二创",
  edit: "剪辑任务",
};

function jobTaskTypeLabel(job: Pick<Job, "queue_task_kind" | "source_name">): string {
  return JOB_TYPE_LABEL[job.queue_task_kind ?? "edit"] ?? "任务";
}

export type JobQueueFilter = "all" | "pending" | "running" | "done" | "attention";
export type JobTaskKindFilter = "all" | NonNullable<Job["queue_task_kind"]>;

type UseJobWorkspaceOptions = {
  isCreateOpen?: boolean;
  additionalJobs?: Job[];
  taskKindFilter?: JobTaskKindFilter;
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
  return status === "needs_review" || status === "awaiting_manual_edit" || status === "failed" || status === "cancelled" || status === "blocked_missing_script";
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

function matchesTaskKindFilter(job: Job, filter: JobTaskKindFilter) {
  if (filter === "all") return true;
  return (job.queue_task_kind ?? "edit") === filter;
}

function sameBoolRecord(left: Record<string, boolean>, right: Record<string, boolean>) {
  const keys = [...new Set([...Object.keys(left), ...Object.keys(right)])];
  return keys.every((key) => Boolean(left[key]) === Boolean(right[key]));
}

function normalizedUniqueStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((item) => String(item ?? "").trim()).filter(Boolean))];
}

function optionValues(options: Array<Pick<SelectOption, "value">>): string[] {
  return options.map((option) => String(option.value ?? "").trim()).filter(Boolean);
}

function capabilityKeys(capabilities: CapabilityDefinition[]): string[] {
  return capabilities.map((capability) => String(capability.key ?? "").trim()).filter(Boolean);
}

type StoredCreateTaskPreferences = {
  workflowMode?: string;
  enhancementModes?: string[];
  selectedSmartCutRuleReasons?: string[];
  materialEnhancementModes?: string[];
  selectedAgentCapabilityKeys?: string[];
  hyperframesOptions?: Record<string, boolean>;
};

function readStoredCreateTaskPreferences(): StoredCreateTaskPreferences {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(CREATE_TASK_PREFERENCES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const payload = parsed as Record<string, unknown>;
    return {
      workflowMode: String(payload.workflowMode ?? "").trim() || undefined,
      enhancementModes: Array.isArray(payload.enhancementModes) ? normalizedUniqueStrings(payload.enhancementModes) : undefined,
      selectedSmartCutRuleReasons: Array.isArray(payload.selectedSmartCutRuleReasons)
        ? normalizedUniqueStrings(payload.selectedSmartCutRuleReasons)
        : undefined,
      materialEnhancementModes: Array.isArray(payload.materialEnhancementModes)
        ? normalizedUniqueStrings(payload.materialEnhancementModes)
        : undefined,
      selectedAgentCapabilityKeys: Array.isArray(payload.selectedAgentCapabilityKeys)
        ? normalizedUniqueStrings(payload.selectedAgentCapabilityKeys)
        : undefined,
      hyperframesOptions: payload.hyperframesOptions && typeof payload.hyperframesOptions === "object" && !Array.isArray(payload.hyperframesOptions)
        ? Object.fromEntries(
          Object.entries(payload.hyperframesOptions as Record<string, unknown>).map(([key, value]) => [key, Boolean(value)]),
        )
        : undefined,
    };
  } catch {
    return {};
  }
}

function writeStoredCreateTaskPreferences(upload: UploadForm) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      CREATE_TASK_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        workflowMode: upload.workflowMode,
        enhancementModes: upload.enhancementModes,
        selectedSmartCutRuleReasons: upload.selectedSmartCutRuleReasons,
        materialEnhancementModes: upload.materialEnhancementModes,
        selectedAgentCapabilityKeys: upload.selectedAgentCapabilityKeys,
        hyperframesOptions: upload.hyperframesOptions,
      }),
    );
  } catch {
    // Local storage is only a convenience for restoring the next create-task form.
  }
}

function normalizeOutputDir(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

function mergeOutputDirHistory(paths: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const path of paths) {
    const outputDir = normalizeOutputDir(path);
    if (!outputDir || seen.has(outputDir)) continue;
    seen.add(outputDir);
    next.push(outputDir);
    if (next.length >= OUTPUT_DIR_HISTORY_LIMIT) break;
  }
  return next;
}

function readStoredOutputDirHistory(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(OUTPUT_DIR_HISTORY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? mergeOutputDirHistory(parsed.map(String)) : [];
  } catch {
    return [];
  }
}

function writeStoredOutputDirHistory(paths: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(OUTPUT_DIR_HISTORY_STORAGE_KEY, JSON.stringify(paths));
  } catch {
    // Local storage is only a convenience for quick selections.
  }
}

function compareJobs(a: { status: string; updated_at: string }, b: { status: string; updated_at: string }) {
  const groupGap = (JOB_STATUS_GROUP_PRIORITY[a.status] ?? 2) - (JOB_STATUS_GROUP_PRIORITY[b.status] ?? 2);
  if (groupGap !== 0) return groupGap;
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

export function useJobWorkspace({
  isCreateOpen = false,
  additionalJobs = [],
  taskKindFilter = "all",
}: UseJobWorkspaceOptions = {}) {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const previousJobStatusRef = useRef<Map<string, string>>(new Map());
  const [keyword, setKeyword] = useState("");
  const [queueFilter, setQueueFilter] = useState<JobQueueFilter>("all");
  const [jobsPage, setJobsPage] = useState(0);
  const [upload, setUpload] = useState<UploadForm>(EMPTY_UPLOAD);
  const [storedOutputDirHistory, setStoredOutputDirHistory] = useState<string[]>(readStoredOutputDirHistory);
  const [storedCreateTaskPreferences] = useState<StoredCreateTaskPreferences>(readStoredCreateTaskPreferences);
  const [pendingInitialization, setPendingInitialization] = useState<PendingInitializationForm>(EMPTY_PENDING_INITIALIZATION);
  const [contentDraft, setContentDraft] = useState<Record<string, unknown>>({});
  const [reviewWorkflowMode, setReviewWorkflowMode] = useState("standard_edit");
  const [reviewEnhancementModes, setReviewEnhancementModes] = useState<string[]>([]);
  const [reviewCopyStyle, setReviewCopyStyle] = useState("attention_grabbing");
  const [restartError, setRestartError] = useState<string | null>(null);
  const previousUploadDefaultsRef = useRef({
    workflowMode: EMPTY_UPLOAD.workflowMode,
    enhancementModes: EMPTY_UPLOAD.enhancementModes,
    selectedSmartCutRuleReasons: EMPTY_UPLOAD.selectedSmartCutRuleReasons,
    materialEnhancementModes: EMPTY_UPLOAD.materialEnhancementModes,
    selectedAgentCapabilityKeys: EMPTY_UPLOAD.selectedAgentCapabilityKeys,
    hyperframesOptions: EMPTY_UPLOAD.hyperframesOptions,
  });

  const jobs = useQuery({
    queryKey: ["jobs", JOBS_PAGE_SIZE, jobsPage],
    queryFn: () => api.listJobs(JOBS_PAGE_SIZE, jobsPage * JOBS_PAGE_SIZE),
    refetchInterval: 8_000,
  });
  const creatorCards = useQuery({
    queryKey: ["creator-cards"],
    queryFn: api.listCreatorCards,
    enabled: isCreateOpen,
  });

  useEffect(() => {
    const items = jobs.data;
    if (!items?.length) {
      previousJobStatusRef.current = new Map();
      return;
    }

    const nextStatusById = new Map<string, string>();
    const notifications: Array<{ title: string; body: string; tag: string }> = [];

    items.forEach((job) => {
      const previousStatus = previousJobStatusRef.current.get(job.id);
      nextStatusById.set(job.id, job.status);

      if (!previousStatus || previousStatus === job.status) return;

      if (job.status === JOB_STATUS_NOTIFY.completed) {
        notifications.push({
          title: `${jobTaskTypeLabel(job)}完成`,
          body: `${job.source_name} 已完成`,
          tag: `${JOB_NOTIFY_TAG_PREFIX}-completed-${job.id}`,
        });
      } else if (job.status === JOB_STATUS_NOTIFY.needsReview) {
        notifications.push({
          title: `${jobTaskTypeLabel(job)}进入待核对`,
          body: `${job.source_name} 已进入审核阶段`,
          tag: `${JOB_NOTIFY_TAG_PREFIX}-needs-review-${job.id}`,
        });
      } else if (job.status === JOB_STATUS_NOTIFY.manualEdit) {
        notifications.push({
          title: `${jobTaskTypeLabel(job)}进入手工剪辑`,
          body: `${job.source_name} 已进入手工调整阶段`,
          tag: `${JOB_NOTIFY_TAG_PREFIX}-manual-edit-${job.id}`,
        });
      }
    });

    previousJobStatusRef.current = nextStatusById;
    notifications.forEach((notification) => {
      void maybeNotify(notification);
    });
  }, [jobs.data]);

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
  const agentPlan = useQuery({
    queryKey: ["job-agent-plan", selectedJobId],
    queryFn: () => api.getJobAgentPlan(selectedJobId!),
    enabled: Boolean(selectedJobId),
    refetchInterval: selectedJobId ? 10_000 : false,
  });
  const agentDecisions = useQuery({
    queryKey: ["job-agent-decisions", selectedJobId],
    queryFn: () => api.getJobAgentDecisions(selectedJobId!),
    enabled: Boolean(selectedJobId),
    refetchInterval: selectedJobId ? 10_000 : false,
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
    () => {
      const availableMaterialEnhancementModes = optionValues(MATERIAL_ENHANCEMENT_OPTIONS);
      const availableAgentCapabilityKeys = capabilityKeys(options.data?.capability_catalog ?? []);
      const storedMaterialEnhancementModes = normalizedUniqueStrings(storedCreateTaskPreferences.materialEnhancementModes)
        .filter((mode) => availableMaterialEnhancementModes.includes(mode));
      const storedAgentCapabilityKeys = normalizedUniqueStrings(storedCreateTaskPreferences.selectedAgentCapabilityKeys)
        .filter((key) => !availableAgentCapabilityKeys.length || availableAgentCapabilityKeys.includes(key));
      return {
        ...EMPTY_UPLOAD,
        workflowMode:
          storedCreateTaskPreferences.workflowMode
          ?? config.data?.default_job_workflow_mode
          ?? EMPTY_UPLOAD.workflowMode,
        enhancementModes:
          storedCreateTaskPreferences.enhancementModes
          ?? config.data?.default_job_enhancement_modes
          ?? EMPTY_UPLOAD.enhancementModes,
        selectedSmartCutRuleReasons: [],
        materialEnhancementModes: storedMaterialEnhancementModes.length || storedCreateTaskPreferences.materialEnhancementModes
          ? storedMaterialEnhancementModes
          : availableMaterialEnhancementModes,
        selectedAgentCapabilityKeys: storedAgentCapabilityKeys.length || storedCreateTaskPreferences.selectedAgentCapabilityKeys
          ? storedAgentCapabilityKeys
          : availableAgentCapabilityKeys,
        hyperframesOptions: storedCreateTaskPreferences.hyperframesOptions ?? EMPTY_UPLOAD.hyperframesOptions,
      };
    },
    [
      config.data?.default_job_workflow_mode,
      config.data?.default_job_enhancement_modes,
      options.data?.capability_catalog,
      storedCreateTaskPreferences,
    ],
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
      jobFlowMode: detail.data.job_flow_mode || "auto",
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
      selectedSmartCutRuleReasons: inheritedUploadDefaults.selectedSmartCutRuleReasons,
      materialEnhancementModes: inheritedUploadDefaults.materialEnhancementModes,
      selectedAgentCapabilityKeys: inheritedUploadDefaults.selectedAgentCapabilityKeys,
      hyperframesOptions: inheritedUploadDefaults.hyperframesOptions,
    };

    setUpload((prev) => {
      const followsPreviousDefaults =
        prev.workflowMode === previousDefaults.workflowMode
        && sameStringArray(prev.enhancementModes, previousDefaults.enhancementModes)
        && sameStringArray(prev.selectedSmartCutRuleReasons, previousDefaults.selectedSmartCutRuleReasons)
        && sameStringArray(prev.materialEnhancementModes, previousDefaults.materialEnhancementModes)
        && sameStringArray(prev.selectedAgentCapabilityKeys, previousDefaults.selectedAgentCapabilityKeys)
        && sameBoolRecord(prev.hyperframesOptions, previousDefaults.hyperframesOptions);

      return followsPreviousDefaults
        ? {
          ...prev,
          workflowMode: nextDefaults.workflowMode,
          enhancementModes: nextDefaults.enhancementModes,
          selectedSmartCutRuleReasons: nextDefaults.selectedSmartCutRuleReasons,
          materialEnhancementModes: nextDefaults.materialEnhancementModes,
          selectedAgentCapabilityKeys: nextDefaults.selectedAgentCapabilityKeys,
          hyperframesOptions: nextDefaults.hyperframesOptions,
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
      void queryClient.invalidateQueries({ queryKey: ["job-agent-plan", selectedJobId] });
      void queryClient.invalidateQueries({ queryKey: ["job-agent-decisions", selectedJobId] });
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
      await queryClient.removeQueries({ queryKey: ["job-agent-plan", jobId] });
      await queryClient.removeQueries({ queryKey: ["job-agent-decisions", jobId] });
    },
  });
  const uploadJob = useMutation({
    mutationFn: async () =>
      api.createJob(
        upload.files,
        upload.language,
        upload.workflowTemplate || undefined,
        upload.jobFlowMode,
        upload.workflowMode,
        upload.enhancementModes,
        upload.selectedSmartCutRuleReasons,
        upload.materialEnhancementModes,
        upload.selectedAgentCapabilityKeys,
        upload.hyperframesOptions,
        upload.outputDir,
        upload.videoDescription,
        upload.creatorCardId || undefined,
        upload.taskBrief,
        upload.executionMode,
        upload.platformTargets,
      ),
    onSuccess: async (job) => {
      setStoredOutputDirHistory((prev) => {
        const next = mergeOutputDirHistory([upload.outputDir, ...prev]);
        writeStoredOutputDirHistory(next);
        return next;
      });
      writeStoredCreateTaskPreferences(upload);
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
        job_flow_mode: pendingInitialization.jobFlowMode,
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
  const refineAgentPlan = useMutation({
    mutationFn: async (payload: { prompt: string; target?: string }) =>
      api.refineJobAgentPlan(selectedJobId!, payload),
    onSuccess: refreshAll,
  });
  const applyAgentPlan = useMutation({
    mutationFn: async (payload: { selected_strategy_id?: string; selected_visual_plan_id?: string; selected_publication_profile_id?: string }) =>
      api.applyJobAgentPlan(selectedJobId!, payload),
    onSuccess: refreshAll,
  });
  const searchMatchedJobs = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    const allJobs = [...(jobs.data ?? []), ...additionalJobs];
    const visibleJobs = !needle
      ? allJobs
      : allJobs.filter((job) =>
        [job.source_name, job.content_subject, job.content_summary, job.video_description, job.status, job.task_brief].some((field) =>
          String(field ?? "").toLowerCase().includes(needle),
        ),
    );
    return [...visibleJobs].filter((job) => matchesTaskKindFilter(job, taskKindFilter)).sort(compareJobs);
  }, [additionalJobs, jobs.data, keyword, taskKindFilter]);
  const queueStats = useMemo(() => ({
    total: searchMatchedJobs.length,
    pending: searchMatchedJobs.filter((job) => isPendingJob(job.status)).length,
    running: searchMatchedJobs.filter((job) => isRunningJob(job.status)).length,
    done: searchMatchedJobs.filter((job) => job.status === "done").length,
    attention: searchMatchedJobs.filter((job) => isAttentionJob(job.status)).length,
    needsReview: searchMatchedJobs.filter((job) => job.status === "needs_review").length,
    failed: searchMatchedJobs.filter((job) => job.status === "failed").length,
    cancelled: searchMatchedJobs.filter((job) => job.status === "cancelled").length,
    blockedMissingScript: searchMatchedJobs.filter((job) => job.status === "blocked_missing_script").length,
  }), [searchMatchedJobs]);
  const filteredJobs = useMemo(
    () => searchMatchedJobs.filter((job) => matchesQueueFilter(job.status, queueFilter)),
    [queueFilter, searchMatchedJobs],
  );
  const outputDirHistory = useMemo(
    () => mergeOutputDirHistory([
      ...storedOutputDirHistory,
      ...(jobs.data ?? []).map((job) => job.output_dir),
    ]),
    [jobs.data, storedOutputDirHistory],
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
    creatorCards,
    outputDirHistory,
    pendingInitialization,
    setPendingInitialization,
    contentDraft,
    setContentDraft,
    jobs,
    detail,
    activity,
    agentPlan,
    agentDecisions,
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
    refineAgentPlan,
    applyAgentPlan,
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

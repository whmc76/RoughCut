import type { Job } from "../../types";
import { getCurrentUiLocale, translate } from "../../i18n";

export const STEP_LABELS: Record<string, string> = {
  probe: "探测",
  extract_audio: "提音频",
  transcribe: "转写",
  subtitle_postprocess: "字幕",
  subtitle_term_resolution: "术语纠偏",
  subtitle_consistency_review: "一致性审校",
  transcript_review: "转写审校",
  subtitle_quality: "字幕质量",
  subtitle_translation: "翻译",
  content_profile: "摘要",
  summary_review: "内容异常门",
  glossary_review: "纠错",
  ai_director: "导演",
  avatar_commentary: "数字人",
  edit_plan: "剪辑",
  render: "渲染",
  final_review: "成片异常门",
  platform_package: "文案",
};

export const CONTENT_FIELDS = [
  "video_type",
  "video_theme",
  "hook_line",
  "summary",
  "engagement_question",
  "correction_notes",
  "supplemental_context",
] as const;

export const CONTENT_FIELD_LABELS: Record<(typeof CONTENT_FIELDS)[number] | "keywords", string> = {
  video_type: "视频类型",
  video_theme: "视频主题",
  hook_line: "标题钩子",
  summary: "内容摘要",
  engagement_question: "互动提问",
  correction_notes: "校对备注",
  supplemental_context: "补充上下文",
  keywords: "关键词",
};

export const IDENTITY_SUPPORT_SOURCE_LABELS: Record<string, string> = {
  transcript: "字幕",
  subtitle_snippets: "字幕",
  source_name: "文件名",
  source_name_terms: "文件名",
  visible_text: "画面文字",
  visible_text_terms: "画面文字",
  evidence: "外部证据",
  evidence_terms: "外部证据",
};

export type UploadForm = {
  files: File[];
  language: string;
  workflowTemplate: string;
  workflowMode: string;
  enhancementModes: string[];
  outputDir: string;
  videoDescription: string;
};

export const RESTARTABLE_JOB_STATUSES = ["done", "running", "processing", "needs_review", "cancelled", "failed"] as const;

function normalizeJobStatus(status: string): string {
  return String(status ?? "").trim().toLowerCase();
}

export const RESTART_UNAVAILABLE_REASONS: Record<string, string> = {
  pending: "jobs.actions.restartUnavailableReason.pending",
  done: "",
  running: "",
  processing: "",
  needs_review: "",
  cancelled: "",
  failed: "",
};

export function isRestartableJobStatus(status: string): boolean {
  return (RESTARTABLE_JOB_STATUSES as readonly string[]).includes(normalizeJobStatus(status));
}

export function getRestartUnavailableReason(status: string): string {
  return RESTART_UNAVAILABLE_REASONS[normalizeJobStatus(status)] || "jobs.actions.restartUnavailableReason.default";
}

export function jobStatusLabel(job: Pick<Job, "status" | "publication_status">): string {
  if (job.status === "done") {
    return job.publication_status === "published" ? "已发布" : "剪辑完成";
  }
  if (job.status === "pending") return "待处理";
  if (job.status === "awaiting_init") return "待初始化";
  if (job.status === "running") return "进行中";
  if (job.status === "processing") return "处理中";
  if (job.status === "failed") return "失败";
  if (job.status === "cancelled") return "已取消";
  if (job.status === "needs_review") return "待核对";
  return job.status;
}

export function jobStatusTone(job: Pick<Job, "status" | "publication_status">): string {
  if (job.status === "done" && job.publication_status === "published") return "published";
  return job.status;
}

export const WORKFLOW_MODE_LABELS: Record<string, string> = {
  standard_edit: "标准成片",
  long_text_to_video: "长文本转视频",
};

export const ENHANCEMENT_MODE_LABELS: Record<string, string> = {
  multilingual_translation: "多语言翻译",
  auto_review: "异常门",
  multi_platform_adaptation: "多平台版本适配",
  avatar_commentary: "数字人解说",
  ai_effects: "智能剪辑特效",
  ai_director: "AI 导演",
};

export function stepLabel(stepName: string): string {
  const key = `jobs.steps.${stepName}`;
  const translated = translate(getCurrentUiLocale(), key);
  return translated === key ? STEP_LABELS[stepName] ?? stepName : translated;
}

export function contentFieldLabel(field: (typeof CONTENT_FIELDS)[number] | "keywords"): string {
  const key = `jobs.fields.${field}`;
  const translated = translate(getCurrentUiLocale(), key);
  return translated === key ? CONTENT_FIELD_LABELS[field] ?? field : translated;
}

export function workflowModeLabel(mode: string): string {
  const key = `creative.workflow.${mode}`;
  const translated = translate(getCurrentUiLocale(), key);
  return translated === key ? WORKFLOW_MODE_LABELS[mode] ?? mode : translated;
}

export function enhancementModeLabel(mode: string): string {
  const key = `creative.enhancement.${mode}`;
  const translated = translate(getCurrentUiLocale(), key);
  return translated === key ? ENHANCEMENT_MODE_LABELS[mode] ?? mode : translated;
}

export function autoReviewBadgeLabel(job: Pick<Job, "auto_review_mode_enabled" | "auto_review_status">): string {
  if (!job.auto_review_mode_enabled) return "异常门";
  return job.auto_review_status === "applied" ? "异常门已自动放行" : "异常门已启用";
}

export function autoReviewTone(status: string | null | undefined): string {
  if (status === "applied") return "done";
  if (status === "blocked") return "pending";
  return "running";
}

export function formatCutEvidenceSummary(timelineDiagnostics: Job["timeline_diagnostics"] | null | undefined): string | null {
  const protectedVisualCutCount = timelineDiagnostics?.protected_visual_cut_count ?? 0;
  const highProtectionEvidenceCount = timelineDiagnostics?.high_protection_evidence_count ?? 0;
  if (!protectedVisualCutCount && !highProtectionEvidenceCount) return null;
  return `${protectedVisualCutCount} 个 cut 命中展示保护，${highProtectionEvidenceCount} 个 cut 带高保护分。`;
}

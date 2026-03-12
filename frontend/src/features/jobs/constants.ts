export const STEP_LABELS: Record<string, string> = {
  probe: "探测",
  extract_audio: "提音频",
  transcribe: "转写",
  subtitle_postprocess: "字幕",
  content_profile: "摘要",
  summary_review: "核对",
  glossary_review: "纠错",
  edit_plan: "剪辑",
  render: "渲染",
  platform_package: "文案",
};

export const CONTENT_FIELDS = [
  "subject_brand",
  "subject_model",
  "subject_type",
  "video_theme",
  "hook_line",
  "visible_text",
  "summary",
  "engagement_question",
  "correction_notes",
  "supplemental_context",
] as const;

export type UploadForm = {
  file: File | null;
  language: string;
  channelProfile: string;
};

export function stepLabel(stepName: string): string {
  return STEP_LABELS[stepName] ?? stepName;
}

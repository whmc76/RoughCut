import type { UiLocale } from "../../i18n";
import { IDENTITY_SUPPORT_SOURCE_LABELS } from "./constants";

const SUPPORTED_VIDEO_TYPES = ["tutorial", "vlog", "commentary", "gameplay", "food", "unboxing"] as const;

const VIDEO_TYPE_LABELS: Record<UiLocale, Record<string, string>> = {
  "zh-CN": {
    tutorial: "教程",
    vlog: "Vlog",
    commentary: "观点",
    gameplay: "游戏",
    food: "探店",
    unboxing: "开箱",
  },
  "en-US": {
    tutorial: "Tutorial",
    vlog: "Vlog",
    commentary: "Commentary",
    gameplay: "Gameplay",
    food: "Food",
    unboxing: "Unboxing",
  },
};

function normalizeTextKey(value: unknown) {
  return getTextValue(value).toUpperCase().replace(/\s+/g, "");
}

export function getTextValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeUniqueStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const text = getTextValue(item);
    const key = normalizeTextKey(text);
    if (!text || seen.has(key)) {
      continue;
    }
    seen.add(key);
    normalized.push(text);
  }
  return normalized;
}

export function normalizeKeywordList(value: unknown) {
  return normalizeUniqueStringArray(value);
}

export function normalizeSourceList(value: unknown) {
  return normalizeUniqueStringArray(value);
}

export function normalizeVideoTypeValue(value: unknown) {
  const normalized = getTextValue(value).toLowerCase();
  if (!normalized) {
    return "";
  }
  if ((SUPPORTED_VIDEO_TYPES as readonly string[]).includes(normalized)) {
    return normalized;
  }
  if (normalized.includes("unboxing") || normalized.includes("开箱") || normalized.includes("机能包")) {
    return "unboxing";
  }
  if (normalized.includes("tutorial") || normalized.includes("教程")) {
    return "tutorial";
  }
  if (normalized.includes("vlog") || normalized.includes("生活") || normalized.includes("日常")) {
    return "vlog";
  }
  if (normalized.includes("commentary") || normalized.includes("观点") || normalized.includes("口播")) {
    return "commentary";
  }
  if (normalized.includes("gameplay") || normalized.includes("游戏")) {
    return "gameplay";
  }
  if (normalized.includes("food") || normalized.includes("探店")) {
    return "food";
  }
  return "";
}

export function normalizeVideoTypeLabel(value: unknown, locale: UiLocale) {
  const normalized = normalizeVideoTypeValue(value);
  if (!normalized) {
    return "";
  }
  const labels = VIDEO_TYPE_LABELS[locale] || VIDEO_TYPE_LABELS["zh-CN"];
  return labels[normalized] ?? "";
}

export function getVideoTypeOptions(locale: UiLocale) {
  const labels = VIDEO_TYPE_LABELS[locale] || VIDEO_TYPE_LABELS["zh-CN"];
  return [
    { value: "", label: locale === "en-US" ? "Pending" : "待补充" },
    ...SUPPORTED_VIDEO_TYPES.map((value) => ({
      value,
      label: labels[value],
    })),
  ];
}

export function formatVideoType(values: unknown[], locale: UiLocale) {
  for (const value of values) {
    const label = normalizeVideoTypeLabel(value, locale);
    if (label) {
      return label;
    }
  }
  return locale === "en-US" ? "Pending" : "待补充";
}

export function formatIdentityEvidenceSourceLabel(value: unknown) {
  const normalized = getTextValue(value);
  if (!normalized) {
    return "";
  }
  return IDENTITY_SUPPORT_SOURCE_LABELS[normalized] ?? normalized;
}

export function formatIdentityEvidenceSources(values: unknown) {
  const labels: string[] = [];
  const seen = new Set<string>();
  for (const value of normalizeSourceList(values)) {
    const label = formatIdentityEvidenceSourceLabel(value);
    const key = normalizeTextKey(label);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    labels.push(label);
  }
  return labels;
}

export function formatIdentityEvidenceGlossaryAliases(
  evidenceBundle: {
    matched_glossary_aliases?: {
      brand?: unknown[];
      model?: unknown[];
    } | null;
  } | null | undefined,
) {
  const aliases = evidenceBundle?.matched_glossary_aliases;
  const brandAliases = normalizeKeywordList(aliases?.brand ?? []);
  const modelAliases = normalizeKeywordList(aliases?.model ?? []);
  return [
    brandAliases.length ? `品牌：${brandAliases.join("、")}` : "",
    modelAliases.length ? `型号：${modelAliases.join("、")}` : "",
  ].filter(Boolean);
}

export function hasIdentityEvidence(identityReview: {
  required?: boolean;
  evidence_bundle?: {
    matched_subtitle_snippets?: unknown[];
    matched_glossary_aliases?: {
      brand?: unknown[];
      model?: unknown[];
    } | null;
    matched_source_name_terms?: unknown[];
    matched_visible_text_terms?: unknown[];
    matched_evidence_terms?: unknown[];
  } | null;
  support_sources?: unknown[];
} | null | undefined) {
  const evidenceBundle = identityReview?.evidence_bundle;
  return Boolean(
    identityReview
    && (
      identityReview.required
      || normalizeSourceList(identityReview.support_sources ?? []).length
      || (evidenceBundle?.matched_subtitle_snippets ?? []).length
      || formatIdentityEvidenceGlossaryAliases(evidenceBundle).length
      || (evidenceBundle?.matched_source_name_terms ?? []).length
      || (evidenceBundle?.matched_visible_text_terms ?? []).length
      || (evidenceBundle?.matched_evidence_terms ?? []).length
    ),
  );
}

function getObjectValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function getNumericValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

export type SemanticSpanView = {
  key: string;
  label: string;
  timestamp: string;
  text: string;
  detail: string[];
  startTime: number | null;
  endTime: number | null;
};

export type VideoUnderstandingSnapshot = {
  videoType: string;
  contentDomain: string;
  primarySubject: string;
  videoTheme: string;
  summary: string;
  styleProfile: string[];
  narrativeSections: string[];
  semanticSpans: SemanticSpanView[];
};

export function formatSecondsLabel(value: unknown) {
  const seconds = getNumericValue(value);
  if (seconds == null) {
    return "";
  }
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remain = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

export function formatSemanticSpanLabel(value: unknown) {
  const normalized = getTextValue(value).toLowerCase();
  if (!normalized) {
    return "内容片段";
  }
  const labels: Record<string, string> = {
    hook: "开场 Hook",
    setup: "铺垫",
    body: "主体段落",
    demo: "演示段",
    comparison: "对比段",
    detail: "细节段",
    detail_showcase: "细节展示",
    conclusion: "结论段",
    cta: "行动引导",
    transition: "过渡段",
    junk: "无效片段",
    retake: "重复拍摄",
  };
  return labels[normalized] ?? normalized;
}

function buildSemanticSpanTimestamp(span: Record<string, unknown>) {
  const explicitTimestamp = getTextValue(span.timestamp);
  if (explicitTimestamp) {
    return explicitTimestamp;
  }
  const start = formatSecondsLabel(span.start_time ?? span.start);
  const end = formatSecondsLabel(span.end_time ?? span.end);
  if (start && end) {
    return `${start}-${end}`;
  }
  return start || end;
}

function buildSemanticSpanDetail(span: Record<string, unknown>) {
  const detail: string[] = [];
  const keepPriority = getTextValue(span.keep_priority);
  const alignment = getTextValue(span.speech_visual_alignment);
  const reasonTags = normalizeKeywordList(span.reason_tags);
  if (keepPriority) {
    detail.push(`保留优先级：${keepPriority}`);
  }
  if (alignment) {
    detail.push(`视听一致性：${alignment}`);
  }
  if (reasonTags.length) {
    detail.push(`标签：${reasonTags.join("、")}`);
  }
  return detail;
}

function normalizeSemanticSpans(values: unknown) {
  if (!Array.isArray(values)) {
    return [];
  }
  const spans: SemanticSpanView[] = [];
  const seen = new Set<string>();
  values.forEach((value, index) => {
    const span = getObjectValue(value);
    if (!span) {
      return;
    }
    const label = formatSemanticSpanLabel(span.type ?? span.role);
    const timestamp = buildSemanticSpanTimestamp(span);
    const text = getTextValue(span.text ?? span.summary);
    const detail = buildSemanticSpanDetail(span);
    const key = `${timestamp}|${label}|${text || detail.join("|")}|${index}`;
    const dedupeKey = `${timestamp}|${label}|${text || detail.join("|")}`;
    if (seen.has(dedupeKey)) {
      return;
    }
    seen.add(dedupeKey);
    spans.push({
      key,
      label,
      timestamp,
      text,
      detail,
      startTime: getNumericValue(span.start_time ?? span.start),
      endTime: getNumericValue(span.end_time ?? span.end),
    });
  });
  return spans;
}

export function buildVideoUnderstandingSnapshot(
  contentSource: Record<string, unknown> | null | undefined,
  contentDraft?: Record<string, unknown> | null,
): VideoUnderstandingSnapshot | null {
  const sourceVideoUnderstanding = getObjectValue(contentSource?.video_understanding);
  const draftVideoUnderstanding = getObjectValue(contentDraft?.video_understanding);
  const videoUnderstanding = sourceVideoUnderstanding ?? draftVideoUnderstanding;
  const globalUnderstanding = getObjectValue(videoUnderstanding?.global_understanding);
  const styleProfile = getObjectValue(globalUnderstanding?.style_profile);
  const contentUnderstanding = getObjectValue(contentSource?.content_understanding);
  const draftUnderstanding = getObjectValue(contentDraft?.content_understanding);
  const understanding = contentUnderstanding ?? draftUnderstanding;
  const evidenceSpans = normalizeSemanticSpans(understanding?.evidence_spans);
  const timedFocusSpans = normalizeSemanticSpans(understanding?.timed_focus_spans);
  const semanticSpans = [...timedFocusSpans, ...evidenceSpans].slice(0, 10);
  const narrativeSections = Array.isArray(globalUnderstanding?.narrative_structure)
    ? (globalUnderstanding?.narrative_structure as unknown[])
      .map((item) => {
        const section = getObjectValue(item);
        if (!section) {
          return "";
        }
        const label = formatSemanticSpanLabel(section.label);
        const timestamp = buildSemanticSpanTimestamp(section);
        return [timestamp, label].filter(Boolean).join(" ");
      })
      .filter(Boolean)
    : [];
  const styleSummary = [
    getTextValue(styleProfile?.pace) ? `节奏 ${getTextValue(styleProfile?.pace)}` : "",
    getTextValue(styleProfile?.information_density) ? `信息密度 ${getTextValue(styleProfile?.information_density)}` : "",
    getTextValue(styleProfile?.emotion_intensity) ? `情绪 ${getTextValue(styleProfile?.emotion_intensity)}` : "",
  ].filter(Boolean);
  const snapshot: VideoUnderstandingSnapshot = {
    videoType: getTextValue(globalUnderstanding?.video_type ?? contentSource?.video_type ?? understanding?.video_type),
    contentDomain: getTextValue(globalUnderstanding?.content_domain ?? understanding?.content_domain),
    primarySubject: getTextValue(
      getObjectValue(globalUnderstanding?.primary_subject)?.name
      ?? understanding?.primary_subject
      ?? contentSource?.subject_type,
    ),
    videoTheme: getTextValue(globalUnderstanding?.video_theme ?? contentSource?.video_theme ?? understanding?.video_theme),
    summary: getTextValue(globalUnderstanding?.summary ?? contentSource?.summary ?? understanding?.summary),
    styleProfile: styleSummary,
    narrativeSections,
    semanticSpans,
  };
  if (
    !snapshot.videoType
    && !snapshot.contentDomain
    && !snapshot.primarySubject
    && !snapshot.videoTheme
    && !snapshot.summary
    && !snapshot.styleProfile.length
    && !snapshot.narrativeSections.length
    && !snapshot.semanticSpans.length
  ) {
    return null;
  }
  return snapshot;
}

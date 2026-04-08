import type { UiLocale } from "../../i18n";
import { IDENTITY_SUPPORT_SOURCE_LABELS } from "./constants";

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

export function normalizeVideoTypeLabel(value: unknown, locale: UiLocale) {
  const normalized = getTextValue(value).toLowerCase();
  if (!normalized) {
    return "";
  }
  const labels = VIDEO_TYPE_LABELS[locale] || VIDEO_TYPE_LABELS["zh-CN"];
  if (normalized in labels) {
    return labels[normalized];
  }
  if (normalized.includes("unboxing") || normalized.includes("开箱") || normalized.includes("机能包")) {
    return labels.unboxing;
  }
  if (normalized.includes("tutorial") || normalized.includes("教程")) {
    return labels.tutorial;
  }
  if (normalized.includes("vlog") || normalized.includes("生活") || normalized.includes("日常")) {
    return labels.vlog;
  }
  if (normalized.includes("commentary") || normalized.includes("观点") || normalized.includes("口播")) {
    return labels.commentary;
  }
  if (normalized.includes("gameplay") || normalized.includes("游戏")) {
    return labels.gameplay;
  }
  if (normalized.includes("food") || normalized.includes("探店")) {
    return labels.food;
  }
  return "";
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

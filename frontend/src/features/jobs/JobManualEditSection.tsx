import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type SyntheticEvent } from "react";
import type WaveSurfer from "wavesurfer.js";
import type { RegionsPlugin as RegionsPluginInstance } from "wavesurfer.js/dist/plugins/regions.esm.js";

import type { Job, JobManualEditApplyPayload, JobManualEditPreviewAssets, JobManualEditSession, JobManualEditSilence, JobManualEditSmartDelete, JobManualEditSubtitle, JobManualEditSubtitleOverride, JobManualEditWord, JobManualSubtitleReplacement, JobManualVideoTransform } from "../../types";
import { classNames } from "../../utils";

type JobManualEditSectionProps = {
  job?: Job;
  session: JobManualEditSession;
  previewAssets?: JobManualEditPreviewAssets;
  saving: boolean;
  autosaving?: boolean;
  autosavedAt?: string | null;
  detectingRotation?: boolean;
  resetSignal?: number;
  renderActionLabel?: string;
  onStateChange?: (state: JobManualEditSectionState) => void;
  onApply?: (payload: JobManualEditApplyPayload) => void;
  onAutoSave?: (payload: JobManualEditApplyPayload) => void;
  onDetectRotation?: () => Promise<number>;
};

export type JobManualEditSectionState = {
  payload: JobManualEditApplyPayload;
  canApply: boolean;
  hasMaterialEdits: boolean;
  hasLocalEdits: boolean;
  hasVideoSummaryEdits: boolean;
  savePlanLabel: string;
  baseSegmentCount: number;
  effectiveSegmentCount: number;
  outputDurationDeltaLabel: string;
  subtitleOverrideCount: number;
  saveImpactSummary: string;
};

type KeepSegment = {
  start: number;
  end: number;
};

type SilenceRange = KeepSegment & {
  duration_sec?: number;
  source?: string;
};

type OutputRange = {
  sourceStart: number;
  sourceEnd: number;
  outputStart: number;
  outputEnd: number;
};

type MappedSubtitleRange = {
  outputStart: number;
  outputEnd: number;
  sourceStart: number;
  sourceEnd: number;
};

type SubtitleDraft = {
  start_time?: number | null;
  end_time?: number | null;
  text_final?: string | null;
  delete?: boolean;
  virtual?: boolean;
};

type VisibleSubtitleRow = JobManualEditSubtitle & {
  deleted?: boolean;
  restoreRanges?: KeepSegment[];
};

type SubtitleTextDraft = {
  text_final?: string | null;
};

type SourceTimelineThumbnailItem = {
  url: string;
  timeSec: number;
  leftPercent: number;
  widthPercent: number;
};

type SourceTimelineRangeItem = KeepSegment & {
  leftPercent: number;
  widthPercent: number;
};

type FrequentTermKind = "名词/术语" | "动作词" | "描述词" | "专名/型号" | "低置信词";

type FrequentTerm = {
  term: string;
  normalized: string;
  count: number;
  kind: FrequentTermKind;
  reviewPriority: number;
  subtitleIndexes: number[];
  occurrences: JobManualEditSubtitle[];
  relatedTerms?: string[];
  manuallyAdded?: boolean;
};

type FrequentTermBucket = FrequentTerm & {
  entityContextCount: number;
  unstableSubtitleCount: number;
};

type ManualEditUndoSnapshot = {
  segments: KeepSegment[];
  selectedSegmentIndex: number;
  selectedSubtitleIndex: number | null;
  editingSubtitleIndex: number | null;
  currentSubtitleDraftText: string;
  subtitleDrafts: Record<number, SubtitleDraft>;
  subtitleReplacementHistory: JobManualSubtitleReplacement[];
  manualSmartCutRestoreRanges: KeepSegment[];
  manualSmartCutConfirmRanges: KeepSegment[];
  manualSmartCutDismissRanges: KeepSegment[];
  editorNote: string;
  videoSummary: string;
  videoTransform: JobManualVideoTransform;
};

type FloatingPreviewPosition = {
  x: number;
  y: number;
};

type SubtitleReplaceDialogState = {
  find: string;
  replacement: string;
  matchCount: number;
};

type PreviewPlaybackMode = "output" | null;
type EditedPlaybackSyncDecision =
  | { action: "none" }
  | { action: "seek"; sourceTime: number }
  | { action: "stop" };

type TranscriptTokenKind = "char" | "pause" | "punctuation";
type TranscriptBreakKind = "soft" | "paragraph";

type TranscriptToken = {
  key: string;
  kind: TranscriptTokenKind;
  text: string;
  subtitleIndex: number | null;
  start: number;
  end: number;
  kept: boolean;
  timingSource?: "word" | "alignment" | "estimated";
  pauseDuration?: number;
  pauseRanges?: KeepSegment[];
  pauseCount?: number;
  inferredPunctuation?: string;
  breakAfter?: TranscriptBreakKind;
};

type MergedTranscriptPauseRange = KeepSegment & {
  ranges: KeepSegment[];
};

type TranscriptSelection = {
  startTokenIndex: number;
  endTokenIndex: number;
  sourceStart: number;
  sourceEnd: number;
  text: string;
  keptTokenCount: number;
  cutTokenCount: number;
  pauseCount: number;
};

type TranscriptSelectionPopoverPosition = {
  left: number;
  top: number;
};

type SmartCutRules = {
  fillerEnabled: boolean;
  repeatedEnabled: boolean;
  pauseEnabled: boolean;
  smartDeleteEnabled: boolean;
  pauseThresholdSec: number;
  pauseBreathSec?: number;
  fillers: string;
};

type SmartCutRuleKind = "filler" | "repeated" | "pause" | "smart_delete";

type SmartCutRuleMatch = KeepSegment & {
  kind: SmartCutRuleKind;
  reason?: string;
  detail?: string | null;
  sourceText?: string;
  protected?: boolean;
};

type TimedSourceRange = KeepSegment & {
  timingSource: "word" | "alignment" | "estimated";
};

type SmartCutRuleAnalysis = {
  filler: SmartCutRuleMatch[];
  repeated: SmartCutRuleMatch[];
  pause: SmartCutRuleMatch[];
  pauseCandidates: SmartCutRuleMatch[];
  smartDelete: SmartCutRuleMatch[];
};

type SmartCutRulePreview = {
  kind: SmartCutRuleKind;
  label: string;
  reason: string;
  count: number;
  enabled: boolean;
  sampleText: string;
  sampleMeta: string;
};

type ManualEditChangeListTone = "timeline" | "video" | "subtitle" | "summary" | "empty";

type ManualEditChangeListItem = {
  key: string;
  title: string;
  detail: string;
  meta?: string;
  tone: ManualEditChangeListTone;
};

const REGION_COLOR = "rgba(34, 197, 94, 0.22)";
const REGION_ACTIVE_COLOR = "rgba(20, 184, 166, 0.36)";
const MIN_SUBTITLE_DURATION_SEC = 0.08;
const MIN_SUBTITLE_GAP_SEC = 0.02;
const SUBTITLE_DISPLAY_MAX_DURATION_SEC = 6.0;
const SUBTITLE_DISPLAY_MAX_CHARS = 32;
const INITIAL_WAVEFORM_ZOOM = 18;
const TERM_RESULT_LIMIT = 80;
const SUBTITLE_TABLE_WINDOW_SIZE = 220;
const FLOATING_PREVIEW_MARGIN = 16;
const TERM_STOPWORDS = new Set([
  "一个",
  "一下",
  "一些",
  "一样",
  "一段",
  "一种",
  "不是",
  "不要",
  "不能",
  "不太",
  "不过",
  "不同",
  "就不",
  "以及",
  "而且",
  "并且",
  "他们",
  "它的",
  "他的",
  "她的",
  "我的",
  "你的",
  "我们的",
  "你们的",
  "他们的",
  "以后",
  "以前",
  "但是",
  "除了",
  "你们",
  "其实",
  "只是",
  "可以",
  "可能",
  "很多",
  "功能",
  "因为",
  "大家",
  "如果",
  "就是",
  "已经",
  "我们",
  "或者",
  "也是",
  "所以",
  "所有",
  "然后",
  "现在",
  "这个",
  "这些",
  "这里",
  "这样",
  "这么",
  "还是",
  "那个",
  "那些",
  "那么",
  "需要",
  "看到",
  "经常",
  "对比",
  "东西",
  "下来",
  "上来",
  "出来",
  "进去",
  "过去",
  "起来",
  "里面",
  "外面",
  "前面",
  "后面",
  "只会",
  "只有",
  "只要",
  "只需",
  "有点",
  "确实",
  "轻松",
  "真的",
  "应该",
  "感觉",
  "觉得",
  "知道",
  "认为",
  "发现",
  "比如",
  "非常",
  "为什么",
]);
const TERM_COMMON_SPOKEN_PREFIX_RE = /^(这个|那个|这些|那些|这里|那里|这样|那样|这么|那么|然后|现在|其实|只是|就是|已经|还是|可能|可以|需要|应该|感觉|觉得|看到|看见|知道|发现|比较|非常|特别|真的|确实|只要|只有|只会|有点|一点|一下|一些|一个|一种|一段)/;
const TERM_COMMON_SPOKEN_SUFFIX_RE = /(的话|一下|一点|一些|一个|一种|一段|出来|起来|下来|上来|进去|过去|而已)$/;
const TERM_GENERIC_NOUNS = new Set([
  "方式",
  "地方",
  "时候",
  "情况",
  "问题",
  "部分",
  "方面",
  "位置",
  "过程",
  "原因",
  "结果",
  "程度",
  "状态",
  "东西",
  "这边",
  "那边",
]);
const TERM_LATIN_STOPWORDS = new Set(["ok", "okay", "yes", "no", "hi", "hello"]);
const TERM_ENTITY_CONTEXT_RE = /(品牌|型号|机型|版本|版型|系列|配置|参数|规格|联名|合作|正品|旗舰|国行|美版|日版|欧版|叫做|叫|来自|出品|发布|升级|适配|兼容|Pro|Max|Plus|Ultra|Mini|Air|SE)/i;
const TERM_DOMAIN_NOUN_RE = /(品牌|型号|机型|版本|版型|系列|配置|参数|规格|材质|工艺|镜头|画面|字幕|音频|视频|电池|接口|按钮|模式|设备|产品|主机|屏幕|外壳|包装|配件|工具|软件|系统|算法|模型|节点|工作流|数据|文件|素材|模板)$/;
const TERM_PRODUCT_SUFFIX_RE = /[\u4e00-\u9fff]{1,}(器|机|仪|版|款|屏|镜|头|盒|包|架|线|片|件|料|胶|油|膜|粉|膏|液|水|刀|钳|笔|灯|卡|盘|芯|模|盖|壳)$/;
const TERM_LOW_CONFIDENCE_SHAPE_RE = /([一-龥])\1{2,}|^[一-龥]{2}$|[A-Za-z0-9+#.-]*\d[A-Za-z0-9+#.-]*/;
const TERM_CHINESE_DIGIT_SEQUENCE_RE = /[零〇一二三四五六七八九两幺]{2,}/g;
const TERM_CHINESE_NUMBER_UNIT_RE = /[十百千万亿几]/;
const TERM_OBVIOUS_CHINESE_NUMBER_RE = /^[零〇一二三四五六七八九两幺十百千万亿几]+(?:个|只|条|块|次|年|岁|号|集|期|分|秒|米|元)?$/;
const TERM_VERB_HINTS = new Set([
  "上传",
  "保存",
  "启动",
  "开始",
  "结束",
  "生成",
  "合成",
  "渲染",
  "删除",
  "添加",
  "调整",
  "修改",
  "替换",
  "识别",
  "核对",
  "预览",
  "播放",
  "剪辑",
  "发布",
  "导出",
]);
const TERM_ADJECTIVE_HINTS = new Set([
  "明显",
  "实时",
  "完整",
  "简单",
  "复杂",
  "高频",
  "低频",
  "重要",
  "必要",
  "准确",
  "错误",
  "清晰",
  "稳定",
  "方便",
]);
const ROTATION_OPTIONS = [0, 90, 180, 270];
const ASPECT_RATIO_OPTIONS = [
  { value: "source", label: "跟随原片" },
  { value: "16:9", label: "横屏 16:9" },
  { value: "9:16", label: "竖屏 9:16" },
  { value: "1:1", label: "方形 1:1" },
  { value: "4:3", label: "经典 4:3" },
];
const RESOLUTION_MODE_OPTIONS = [
  { value: "source", label: "保留原分辨率" },
  { value: "specified", label: "指定分辨率" },
];
const RESOLUTION_PRESET_OPTIONS = [
  { value: "1080p", label: "1080p" },
  { value: "1440p", label: "2K" },
  { value: "2160p", label: "4K" },
];
const PREVIEW_AUTO_VOLUME_MIN_GAIN = 0.35;
const PREVIEW_AUTO_VOLUME_MAX_GAIN = 12;
const DEFAULT_SMART_CUT_FILLERS = "嗯,呃,额,呃呃,嗯嗯";
const SMART_CUT_RULE_STORAGE_KEY = "roughcut.manualEditor.smartCutRules.v3";
const DEFAULT_SMART_CUT_RULES: SmartCutRules = {
  fillerEnabled: true,
  repeatedEnabled: true,
  pauseEnabled: true,
  smartDeleteEnabled: true,
  pauseThresholdSec: 0.8,
  pauseBreathSec: 0.08,
  fillers: DEFAULT_SMART_CUT_FILLERS,
};

const SMART_CUT_AUDIO_SAFETY_SEC: Record<SmartCutRuleKind, number> = {
  filler: 0,
  repeated: 0,
  pause: 0.08,
  smart_delete: 0.08,
};
const SMART_CUT_PAUSE_CLUSTER_GAP_SEC = 0.8;
const SMART_DELETE_PROTECTED_TERM_PATTERN = /(?:^|[^A-Za-z0-9])(?:EDC\s*\d{1,4}|NITE\s*CORE|NITECORE|NOC|MT\s*\d{1,4}|S\d{2}\s*mini|OLIGHT|FENIX|ACEBEAM|NEXTORCH|NEXTOOL)(?=$|[^A-Za-z0-9])/i;

function normalizeSmartCutRules(value: Partial<SmartCutRules> | null | undefined): SmartCutRules {
  const pauseThresholdSec = Number(value?.pauseThresholdSec);
  const pauseBreathSec = Number(value?.pauseBreathSec);
  return {
    fillerEnabled: typeof value?.fillerEnabled === "boolean" ? value.fillerEnabled : DEFAULT_SMART_CUT_RULES.fillerEnabled,
    repeatedEnabled: typeof value?.repeatedEnabled === "boolean" ? value.repeatedEnabled : DEFAULT_SMART_CUT_RULES.repeatedEnabled,
    pauseEnabled: typeof value?.pauseEnabled === "boolean" ? value.pauseEnabled : DEFAULT_SMART_CUT_RULES.pauseEnabled,
    smartDeleteEnabled: typeof value?.smartDeleteEnabled === "boolean" ? value.smartDeleteEnabled : DEFAULT_SMART_CUT_RULES.smartDeleteEnabled,
    pauseThresholdSec: Number.isFinite(pauseThresholdSec) ? clamp(pauseThresholdSec, 0.1, 5) : DEFAULT_SMART_CUT_RULES.pauseThresholdSec,
    pauseBreathSec: Number.isFinite(pauseBreathSec) ? clamp(pauseBreathSec, 0, 1) : DEFAULT_SMART_CUT_RULES.pauseBreathSec,
    fillers: typeof value?.fillers === "string" && value.fillers.trim() ? value.fillers : DEFAULT_SMART_CUT_RULES.fillers,
  };
}

function loadSmartCutRules(): SmartCutRules {
  if (typeof window === "undefined") return DEFAULT_SMART_CUT_RULES;
  try {
    return normalizeSmartCutRules(JSON.parse(window.localStorage.getItem(SMART_CUT_RULE_STORAGE_KEY) || "null"));
  } catch {
    return DEFAULT_SMART_CUT_RULES;
  }
}

function saveSmartCutRules(rules: SmartCutRules) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SMART_CUT_RULE_STORAGE_KEY, JSON.stringify(normalizeSmartCutRules(rules)));
  } catch {
    // Global rule memory is an enhancement; private browsing/storage errors should not block editing.
  }
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M6 7l1 14h10l1-14" />
      <path d="M9 7V4h6v3" />
    </svg>
  );
}

function RestoreIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 8h8a6 6 0 1 1-5.2 9" />
      <path d="M5 8l4-4" />
      <path d="M5 8l4 4" />
    </svg>
  );
}

function ReplaceIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h11" />
      <path d="M12 4l3 3-3 3" />
      <path d="M20 17H9" />
      <path d="M12 14l-3 3 3 3" />
    </svg>
  );
}

function ReplaceAllIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 6h10" />
      <path d="M11 3l3 3-3 3" />
      <path d="M7 12h10" />
      <path d="M14 9l3 3-3 3" />
      <path d="M10 18h10" />
      <path d="M17 15l3 3-3 3" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

function regionIdForIndex(index: number) {
  return `keep-${index}`;
}

function applyConservativeAsrWordCorrections(text: string) {
  return text.replace(/(^|[\s，,。.!！?？、；;：:])612(?=一[把个支只台颗])/g, "$1另外");
}

function subtitleText(subtitle: JobManualEditSubtitle) {
  return applyConservativeAsrWordCorrections(String(subtitle.text_final ?? subtitle.text_norm ?? subtitle.text_raw ?? "").trim());
}

export function subtitleAutoCorrectionSummary(subtitle: JobManualEditSubtitle) {
  const raw = String(subtitle.text_raw ?? "").trim();
  const norm = String(subtitle.text_norm ?? "").trim();
  const final = String(subtitle.text_final ?? "").trim();
  const current = subtitleText(subtitle);
  const baseline = norm || raw;
  const ruleChanged = Boolean(raw && norm && raw !== norm);
  const llmChanged = Boolean(final && baseline && final !== baseline);
  const source = ruleChanged ? raw : baseline;
  if (!current || !source || current === source) return null;
  return {
    label: llmChanged ? (ruleChanged ? "规则清理 + LLM精修" : "LLM精修") : "规则清理",
    source,
    current,
  };
}

function subtitleTranscriptSourceText(subtitle: JobManualEditSubtitle) {
  const suppressedReason = String(subtitle.display_suppressed_reason || "").trim();
  if (suppressedReason && suppressedReason !== "standalone_filler") return "";
  const finalText = subtitleText(subtitle);
  const normText = String(subtitle.text_norm || "").trim();
  const rawText = String(subtitle.text_raw || "").trim();
  const transcriptText = String(subtitle.transcript_text || "").trim();
  const baselineText = finalText || normText || rawText || transcriptText;
  if (transcriptText) {
    return applyConservativeAsrWordCorrections(preferDenoisedAsrTranscriptText(baselineText, transcriptText));
  }
  if (rawText && shouldRevealRawAsrTranscriptText(baselineText, rawText)) return applyConservativeAsrWordCorrections(rawText);
  return applyConservativeAsrWordCorrections(baselineText);
}

function compactTranscriptText(value: string) {
  return value.replace(/[\s，,。.!！?？、；;：:“”"'‘’（）()[\]【】]+/g, "");
}

function transcriptTextIsSubsequence(needle: string, haystack: string) {
  if (!needle) return true;
  if (!haystack) return false;
  const needleChars = Array.from(needle);
  const haystackChars = Array.from(haystack);
  let cursor = 0;
  for (const char of haystackChars) {
    if (char === needleChars[cursor]) cursor += 1;
    if (cursor >= needleChars.length) return true;
  }
  return false;
}

function transcriptTextCommonSubsequenceRatio(left: string, right: string) {
  const leftChars = Array.from(left);
  const rightChars = Array.from(right);
  if (!leftChars.length || !rightChars.length) return 0;
  const previous = Array(rightChars.length + 1).fill(0);
  for (let leftIndex = 0; leftIndex < leftChars.length; leftIndex += 1) {
    let diagonal = 0;
    for (let rightIndex = 0; rightIndex < rightChars.length; rightIndex += 1) {
      const saved = previous[rightIndex + 1];
      previous[rightIndex + 1] = leftChars[leftIndex] === rightChars[rightIndex]
        ? diagonal + 1
        : Math.max(previous[rightIndex + 1], previous[rightIndex]);
      diagonal = saved;
    }
  }
  const commonLength = previous[rightChars.length];
  return commonLength / Math.max(leftChars.length, rightChars.length);
}

const TRANSCRIPT_REVEALABLE_FILLER_CHARS = new Set(Array.from("啊呃额嗯哎唉诶欸吧呀嘛呢哦喔哈"));

function normalizeLatinAsrDuplicateNoise(text: string) {
  return text
    .replace(/\bN+O+C+(?:O+C+)+\b/gi, (match) => (match === match.toUpperCase() ? "NOC" : "NOC"))
    .replace(/\bE+D+E+D+C+\b/gi, "EDC");
}

function normalizeCjkAdjacentDuplicateNoise(text: string) {
  const duplicatePairCount = Array.from(text.matchAll(/([\u4e00-\u9fff])\1/g)).filter((match) => (
    !TRANSCRIPT_REVEALABLE_FILLER_CHARS.has(match[1] || "")
  )).length;
  if (duplicatePairCount < 3) return text;
  return text.replace(/([\u4e00-\u9fff])\1+/g, (match, char: string) => (
    TRANSCRIPT_REVEALABLE_FILLER_CHARS.has(char) ? match : char
  ));
}

function denoiseAsrTranscriptText(text: string) {
  const normalized = normalizeLatinAsrDuplicateNoise(String(text || "").trim())
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "")
    .replace(/([，。！？、：；,.!?])\1+/g, "$1");
  return normalizeCjkAdjacentDuplicateNoise(normalized).replace(/\s{2,}/g, " ").trim();
}

function preferDenoisedAsrTranscriptText(baselineText: string, asrText: string) {
  const baseline = baselineText.trim();
  const asr = denoiseAsrTranscriptText(asrText);
  if (!asr) return baseline;
  if (!baseline) return asr;
  const baselineKey = compactTranscriptText(baseline);
  const asrKey = compactTranscriptText(asr);
  if (!asrKey) return baseline;
  if (!baselineKey) return asr;
  if (asrKey === baselineKey) return asr;
  if (transcriptTextIsSubsequence(baselineKey, asrKey)) return asr;
  const commonRatio = transcriptTextCommonSubsequenceRatio(baselineKey, asrKey);
  const lengthRatio = Math.max(baselineKey.length, asrKey.length) / Math.max(1, Math.min(baselineKey.length, asrKey.length));
  return commonRatio >= 0.72 && lengthRatio <= 2.2 ? asr : baseline;
}

function preferSourceTranscriptOverDraftText(draftText: string, sourceText: string) {
  const draft = draftText.trim();
  const source = denoiseAsrTranscriptText(sourceText);
  if (!source) return draft;
  if (!draft) return source;
  const draftKey = compactTranscriptText(draft);
  const sourceKey = compactTranscriptText(source);
  if (!sourceKey) return draft;
  if (!draftKey || draftKey === sourceKey) return source;
  if (transcriptTextIsSubsequence(draftKey, sourceKey)) return source;
  if (/[A-Za-z0-9]/.test(`${draftKey}${sourceKey}`)) return draft;
  const commonRatio = transcriptTextCommonSubsequenceRatio(draftKey, sourceKey);
  const lengthRatio = Math.max(draftKey.length, sourceKey.length) / Math.max(1, Math.min(draftKey.length, sourceKey.length));
  if (sourceKey.length > draftKey.length + 1 && commonRatio >= 0.72 && lengthRatio <= 2.2) return source;
  return commonRatio >= 0.86 && lengthRatio <= 1.25 ? source : draft;
}

function transcriptSubsequenceExtraText(needle: string, haystack: string) {
  if (!needle) return haystack;
  const needleChars = Array.from(needle);
  let cursor = 0;
  const extras: string[] = [];
  for (const char of Array.from(haystack)) {
    if (cursor < needleChars.length && char === needleChars[cursor]) {
      cursor += 1;
    } else {
      extras.push(char);
    }
  }
  return cursor >= needleChars.length ? extras.join("") : "";
}

function shouldRevealRawAsrTranscriptText(baselineText: string, rawText: string) {
  const baselineKey = compactTranscriptText(baselineText);
  const rawKey = compactTranscriptText(rawText);
  if (!rawKey || rawKey === baselineKey) return false;
  if (!baselineKey) return true;
  if (!transcriptTextIsSubsequence(baselineKey, rawKey)) return false;
  const extraChars = rawKey.length - baselineKey.length;
  if (extraChars <= 0) return false;
  const extraText = transcriptSubsequenceExtraText(baselineKey, rawKey);
  if (!extraText) return false;
  const fillerExtraCount = Array.from(extraText).filter((char) => TRANSCRIPT_REVEALABLE_FILLER_CHARS.has(char)).length;
  return fillerExtraCount / Math.max(1, Array.from(extraText).length) >= 0.6
    && (extraChars <= 12 || baselineKey.length / Math.max(1, rawKey.length) >= 0.72);
}

function shouldPreferSupersetTranscriptText(candidateText: string, baseText: string) {
  const candidateKey = compactTranscriptText(candidateText);
  const baseKey = compactTranscriptText(baseText);
  if (!candidateKey) return false;
  if (!baseKey) return true;
  if (candidateKey.length <= baseKey.length) return false;
  if (!transcriptTextIsSubsequence(baseKey, candidateKey)) return false;
  const extraChars = candidateKey.length - baseKey.length;
  const maxExtraChars = Math.max(12, Math.floor(baseKey.length * 0.35));
  return extraChars <= maxExtraChars;
}

function shouldPreferSourceTranscriptText(sourceText: string, projectedText: string | undefined) {
  const sourceKey = compactTranscriptText(sourceText);
  const projectedKey = compactTranscriptText(projectedText || "");
  if (!sourceKey) return false;
  if (!projectedKey) return true;
  if (sourceKey.length > projectedKey.length && sourceKey.includes(projectedKey)) return true;
  if (shouldPreferSupersetTranscriptText(sourceText, projectedText || "")) return true;
  const lengthRatio = Math.max(sourceKey.length, projectedKey.length) / Math.max(1, Math.min(sourceKey.length, projectedKey.length));
  return transcriptTextCommonSubsequenceRatio(sourceKey, projectedKey) < 0.32 && lengthRatio >= 1.8;
}

function subtitleSourceIndex(subtitle: Pick<JobManualEditSubtitle, "index" | "source_index">) {
  return Number.isFinite(Number(subtitle.source_index)) ? Number(subtitle.source_index) : Number(subtitle.index);
}

function subtitleSourceIndexes(subtitle: JobManualEditSubtitle, sourceIndex = subtitleSourceIndex(subtitle)) {
  const indexes = Array.isArray(subtitle.source_indexes)
    ? subtitle.source_indexes
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value))
    : [];
  if (!indexes.includes(sourceIndex)) indexes.unshift(sourceIndex);
  return indexes.length ? indexes : [sourceIndex];
}

function withUniqueRemappedSubtitleIndexes(subtitles: JobManualEditSubtitle[]) {
  const normalizedIndexes = subtitles.map((subtitle, position) => {
    const index = Number(subtitle.index);
    return Number.isFinite(index) ? index : position;
  });
  const counts = normalizedIndexes.reduce((result, index) => {
    result.set(index, (result.get(index) ?? 0) + 1);
    return result;
  }, new Map<number, number>());
  const occupiedIndexes = new Set(normalizedIndexes);
  const usedIndexes = new Set<number>();
  let nextIndex = normalizedIndexes.length ? Math.max(...normalizedIndexes) + 1 : 0;
  return subtitles.map((subtitle, position) => {
    const originalIndex = normalizedIndexes[position] ?? position;
    const duplicate = (counts.get(originalIndex) ?? 0) > 1;
    const sourceIndex = subtitleSourceIndex({ index: originalIndex, source_index: subtitle.source_index });
    const subtitleWithSource = duplicate
      ? {
          ...subtitle,
          source_index: sourceIndex,
          source_indexes: subtitleSourceIndexes(subtitle, sourceIndex),
        }
      : subtitle;
    if (!usedIndexes.has(originalIndex)) {
      usedIndexes.add(originalIndex);
      return { ...subtitleWithSource, index: originalIndex };
    }
    while (occupiedIndexes.has(nextIndex) || usedIndexes.has(nextIndex)) nextIndex += 1;
    const uniqueIndex = nextIndex;
    usedIndexes.add(uniqueIndex);
    nextIndex += 1;
    return { ...subtitleWithSource, index: uniqueIndex };
  });
}

function formatSeconds(value: number) {
  const total = Math.max(0, value || 0);
  const minutes = Math.floor(total / 60);
  const seconds = total - minutes * 60;
  return `${minutes}:${seconds.toFixed(2).padStart(5, "0")}`;
}

function previewAssetStageLabel(stage?: string | null) {
  switch (stage) {
    case "queued":
      return "已排队";
    case "proxy_video":
      return "生成视频代理";
    case "proxy_webm":
      return "生成备用视频代理";
    case "proxy_audio":
      return "生成音频代理";
    case "waveform_peaks":
      return "计算波形峰值";
    case "loudness_analysis":
      return "分析响度";
    case "thumbnails":
      return "抽取时间轴缩略图";
    case "cached":
      return "命中缓存";
    case "ready":
      return "生成完成";
    case "failed":
      return "生成失败";
    default:
      return "未开始";
  }
}

function previewAssetStatusLabel(previewAssets: JobManualEditPreviewAssets) {
  if (previewAssets.ready) return previewAssets.cached ? "已复用预览资产" : "已生成预览资产";
  if (previewAssets.video_url || previewAssets.video_ready) return "已启用视频代理";
  if (previewAssets.status === "failed" || previewAssets.error) return "预览资产生成失败";
  if (previewAssets.warming || previewAssets.status === "warming") return "预览资产生成中";
  return "预览资产待生成";
}

function normalizePreviewVideoSources(previewAssets: JobManualEditPreviewAssets | undefined, sourceUrl: string | null | undefined) {
  const proxySources = (previewAssets?.video_sources || [])
    .map((source) => ({ url: String(source.url || "").trim(), type: source.type || undefined }))
    .filter((source) => source.url);
  if (proxySources.length) {
    return [...proxySources].sort((left, right) => {
      const leftWebm = left.type?.includes("webm") || left.url.endsWith(".webm");
      const rightWebm = right.type?.includes("webm") || right.url.endsWith(".webm");
      return Number(leftWebm) - Number(rightWebm);
    });
  }
  if (previewAssets?.video_url) {
    const sources = [];
    sources.push({ url: previewAssets.video_url, type: 'video/mp4; codecs="avc1.42E01F, mp4a.40.2"' });
    if (previewAssets.video_url.endsWith("/proxy.mp4")) {
      sources.push({
        url: previewAssets.video_url.replace(/\/proxy\.mp4$/, "/proxy.webm"),
        type: 'video/webm; codecs="vp8, opus"',
      });
    }
    return sources;
  }
  const assetStatus = String(previewAssets?.status || "").trim();
  const mayUseOriginalFallback = Boolean(previewAssets && (previewAssets.error || assetStatus === "failed"));
  return sourceUrl && mayUseOriginalFallback ? [{ url: sourceUrl, type: undefined }] : [];
}

function previewUnavailableMessage(
  previewAssets: JobManualEditPreviewAssets | undefined,
  sourceUrl: string | null | undefined,
) {
  if (!sourceUrl) {
    return "当前机器拿不到原片本地路径，暂时不能内嵌预览，但仍可调整并保存时间线。";
  }
  if (!previewAssets) {
    return "正在启动轻量视频代理，避免直接加载完整原片。";
  }
  if (previewAssets.error || previewAssets.status === "failed") {
    return "视频代理生成失败，已允许使用完整原片兜底；如果仍然加载缓慢，请重新生成预览资产或检查 ffmpeg。";
  }
  if (previewAssets.warming || previewAssets.status === "warming" || previewAssets.status === "missing") {
    return "正在生成轻量视频代理，完成后会自动启用预览。";
  }
  return "正在等待视频代理文件可用。";
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function clampFloatingPreviewPosition(x: number, y: number, width: number, height: number) {
  const maxX = Math.max(FLOATING_PREVIEW_MARGIN, window.innerWidth - width - FLOATING_PREVIEW_MARGIN);
  const maxY = Math.max(FLOATING_PREVIEW_MARGIN, window.innerHeight - height - FLOATING_PREVIEW_MARGIN);
  return {
    x: clamp(x, FLOATING_PREVIEW_MARGIN, maxX),
    y: clamp(y, FLOATING_PREVIEW_MARGIN, maxY),
  };
}

function isTextEntryTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}

function buildOutputRanges(keepSegments: KeepSegment[]) {
  const ordered = [...keepSegments].sort((left, right) => left.start - right.start);
  let outputCursor = 0;
  const ranges = ordered.map((segment) => {
    const duration = Math.max(0, segment.end - segment.start);
    const range = {
      sourceStart: segment.start,
      sourceEnd: segment.end,
      outputStart: outputCursor,
      outputEnd: outputCursor + duration,
    };
    outputCursor += duration;
    return range;
  });
  return { ranges, totalDuration: outputCursor };
}

function sourceRangeToOutputRanges(sourceStart: number, sourceEnd: number, ranges: OutputRange[]) {
  const mappedRanges: MappedSubtitleRange[] = [];
  const start = Math.min(sourceStart, sourceEnd);
  const end = Math.max(sourceStart, sourceEnd);
  for (const range of ranges) {
    const overlapStart = Math.max(start, range.sourceStart);
    const overlapEnd = Math.min(end, range.sourceEnd);
    const overlapDuration = overlapEnd - overlapStart;
    if (overlapDuration <= 0.05) continue;
    const outputStart = range.outputStart + (overlapStart - range.sourceStart);
    const outputEnd = range.outputStart + (overlapEnd - range.sourceStart);
    if (outputEnd <= outputStart + 0.05) continue;
    mappedRanges.push({
      outputStart,
      outputEnd,
      sourceStart: overlapStart,
      sourceEnd: overlapEnd,
    });
  }
  return mappedRanges;
}

export function remapSubtitles(subtitles: JobManualEditSubtitle[], keepSegments: KeepSegment[]) {
  const { ranges, totalDuration } = buildOutputRanges(keepSegments);
  const remapped = subtitles
    .flatMap((subtitle, index) => {
      const subtitleStart = Number(subtitle.start_time || 0);
      const subtitleEnd = Number(subtitle.end_time || 0);
      const mappedRanges = sourceRangeToOutputRanges(subtitleStart, subtitleEnd, ranges);
      if (!mappedRanges.length || subtitleEnd <= subtitleStart + 0.001) return [];
      const fragmentTexts = splitRemappedSubtitleText(subtitle, mappedRanges, subtitleStart, subtitleEnd);
      const sourceIndex = subtitleSourceIndex({ index: subtitle.index ?? index, source_index: subtitle.source_index });
      const sourceIndexes = subtitleSourceIndexes(subtitle, sourceIndex);
      return mappedRanges.flatMap((mappedRange, fragmentIndex) => {
        const fragmentText = fragmentTexts[fragmentIndex]?.trim() || "";
        if (!fragmentText) return [];
        const remappedSubtitle = withRemappedSubtitleText({
          ...subtitle,
          index: subtitle.index ?? index,
          source_index: sourceIndex,
          source_indexes: sourceIndexes,
          ...(mappedRanges.length > 1
            ? {
                source_fragment_index: fragmentIndex,
                source_fragment_count: mappedRanges.length,
                source_text_full: subtitleText(subtitle),
                source_overlap_start_time: mappedRange.sourceStart,
                source_overlap_end_time: mappedRange.sourceEnd,
              }
            : {}),
          start_time: Number(mappedRange.outputStart.toFixed(3)),
          end_time: Number(mappedRange.outputEnd.toFixed(3)),
        }, fragmentText);
        return [remappedSubtitle];
      });
    })
    .sort((left, right) => left.start_time - right.start_time || left.index - right.index);

  return { remapped: withUniqueRemappedSubtitleIndexes(remapped), ranges, totalDuration };
}

export function remapProjectedSubtitlesFromBaseTimeline(
  subtitles: JobManualEditSubtitle[],
  baseKeepSegments: KeepSegment[],
  nextKeepSegments: KeepSegment[],
) {
  const baseRanges = buildOutputRanges(baseKeepSegments).ranges;
  const { ranges, totalDuration } = buildOutputRanges(nextKeepSegments);
  const remapped = sortedSubtitles(subtitles)
    .flatMap((subtitle, index) => {
      const outputStart = Number(subtitle.start_time || 0);
      const outputEnd = Number(subtitle.end_time || 0);
      if (outputEnd <= outputStart + 0.001) return [];
      const sourceRanges = outputRangeToSourceRanges(outputStart, outputEnd, baseRanges);
      if (!sourceRanges.length) return [];
      const mappedRanges = sourceRanges
        .flatMap((range) => sourceRangeToOutputRanges(range.start, range.end, ranges))
        .sort((left, right) => left.outputStart - right.outputStart || left.outputEnd - right.outputEnd);
      if (!mappedRanges.length) return [];
      const textRanges = mappedRanges.map((range) => ({
        ...range,
        sourceStart: sourceTimeToOutputTime(range.sourceStart, baseRanges),
        sourceEnd: sourceTimeToOutputTime(range.sourceEnd, baseRanges),
      }));
      const fragmentTexts = splitRemappedSubtitleText(subtitle, textRanges, outputStart, outputEnd);
      return mappedRanges.flatMap((mappedRange, fragmentIndex) => {
        const fragmentText = fragmentTexts[fragmentIndex]?.trim() || "";
        if (!fragmentText) return [];
        return [withRemappedSubtitleText({
          ...subtitle,
          index: subtitle.index ?? index,
          start_time: Number(mappedRange.outputStart.toFixed(3)),
          end_time: Number(mappedRange.outputEnd.toFixed(3)),
        }, fragmentText)];
      });
    })
    .sort((left, right) => left.start_time - right.start_time || left.index - right.index);

  return { remapped: withUniqueRemappedSubtitleIndexes(remapped), ranges, totalDuration };
}

function withRemappedSubtitleText(
  subtitle: JobManualEditSubtitle,
  text: string,
  options: { syncTranscriptText?: boolean } = {},
) {
  return {
    ...subtitle,
    text_raw: subtitle.text_raw == null ? subtitle.text_raw : text,
    text_norm: subtitle.text_norm == null ? subtitle.text_norm : text,
    text_final: text,
    ...(options.syncTranscriptText && subtitle.transcript_text != null ? { transcript_text: text } : {}),
  };
}

function splitSubtitleDisplayText(text: string, maxChars = SUBTITLE_DISPLAY_MAX_CHARS) {
  const normalized = String(text || "").trim().replace(/\s{2,}/g, " ");
  if (!normalized) return [];
  const words = normalized.split(" ");
  if (words.length <= 1) {
    const compact = normalized.replace(/\s/g, "");
    if (Array.from(compact).length <= maxChars) return [normalized];
    const chars = Array.from(compact);
    const pieces: string[] = [];
    for (let index = 0; index < chars.length; index += maxChars) {
      pieces.push(chars.slice(index, index + maxChars).join(""));
    }
    return pieces;
  }

  const pieces: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (Array.from(candidate.replace(/\s/g, "")).length <= maxChars || !current) {
      current = candidate;
      continue;
    }
    pieces.push(current);
    current = word;
  }
  if (current) pieces.push(current);
  return pieces;
}

function timedCharCount(value: string) {
  return Array.from(String(value || "")).filter(isTranscriptTimedChar).length;
}

function compactCharCount(value: string) {
  return Array.from(String(value || "").replace(/\s/g, "")).length;
}

function splitAlignmentTokensForDisplayPieces(
  tokens: JobManualEditSubtitle["alignment_tokens"],
  pieces: string[],
) {
  const sourceTokens = [...(tokens || [])];
  if (!sourceTokens.length || pieces.length <= 1) return pieces.map(() => []);
  const totalPieceCompactChars = pieces.reduce((total, piece) => total + compactCharCount(piece), 0);
  const totalTokenCompactChars = sourceTokens.reduce((total, token) => total + compactCharCount(token.text), 0);
  const useCompactCounts = totalTokenCompactChars >= totalPieceCompactChars * 0.8;
  const countText = useCompactCounts ? compactCharCount : timedCharCount;
  const slices: NonNullable<JobManualEditSubtitle["alignment_tokens"]>[] = [];
  let cursor = 0;
  pieces.forEach((piece, index) => {
    if (index === pieces.length - 1) {
      slices.push(sourceTokens.slice(cursor));
      cursor = sourceTokens.length;
      return;
    }
    const targetCount = countText(piece);
    const slice: NonNullable<JobManualEditSubtitle["alignment_tokens"]> = [];
    let consumed = 0;
    while (cursor < sourceTokens.length && consumed < targetCount) {
      const token = sourceTokens[cursor];
      slice.push(token);
      consumed += Math.max(1, countText(token.text));
      cursor += 1;
    }
    slices.push(slice);
  });
  return slices;
}

function splitWordsForDisplayPieces(words: JobManualEditWord[] | undefined, pieces: string[]) {
  const sourceWords = [...(words || [])];
  if (!sourceWords.length || pieces.length <= 1) return pieces.map(() => []);
  const slices: JobManualEditWord[][] = [];
  let cursor = 0;
  let consumedChars = 0;
  pieces.forEach((piece, index) => {
    if (index === pieces.length - 1) {
      slices.push(sourceWords.slice(cursor));
      cursor = sourceWords.length;
      return;
    }
    const targetChars = timedCharCount(piece);
    const slice: JobManualEditWord[] = [];
    while (cursor < sourceWords.length && consumedChars < targetChars) {
      const word = sourceWords[cursor];
      slice.push(word);
      consumedChars += timedCharCount(word.word);
      cursor += 1;
    }
    consumedChars = Math.max(0, consumedChars - targetChars);
    slices.push(slice);
  });
  return slices;
}

function splitLongSubtitleDisplayRows(subtitles: JobManualEditSubtitle[]) {
  const splitRows = sortedSubtitles(subtitles).flatMap((subtitle) => {
    const text = subtitleText(subtitle).trim();
    const duration = Math.max(0, subtitle.end_time - subtitle.start_time);
    const compactLength = Array.from(text.replace(/\s/g, "")).length;
    if (!text || (duration <= SUBTITLE_DISPLAY_MAX_DURATION_SEC && compactLength <= SUBTITLE_DISPLAY_MAX_CHARS)) {
      return [subtitle];
    }

    const targetChars = Math.min(
      SUBTITLE_DISPLAY_MAX_CHARS,
      Math.max(12, Math.floor(SUBTITLE_DISPLAY_MAX_CHARS * SUBTITLE_DISPLAY_MAX_DURATION_SEC / Math.max(duration, 0.001))),
    );
    const pieces = splitSubtitleDisplayText(text, targetChars);
    if (pieces.length <= 1) return [subtitle];

    const weights = pieces.map((piece) => Math.max(1, Array.from(piece.replace(/\s/g, "")).length));
    const totalWeight = weights.reduce((total, weight) => total + weight, 0) || pieces.length;
    const alignmentTokenSlices = splitAlignmentTokensForDisplayPieces(subtitle.alignment_tokens, pieces);
    const wordSlices = splitWordsForDisplayPieces(subtitle.words, pieces);
    let cursor = subtitle.start_time;
    return pieces.map((piece, index) => {
      const end = index === pieces.length - 1
        ? subtitle.end_time
        : Math.min(subtitle.end_time, cursor + duration * (weights[index] / totalWeight));
      const alignmentTokens = alignmentTokenSlices[index] || [];
      const words = wordSlices[index] || [];
      const row = withRemappedSubtitleText({
        ...subtitle,
        source_fragment_index: index,
        source_fragment_count: pieces.length,
        source_text_full: text,
        source_overlap_start_time: subtitle.source_overlap_start_time ?? cursor,
        source_overlap_end_time: subtitle.source_overlap_end_time ?? end,
        words: words.length ? words : undefined,
        alignment_tokens: alignmentTokens.length ? alignmentTokens : undefined,
        alignment_diagnostics: alignmentTokens.length ? subtitle.alignment_diagnostics : undefined,
        start_time: Number(cursor.toFixed(3)),
        end_time: Number(Math.max(cursor + MIN_SUBTITLE_DURATION_SEC, end).toFixed(3)),
      }, piece, { syncTranscriptText: true });
      cursor = end;
      return row;
    });
  });
  return withUniqueRemappedSubtitleIndexes(splitRows);
}

const SUBTITLE_BOUNDARY_OVERLAP_MAX_CHARS = 14;
const SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS = 2;
const SUBTITLE_BOUNDARY_OVERLAP_MAX_GAP_SEC = 1.2;
const SUBTITLE_BOUNDARY_FUZZY_OVERLAP_MAX_CHARS = 8;
const SUBTITLE_BOUNDARY_MIN_TIME_OVERLAP_SEC = 0.04;

function meaningfulOverlapText(value: string) {
  return value.replace(/[\s，,。.!！?？、；;：:“”"'‘’（）()[\]【】]+/g, "");
}

function subtitleTimeOverlapSeconds(previous: JobManualEditSubtitle, current: JobManualEditSubtitle) {
  return Math.max(0, Math.min(previous.end_time, current.end_time) - Math.max(previous.start_time, current.start_time));
}

function commonSuffixLength(left: string, right: string) {
  const leftChars = Array.from(left);
  const rightChars = Array.from(right);
  let count = 0;
  while (
    count < leftChars.length
    && count < rightChars.length
    && leftChars[leftChars.length - 1 - count] === rightChars[rightChars.length - 1 - count]
  ) {
    count += 1;
  }
  return count;
}

function levenshteinDistance(left: string, right: string) {
  const leftChars = Array.from(left);
  const rightChars = Array.from(right);
  const previous = Array.from({ length: rightChars.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= leftChars.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= rightChars.length; rightIndex += 1) {
      const substitutionCost = leftChars[leftIndex - 1] === rightChars[rightIndex - 1] ? 0 : 1;
      current[rightIndex] = Math.min(
        previous[rightIndex] + 1,
        current[rightIndex - 1] + 1,
        previous[rightIndex - 1] + substitutionCost,
      );
    }
    previous.splice(0, previous.length, ...current);
  }
  return previous[rightChars.length] ?? 0;
}

function findSubtitleBoundaryOverlapLength(previousText: string, currentText: string) {
  const previousChars = Array.from(previousText.trim());
  const currentChars = Array.from(currentText.trim());
  const maxLength = Math.min(SUBTITLE_BOUNDARY_OVERLAP_MAX_CHARS, previousChars.length - 1, currentChars.length);
  for (let length = maxLength; length >= SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS; length -= 1) {
    const previousSuffix = previousChars.slice(-length).join("");
    const currentPrefix = currentChars.slice(0, length).join("");
    if (previousSuffix === currentPrefix && meaningfulOverlapText(previousSuffix).length >= SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS) {
      return length;
    }
  }
  return 0;
}

function findSubtitleBoundaryFuzzyOverlapLength(previousText: string, currentText: string) {
  const previousChars = Array.from(previousText.trim());
  const currentChars = Array.from(currentText.trim());
  const maxPreviousLength = Math.min(SUBTITLE_BOUNDARY_FUZZY_OVERLAP_MAX_CHARS, previousChars.length - 1);
  const maxCurrentLength = Math.min(SUBTITLE_BOUNDARY_FUZZY_OVERLAP_MAX_CHARS, currentChars.length);
  let bestLength = 0;
  for (let previousLength = maxPreviousLength; previousLength >= SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS; previousLength -= 1) {
    const previousSuffix = previousChars.slice(-previousLength).join("");
    const meaningfulPrevious = meaningfulOverlapText(previousSuffix);
    if (meaningfulPrevious.length < SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS) continue;
    for (let currentLength = maxCurrentLength; currentLength >= SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS; currentLength -= 1) {
      const currentPrefix = currentChars.slice(0, currentLength).join("");
      const meaningfulCurrent = meaningfulOverlapText(currentPrefix);
      if (meaningfulCurrent.length < SUBTITLE_BOUNDARY_OVERLAP_MIN_CHARS) continue;
      const maxLength = Math.max(meaningfulPrevious.length, meaningfulCurrent.length);
      const minLength = Math.min(meaningfulPrevious.length, meaningfulCurrent.length);
      const editDistance = levenshteinDistance(meaningfulPrevious, meaningfulCurrent);
      const sharedTailLength = commonSuffixLength(meaningfulPrevious, meaningfulCurrent);
      const nearSameText = editDistance <= Math.max(1, Math.floor(maxLength * 0.34));
      const sameTailStutter = Math.abs(meaningfulPrevious.length - meaningfulCurrent.length) <= 1
        && sharedTailLength >= 2
        && sharedTailLength / Math.max(1, minLength) >= 0.65;
      if (nearSameText || sameTailStutter) {
        bestLength = Math.max(bestLength, previousLength);
        break;
      }
    }
  }
  return bestLength;
}

function trimSubtitleEndByChars(subtitle: JobManualEditSubtitle, trimCharCount: number) {
  const text = subtitleText(subtitle);
  const chars = Array.from(text);
  if (trimCharCount <= 0 || trimCharCount >= chars.length) return subtitle;
  const nextText = chars.slice(0, chars.length - trimCharCount).join("").trimEnd();
  if (!nextText) return subtitle;
  const duration = Math.max(MIN_SUBTITLE_DURATION_SEC, subtitle.end_time - subtitle.start_time);
  const nextRatio = Array.from(nextText).length / Math.max(1, chars.length);
  const nextEnd = clamp(
    subtitle.start_time + duration * nextRatio,
    subtitle.start_time + MIN_SUBTITLE_DURATION_SEC,
    subtitle.end_time,
  );
  return withRemappedSubtitleText({
    ...subtitle,
    end_time: Number(nextEnd.toFixed(3)),
  }, nextText);
}

export function normalizeAdjacentSubtitleTextOverlaps(subtitles: JobManualEditSubtitle[]) {
  const normalized = sortedSubtitles(subtitles).map((subtitle) => ({ ...subtitle }));
  for (let index = 1; index < normalized.length; index += 1) {
    const previous = normalized[index - 1];
    const current = normalized[index];
    const gap = current.start_time - previous.end_time;
    const timeOverlap = subtitleTimeOverlapSeconds(previous, current);
    if (gap > SUBTITLE_BOUNDARY_OVERLAP_MAX_GAP_SEC) continue;
    const shouldResolveBoundaryDuplicate = timeOverlap >= SUBTITLE_BOUNDARY_MIN_TIME_OVERLAP_SEC || Math.abs(gap) <= 0.08;
    if (!shouldResolveBoundaryDuplicate) continue;
    const exactOverlapLength = findSubtitleBoundaryOverlapLength(subtitleText(previous), subtitleText(current));
    const fuzzyOverlapLength = exactOverlapLength > 0 || timeOverlap < SUBTITLE_BOUNDARY_MIN_TIME_OVERLAP_SEC
      ? 0
      : findSubtitleBoundaryFuzzyOverlapLength(subtitleText(previous), subtitleText(current));
    const overlapLength = Math.max(exactOverlapLength, fuzzyOverlapLength);
    if (overlapLength <= 0) continue;
    normalized[index - 1] = trimSubtitleEndByChars(previous, overlapLength);
  }
  return normalized;
}

type RemapTimedTextUnit = {
  text: string;
  start: number;
  end: number;
};

type RemapTimedTextUnitWithSpan = RemapTimedTextUnit & {
  textStart: number;
  textEnd: number;
};

function timedUnitsFromSubtitleForRemap(subtitle: JobManualEditSubtitle): RemapTimedTextUnit[] {
  const words = (subtitle.words || [])
    .map((word) => ({
      text: String(word.word || ""),
      start: Number(word.start),
      end: Number(word.end),
    }))
    .filter((word) => word.text && Number.isFinite(word.start) && Number.isFinite(word.end) && word.end > word.start);
  if (words.length) return words;
  return (subtitle.alignment_tokens || [])
    .map((token) => ({
      text: String(token.text || ""),
      start: Number(token.start),
      end: Number(token.end),
    }))
    .filter((token) => token.text && Number.isFinite(token.start) && Number.isFinite(token.end) && token.end > token.start);
}

function timedUnitsWithTextSpansForRemap(text: string, subtitle: JobManualEditSubtitle): RemapTimedTextUnitWithSpan[] {
  const units = timedUnitsFromSubtitleForRemap(subtitle);
  if (!units.length) return [];
  const chars = Array.from(text);
  const textTimingChars = chars
    .map((char, charIndex) => ({ char, charIndex, key: normalizeTranscriptTimingChar(char) }))
    .filter((item) => isTranscriptTimedChar(item.char));
  const unitTimingChars = units.flatMap((unit, unitIndex) => (
    Array.from(unit.text)
      .filter(isTranscriptTimedChar)
      .map((char) => ({ unitIndex, key: normalizeTranscriptTimingChar(char) }))
  ));
  if (!textTimingChars.length || !unitTimingChars.length) return [];
  const pairs = transcriptTimingIndexPairs(
    textTimingChars.map((item) => item.key),
    unitTimingChars.map((item) => item.key),
  );
  if (pairs.length / Math.max(1, textTimingChars.length) < 0.6) return [];
  const matchedTextIndexesByUnit = new Map<number, number[]>();
  pairs.forEach(([textTimingIndex, unitTimingIndex]) => {
    const unitIndex = unitTimingChars[unitTimingIndex]?.unitIndex;
    const textIndex = textTimingChars[textTimingIndex]?.charIndex;
    if (unitIndex == null || textIndex == null) return;
    const indexes = matchedTextIndexesByUnit.get(unitIndex) || [];
    indexes.push(textIndex);
    matchedTextIndexesByUnit.set(unitIndex, indexes);
  });
  return units.flatMap((unit, unitIndex) => {
    const indexes = matchedTextIndexesByUnit.get(unitIndex);
    if (!indexes?.length) return [];
    return [{
      ...unit,
      textStart: Math.min(...indexes),
      textEnd: Math.max(...indexes) + 1,
    }];
  });
}

function remapRangeOverlapSeconds(unit: RemapTimedTextUnit, range: MappedSubtitleRange) {
  return Math.max(0, Math.min(unit.end, range.sourceEnd) - Math.max(unit.start, range.sourceStart));
}

function assignTimedTextUnitToMappedRange(unit: RemapTimedTextUnit, mappedRanges: MappedSubtitleRange[]) {
  const midpoint = (unit.start + unit.end) / 2;
  const midpointRangeIndex = mappedRanges.findIndex((range) => midpoint >= range.sourceStart - 0.001 && midpoint <= range.sourceEnd + 0.001);
  if (midpointRangeIndex >= 0) return midpointRangeIndex;
  const endRangeIndex = mappedRanges.findIndex((range) => unit.end > range.sourceStart + 0.001 && unit.end <= range.sourceEnd + 0.001);
  if (endRangeIndex >= 0 && remapRangeOverlapSeconds(unit, mappedRanges[endRangeIndex]) > 0.001) return endRangeIndex;
  let bestIndex = -1;
  let bestOverlap = 0;
  mappedRanges.forEach((range, index) => {
    const overlap = remapRangeOverlapSeconds(unit, range);
    if (overlap > bestOverlap + 0.001 || (Math.abs(overlap - bestOverlap) <= 0.001 && overlap > 0 && index > bestIndex)) {
      bestOverlap = overlap;
      bestIndex = index;
    }
  });
  return bestOverlap > 0.001 ? bestIndex : -1;
}

function extendSubtitleTextEndThroughTrailingSeparators(chars: string[], endIndex: number) {
  let nextEnd = endIndex;
  while (nextEnd < chars.length && !isTranscriptTimedChar(chars[nextEnd])) {
    nextEnd += 1;
  }
  return nextEnd;
}

function splitRemappedSubtitleTextByTimedUnits(
  subtitle: JobManualEditSubtitle,
  mappedRanges: MappedSubtitleRange[],
  text: string,
) {
  const units = timedUnitsWithTextSpansForRemap(text, subtitle);
  if (!units.length) return null;
  const chars = Array.from(text);
  const unitsByRange = mappedRanges.map(() => [] as RemapTimedTextUnitWithSpan[]);
  for (const unit of units) {
    const rangeIndex = assignTimedTextUnitToMappedRange(unit, mappedRanges);
    if (rangeIndex >= 0) unitsByRange[rangeIndex]?.push(unit);
  }
  if (!unitsByRange.some((items) => items.length)) return null;
  let cursor = 0;
  return unitsByRange.map((rangeUnits) => {
    if (!rangeUnits.length) return "";
    const sortedUnits = [...rangeUnits].sort((left, right) => left.textStart - right.textStart || left.textEnd - right.textEnd);
    const first = sortedUnits[0];
    const last = sortedUnits[sortedUnits.length - 1];
    const startIndex = Math.max(cursor, first.textStart);
    const endIndex = extendSubtitleTextEndThroughTrailingSeparators(chars, Math.max(startIndex, last.textEnd));
    cursor = Math.max(cursor, endIndex);
    return chars.slice(startIndex, endIndex).join("").trim();
  });
}

const SUBTITLE_SAFE_SPLIT_BOUNDARY_RE = /[\s,，、。.!！?？;；:：()[\]（）【】"'“”‘’]/;
const SUBTITLE_CJK_CHAR_RE = /[\u4e00-\u9fff]/;

function isSafeSubtitleTextSplitBoundary(chars: string[], index: number) {
  if (index <= 0 || index >= chars.length) return true;
  const left = chars[index - 1] || "";
  const right = chars[index] || "";
  if (SUBTITLE_SAFE_SPLIT_BOUNDARY_RE.test(left) || SUBTITLE_SAFE_SPLIT_BOUNDARY_RE.test(right)) return true;
  return !(SUBTITLE_CJK_CHAR_RE.test(left) && SUBTITLE_CJK_CHAR_RE.test(right));
}

function snapSubtitleTextSplitBoundary(chars: string[], boundary: number, minIndex: number, maxIndex: number) {
  const clamped = clamp(Math.round(boundary), minIndex, maxIndex);
  if (isSafeSubtitleTextSplitBoundary(chars, clamped)) return clamped;
  const maxDistance = Math.max(4, Math.ceil(chars.length * 0.2));
  for (let distance = 1; distance <= maxDistance; distance += 1) {
    const left = clamped - distance;
    if (left >= minIndex && isSafeSubtitleTextSplitBoundary(chars, left)) return left;
    const right = clamped + distance;
    if (right <= maxIndex && isSafeSubtitleTextSplitBoundary(chars, right)) return right;
  }
  return clamped;
}

function splitRemappedSubtitleTextBySafeCharacterBoundaries(
  text: string,
  mappedRanges: MappedSubtitleRange[],
  subtitleStart: number,
  subtitleEnd: number,
) {
  const chars = Array.from(text);
  const duration = Math.max(0.001, subtitleEnd - subtitleStart);
  let cursor = 0;
  return mappedRanges.map((range, index) => {
    const remainingRanges = mappedRanges.length - index - 1;
    const startRatio = clamp((range.sourceStart - subtitleStart) / duration, 0, 1);
    const endRatio = clamp((range.sourceEnd - subtitleStart) / duration, 0, 1);
    const rawStart = Math.floor(chars.length * startRatio);
    const rawEnd = Math.ceil(chars.length * endRatio);
    const maxEnd = chars.length - remainingRanges;
    let startIndex = Math.max(cursor, rawStart);
    let endIndex = Math.max(startIndex, rawEnd);
    endIndex = Math.min(endIndex, maxEnd);
    if (index > 0 && endIndex > cursor + 1) {
      startIndex = snapSubtitleTextSplitBoundary(chars, startIndex, cursor, endIndex - 1);
    }
    endIndex = snapSubtitleTextSplitBoundary(chars, endIndex, Math.min(maxEnd, startIndex + 1), maxEnd);
    if (endIndex <= startIndex && chars.length - cursor > remainingRanges) {
      endIndex = Math.min(maxEnd, startIndex + 1);
    }
    const piece = chars.slice(startIndex, endIndex);
    cursor = Math.max(cursor, endIndex);
    return piece.join("");
  });
}

function splitRemappedSubtitleText(
  subtitle: JobManualEditSubtitle,
  mappedRanges: MappedSubtitleRange[],
  subtitleStart: number,
  subtitleEnd: number,
) {
  const text = subtitleText(subtitle).trim();
  if (!text) return mappedRanges.map(() => "");
  const timedPieces = splitRemappedSubtitleTextByTimedUnits(subtitle, mappedRanges, text);
  if (timedPieces) return timedPieces;
  const hasSpaces = text.includes(" ");
  const tokens = hasSpaces ? text.split(/\s+/).filter(Boolean) : Array.from(text);
  if (!tokens.length) return mappedRanges.map(() => "");
  if (!hasSpaces) {
    return splitRemappedSubtitleTextBySafeCharacterBoundaries(text, mappedRanges, subtitleStart, subtitleEnd);
  }
  const duration = Math.max(0.001, subtitleEnd - subtitleStart);
  let cursor = 0;
  return mappedRanges.map((range, index) => {
    const remainingRanges = mappedRanges.length - index - 1;
    const startRatio = clamp((range.sourceStart - subtitleStart) / duration, 0, 1);
    const endRatio = clamp((range.sourceEnd - subtitleStart) / duration, 0, 1);
    const rawStart = Math.floor(tokens.length * startRatio);
    const rawEnd = Math.ceil(tokens.length * endRatio);
    let startIndex = Math.max(cursor, rawStart);
    let endIndex = Math.max(startIndex, rawEnd);
    endIndex = Math.min(endIndex, tokens.length - remainingRanges);
    if (endIndex <= startIndex && tokens.length - cursor > remainingRanges) {
      endIndex = Math.min(tokens.length - remainingRanges, startIndex + 1);
    }
    const piece = tokens.slice(startIndex, endIndex);
    cursor = Math.max(cursor, endIndex);
    return hasSpaces ? piece.join(" ") : piece.join("");
  });
}

function keepSegmentsEquivalent(left: KeepSegment[], right: KeepSegment[]) {
  if (left.length !== right.length) return false;
  return left.every((segment, index) => {
    const other = right[index];
    return Boolean(other)
      && Math.abs(segment.start - other.start) <= 0.001
      && Math.abs(segment.end - other.end) <= 0.001;
  });
}

function sortedSubtitles(subtitles: JobManualEditSubtitle[]) {
  return [...subtitles].sort((left, right) => left.start_time - right.start_time || left.index - right.index);
}

function applySubtitleDrafts(subtitles: JobManualEditSubtitle[], drafts: Record<number, SubtitleDraft>) {
  const baseIndexes = new Set(subtitles.map((subtitle) => subtitle.index));
  const adjusted = subtitles
    .map((subtitle) => {
      const draft = drafts[subtitle.index];
      if (!draft) return subtitle;
      if (draft.delete) return null;
      const start = draft.start_time ?? subtitle.start_time;
      const end = draft.end_time ?? subtitle.end_time;
      return {
        ...subtitle,
        start_time: Number(Math.max(0, start).toFixed(3)),
        end_time: Number(Math.max(start + MIN_SUBTITLE_DURATION_SEC, end).toFixed(3)),
        text_final: draft.text_final ?? subtitle.text_final,
      };
    })
    .filter(Boolean) as JobManualEditSubtitle[];

  for (const [rawIndex, draft] of Object.entries(drafts)) {
    const index = Number(rawIndex);
    if (baseIndexes.has(index) || draft.delete) continue;
    const start = Math.max(0, Number(draft.start_time || 0));
    const end = Math.max(start + MIN_SUBTITLE_DURATION_SEC, Number(draft.end_time || start + MIN_SUBTITLE_DURATION_SEC));
    const text = String(draft.text_final || "").trim();
    adjusted.push({
      index,
      start_time: Number(start.toFixed(3)),
      end_time: Number(end.toFixed(3)),
      text_raw: text,
      text_norm: text,
      text_final: text,
    });
  }

  return adjusted
    .sort((left, right) => left.start_time - right.start_time || left.index - right.index);
}

export function buildVisibleSubtitleRows(
  remappedSubtitles: JobManualEditSubtitle[],
  baseProjection: { remapped: JobManualEditSubtitle[]; ranges: OutputRange[] },
  subtitleDrafts: Record<number, SubtitleDraft>,
  sessionKeepSegments: KeepSegment[],
  sessionProjectedSubtitles: JobManualEditSubtitle[],
) {
  const rows: VisibleSubtitleRow[] = remappedSubtitles.map((subtitle) => ({ ...subtitle }));
  const activeIndexes = new Set(rows.map((subtitle) => subtitle.index));
  const sessionRanges = buildOutputRanges(sessionKeepSegments).ranges;
  for (const [rawIndex, draft] of Object.entries(subtitleDrafts)) {
    if (!draft.delete) continue;
    const index = Number(rawIndex);
    if (!Number.isFinite(index) || activeIndexes.has(index)) continue;
    const baseSubtitle = baseProjection.remapped.find((subtitle) => subtitle.index === index);
    const sessionSubtitle = sessionProjectedSubtitles.find((subtitle) => subtitle.index === index);
    const subtitle = baseSubtitle ?? sessionSubtitle;
    if (!subtitle) continue;
    const restoreRanges = baseSubtitle
      ? outputRangeToSourceRanges(baseSubtitle.start_time, baseSubtitle.end_time, baseProjection.ranges)
      : outputRangeToSourceRanges(sessionSubtitle?.start_time ?? subtitle.start_time, sessionSubtitle?.end_time ?? subtitle.end_time, sessionRanges);
    rows.push({
      ...subtitle,
      start_time: Number((draft.start_time ?? subtitle.start_time).toFixed(3)),
      end_time: Number((draft.end_time ?? subtitle.end_time).toFixed(3)),
      text_final: draft.text_final ?? subtitle.text_final,
      deleted: true,
      restoreRanges,
    });
  }
  return rows.sort((left, right) => left.start_time - right.start_time || left.index - right.index);
}

function subtitleOverrideChanged(base: JobManualEditSubtitle | undefined, draft: SubtitleDraft) {
  if (draft.delete) return true;
  if (!base) return Boolean(draft.text_final || draft.start_time != null || draft.end_time != null);
  const baseText = subtitleText(base);
  const draftText = String(draft.text_final ?? baseText);
  const draftStart = draft.start_time ?? base.start_time;
  const draftEnd = draft.end_time ?? base.end_time;
  return (
    Math.abs(draftStart - base.start_time) > 0.001 ||
    Math.abs(draftEnd - base.end_time) > 0.001 ||
    draftText.trim() !== baseText.trim()
  );
}

function videoAspectRatioLabel(value?: string | null) {
  return ASPECT_RATIO_OPTIONS.find((option) => option.value === value)?.label ?? "跟随原片";
}

function videoResolutionLabel(transform: JobManualVideoTransform) {
  if (transform.resolution_mode === "specified") {
    return RESOLUTION_PRESET_OPTIONS.find((option) => option.value === transform.resolution_preset)?.label ?? "1080p";
  }
  return "原片";
}

function summarizeSubtitleOverrides(overrides: JobManualEditSubtitleOverride[], baseSubtitles: JobManualEditSubtitle[]) {
  const baseByIndex = new Map(baseSubtitles.map((subtitle) => [subtitle.index, subtitle]));
  return overrides.reduce(
    (summary, override) => {
      const base = baseByIndex.get(override.index);
      if (!base && !override.delete) {
        summary.created += 1;
        return summary;
      }
      if (override.delete) {
        summary.deleted += 1;
        return summary;
      }
      if ((override.text_final ?? base?.text_final ?? null) !== (base?.text_final ?? null)) summary.text += 1;
      if (
        base
        && (
          Math.abs((override.start_time ?? base.start_time) - base.start_time) > 0.001
          || Math.abs((override.end_time ?? base.end_time) - base.end_time) > 0.001
        )
      ) {
        summary.timing += 1;
      }
      return summary;
    },
    { created: 0, deleted: 0, text: 0, timing: 0 },
  );
}

export function buildManualEditChangeList(options: {
  baseSegments: KeepSegment[];
  effectiveSegments: KeepSegment[];
  outputDurationDeltaSec: number;
  subtitleOverrides: JobManualEditSubtitleOverride[];
  baseSubtitles: JobManualEditSubtitle[];
  subtitleReplacements: JobManualSubtitleReplacement[];
  baseVideoTransform: JobManualVideoTransform;
  currentVideoTransform: JobManualVideoTransform;
  hasVideoSummaryEdits: boolean;
}): ManualEditChangeListItem[] {
  const items: ManualEditChangeListItem[] = [];
  const hasTimelineEdits = !keepSegmentsEquivalent(options.baseSegments, options.effectiveSegments);
  if (hasTimelineEdits) {
    const segmentDetail = options.baseSegments.length === options.effectiveSegments.length
      ? `${options.effectiveSegments.length} 个保留段边界已调整`
      : `保留段 ${options.baseSegments.length} -> ${options.effectiveSegments.length}`;
    items.push({
      key: "timeline",
      title: "剪辑时间线",
      detail: `${segmentDetail}，输出时长变化 ${options.outputDurationDeltaSec >= 0 ? "+" : "-"}${formatSeconds(Math.abs(options.outputDurationDeltaSec))}`,
      meta: "保存后重建时间线",
      tone: "timeline",
    });
  }

  if (options.baseVideoTransform.rotation_cw !== options.currentVideoTransform.rotation_cw) {
    items.push({
      key: "rotation",
      title: "画面旋转",
      detail: `${options.baseVideoTransform.rotation_cw}° -> ${options.currentVideoTransform.rotation_cw}°`,
      meta: "重新渲染",
      tone: "video",
    });
  }

  if (options.baseVideoTransform.aspect_ratio !== options.currentVideoTransform.aspect_ratio) {
    items.push({
      key: "aspect-ratio",
      title: "画面比例",
      detail: `${videoAspectRatioLabel(options.baseVideoTransform.aspect_ratio)} -> ${videoAspectRatioLabel(options.currentVideoTransform.aspect_ratio)}`,
      meta: "重新渲染",
      tone: "video",
    });
  }

  if (
    options.baseVideoTransform.resolution_mode !== options.currentVideoTransform.resolution_mode
    || options.baseVideoTransform.resolution_preset !== options.currentVideoTransform.resolution_preset
  ) {
    items.push({
      key: "resolution",
      title: "输出分辨率",
      detail: `${videoResolutionLabel(options.baseVideoTransform)} -> ${videoResolutionLabel(options.currentVideoTransform)}`,
      meta: "重新渲染",
      tone: "video",
    });
  }

  if (options.subtitleOverrides.length) {
    const summary = summarizeSubtitleOverrides(options.subtitleOverrides, options.baseSubtitles);
    const details = [
      summary.text ? `文本 ${summary.text}` : "",
      summary.timing ? `时间 ${summary.timing}` : "",
      summary.deleted ? `删除 ${summary.deleted}` : "",
      summary.created ? `新增 ${summary.created}` : "",
    ].filter(Boolean);
    items.push({
      key: "subtitles",
      title: "字幕修改",
      detail: `${options.subtitleOverrides.length} 条${details.length ? `（${details.join(" / ")}）` : ""}`,
      meta: "复用剪辑计划",
      tone: "subtitle",
    });
  }

  if (options.subtitleReplacements.length) {
    const replacementCount = options.subtitleReplacements.reduce((total, item) => total + Math.max(1, Number(item.occurrence_count || 1)), 0);
    items.push({
      key: "subtitle-replacements",
      title: "术语替换",
      detail: `${options.subtitleReplacements.length} 组替换，影响 ${replacementCount} 处`,
      meta: "写入校对习惯",
      tone: "subtitle",
    });
  }

  if (options.hasVideoSummaryEdits) {
    items.push({
      key: "video-summary",
      title: "视频摘要",
      detail: "人工摘要已修改，将作为审核、字幕校对和文案链路的强证据",
      meta: "更新上下文",
      tone: "summary",
    });
  }

  if (!items.length) {
    items.push({
      key: "empty",
      title: "暂无改动",
      detail: "删段、字幕、画面或摘要调整后会在这里实时汇总。",
      meta: "草稿监听中",
      tone: "empty",
    });
  }

  return items;
}

function subtitleDiagnostics(subtitles: JobManualEditSubtitle[], totalDuration: number) {
  const warnings: Record<number, string[]> = {};
  let issueCount = 0;
  subtitles.forEach((subtitle, index) => {
    const rowWarnings: string[] = [];
    const previous = index > 0 ? subtitles[index - 1] : null;
    const text = subtitleText(subtitle).trim();
    if (!text) rowWarnings.push("空文本");
    if (subtitle.end_time <= subtitle.start_time + MIN_SUBTITLE_DURATION_SEC) rowWarnings.push("过短");
    if (previous && subtitle.start_time < previous.end_time + MIN_SUBTITLE_GAP_SEC - 0.001) rowWarnings.push("重叠");
    if (totalDuration > 0 && subtitle.end_time > totalDuration + 0.001) rowWarnings.push("超出");
    if (rowWarnings.length) {
      warnings[subtitle.index] = rowWarnings;
      issueCount += rowWarnings.length;
    }
  });
  return { warnings, issueCount };
}

function normalizeTermKey(term: string) {
  return term.trim().toLocaleLowerCase().replace(/\s+/g, "");
}

function compactTermText(term: string) {
  return term.toLocaleLowerCase().replace(/[\s"'`.,!?;:，。！？、；：《》（）()【】[\]{}]+/g, "");
}

function cleanTermToken(term: string) {
  return term.replace(/^[\s"'`.,!?;:，。！？、；：《》（）()【】[\]{}]+|[\s"'`.,!?;:，。！？、；：《》（）()【】[\]{}]+$/g, "");
}

function isCommonSpokenTerm(term: string) {
  const cleaned = cleanTermToken(term);
  if (!cleaned) return true;
  if (TERM_STOPWORDS.has(cleaned) || TERM_GENERIC_NOUNS.has(cleaned)) return true;
  if (cleaned.length <= 4 && (TERM_COMMON_SPOKEN_PREFIX_RE.test(cleaned) || TERM_COMMON_SPOKEN_SUFFIX_RE.test(cleaned))) return true;
  if (/^[这那它他她我你您咱][个些种样的]?$/.test(cleaned)) return true;
  if (/^(怎么|怎样|为什么|什么|哪里|哪个|哪些|多少|这么|那么)/.test(cleaned)) return true;
  if (/^(经常|一直|总是|已经|还是|就是|只是|比较|非常|特别|很多|一些|所有|每个)/.test(cleaned)) return true;
  if (/^(除了|以及|而且|并且|或者|但是|不过|所以|因为)/.test(cleaned)) return true;
  if (/^(不|没|无|非)[\u4e00-\u9fff]{1,2}$/.test(cleaned)) return true;
  if (/^(看到|看见|觉得|感觉|知道|认为|发现|比如|对比)$/.test(cleaned)) return true;
  if (/[的地得]$/.test(cleaned) && cleaned.length <= 3) return true;
  return false;
}

function isMeaningfulTerm(term: string) {
  const cleaned = cleanTermToken(term);
  if (!cleaned || isCommonSpokenTerm(cleaned)) return false;
  if (/^\d+(?:\.\d+)?$/.test(cleaned)) return false;
  if (TERM_OBVIOUS_CHINESE_NUMBER_RE.test(cleaned) && TERM_CHINESE_NUMBER_UNIT_RE.test(cleaned)) return false;
  if (/^[a-z]$/i.test(cleaned)) return false;
  if (/^[\u4e00-\u9fff]$/.test(cleaned)) return false;
  if (/^(怎么|怎样|为什么|什么|哪里|哪个|哪些|多少|这么|那么)/.test(cleaned)) return false;
  if (/^(经常|一直|总是|已经|还是|就是|只是|比较|非常|特别|很多|一些|所有|每个)/.test(cleaned)) return false;
  if (/^(除了|以及|而且|并且|或者|但是|不过|所以|因为)/.test(cleaned)) return false;
  if (/^(不|没|无|非)[\u4e00-\u9fff]{1,2}$/.test(cleaned)) return false;
  if (/^(看到|看见|觉得|感觉|知道|认为|发现|比如|对比)$/.test(cleaned)) return false;
  if (/[的地得]$/.test(cleaned) && cleaned.length <= 3) return false;
  if (cleaned.length < 2) return false;
  return /[\u4e00-\u9fffA-Za-z]/.test(cleaned);
}

function isModelOrBrandLikeTerm(term: string) {
  const cleaned = cleanTermToken(term);
  const normalized = normalizeTermKey(cleaned);
  if (TERM_LATIN_STOPWORDS.has(normalized)) return false;
  if (isChineseDigitSequenceLikeTerm(cleaned)) return true;
  if (/[A-Za-z].*\d|\d.*[A-Za-z]/.test(cleaned)) return true;
  if (/[A-Z]{2,}/.test(cleaned)) return true;
  if (/[A-Za-z]/.test(cleaned) && /(pro|max|plus|ultra|mini|air|se|lite|gen|v\d+)$/i.test(cleaned)) return true;
  if (/[A-Za-z]/.test(cleaned) && cleaned.length >= 3) return true;
  if (/\d+(?:\.\d+)?(?:k|p|fps|hz|mm|cm|gb|tb|x)?$/i.test(cleaned) && /[A-Za-z0-9]/.test(cleaned)) return true;
  return false;
}

function isChineseDigitSequenceLikeTerm(term: string) {
  const cleaned = cleanTermToken(term);
  return /^[零〇一二三四五六七八九两幺]{2,}$/.test(cleaned);
}

function tokenizeChineseDigitSequences(text: string) {
  const tokens: string[] = [];
  for (const match of text.matchAll(TERM_CHINESE_DIGIT_SEQUENCE_RE)) {
    const token = match[0];
    const start = match.index ?? 0;
    const before = text[start - 1] || "";
    const after = text[start + token.length] || "";
    if (TERM_CHINESE_NUMBER_UNIT_RE.test(before) || TERM_CHINESE_NUMBER_UNIT_RE.test(after)) continue;
    tokens.push(token);
  }
  return tokens;
}

function hasTermEntityContext(term: string, subtitles: JobManualEditSubtitle[]) {
  return subtitles.some((subtitle) => {
    const text = subtitleText(subtitle);
    const index = text.indexOf(term);
    if (index < 0) return false;
    const windowText = text.slice(Math.max(0, index - 10), Math.min(text.length, index + term.length + 10));
    return TERM_ENTITY_CONTEXT_RE.test(windowText);
  });
}

function isDomainNounOrTerm(term: string, subtitles: JobManualEditSubtitle[]) {
  const cleaned = cleanTermToken(term);
  if (TERM_GENERIC_NOUNS.has(cleaned) || isCommonSpokenTerm(cleaned)) return false;
  if (isModelOrBrandLikeTerm(cleaned)) return true;
  if (TERM_DOMAIN_NOUN_RE.test(cleaned) || TERM_PRODUCT_SUFFIX_RE.test(cleaned)) return true;
  if (cleaned.length >= 3 && hasTermEntityContext(cleaned, subtitles)) return true;
  return false;
}

function subtitleHasUnstableText(subtitle: JobManualEditSubtitle) {
  const variants = [subtitle.text_raw, subtitle.text_norm, subtitle.text_final]
    .map((value) => compactTermText(String(value || "")))
    .filter(Boolean);
  return new Set(variants).size > 1;
}

function isLowConfidenceLikeTerm(term: string, bucket: FrequentTermBucket) {
  if (bucket.unstableSubtitleCount >= 2 && bucket.unstableSubtitleCount / Math.max(1, bucket.occurrences.length) >= 0.35) return true;
  if (bucket.count >= 4 && TERM_LOW_CONFIDENCE_SHAPE_RE.test(term) && !isCommonSpokenTerm(term)) return true;
  return false;
}

function frequentTermReviewPriority(bucket: FrequentTermBucket) {
  const term = bucket.term;
  if (isCommonSpokenTerm(term)) return 0;
  let priority = 0;
  const modelLike = isModelOrBrandLikeTerm(term);
  const domainLike = isDomainNounOrTerm(term, bucket.occurrences);
  const lowConfidenceLike = isLowConfidenceLikeTerm(term, bucket);
  if (modelLike) priority += 6;
  if (domainLike) priority += 4;
  if (lowConfidenceLike) priority += 3;
  if (bucket.entityContextCount > 0) priority += 2;
  if (bucket.count >= 5) priority += 1;
  if (/^[\u4e00-\u9fff]{2}$/.test(term) && !modelLike && !domainLike && !lowConfidenceLike) priority -= 3;
  if ((TERM_VERB_HINTS.has(term) || TERM_ADJECTIVE_HINTS.has(term)) && !lowConfidenceLike && !modelLike && !domainLike) priority -= 2;
  return Math.max(0, priority);
}

function classifyMeaningfulTerm(term: string, bucket?: FrequentTermBucket): FrequentTermKind {
  if (isModelOrBrandLikeTerm(term)) return "专名/型号";
  if (bucket && isLowConfidenceLikeTerm(term, bucket) && !isDomainNounOrTerm(term, bucket.occurrences)) return "低置信词";
  if (bucket && isDomainNounOrTerm(term, bucket.occurrences)) return "名词/术语";
  if (TERM_VERB_HINTS.has(term) || /(化|启动|生成|调整|修改|替换|识别|核对|渲染|合成|剪辑|发布)$/.test(term)) return "动作词";
  if (TERM_ADJECTIVE_HINTS.has(term) || /(高|低|快|慢|强|弱|好|坏|准|错|清晰|稳定|方便|完整|明显)$/.test(term)) return "描述词";
  return "名词/术语";
}

function termCharacterSet(term: string) {
  return new Set([...cleanTermToken(term)].filter((char) => /[\u4e00-\u9fffA-Za-z0-9]/.test(char)));
}

function sharedTermCharacterCount(left: string, right: string) {
  const leftChars = termCharacterSet(left);
  const rightChars = termCharacterSet(right);
  let count = 0;
  for (const char of leftChars) {
    if (rightChars.has(char)) count += 1;
  }
  return count;
}

function areRelatedManualTermCandidates(baseTerm: string, candidateTerm: string) {
  const base = cleanTermToken(baseTerm);
  const candidate = cleanTermToken(candidateTerm);
  if (!base || !candidate || normalizeTermKey(base) === normalizeTermKey(candidate)) return false;
  if (base.length < 2 || candidate.length < 2) return false;
  if (base.includes(candidate) || candidate.includes(base)) return true;
  const sharedCount = sharedTermCharacterCount(base, candidate);
  if (sharedCount >= 2) return true;
  return (
    sharedCount >= 1
    && Math.min(base.length, candidate.length) <= 3
    && (base[0] === candidate[0] || base[base.length - 1] === candidate[candidate.length - 1])
  );
}

function tokenizeRelatedChineseFragments(text: string, baseTerm: string) {
  const fragments: string[] = [];
  for (const match of text.matchAll(/[\u4e00-\u9fff]{2,12}/g)) {
    const segment = match[0];
    for (let size = 2; size <= Math.min(4, segment.length); size += 1) {
      for (let start = 0; start <= segment.length - size; start += 1) {
        const fragment = segment.slice(start, start + size);
        if (!isCommonSpokenTerm(fragment) && areRelatedManualTermCandidates(baseTerm, fragment)) fragments.push(fragment);
      }
    }
  }
  return fragments;
}

function tokenizeMeaningfulTerms(text: string) {
  const normalized = text.replace(/[|/\\\n\r\t]/g, " ");
  const tokens = tokenizeChineseDigitSequences(normalized);
  const Segmenter = (Intl as typeof Intl & {
    Segmenter?: new (locale: string, options: { granularity: "word" }) => {
      segment: (input: string) => Iterable<{ segment: string; isWordLike?: boolean }>;
    };
  }).Segmenter;

  if (Segmenter) {
    const segmenter = new Segmenter("zh", { granularity: "word" });
    for (const part of segmenter.segment(normalized)) {
      if (part.isWordLike === false) continue;
      const cleaned = cleanTermToken(part.segment);
      if (isMeaningfulTerm(cleaned)) tokens.push(cleaned);
    }
    return tokens;
  }

  const matches = normalized.match(/[A-Za-z][A-Za-z0-9+#.-]{1,}|[A-Za-z0-9+#.-]*\d[A-Za-z0-9+#.-]*|[\u4e00-\u9fff]{2,8}/g) || [];
  for (const match of matches) {
    const cleaned = cleanTermToken(match);
    if (isMeaningfulTerm(cleaned)) tokens.push(cleaned);
  }
  return tokens;
}

export function buildFrequentTerms(subtitles: JobManualEditSubtitle[]) {
  const buckets = new Map<string, FrequentTermBucket>();
  for (const subtitle of subtitles) {
    const seenInSubtitle = new Set<string>();
    const unstableSubtitle = subtitleHasUnstableText(subtitle);
    for (const term of tokenizeMeaningfulTerms(subtitleText(subtitle))) {
      const normalized = normalizeTermKey(term);
      const existing = buckets.get(normalized) ?? {
        term,
        normalized,
        count: 0,
        kind: "名词/术语" as FrequentTermKind,
        reviewPriority: 0,
        subtitleIndexes: [],
        occurrences: [],
        entityContextCount: 0,
        unstableSubtitleCount: 0,
      };
      existing.count += 1;
      if (!seenInSubtitle.has(normalized)) {
        existing.subtitleIndexes.push(subtitle.index);
        existing.occurrences.push(subtitle);
        if (unstableSubtitle) existing.unstableSubtitleCount += 1;
        if (hasTermEntityContext(term, [subtitle])) existing.entityContextCount += 1;
        seenInSubtitle.add(normalized);
      }
      buckets.set(normalized, existing);
    }
  }

  return [...buckets.values()]
    .map((bucket) => {
      const reviewPriority = frequentTermReviewPriority(bucket);
      return {
        term: bucket.term,
        normalized: bucket.normalized,
        count: bucket.count,
        kind: classifyMeaningfulTerm(bucket.term, bucket),
        reviewPriority,
        subtitleIndexes: bucket.subtitleIndexes,
        occurrences: bucket.occurrences,
      };
    })
    .filter((term) => term.reviewPriority >= 3)
    .sort((left, right) => (
      right.reviewPriority - left.reviewPriority
      || right.count - left.count
      || left.term.localeCompare(right.term, "zh-Hans-CN")
    ))
    .slice(0, TERM_RESULT_LIMIT);
}

function collectManualRelatedTermBuckets(term: string, subtitles: JobManualEditSubtitle[], frequentTerms: FrequentTerm[]) {
  const buckets = new Map<string, FrequentTermBucket>();
  const remember = (candidate: string, subtitle: JobManualEditSubtitle, occurrenceCount: number) => {
    const cleaned = cleanTermToken(candidate);
    if (!cleaned || !areRelatedManualTermCandidates(term, cleaned)) return;
    const normalized = normalizeTermKey(cleaned);
    const existing = buckets.get(normalized) ?? {
      term: cleaned,
      normalized,
      count: 0,
      kind: "名词/术语" as FrequentTermKind,
      reviewPriority: 0,
      subtitleIndexes: [],
      occurrences: [],
      entityContextCount: 0,
      unstableSubtitleCount: 0,
    };
    existing.count += Math.max(1, occurrenceCount);
    if (!existing.subtitleIndexes.includes(subtitle.index)) {
      existing.subtitleIndexes.push(subtitle.index);
      existing.occurrences.push(subtitle);
      if (subtitleHasUnstableText(subtitle)) existing.unstableSubtitleCount += 1;
      if (hasTermEntityContext(cleaned, [subtitle])) existing.entityContextCount += 1;
    }
    buckets.set(normalized, existing);
  };

  for (const subtitle of subtitles) {
    const text = subtitleText(subtitle);
    const seen = new Set<string>();
    for (const token of tokenizeMeaningfulTerms(text)) {
      const normalized = normalizeTermKey(token);
      if (seen.has(normalized)) continue;
      seen.add(normalized);
      remember(token, subtitle, countTextMatches(text, token));
    }
    for (const token of tokenizeRelatedChineseFragments(text, term)) {
      const normalized = normalizeTermKey(token);
      if (seen.has(normalized)) continue;
      seen.add(normalized);
      remember(token, subtitle, countTextMatches(text, token));
    }
  }

  for (const candidate of frequentTerms) {
    if (!areRelatedManualTermCandidates(term, candidate.term)) continue;
    const existing = buckets.get(candidate.normalized) ?? {
      ...candidate,
      entityContextCount: 0,
      unstableSubtitleCount: 0,
    };
    existing.count = Math.max(existing.count, candidate.count);
    existing.subtitleIndexes = Array.from(new Set([...existing.subtitleIndexes, ...candidate.subtitleIndexes]));
    const occurrenceMap = new Map(existing.occurrences.map((subtitle) => [subtitle.index, subtitle]));
    for (const subtitle of candidate.occurrences) occurrenceMap.set(subtitle.index, subtitle);
    existing.occurrences = [...occurrenceMap.values()].sort((left, right) => left.start_time - right.start_time);
    buckets.set(candidate.normalized, existing);
  }

  return [...buckets.values()].filter((bucket) => bucket.count >= 2);
}

export function buildManualFrequentTerm(term: string, subtitles: JobManualEditSubtitle[], frequentTerms: FrequentTerm[] = []) {
  const cleaned = cleanTermToken(term);
  if (!cleaned || normalizeTermKey(cleaned).length < 2) return null;
  const relatedBuckets = collectManualRelatedTermBuckets(cleaned, subtitles, frequentTerms);
  const occurrenceMap = new Map<number, JobManualEditSubtitle>();
  let count = 0;

  for (const subtitle of subtitles) {
    const text = subtitleText(subtitle);
    const subtitleMatchCount = countTextMatches(text, cleaned);
    if (subtitleMatchCount > 0) {
      count += subtitleMatchCount;
      occurrenceMap.set(subtitle.index, subtitle);
    }
  }

  if (count <= 0) return null;
  const occurrences = [...occurrenceMap.values()].sort((left, right) => left.start_time - right.start_time);
  return {
    term: cleaned,
    normalized: normalizeTermKey(cleaned),
    count,
    kind: isModelOrBrandLikeTerm(cleaned) ? "专名/型号" : "低置信词",
    reviewPriority: 100,
    subtitleIndexes: occurrences.map((subtitle) => subtitle.index),
    occurrences,
    relatedTerms: relatedBuckets.map((bucket) => bucket.term),
    manuallyAdded: true,
  } satisfies FrequentTerm;
}

function mergeManualFrequentTerms(frequentTerms: FrequentTerm[], manualTerms: FrequentTerm[]) {
  if (!manualTerms.length) return frequentTerms;
  const hiddenByManual = new Set<string>();
  for (const term of manualTerms) {
    for (const relatedTerm of term.relatedTerms || []) hiddenByManual.add(normalizeTermKey(relatedTerm));
  }
  const kept = frequentTerms.filter((term) => (
    !manualTerms.some((manualTerm) => manualTerm.normalized === term.normalized)
    && !hiddenByManual.has(term.normalized)
  ));
  return [...manualTerms, ...kept]
    .sort((left, right) => (
      Number(Boolean(right.manuallyAdded)) - Number(Boolean(left.manuallyAdded))
      || right.reviewPriority - left.reviewPriority
      || right.count - left.count
      || left.term.localeCompare(right.term, "zh-Hans-CN")
    ))
    .slice(0, TERM_RESULT_LIMIT);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function selectedTextFromElement(element: Element | null) {
  if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) return "";
  const start = element.selectionStart ?? 0;
  const end = element.selectionEnd ?? 0;
  if (end <= start) return "";
  return element.value.slice(start, end).trim();
}

function selectedTextFromWindow() {
  return (window.getSelection?.()?.toString() || "").trim();
}

function countSubtitleMatches(subtitles: JobManualEditSubtitle[], find: string) {
  if (!find) return 0;
  let count = 0;
  for (const subtitle of subtitles) {
    const text = subtitleText(subtitle);
    let cursor = 0;
    while (true) {
      const index = text.indexOf(find, cursor);
      if (index < 0) break;
      count += 1;
      cursor = index + Math.max(1, find.length);
    }
  }
  return count;
}

function countTextMatches(text: string, find: string) {
  if (!find) return 0;
  let count = 0;
  let cursor = 0;
  while (true) {
    const index = text.indexOf(find, cursor);
    if (index < 0) break;
    count += 1;
    cursor = index + Math.max(1, find.length);
  }
  return count;
}

function applySubtitleReplacementHistoryToText(text: string, replacements: JobManualSubtitleReplacement[] = []) {
  return replacements.reduce((current, item) => {
    const original = String(item.original || "").trim();
    const replacement = String(item.replacement || "").trim();
    if (!original || !replacement || original === replacement || !current.includes(original)) return current;
    return current.replace(new RegExp(escapeRegExp(original), "g"), replacement);
  }, text);
}

function normalizeRotationValue(value: number) {
  const normalized = ((Math.round(value / 90) * 90) % 360 + 360) % 360;
  return ROTATION_OPTIONS.includes(normalized) ? normalized : 0;
}

function normalizeVideoTransform(transform?: JobManualVideoTransform | null): JobManualVideoTransform {
  const aspectRatio = ASPECT_RATIO_OPTIONS.some((option) => option.value === transform?.aspect_ratio) ? String(transform?.aspect_ratio) : "source";
  const resolutionMode = RESOLUTION_MODE_OPTIONS.some((option) => option.value === transform?.resolution_mode) ? String(transform?.resolution_mode) : "source";
  const resolutionPreset = RESOLUTION_PRESET_OPTIONS.some((option) => option.value === transform?.resolution_preset) ? String(transform?.resolution_preset) : "1080p";
  return {
    rotation_cw: normalizeRotationValue(Number(transform?.rotation_cw || 0)),
    aspect_ratio: aspectRatio,
    resolution_mode: resolutionMode,
    resolution_preset: resolutionPreset,
  };
}

function aspectRatioCssValue(value?: string | null) {
  switch (value) {
    case "9:16":
      return "9 / 16";
    case "1:1":
      return "1 / 1";
    case "4:3":
      return "4 / 3";
    case "16:9":
    case "source":
    default:
      return "16 / 9";
  }
}

function aspectRatioNumber(value?: string | null) {
  switch (value) {
    case "9:16":
      return 9 / 16;
    case "1:1":
      return 1;
    case "4:3":
      return 4 / 3;
    case "16:9":
    default:
      return 16 / 9;
  }
}

export function outputTimeToSourceTime(outputTime: number, ranges: OutputRange[]) {
  if (!ranges.length) return 0;
  const normalized = Math.max(0, outputTime || 0);
  for (const range of ranges) {
    if (normalized < range.outputStart) return range.sourceStart;
    if (normalized <= range.outputEnd) {
      return range.sourceStart + (normalized - range.outputStart);
    }
  }
  return ranges[ranges.length - 1]?.sourceEnd ?? 0;
}

export function outputTimeToSourceTimeForSegments(outputTime: number, keepSegments: KeepSegment[]) {
  const projection = buildOutputRanges(keepSegments);
  if (!projection.ranges.length || projection.totalDuration <= 0) return 0;
  const normalizedOutputTime = clamp(outputTime, 0, Math.max(0, projection.totalDuration - 0.001));
  return outputTimeToSourceTime(normalizedOutputTime, projection.ranges);
}

export function sourceTimeToOutputTime(sourceTime: number, ranges: OutputRange[]) {
  if (!ranges.length) return 0;
  const normalized = Math.max(0, sourceTime || 0);
  let lastOutput = 0;
  for (const range of ranges) {
    if (normalized < range.sourceStart) return lastOutput;
    if (normalized <= range.sourceEnd) {
      return range.outputStart + (normalized - range.sourceStart);
    }
    lastOutput = range.outputEnd;
  }
  return lastOutput;
}

export function sourceTimeToActiveOutputTime(sourceTime: number, ranges: OutputRange[]) {
  if (!ranges.length) return null;
  const normalized = Math.max(0, sourceTime || 0);
  for (const range of ranges) {
    if (normalized < range.sourceStart - 0.02) return null;
    if (normalized <= range.sourceEnd + 0.02) {
      return clamp(range.outputStart + (normalized - range.sourceStart), range.outputStart, range.outputEnd);
    }
  }
  return null;
}

export function sourceTimeToEditedPlaybackStartTime(sourceTime: number, ranges: OutputRange[]) {
  if (!ranges.length) return null;
  const normalized = Math.max(0, sourceTime || 0);
  for (const range of ranges) {
    if (normalized < range.sourceStart - 0.001) return range.sourceStart;
    if (normalized < range.sourceEnd - 0.02) {
      return clamp(normalized, range.sourceStart, range.sourceEnd);
    }
  }
  return null;
}

export function resolveEditedPlaybackSyncDecision(
  sourceTime: number,
  ranges: OutputRange[],
  options?: { boundaryToleranceSec?: number; gapOvershootToleranceSec?: number },
): EditedPlaybackSyncDecision {
  if (!ranges.length) return { action: "none" };
  const normalized = Math.max(0, Number(sourceTime || 0));
  const boundaryTolerance = options?.boundaryToleranceSec ?? 0.04;
  const gapOvershootTolerance = options?.gapOvershootToleranceSec ?? 0.04;

  for (let index = 0; index < ranges.length; index += 1) {
    const range = ranges[index];
    if (normalized < range.sourceStart - boundaryTolerance) {
      return { action: "seek", sourceTime: range.sourceStart };
    }
    if (normalized <= range.sourceEnd - boundaryTolerance) {
      return { action: "none" };
    }
    if (normalized <= range.sourceEnd + gapOvershootTolerance) {
      const nextRange = ranges[index + 1];
      return nextRange ? { action: "seek", sourceTime: nextRange.sourceStart } : { action: "stop" };
    }
  }

  return { action: "stop" };
}

export function findSubtitleIndexNearOutputTime(
  subtitles: Pick<JobManualEditSubtitle, "start_time" | "end_time">[],
  outputTime: number | null | undefined,
) {
  if (!subtitles.length) return -1;
  const time = Number(outputTime ?? 0);
  if (!Number.isFinite(time)) return 0;
  let previousIndex = -1;
  for (let index = 0; index < subtitles.length; index += 1) {
    const subtitle = subtitles[index];
    if (time <= subtitle.end_time + 0.02) return index;
    previousIndex = index;
  }
  return previousIndex >= 0 ? previousIndex : 0;
}

export function buildOutputWaveformBars(
  peaks: number[] | undefined,
  ranges: OutputRange[],
  totalOutputDuration: number,
  sourceDuration: number,
  barCount = 180,
) {
  const count = Math.max(1, Math.floor(barCount));
  if (!peaks?.length || !ranges.length || totalOutputDuration <= 0 || sourceDuration <= 0) {
    return Array.from({ length: count }, () => 0.12);
  }
  return Array.from({ length: count }, (_, index) => {
    const outputTime = totalOutputDuration * ((index + 0.5) / count);
    const sourceTime = outputTimeToSourceTime(outputTime, ranges);
    const peakIndex = clamp(Math.round((sourceTime / sourceDuration) * (peaks.length - 1)), 0, peaks.length - 1);
    const peak = Math.abs(Number(peaks[peakIndex] || 0));
    return clamp(Math.max(peak, 0.08), 0.08, 1);
  });
}

function buildSourceWaveformBars(peaks: number[] | undefined, count = 220) {
  if (!peaks?.length) {
    return Array.from({ length: count }, () => 0.08);
  }
  return Array.from({ length: count }, (_, index) => {
    const peakIndex = clamp(Math.round(((index + 0.5) / count) * (peaks.length - 1)), 0, peaks.length - 1);
    return clamp(Math.abs(Number(peaks[peakIndex] || 0)), 0.08, 1);
  });
}

function outputRangeToSourceRanges(outputStart: number, outputEnd: number, ranges: OutputRange[]) {
  const start = Math.min(outputStart, outputEnd);
  const end = Math.max(outputStart, outputEnd);
  const sourceRanges: KeepSegment[] = [];
  for (const range of ranges) {
    const overlapStart = Math.max(start, range.outputStart);
    const overlapEnd = Math.min(end, range.outputEnd);
    if (overlapEnd <= overlapStart + 0.02) continue;
    sourceRanges.push({
      start: Number((range.sourceStart + (overlapStart - range.outputStart)).toFixed(3)),
      end: Number((range.sourceStart + (overlapEnd - range.outputStart)).toFixed(3)),
    });
  }
  return sourceRanges;
}

function removeSourceRangesFromSegments(segments: KeepSegment[], rangesToRemove: KeepSegment[]) {
  if (!rangesToRemove.length) return segments;
  let nextSegments = [...segments];
  for (const removeRange of rangesToRemove) {
    nextSegments = nextSegments.flatMap((segment) => {
      if (removeRange.end <= segment.start + 0.001 || removeRange.start >= segment.end - 0.001) return [segment];
      const pieces: KeepSegment[] = [];
      const beforeEnd = Math.min(segment.end, removeRange.start);
      const afterStart = Math.max(segment.start, removeRange.end);
      if (beforeEnd > segment.start + 0.05) {
        pieces.push({ start: segment.start, end: Number(beforeEnd.toFixed(3)) });
      }
      if (segment.end > afterStart + 0.05) {
        pieces.push({ start: Number(afterStart.toFixed(3)), end: segment.end });
      }
      return pieces;
    });
  }
  return nextSegments.sort((left, right) => left.start - right.start);
}

function addSourceRangesToSegments(segments: KeepSegment[], rangesToAdd: KeepSegment[], sourceDuration: number) {
  const normalized = [...segments, ...rangesToAdd]
    .map((segment) => ({
      start: Number(clamp(segment.start, 0, sourceDuration).toFixed(3)),
      end: Number(clamp(segment.end, 0, sourceDuration).toFixed(3)),
    }))
    .filter((segment) => segment.end > segment.start + 0.05)
    .sort((left, right) => left.start - right.start);
  const merged: KeepSegment[] = [];
  for (const segment of normalized) {
    const previous = merged[merged.length - 1];
    if (!previous || segment.start > previous.end + 0.02) {
      merged.push({ ...segment });
      continue;
    }
    previous.end = Number(Math.max(previous.end, segment.end).toFixed(3));
  }
  return merged;
}

function isSourceRangeKept(start: number, end: number, segments: KeepSegment[]) {
  return segments.some((segment) => start >= segment.start - 0.02 && end <= segment.end + 0.02);
}

function sourceCutRangesFromKeepSegments(segments: KeepSegment[], sourceDuration: number) {
  const cuts: KeepSegment[] = [];
  const duration = Math.max(0, sourceDuration || 0);
  let cursor = 0;
  for (const segment of [...segments].sort((left, right) => left.start - right.start)) {
    const start = clamp(segment.start, 0, duration);
    const end = clamp(segment.end, start, duration);
    if (start > cursor + 0.05) {
      cuts.push({ start: Number(cursor.toFixed(3)), end: Number(start.toFixed(3)) });
    }
    cursor = Math.max(cursor, end);
  }
  if (duration > cursor + 0.05) {
    cuts.push({ start: Number(cursor.toFixed(3)), end: Number(duration.toFixed(3)) });
  }
  return cuts;
}

function sourceRangesToTimelineItems(ranges: KeepSegment[], sourceDuration: number): SourceTimelineRangeItem[] {
  if (sourceDuration <= 0) return [];
  return ranges
    .map((range) => {
      const start = clamp(range.start, 0, sourceDuration);
      const end = clamp(range.end, start, sourceDuration);
      return {
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
        leftPercent: clamp((start / sourceDuration) * 100, 0, 100),
        widthPercent: clamp(((end - start) / sourceDuration) * 100, 0, 100),
      };
    })
    .filter((range) => range.end > range.start + 0.05 && range.widthPercent > 0);
}

function sourceSubtitlesForTranscript(session: Pick<JobManualEditSession, "source_subtitles" | "projected_subtitles">) {
  const source = session.source_subtitles.length ? session.source_subtitles : session.projected_subtitles;
  return sortedSubtitles(source);
}

function buildSourceTranscriptRowsForTimeline(
  session: Pick<JobManualEditSession, "source_subtitles" | "projected_subtitles"> & { keep_segments?: KeepSegment[] },
  subtitleDrafts: Record<number, SubtitleTextDraft>,
  subtitleReplacements: JobManualSubtitleReplacement[] = [],
  _projectedSubtitles: JobManualEditSubtitle[] = [],
) {
  return sourceSubtitlesForTranscript(session).map((subtitle) => {
    const draft = subtitleDrafts[subtitle.index];
    const sourceText = subtitleTranscriptSourceText(subtitle);
    const fallbackText = sourceText.trim() ? sourceText : subtitleText(subtitle);
    const draftText = draft?.text_final;
    const baseText = draftText != null ? preferSourceTranscriptOverDraftText(draftText, fallbackText) : fallbackText;
    const nextText = applySubtitleReplacementHistoryToText(baseText, subtitleReplacements);
    const transcriptTextChanged = nextText !== sourceText;
    return {
      ...subtitle,
      text_final: nextText,
      ...(subtitle.transcript_text != null || transcriptTextChanged ? { transcript_text: nextText } : {}),
    };
  });
}

export function buildSourceTranscriptSubtitlesForTimeline(
  session: Pick<JobManualEditSession, "source_subtitles" | "projected_subtitles"> & { keep_segments?: KeepSegment[] },
  projectedSubtitles: JobManualEditSubtitle[],
  subtitleDrafts: Record<number, SubtitleTextDraft>,
  subtitleReplacements: JobManualSubtitleReplacement[] = [],
) {
  const sourceRows = buildSourceTranscriptRowsForTimeline(session, subtitleDrafts, subtitleReplacements, projectedSubtitles);
  return splitLongSubtitleDisplayRows(sourceRows);
}

export function buildSourceTranscriptProjectedBaseline(
  session: Pick<JobManualEditSession, "projected_subtitles">,
  subtitleDrafts: Record<number, SubtitleDraft>,
) {
  return applySubtitleDrafts(sortedSubtitles(session.projected_subtitles), subtitleDrafts);
}

function projectedSubtitlesForTranscript(subtitles: JobManualEditSubtitle[], ranges: OutputRange[]) {
  if (!subtitles.length || !ranges.length) return [];
  return sortedSubtitles(subtitles).flatMap((subtitle) => {
    const sourceRanges = outputRangeToSourceRanges(subtitle.start_time, subtitle.end_time, ranges);
    if (!sourceRanges.length) return [];
    const sourceStart = Math.min(...sourceRanges.map((range) => range.start));
    const sourceEnd = Math.max(...sourceRanges.map((range) => range.end));
    if (sourceEnd <= sourceStart + 0.02) return [];
    return [{
      ...subtitle,
      start_time: Number(sourceStart.toFixed(3)),
      end_time: Number(sourceEnd.toFixed(3)),
    }];
  });
}

function sourceRangeOverlapsKeptSegments(start: number, end: number, segments: KeepSegment[]) {
  return segments.some((segment) => Math.min(end, segment.end) > Math.max(start, segment.start) + 0.02);
}

export function sourceRangeOverlapsCutRanges(start: number, end: number, cutRanges: KeepSegment[]) {
  const rangeStart = Math.min(start, end);
  const rangeEnd = Math.max(start, end);
  const duration = Math.max(0, rangeEnd - rangeStart);
  const minimumOverlap = duration > 0 ? Math.min(0.015, Math.max(0.004, duration * 0.2)) : 0.001;
  return cutRanges.some((range) => Math.min(rangeEnd, range.end) - Math.max(rangeStart, range.start) >= minimumOverlap);
}

function smartDeleteReasonLabel(reason?: string | null) {
  switch (reason) {
    case "rollback_instruction":
      return "口播指令回删";
    case "restart_retake":
      return "重说/返工片段";
    case "duplicate":
      return "重复表达";
    case "off_topic":
      return "偏离主题";
    case "low_information":
      return "信息量低";
    case "filler":
      return "冗余口播";
    default:
      return reason?.trim() || "模型判断为可删内容";
  }
}

function smartCutRuleLabel(kind: SmartCutRuleKind) {
  switch (kind) {
    case "filler":
      return "语气词";
    case "repeated":
      return "重复口误";
    case "pause":
      return "长停顿";
    case "smart_delete":
      return "智能废片";
    default:
      return "剪辑规则";
  }
}

function smartCutRuleReason(kind: SmartCutRuleKind, match?: SmartCutRuleMatch | null) {
  switch (kind) {
    case "filler":
      return "删除没有信息增量的口头填充音。";
    case "repeated":
      return "删除重说时多出来的重复字词。";
    case "pause":
      return "删除超过阈值且不压到有效语音的空白。";
    case "smart_delete":
      return `建议剪掉${smartDeleteReasonLabel(match?.detail || match?.reason)}，需逐条确认。`;
    default:
      return "按当前规则进入待剪区间。";
  }
}

function manualCutReason() {
  return "手动删除：用户在全文剪辑或时间轴中删除。";
}

function smartCutRuleMatchForSourceRange(
  start: number,
  end: number,
  ranges: SmartCutRuleMatch[],
  restoredRanges: KeepSegment[],
): SmartCutRuleMatch | null {
  if (sourceRangeOverlapsCutRanges(start, end, restoredRanges)) return null;
  const priority: SmartCutRuleKind[] = ["smart_delete", "pause", "repeated", "filler"];
  for (const kind of priority) {
    const match = ranges.find((range) => range.kind === kind && sourceRangeOverlapsCutRanges(start, end, [range]));
    if (match) return match;
  }
  return null;
}

function normalizeSilenceRanges(
  ranges: Array<Partial<JobManualEditSilence> | Partial<SilenceRange> | null | undefined>,
  sourceDuration: number,
  minDuration = 0.12,
) {
  const normalized = ranges
    .map((range) => {
      const start = Number(range?.start ?? 0);
      const end = Number(range?.end ?? start);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      const clampedStart = Number(clamp(start, 0, Math.max(0, sourceDuration || end)).toFixed(3));
      const clampedEnd = Number(clamp(end, clampedStart, Math.max(clampedStart, sourceDuration || end)).toFixed(3));
      if (clampedEnd <= clampedStart + minDuration - 0.001) return null;
      return {
        start: clampedStart,
        end: clampedEnd,
        duration_sec: Number((clampedEnd - clampedStart).toFixed(3)),
        source: String(range?.source || "audio_vad"),
      } satisfies SilenceRange;
    })
    .filter(Boolean) as SilenceRange[];

  normalized.sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: SilenceRange[] = [];
  for (const range of normalized) {
    const previous = merged[merged.length - 1];
    if (!previous || range.start > previous.end + 0.03) {
      merged.push({ ...range });
      continue;
    }
    previous.end = Number(Math.max(previous.end, range.end).toFixed(3));
    previous.duration_sec = Number((previous.end - previous.start).toFixed(3));
    if (previous.source !== range.source) previous.source = "mixed";
  }
  return merged;
}

export function normalizeReviewPauseRanges(
  ranges: SilenceRange[],
  subtitles: JobManualEditSubtitle[],
  options: { fillers?: string[] } = {},
) {
  const fillers = options.fillers || [];
  const sorted = [...ranges]
    .filter((range) => range.end > range.start + 0.02)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const groups: SilenceRange[][] = [];
  const timedSpeechRanges = asrTimedSpeechRangesForSubtitles(subtitles);
  for (const range of sorted) {
    const previousGroup = groups[groups.length - 1];
    const previousRange = previousGroup?.[previousGroup.length - 1];
    if (previousGroup && previousRange && pauseRangesCanCluster(previousRange, range, subtitles, fillers, timedSpeechRanges)) {
      previousGroup.push(range);
    } else {
      groups.push([range]);
    }
  }

  const normalized: SilenceRange[] = [];
  for (const group of groups) {
    const first = group[0];
    const last = group[group.length - 1];
    if (!first || !last) continue;
    const start = Number(first.start.toFixed(3));
    const end = Number(last.end.toFixed(3));
    const spanDuration = Number((end - start).toFixed(3));
    const source = group.every((range) => range.source === first.source) ? first.source : "mixed";
    normalized.push({
      start,
      end,
      duration_sec: spanDuration,
      source,
    });
  }
  return normalized;
}

function silenceRangeHasAudioEvidence(range: Pick<SilenceRange, "source"> | null | undefined) {
  const source = String(range?.source || "").toLocaleLowerCase();
  return source.includes("audio") || source.includes("vad") || source === "mixed";
}

function silenceRangeHasAsrEvidence(range: Pick<SilenceRange, "source"> | null | undefined) {
  const source = String(range?.source || "").toLocaleLowerCase();
  return source.includes("asr") || source.includes("word") || source.includes("alignment") || source === "mixed";
}

function subtitlePauseIntervals(subtitles: JobManualEditSubtitle[]) {
  const intervals: SilenceRange[] = [];
  sortedSubtitles(subtitles).forEach((subtitle, index, items) => {
    const previous = items[index - 1];
    if (!previous) return;
    const start = Number(previous.end_time || 0);
    const end = Number(subtitle.start_time || 0);
    if (end <= start + 0.12) return;
    intervals.push({
      start: Number(start.toFixed(3)),
      end: Number(end.toFixed(3)),
      duration_sec: Number((end - start).toFixed(3)),
      source: "subtitle_gap",
    });
  });
  return intervals;
}

export function intersectInferredPausesWithAudioSilence(inferredPauses: SilenceRange[], audioSilences: SilenceRange[]) {
  if (!audioSilences.length) return inferredPauses;
  const sortedAudioSilences = [...audioSilences].sort((left, right) => left.start - right.start || left.end - right.end);
  const intervals: SilenceRange[] = [];
  inferredPauses.forEach((pause) => {
    sortedAudioSilences.forEach((silence) => {
      const start = Number(Math.max(pause.start, silence.start).toFixed(3));
      const end = Number(Math.min(pause.end, silence.end).toFixed(3));
      if (end <= start + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001) return;
      intervals.push({
        start,
        end,
        duration_sec: Number((end - start).toFixed(3)),
        source: `${pause.source}+${silence.source || "audio_vad"}`,
      });
    });
  });
  return intervals;
}

function silenceRangesOverlap(left: KeepSegment, right: KeepSegment) {
  return Math.min(left.end, right.end) - Math.max(left.start, right.start) > 0.02;
}

type AsrTimedSpeechRange = KeepSegment & {
  source: "alignment" | "word";
};

function asrTimedSpeechRangesForSubtitle(subtitle: JobManualEditSubtitle) {
  const alignmentRanges = (subtitle.alignment_tokens || [])
    .map((token): AsrTimedSpeechRange | null => {
      const start = Number(token.start);
      const end = Number(token.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
      if (!String(token.text || "").trim()) return null;
      return {
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
        source: "alignment",
      };
    })
    .filter((range): range is AsrTimedSpeechRange => Boolean(range));
  if (alignmentRanges.length) {
    if (
      !subtitleAlignmentTimingTextMatchesSubtitleText(
        subtitle,
        (subtitle.alignment_tokens || []).map((token) => String(token.text || "")).join(""),
      )
      || !subtitleTimingRangesArePlausible(subtitle, alignmentRanges)
    ) {
      return [];
    }
    return alignmentRanges.sort((left, right) => left.start - right.start || left.end - right.end);
  }

  if (!subtitleWordTimingsMatchSubtitleText(subtitle)) return [];

  return (subtitle.words || [])
    .map((word): AsrTimedSpeechRange | null => {
      const start = Number(word.start);
      const end = Number(word.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
      if (!String(word.word || "").trim()) return null;
      return {
        start: Number(clamp(start, subtitle.start_time, subtitle.end_time).toFixed(3)),
        end: Number(clamp(end, subtitle.start_time, subtitle.end_time).toFixed(3)),
        source: "word",
      };
    })
    .filter((range): range is AsrTimedSpeechRange => Boolean(range))
    .sort((left, right) => left.start - right.start || left.end - right.end);
}

function subtitleCanonicalTimingText(subtitle: JobManualEditSubtitle) {
  return subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
}

function subtitleTimingTextMatchesSubtitleText(subtitle: JobManualEditSubtitle, timingText: string) {
  const subtitleKey = compactTranscriptText(subtitleCanonicalTimingText(subtitle));
  const timingKey = compactTranscriptText(timingText);
  if (!subtitleKey || !timingKey) return false;
  if (subtitleKey === timingKey) return true;
  if (timingKey.length >= 4 && subtitleKey.includes(timingKey)) return true;
  if (timingKey.length >= 4 && transcriptTextIsSubsequence(timingKey, subtitleKey)) return true;
  const commonRatio = transcriptTextCommonSubsequenceRatio(subtitleKey, timingKey);
  const lengthRatio = Math.max(subtitleKey.length, timingKey.length) / Math.max(1, Math.min(subtitleKey.length, timingKey.length));
  return commonRatio >= 0.6 && lengthRatio <= 1.8;
}

function subtitleAlignmentTimingTextMatchesSubtitleText(subtitle: JobManualEditSubtitle, timingText: string) {
  if (subtitleTimingTextMatchesSubtitleText(subtitle, timingText)) return true;
  const diagnostics = subtitle.alignment_diagnostics;
  const matchedRatio = Number(diagnostics?.matched_ratio ?? 0);
  const boundaryPartialAlignment = (diagnostics?.issues || []).some((issue) => /unmatched_text_(prefix|suffix)/.test(String(issue || "")));
  return diagnostics?.status === "warning"
    && boundaryPartialAlignment
    && matchedRatio >= 0.35
    && compactTranscriptText(timingText).length >= 2;
}

function subtitleTimingRangesArePlausible(subtitle: JobManualEditSubtitle, ranges: KeepSegment[]) {
  const sorted = [...ranges].sort((left, right) => left.start - right.start || left.end - right.end);
  if (sorted.length < 2) return true;
  const subtitleStart = Number(subtitle.start_time || 0);
  const subtitleEnd = Number(subtitle.end_time || subtitleStart);
  const subtitleDuration = Math.max(0.001, subtitleEnd - subtitleStart);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (!first || !last) return false;
  if (first.start < subtitleStart - 0.35 || last.end > subtitleEnd + 0.35) return false;
  const span = Math.max(0, last.end - first.start);
  const tinyDurationRatio = sorted.filter((range) => range.end <= range.start + 0.006).length / sorted.length;
  if (sorted.length >= 4 && tinyDurationRatio > 0.35) return false;
  const timedTextLength = compactTranscriptText(subtitleCanonicalTimingText(subtitle)).length;
  if (timedTextLength >= 6 && span < Math.min(subtitleDuration * 0.18, timedTextLength * 0.035)) return false;
  return true;
}

function subtitleWordTimingsMatchSubtitleText(subtitle: JobManualEditSubtitle) {
  const words = subtitle.words || [];
  if (!words.length) return false;
  const timingText = words.map((word) => String(word.word || "")).join("");
  if (!subtitleTimingTextMatchesSubtitleText(subtitle, timingText)) return false;
  const ranges = words
    .map((word): KeepSegment | null => {
      const start = Number(word.start);
      const end = Number(word.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
      return { start, end };
    })
    .filter((range): range is KeepSegment => Boolean(range));
  return subtitleTimingRangesArePlausible(subtitle, ranges);
}

function asrTimedSpeechRangesForSubtitles(subtitles: JobManualEditSubtitle[]) {
  return sortedSubtitles(subtitles)
    .flatMap(asrTimedSpeechRangesForSubtitle)
    .sort((left, right) => left.start - right.start || left.end - right.end);
}

export function wordTimingPauseIntervals(subtitles: JobManualEditSubtitle[], minDuration = 0.18) {
  const speechRanges = asrTimedSpeechRangesForSubtitles(subtitles);
  const intervals: SilenceRange[] = [];
  let previous: AsrTimedSpeechRange | null = null;
  for (const current of speechRanges) {
    if (!previous) {
      previous = current;
      continue;
    }
    if (current.start <= previous.end + 0.001) {
      if (current.end > previous.end) {
        previous = {
          start: previous.start,
          end: current.end,
          source: previous.source === "alignment" || current.source === "alignment" ? "alignment" : "word",
        };
      }
      continue;
    }
    const rawStart = previous.end;
    const rawEnd = current.start;
    if (rawEnd > rawStart + minDuration - 0.001) {
      const start = Number(Math.min(rawEnd, rawStart + WORD_TIMING_PAUSE_EDGE_GUARD_SEC).toFixed(3));
      const end = Number(Math.max(start, rawEnd - WORD_TIMING_PAUSE_EDGE_GUARD_SEC).toFixed(3));
      if (end > start + minDuration - 0.001) {
        const source = previous.source === "alignment" || current.source === "alignment" ? "alignment_gap" : "word_gap";
        intervals.push({
          start,
          end,
          duration_sec: Number((end - start).toFixed(3)),
          source,
        });
      }
    }
    previous = current;
  }
  return intervals;
}

export function projectedTranscriptMissesKeptSpeech(
  projectedTranscript: JobManualEditSubtitle[],
  sourceSubtitles: JobManualEditSubtitle[],
  segments: KeepSegment[],
) {
  if (!projectedTranscript.length || !sourceSubtitles.length || !segments.length) return false;
  const sortedProjected = sortedSubtitles(projectedTranscript);
  const sortedSource = sortedSubtitles(sourceSubtitles);
  for (let index = 1; index < sortedProjected.length; index += 1) {
    const previous = sortedProjected[index - 1];
    const current = sortedProjected[index];
    const gapStart = Number(previous.end_time || 0);
    const gapEnd = Number(current.start_time || 0);
    if (gapEnd <= gapStart + 1.0) continue;
    const hasKeptSourceSpeech = sortedSource.some((subtitle) => {
      if (!subtitleText(subtitle).trim()) return false;
      const overlapStart = Math.max(gapStart, Number(subtitle.start_time || 0));
      const overlapEnd = Math.min(gapEnd, Number(subtitle.end_time || 0));
      return overlapEnd > overlapStart + 0.12 && sourceRangeOverlapsKeptSegments(overlapStart, overlapEnd, segments);
    });
    if (hasKeptSourceSpeech) return true;
  }
  return false;
}

function subtitleIndexesOverlap(left: JobManualEditSubtitle, right: JobManualEditSubtitle) {
  const leftIndexes = new Set(subtitleSourceIndexes(left));
  return subtitleSourceIndexes(right).some((index) => leftIndexes.has(index));
}

export function projectedSubtitlesHaveDuplicateSourceOverlap(subtitles: JobManualEditSubtitle[]) {
  const sorted = sortedSubtitles(subtitles);
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    if (!subtitleIndexesOverlap(previous, current)) continue;
    const overlap = subtitleTimeOverlapSeconds(previous, current);
    const previousDuration = Math.max(0.001, previous.end_time - previous.start_time);
    const currentDuration = Math.max(0.001, current.end_time - current.start_time);
    const overlapRatio = overlap / Math.min(previousDuration, currentDuration);
    if (overlapRatio >= 0.72) return true;
  }
  return false;
}

const TRANSCRIPT_BOUNDARY_PUNCTUATION_PATTERN = /[。！？!?…，,、；;：:]$/;
const TRANSCRIPT_SENTENCE_PUNCTUATION_PATTERN = /[。！？!?…]$/;

function inferTranscriptBoundaryPunctuation(text: string, gapAfter: number) {
  const trimmed = text.trim();
  if (!trimmed || TRANSCRIPT_BOUNDARY_PUNCTUATION_PATTERN.test(trimmed)) return "";
  return gapAfter >= 0.55 || Array.from(trimmed).length >= 18 ? "。" : "，";
}

function inferTranscriptBreakAfter(text: string, gapAfter: number, paragraphCharCount: number): TranscriptBreakKind | undefined {
  const trimmed = text.trim();
  const sentenceEnd = TRANSCRIPT_SENTENCE_PUNCTUATION_PATTERN.test(trimmed);
  if (gapAfter >= 3.2 || (sentenceEnd && paragraphCharCount >= 96) || paragraphCharCount >= 150) return "paragraph";
  if (gapAfter >= 1.2 || (sentenceEnd && paragraphCharCount >= 52) || Array.from(trimmed).length >= 36) return "soft";
  return undefined;
}

const TRANSCRIPT_TIMED_CHAR_RE = /[\u4e00-\u9fffA-Za-z0-9]/;
const TRANSCRIPT_PAUSE_WORD_GUARD_SEC = 0.08;
const TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC = 0.12;
const WORD_TIMING_PAUSE_EDGE_GUARD_SEC = 0.08;
const SMART_CUT_PAUSE_REVIEW_GROUP_GAP_SEC = 2.4;
const SMART_CUT_PAUSE_REVIEW_GROUP_MAX_SPAN_SEC = 12;
const SMART_CUT_PAUSE_REVIEW_GROUP_MAX_TEXT_CHARS = 30;

type TimedTranscriptChar = {
  text: string;
  start: number;
  end: number;
};

function isTranscriptTimedChar(char: string) {
  return TRANSCRIPT_TIMED_CHAR_RE.test(char);
}

function normalizeTranscriptTimingChar(char: string) {
  const normalized = char.toLocaleLowerCase();
  const digitMap: Record<string, string> = {
    零: "0",
    "〇": "0",
    一: "1",
    二: "2",
    两: "2",
    三: "3",
    四: "4",
    五: "5",
    六: "6",
    七: "7",
    八: "8",
    九: "9",
  };
  return digitMap[normalized] ?? normalized;
}

function timedCharsFromWords(words: JobManualEditWord[] | undefined) {
  const timedChars: TimedTranscriptChar[] = [];
  for (const word of words || []) {
    const start = Number(word.start);
    const end = Number(word.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
    const chars = Array.from(String(word.word || "")).filter(isTranscriptTimedChar);
    if (!chars.length) continue;
    const duration = end - start;
    chars.forEach((char, index) => {
      timedChars.push({
        text: char,
        start: Number((start + duration * (index / chars.length)).toFixed(3)),
        end: Number((start + duration * ((index + 1) / chars.length)).toFixed(3)),
      });
    });
  }
  return timedChars.sort((left, right) => left.start - right.start || left.end - right.end);
}

function transcriptTimingIndexPairs(left: string[], right: string[]) {
  if (!left.length || !right.length) return [];
  const rows = left.length + 1;
  const cols = right.length + 1;
  const dp = Array.from({ length: rows }, () => Array.from({ length: cols }, () => 0));
  for (let row = 1; row < rows; row += 1) {
    for (let col = 1; col < cols; col += 1) {
      dp[row][col] = left[row - 1] === right[col - 1]
        ? dp[row - 1][col - 1] + 1
        : Math.max(dp[row - 1][col], dp[row][col - 1]);
    }
  }
  const pairs: Array<[number, number]> = [];
  let row = left.length;
  let col = right.length;
  while (row > 0 && col > 0) {
    if (left[row - 1] === right[col - 1]) {
      pairs.push([row - 1, col - 1]);
      row -= 1;
      col -= 1;
    } else if (dp[row - 1][col] >= dp[row][col - 1]) {
      row -= 1;
    } else {
      col -= 1;
    }
  }
  return pairs.reverse();
}

function buildTimedTranscriptCharTokens(
  subtitle: JobManualEditSubtitle,
  text: string,
  segments: KeepSegment[],
  options: { sourceIndex: number; tokenKeyScope: string },
): TranscriptToken[] | null {
  const { sourceIndex, tokenKeyScope } = options;
  if (!subtitleWordTimingsMatchSubtitleText(subtitle)) return null;
  const timedChars = timedCharsFromWords(subtitle.words);
  if (!timedChars.length) return null;
  const chars = Array.from(text);
  const timingCharCount = chars.filter(isTranscriptTimedChar).length;
  if (!timingCharCount) return null;
  const timingChars = chars
    .map((char, charIndex) => ({ char, charIndex, key: normalizeTranscriptTimingChar(char) }))
    .filter((item) => isTranscriptTimedChar(item.char));
  const pairs = transcriptTimingIndexPairs(
    timingChars.map((item) => item.key),
    timedChars.map((item) => normalizeTranscriptTimingChar(item.text)),
  );
  const matchedTimedCharByTextIndex = new Map<number, TimedTranscriptChar>();
  pairs.forEach(([timingCharIndex, timedCharIndex]) => {
    matchedTimedCharByTextIndex.set(timingChars[timingCharIndex].charIndex, timedChars[timedCharIndex]);
  });

  const tokens: TranscriptToken[] = [];
  const matchedTimingChars = pairs.length;
  let previousEnd = subtitle.start_time;

  chars.forEach((char, charIndex) => {
    let start = previousEnd;
    let end = previousEnd;
    let timingSource: TranscriptToken["timingSource"] = "estimated";
    if (isTranscriptTimedChar(char)) {
      const match = matchedTimedCharByTextIndex.get(charIndex);
      if (match) {
        start = match.start;
        end = match.end;
        timingSource = "word";
      } else {
        const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
        start = subtitle.start_time + duration * (charIndex / Math.max(1, chars.length));
        end = subtitle.start_time + duration * ((charIndex + 1) / Math.max(1, chars.length));
      }
    }
    previousEnd = Math.max(previousEnd, end);
    tokens.push({
      key: `char-${tokenKeyScope}-${charIndex}`,
      kind: "char",
      text: char,
      subtitleIndex: sourceIndex,
      start: Number(start.toFixed(3)),
      end: Number(end.toFixed(3)),
      kept: isSourceRangeKept(start, end, segments),
      timingSource,
    });
  });

  if (matchedTimingChars / timingCharCount < 0.6) return null;
  return tokens;
}

function buildBackendAlignedTranscriptTokens(
  subtitle: JobManualEditSubtitle,
  segments: KeepSegment[],
  options: { sourceIndex: number; tokenKeyScope: string },
): TranscriptToken[] | null {
  const { sourceIndex, tokenKeyScope } = options;
  const backendTokens: TranscriptToken[] = [];
  (subtitle.alignment_tokens || []).forEach((token, tokenIndex) => {
    const start = Number(token.start);
    const end = Number(token.end);
    const text = String(token.text || "");
    if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    backendTokens.push({
      key: `span-${tokenKeyScope}-${tokenIndex}`,
      kind: "char",
      text,
      subtitleIndex: sourceIndex,
      start: Number(start.toFixed(3)),
      end: Number(end.toFixed(3)),
      kept: isSourceRangeKept(start, end, segments),
      timingSource: "alignment",
    });
  });
  if (!backendTokens.length) return null;
  const rawAlignedText = backendTokens.map((token) => token.text).join("");
  if (
    !subtitleAlignmentTimingTextMatchesSubtitleText(subtitle, rawAlignedText)
    || !subtitleTimingRangesArePlausible(subtitle, backendTokens.map((token) => ({ start: token.start, end: token.end })))
  ) {
    return null;
  }
  const diagnostics = subtitle.alignment_diagnostics;
  const matchedRatio = Number(diagnostics?.matched_ratio ?? 0);
  if (diagnostics?.status === "warning" && matchedRatio < 0.35) return null;
  const canonicalText = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
  const canUseCanonicalText = shouldUseCanonicalAlignedTranscriptText(canonicalText, rawAlignedText, diagnostics?.issues);
  return normalizeAlignedTranscriptTokens(backendTokens, sourceIndex, tokenKeyScope, segments, canUseCanonicalText ? canonicalText : undefined);
}

function shouldUseCanonicalAlignedTranscriptText(canonicalText: string, rawAlignedText: string, alignmentIssues: string[] = []) {
  const canonicalKey = compactTranscriptText(canonicalText);
  const rawKey = compactTranscriptText(rawAlignedText);
  if (!canonicalKey) return false;
  if (!rawKey || canonicalKey === rawKey) return true;
  const boundaryPartialAlignment = alignmentIssues.some((issue) => /unmatched_text_(prefix|suffix)/.test(String(issue || "")));
  if (boundaryPartialAlignment && canonicalKey.includes(rawKey) && canonicalKey.length - rawKey.length >= 2) return false;
  const commonRatio = transcriptTextCommonSubsequenceRatio(canonicalKey, rawKey);
  const lengthRatio = Math.max(canonicalKey.length, rawKey.length) / Math.max(1, Math.min(canonicalKey.length, rawKey.length));
  if (commonRatio >= 0.55 && lengthRatio <= 1.8) return true;
  return Math.max(canonicalKey.length, rawKey.length) <= 4 && commonRatio >= 0.45;
}

function normalizeAlignedTranscriptTokens(tokens: TranscriptToken[], sourceIndex: number, tokenKeyScope: string, segments: KeepSegment[], canonicalText?: string) {
  const rawText = tokens.map((token) => token.text).join("");
  const normalizedText = String(canonicalText || rawText).trim();
  if (!normalizedText || normalizedText === rawText) return tokens;

  const timedChars: TimedTranscriptChar[] = [];
  tokens.forEach((token) => {
    const chars = Array.from(token.text);
    if (!chars.length) return;
    const duration = Math.max(0.001, token.end - token.start);
    chars.forEach((char, charIndex) => {
      timedChars.push({
        text: char,
        start: Number((token.start + duration * (charIndex / chars.length)).toFixed(3)),
        end: Number((token.start + duration * ((charIndex + 1) / chars.length)).toFixed(3)),
      });
    });
  });
  const normalizedChars = Array.from(normalizedText);
  const pairs = transcriptTimingIndexPairs(
    normalizedChars.map(normalizeTranscriptTimingChar),
    timedChars.map((char) => normalizeTranscriptTimingChar(char.text)),
  );
  const timedCharByNormalizedIndex = new Map<number, TimedTranscriptChar>();
  pairs.forEach(([normalizedIndex, timedIndex]) => {
    timedCharByNormalizedIndex.set(normalizedIndex, timedChars[timedIndex]);
  });
  let previousEnd = tokens[0]?.start ?? 0;
  return normalizedChars.map((char, charIndex): TranscriptToken => {
    const match = timedCharByNormalizedIndex.get(charIndex);
    const start = match?.start ?? previousEnd;
    const end = match?.end ?? Math.max(start + 0.001, previousEnd);
    previousEnd = Math.max(previousEnd, end);
    return {
      key: `span-clean-${tokenKeyScope}-${charIndex}`,
      kind: "char",
      text: char,
      subtitleIndex: sourceIndex,
      start: Number(start.toFixed(3)),
      end: Number(end.toFixed(3)),
      kept: isSourceRangeKept(start, end, segments),
      timingSource: match ? "alignment" : "estimated",
    };
  });
}

function transcriptTokenKeyScope(subtitle: JobManualEditSubtitle, subtitlePosition: number, sourceIndex: number) {
  const displayIndex = Number.isFinite(Number(subtitle.index)) ? Number(subtitle.index) : subtitlePosition;
  const fragmentIndex = Number.isFinite(Number(subtitle.source_fragment_index)) ? Number(subtitle.source_fragment_index) : 0;
  return `${sourceIndex}-${displayIndex}-${fragmentIndex}`;
}

function mergeTranscriptTokensInDisplayOrder(charTokens: TranscriptToken[], pauseTokens: TranscriptToken[]) {
  const sortedPauses = [...pauseTokens].sort((left, right) => left.start - right.start || left.end - right.end);
  const tokens: TranscriptToken[] = [];
  let pauseIndex = 0;
  for (const token of charTokens) {
    while (pauseIndex < sortedPauses.length && sortedPauses[pauseIndex].end <= token.start + 0.001) {
      tokens.push(sortedPauses[pauseIndex]);
      pauseIndex += 1;
    }
    tokens.push(token);
  }
  while (pauseIndex < sortedPauses.length) {
    tokens.push(sortedPauses[pauseIndex]);
    pauseIndex += 1;
  }
  return coalesceAdjacentTranscriptPauseTokens(tokens);
}

function transcriptTokenIsVisibleTextBarrier(token: TranscriptToken) {
  if (token.kind === "pause") return false;
  if (token.kind === "punctuation" && token.inferredPunctuation) return false;
  return token.text.trim().length > 0;
}

function mergeTranscriptPauseTokens(left: TranscriptToken, right: TranscriptToken): TranscriptToken {
  const start = Number(Math.min(left.start, right.start).toFixed(3));
  const end = Number(Math.max(left.end, right.end).toFixed(3));
  const pauseDuration = Number(Math.max(0, end - start).toFixed(3));
  const pauseRanges = [
    ...transcriptPauseRangesForToken(left),
    ...transcriptPauseRangesForToken(right),
  ].sort((previous, next) => previous.start - next.start || previous.end - next.end);
  return {
    ...left,
    key: `${left.key}+${right.key}`,
    text: `[...,${pauseDuration.toFixed(1)}s]`,
    start,
    end,
    kept: left.kept && right.kept,
    pauseDuration,
    pauseRanges,
    pauseCount: pauseRanges.length,
  };
}

function coalesceAdjacentTranscriptPauseTokens(tokens: TranscriptToken[]) {
  const merged: TranscriptToken[] = [];
  let pendingPause: TranscriptToken | null = null;
  let pendingNonTextTokens: TranscriptToken[] = [];
  const flushPendingPause = () => {
    if (pendingPause) {
      merged.push(pendingPause);
      pendingPause = null;
    }
    if (pendingNonTextTokens.length) {
      merged.push(...pendingNonTextTokens);
      pendingNonTextTokens = [];
    }
  };

  for (const token of tokens) {
    if (token.kind === "pause") {
      if (pendingPause && token.start <= pendingPause.end + SMART_CUT_PAUSE_CLUSTER_GAP_SEC + 0.001) {
        pendingPause = mergeTranscriptPauseTokens(pendingPause, token);
        pendingNonTextTokens = [];
      } else {
        flushPendingPause();
        pendingPause = token;
      }
      continue;
    }

    if (pendingPause && !transcriptTokenIsVisibleTextBarrier(token)) {
      pendingNonTextTokens.push(token);
      continue;
    }

    flushPendingPause();
    merged.push(token);
  }
  flushPendingPause();
  return merged;
}

export function buildTranscriptTokens(subtitles: JobManualEditSubtitle[], segments: KeepSegment[], silenceRanges: SilenceRange[] = []) {
  const charTokens: TranscriptToken[] = [];
  let paragraphCharCount = 0;
  subtitles.forEach((subtitle, subtitlePosition) => {
    const sourceIndex = subtitleSourceIndex(subtitle);
    const tokenKeyScope = transcriptTokenKeyScope(subtitle, subtitlePosition, sourceIndex);
    const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
    const chars = Array.from(text);
    const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
    const nextSubtitle = subtitles[subtitlePosition + 1];
    const gapAfter = nextSubtitle ? Math.max(0, nextSubtitle.start_time - subtitle.end_time) : 0;
    const inferredPunctuation = inferTranscriptBoundaryPunctuation(text, gapAfter);
    const nextParagraphCharCount = paragraphCharCount + chars.filter((char) => char.trim()).length;
    const breakAfter = inferTranscriptBreakAfter(inferredPunctuation ? `${text}${inferredPunctuation}` : text, gapAfter, nextParagraphCharCount);
    const timedTokens = buildBackendAlignedTranscriptTokens(subtitle, segments, { sourceIndex, tokenKeyScope })
      ?? buildTimedTranscriptCharTokens(subtitle, text, segments, { sourceIndex, tokenKeyScope });
    const tokens: TranscriptToken[] = timedTokens ?? chars.map((char, charIndex): TranscriptToken => {
      const start = subtitle.start_time + duration * (charIndex / Math.max(1, chars.length));
      const end = subtitle.start_time + duration * ((charIndex + 1) / Math.max(1, chars.length));
      return {
        key: `char-${tokenKeyScope}-${charIndex}`,
        kind: "char" as const,
        text: char,
        subtitleIndex: sourceIndex,
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
        kept: isSourceRangeKept(start, end, segments),
        timingSource: "estimated",
      };
    });
    const lastToken = tokens[tokens.length - 1];
    if (lastToken) {
      if (inferredPunctuation && nextSubtitle) {
        const punctuationStart = lastToken.end;
        const punctuationEnd = Math.max(punctuationStart + 0.001, nextSubtitle.start_time);
        tokens.push({
          key: `punctuation-${tokenKeyScope}`,
          kind: "punctuation",
          text: inferredPunctuation,
          subtitleIndex: sourceIndex,
          start: Number(punctuationStart.toFixed(3)),
          end: Number(punctuationEnd.toFixed(3)),
          kept: isSourceRangeKept(punctuationStart, punctuationEnd, segments),
          inferredPunctuation,
          breakAfter,
        });
      } else {
        lastToken.breakAfter = breakAfter;
      }
    }
    charTokens.push(...tokens);
    paragraphCharCount = breakAfter === "paragraph" ? 0 : nextParagraphCharCount;
  });

  const visiblePauseRanges = mergeTranscriptVisiblePauseRanges(
    silenceRanges.flatMap((range) => transcriptVisiblePauseRanges(range, charTokens)),
    charTokens,
  );
  const pauseTokens = visiblePauseRanges.flatMap((visibleRange, visibleIndex) => {
    const fragments = splitPauseRangeByKeepSegments(visibleRange, segments);
    return fragments.map((fragment, fragmentIndex) => {
      const pauseDuration = Number(Math.max(0, fragment.end - fragment.start).toFixed(3));
      const pauseRanges = clipPauseRangesToFragment(visibleRange.ranges, fragment);
      return {
        key: `pause-${visibleIndex}-${fragmentIndex}-${fragment.start}`,
        kind: "pause" as const,
        text: `[...,${pauseDuration.toFixed(1)}s]`,
        subtitleIndex: null,
        start: fragment.start,
        end: fragment.end,
        kept: fragment.kept,
        pauseDuration,
        pauseRanges,
        pauseCount: pauseRanges.length,
      };
    });
  });

  return mergeTranscriptTokensInDisplayOrder(charTokens, pauseTokens);
}

function mergeTranscriptVisiblePauseRanges(ranges: KeepSegment[], tokens: TranscriptToken[]): MergedTranscriptPauseRange[] {
  const sorted = ranges
    .map((range) => ({
      start: Number(range.start.toFixed(3)),
      end: Number(range.end.toFixed(3)),
    }))
    .filter((range) => range.end > range.start + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: MergedTranscriptPauseRange[] = [];
  for (const range of sorted) {
    const previous = merged[merged.length - 1];
    if (!previous || !transcriptPauseRangesCanMerge(previous, range, tokens)) {
      merged.push({ ...range, ranges: [{ start: range.start, end: range.end }] });
      continue;
    }
    previous.end = Number(Math.max(previous.end, range.end).toFixed(3));
    previous.ranges.push({ start: range.start, end: range.end });
  }
  return merged;
}

function transcriptPauseRangesCanMerge(left: KeepSegment, right: KeepSegment, tokens: TranscriptToken[]) {
  if (right.start > left.end + SMART_CUT_PAUSE_CLUSTER_GAP_SEC) return false;
  const gapStart = Math.min(left.end, right.start);
  const gapEnd = Math.max(left.end, right.start);
  if (gapEnd <= gapStart + 0.001) return true;
  return !tokens.some((token) => (
    token.kind === "char"
    && token.text.trim()
    && token.end > gapStart + 0.001
    && token.start < gapEnd - 0.001
  ));
}

function splitPauseRangeByKeepSegments(range: KeepSegment, segments: KeepSegment[]) {
  const start = Number(range.start.toFixed(3));
  const end = Number(range.end.toFixed(3));
  if (end <= start + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001) {
    return [];
  }
  const boundaries = new Set<number>([start, end]);
  for (const segment of segments) {
    if (segment.end <= start + 0.001 || segment.start >= end - 0.001) continue;
    boundaries.add(Number(clamp(segment.start, start, end).toFixed(3)));
    boundaries.add(Number(clamp(segment.end, start, end).toFixed(3)));
  }
  const points = [...boundaries].sort((left, right) => left - right);
  const fragments: Array<KeepSegment & { kept: boolean }> = [];
  for (let index = 1; index < points.length; index += 1) {
    const fragmentStart = points[index - 1];
    const fragmentEnd = points[index];
    if (fragmentEnd <= fragmentStart + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001) continue;
    fragments.push({
      start: fragmentStart,
      end: fragmentEnd,
      kept: isSourceRangeKept(fragmentStart, fragmentEnd, segments),
    });
  }
  return fragments;
}

function clipPauseRangesToFragment(ranges: KeepSegment[], fragment: KeepSegment) {
  const clipped = ranges
    .map((range) => ({
      start: Number(Math.max(range.start, fragment.start).toFixed(3)),
      end: Number(Math.min(range.end, fragment.end).toFixed(3)),
    }))
    .filter((range) => range.end > range.start + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001);
  return clipped.length ? clipped : [{ start: fragment.start, end: fragment.end }];
}

function transcriptVisiblePauseRanges(range: SilenceRange, tokens: TranscriptToken[]) {
  const audioEvidence = silenceRangeHasAudioEvidence(range);
  const asrEvidence = silenceRangeHasAsrEvidence(range);
  if (audioEvidence && audioRangeBroadlyOverlapsEstimatedSpeech(range, tokens)) {
    return [];
  }
  const speechBlockers = tokens
    .filter((token) => token.kind === "char"
      && token.text.trim()
      && (!audioEvidence || transcriptTokenBlocksAudioPause(token))
      && (!asrEvidence || token.timingSource === "word" || token.timingSource === "alignment")
      && token.end > range.start + 0.001
      && token.start < range.end - 0.001)
    .map((token) => ({
      start: Number(Math.max(range.start, token.start - (token.timingSource === "word" ? TRANSCRIPT_PAUSE_WORD_GUARD_SEC : 0.018)).toFixed(3)),
      end: Number(Math.min(range.end, token.end + (token.timingSource === "word" ? TRANSCRIPT_PAUSE_WORD_GUARD_SEC : 0.018)).toFixed(3)),
    }))
    .filter((blocker) => blocker.end > blocker.start + 0.001);
  const visibleRanges = speechBlockers.length
    ? removeSourceRangesFromSegments([{ start: range.start, end: range.end }], addSourceRangesToSegments([], speechBlockers, range.end))
    : [{ start: range.start, end: range.end }];
  return visibleRanges
    .map((visibleRange) => ({
      start: Number(visibleRange.start.toFixed(3)),
      end: Number(visibleRange.end.toFixed(3)),
    }))
    .filter((visibleRange) => visibleRange.end > visibleRange.start + TRANSCRIPT_MIN_VISIBLE_PAUSE_SEC - 0.001);
}

function transcriptTokenBlocksAudioPause(token: TranscriptToken) {
  if (token.timingSource === "word") return true;
  if (token.timingSource === "alignment") return true;
  return false;
}

function audioRangeBroadlyOverlapsEstimatedSpeech(range: SilenceRange, tokens: TranscriptToken[]) {
  const groups = new Map<number, TranscriptToken[]>();
  for (const token of tokens) {
    if (token.kind !== "char" || token.timingSource === "word" || token.timingSource === "alignment" || token.subtitleIndex == null || !token.text.trim()) continue;
    if (token.end <= range.start + 0.001 || token.start >= range.end - 0.001) continue;
    groups.set(token.subtitleIndex, [...(groups.get(token.subtitleIndex) || []), token]);
  }
  for (const group of groups.values()) {
    if (group.length < 4) continue;
    const spanStart = Math.min(...group.map((token) => token.start));
    const spanEnd = Math.max(...group.map((token) => token.end));
    const spanDuration = Math.max(0.001, spanEnd - spanStart);
    const overlap = Math.min(range.end, spanEnd) - Math.max(range.start, spanStart);
    const subtitleIndex = group[0]?.subtitleIndex;
    const subtitleTokens = tokens.filter((token) => (
      token.kind === "char"
      && token.timingSource === "estimated"
      && token.subtitleIndex === subtitleIndex
      && token.text.trim()
    ));
    const subtitleDuration = subtitleTokens.length
      ? Math.max(0.001, Math.max(...subtitleTokens.map((token) => token.end)) - Math.min(...subtitleTokens.map((token) => token.start)))
      : spanDuration;
    const rangeDuration = Math.max(0, range.end - range.start);
    if (overlap / spanDuration >= 0.55 && rangeDuration / subtitleDuration >= 0.72) return true;
  }
  return false;
}

function closestTranscriptTokenIndex(node: Node | null) {
  const element = node instanceof HTMLElement ? node : node?.parentElement;
  const token = element?.closest<HTMLElement>("[data-transcript-token-index]");
  if (!token) return null;
  const index = Number(token.dataset.transcriptTokenIndex);
  return Number.isFinite(index) ? index : null;
}

function transcriptSelectionFromWindow(tokens: TranscriptToken[]) {
  const selection = window.getSelection?.();
  if (!selection || selection.rangeCount <= 0 || selection.isCollapsed) return null;
  const anchorIndex = closestTranscriptTokenIndex(selection.anchorNode);
  const focusIndex = closestTranscriptTokenIndex(selection.focusNode);
  if (anchorIndex == null || focusIndex == null) return null;
  return transcriptSelectionFromTokenRange(tokens, anchorIndex, focusIndex);
}

function transcriptSelectionPopoverPositionFromRect(rect: DOMRect | null): TranscriptSelectionPopoverPosition | null {
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  return {
    left: clamp(rect.left + rect.width / 2, 190, Math.max(190, window.innerWidth - 190)),
    top: clamp(rect.top - 10, 136, Math.max(136, window.innerHeight - 24)),
  };
}

function transcriptSelectionPopoverPositionFromWindow() {
  const selection = window.getSelection?.();
  if (!selection || selection.rangeCount <= 0) return null;
  return transcriptSelectionPopoverPositionFromRect(selection.getRangeAt(0).getBoundingClientRect());
}

function transcriptSelectionFromTokenRange(tokens: TranscriptToken[], anchorIndex: number, focusIndex: number) {
  const startTokenIndex = Math.min(anchorIndex, focusIndex);
  const endTokenIndex = Math.max(anchorIndex, focusIndex);
  const selectedTokens = tokens.slice(startTokenIndex, endTokenIndex + 1);
  if (!selectedTokens.length) return null;
  const sourceStart = Math.min(...selectedTokens.map((token) => token.start));
  const sourceEnd = Math.max(...selectedTokens.map((token) => token.end));
  const text = selectedTokens
    .filter((token) => token.kind === "char" || (token.kind === "punctuation" && !token.inferredPunctuation))
    .map((token) => token.text)
    .join("")
    .trim();
  const pauseCount = selectedTokens.filter((token) => token.kind === "pause").length;
  if (!text && !pauseCount) return null;
  return {
    startTokenIndex,
    endTokenIndex,
    sourceStart: Number(sourceStart.toFixed(3)),
    sourceEnd: Number(sourceEnd.toFixed(3)),
    text,
    keptTokenCount: selectedTokens.filter((token) => token.kept).length,
    cutTokenCount: selectedTokens.filter((token) => !token.kept).length,
    pauseCount: selectedTokens.reduce((total, token) => total + (token.kind === "pause" ? token.pauseCount || 1 : 0), 0),
  };
}

function transcriptPauseRangesForToken(token: TranscriptToken): KeepSegment[] {
  if (token.kind !== "pause") return [];
  return token.pauseRanges?.length
    ? token.pauseRanges.map((range) => ({ start: range.start, end: range.end }))
    : [{ start: token.start, end: token.end }];
}

function transcriptTokenRangesOverlap(token: TranscriptToken, ranges: KeepSegment[]) {
  if (token.kind === "pause") {
    return transcriptPauseRangesForToken(token).some((range) => sourceRangeOverlapsCutRanges(range.start, range.end, ranges));
  }
  return sourceRangeOverlapsCutRanges(token.start, token.end, ranges);
}

function smartCutRuleMatchForTranscriptToken(token: TranscriptToken, ranges: SmartCutRuleMatch[]) {
  const eligibleRanges = token.kind === "pause" ? ranges : ranges.filter((range) => range.kind !== "pause");
  if (token.kind === "pause") {
    for (const range of transcriptPauseRangesForToken(token)) {
      const match = smartCutRuleMatchForSourceRange(range.start, range.end, eligibleRanges, []);
      if (match) return match;
    }
    return null;
  }
  return smartCutRuleMatchForSourceRange(token.start, token.end, eligibleRanges, []);
}

export function removeTranscriptSelectionTextFromSubtitleDrafts(
  subtitles: JobManualEditSubtitle[],
  tokens: TranscriptToken[],
  selection: Pick<TranscriptSelection, "startTokenIndex" | "endTokenIndex">,
  drafts: Record<number, SubtitleDraft>,
) {
  const selectedCharIndexesBySource = new Map<number, Set<number>>();
  const charCursorBySource = new Map<number, number>();
  tokens.forEach((token, tokenIndex) => {
    if (token.kind !== "char" || token.subtitleIndex == null) return;
    const sourceIndex = token.subtitleIndex;
    const charIndex = charCursorBySource.get(sourceIndex) ?? 0;
    charCursorBySource.set(sourceIndex, charIndex + 1);
    if (tokenIndex < selection.startTokenIndex || tokenIndex > selection.endTokenIndex) return;
    const selected = selectedCharIndexesBySource.get(sourceIndex) ?? new Set<number>();
    selected.add(charIndex);
    selectedCharIndexesBySource.set(sourceIndex, selected);
  });
  if (!selectedCharIndexesBySource.size) return drafts;

  const subtitlesBySource = new Map<number, JobManualEditSubtitle>();
  for (const subtitle of subtitles) {
    subtitlesBySource.set(subtitleSourceIndex(subtitle), subtitle);
  }

  let changed = false;
  const nextDrafts: Record<number, SubtitleDraft> = { ...drafts };
  for (const [sourceIndex, selectedCharIndexes] of selectedCharIndexesBySource.entries()) {
    const subtitle = subtitlesBySource.get(sourceIndex);
    if (!subtitle || !selectedCharIndexes.size) continue;
    const chars = Array.from(subtitleText(subtitle));
    const nextText = chars.filter((_, charIndex) => !selectedCharIndexes.has(charIndex)).join("").trim();
    if (nextText === subtitleText(subtitle).trim()) continue;
    nextDrafts[subtitle.index] = {
      ...(nextDrafts[subtitle.index] ?? {}),
      text_final: nextText,
    };
    changed = true;
  }
  return changed ? nextDrafts : drafts;
}

export function transcriptCutRangesForSelection(
  subtitles: JobManualEditSubtitle[],
  tokens: TranscriptToken[],
  selection: Pick<TranscriptSelection, "startTokenIndex" | "endTokenIndex">,
  sourceDuration: number,
) {
  const selectedTokens = tokens.slice(selection.startTokenIndex, selection.endTokenIndex + 1);
  if (!selectedTokens.length) return [];

  const subtitlesBySource = new Map<number, JobManualEditSubtitle>();
  for (const subtitle of subtitles) {
    subtitlesBySource.set(subtitleSourceIndex(subtitle), subtitle);
  }

  const charTokensBySource = new Map<number, TranscriptToken[]>();
  const selectedCharTokensBySource = new Map<number, TranscriptToken[]>();
  const selectedBoundaryTokens: TranscriptToken[] = [];
  tokens.forEach((token, tokenIndex) => {
    if (token.kind === "punctuation" && tokenIndex >= selection.startTokenIndex && tokenIndex <= selection.endTokenIndex) {
      selectedBoundaryTokens.push(token);
      return;
    }
    if (token.kind !== "char" || token.subtitleIndex == null || !token.text.trim()) return;
    const sourceIndex = token.subtitleIndex;
    const allTokens = charTokensBySource.get(sourceIndex) ?? [];
    allTokens.push(token);
    charTokensBySource.set(sourceIndex, allTokens);
    if (tokenIndex < selection.startTokenIndex || tokenIndex > selection.endTokenIndex) return;
    const selected = selectedCharTokensBySource.get(sourceIndex) ?? [];
    selected.push(token);
    selectedCharTokensBySource.set(sourceIndex, selected);
  });

  const ranges: KeepSegment[] = [];
  for (const token of selectedBoundaryTokens) {
    ranges.push({
      start: Number(Math.max(0, token.start).toFixed(3)),
      end: Number(Math.min(sourceDuration, Math.max(token.start, token.end)).toFixed(3)),
    });
  }
  for (const [sourceIndex, selectedCharTokens] of selectedCharTokensBySource.entries()) {
    const allCharTokens = charTokensBySource.get(sourceIndex) || [];
    const subtitle = subtitlesBySource.get(sourceIndex);
    if (subtitle && allCharTokens.length > 0 && selectedCharTokens.length >= allCharTokens.length) {
      ranges.push({
        start: Number(subtitle.start_time.toFixed(3)),
        end: Number(subtitle.end_time.toFixed(3)),
      });
      continue;
    }
    ranges.push({
      start: Number(Math.min(...selectedCharTokens.map((token) => token.start)).toFixed(3)),
      end: Number(Math.max(...selectedCharTokens.map((token) => token.end)).toFixed(3)),
    });
  }

  ranges.push(
    ...selectedTokens
      .filter((token) => token.kind === "pause")
      .flatMap(transcriptPauseRangesForToken)
      .map((range) => ({
        start: Number(range.start.toFixed(3)),
        end: Number(range.end.toFixed(3)),
      })),
  );

  return addSourceRangesToSegments([], ranges, sourceDuration);
}

function parseSmartCutFillers(value: string) {
  return value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);
}

const SMART_CUT_BOUNDARY_PATTERN = /[\s,，、。.!！?？;；:：()[\]（）【】"'“”‘’]/;
const SMART_CUT_HESITATION_FILLERS = new Set(["嗯", "呃", "额", "呃呃", "嗯嗯"]);
const SMART_CUT_WORD_BOUNDARY_GUARD_SEC = 0.16;
const SMART_CUT_REPEAT_STOP_PHRASES = new Set(["这个", "那个", "然后", "就是", "因为", "所以", "但是", "不过", "经常", "常会", "我们", "大家"]);
const SMART_CUT_REPEAT_PROTECTED_PATTERN = /(?:EDC|NITECORE|NOC|UV|流明|\d)/i;

function isSmartCutBoundary(char: string | undefined) {
  return !char || SMART_CUT_BOUNDARY_PATTERN.test(char);
}

function findTextRangesInSubtitle(subtitle: JobManualEditSubtitle, needle: string) {
  const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
  if (!text || !needle) return [];
  const ranges: KeepSegment[] = [];
  const chars = Array.from(text);
  let searchFrom = 0;
  while (searchFrom < text.length) {
    const matchIndex = text.indexOf(needle, searchFrom);
    if (matchIndex < 0) break;
    const startChar = Array.from(text.slice(0, matchIndex)).length;
    const endChar = startChar + Array.from(needle).length;
    const before = chars[startChar - 1];
    const after = chars[endChar];
    const exactBoundaryMatch = isSmartCutBoundary(before) && isSmartCutBoundary(after);
    const leadingHesitation = startChar === 0 && SMART_CUT_HESITATION_FILLERS.has(needle);
    if (!exactBoundaryMatch && !leadingHesitation) {
      searchFrom = matchIndex + needle.length;
      continue;
    }
    const range = sourceRangeForSubtitleChars(subtitle, startChar, endChar);
    if (rangeHasReliableTextCutTiming(range, subtitle)) {
      ranges.push({ start: range.start, end: range.end });
    }
    searchFrom = matchIndex + needle.length;
  }
  return ranges;
}

function sourceRangeForSubtitleChars(subtitle: JobManualEditSubtitle, startChar: number, endChar: number): TimedSourceRange {
  const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
  const chars = Array.from(text);
  const timedTokens = buildBackendAlignedTranscriptTokens(
    subtitle,
    [{ start: subtitle.start_time, end: subtitle.end_time }],
    { sourceIndex: subtitleSourceIndex(subtitle), tokenKeyScope: `range-${subtitle.index}` },
  ) ?? buildTimedTranscriptCharTokens(
    subtitle,
    text,
    [{ start: subtitle.start_time, end: subtitle.end_time }],
    { sourceIndex: subtitleSourceIndex(subtitle), tokenKeyScope: `range-${subtitle.index}` },
  );
  if (timedTokens?.length === chars.length) {
    const clampedStart = clamp(startChar, 0, chars.length);
    const clampedEnd = clamp(endChar, clampedStart, chars.length);
    const startToken = timedTokens[clampedStart];
    const endToken = timedTokens[clampedEnd - 1];
    if (startToken && endToken && endToken.end > startToken.start + 0.02) {
      return {
        start: Number(startToken.start.toFixed(3)),
        end: Number(endToken.end.toFixed(3)),
        timingSource: "word",
      };
    }
  }
  const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
  const clampedStart = clamp(startChar, 0, chars.length);
  const clampedEnd = clamp(endChar, clampedStart, chars.length);
  return {
    start: Number((subtitle.start_time + duration * (clampedStart / Math.max(1, chars.length))).toFixed(3)),
    end: Number((subtitle.start_time + duration * (clampedEnd / Math.max(1, chars.length))).toFixed(3)),
    timingSource: "estimated",
  };
}

function rangeCoversWholeSubtitle(range: KeepSegment, subtitle: JobManualEditSubtitle) {
  return range.start <= subtitle.start_time + 0.03 && range.end >= subtitle.end_time - 0.03;
}

function rangeHasReliableTextCutTiming(range: TimedSourceRange, subtitle: JobManualEditSubtitle) {
  return range.timingSource === "word" || range.timingSource === "alignment" || rangeCoversWholeSubtitle(range, subtitle);
}

function findRepeatedSpeechRangesInSubtitle(subtitle: JobManualEditSubtitle) {
  const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
  if (!text) return [];
  const ranges: KeepSegment[] = [];
  const repeatedMatches = text.matchAll(/([\u4e00-\u9fff]{1,3})([\s，,、]*)\1/g);
  for (const match of repeatedMatches) {
    const separator = match[2] || "";
    const keepFirst = match[1] || "";
    if (SMART_CUT_REPEAT_STOP_PHRASES.has(keepFirst) || SMART_CUT_REPEAT_PROTECTED_PATTERN.test(keepFirst)) continue;
    if (keepFirst.length <= 1 && !separator.trim() && !/[，,、]/.test(separator)) continue;
    const matchIndex = match.index ?? 0;
    const removeStartChar = Array.from(text.slice(0, matchIndex)).length + Array.from(keepFirst + separator).length;
    const removeEndChar = removeStartChar + Array.from(keepFirst).length;
    const range = sourceRangeForSubtitleChars(subtitle, removeStartChar, removeEndChar);
    if (range.end > range.start + 0.02 && rangeHasReliableTextCutTiming(range, subtitle)) {
      ranges.push({ start: range.start, end: range.end });
    }
  }
  const chars = Array.from(text);
  const seenPhraseRanges = new Set<string>();
  for (let phraseLength = Math.min(12, Math.floor(chars.length / 2)); phraseLength >= 4; phraseLength -= 1) {
    for (let startChar = 0; startChar + phraseLength * 2 <= chars.length; startChar += 1) {
      const phrase = chars.slice(startChar, startChar + phraseLength).join("");
      if (!/[\u4e00-\u9fff]{4,}/.test(phrase)) continue;
      if (SMART_CUT_REPEAT_PROTECTED_PATTERN.test(phrase)) continue;
      if (/^(这个|那个|然后|就是|因为|所以|但是|不过)/.test(phrase) && phrase.length <= 5) continue;
      let separatorEnd = startChar + phraseLength;
      while (separatorEnd < chars.length && /^[\s，,、。.!！?？;；:：啊呀呃额嗯哎唉嘛呢吧]*$/.test(chars[separatorEnd])) {
        separatorEnd += 1;
      }
      if (separatorEnd - (startChar + phraseLength) > 6) continue;
      const repeated = chars.slice(separatorEnd, separatorEnd + phraseLength).join("");
      if (repeated !== phrase) continue;
      if (SMART_CUT_REPEAT_STOP_PHRASES.has(phrase)) continue;
      const key = `${separatorEnd}:${separatorEnd + phraseLength}`;
      if (seenPhraseRanges.has(key)) continue;
      seenPhraseRanges.add(key);
      const range = sourceRangeForSubtitleChars(subtitle, separatorEnd, separatorEnd + phraseLength);
      if (
        range.end > range.start + 0.08
        && rangeHasReliableTextCutTiming(range, subtitle)
        && !sourceRangeOverlapsCutRanges(range.start, range.end, ranges)
      ) ranges.push({ start: range.start, end: range.end });
    }
  }
  return ranges;
}

function findRepeatedSpeechRangesAcrossSubtitles(subtitles: JobManualEditSubtitle[]) {
  const ranges: SmartCutRuleMatch[] = [];
  const sorted = sortedSubtitles(subtitles);
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    const previousChars = Array.from(subtitleTranscriptSourceText(previous) || subtitleText(previous));
    const currentChars = Array.from(subtitleTranscriptSourceText(current) || subtitleText(current));
    const maxLength = Math.min(12, previousChars.length, currentChars.length);
    for (let phraseLength = maxLength; phraseLength >= 4; phraseLength -= 1) {
      const phrase = previousChars.slice(previousChars.length - phraseLength).join("");
      if (!/[\u4e00-\u9fff]{4,}/.test(phrase)) continue;
      if (SMART_CUT_REPEAT_PROTECTED_PATTERN.test(phrase)) continue;
      if (smartCutMeaningfulText(phrase, []).length < 4) continue;
      const repeated = currentChars.slice(0, phraseLength).join("");
      if (repeated !== phrase) continue;
      const range = sourceRangeForSubtitleChars(current, 0, phraseLength);
      if (range.end > range.start + 0.08 && rangeHasReliableTextCutTiming(range, current)) {
        ranges.push({ start: range.start, end: range.end, kind: "repeated" });
      }
      break;
    }
  }
  return ranges;
}

function smartCutMeaningfulText(text: string, fillers: string[]) {
  let cleaned = text.trim();
  if (!cleaned) return "";
  for (const filler of fillers) {
    cleaned = cleaned.replace(new RegExp(escapeRegExp(filler), "g"), "");
  }
  cleaned = cleaned.replace(/[啊呀呃额嗯哎唉喔哦嘛呢吧哈\s,，、。.!！?？;；:：()[\]（）【】"'“”‘’]+/g, "");
  return cleaned;
}

function subtitleHasUsableWordTimings(subtitle: JobManualEditSubtitle) {
  if (!subtitleWordTimingsMatchSubtitleText(subtitle)) return false;
  return Boolean(subtitle.words?.some((word) => {
    const start = Number(word.start);
    const end = Number(word.end);
    return Number.isFinite(start) && Number.isFinite(end) && end > start;
  }));
}

function pauseRangeOverlapsMeaningfulSpeech(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  const overlappingSubtitles = subtitles.filter((subtitle) => {
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    return overlap > 0.08 && smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length >= 2;
  });
  if (!overlappingSubtitles.length) return false;

  const subtitlesWithWordTimings = overlappingSubtitles.filter(subtitleHasUsableWordTimings);
  if (subtitlesWithWordTimings.length) {
    return subtitlesWithWordTimings.some((subtitle) => (
      subtitle.words || []
    ).some((word) => {
      const start = Number(word.start);
      const end = Number(word.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
      const overlap = Math.min(range.end, end) - Math.max(range.start, start);
      return overlap > 0.06;
    }));
  }

  return true;
}

function meaningfulWordRangesForPause(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  const wordRanges: KeepSegment[] = [];
  for (const subtitle of subtitles) {
    if (!subtitleHasUsableWordTimings(subtitle)) continue;
    const subtitleOverlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    if (subtitleOverlap <= 0.08) continue;
    for (const word of subtitle.words || []) {
      if (!smartCutMeaningfulText(String(word.word || ""), fillers)) continue;
      const start = Number(word.start);
      const end = Number(word.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
      wordRanges.push({
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
      });
    }
  }
  return wordRanges.sort((left, right) => left.start - right.start || left.end - right.end);
}

function wordBoundedPauseRanges(range: SilenceRange, wordRanges: KeepSegment[]) {
  const ranges: KeepSegment[] = [];
  for (let index = 1; index < wordRanges.length; index += 1) {
    const previous = wordRanges[index - 1];
    const next = wordRanges[index];
    const start = Math.max(range.start, previous.end + SMART_CUT_WORD_BOUNDARY_GUARD_SEC);
    const end = Math.min(range.end, next.start - SMART_CUT_WORD_BOUNDARY_GUARD_SEC);
    if (end > start + 0.02) {
      ranges.push({
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
      });
    }
  }
  return ranges;
}

function speechSeparatedPauseRanges(range: SilenceRange, wordRanges: KeepSegment[]) {
  const ranges: KeepSegment[] = [];
  let cursor = range.start;
  for (const wordRange of wordRanges) {
    if (wordRange.end <= range.start + 0.001 || wordRange.start >= range.end - 0.001) continue;
    const end = Math.min(range.end, wordRange.start - SMART_CUT_WORD_BOUNDARY_GUARD_SEC);
    if (end > cursor + 0.02) {
      ranges.push({
        start: Number(cursor.toFixed(3)),
        end: Number(end.toFixed(3)),
      });
    }
    cursor = Math.max(cursor, wordRange.end + SMART_CUT_WORD_BOUNDARY_GUARD_SEC);
  }
  if (range.end > cursor + 0.02) {
    ranges.push({
      start: Number(cursor.toFixed(3)),
      end: Number(range.end.toFixed(3)),
    });
  }
  return ranges;
}

function pauseRangeOverlapsTimedSpeech(range: SilenceRange, wordRanges: KeepSegment[]) {
  return wordRanges.some((wordRange) => {
    const overlap = Math.min(range.end, wordRange.end) - Math.max(range.start, wordRange.start);
    return overlap > 0.03;
  });
}

function subtitleBoundedPauseRanges(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  const ranges: KeepSegment[] = [];
  const sorted = sortedSubtitles(subtitles).filter((subtitle) => (
    smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length >= 2
  ));
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const next = sorted[index];
    const start = Math.max(range.start, previous.end_time);
    const end = Math.min(range.end, next.start_time);
    if (end > start + 0.02) {
      ranges.push({
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
      });
    }
  }
  return ranges;
}

function rangeOverlapsSubtitleSpeech(range: KeepSegment, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  return subtitles.some((subtitle) => {
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    return overlap > 0.08 && smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length >= 2;
  });
}

function fallbackCuttablePauseRanges(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  const boundedRanges = subtitleBoundedPauseRanges(range, subtitles, fillers);
  if (boundedRanges.length) {
    return boundedRanges.filter((candidate) => !rangeOverlapsSubtitleSpeech(candidate, subtitles, fillers));
  }
  if (silenceRangeHasAudioEvidence(range) && rangeOverlapsUntrustedSubtitleSpeech(range, subtitles, fillers)) {
    return [];
  }
  if (
    silenceRangeHasAudioEvidence(range)
    && !audioRangeBroadlyOverlapsSubtitleSpeech(range, subtitles, fillers)
    && !audioRangeOverlapsProtectedVisualSubtitle(range, subtitles, fillers)
  ) {
    return [{ start: range.start, end: range.end }];
  }
  return pauseRangeOverlapsMeaningfulSpeech(range, subtitles, fillers) ? [] : [{ start: range.start, end: range.end }];
}

function rangeOverlapsUntrustedSubtitleSpeech(range: KeepSegment, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  return subtitles.some((subtitle) => {
    if (smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length < 2) return false;
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    if (overlap <= 0.08) return false;
    return !asrTimedSpeechRangesForSubtitle(subtitle).length;
  });
}

function audioRangeBroadlyOverlapsSubtitleSpeech(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  return subtitles.some((subtitle) => {
    if (smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length < 2) return false;
    const subtitleDuration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    return overlap > 0.08 && overlap / subtitleDuration >= 0.55;
  });
}

const SMART_CUT_VISUAL_SHOWCASE_TEXT_RE = /(看到|看一下|来看|镜头|画面|展示|演示|操作|实操|特写|细节|同框|对比|手电|刀|上手|打开|合上)/;

function audioRangeOverlapsProtectedVisualSubtitle(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  return subtitles.some((subtitle) => {
    const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
    if (!SMART_CUT_VISUAL_SHOWCASE_TEXT_RE.test(text)) return false;
    if (smartCutMeaningfulText(text, fillers).length < 2) return false;
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    return overlap > 0.08;
  });
}

function cuttablePauseRanges(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  const wordRanges = meaningfulWordRangesForPause(range, subtitles, fillers);
  if (wordRanges.length) {
    if (silenceRangeHasAsrEvidence(range)) return speechSeparatedPauseRanges(range, wordRanges);
    if (pauseRangeOverlapsTimedSpeech(range, wordRanges)) return [];
    return wordBoundedPauseRanges(range, wordRanges);
  }
  return fallbackCuttablePauseRanges(range, subtitles, fillers);
}

function pauseRangesCanCluster(
  left: KeepSegment,
  right: KeepSegment,
  subtitles: JobManualEditSubtitle[],
  fillers: string[],
  timedSpeechRanges = asrTimedSpeechRangesForSubtitles(subtitles),
) {
  const gapStart = Math.min(left.end, right.start);
  const gapEnd = Math.max(left.end, right.start);
  if (gapEnd <= gapStart + 0.001) return true;
  if (gapEnd - gapStart > SMART_CUT_PAUSE_CLUSTER_GAP_SEC) return false;
  const contextStart = Math.min(left.start, right.start);
  const contextEnd = Math.max(left.end, right.end);
  const hasRelevantTimedSpeech = timedSpeechRanges.some((range) => range.end > contextStart - 0.35 && range.start < contextEnd + 0.35);
  if (hasRelevantTimedSpeech) {
    return !timedSpeechRanges.some((range) => range.end > gapStart + 0.001 && range.start < gapEnd - 0.001);
  }
  return !smartCutMeaningfulText(subtitleTextForSourceRange({ start: gapStart, end: gapEnd }, subtitles), fillers);
}

function pauseRangesCanReviewGroup(
  left: KeepSegment,
  right: KeepSegment,
  subtitles: JobManualEditSubtitle[],
  fillers: string[],
) {
  const gapStart = Math.min(left.end, right.start);
  const gapEnd = Math.max(left.end, right.start);
  if (gapEnd <= gapStart + 0.001) return true;
  if (gapEnd - gapStart > SMART_CUT_PAUSE_REVIEW_GROUP_GAP_SEC) return false;
  if (Math.max(left.end, right.end) - Math.min(left.start, right.start) > SMART_CUT_PAUSE_REVIEW_GROUP_MAX_SPAN_SEC) return false;
  const text = subtitleTextForSourceRange({ start: gapStart, end: gapEnd }, subtitles);
  const meaningfulText = smartCutMeaningfulText(text, fillers);
  if (meaningfulText.length > SMART_CUT_PAUSE_REVIEW_GROUP_MAX_TEXT_CHARS) return false;
  if (/[。！？!?]/.test(text) && meaningfulText.length > 8) return false;
  return true;
}

function pauseGroupsForThreshold(
  candidates: SmartCutRuleMatch[],
  subtitles: JobManualEditSubtitle[],
  fillers: string[],
) {
  const sorted = candidates
    .filter((range) => range.end > range.start + 0.02)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const groups: SmartCutRuleMatch[][] = [];
  for (const candidate of sorted) {
    const previousGroup = groups[groups.length - 1];
    const previousRange = previousGroup?.[previousGroup.length - 1];
    if (previousGroup && previousRange && pauseRangesCanReviewGroup(previousRange, candidate, subtitles, fillers)) {
      previousGroup.push(candidate);
    } else {
      groups.push([candidate]);
    }
  }
  return groups;
}

function subtitleTextForSourceRange(range: KeepSegment, subtitles: JobManualEditSubtitle[]) {
  const fragments: string[] = [];
  for (const subtitle of subtitles) {
    const overlapStart = Math.max(range.start, subtitle.start_time);
    const overlapEnd = Math.min(range.end, subtitle.end_time);
    if (overlapEnd <= overlapStart + 0.015) continue;
    const text = subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle);
    const chars = Array.from(text);
    if (!chars.length) continue;
    const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
    const startChar = clamp(Math.floor(((overlapStart - subtitle.start_time) / duration) * chars.length), 0, chars.length);
    const endChar = clamp(Math.ceil(((overlapEnd - subtitle.start_time) / duration) * chars.length), startChar + 1, chars.length);
    const fragment = chars.slice(startChar, endChar).join("").trim();
    if (fragment) fragments.push(fragment);
  }
  return fragments.join("");
}

function smartDeleteRangeContainsProtectedTerm(range: SmartCutRuleMatch, subtitles: JobManualEditSubtitle[]) {
  const text = [
    subtitleTextForSourceRange(range, subtitles),
    range.sourceText || "",
    range.detail || "",
    range.reason || "",
  ].join(" ");
  return SMART_DELETE_PROTECTED_TERM_PATTERN.test(text);
}

function smartDeleteRuleRanges(smartDeleteSegments: JobManualEditSmartDelete[] = [], subtitles: JobManualEditSubtitle[] = []): SmartCutRuleMatch[] {
  return smartDeleteSegments
    .map((segment) => {
      const range = {
        start: Number(segment.start.toFixed(3)),
        end: Number(segment.end.toFixed(3)),
        kind: "smart_delete" as const,
        reason: segment.reason,
        detail: segment.detail,
        sourceText: segment.evidence?.find((item) => item.trim()) || segment.detail || segment.reason,
      };
      return {
        ...range,
        protected: smartDeleteRangeContainsProtectedTerm(range, subtitles),
      };
    })
    .filter((range) => range.end > range.start + 0.02);
}

export function buildSmartCutRuleAnalysis(
  subtitles: JobManualEditSubtitle[],
  rules: SmartCutRules,
  silenceRanges: SilenceRange[] = [],
  smartDeleteSegments: JobManualEditSmartDelete[] = [],
): SmartCutRuleAnalysis {
  const analysis: SmartCutRuleAnalysis = {
    filler: [],
    repeated: [],
    pause: [],
    pauseCandidates: [],
    smartDelete: smartDeleteRuleRanges(smartDeleteSegments, subtitles),
  };
  const fillers = parseSmartCutFillers(rules.fillers);
  for (const subtitle of subtitles) {
    for (const filler of fillers) {
      analysis.filler.push(...findTextRangesInSubtitle(subtitle, filler).map((range) => ({ ...range, kind: "filler" as const })));
    }
    analysis.repeated.push(...findRepeatedSpeechRangesInSubtitle(subtitle).map((range) => ({ ...range, kind: "repeated" as const })));
  }
  analysis.repeated.push(...findRepeatedSpeechRangesAcrossSubtitles(subtitles));
  const pauseCandidates: SmartCutRuleMatch[] = [];
  for (const range of silenceRanges) {
    for (const cuttableRange of cuttablePauseRanges(range, subtitles, fillers)) {
      if (rangeOverlapsUntrustedSubtitleSpeech(cuttableRange, subtitles, fillers)) continue;
      const pauseMatch = {
        start: Number(cuttableRange.start.toFixed(3)),
        end: Number(cuttableRange.end.toFixed(3)),
        kind: "pause" as const,
      };
      pauseCandidates.push(pauseMatch);
    }
  }
  analysis.pauseCandidates = pauseCandidates;
  for (const group of pauseGroupsForThreshold(pauseCandidates, subtitles, fillers)) {
    const pauseDuration = group.reduce((total, range) => total + Math.max(0, range.end - range.start), 0);
    if (pauseDuration >= rules.pauseThresholdSec) {
      analysis.pause.push(...group);
    }
  }
  return {
    filler: analysis.filler.filter((range) => range.end > range.start + 0.02),
    repeated: analysis.repeated.filter((range) => range.end > range.start + 0.02),
    pause: analysis.pause.filter((range) => range.end > range.start + 0.02),
    pauseCandidates: analysis.pauseCandidates.filter((range) => range.end > range.start + 0.02),
    smartDelete: analysis.smartDelete,
  };
}

function textSnippet(value: string, maxChars = 18) {
  const text = value.replace(/\s+/g, " ").trim();
  const chars = Array.from(text);
  if (chars.length <= maxChars) return text;
  return `${chars.slice(0, maxChars).join("")}...`;
}

function subtitleSnippetForSourceRange(range: KeepSegment, subtitles: JobManualEditSubtitle[]) {
  return textSnippet(subtitleTextForSourceRange(range, subtitles));
}

function sampleTextForSmartCutRange(kind: SmartCutRuleKind, range: SmartCutRuleMatch | undefined, subtitles: JobManualEditSubtitle[]) {
  if (!range) {
    switch (kind) {
      case "filler":
        return "嗯";
      case "repeated":
        return "这个这个";
      case "pause":
        return "[1.0s]";
      case "smart_delete":
        return "重说片段";
      default:
        return "待剪内容";
    }
  }
  if (kind === "pause") return `[${(range.end - range.start).toFixed(1)}s]`;
  return subtitleSnippetForSourceRange(range, subtitles) || textSnippet(range.sourceText || smartDeleteReasonLabel(range.detail || range.reason));
}

function previewMatchForSmartCutRule(kind: SmartCutRuleKind, matches: SmartCutRuleMatch[]) {
  const eligibleMatches = matches.filter((match) => !match.protected);
  if (!eligibleMatches.length) return undefined;
  if (kind === "pause" || kind === "smart_delete") {
    return [...eligibleMatches].sort((left, right) => (right.end - right.start) - (left.end - left.start))[0];
  }
  return eligibleMatches[0];
}

export function buildSmartCutRulePreviews(
  analysis: SmartCutRuleAnalysis,
  rules: SmartCutRules,
  subtitles: JobManualEditSubtitle[],
): SmartCutRulePreview[] {
  const configs: Array<{ kind: SmartCutRuleKind; enabled: boolean; matches: SmartCutRuleMatch[] }> = [
    { kind: "filler", enabled: rules.fillerEnabled, matches: analysis.filler },
    { kind: "repeated", enabled: rules.repeatedEnabled, matches: analysis.repeated },
    { kind: "pause", enabled: rules.pauseEnabled, matches: analysis.pause },
    { kind: "smart_delete", enabled: rules.smartDeleteEnabled, matches: analysis.smartDelete },
  ];
  return configs.map(({ kind, enabled, matches }) => {
    const sample = previewMatchForSmartCutRule(kind, matches);
    const activeCount = matches.filter((match) => !match.protected).length;
    return {
      kind,
      label: smartCutRuleLabel(kind),
      reason: smartCutRuleReason(kind, sample),
      count: activeCount,
      enabled,
      sampleText: sampleTextForSmartCutRange(kind, sample, subtitles),
      sampleMeta: sample ? `${formatSeconds(sample.start)} - ${formatSeconds(sample.end)}` : "暂无命中，显示样式示范",
    };
  });
}

export function autoSmartCutRuleRanges(analysis: SmartCutRuleAnalysis, rules: SmartCutRules) {
  return [
    ...(rules.fillerEnabled ? analysis.filler : []),
    ...(rules.repeatedEnabled ? analysis.repeated : []),
    ...(rules.pauseEnabled ? analysis.pause : []),
  ];
}

export function blockAutoSmartCutRangesForSmartDeleteReview(
  autoRanges: SmartCutRuleMatch[],
  smartDeleteRanges: SmartCutRuleMatch[],
  rules: SmartCutRules,
  confirmedRanges: KeepSegment[] = [],
) {
  if (!rules.smartDeleteEnabled || !smartDeleteRanges.length || !autoRanges.length) return autoRanges;
  const reviewBlocks = smartDeleteRanges.filter((range) => (
    !range.protected
    && !sourceRangeOverlapsCutRanges(range.start, range.end, confirmedRanges)
  ));
  if (!reviewBlocks.length) return autoRanges;
  return autoRanges.filter((range) => (
    !sourceRangeOverlapsCutRanges(range.start, range.end, reviewBlocks)
  ));
}

export function smartDeleteSuggestionRanges(
  analysis: SmartCutRuleAnalysis,
  rules: SmartCutRules,
  dismissedRanges: KeepSegment[] = [],
) {
  if (!rules.smartDeleteEnabled) return [];
  return analysis.smartDelete.filter((range) => (
    !range.protected
    && !sourceRangeOverlapsCutRanges(range.start, range.end, dismissedRanges)
  ));
}

export function smartCutRuleManagedRanges(analysis: SmartCutRuleAnalysis) {
  return [
    ...analysis.filler,
    ...analysis.repeated,
    ...analysis.pause,
    ...analysis.pauseCandidates,
    ...analysis.smartDelete,
  ];
}

function smartCutSafetyPadding(kind: SmartCutRuleKind | undefined, rules?: Partial<SmartCutRules>) {
  if (kind === "pause") {
    return normalizeSmartCutRules(rules).pauseBreathSec ?? DEFAULT_SMART_CUT_RULES.pauseBreathSec ?? 0;
  }
  return kind ? SMART_CUT_AUDIO_SAFETY_SEC[kind] ?? 0 : 0;
}

function applyAutomaticCutSafetyPadding(ranges: KeepSegment[], sourceDuration: number, rules?: Partial<SmartCutRules>) {
  return ranges
    .map((range) => {
      const kind = (range as SmartCutRuleMatch).kind;
      const padding = smartCutSafetyPadding(kind, rules);
      const start = Number(clamp(range.start + padding, 0, sourceDuration).toFixed(3));
      const end = Number(clamp(range.end - padding, start, sourceDuration).toFixed(3));
      return { ...range, start, end };
    })
    .filter((range) => range.end > range.start + 0.02);
}

function protectPauseCutRangesFromSpeech(ranges: Array<KeepSegment | SmartCutRuleMatch>, protectedSpeechRanges: KeepSegment[], sourceDuration: number) {
  if (!protectedSpeechRanges.length) return ranges;
  const blockers = protectedSpeechRanges
    .map((range) => ({
      start: Number(clamp(range.start - 0.03, 0, sourceDuration).toFixed(3)),
      end: Number(clamp(range.end + 0.03, 0, sourceDuration).toFixed(3)),
    }))
    .filter((range) => range.end > range.start + 0.02);
  if (!blockers.length) return ranges;
  return ranges.flatMap((range) => {
    if ((range as SmartCutRuleMatch).kind !== "pause") return [range];
    return removeSourceRangesFromSegments([{ start: range.start, end: range.end }], blockers)
      .map((piece) => ({ ...range, start: piece.start, end: piece.end }));
  });
}

export function applySmartCutRuleRangesToSegments(
  baseSegments: KeepSegment[],
  ranges: Array<KeepSegment | SmartCutRuleMatch>,
  managedRanges: Array<KeepSegment | SmartCutRuleMatch>,
  sourceDuration: number,
  restoredRanges: KeepSegment[] = [],
  rules?: Partial<SmartCutRules>,
  protectedSpeechRanges: KeepSegment[] = [],
) {
  if (!baseSegments.length) return [];
  const controlledBaseline = managedRanges.length
    ? addSourceRangesToSegments(baseSegments, managedRanges, sourceDuration)
    : baseSegments;
  const activeRanges = restoredRanges.length
    ? removeSourceRangesFromSegments(ranges, restoredRanges)
    : ranges;
  const speechSafeRanges = protectPauseCutRangesFromSpeech(activeRanges, protectedSpeechRanges, sourceDuration);
  const paddedRanges = applyAutomaticCutSafetyPadding(speechSafeRanges, sourceDuration, rules);
  const keptRanges = paddedRanges.filter((range) => isSourceRangeKept(range.start, range.end, controlledBaseline));
  return keptRanges.length
    ? removeSourceRangesFromSegments(controlledBaseline, keptRanges)
    : controlledBaseline;
}

function smartCutRulesSignature(rules: SmartCutRules) {
  const normalized = normalizeSmartCutRules(rules);
  return JSON.stringify({
    fillerEnabled: normalized.fillerEnabled,
    repeatedEnabled: normalized.repeatedEnabled,
    pauseEnabled: normalized.pauseEnabled,
    smartDeleteEnabled: normalized.smartDeleteEnabled,
    pauseThresholdSec: normalized.pauseThresholdSec,
    pauseBreathSec: normalized.pauseBreathSec,
    fillers: parseSmartCutFillers(normalized.fillers),
  });
}

function cloneSubtitleDrafts(drafts: Record<number, SubtitleDraft>) {
  return Object.fromEntries(
    Object.entries(drafts).map(([index, draft]) => [Number(index), { ...draft }]),
  ) as Record<number, SubtitleDraft>;
}

function cloneUndoSnapshot(snapshot: ManualEditUndoSnapshot): ManualEditUndoSnapshot {
  return {
    ...snapshot,
    segments: snapshot.segments.map((segment) => ({ ...segment })),
    subtitleDrafts: cloneSubtitleDrafts(snapshot.subtitleDrafts),
    subtitleReplacementHistory: snapshot.subtitleReplacementHistory.map((item) => ({ ...item })),
    manualSmartCutRestoreRanges: snapshot.manualSmartCutRestoreRanges.map((range) => ({ ...range })),
    manualSmartCutConfirmRanges: snapshot.manualSmartCutConfirmRanges.map((range) => ({ ...range })),
    manualSmartCutDismissRanges: snapshot.manualSmartCutDismissRanges.map((range) => ({ ...range })),
    videoTransform: { ...snapshot.videoTransform },
  };
}

export function JobManualEditSection({ job, session, previewAssets, saving, autosaving = false, autosavedAt, detectingRotation = false, resetSignal = 0, renderActionLabel = "根据当前改动重新渲染", onStateChange, onApply, onAutoSave, onDetectRotation }: JobManualEditSectionProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const previewAudioContextRef = useRef<AudioContext | null>(null);
  const previewAudioSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const previewGainRef = useRef<GainNode | null>(null);
  const previewCompressorRef = useRef<DynamicsCompressorNode | null>(null);
  const previewDockRef = useRef<HTMLDivElement | null>(null);
  const currentSubtitleInputRef = useRef<HTMLInputElement | null>(null);
  const subtitleListRef = useRef<HTMLDivElement | null>(null);
  const subtitleChipRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const transcriptTokenRefs = useRef<Map<number, HTMLElement>>(new Map());
  const waveformRef = useRef<HTMLDivElement | null>(null);
  const waveformTimelineRef = useRef<HTMLDivElement | null>(null);
  const unifiedTimelineRef = useRef<HTMLDivElement | null>(null);
  const waveSurferRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPluginInstance | null>(null);
  const syncingRegionsRef = useRef(false);
  const timelinePlaybackRef = useRef(false);
  const previewClockFrameRef = useRef<number | null>(null);
  const pendingPreviewSeekRef = useRef<number | null>(null);
  const outputPlaybackSeekTimeoutRef = useRef<number | null>(null);
  const outputPlaybackSeekInProgressRef = useRef(false);
  const lastUserPreviewSeekSourceTimeRef = useRef<number | null>(null);
  const lastSyncedPreviewSourceTimeRef = useRef(-1);
  const floatingPreviewDragRef = useRef<{
    pointerId: number;
    offsetX: number;
    offsetY: number;
    width: number;
    height: number;
  } | null>(null);
  const autoSaveSessionKeyRef = useRef("");
  const lastAutoSaveSignatureRef = useRef("");
  const lastAutoSmartCutSignatureRef = useRef("");
  const lastSelectedSubtitleTextRef = useRef("");
  const resumeAfterSubtitleEditRef = useRef(false);
  const currentEditSnapshotRef = useRef<ManualEditUndoSnapshot | null>(null);
  const undoStackRef = useRef<ManualEditUndoSnapshot[]>([]);
  const [segments, setSegments] = useState<KeepSegment[]>([]);
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(0);
  const [editorNote, setEditorNote] = useState("");
  const [videoSummary, setVideoSummary] = useState("");
  const [currentSourceTime, setCurrentSourceTime] = useState(0);
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false);
  const [previewPlaybackMode, setPreviewPlaybackMode] = useState<PreviewPlaybackMode>(null);
  const [previewVideoLoadError, setPreviewVideoLoadError] = useState<string | null>(null);
  const [previewVideoLoading, setPreviewVideoLoading] = useState(false);
  const [previewVideoLoadingLabel, setPreviewVideoLoadingLabel] = useState("正在载入视频");
  const [previewVideoLoadProgress, setPreviewVideoLoadProgress] = useState<number | null>(null);
  const [previewVolume, setPreviewVolume] = useState(1);
  const [previewMuted, setPreviewMuted] = useState(false);
  const [previewAutoVolumeEnabled, setPreviewAutoVolumeEnabled] = useState(true);
  const [selectedSubtitleIndex, setSelectedSubtitleIndex] = useState<number | null>(null);
  const [editingSubtitleIndex, setEditingSubtitleIndex] = useState<number | null>(null);
  const [currentSubtitleDraftText, setCurrentSubtitleDraftText] = useState("");
  const [subtitleDrafts, setSubtitleDrafts] = useState<Record<number, SubtitleDraft>>({});
  const [batchShiftMs, setBatchShiftMs] = useState(100);
  const [waveformZoom, setWaveformZoom] = useState(INITIAL_WAVEFORM_ZOOM);
  const [waveformReady, setWaveformReady] = useState(false);
  const [waveformError, setWaveformError] = useState<string | null>(null);
  const [timelineHoverSourceTime, setTimelineHoverSourceTime] = useState<number | null>(null);
  const [termReviewFilter, setTermReviewFilter] = useState("");
  const [minTermCount, setMinTermCount] = useState(2);
  const [manualTermDraft, setManualTermDraft] = useState("");
  const [manualReplacementDraft, setManualReplacementDraft] = useState("");
  const [manualTermKeys, setManualTermKeys] = useState<string[]>([]);
  const [termReplacementDrafts, setTermReplacementDrafts] = useState<Record<string, string>>({});
  const [hiddenTermKeys, setHiddenTermKeys] = useState<Set<string>>(() => new Set());
  const [subtitleReplaceDialog, setSubtitleReplaceDialog] = useState<SubtitleReplaceDialogState | null>(null);
  const [subtitleReplacementHistory, setSubtitleReplacementHistory] = useState<JobManualSubtitleReplacement[]>([]);
  const [transcriptSelection, setTranscriptSelection] = useState<TranscriptSelection | null>(null);
  const [transcriptSelectionPopover, setTranscriptSelectionPopover] = useState<TranscriptSelectionPopoverPosition | null>(null);
  const [transcriptReplacementDraft, setTranscriptReplacementDraft] = useState("");
  const [smartCutRulesExpanded, setSmartCutRulesExpanded] = useState(false);
  const [smartCutRules, setSmartCutRules] = useState<SmartCutRules>(() => loadSmartCutRules());
  const [manualSmartCutRestoreRanges, setManualSmartCutRestoreRanges] = useState<KeepSegment[]>([]);
  const [manualSmartCutConfirmRanges, setManualSmartCutConfirmRanges] = useState<KeepSegment[]>([]);
  const [manualSmartCutDismissRanges, setManualSmartCutDismissRanges] = useState<KeepSegment[]>([]);
  const [videoTransform, setVideoTransform] = useState<JobManualVideoTransform>(() => normalizeVideoTransform(null));
  const [rotationDialogOpen, setRotationDialogOpen] = useState(false);
  const [rotationDraft, setRotationDraft] = useState(0);
  const [rotationDetectMessage, setRotationDetectMessage] = useState<string | null>(null);
  const [resolutionDialogOpen, setResolutionDialogOpen] = useState(false);
  const [resolutionDraft, setResolutionDraft] = useState<JobManualVideoTransform>(() => normalizeVideoTransform(null));
  const [sourceVideoSize, setSourceVideoSize] = useState<{ width: number; height: number } | null>(null);
  const [isPreviewFloating, setIsPreviewFloating] = useState(false);
  const [previewDockHeight, setPreviewDockHeight] = useState<number | null>(null);
  const [previewFrameHeight, setPreviewFrameHeight] = useState<number | null>(null);
  const [floatingPreviewPosition, setFloatingPreviewPosition] = useState<FloatingPreviewPosition | null>(null);
  const [frequentTerms, setFrequentTerms] = useState<FrequentTerm[]>([]);

  const buildUndoSnapshot = (): ManualEditUndoSnapshot => ({
    segments: segments.map((segment) => ({ ...segment })),
    selectedSegmentIndex,
    selectedSubtitleIndex,
    editingSubtitleIndex,
    currentSubtitleDraftText,
    subtitleDrafts: cloneSubtitleDrafts(subtitleDrafts),
    subtitleReplacementHistory: subtitleReplacementHistory.map((item) => ({ ...item })),
    manualSmartCutRestoreRanges: manualSmartCutRestoreRanges.map((range) => ({ ...range })),
    manualSmartCutConfirmRanges: manualSmartCutConfirmRanges.map((range) => ({ ...range })),
    manualSmartCutDismissRanges: manualSmartCutDismissRanges.map((range) => ({ ...range })),
    editorNote,
    videoSummary,
    videoTransform: { ...normalizeVideoTransform(videoTransform) },
  });

  const recordUndoSnapshot = () => {
    const snapshot = currentEditSnapshotRef.current ? cloneUndoSnapshot(currentEditSnapshotRef.current) : buildUndoSnapshot();
    const stack = undoStackRef.current;
    const snapshotSignature = JSON.stringify(snapshot);
    if (stack.length && JSON.stringify(stack[stack.length - 1]) === snapshotSignature) return;
    stack.push(snapshot);
    if (stack.length > 80) stack.shift();
  };

  const undoLastEdit = () => {
    const snapshot = undoStackRef.current.pop();
    if (!snapshot) return false;
    const restored = cloneUndoSnapshot(snapshot);
    pauseEditedTimeline();
    setSegments(restored.segments);
    setSelectedSegmentIndex(restored.selectedSegmentIndex);
    setSelectedSubtitleIndex(restored.selectedSubtitleIndex);
    setEditingSubtitleIndex(null);
    setCurrentSubtitleDraftText("");
    setSubtitleDrafts(restored.subtitleDrafts);
    setSubtitleReplacementHistory(restored.subtitleReplacementHistory.map((item) => ({ ...item })));
    setManualSmartCutRestoreRanges(restored.manualSmartCutRestoreRanges.map((range) => ({ ...range })));
    setManualSmartCutConfirmRanges(restored.manualSmartCutConfirmRanges.map((range) => ({ ...range })));
    setManualSmartCutDismissRanges(restored.manualSmartCutDismissRanges.map((range) => ({ ...range })));
    setEditorNote(restored.editorNote);
    setVideoSummary(restored.videoSummary);
    setVideoTransform(restored.videoTransform);
    setRotationDraft(restored.videoTransform.rotation_cw);
    setResolutionDraft(restored.videoTransform);
    setRotationDialogOpen(false);
    setResolutionDialogOpen(false);
    resumeAfterSubtitleEditRef.current = false;
    return true;
  };

  useEffect(() => {
    undoStackRef.current = [];
    setSegments(session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end })));
    setSelectedSegmentIndex(0);
    setSelectedSubtitleIndex(null);
    setEditingSubtitleIndex(null);
    setCurrentSubtitleDraftText("");
    setSubtitleDrafts(
      Object.fromEntries(
        (session.subtitle_overrides || []).map((override) => [
          override.index,
          {
            start_time: override.start_time,
            end_time: override.end_time,
            text_final: override.text_final,
            delete: override.delete,
          },
        ]),
      ),
    );
    lastSelectedSubtitleTextRef.current = "";
    setSubtitleReplaceDialog(null);
    setSubtitleReplacementHistory([]);
    setTranscriptSelection(null);
    setTranscriptSelectionPopover(null);
    setTranscriptReplacementDraft("");
    setSmartCutRules(loadSmartCutRules());
    setManualSmartCutRestoreRanges([]);
    setManualSmartCutConfirmRanges([]);
    setManualSmartCutDismissRanges([]);
    lastAutoSmartCutSignatureRef.current = "";
    setManualTermDraft("");
    setManualReplacementDraft("");
    setManualTermKeys([]);
    setEditorNote("");
    setVideoSummary(session.video_summary || "");
    setCurrentSourceTime(0);
    setPreviewPlaybackMode(null);
    pendingPreviewSeekRef.current = null;
    setWaveformReady(false);
    setWaveformError(null);
    setTermReviewFilter("");
    setTermReplacementDrafts({});
    setHiddenTermKeys(new Set());
    const nextTransform = normalizeVideoTransform(session.video_transform);
    setVideoTransform(nextTransform);
    setRotationDraft(nextTransform.rotation_cw);
    setResolutionDraft(nextTransform);
    setRotationDialogOpen(false);
    setResolutionDialogOpen(false);
    setRotationDetectMessage(null);
    timelinePlaybackRef.current = false;
    resumeAfterSubtitleEditRef.current = false;
  }, [session.job_id, session.timeline_id, session.timeline_version, session.keep_segments, session.subtitle_overrides, session.video_transform, session.video_summary]);

  useEffect(() => {
    currentEditSnapshotRef.current = buildUndoSnapshot();
  }, [currentSubtitleDraftText, editorNote, editingSubtitleIndex, manualSmartCutConfirmRanges, manualSmartCutDismissRanges, manualSmartCutRestoreRanges, segments, selectedSegmentIndex, selectedSubtitleIndex, subtitleDrafts, subtitleReplacementHistory, videoSummary, videoTransform]);

  const effectiveSegments = useMemo(
    () => segments.filter((segment) => segment.end > segment.start + 0.05),
    [segments],
  );

  const baseProjection = useMemo(
    () => {
      const sessionKeepSegments = session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end }));
      const sourceFallbackProjection = session.source_subtitles.length
        ? (() => {
            const fallback = remapSubtitles(session.source_subtitles, effectiveSegments);
            return { ...fallback, remapped: splitLongSubtitleDisplayRows(fallback.remapped) };
          })()
        : null;
      const useSourceFallbackWhenProjectionMissesSpeech = (candidate: { remapped: JobManualEditSubtitle[]; ranges: OutputRange[] }) => {
        if (!sourceFallbackProjection) return false;
        if (projectedSubtitlesHaveDuplicateSourceOverlap(candidate.remapped)) return true;
        const candidateOnSourceTimeline = projectedSubtitlesForTranscript(candidate.remapped, candidate.ranges);
        return projectedTranscriptMissesKeptSpeech(candidateOnSourceTimeline, session.source_subtitles, effectiveSegments);
      };
      if (
        session.projected_subtitles.length
        && keepSegmentsEquivalent(effectiveSegments, sessionKeepSegments)
      ) {
        const { ranges, totalDuration } = buildOutputRanges(effectiveSegments);
        const candidate = {
          ranges,
          totalDuration,
          remapped: sortedSubtitles(session.projected_subtitles),
        };
        return useSourceFallbackWhenProjectionMissesSpeech(candidate) ? sourceFallbackProjection! : candidate;
      }
      if (session.projected_subtitles.length) {
        const candidate = remapProjectedSubtitlesFromBaseTimeline(
          session.projected_subtitles,
          sessionKeepSegments,
          effectiveSegments,
        );
        return useSourceFallbackWhenProjectionMissesSpeech(candidate) ? sourceFallbackProjection! : candidate;
      }
      return sourceFallbackProjection ?? remapSubtitles(session.projected_subtitles, effectiveSegments);
    },
    [session.keep_segments, session.projected_subtitles, session.source_subtitles, effectiveSegments],
  );

  const projection = useMemo(
    () => ({
      ...baseProjection,
      remapped: normalizeAdjacentSubtitleTextOverlaps(applySubtitleDrafts(baseProjection.remapped, subtitleDrafts)),
    }),
    [baseProjection, subtitleDrafts],
  );
  const sourceTranscriptSubtitles = useMemo(() => {
    const projectedBaseline = buildSourceTranscriptProjectedBaseline(session, subtitleDrafts);
    return buildSourceTranscriptSubtitlesForTimeline(session, projectedBaseline, subtitleDrafts, subtitleReplacementHistory);
  }, [session.keep_segments, session.projected_subtitles, session.source_subtitles, subtitleDrafts, subtitleReplacementHistory]);
  const sourceTranscriptTimingRows = useMemo(
    () => {
      const projectedBaseline = buildSourceTranscriptProjectedBaseline(session, subtitleDrafts);
      return buildSourceTranscriptRowsForTimeline(session, subtitleDrafts, subtitleReplacementHistory, projectedBaseline);
    },
    [session.projected_subtitles, session.source_subtitles, subtitleDrafts, subtitleReplacementHistory],
  );
  const sourceSpeechProtectionRanges = useMemo(
    () => asrTimedSpeechRangesForSubtitles(sourceTranscriptSubtitles),
    [sourceTranscriptSubtitles],
  );
  const sourceTranscriptDisplaySilenceRanges = useMemo(() => {
    const audioSilences = previewAssets?.silence_intervals?.length
      ? previewAssets.silence_intervals
      : session.silence_segments || [];
    const inferredPauses = [
      ...subtitlePauseIntervals(sourceTranscriptSubtitles),
      ...wordTimingPauseIntervals(sourceTranscriptTimingRows),
    ];
    const audioBackedInferredPauses = intersectInferredPausesWithAudioSilence(inferredPauses, audioSilences);
    const standaloneAudioSilences = audioSilences.filter(
      (silence) => !audioBackedInferredPauses.some((pause) => silenceRangesOverlap(silence, pause)),
    );
    return normalizeSilenceRanges(
      [
        ...audioBackedInferredPauses,
        ...standaloneAudioSilences,
      ],
      session.source_duration_sec,
    );
  }, [
    previewAssets?.silence_intervals,
    session.silence_segments,
    session.source_duration_sec,
    sourceTranscriptSubtitles,
    sourceTranscriptTimingRows,
  ]);
  const sourceSilenceRanges = useMemo(() => {
    return normalizeReviewPauseRanges(sourceTranscriptDisplaySilenceRanges, sourceTranscriptSubtitles, {
      fillers: parseSmartCutFillers(smartCutRules.fillers),
    });
  }, [
    smartCutRules.fillers,
    sourceTranscriptDisplaySilenceRanges,
    sourceTranscriptSubtitles,
  ]);
  const transcriptTokens = useMemo(
    () => buildTranscriptTokens(sourceTranscriptSubtitles, effectiveSegments, sourceTranscriptDisplaySilenceRanges),
    [effectiveSegments, sourceTranscriptDisplaySilenceRanges, sourceTranscriptSubtitles],
  );
  const transcriptCutRanges = useMemo(
    () => sourceCutRangesFromKeepSegments(effectiveSegments, session.source_duration_sec),
    [effectiveSegments, session.source_duration_sec],
  );
  const transcriptCharCount = useMemo(
    () => transcriptTokens.filter((token) => token.kind === "char").length,
    [transcriptTokens],
  );
  const transcriptPauseCount = useMemo(
    () => transcriptTokens.filter((token) => token.kind === "pause").length,
    [transcriptTokens],
  );

  const currentOutputTime = useMemo(
    () => sourceTimeToOutputTime(currentSourceTime, projection.ranges),
    [currentSourceTime, projection.ranges],
  );
  const activePreviewOutputTime = useMemo(
    () => sourceTimeToActiveOutputTime(currentSourceTime, projection.ranges),
    [currentSourceTime, projection.ranges],
  );
  const activeTranscriptTokenIndex = useMemo(
    () => transcriptTokens.findIndex((token) => (
      token.kind === "pause"
        ? transcriptPauseRangesForToken(token).some((range) => currentSourceTime >= range.start - 0.015 && currentSourceTime <= range.end + 0.015)
        : currentSourceTime >= token.start - 0.015 && currentSourceTime <= token.end + 0.015
    )),
    [currentSourceTime, transcriptTokens],
  );

  const baseKeepSegments = session.base_keep_segments?.length ? session.base_keep_segments : session.keep_segments;
  const activeSubtitleIndex = useMemo(
    () => {
      if (activePreviewOutputTime == null) return -1;
      return projection.remapped.findIndex((item) => activePreviewOutputTime >= item.start_time && activePreviewOutputTime <= item.end_time + 0.02);
    },
    [activePreviewOutputTime, projection.remapped],
  );

  const smartCutRuleAnalysis = useMemo(
    () => buildSmartCutRuleAnalysis(sourceTranscriptSubtitles, smartCutRules, sourceSilenceRanges, session.smart_delete_segments || []),
    [smartCutRules, sourceSilenceRanges, sourceTranscriptSubtitles, session.smart_delete_segments],
  );
  const smartCutRuleRanges = useMemo(
    () => {
      const confirmedSmartDeleteRanges = smartCutRules.smartDeleteEnabled
        ? manualSmartCutConfirmRanges.map((range) => ({ ...range, kind: "smart_delete" as const }))
        : [];
      return confirmedSmartDeleteRanges;
    },
    [manualSmartCutConfirmRanges, smartCutRules.smartDeleteEnabled],
  );
  const smartCutManagedRanges = useMemo(
    () => smartCutRuleManagedRanges(smartCutRuleAnalysis),
    [smartCutRuleAnalysis],
  );
  const pendingSmartDeleteRanges = useMemo(
    () => smartDeleteSuggestionRanges(
      smartCutRuleAnalysis,
      smartCutRules,
      [...manualSmartCutDismissRanges, ...manualSmartCutConfirmRanges],
    ),
    [manualSmartCutConfirmRanges, manualSmartCutDismissRanges, smartCutRuleAnalysis, smartCutRules],
  );
  const activeSmartCutRuleRanges = useMemo(
    () => (manualSmartCutRestoreRanges.length
      ? smartCutRuleRanges.filter((range) => !sourceRangeOverlapsCutRanges(range.start, range.end, manualSmartCutRestoreRanges))
      : smartCutRuleRanges),
    [manualSmartCutRestoreRanges, smartCutRuleRanges],
  );
  const smartCutRuleCounts = useMemo(
    () => ({
      filler: smartCutRules.fillerEnabled ? smartCutRuleAnalysis.filler.filter((range) => !range.protected).length : 0,
      repeated: smartCutRules.repeatedEnabled ? smartCutRuleAnalysis.repeated.filter((range) => !range.protected).length : 0,
      pause: smartCutRules.pauseEnabled ? smartCutRuleAnalysis.pause.filter((range) => !range.protected).length : 0,
      smartDelete: pendingSmartDeleteRanges.length,
    }),
    [pendingSmartDeleteRanges.length, smartCutRuleAnalysis, smartCutRules],
  );
  const smartCutRulePreviews = useMemo(
    () => buildSmartCutRulePreviews(smartCutRuleAnalysis, smartCutRules, sourceTranscriptSubtitles),
    [smartCutRuleAnalysis, smartCutRules, sourceTranscriptSubtitles],
  );
  const activeSmartCutRuleRangeCount = smartCutRuleCounts.filler + smartCutRuleCounts.repeated + smartCutRuleCounts.pause;
  const pendingSmartDeleteRangeCount = pendingSmartDeleteRanges.length;

  const totalOutputDuration = projection.totalDuration;
  const activeSubtitle = activeSubtitleIndex >= 0 ? projection.remapped[activeSubtitleIndex] : null;
  const visibleSubtitles = useMemo(
    () => buildVisibleSubtitleRows(
      projection.remapped,
      baseProjection,
      subtitleDrafts,
      session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end })),
      session.projected_subtitles,
    ),
    [baseProjection, projection.remapped, session.keep_segments, session.projected_subtitles, subtitleDrafts],
  );
  const deletedSubtitleCount = useMemo(
    () => visibleSubtitles.filter((subtitle) => subtitle.deleted).length,
    [visibleSubtitles],
  );
  const baseVideoSummary = (session.base_video_summary || "").trim();
  const currentVideoSummary = videoSummary.trim();
  const baseVideoTransform = useMemo(() => normalizeVideoTransform(session.base_video_transform), [session.base_video_transform]);
  const currentVideoTransform = useMemo(() => normalizeVideoTransform(videoTransform), [videoTransform]);
  const baseVideoRotation = baseVideoTransform.rotation_cw;
  const currentVideoRotation = currentVideoTransform.rotation_cw;
  const hasVideoTransformEdits = JSON.stringify(currentVideoTransform) !== JSON.stringify(baseVideoTransform);
  const hasVideoSummaryEdits = currentVideoSummary !== baseVideoSummary;
  const previewVideoSources = useMemo(
    () => normalizePreviewVideoSources(previewAssets, session.source_url),
    [previewAssets, session.source_url],
  );
  const previewVideoUrl = previewVideoSources[0]?.url ?? null;
  const previewDisabledMessage = previewUnavailableMessage(previewAssets, session.source_url);
  const previewVideoSourceKey = previewVideoSources.map((source) => `${source.url}:${source.type || ""}`).join("|") || "manual-preview";
  const previewVideoUsingProxy = Boolean(previewAssets?.video_url || previewAssets?.video_sources?.length);
  const waveformUrl = previewAssets?.ready && previewAssets.audio_url ? previewAssets.audio_url : "";
  const waveformPeaks = useMemo(
    () => (previewAssets?.peaks?.length ? [previewAssets.peaks] : undefined),
    [previewAssets?.peaks],
  );
  const waveformDuration = previewAssets?.duration_sec || session.source_duration_sec || undefined;
  const thumbnailItems = useMemo(() => {
    if (previewAssets?.thumbnail_items?.length) return previewAssets.thumbnail_items;
    return (previewAssets?.thumbnail_urls || []).map((url, index) => ({
      url,
      time_sec: previewAssets?.duration_sec
        ? previewAssets.duration_sec * ((index + 0.5) / Math.max(1, previewAssets.thumbnail_urls.length))
        : 0,
    }));
  }, [previewAssets?.duration_sec, previewAssets?.thumbnail_items, previewAssets?.thumbnail_urls]);
  const sourceTimelineDuration = Math.max(0, session.source_duration_sec || previewAssets?.duration_sec || 0);
  const unifiedThumbnailItems = useMemo<SourceTimelineThumbnailItem[]>(() => {
    if (!thumbnailItems.length || sourceTimelineDuration <= 0) return [];
    const ordered = [...thumbnailItems].sort((left, right) => left.time_sec - right.time_sec);
    const estimatedWidth = clamp(100 / Math.max(8, ordered.length), 3.5, 8);
    return ordered.map((item, index) => {
      const timeSec = clamp(Number(item.time_sec || 0), 0, sourceTimelineDuration);
      const nextTime = ordered[index + 1]?.time_sec;
      const widthPercent = nextTime == null
        ? estimatedWidth
        : clamp(((Math.max(timeSec, nextTime) - timeSec) / sourceTimelineDuration) * 100, estimatedWidth, 10);
      return {
        url: item.url,
        timeSec,
        leftPercent: clamp((timeSec / sourceTimelineDuration) * 100, 0, 100),
        widthPercent,
      };
    });
  }, [sourceTimelineDuration, thumbnailItems]);
  const unifiedWaveformBars = useMemo(
    () => buildSourceWaveformBars(previewAssets?.peaks, 220),
    [previewAssets?.peaks],
  );
  const sourceKeepTimelineItems = useMemo(
    () => sourceRangesToTimelineItems(effectiveSegments, sourceTimelineDuration),
    [effectiveSegments, sourceTimelineDuration],
  );
  const sourceCutTimelineItems = useMemo(
    () => sourceRangesToTimelineItems(sourceCutRangesFromKeepSegments(effectiveSegments, sourceTimelineDuration), sourceTimelineDuration),
    [effectiveSegments, sourceTimelineDuration],
  );
  const timelineRulerTicks = useMemo(
    () => Array.from({ length: 7 }, (_, index) => {
      const ratio = index / 6;
      return {
        key: index,
        leftPercent: ratio * 100,
        label: formatSeconds(sourceTimelineDuration * ratio),
      };
    }),
    [sourceTimelineDuration],
  );
  const timelinePlayheadSourceTime = clamp(currentSourceTime, 0, Math.max(0, sourceTimelineDuration));
  const unifiedTimelineStyle = {
    "--playhead-left": `${sourceTimelineDuration > 0 ? (timelinePlayheadSourceTime / sourceTimelineDuration) * 100 : 0}%`,
    "--hover-left": timelineHoverSourceTime == null || sourceTimelineDuration <= 0
      ? "-100%"
      : `${clamp((timelineHoverSourceTime / sourceTimelineDuration) * 100, 0, 100)}%`,
  } as CSSProperties;
  const previewAssetProgress = previewAssets?.progress == null ? null : clamp(previewAssets.progress, 0, 1);
  const previewAssetProgressPercent = previewAssetProgress == null ? null : Math.round(previewAssetProgress * 100);
  const previewAutoVolumeGain = useMemo(() => {
    const gain = Number(previewAssets?.auto_volume_gain || 1);
    return Number.isFinite(gain) ? clamp(gain, PREVIEW_AUTO_VOLUME_MIN_GAIN, PREVIEW_AUTO_VOLUME_MAX_GAIN) : 1;
  }, [previewAssets?.auto_volume_gain]);
  const previewMeasuredLufs = Number(previewAssets?.audio_lufs || 0);
  const previewTargetLufs = Number(previewAssets?.target_lufs || -16);
  const previewAutoVolumeLabel = previewAutoVolumeEnabled
    ? `自动 ${previewAutoVolumeGain.toFixed(2)}x`
    : "自动音量";
  const selectedSubtitle = useMemo(
    () => projection.remapped.find((subtitle) => subtitle.index === selectedSubtitleIndex) ?? activeSubtitle ?? null,
    [activeSubtitle, projection.remapped, selectedSubtitleIndex],
  );
  const previewSubtitleText = activeSubtitle
    ? (editingSubtitleIndex === activeSubtitle.index ? currentSubtitleDraftText : subtitleText(activeSubtitle)).trim()
    : "";
  const subtitleOverrides = useMemo(
    () =>
      Object.entries(subtitleDrafts)
        .map(([index, draft]) => {
          const base = baseProjection.remapped.find((subtitle) => subtitle.index === Number(index));
          if (!subtitleOverrideChanged(base, draft)) return null;
          return {
            index: Number(index),
            start_time: draft.start_time ?? base?.start_time ?? null,
            end_time: draft.end_time ?? base?.end_time ?? null,
            text_final: draft.text_final ?? base?.text_final ?? null,
            delete: draft.delete || undefined,
          };
        })
        .filter(Boolean) as JobManualEditSubtitleOverride[],
    [baseProjection.remapped, subtitleDrafts],
  );
  const subtitleReplacements = useMemo(
    () =>
      subtitleReplacementHistory
        .map((item) => ({
          original: item.original.trim(),
          replacement: item.replacement.trim(),
          occurrence_count: Math.max(1, Number(item.occurrence_count || 1)),
        }))
        .filter((item, index, items) => (
          item.original
          && item.replacement
          && item.original !== item.replacement
          && items.findIndex((candidate) => (
            candidate.original === item.original
            && candidate.replacement === item.replacement
          )) === index
        )),
    [subtitleReplacementHistory],
  );
  const diagnostics = useMemo(
    () => subtitleDiagnostics(projection.remapped, totalOutputDuration),
    [projection.remapped, totalOutputDuration],
  );
  const mergedFrequentTerms = useMemo(() => {
    const manualTerms = manualTermKeys
      .map((term) => buildManualFrequentTerm(term, projection.remapped, frequentTerms))
      .filter(Boolean) as FrequentTerm[];
    return mergeManualFrequentTerms(frequentTerms, manualTerms);
  }, [frequentTerms, manualTermKeys, projection.remapped]);
  const visibleFrequentTerms = useMemo(() => {
    const query = normalizeTermKey(termReviewFilter);
    return mergedFrequentTerms.filter((term) => {
      if (term.count < minTermCount) return false;
      if (hiddenTermKeys.has(term.normalized)) return false;
      if (!query) return true;
      return term.normalized.includes(query) || term.kind.includes(termReviewFilter.trim());
    });
  }, [hiddenTermKeys, mergedFrequentTerms, minTermCount, termReviewFilter]);
  const hasTimelineEdits = useMemo(() => {
    if (baseKeepSegments.length !== effectiveSegments.length) return true;
    return baseKeepSegments.some((segment, index) => {
      const current = effectiveSegments[index];
      return !current || Math.abs(segment.start - current.start) > 0.02 || Math.abs(segment.end - current.end) > 0.02;
    });
  }, [baseKeepSegments, effectiveSegments]);
  const initialOutputDuration = useMemo(
    () => baseKeepSegments.reduce((total, segment) => total + Math.max(0, segment.end - segment.start), 0),
    [baseKeepSegments],
  );
  const outputDurationDelta = totalOutputDuration - initialOutputDuration;
  const hasMaterialEdits = hasTimelineEdits || subtitleOverrides.length > 0 || hasVideoTransformEdits;
  const visibleDraftSavedAt = autosavedAt || session.draft_saved_at || null;
  const manualEditorPayload = useMemo(
    () => ({
      keep_segments: effectiveSegments.map((segment) => ({
        start: Number(segment.start.toFixed(3)),
        end: Number(segment.end.toFixed(3)),
      })),
      subtitle_overrides: subtitleOverrides,
      subtitle_replacements: subtitleReplacements,
      video_transform: currentVideoTransform,
      video_summary: currentVideoSummary || null,
      base_timeline_id: session.timeline_id,
      base_timeline_version: session.timeline_version,
      base_render_plan_version: session.render_plan_version,
      base_subtitle_fingerprint: session.subtitle_fingerprint || null,
      note: editorNote.trim() || undefined,
    }),
    [currentVideoSummary, currentVideoTransform, effectiveSegments, editorNote, session.render_plan_version, session.subtitle_fingerprint, session.timeline_id, session.timeline_version, subtitleOverrides, subtitleReplacements],
  );
  const savePlanLabel = hasTimelineEdits
    ? "剪辑变更：重建时间线/特效"
    : hasVideoTransformEdits
      ? "画面方向变更：重新渲染"
      : subtitleOverrides.length
        ? "字幕变更：复用剪辑/特效计划"
        : hasVideoSummaryEdits
          ? "摘要变更：更新审核/校对证据"
      : "暂无实质修改";
  const saveImpactSummary = hasTimelineEdits
    ? "会保存新的剪辑时间线，并从 render 开始重新生成成片、特效和数字人版本。"
    : hasVideoTransformEdits
      ? "会保存画面旋转参数，并从 render 开始重新生成成片、特效和数字人版本。"
      : subtitleOverrides.length
        ? "会保存字幕文本/时间修改，复用当前剪辑和特效计划重新烧录字幕层。"
        : hasVideoSummaryEdits
          ? "会把人工视频摘要写入内容画像和下游上下文，作为自动审核与字幕校对的强证据。"
      : "当前没有检测到剪辑、画面方向或字幕修改。";
  const outputDurationDeltaLabel = `${outputDurationDelta >= 0 ? "+" : "-"}${formatSeconds(Math.abs(outputDurationDelta))}`;
  const manualEditChangeList = useMemo(
    () => buildManualEditChangeList({
      baseSegments: baseKeepSegments,
      effectiveSegments,
      outputDurationDeltaSec: outputDurationDelta,
      subtitleOverrides,
      baseSubtitles: baseProjection.remapped,
      subtitleReplacements,
      baseVideoTransform,
      currentVideoTransform,
      hasVideoSummaryEdits,
    }),
    [baseKeepSegments, baseProjection.remapped, baseVideoTransform, currentVideoTransform, effectiveSegments, hasVideoSummaryEdits, outputDurationDelta, subtitleOverrides, subtitleReplacements],
  );
  const hasManualEditChangeListItems = manualEditChangeList.some((item) => item.tone !== "empty");
  useEffect(() => {
    onStateChange?.({
      payload: manualEditorPayload,
      canApply: session.editable && Boolean(onApply) && hasMaterialEdits && effectiveSegments.length > 0 && pendingSmartDeleteRangeCount === 0,
      hasMaterialEdits,
      hasLocalEdits: hasMaterialEdits || hasVideoSummaryEdits,
      hasVideoSummaryEdits,
      savePlanLabel,
      baseSegmentCount: baseKeepSegments.length,
      effectiveSegmentCount: effectiveSegments.length,
      outputDurationDeltaLabel,
      subtitleOverrideCount: subtitleOverrides.length,
      saveImpactSummary,
    });
  }, [
    baseKeepSegments.length,
    effectiveSegments.length,
    hasMaterialEdits,
    hasVideoSummaryEdits,
    manualEditorPayload,
    onApply,
    onStateChange,
    outputDurationDeltaLabel,
    pendingSmartDeleteRangeCount,
    saveImpactSummary,
    savePlanLabel,
    session.editable,
    subtitleOverrides.length,
  ]);
  const selectedSubtitlePosition = selectedSubtitleIndex != null
    ? visibleSubtitles.findIndex((subtitle) => subtitle.index === selectedSubtitleIndex)
    : activeSubtitle
      ? visibleSubtitles.findIndex((subtitle) => subtitle.index === activeSubtitle.index)
      : activeSubtitleIndex;
  const subtitleTableWindow = useMemo(() => {
    const subtitles = visibleSubtitles;
    if (subtitles.length <= SUBTITLE_TABLE_WINDOW_SIZE) {
      return {
        rows: subtitles,
        start: 0,
        end: subtitles.length,
        clipped: false,
      };
    }
    const anchor = selectedSubtitlePosition >= 0 ? selectedSubtitlePosition : 0;
    const start = clamp(anchor - Math.floor(SUBTITLE_TABLE_WINDOW_SIZE / 2), 0, Math.max(0, subtitles.length - SUBTITLE_TABLE_WINDOW_SIZE));
    const end = Math.min(subtitles.length, start + SUBTITLE_TABLE_WINDOW_SIZE);
    return {
      rows: subtitles.slice(start, end),
      start,
      end,
      clipped: true,
    };
  }, [selectedSubtitlePosition, visibleSubtitles]);

  useEffect(() => {
    if (!selectedSubtitle) {
      setCurrentSubtitleDraftText("");
      setEditingSubtitleIndex(null);
      return;
    }
    if (editingSubtitleIndex !== selectedSubtitle.index) {
      setCurrentSubtitleDraftText(subtitleText(selectedSubtitle));
    }
  }, [editingSubtitleIndex, selectedSubtitle]);

  useEffect(() => {
    if (editingSubtitleIndex == null) return;
    const input = currentSubtitleInputRef.current;
    if (!input) return;
    input.focus();
    input.select();
  }, [editingSubtitleIndex]);

  useEffect(() => {
    saveSmartCutRules(smartCutRules);
  }, [smartCutRules]);

  useEffect(() => {
    const waveformElement = waveformRef.current;
    const timelineElement = waveformTimelineRef.current;
    if (!waveformUrl || !waveformElement || !timelineElement) {
      setWaveformReady(false);
      setWaveformError(null);
      return;
    }

    setWaveformReady(false);
    setWaveformError(null);
    let cancelled = false;
    let cleanupWaveform = () => {};

    void (async () => {
      const [{ default: WaveSurferModule }, { default: RegionsPlugin }, { default: TimelinePlugin }] = await Promise.all([
        import("wavesurfer.js"),
        import("wavesurfer.js/dist/plugins/regions.esm.js"),
        import("wavesurfer.js/dist/plugins/timeline.esm.js"),
      ]);
      if (cancelled) return;

      const regionsPlugin = RegionsPlugin.create();
      const timelinePlugin = TimelinePlugin.create({
        container: timelineElement,
        height: 24,
        formatTimeCallback: formatSeconds,
      });
      const waveSurfer = WaveSurferModule.create({
        container: waveformElement,
        url: waveformUrl,
        peaks: waveformPeaks,
        duration: waveformDuration,
        height: 112,
        waveColor: "#64748b",
        progressColor: "#0f766e",
        cursorColor: "#f97316",
        cursorWidth: 2,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        dragToSeek: true,
        minPxPerSec: INITIAL_WAVEFORM_ZOOM,
        autoScroll: true,
        autoCenter: true,
        plugins: [regionsPlugin as any, timelinePlugin as any],
      });

      waveSurferRef.current = waveSurfer;
      regionsRef.current = regionsPlugin;

      const seekPreview = (sourceTime: number) => {
        const nextTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
        const video = videoRef.current;
        if (video) video.currentTime = nextTime;
        setCurrentSourceTime(nextTime);
      };

      const updateSegmentsFromRegions = () => {
        if (syncingRegionsRef.current) return;
        const nextSegments = regionsPlugin
          .getRegions()
          .map((region) => ({ start: Number(region.start.toFixed(3)), end: Number(region.end.toFixed(3)) }))
          .filter((segment) => segment.end > segment.start + 0.05)
          .sort((left, right) => left.start - right.start);
        if (!nextSegments.length) return;
        recordUndoSnapshot();
        setSegments(nextSegments);
        setSelectedSegmentIndex((current) => Math.min(current, nextSegments.length - 1));
      };

      const unsubscribeReady = waveSurfer.on("ready", () => {
        setWaveformReady(true);
      });
      const unsubscribeError = waveSurfer.on("error", (error) => {
        setWaveformError(error.message || "波形加载失败");
      });
      const unsubscribeInteraction = waveSurfer.on("interaction", (sourceTime) => {
        seekPreview(sourceTime);
      });
      const unsubscribeClick = waveSurfer.on("click", (relativeX) => {
        seekPreview(relativeX * waveSurfer.getDuration());
      });
      const unsubscribeRegionClick = regionsPlugin.on("region-clicked", (region, event) => {
        event.stopPropagation();
        const index = regionsPlugin.getRegions().sort((left, right) => left.start - right.start).findIndex((item) => item.id === region.id);
        if (index >= 0) setSelectedSegmentIndex(index);
        waveSurfer.setTime(region.start);
        seekPreview(region.start);
      });
      const unsubscribeRegionUpdated = regionsPlugin.on("region-updated", updateSegmentsFromRegions);

      cleanupWaveform = () => {
        unsubscribeReady();
        unsubscribeError();
        unsubscribeInteraction();
        unsubscribeClick();
        unsubscribeRegionClick();
        unsubscribeRegionUpdated();
        waveSurfer.destroy();
        if (waveSurferRef.current === waveSurfer) waveSurferRef.current = null;
        if (regionsRef.current === regionsPlugin) regionsRef.current = null;
      };
    })().catch((error) => {
      if (!cancelled) setWaveformError(error instanceof Error ? error.message : "波形组件加载失败");
    });

    return () => {
      cancelled = true;
      cleanupWaveform();
    };
  }, [session.job_id, session.source_duration_sec, session.timeline_id, session.timeline_version, waveformDuration, waveformPeaks, waveformUrl]);

  useEffect(() => {
    setFrequentTerms([]);
    const build = () => setFrequentTerms(buildFrequentTerms(projection.remapped));
    const requestIdleCallback = window.requestIdleCallback;
    if (requestIdleCallback) {
      const idleId = requestIdleCallback(build, { timeout: 900 });
      return () => window.cancelIdleCallback?.(idleId);
    }
    const timeout = window.setTimeout(build, 120);
    return () => window.clearTimeout(timeout);
  }, [projection.remapped]);

  useEffect(() => {
    const regionsPlugin = regionsRef.current;
    if (!regionsPlugin || !waveformReady) return;
    syncingRegionsRef.current = true;
    regionsPlugin.clearRegions();
    effectiveSegments.forEach((segment, index) => {
      const region = regionsPlugin.addRegion({
        id: regionIdForIndex(index),
        start: segment.start,
        end: segment.end,
        drag: session.editable,
        resize: session.editable,
        color: index === selectedSegmentIndex ? REGION_ACTIVE_COLOR : REGION_COLOR,
        content: String(index + 1),
        minLength: 0.1,
      });
      region.element?.setAttribute("title", `${formatSeconds(segment.start)} - ${formatSeconds(segment.end)}`);
    });
    syncingRegionsRef.current = false;
  }, [effectiveSegments, selectedSegmentIndex, session.editable, waveformReady]);

  useEffect(() => {
    const waveSurfer = waveSurferRef.current;
    if (!waveSurfer || !waveformReady) return;
    waveSurfer.setTime(clamp(currentSourceTime, 0, session.source_duration_sec || currentSourceTime));
  }, [currentSourceTime, session.source_duration_sec, waveformReady]);

  useEffect(() => {
    const waveSurfer = waveSurferRef.current;
    if (!waveSurfer || !waveformReady) return;
    waveSurfer.zoom(waveformZoom);
  }, [waveformReady, waveformZoom]);

  const setPreviewSourceTime = (sourceTime: number, force = false) => {
    const nextSourceTime = Number(sourceTime || 0);
    if (!Number.isFinite(nextSourceTime)) return;
    if (!force && Math.abs(lastSyncedPreviewSourceTimeRef.current - nextSourceTime) < 0.03) return;
    lastSyncedPreviewSourceTimeRef.current = nextSourceTime;
    setCurrentSourceTime(nextSourceTime);
  };

  const syncPreviewTime = () => {
    const video = videoRef.current;
    if (!video) return;
    const sourceTime = Number(video.currentTime || 0);
    setPreviewSourceTime(sourceTime);
    if (!timelinePlaybackRef.current || !projection.ranges.length) return;

    const decision = resolveEditedPlaybackSyncDecision(sourceTime, projection.ranges);
    if (decision.action === "seek") {
      seekOutputPlaybackToSourceTime(video, decision.sourceTime);
      return;
    }
    if (decision.action === "stop") {
      timelinePlaybackRef.current = false;
      void video.pause();
    }
  };

  const stopPreviewClock = () => {
    if (previewClockFrameRef.current == null) return;
    window.cancelAnimationFrame(previewClockFrameRef.current);
    previewClockFrameRef.current = null;
  };

  const startPreviewClock = () => {
    if (previewClockFrameRef.current != null) return;
    const tick = () => {
      syncPreviewTime();
      const video = videoRef.current;
      if (!video || video.paused || video.ended) {
        previewClockFrameRef.current = null;
        return;
      }
      previewClockFrameRef.current = window.requestAnimationFrame(tick);
    };
    previewClockFrameRef.current = window.requestAnimationFrame(tick);
  };

  const seekPreviewToSourceTime = (video: HTMLVideoElement, sourceTime: number) => {
    const nextSourceTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
    pendingPreviewSeekRef.current = nextSourceTime;
    const alreadyThere = Math.abs(Number(video.currentTime || 0) - nextSourceTime) <= 0.015;
    waveSurferRef.current?.setTime(nextSourceTime);
    setPreviewSourceTime(nextSourceTime, true);
    if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
      try {
        video.load();
      } catch {
        // Some browsers reject load() while source selection is already in progress.
      }
      return Promise.resolve();
    }
    if (alreadyThere && !video.seeking) {
      pendingPreviewSeekRef.current = null;
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeoutId);
        video.removeEventListener("seeked", finish);
        setPreviewSourceTime(nextSourceTime, true);
        if (Math.abs((pendingPreviewSeekRef.current ?? nextSourceTime) - nextSourceTime) <= 0.015) {
          pendingPreviewSeekRef.current = null;
        }
        resolve();
      };
      const timeoutId = window.setTimeout(finish, 750);
      video.addEventListener("seeked", finish);
      try {
        video.currentTime = nextSourceTime;
      } catch {
        finish();
        return;
      }
      if (!video.seeking) finish();
    });
  };

  const markOutputPlaybackSeek = () => {
    outputPlaybackSeekInProgressRef.current = true;
    if (outputPlaybackSeekTimeoutRef.current != null) {
      window.clearTimeout(outputPlaybackSeekTimeoutRef.current);
    }
    outputPlaybackSeekTimeoutRef.current = window.setTimeout(() => {
      outputPlaybackSeekInProgressRef.current = false;
      outputPlaybackSeekTimeoutRef.current = null;
    }, 900);
  };

  const clearOutputPlaybackSeek = () => {
    outputPlaybackSeekInProgressRef.current = false;
    if (outputPlaybackSeekTimeoutRef.current != null) {
      window.clearTimeout(outputPlaybackSeekTimeoutRef.current);
      outputPlaybackSeekTimeoutRef.current = null;
    }
  };

  const resumeOutputPlaybackAfterSeek = (video: HTMLVideoElement) => {
    window.setTimeout(() => {
      if (videoRef.current !== video) return;
      if (!timelinePlaybackRef.current || video.ended || !projection.ranges.length) return;
      if (!video.paused) {
        startPreviewClock();
        return;
      }
      void video.play()
        .then(() => {
          setIsPreviewPlaying(true);
          setPreviewPlaybackMode("output");
          startPreviewClock();
        })
        .catch(() => {
          timelinePlaybackRef.current = false;
          setIsPreviewPlaying(false);
          setPreviewPlaybackMode(null);
          stopPreviewClock();
        });
    }, 0);
  };

  const seekOutputPlaybackToSourceTime = (video: HTMLVideoElement, sourceTime: number) => {
    const nextSourceTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
    if (Math.abs(Number(video.currentTime || 0) - nextSourceTime) <= 0.015) return;
    markOutputPlaybackSeek();
    try {
      video.currentTime = nextSourceTime;
    } catch {
      clearOutputPlaybackSeek();
      return;
    }
    setPreviewSourceTime(nextSourceTime, true);
    waveSurferRef.current?.setTime(nextSourceTime);
    resumeOutputPlaybackAfterSeek(video);
  };

  const jumpToOutputTime = (outputTime: number) => {
    const video = videoRef.current;
    if (!projection.ranges.length) return;
    const sourceTime = outputTimeToSourceTime(outputTime, projection.ranges);
    lastUserPreviewSeekSourceTimeRef.current = sourceTime;
    if (video) {
      void seekPreviewToSourceTime(video, sourceTime);
      return;
    }
    pendingPreviewSeekRef.current = sourceTime;
    waveSurferRef.current?.setTime(sourceTime);
    setPreviewSourceTime(sourceTime, true);
  };

  const jumpToSourceTime = (sourceTime: number) => {
    const nextSourceTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
    lastUserPreviewSeekSourceTimeRef.current = nextSourceTime;
    const video = videoRef.current;
    if (video) {
      void seekPreviewToSourceTime(video, nextSourceTime);
      return;
    }
    pendingPreviewSeekRef.current = nextSourceTime;
    waveSurferRef.current?.setTime(nextSourceTime);
    setPreviewSourceTime(nextSourceTime, true);
  };

  const reanchorPreviewToSegments = (nextSegments: KeepSegment[], outputTime = currentOutputTime) => {
    if (!timelinePlaybackRef.current) {
      jumpToSourceTime(currentSourceTime);
      return;
    }
    const nextSourceTime = outputTimeToSourceTimeForSegments(outputTime, nextSegments);
    jumpToSourceTime(nextSourceTime);
  };

  const selectSubtitleNearOutputTime = (outputTime: number) => {
    if (editingSubtitleIndex != null) return;
    const subtitleIndex = findSubtitleIndexNearOutputTime(projection.remapped, outputTime);
    const subtitle = projection.remapped[subtitleIndex];
    if (subtitle) setSelectedSubtitleIndex(subtitle.index);
  };

  const selectSubtitleNearSourceTime = (sourceTime: number) => {
    const outputTime = sourceTimeToActiveOutputTime(sourceTime, projection.ranges);
    if (outputTime == null) {
      if (editingSubtitleIndex == null) setSelectedSubtitleIndex(null);
      return;
    }
    selectSubtitleNearOutputTime(outputTime);
  };

  const sourceTimeFromUnifiedTimelinePointer = (event: { clientX: number }) => {
    const timeline = unifiedTimelineRef.current;
    if (!timeline || sourceTimelineDuration <= 0) return null;
    const rect = timeline.getBoundingClientRect();
    if (rect.width <= 0) return null;
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    return sourceTimelineDuration * ratio;
  };

  const previewUnifiedTimelineAtPointer = (event: ReactPointerEvent<HTMLElement>) => {
    const sourceTime = sourceTimeFromUnifiedTimelinePointer(event);
    if (sourceTime == null) return;
    setTimelineHoverSourceTime(sourceTime);
  };

  const commitUnifiedTimelinePointer = (event: { clientX: number }) => {
    const sourceTime = sourceTimeFromUnifiedTimelinePointer(event);
    if (sourceTime == null) return;
    setTimelineHoverSourceTime(sourceTime);
    selectSubtitleNearSourceTime(sourceTime);
    jumpToSourceTime(sourceTime);
  };

  const playEditedTimeline = async () => {
    const video = videoRef.current;
    if (!video || !projection.ranges.length) return;
    const userSeekSourceTime = lastUserPreviewSeekSourceTimeRef.current;
    lastUserPreviewSeekSourceTimeRef.current = null;
    const playbackAnchorSourceTime = userSeekSourceTime ?? Number(video.currentTime || currentSourceTime || 0);
    const playbackAnchorOutputTime = sourceTimeToOutputTime(playbackAnchorSourceTime, projection.ranges);
    const currentRange = projection.ranges.find((range) => playbackAnchorSourceTime >= range.sourceStart && playbackAnchorSourceTime < range.sourceEnd - 0.02);
    const playbackStartSourceTime = sourceTimeToEditedPlaybackStartTime(playbackAnchorSourceTime, projection.ranges);
    const shouldRestart = userSeekSourceTime == null && (video.ended || playbackAnchorOutputTime >= Math.max(0, totalOutputDuration - 0.08));
    timelinePlaybackRef.current = true;
    setPreviewPlaybackMode("output");
    if (shouldRestart) {
      await seekPreviewToSourceTime(video, projection.ranges[0].sourceStart);
    } else if (currentRange && Math.abs(Number(video.currentTime || 0) - playbackAnchorSourceTime) > 0.015) {
      await seekPreviewToSourceTime(video, playbackAnchorSourceTime);
    } else if (!currentRange && playbackStartSourceTime != null) {
      await seekPreviewToSourceTime(video, playbackStartSourceTime);
    } else if (!currentRange) {
      timelinePlaybackRef.current = false;
      setIsPreviewPlaying(false);
      setPreviewPlaybackMode(null);
      stopPreviewClock();
      return;
    }
    applyPreviewAudioSettings(previewVolume, previewMuted, previewAutoVolumeEnabled, true);
    await video.play();
    startPreviewClock();
  };

  const pauseEditedTimeline = () => {
    timelinePlaybackRef.current = false;
    lastUserPreviewSeekSourceTimeRef.current = null;
    setIsPreviewPlaying(false);
    setPreviewPlaybackMode(null);
    stopPreviewClock();
    void videoRef.current?.pause();
  };

  const toggleEditedTimelinePlayback = () => {
    if (isPreviewPlaying) {
      pauseEditedTimeline();
      return;
    }
    void playEditedTimeline();
  };

  const fallbackPreviewElementVolume = (video: HTMLVideoElement, volume: number, muted: boolean, autoVolumeEnabled: boolean) => {
    const gain = autoVolumeEnabled ? previewAutoVolumeGain : 1;
    video.volume = muted ? 0 : clamp(volume * gain, 0, 1);
    video.muted = muted || volume <= 0;
  };

  const ensurePreviewAudioGraph = () => {
    const video = videoRef.current;
    if (!video || typeof window === "undefined") return null;
    if (previewGainRef.current) return previewGainRef.current;
    const AudioContextConstructor = window.AudioContext
      || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return null;
    try {
      const audioContext = previewAudioContextRef.current ?? new AudioContextConstructor();
      previewAudioContextRef.current = audioContext;
      const sourceNode = previewAudioSourceRef.current ?? audioContext.createMediaElementSource(video);
      const gainNode = audioContext.createGain();
      const compressorNode = audioContext.createDynamicsCompressor();
      compressorNode.threshold.value = -3;
      compressorNode.knee.value = 12;
      compressorNode.ratio.value = 12;
      compressorNode.attack.value = 0.003;
      compressorNode.release.value = 0.25;
      sourceNode.connect(gainNode);
      gainNode.connect(compressorNode);
      compressorNode.connect(audioContext.destination);
      previewAudioSourceRef.current = sourceNode;
      previewGainRef.current = gainNode;
      previewCompressorRef.current = compressorNode;
      return gainNode;
    } catch {
      return null;
    }
  };

  const applyPreviewAudioSettings = (volume = previewVolume, muted = previewMuted, autoVolumeEnabled = previewAutoVolumeEnabled, createGraph = false) => {
    const nextVolume = clamp(volume, 0, 1);
    const video = videoRef.current;
    if (!video) return;
    const gainNode = previewGainRef.current ?? (createGraph ? ensurePreviewAudioGraph() : null);
    const outputGain = muted || nextVolume <= 0 ? 0 : nextVolume * (autoVolumeEnabled ? previewAutoVolumeGain : 1);
    if (gainNode) {
      gainNode.gain.value = outputGain;
      video.volume = 1;
      video.muted = false;
      if (previewAudioContextRef.current?.state === "suspended") {
        void previewAudioContextRef.current.resume();
      }
      return;
    }
    fallbackPreviewElementVolume(video, nextVolume, muted, autoVolumeEnabled);
  };

  const applyPreviewVolume = (volume: number, muted = previewMuted) => {
    const nextVolume = clamp(volume, 0, 1);
    setPreviewVolume(nextVolume);
    setPreviewMuted(muted || nextVolume <= 0);
    applyPreviewAudioSettings(nextVolume, muted || nextVolume <= 0, previewAutoVolumeEnabled, true);
  };

  const togglePreviewMuted = () => {
    const nextMuted = !previewMuted;
    setPreviewMuted(nextMuted);
    const nextVolume = !nextMuted && previewVolume <= 0 ? 0.6 : previewVolume;
    if (nextVolume !== previewVolume) setPreviewVolume(nextVolume);
    applyPreviewAudioSettings(nextVolume, nextMuted, previewAutoVolumeEnabled, true);
  };

  const togglePreviewAutoVolume = () => {
    const nextEnabled = !previewAutoVolumeEnabled;
    setPreviewAutoVolumeEnabled(nextEnabled);
    applyPreviewAudioSettings(previewVolume, previewMuted, nextEnabled, true);
  };

  useEffect(() => {
    applyPreviewAudioSettings(previewVolume, previewMuted, previewAutoVolumeEnabled, false);
  }, [previewAutoVolumeEnabled, previewAutoVolumeGain, previewMuted, previewVolume]);

  useEffect(() => {
    clearOutputPlaybackSeek();
    try {
      previewGainRef.current?.disconnect();
      previewCompressorRef.current?.disconnect();
      previewAudioSourceRef.current?.disconnect();
    } catch {
      // Ignore browser-specific Web Audio teardown errors.
    }
    if (previewAudioContextRef.current?.state !== "closed") {
      void previewAudioContextRef.current?.close();
    }
    previewAudioContextRef.current = null;
    previewAudioSourceRef.current = null;
    previewGainRef.current = null;
    previewCompressorRef.current = null;
  }, [previewVideoSourceKey]);

  useEffect(() => () => {
    stopPreviewClock();
    clearOutputPlaybackSeek();
    try {
      previewGainRef.current?.disconnect();
      previewCompressorRef.current?.disconnect();
      previewAudioSourceRef.current?.disconnect();
    } catch {
      // Ignore browser-specific Web Audio teardown errors.
    }
    if (previewAudioContextRef.current?.state !== "closed") {
      void previewAudioContextRef.current?.close();
    }
  }, []);

  const pauseForSubtitleEdit = () => {
    const video = videoRef.current;
    resumeAfterSubtitleEditRef.current = Boolean(video && !video.paused);
    if (video && !video.paused) void video.pause();
    timelinePlaybackRef.current = false;
  };

  const resumeAfterSubtitleEdit = (options?: { force?: boolean }) => {
    const shouldResume = resumeAfterSubtitleEditRef.current;
    resumeAfterSubtitleEditRef.current = false;
    if (!shouldResume && !options?.force) return;
    void playEditedTimeline();
  };

  const restoreInitialSegments = () => {
    recordUndoSnapshot();
    setSegments(session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end })));
    setSelectedSegmentIndex(0);
    setSelectedSubtitleIndex(null);
    setEditingSubtitleIndex(null);
    setCurrentSubtitleDraftText("");
    setSubtitleDrafts(
      Object.fromEntries(
        (session.subtitle_overrides || []).map((override) => [
          override.index,
          {
            start_time: override.start_time,
            end_time: override.end_time,
            text_final: override.text_final,
            delete: override.delete,
          },
        ]),
      ),
    );
    lastSelectedSubtitleTextRef.current = "";
    setSubtitleReplaceDialog(null);
    setSubtitleReplacementHistory([]);
    setManualSmartCutRestoreRanges([]);
    setManualSmartCutConfirmRanges([]);
    setManualSmartCutDismissRanges([]);
    setEditorNote("");
    setVideoSummary(session.video_summary || "");
    const nextTransform = normalizeVideoTransform(session.video_transform);
    setVideoTransform(nextTransform);
    setRotationDraft(nextTransform.rotation_cw);
    setResolutionDraft(nextTransform);
    setRotationDialogOpen(false);
    setResolutionDialogOpen(false);
    setRotationDetectMessage(null);
    resumeAfterSubtitleEditRef.current = false;
  };

  useEffect(() => {
    if (!resetSignal) return;
    restoreInitialSegments();
  }, [resetSignal]);

  const openRotationDialog = () => {
    setRotationDraft(currentVideoRotation);
    setRotationDetectMessage(null);
    setRotationDialogOpen(true);
  };

  const detectRotation = async () => {
    if (!onDetectRotation || detectingRotation) return;
    setRotationDetectMessage("正在自动检测画面方向...");
    try {
      const detected = normalizeRotationValue(await onDetectRotation());
      setRotationDraft(detected);
      setRotationDetectMessage(`检测建议：顺时针旋转 ${detected}°`);
    } catch (error) {
      setRotationDetectMessage(error instanceof Error ? error.message : "自动检测失败，请手动选择角度。");
    }
  };

  const applyRotationDraft = () => {
    const nextRotation = normalizeRotationValue(rotationDraft);
    recordUndoSnapshot();
    setVideoTransform((current) => ({ ...normalizeVideoTransform(current), rotation_cw: nextRotation }));
    setRotationDraft(nextRotation);
    setRotationDialogOpen(false);
  };

  const openResolutionDialog = () => {
    setResolutionDraft(currentVideoTransform);
    setResolutionDialogOpen(true);
  };

  const updateResolutionDraft = (patch: Partial<JobManualVideoTransform>) => {
    setResolutionDraft((current) => normalizeVideoTransform({ ...current, ...patch }));
  };

  const applyResolutionDraft = () => {
    const nextTransform = normalizeVideoTransform({
      ...currentVideoTransform,
      aspect_ratio: resolutionDraft.aspect_ratio,
      resolution_mode: resolutionDraft.resolution_mode,
      resolution_preset: resolutionDraft.resolution_preset,
    });
    recordUndoSnapshot();
    setVideoTransform(nextTransform);
    setResolutionDraft(nextTransform);
    setResolutionDialogOpen(false);
  };

  const updatePreviewVideoLoadProgress = (video: HTMLVideoElement) => {
    const duration = Number(video.duration || 0);
    if (!Number.isFinite(duration) || duration <= 0 || video.buffered.length <= 0) {
      setPreviewVideoLoadProgress(null);
      return;
    }
    const bufferedEnd = video.buffered.end(video.buffered.length - 1);
    setPreviewVideoLoadProgress(clamp(bufferedEnd / duration, 0, 1));
  };

  const rememberVideoMetadata = (event: SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    setPreviewVideoLoadError(null);
    updatePreviewVideoLoadProgress(video);
    if (video.videoWidth > 0 && video.videoHeight > 0) {
      setSourceVideoSize({ width: video.videoWidth, height: video.videoHeight });
    }
    const pendingSeek = pendingPreviewSeekRef.current;
    if (pendingSeek != null) {
      void seekPreviewToSourceTime(video, pendingSeek);
    }
  };

  const handlePreviewVideoError = (event: SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.currentSrc) {
      setPreviewVideoLoadError(null);
      setPreviewVideoLoading(false);
      return;
    }
    const code = video.error?.code;
    const message = code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED
      ? previewVideoUsingProxy
        ? "浏览器无法解码当前视频代理，请重新生成预览资产或检查 ffmpeg 编码支持。"
        : "浏览器无法解码当前原片，等待视频代理生成后会自动切换。"
      : code === MediaError.MEDIA_ERR_NETWORK
        ? "预览视频加载中断，请刷新后重试。"
        : "预览视频加载失败，请刷新或重新生成预览资产。";
    setPreviewVideoLoadError(message);
    setPreviewVideoLoading(false);
    setIsPreviewPlaying(false);
    timelinePlaybackRef.current = false;
  };

  const updateSubtitleDraft = (subtitle: JobManualEditSubtitle, patch: SubtitleDraft) => {
    recordUndoSnapshot();
    setSelectedSubtitleIndex(subtitle.index);
    setSubtitleDrafts((current) => {
      const existing = current[subtitle.index] ?? {};
      const next = {
        ...existing,
        ...patch,
      };
      if (next.start_time != null && next.end_time != null && next.end_time <= next.start_time + 0.08) {
        next.end_time = Number((next.start_time + 0.08).toFixed(3));
      }
      return { ...current, [subtitle.index]: next };
    });
  };

  const selectSubtitle = (subtitle: JobManualEditSubtitle, options?: { edit?: boolean }) => {
    setSelectedSubtitleIndex(subtitle.index);
    if (options?.edit) {
      if (editingSubtitleIndex !== subtitle.index) pauseForSubtitleEdit();
      setEditingSubtitleIndex(subtitle.index);
      setCurrentSubtitleDraftText(subtitleText(subtitle));
    }
    jumpToOutputTime(subtitle.start_time);
  };

  const clearSubtitleSelection = () => {
    if (editingSubtitleIndex != null) {
      const editingSubtitle = projection.remapped.find((subtitle) => subtitle.index === editingSubtitleIndex);
      if (editingSubtitle) {
        updateSubtitleDraft(editingSubtitle, { text_final: currentSubtitleDraftText });
      }
    }
    setSelectedSubtitleIndex(null);
    setEditingSubtitleIndex(null);
    setCurrentSubtitleDraftText("");
  };

  const commitCurrentSubtitleEdit = (options?: { resume?: boolean; forceResume?: boolean }) => {
    if (!selectedSubtitle || editingSubtitleIndex !== selectedSubtitle.index) return;
    updateSubtitleDraft(selectedSubtitle, { text_final: currentSubtitleDraftText });
    setEditingSubtitleIndex(null);
    if (options?.resume) resumeAfterSubtitleEdit({ force: options.forceResume });
  };

  const clearSelectedSubtitleText = () => {
    if (!selectedSubtitle) return;
    pauseForSubtitleEdit();
    setEditingSubtitleIndex(null);
    setCurrentSubtitleDraftText("");
    updateSubtitleDraft(selectedSubtitle, { text_final: "" });
  };

  const removeSelectedSubtitleSegment = () => {
    if (!selectedSubtitle) return;
    pauseForSubtitleEdit();
    const sourceRanges = outputRangeToSourceRanges(selectedSubtitle.start_time, selectedSubtitle.end_time, projection.ranges);
    const nextSegments = removeSourceRangesFromSegments(effectiveSegments, sourceRanges);
    if (!nextSegments.length) return;
    recordUndoSnapshot();
    setSegments(nextSegments);
    setSelectedSegmentIndex((current) => clamp(current, 0, nextSegments.length - 1));
    updateSubtitleDraft(selectedSubtitle, { delete: true });
    setEditingSubtitleIndex(null);
    forgetManualSmartCutRestores(sourceRanges);
    confirmSmartDeleteSuggestionsForRanges(sourceRanges);
  };

  const clearTranscriptSelection = () => {
    setTranscriptSelection(null);
    setTranscriptSelectionPopover(null);
    setTranscriptReplacementDraft("");
    window.getSelection?.()?.removeAllRanges();
  };

  useEffect(() => {
    if (!transcriptSelection) return undefined;
    const close = () => {
      setTranscriptSelection(null);
      setTranscriptSelectionPopover(null);
      setTranscriptReplacementDraft("");
      window.getSelection?.()?.removeAllRanges();
    };
    const handlePointerDown = (event: globalThis.PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-subtitle-selection-scope]")) return;
      close();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const handleScroll = () => close();
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [transcriptSelection]);

  const updateTranscriptSelectionFromWindow = () => {
    const nextSelection = transcriptSelectionFromWindow(transcriptTokens);
    if (!nextSelection) {
      clearTranscriptSelection();
      return;
    }
    setTranscriptSelection(nextSelection);
    setTranscriptSelectionPopover(transcriptSelectionPopoverPositionFromWindow());
    if (nextSelection.text) {
      lastSelectedSubtitleTextRef.current = nextSelection.text.slice(0, 80);
    }
  };

  const transcriptTokenIsCut = (token: TranscriptToken) => (
    !token.kept
    || transcriptTokenRangesOverlap(token, transcriptCutRanges)
    || smartCutRuleMatchForTranscriptToken(token, activeSmartCutRuleRanges) != null
  );

  const smartCutClassificationForToken = (token: TranscriptToken, cut: boolean) => {
    const match = smartCutRuleMatchForTranscriptToken(token, activeSmartCutRuleRanges);
    if (match) return { match, kind: match.kind };
    if (cut && token.kind === "pause") return { match: null, kind: "pause" as const };
    return { match: null, kind: null };
  };

  const smartDeleteSuggestionForToken = (token: TranscriptToken) => (
    smartCutRuleMatchForTranscriptToken(token, pendingSmartDeleteRanges)
  );

  const selectTranscriptToken = (tokenIndex: number) => {
    const token = transcriptTokens[tokenIndex];
    if (!token) return;
    const nextSelection = transcriptSelectionFromTokenRange(transcriptTokens, tokenIndex, tokenIndex);
    setTranscriptSelection(nextSelection);
    setTranscriptSelectionPopover(transcriptSelectionPopoverPositionFromRect(transcriptTokenRefs.current.get(tokenIndex)?.getBoundingClientRect() ?? null));
    if (!transcriptTokenIsCut(token)) {
      jumpToSourceTime(transcriptPauseRangesForToken(token)[0]?.start ?? token.start);
    }
    if (token.subtitleIndex != null) {
      const subtitle = projection.remapped.find((item) => subtitleSourceIndex(item) === token.subtitleIndex)
        ?? projection.remapped.find((item) => item.index === token.subtitleIndex);
      if (subtitle) setSelectedSubtitleIndex(subtitle.index);
    }
  };

  const cutTranscriptSelection = () => {
    if (!transcriptSelection) return;
    const ranges = transcriptCutRangesForSelection(
      sourceTranscriptSubtitles,
      transcriptTokens,
      transcriptSelection,
      session.source_duration_sec,
    );
    if (!ranges.length) return;
    const nextSegments = removeSourceRangesFromSegments(effectiveSegments, ranges);
    if (!nextSegments.length) return;
    recordUndoSnapshot();
    pauseEditedTimeline();
    setSegments(nextSegments);
    setSubtitleDrafts((current) => removeTranscriptSelectionTextFromSubtitleDrafts(
      projection.remapped,
      transcriptTokens,
      transcriptSelection,
      current,
    ));
    setSelectedSegmentIndex((current) => clamp(current, 0, nextSegments.length - 1));
    forgetManualSmartCutRestores(ranges);
    confirmSmartDeleteSuggestionsForRanges(ranges);
    clearTranscriptSelection();
  };

  const restoreTranscriptSelection = () => {
    if (!transcriptSelection) return;
    const range = { start: transcriptSelection.sourceStart, end: transcriptSelection.sourceEnd };
    recordUndoSnapshot();
    pauseEditedTimeline();
    rememberManualSmartCutRestores([range]);
    unconfirmSmartDeleteSuggestionsForRanges([range]);
    setSegments((current) => addSourceRangesToSegments(current, [range], session.source_duration_sec));
    jumpToSourceTime(range.start);
    clearTranscriptSelection();
  };

  const replaceSelectedTranscriptText = () => {
    const replacement = transcriptReplacementDraft.trim();
    if (!transcriptSelection?.text || !replacement || replacement === transcriptSelection.text) return;
    const selectedSubtitleIndexes = new Set(
      transcriptTokens
        .slice(transcriptSelection.startTokenIndex, transcriptSelection.endTokenIndex + 1)
        .map((token) => token.subtitleIndex)
        .filter((index): index is number => index != null),
    );
    const sourceText = transcriptSelection.text;
    const subtitles = projection.remapped.filter((subtitle) => selectedSubtitleIndexes.has(subtitleSourceIndex(subtitle)));
    const firstSubtitle = subtitles.find((subtitle) => subtitleText(subtitle).includes(sourceText));
    if (!firstSubtitle) return;
    recordUndoSnapshot();
    updateSubtitleDraft(firstSubtitle, { text_final: subtitleText(firstSubtitle).replace(sourceText, replacement) });
    setSubtitleReplacementHistory((current) => [
      ...current.filter((item) => !(item.original === sourceText && item.replacement === replacement)),
      { original: sourceText, replacement, occurrence_count: 1 },
    ]);
    setTranscriptReplacementDraft("");
    lastSelectedSubtitleTextRef.current = replacement;
    clearTranscriptSelection();
  };

  const replaceAllTranscriptText = () => {
    if (!transcriptSelection?.text || !transcriptReplacementDraft.trim()) return;
    applySubtitleReplacement(transcriptSelection.text, transcriptReplacementDraft, { clearManualDraft: false });
    setTranscriptReplacementDraft("");
    clearTranscriptSelection();
  };

  const rememberManualSmartCutRestores = (ranges: KeepSegment[]) => {
    if (!ranges.length) return;
    setManualSmartCutRestoreRanges((current) => addSourceRangesToSegments(current, ranges, session.source_duration_sec));
  };

  const forgetManualSmartCutRestores = (ranges: KeepSegment[]) => {
    if (!ranges.length) return;
    setManualSmartCutRestoreRanges((current) => removeSourceRangesFromSegments(current, ranges));
  };

  const confirmSmartDeleteSuggestionsForRanges = (ranges: KeepSegment[]) => {
    const matched = pendingSmartDeleteRanges
      .filter((suggestion) => sourceRangeOverlapsCutRanges(suggestion.start, suggestion.end, ranges))
      .map((suggestion) => ({ start: suggestion.start, end: suggestion.end }));
    if (!matched.length) return;
    setManualSmartCutConfirmRanges((current) => addSourceRangesToSegments(current, matched, session.source_duration_sec));
    setManualSmartCutDismissRanges((current) => removeSourceRangesFromSegments(current, matched));
  };

  const unconfirmSmartDeleteSuggestionsForRanges = (ranges: KeepSegment[]) => {
    if (!ranges.length) return;
    setManualSmartCutConfirmRanges((current) => removeSourceRangesFromSegments(current, ranges));
  };

  const confirmSmartDeleteSuggestion = (range: SmartCutRuleMatch) => {
    const nextRange = { start: range.start, end: range.end };
    const nextSegments = removeSourceRangesFromSegments(effectiveSegments, [nextRange]);
    if (!nextSegments.length) return;
    recordUndoSnapshot();
    pauseEditedTimeline();
    setSegments(nextSegments);
    setManualSmartCutConfirmRanges((current) => addSourceRangesToSegments(current, [nextRange], session.source_duration_sec));
    setManualSmartCutDismissRanges((current) => removeSourceRangesFromSegments(current, [nextRange]));
    setSelectedSegmentIndex((current) => clamp(current, 0, nextSegments.length - 1));
    reanchorPreviewToSegments(nextSegments);
  };

  const dismissSmartDeleteSuggestion = (range: SmartCutRuleMatch) => {
    const nextRange = { start: range.start, end: range.end };
    recordUndoSnapshot();
    setManualSmartCutDismissRanges((current) => addSourceRangesToSegments(current, [nextRange], session.source_duration_sec));
    setManualSmartCutConfirmRanges((current) => removeSourceRangesFromSegments(current, [nextRange]));
  };

  const applySmartCutRuleRanges = (ranges: KeepSegment[], managedRanges: KeepSegment[]) => {
    const baseSegments = baseKeepSegments.map((segment) => ({ start: segment.start, end: segment.end }));
    const nextSegments = applySmartCutRuleRangesToSegments(
      baseSegments,
      ranges,
      managedRanges,
      session.source_duration_sec,
      manualSmartCutRestoreRanges,
      smartCutRules,
      sourceSpeechProtectionRanges,
    );
    if (!nextSegments.length) return;
    if (keepSegmentsEquivalent(effectiveSegments, nextSegments)) return;
    recordUndoSnapshot();
    pauseEditedTimeline();
    setSegments(nextSegments);
    setSelectedSegmentIndex((current) => clamp(current, 0, nextSegments.length - 1));
    reanchorPreviewToSegments(nextSegments);
  };

  const updateSmartCutRule = (patch: Partial<SmartCutRules>) => {
    setSmartCutRules((current) => normalizeSmartCutRules({ ...current, ...patch }));
  };

  const addManualFrequentTerm = () => {
    const cleaned = cleanTermToken(manualTermDraft);
    if (!cleaned || normalizeTermKey(cleaned).length < 2) return;
    const manualTerm = buildManualFrequentTerm(cleaned, projection.remapped, frequentTerms);
    if (!manualTerm) return;
    setManualTermKeys((current) => (
      current.some((item) => normalizeTermKey(item) === manualTerm.normalized)
        ? current
        : [...current, manualTerm.term]
    ));
    setHiddenTermKeys((current) => {
      if (!current.has(manualTerm.normalized)) return current;
      const next = new Set(current);
      next.delete(manualTerm.normalized);
      return next;
    });
    setTermReviewFilter("");
    setManualTermDraft("");
  };

  const replaceTermAcrossSubtitles = (term: FrequentTerm) => {
    const replacement = (termReplacementDrafts[term.normalized] || "").trim();
    if (!replacement || replacement === term.term) return;
    const sourceCandidates = term.manuallyAdded ? [term.term] : [term.term, ...(term.relatedTerms || [])];
    const sourceTerms = sourceCandidates
      .map((value) => cleanTermToken(value))
      .filter((value, index, values) => (
        value
        && value !== replacement
        && values.findIndex((candidate) => normalizeTermKey(candidate) === normalizeTermKey(value)) === index
      ))
      .sort((left, right) => right.length - left.length);
    if (!sourceTerms.length) return;
    const replacementCounts = new Map(sourceTerms.map((sourceTerm) => [sourceTerm, 0]));
    recordUndoSnapshot();
    setSubtitleDrafts((current) => {
      const next = { ...current };
      for (const subtitle of projection.remapped) {
        let text = subtitleText(subtitle);
        let changed = false;
        for (const sourceTerm of sourceTerms) {
          const matchCount = countTextMatches(text, sourceTerm);
          if (matchCount <= 0) continue;
          replacementCounts.set(sourceTerm, (replacementCounts.get(sourceTerm) || 0) + matchCount);
          text = text.replace(new RegExp(escapeRegExp(sourceTerm), "g"), replacement);
          changed = true;
        }
        if (!changed) continue;
        next[subtitle.index] = {
          ...(next[subtitle.index] ?? {}),
          text_final: text,
        };
      }
      return next;
    });
    const replacementRows = [...replacementCounts.entries()]
      .filter(([, count]) => count > 0)
      .map(([original, occurrence_count]) => ({ original, replacement, occurrence_count }));
    if (replacementRows.length) {
      setSubtitleReplacementHistory((current) => [
        ...current.filter((item) => !replacementRows.some((row) => item.original === row.original && item.replacement === row.replacement)),
        ...replacementRows,
      ]);
    }
    setTermReplacementDrafts((current) => {
      const next = { ...current };
      delete next[term.normalized];
      return next;
    });
    const firstOccurrence = term.occurrences[0];
    if (firstOccurrence) selectSubtitle(firstOccurrence);
  };

  const rememberSelectedSubtitleText = () => {
    const selectedText = selectedTextFromElement(document.activeElement) || selectedTextFromWindow();
    if (selectedText) lastSelectedSubtitleTextRef.current = selectedText;
  };

  const openSubtitleReplaceDialog = () => {
    rememberSelectedSubtitleText();
    if (selectedSubtitle && editingSubtitleIndex === selectedSubtitle.index) {
      updateSubtitleDraft(selectedSubtitle, { text_final: currentSubtitleDraftText });
      setEditingSubtitleIndex(null);
    }
    const seed = (
      selectedTextFromElement(document.activeElement)
      || selectedTextFromElement(currentSubtitleInputRef.current)
      || selectedTextFromWindow()
      || lastSelectedSubtitleTextRef.current
      || ""
    ).trim().slice(0, 80);
    setSubtitleReplaceDialog({
      find: seed,
      replacement: "",
      matchCount: countSubtitleMatches(projection.remapped, seed),
    });
  };

  const updateSubtitleReplaceDialog = (patch: Partial<SubtitleReplaceDialogState>) => {
    setSubtitleReplaceDialog((current) => {
      if (!current) return current;
      const next = { ...current, ...patch };
      next.matchCount = countSubtitleMatches(projection.remapped, next.find.trim());
      return next;
    });
  };

  const applySubtitleReplacement = (findValue?: string, replacementValue?: string, options?: { clearManualDraft?: boolean; closeDialog?: boolean }) => {
    const find = (findValue ?? subtitleReplaceDialog?.find ?? "").trim();
    const replacement = (replacementValue ?? subtitleReplaceDialog?.replacement ?? "").trim();
    if (!find || !replacement || find === replacement) return;
    const pattern = new RegExp(escapeRegExp(find), "g");
    const changes: Array<{ subtitle: JobManualEditSubtitle; text_final: string; occurrences: number }> = [];
    for (const subtitle of projection.remapped) {
      const text = subtitleText(subtitle);
      if (!text.includes(find)) continue;
      changes.push({
        subtitle,
        text_final: text.replace(pattern, replacement),
        occurrences: text.split(find).length - 1,
      });
    }
    if (!changes.length) return;
    const matchCount = changes.reduce((total, item) => total + item.occurrences, 0);
    recordUndoSnapshot();
    setSubtitleDrafts((current) => {
      const next = { ...current };
      for (const change of changes) {
        next[change.subtitle.index] = {
          ...(next[change.subtitle.index] ?? {}),
          text_final: change.text_final,
        };
      }
      return next;
    });
    setSubtitleReplacementHistory((current) => [
      ...current.filter((item) => !(item.original === find && item.replacement === replacement)),
      { original: find, replacement, occurrence_count: matchCount },
    ]);
    lastSelectedSubtitleTextRef.current = replacement;
    if (options?.clearManualDraft) {
      setManualTermDraft("");
      setManualReplacementDraft("");
    }
    if (options?.closeDialog ?? !findValue) setSubtitleReplaceDialog(null);
    selectSubtitle(changes[0].subtitle);
  };

  const selectAdjacentSubtitle = (direction: -1 | 1) => {
    if (!projection.remapped.length) return;
    const currentIndex = selectedSubtitle
      ? projection.remapped.findIndex((subtitle) => subtitle.index === selectedSubtitle.index)
      : activeSubtitleIndex;
    const nextIndex = clamp(currentIndex >= 0 ? currentIndex + direction : direction > 0 ? 0 : projection.remapped.length - 1, 0, projection.remapped.length - 1);
    const nextSubtitle = projection.remapped[nextIndex];
    if (nextSubtitle) selectSubtitle(nextSubtitle);
  };

  const nudgeSelectedSubtitle = (delta: number) => {
    if (!selectedSubtitle) return;
    const nextStart = clamp(selectedSubtitle.start_time + delta, 0, totalOutputDuration);
    const nextEnd = clamp(selectedSubtitle.end_time + delta, nextStart + MIN_SUBTITLE_DURATION_SEC, totalOutputDuration || selectedSubtitle.end_time + delta);
    updateSubtitleDraft(selectedSubtitle, {
      start_time: Number(nextStart.toFixed(3)),
      end_time: Number(nextEnd.toFixed(3)),
    });
  };

  const setSelectedSubtitleBoundaryFromPlayhead = (boundary: "start" | "end") => {
    if (!selectedSubtitle) return;
    const playhead = clamp(currentOutputTime, 0, totalOutputDuration || currentOutputTime);
    if (boundary === "start") {
      const nextStart = clamp(playhead, 0, Math.max(0, selectedSubtitle.end_time - MIN_SUBTITLE_DURATION_SEC));
      updateSubtitleDraft(selectedSubtitle, { start_time: Number(nextStart.toFixed(3)) });
      return;
    }
    const nextEnd = clamp(
      playhead,
      selectedSubtitle.start_time + MIN_SUBTITLE_DURATION_SEC,
      totalOutputDuration || selectedSubtitle.start_time + MIN_SUBTITLE_DURATION_SEC,
    );
    updateSubtitleDraft(selectedSubtitle, { end_time: Number(nextEnd.toFixed(3)) });
  };

  const splitSelectedSubtitle = () => {
    if (!selectedSubtitle) return;
    const text = subtitleText(selectedSubtitle).trim();
    if (text.length < 2 || selectedSubtitle.end_time <= selectedSubtitle.start_time + MIN_SUBTITLE_DURATION_SEC * 2) return;
    const splitAt = Math.max(1, Math.ceil(text.length / 2));
    const firstText = text.slice(0, splitAt).trim() || text;
    const secondText = text.slice(splitAt).trim() || text;
    const midpoint = Number(((selectedSubtitle.start_time + selectedSubtitle.end_time) / 2).toFixed(3));
    const existingIndexes = [
      ...projection.remapped.map((subtitle) => subtitle.index),
      ...Object.keys(subtitleDrafts).map((index) => Number(index)),
    ];
    const nextIndex = Math.max(0, ...existingIndexes) + 1;
    recordUndoSnapshot();
    setSubtitleDrafts((current) => ({
      ...current,
      [selectedSubtitle.index]: {
        ...current[selectedSubtitle.index],
        end_time: midpoint,
        text_final: firstText,
      },
      [nextIndex]: {
        start_time: midpoint,
        end_time: selectedSubtitle.end_time,
        text_final: secondText,
        virtual: true,
      },
    }));
    setSelectedSubtitleIndex(nextIndex);
  };

  const mergeSelectedSubtitleWithNext = () => {
    if (!selectedSubtitle) return;
    const index = projection.remapped.findIndex((subtitle) => subtitle.index === selectedSubtitle.index);
    const nextSubtitle = index >= 0 ? projection.remapped[index + 1] : null;
    if (!nextSubtitle) return;
    recordUndoSnapshot();
    setSubtitleDrafts((current) => ({
      ...current,
      [selectedSubtitle.index]: {
        ...current[selectedSubtitle.index],
        end_time: nextSubtitle.end_time,
        text_final: `${subtitleText(selectedSubtitle).trim()}${subtitleText(nextSubtitle).trim()}`.trim(),
      },
      [nextSubtitle.index]: {
        ...current[nextSubtitle.index],
        delete: true,
      },
    }));
    setSelectedSubtitleIndex(selectedSubtitle.index);
  };

  const shiftAllSubtitles = (delta: number) => {
    if (!projection.remapped.length) return;
    recordUndoSnapshot();
    setSubtitleDrafts((current) => {
      const next = { ...current };
      for (const subtitle of projection.remapped) {
        const start = clamp(subtitle.start_time + delta, 0, totalOutputDuration);
        const end = clamp(subtitle.end_time + delta, start + MIN_SUBTITLE_DURATION_SEC, totalOutputDuration || subtitle.end_time + delta);
        next[subtitle.index] = {
          ...next[subtitle.index],
          start_time: Number(start.toFixed(3)),
          end_time: Number(end.toFixed(3)),
        };
      }
      return next;
    });
  };

  const enforceSubtitleGaps = () => {
    let cursor = 0;
    recordUndoSnapshot();
    setSubtitleDrafts((current) => {
      const next = { ...current };
      for (const subtitle of projection.remapped) {
        const start = clamp(Math.max(subtitle.start_time, cursor), 0, totalOutputDuration);
        const end = clamp(
          Math.max(subtitle.end_time, start + MIN_SUBTITLE_DURATION_SEC),
          start + MIN_SUBTITLE_DURATION_SEC,
          totalOutputDuration || subtitle.end_time,
        );
        next[subtitle.index] = {
          ...next[subtitle.index],
          start_time: Number(start.toFixed(3)),
          end_time: Number(end.toFixed(3)),
        };
        cursor = end + MIN_SUBTITLE_GAP_SEC;
      }
      return next;
    });
  };

  const resetSubtitleDraft = (subtitle: JobManualEditSubtitle) => {
    recordUndoSnapshot();
    setSubtitleDrafts((current) => {
      const next = { ...current };
      delete next[subtitle.index];
      return next;
    });
  };

  const restoreDeletedSubtitle = (subtitle: VisibleSubtitleRow) => {
    recordUndoSnapshot();
    if (subtitle.restoreRanges?.length) {
      pauseEditedTimeline();
      rememberManualSmartCutRestores(subtitle.restoreRanges);
      setSegments((current) => addSourceRangesToSegments(current, subtitle.restoreRanges ?? [], session.source_duration_sec));
      jumpToSourceTime(subtitle.restoreRanges[0].start);
    }
    setSubtitleDrafts((current) => {
      const next = { ...current };
      delete next[subtitle.index];
      return next;
    });
    setSelectedSubtitleIndex(subtitle.index);
  };

  useEffect(() => {
    if (!session.editable || !baseKeepSegments.length) return;
    const signature = [
      session.job_id,
      session.timeline_id,
      session.timeline_version,
      JSON.stringify(baseKeepSegments.map((segment) => [segment.start, segment.end])),
      smartCutRulesSignature(smartCutRules),
      JSON.stringify(smartCutManagedRanges.map((range) => [range.kind, range.start, range.end])),
      JSON.stringify(smartCutRuleRanges.map((range) => [range.kind, range.start, range.end])),
      JSON.stringify(manualSmartCutRestoreRanges.map((range) => [range.start, range.end])),
      JSON.stringify(sourceSpeechProtectionRanges.map((range) => [range.start, range.end])),
    ].join(":");
    if (signature === lastAutoSmartCutSignatureRef.current) return;
    lastAutoSmartCutSignatureRef.current = signature;
    applySmartCutRuleRanges(smartCutRuleRanges, smartCutManagedRanges);
  }, [baseKeepSegments, manualSmartCutRestoreRanges, session.editable, session.job_id, session.source_duration_sec, session.timeline_id, session.timeline_version, smartCutManagedRanges, smartCutRuleRanges, smartCutRules, sourceSilenceRanges, sourceSpeechProtectionRanges, sourceTranscriptSubtitles]);

  const handleApply = () => {
    if (!onApply || !effectiveSegments.length) return;
    if (!hasMaterialEdits) return;
    const confirmed = window.confirm(
      [
        "确认保存手动调整？",
        `保存类型：${savePlanLabel}`,
        `输出时长变化：${outputDurationDeltaLabel}`,
        `字幕修改：${subtitleOverrides.length} 条`,
        saveImpactSummary,
      ].join("\n"),
    );
    if (!confirmed) return;
    onApply(manualEditorPayload);
  };

  useEffect(() => {
    if (selectedSubtitleIndex != null || editingSubtitleIndex != null) return;
    if (!activeSubtitle) return;
    const list = subtitleListRef.current;
    const chip = subtitleChipRefs.current.get(activeSubtitle.index);
    if (!list || !chip) return;
    if (typeof chip.scrollIntoView !== "function") return;
    chip.scrollIntoView({ block: "nearest" });
  }, [activeSubtitle?.index, editingSubtitleIndex, selectedSubtitleIndex]);

  useEffect(() => {
    if (!transcriptSelection) return;
    const refreshed = transcriptSelectionFromTokenRange(
      transcriptTokens,
      transcriptSelection.startTokenIndex,
      transcriptSelection.endTokenIndex,
    );
    setTranscriptSelection(refreshed);
  }, [transcriptTokens]);

  useEffect(() => {
    if (activeTranscriptTokenIndex < 0) return;
    const token = transcriptTokenRefs.current.get(activeTranscriptTokenIndex);
    if (!token || typeof token.scrollIntoView !== "function") return;
    token.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeTranscriptTokenIndex]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (selectedSubtitleIndex == null && editingSubtitleIndex == null) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("[data-subtitle-selection-scope='true']")) return;
      clearSubtitleSelection();
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [currentSubtitleDraftText, editingSubtitleIndex, projection.remapped, selectedSubtitleIndex]);

  useEffect(() => {
    if (!onAutoSave || autosaving || !session.editable || !effectiveSegments.length) return undefined;
    const sessionKey = [
      session.job_id,
      session.timeline_id,
      session.timeline_version,
      session.render_plan_version ?? "",
      session.draft_saved_at ?? "",
    ].join(":");
    const signature = JSON.stringify(manualEditorPayload);
    if (autoSaveSessionKeyRef.current !== sessionKey) {
      autoSaveSessionKeyRef.current = sessionKey;
      lastAutoSaveSignatureRef.current = signature;
      return undefined;
    }
    if (signature === lastAutoSaveSignatureRef.current) return undefined;
    const timeout = window.setTimeout(() => {
      lastAutoSaveSignatureRef.current = signature;
      onAutoSave(manualEditorPayload);
    }, 1200);
    return () => window.clearTimeout(timeout);
  }, [autosaving, effectiveSegments.length, manualEditorPayload, onAutoSave, session.draft_saved_at, session.editable, session.job_id, session.render_plan_version, session.timeline_id, session.timeline_version]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const textEntryTarget = isTextEntryTarget(event.target);
      const saveShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s";
      const undoShortcut = (event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "z";
      if (saveShortcut) {
        event.preventDefault();
        if (session.editable && !saving && onApply) handleApply();
        return;
      }
      if (undoShortcut) {
        if (textEntryTarget) return;
        event.preventDefault();
        undoLastEdit();
        return;
      }
      if (textEntryTarget) return;

      if (event.code === "Space") {
        event.preventDefault();
        toggleEditedTimelinePlayback();
        return;
      }

      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const step = event.altKey ? 1 / 30 : event.shiftKey ? 5 : 1;
        jumpToSourceTime(currentSourceTime + direction * step);
        return;
      }

      if (event.code === "BracketLeft" || event.code === "BracketRight") {
        event.preventDefault();
        const direction = event.code === "BracketRight" ? 1 : -1;
        nudgeSelectedSubtitle(direction * (event.altKey ? 0.01 : 0.1));
        return;
      }

      if (event.code === "KeyA" || event.code === "KeyS") {
        event.preventDefault();
        setSelectedSubtitleBoundaryFromPlayhead(event.code === "KeyA" ? "start" : "end");
        return;
      }

      if (event.code === "KeyJ" || event.code === "KeyK") {
        event.preventDefault();
        selectAdjacentSubtitle(event.code === "KeyJ" ? -1 : 1);
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    currentSourceTime,
    currentOutputTime,
    effectiveSegments.length,
    handleApply,
    hasMaterialEdits,
    nudgeSelectedSubtitle,
    onApply,
    outputDurationDeltaLabel,
    selectAdjacentSubtitle,
    setSelectedSubtitleBoundaryFromPlayhead,
    saveImpactSummary,
    savePlanLabel,
    saving,
    manualEditorPayload,
    session.editable,
    baseKeepSegments.length,
    subtitleOverrides.length,
  ]);

  const previewDisabled = !previewVideoUrl;
  useEffect(() => {
    const dock = previewDockRef.current;
    const frame = dock?.querySelector<HTMLElement>(".manual-editor-video-frame") ?? null;
    if (!dock || !frame || previewDisabled) {
      setPreviewFrameHeight(null);
      return;
    }

    const updatePreviewFrameHeight = () => {
      const nextHeight = Math.max(280, Math.round(frame.getBoundingClientRect().height));
      setPreviewFrameHeight((current) => (current != null && Math.abs(current - nextHeight) < 2 ? current : nextHeight));
    };

    updatePreviewFrameHeight();
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updatePreviewFrameHeight);
    resizeObserver?.observe(frame);
    window.addEventListener("resize", updatePreviewFrameHeight);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updatePreviewFrameHeight);
    };
  }, [currentVideoRotation, currentVideoTransform.aspect_ratio, previewDisabled, previewVideoSourceKey, sourceVideoSize]);

  useEffect(() => {
    const updateFloatingState = () => {
      const dock = previewDockRef.current;
      if (!dock || previewDisabled) {
        setIsPreviewFloating(false);
        setPreviewDockHeight(null);
        return;
      }

      const rect = dock.getBoundingClientRect();
      const nextFloating = rect.bottom < 96;
      setIsPreviewFloating(nextFloating);
      setPreviewDockHeight((currentHeight) => {
        if (!nextFloating) return null;
        return currentHeight ?? Math.max(180, Math.round(rect.height));
      });
      const frame = dock.querySelector<HTMLElement>(".manual-editor-video-frame");
      const frameRect = frame?.getBoundingClientRect();
      if (nextFloating && frameRect) {
        setFloatingPreviewPosition((current) => (
          current ? clampFloatingPreviewPosition(current.x, current.y, frameRect.width, frameRect.height) : current
        ));
      }
    };

    updateFloatingState();
    window.addEventListener("scroll", updateFloatingState, { passive: true });
    window.addEventListener("resize", updateFloatingState);
    return () => {
      window.removeEventListener("scroll", updateFloatingState);
      window.removeEventListener("resize", updateFloatingState);
    };
  }, [previewDisabled, previewVideoSourceKey, session.job_id]);

  useEffect(() => {
    setFloatingPreviewPosition(null);
    floatingPreviewDragRef.current = null;
  }, [session.job_id, previewVideoSourceKey]);

  useEffect(() => {
    setPreviewVideoLoadError(null);
    setPreviewVideoLoadProgress(null);
    setPreviewVideoLoading(Boolean(previewVideoUrl));
    setPreviewVideoLoadingLabel("正在载入视频");
  }, [previewVideoSourceKey, previewVideoUrl]);

  const buildRotatedPreviewStyle = (rotationValue: number) => {
    const rotation = normalizeRotationValue(rotationValue);
    const rawWidth = Math.max(1, sourceVideoSize?.width || 16);
    const rawHeight = Math.max(1, sourceVideoSize?.height || 9);
    const rawAspect = rawWidth / rawHeight;
    const frameAspectValue = currentVideoTransform.aspect_ratio === "source" ? 16 / 9 : aspectRatioNumber(currentVideoTransform.aspect_ratio);
    const quarterTurn = rotation === 90 || rotation === 270;
    const displayedAspect = quarterTurn ? 1 / rawAspect : rawAspect;
    let stageWidth: number;
    let stageHeight: number;
    if (displayedAspect >= frameAspectValue) {
      stageWidth = 1;
      stageHeight = frameAspectValue / displayedAspect;
    } else {
      stageWidth = displayedAspect / frameAspectValue;
      stageHeight = 1;
    }
    const unrotatedWidth = quarterTurn ? stageHeight / stageWidth / frameAspectValue : 1;
    const unrotatedHeight = quarterTurn ? (stageWidth / stageHeight) * frameAspectValue : 1;
    const boundedWidth = Math.min(900, Math.max(260, Math.round(frameAspectValue * 460)));
    return {
      "--manual-video-rotation": `${rotation}deg`,
      "--manual-video-stage-width": `${stageWidth * 100}%`,
      "--manual-video-stage-height": `${stageHeight * 100}%`,
      "--manual-video-width": `${unrotatedWidth * 100}%`,
      "--manual-video-height": `${unrotatedHeight * 100}%`,
      aspectRatio: currentVideoTransform.aspect_ratio === "source" ? "16 / 9" : aspectRatioCssValue(currentVideoTransform.aspect_ratio),
      width: `min(100%, ${boundedWidth}px)`,
    } as CSSProperties;
  };
  const rotatedPreviewStyle = buildRotatedPreviewStyle(currentVideoRotation);
  const floatingPreviewFrameStyle = isPreviewFloating && floatingPreviewPosition
    ? {
        ...rotatedPreviewStyle,
        left: `${floatingPreviewPosition.x}px`,
        top: `${floatingPreviewPosition.y}px`,
        right: "auto",
        bottom: "auto",
      } as CSSProperties
    : rotatedPreviewStyle;
  const subtitleStageStyle = previewFrameHeight
    ? { "--manual-subtitle-stage-height": `${previewFrameHeight}px` } as CSSProperties
    : undefined;
  const rotationDialogPreviewStyle = {
    ...buildRotatedPreviewStyle(rotationDraft),
    width: "min(100%, 420px)",
    maxHeight: "260px",
  } as CSSProperties;

  const beginFloatingPreviewDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!isPreviewFloating) return;
    const frame = event.currentTarget.closest(".manual-editor-video-frame") as HTMLElement | null;
    if (!frame) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = frame.getBoundingClientRect();
    floatingPreviewDragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setFloatingPreviewPosition(clampFloatingPreviewPosition(rect.left, rect.top, rect.width, rect.height));
  };

  const dragFloatingPreview = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = floatingPreviewDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    setFloatingPreviewPosition(clampFloatingPreviewPosition(
      event.clientX - drag.offsetX,
      event.clientY - drag.offsetY,
      drag.width,
      drag.height,
    ));
  };

  const endFloatingPreviewDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = floatingPreviewDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    floatingPreviewDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  return (
    <section className="detail-block manual-editor-section">
      <div className="toolbar">
        <div>
          <div className="detail-key">手动调整模式</div>
          <div className="muted compact-top">
            基于完整源片做人工删段和边界微调；剪辑痕迹覆盖在源片时间轴上，输出成片预览只作为派生检查。保存后会从渲染开始重跑，继续生成特效和数字人版本。
          </div>
        </div>
        <div className="toolbar">
          <span className={classNames("status-pill", session.editable ? "done" : "pending")}>
            {session.editable ? "可编辑" : "只读"}
          </span>
          <span className="status-pill pending">{savePlanLabel}</span>
          <span className={classNames("status-pill", autosaving ? "running" : "done")}>
            {autosaving ? "自动保存中" : visibleDraftSavedAt ? "草稿已保存" : "自动保存开启"}
          </span>
          <span className="status-pill pending">时间线 v{session.timeline_version}</span>
        </div>
      </div>

      <section className={classNames("manual-editor-change-list", !hasManualEditChangeListItems && "empty")} aria-label="改动清单">
        <div className="manual-editor-change-list-head">
          <div>
            <strong>改动清单</strong>
            <div className="muted compact-top">当前草稿会保存的剪辑、画面、字幕和摘要变化。</div>
          </div>
          <span className={classNames("status-pill", hasManualEditChangeListItems ? "pending" : "done")}>
            {hasManualEditChangeListItems ? `${manualEditChangeList.length} 项改动` : "暂无改动"}
          </span>
        </div>
        <ul className="manual-editor-change-list-items">
          {manualEditChangeList.map((item) => (
            <li key={item.key} className={classNames("manual-editor-change-list-item", item.tone)}>
              <span className="manual-editor-change-list-marker" aria-hidden="true" />
              <div className="manual-editor-change-list-main">
                <strong>{item.title}</strong>
                <span>{item.detail}</span>
              </div>
              {item.meta ? <span className="manual-editor-change-list-meta">{item.meta}</span> : null}
            </li>
          ))}
        </ul>
      </section>

      {session.detail ? <div className="notice compact-top">{session.detail}</div> : null}
      {subtitleReplaceDialog ? (
        <div className="manual-editor-floating-backdrop" role="presentation">
          <section className="manual-editor-floating-panel manual-editor-replace-panel" role="dialog" aria-modal="true" aria-label="一键替换字幕内容">
            <div className="manual-editor-preview-head">
              <div>
                <strong>一键替换</strong>
                <div className="muted compact-top">替换会写入字幕草稿，保存后作为校对习惯学习。</div>
              </div>
              <span className="status-pill pending">匹配 {subtitleReplaceDialog.matchCount}</span>
            </div>
            <label className="form-field">
              <span className="field-label">需要替换的内容</span>
              <input
                className="input"
                value={subtitleReplaceDialog.find}
                autoFocus
                onChange={(event) => updateSubtitleReplaceDialog({ find: event.target.value })}
              />
            </label>
            <label className="form-field">
              <span className="field-label">替换为</span>
              <input
                className="input"
                value={subtitleReplaceDialog.replacement}
                onChange={(event) => updateSubtitleReplaceDialog({ replacement: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
                  event.preventDefault();
                  applySubtitleReplacement();
                }}
              />
            </label>
            <div className="manual-editor-replace-actions">
              <button type="button" className="button ghost" onClick={() => setSubtitleReplaceDialog(null)}>
                取消
              </button>
              <button
                type="button"
                className="button primary"
                disabled={!subtitleReplaceDialog.find.trim() || !subtitleReplaceDialog.replacement.trim() || subtitleReplaceDialog.find.trim() === subtitleReplaceDialog.replacement.trim() || subtitleReplaceDialog.matchCount <= 0}
                onClick={() => applySubtitleReplacement()}
              >
                全部替换
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {rotationDialogOpen ? (
        <div className="manual-editor-floating-backdrop" role="presentation">
          <section className="manual-editor-floating-panel" role="dialog" aria-modal="true" aria-label="旋转画面">
            <div className="manual-editor-preview-head">
              <div>
                <strong>旋转画面</strong>
                <div className="muted compact-top">用于修正方向错误的视频。应用后会立即更新预览，并自动保存到手动调整草稿。</div>
              </div>
              <button type="button" className="button ghost" onClick={() => setRotationDialogOpen(false)}>
                关闭
              </button>
            </div>

            <div className="manual-editor-rotation-preview" style={rotationDialogPreviewStyle}>
              <div className="manual-editor-video-stage">
                <video key={previewVideoSourceKey} muted playsInline preload="metadata" onLoadedMetadata={rememberVideoMetadata}>
                  {previewVideoSources.map((source) => (
                    <source key={`${source.url}:${source.type || ""}`} src={source.url} type={source.type} />
                  ))}
                </video>
              </div>
            </div>

            <div className="manual-editor-actions">
              <button type="button" className="button ghost" disabled={!onDetectRotation || detectingRotation} onClick={() => void detectRotation()}>
                {detectingRotation ? "检测中..." : "自动检测"}
              </button>
              {ROTATION_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={classNames("button", normalizeRotationValue(rotationDraft) === option ? "primary" : "ghost")}
                  onClick={() => setRotationDraft(option)}
                >
                  {option}°
                </button>
              ))}
            </div>

            <label className="form-field">
              <span className="field-label">手动角度（按 90° 档位归一化用于最终渲染）</span>
              <input
                className="input"
                type="number"
                step={90}
                min={0}
                max={270}
                value={rotationDraft}
                onChange={(event) => setRotationDraft(Number(event.target.value || 0))}
              />
            </label>
            {rotationDetectMessage ? <div className="notice compact-top">{rotationDetectMessage}</div> : null}

            <div className="manual-editor-actions">
              <button type="button" className="button primary" onClick={applyRotationDraft}>
                应用
              </button>
              <button type="button" className="button ghost" onClick={() => setRotationDialogOpen(false)}>
                取消
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {resolutionDialogOpen ? (
        <div className="manual-editor-floating-backdrop" role="presentation">
          <section className="manual-editor-floating-panel" role="dialog" aria-modal="true" aria-label="调整分辨率">
            <div className="manual-editor-preview-head">
              <div>
                <strong>调整分辨率</strong>
                <div className="muted compact-top">设置输出画面比例和分辨率。默认完整显示画面，比例变化会用黑边补齐，不裁切原画面。</div>
              </div>
              <button type="button" className="button ghost" onClick={() => setResolutionDialogOpen(false)}>
                关闭
              </button>
            </div>

            <div className="manual-editor-resolution-preview">
              <div style={{ aspectRatio: aspectRatioCssValue(resolutionDraft.aspect_ratio) }}>
                <span>{ASPECT_RATIO_OPTIONS.find((option) => option.value === resolutionDraft.aspect_ratio)?.label ?? "跟随原片"}</span>
                <small>
                  {resolutionDraft.resolution_mode === "specified"
                    ? RESOLUTION_PRESET_OPTIONS.find((option) => option.value === resolutionDraft.resolution_preset)?.label
                    : "原分辨率"}
                </small>
              </div>
            </div>

            <div className="manual-editor-setting-grid">
              <label className="form-field">
                <span className="field-label">画面比例</span>
                <select
                  className="input"
                  value={resolutionDraft.aspect_ratio || "source"}
                  onChange={(event) => updateResolutionDraft({ aspect_ratio: event.target.value })}
                >
                  {ASPECT_RATIO_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="form-field">
                <span className="field-label">分辨率模式</span>
                <select
                  className="input"
                  value={resolutionDraft.resolution_mode || "source"}
                  onChange={(event) => updateResolutionDraft({ resolution_mode: event.target.value })}
                >
                  {RESOLUTION_MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="form-field">
                <span className="field-label">指定分辨率</span>
                <select
                  className="input"
                  value={resolutionDraft.resolution_preset || "1080p"}
                  disabled={resolutionDraft.resolution_mode !== "specified"}
                  onChange={(event) => updateResolutionDraft({ resolution_preset: event.target.value })}
                >
                  {RESOLUTION_PRESET_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="manual-editor-actions">
              <button type="button" className="button primary" onClick={applyResolutionDraft}>
                应用
              </button>
              <button type="button" className="button ghost" onClick={() => setResolutionDialogOpen(false)}>
                取消
              </button>
            </div>
          </section>
        </div>
      ) : null}
      <div className="manual-editor-shortcuts" aria-label="手动编辑快捷键">
        <span><kbd>Space</kbd> 播放/暂停输出预览</span>
        <span><kbd>←/→</kbd> 跳 1s</span>
        <span><kbd>Alt</kbd> + <kbd>←/→</kbd> 逐帧</span>
        <span><kbd>[</kbd>/<kbd>]</kbd> 字幕 ±100ms</span>
        <span><kbd>Alt</kbd> + <kbd>[</kbd>/<kbd>]</kbd> 字幕 ±10ms</span>
        <span><kbd>A</kbd>/<kbd>S</kbd> 设字幕起止</span>
        <span><kbd>J</kbd>/<kbd>K</kbd> 上/下字幕</span>
        <span><kbd>Ctrl/⌘</kbd> + <kbd>Z</kbd> 撤销</span>
        <span><kbd>Ctrl/⌘</kbd> + <kbd>S</kbd> {renderActionLabel}</span>
      </div>

      <div className="manual-editor-stats top-gap">
        <article className="activity-card">
          <div className="muted">输出时长</div>
          <strong>{formatSeconds(totalOutputDuration)}</strong>
        </article>
        <article className="activity-card">
          <div className="muted">映射字幕</div>
          <strong>{projection.remapped.length}</strong>
        </article>
        <article className="activity-card">
          <div className="muted">原片时长</div>
          <strong>{formatSeconds(session.source_duration_sec)}</strong>
        </article>
      </div>
      <div className={classNames("manual-editor-save-impact", hasTimelineEdits && "timeline", hasVideoTransformEdits && !hasTimelineEdits && "timeline", subtitleOverrides.length > 0 && !hasTimelineEdits && !hasVideoTransformEdits && "subtitle")}>
        <strong>{savePlanLabel}</strong>
        <span>{saveImpactSummary}</span>
        <span>输出时长变化 {outputDurationDeltaLabel}</span>
        <span>画面旋转 {baseVideoRotation}°{" -> "}{currentVideoRotation}°</span>
        <span>画面比例 {baseVideoTransform.aspect_ratio}{" -> "}{currentVideoTransform.aspect_ratio}</span>
        <span>分辨率 {currentVideoTransform.resolution_mode === "specified" ? currentVideoTransform.resolution_preset : "原片"}</span>
        <span>字幕修改 {subtitleOverrides.length} 条</span>
        {currentVideoSummary ? <span>视频摘要 强证据</span> : null}
        {visibleDraftSavedAt ? <span>上次草稿 {new Date(visibleDraftSavedAt).toLocaleTimeString()}</span> : null}
      </div>

      <section className="manual-editor-evidence-panel">
        <div className="manual-editor-preview-head">
          <div>
            <strong>视频摘要</strong>
            <div className="muted compact-top">人工填写后会自动保存，并作为强证据进入自动审核、字幕校对和后续文案链路。</div>
          </div>
          <span className={classNames("status-pill", currentVideoSummary ? "done" : "pending")}>
            {currentVideoSummary ? "强证据已填写" : "待填写"}
          </span>
        </div>
        <textarea
          className="input textarea manual-editor-summary-input"
          rows={4}
          value={videoSummary}
          onChange={(event) => setVideoSummary(event.target.value)}
          placeholder="用一两句话确认视频主体、核心内容、关键误读点或必须保留的信息。"
        />
      </section>

      <div className="manual-editor-grid top-gap">
        <section className="manual-editor-preview">
          <div className="manual-editor-preview-head">
            <strong>{job?.source_name ?? session.source_name}</strong>
          </div>
          <div className="manual-editor-preview-main">
            <div className="manual-editor-video-column">
              {previewDisabled ? (
                <div className="notice">{previewDisabledMessage}</div>
              ) : (
                <div
                  ref={previewDockRef}
                  className={classNames("manual-editor-video-dock", isPreviewFloating && "floating")}
                  style={isPreviewFloating && previewDockHeight ? { minHeight: `${previewDockHeight}px` } : undefined}
                >
                  <div
                    className={classNames("manual-editor-video-frame", isPreviewFloating && floatingPreviewPosition && "positioned")}
                    style={floatingPreviewFrameStyle}
                    role="button"
                    tabIndex={0}
                    onClick={toggleEditedTimelinePlayback}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      toggleEditedTimelinePlayback();
                    }}
                    aria-label={isPreviewPlaying ? "暂停预览" : "播放输出预览"}
                  >
                    <div className="manual-editor-video-stage">
                      <video
                        key={previewVideoSourceKey}
                        ref={videoRef}
                        className="manual-editor-video"
                        preload="metadata"
                        playsInline
                        onLoadStart={() => {
                          setPreviewVideoLoadError(null);
                          setPreviewVideoLoading(true);
                          setPreviewVideoLoadingLabel("正在载入视频");
                          setPreviewVideoLoadProgress(null);
                        }}
                        onLoadedMetadata={(event) => {
                          rememberVideoMetadata(event);
                          fallbackPreviewElementVolume(event.currentTarget, previewVolume, previewMuted, previewAutoVolumeEnabled);
                          applyPreviewAudioSettings(previewVolume, previewMuted, previewAutoVolumeEnabled, false);
                        }}
                        onLoadedData={(event) => {
                          setPreviewVideoLoadError(null);
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                        }}
                        onProgress={(event) => updatePreviewVideoLoadProgress(event.currentTarget)}
                        onCanPlay={(event) => {
                          setPreviewVideoLoadError(null);
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                          const pendingSeek = pendingPreviewSeekRef.current;
                          if (pendingSeek != null) {
                            void seekPreviewToSourceTime(event.currentTarget, pendingSeek);
                          }
                        }}
                        onWaiting={(event) => {
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(true);
                          setPreviewVideoLoadingLabel("正在缓冲视频");
                        }}
                        onPlaying={(event) => {
                          clearOutputPlaybackSeek();
                          setPreviewVideoLoadError(null);
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                          setIsPreviewPlaying(true);
                          timelinePlaybackRef.current = true;
                          setPreviewPlaybackMode("output");
                          startPreviewClock();
                        }}
                        onPlay={() => {
                          setIsPreviewPlaying(true);
                          timelinePlaybackRef.current = true;
                          setPreviewPlaybackMode("output");
                          startPreviewClock();
                        }}
                        onError={handlePreviewVideoError}
                        onTimeUpdate={syncPreviewTime}
                        onSeeked={(event) => {
                          syncPreviewTime();
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          if (event.currentTarget.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
                            setPreviewVideoLoading(false);
                            setPreviewVideoLoadError(null);
                          }
                          if (outputPlaybackSeekInProgressRef.current && timelinePlaybackRef.current && !event.currentTarget.paused) {
                            clearOutputPlaybackSeek();
                          }
                        }}
                        onPause={(event) => {
                          const video = event.currentTarget;
                          if (timelinePlaybackRef.current && !video.ended && projection.ranges.length) {
                            const decision = resolveEditedPlaybackSyncDecision(Number(video.currentTime || 0), projection.ranges);
                            if (decision.action === "seek") {
                              seekOutputPlaybackToSourceTime(video, decision.sourceTime);
                              return;
                            }
                            if (outputPlaybackSeekInProgressRef.current) {
                              resumeOutputPlaybackAfterSeek(video);
                              return;
                            }
                          }
                          if (video.paused) {
                            clearOutputPlaybackSeek();
                            setPreviewVideoLoading(false);
                            timelinePlaybackRef.current = false;
                            setIsPreviewPlaying(false);
                            setPreviewPlaybackMode(null);
                            stopPreviewClock();
                          }
                        }}
                        onEnded={() => {
                          clearOutputPlaybackSeek();
                          timelinePlaybackRef.current = false;
                          setIsPreviewPlaying(false);
                          setPreviewPlaybackMode(null);
                          stopPreviewClock();
                        }}
                      >
                        {previewVideoSources.map((source) => (
                          <source key={`${source.url}:${source.type || ""}`} src={source.url} type={source.type} />
                        ))}
                      </video>
                      {previewSubtitleText ? (
                        <div className="manual-editor-video-subtitle" aria-live="polite">
                          {previewSubtitleText}
                        </div>
                      ) : null}
                      {previewVideoLoading && !previewVideoLoadError ? (
                        <div className="manual-editor-video-loading" onClick={(event) => event.stopPropagation()}>
                          <div className="manual-editor-video-loading-label">
                            <span>{previewVideoLoadingLabel}</span>
                            <span>{previewVideoLoadProgress == null ? "准备中" : `${Math.round(previewVideoLoadProgress * 100)}%`}</span>
                          </div>
                          <div
                            className={classNames("manual-editor-video-loading-bar", previewVideoLoadProgress == null && "indeterminate")}
                            role="progressbar"
                            aria-label={previewVideoLoadingLabel}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={previewVideoLoadProgress == null ? undefined : Math.round(previewVideoLoadProgress * 100)}
                          >
                            <span style={previewVideoLoadProgress == null ? undefined : { width: `${Math.round(previewVideoLoadProgress * 100)}%` }} />
                          </div>
                        </div>
                      ) : null}
                    </div>
                    {previewVideoLoadError ? (
                      <div className="manual-editor-video-error" onClick={(event) => event.stopPropagation()}>
                        {previewVideoLoadError}
                      </div>
                    ) : null}
                    {isPreviewFloating ? (
                      <button
                        type="button"
                        className="manual-editor-preview-drag-handle"
                        aria-label="拖动悬浮预览窗口"
                        title="拖动悬浮预览窗口"
                        onClick={(event) => event.stopPropagation()}
                        onPointerDown={beginFloatingPreviewDrag}
                        onPointerMove={dragFloatingPreview}
                        onPointerUp={endFloatingPreviewDrag}
                        onPointerCancel={endFloatingPreviewDrag}
                      >
                        <span />
                        <span />
                        <span />
                      </button>
                    ) : null}
                    <div className="manual-editor-preview-controlbar" onClick={(event) => event.stopPropagation()}>
                      <button
                        type="button"
                        className="manual-editor-preview-play"
                        disabled={previewDisabled}
                        onClick={toggleEditedTimelinePlayback}
                        aria-label={isPreviewPlaying ? "暂停预览" : "播放输出预览"}
                      >
                        {isPreviewPlaying ? "暂停" : "播放输出"}
                      </button>
                      <div className="manual-editor-preview-volume" onPointerDown={(event) => event.stopPropagation()}>
                        <button
                          type="button"
                          className="manual-editor-preview-icon-button"
                          onClick={togglePreviewMuted}
                          aria-label={previewMuted || previewVolume <= 0 ? "恢复声音" : "静音"}
                        >
                          {previewMuted || previewVolume <= 0 ? "静音" : "音量"}
                        </button>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.01}
                          value={previewMuted ? 0 : previewVolume}
                          onChange={(event) => applyPreviewVolume(Number(event.target.value), false)}
                          aria-label="预览音量"
                        />
                      </div>
                      <button
                        type="button"
                        className={classNames("manual-editor-preview-auto-volume", previewAutoVolumeEnabled && "active")}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={togglePreviewAutoVolume}
                        aria-pressed={previewAutoVolumeEnabled}
                        aria-label={previewAutoVolumeEnabled ? "关闭自动平衡音量" : "开启自动平衡音量"}
                        title={previewAssets?.ready ? `测得 ${previewMeasuredLufs.toFixed(1)} LUFS，目标 ${previewTargetLufs.toFixed(0)} LUFS` : "预处理完成后使用建议音量"}
                      >
                        {previewAutoVolumeLabel}
                      </button>
                      <span>
                        源 {formatSeconds(currentSourceTime)} / {formatSeconds(sourceTimelineDuration)}
                        {activePreviewOutputTime == null ? "" : ` · 输出 ${formatSeconds(activePreviewOutputTime)}`}
                      </span>
                    </div>
                  </div>
                </div>
              )}
              {currentVideoRotation ? <div className="manual-editor-rotation-status">当前预览已顺时针旋转 {currentVideoRotation}°，该参数会自动保存并用于重渲染。</div> : null}

              <div className="manual-editor-controls">
                <button type="button" className="button primary" disabled={previewDisabled || !effectiveSegments.length} onClick={toggleEditedTimelinePlayback}>
                  {isPreviewPlaying && previewPlaybackMode === "output" ? "暂停输出预览" : "播放输出预览"}
                </button>
                <button type="button" className="button ghost" onClick={openRotationDialog}>
                  旋转画面
                </button>
                <button type="button" className="button ghost" onClick={openResolutionDialog}>
                  调整分辨率
                </button>
                <span className="muted">画面 {currentVideoRotation}° / {currentVideoTransform.aspect_ratio === "source" ? "原比例" : currentVideoTransform.aspect_ratio}</span>
              </div>
            </div>

            <div className="manual-editor-transcript-column">
              <div className="manual-editor-transcript-stage" style={subtitleStageStyle} data-subtitle-selection-scope="true">
                <div className="manual-editor-transcript-head">
                  <div>
                    <strong>全文剪辑</strong>
                  </div>
                  <span className="status-pill pending">{transcriptCharCount} 字 / {transcriptPauseCount} 停顿</span>
                </div>

                <div
                  ref={transcriptScrollRef}
                  className="manual-editor-transcript-body"
                  onMouseUp={updateTranscriptSelectionFromWindow}
                  onKeyUp={updateTranscriptSelectionFromWindow}
                  onScroll={clearTranscriptSelection}
                >
                  {transcriptTokens.map((token, index) => {
                    const selected = transcriptSelection
                      ? index >= transcriptSelection.startTokenIndex && index <= transcriptSelection.endTokenIndex
                      : false;
                    const active = index === activeTranscriptTokenIndex;
                    const cut = transcriptTokenIsCut(token);
                    const { match: smartCutMatch, kind: smartCutKind } = smartCutClassificationForToken(token, cut);
                    const smartDeleteSuggestion = smartDeleteSuggestionForToken(token);
                    const cutKind = cut ? smartCutKind ?? "manual" : null;
                    const cutReason = cutKind && cutKind !== "manual"
                      ? `${smartCutRuleLabel(cutKind)}：${smartCutRuleReason(cutKind, smartCutMatch)}`
                      : cut ? manualCutReason() : null;
                    const suggestionReason = smartDeleteSuggestion
                      ? `${smartCutRuleLabel("smart_delete")}建议：${smartCutRuleReason("smart_delete", smartDeleteSuggestion)}`
                      : null;
                    const tokenTitle = cutReason
                      ? `${cutReason}${suggestionReason ? `；${suggestionReason}` : ""} ${formatSeconds(token.start)} - ${formatSeconds(token.end)}`
                      : suggestionReason
                        ? `${suggestionReason} ${formatSeconds(token.start)} - ${formatSeconds(token.end)}`
                      : `${formatSeconds(token.start)} - ${formatSeconds(token.end)}`;
                    const breakNode = token.breakAfter === "paragraph"
                      ? (
                        <span className="manual-editor-transcript-break paragraph" aria-hidden="true">
                          <br />
                          <br />
                        </span>
                      )
                      : token.breakAfter
                        ? (
                          <span className="manual-editor-transcript-break soft" aria-hidden="true">
                            <br />
                          </span>
                        )
                        : null;
                    if (token.kind === "pause") {
                      return (
                        <Fragment key={token.key}>
                          <button
                            type="button"
                            ref={(element) => {
                              if (element) {
                                transcriptTokenRefs.current.set(index, element);
                              } else {
                              transcriptTokenRefs.current.delete(index);
                            }
                          }}
                            className={classNames("manual-editor-transcript-pause", cut && "cut", cutKind && `cut-${cutKind}`, smartDeleteSuggestion && "suggested-smart_delete", active && "active", selected && "selected")}
                            data-transcript-token-index={index}
                            onClick={() => selectTranscriptToken(index)}
                            title={cutReason || suggestionReason ? `停顿 · ${tokenTitle}` : `停顿 ${tokenTitle}`}
                            aria-label={cutReason ? `停顿，${cutReason}` : suggestionReason ? `停顿，${suggestionReason}` : `停顿 ${tokenTitle}`}
                          >
                            [{(token.pauseDuration ?? Math.max(0, token.end - token.start)).toFixed(1)}s{(token.pauseCount || 1) > 1 ? `/${token.pauseCount}` : ""}]
                          </button>
                          {breakNode}
                        </Fragment>
                      );
                    }
                    if (token.kind === "punctuation") {
                      if (token.inferredPunctuation) {
                        return <Fragment key={token.key}>{breakNode}</Fragment>;
                      }
                      return (
                        <Fragment key={token.key}>
                          <span
                            ref={(element) => {
                              if (element) {
                                transcriptTokenRefs.current.set(index, element);
                              } else {
                                transcriptTokenRefs.current.delete(index);
                              }
                            }}
                            className={classNames(
                              "manual-editor-transcript-punctuation",
                              token.inferredPunctuation && "inferred",
                              cut && "cut",
                              cutKind && `cut-${cutKind}`,
                              smartDeleteSuggestion && "suggested-smart_delete",
                              active && "active",
                              selected && "selected",
                            )}
                            data-transcript-token-index={index}
                            onClick={() => selectTranscriptToken(index)}
                            title={token.inferredPunctuation ? `断句边界 · ${tokenTitle}` : tokenTitle}
                          >
                            {token.inferredPunctuation ? "" : token.text}
                          </span>
                          {breakNode}
                        </Fragment>
                      );
                    }
                    return (
                      <Fragment key={token.key}>
                        <span
                          ref={(element) => {
                            if (element) {
                              transcriptTokenRefs.current.set(index, element);
                            } else {
                              transcriptTokenRefs.current.delete(index);
                            }
                          }}
                          className={classNames("manual-editor-transcript-token", cut && "cut", cutKind && `cut-${cutKind}`, smartDeleteSuggestion && "suggested-smart_delete", active && "active", selected && "selected")}
                          data-transcript-token-index={index}
                          onClick={() => selectTranscriptToken(index)}
                          title={tokenTitle}
                        >
                          {token.text}
                        </span>
                        {breakNode}
                      </Fragment>
                    );
                  })}
                </div>

                {transcriptSelection && transcriptSelectionPopover ? (
                  <div
                    className="manual-editor-selection-popover"
                    style={{
                      left: `${transcriptSelectionPopover.left}px`,
                      top: `${transcriptSelectionPopover.top}px`,
                    }}
                    onMouseDown={(event) => event.stopPropagation()}
                    data-subtitle-selection-scope="true"
                  >
                    <div className="manual-editor-selection-popover-summary">
                      <span className="manual-editor-selection-popover-target">{transcriptSelection.text || `${transcriptSelection.pauseCount} 个停顿`}</span>
                    </div>
                    <div className="manual-editor-selection-popover-actions">
                      {transcriptSelection.keptTokenCount > 0 ? (
                        <button type="button" className="manual-editor-popover-icon-button danger" disabled={!session.editable} onClick={cutTranscriptSelection} title="删除选区" aria-label="删除选区">
                          <TrashIcon />
                        </button>
                      ) : null}
                      {transcriptSelection.cutTokenCount > 0 ? (
                        <button type="button" className="manual-editor-popover-icon-button restore" disabled={!session.editable} onClick={restoreTranscriptSelection} title="恢复选区" aria-label="恢复选区">
                          <RestoreIcon />
                        </button>
                      ) : null}
                      {transcriptSelection.text ? (
                        <>
                          <input
                            className="input"
                            value={transcriptReplacementDraft}
                            onChange={(event) => setTranscriptReplacementDraft(event.target.value)}
                            placeholder="替换为"
                          />
                          <button
                            type="button"
                            className="manual-editor-popover-icon-button replace"
                            disabled={!session.editable || !transcriptReplacementDraft.trim() || transcriptReplacementDraft.trim() === transcriptSelection.text}
                            onClick={replaceSelectedTranscriptText}
                            title="替换选区"
                            aria-label="替换选区"
                          >
                            <ReplaceIcon />
                          </button>
                          <button
                            type="button"
                            className="manual-editor-popover-icon-button replace-all"
                            disabled={!session.editable || !transcriptReplacementDraft.trim() || transcriptReplacementDraft.trim() === transcriptSelection.text || countSubtitleMatches(projection.remapped, transcriptSelection.text) <= 0}
                            onClick={replaceAllTranscriptText}
                            title="全部替换"
                            aria-label="全部替换"
                          >
                            <ReplaceAllIcon />
                          </button>
                        </>
                      ) : null}
                      <button type="button" className="manual-editor-popover-icon-button close" onClick={clearTranscriptSelection} title="关闭浮层" aria-label="关闭浮层">
                        <CloseIcon />
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              <div className="manual-editor-rule-panel">
                <div className="manual-editor-rule-head">
                  <button
                    type="button"
                    className="manual-editor-rule-toggle"
                    onClick={() => setSmartCutRulesExpanded((current) => !current)}
                    aria-expanded={smartCutRulesExpanded}
                  >
                    <strong>剪辑规则</strong>
                    <span>{smartCutRulesExpanded ? "收起" : "展开"}</span>
                  </button>
                  <span className="status-pill pending">规则候选 {activeSmartCutRuleRangeCount}</span>
                  {pendingSmartDeleteRangeCount ? <span className="status-pill running">智能待确认 {pendingSmartDeleteRangeCount}</span> : null}
                </div>
                {smartCutRulesExpanded ? (
                  <>
                    <div className="manual-editor-rule-grid">
                      <label>
                        <input
                          type="checkbox"
                          checked={smartCutRules.fillerEnabled}
                          onChange={(event) => updateSmartCutRule({ fillerEnabled: event.target.checked })}
                        />
                        <span>语气词</span>
                        <strong>{smartCutRuleCounts.filler}</strong>
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={smartCutRules.repeatedEnabled}
                          onChange={(event) => updateSmartCutRule({ repeatedEnabled: event.target.checked })}
                        />
                        <span>重复口误</span>
                        <strong>{smartCutRuleCounts.repeated}</strong>
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={smartCutRules.pauseEnabled}
                          onChange={(event) => updateSmartCutRule({ pauseEnabled: event.target.checked })}
                        />
                        <span>长停顿</span>
                        <strong>{smartCutRuleCounts.pause}</strong>
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={smartCutRules.smartDeleteEnabled}
                          onChange={(event) => updateSmartCutRule({ smartDeleteEnabled: event.target.checked })}
                        />
                        <span>智能废片</span>
                        <strong>{smartCutRuleCounts.smartDelete}</strong>
                      </label>
                      <label>
                        停顿
                        <input
                          className="input"
                          type="number"
                          min={0.1}
                          max={5}
                          step={0.1}
                          value={smartCutRules.pauseThresholdSec}
                          onChange={(event) => updateSmartCutRule({ pauseThresholdSec: Number(event.target.value || 0.8) })}
                        />
                        秒
                      </label>
                      <label>
                        保留气口
                        <input
                          className="input"
                          type="number"
                          min={0}
                          max={1}
                          step={0.01}
                          value={smartCutRules.pauseBreathSec ?? DEFAULT_SMART_CUT_RULES.pauseBreathSec}
                          onChange={(event) => updateSmartCutRule({ pauseBreathSec: Number(event.target.value || 0) })}
                        />
                        秒/侧
                      </label>
                    </div>
                    <input
                      className="input"
                      value={smartCutRules.fillers}
                      onChange={(event) => updateSmartCutRule({ fillers: event.target.value })}
                      placeholder="自定义语气词，用逗号分隔"
                    />
                    <div className="manual-editor-rule-examples" aria-label="剪辑规则删除样式示范">
                      {smartCutRulePreviews.map((preview) => (
                        <article key={preview.kind} className={classNames("manual-editor-rule-example", !preview.enabled && "disabled")}>
                          <div className="manual-editor-rule-example-head">
                            <strong>{preview.label}</strong>
                            <span>{preview.count} 处</span>
                          </div>
                          <div className="manual-editor-rule-example-sample">
                            {preview.kind === "pause" ? (
                              <span className={classNames("manual-editor-transcript-pause", "manual-editor-rule-sample", `rule-${preview.kind}`)}>
                                {preview.sampleText}
                              </span>
                            ) : (
                              <span className={classNames("manual-editor-transcript-token", "manual-editor-rule-sample", `rule-${preview.kind}`)}>
                                {preview.sampleText}
                              </span>
                            )}
                            <span>{preview.sampleMeta}</span>
                          </div>
                          <p>{preview.reason}</p>
                        </article>
                      ))}
                    </div>
                    {pendingSmartDeleteRanges.length ? (
                      <div className="manual-editor-smart-suggestions" aria-label="智能剪辑建议">
                        <div className="manual-editor-smart-suggestions-head">
                          <strong>智能废片建议</strong>
                          <span>{pendingSmartDeleteRanges.length} 条需确认</span>
                        </div>
                        {pendingSmartDeleteRanges.map((range) => (
                          <article key={`${range.start}-${range.end}-${range.reason || ""}`} className="manual-editor-smart-suggestion">
                            <button
                              type="button"
                              className="manual-editor-smart-suggestion-main"
                              onClick={() => jumpToSourceTime(range.start)}
                              title={`定位 ${formatSeconds(range.start)} - ${formatSeconds(range.end)}`}
                            >
                              <strong>{formatSeconds(range.start)} - {formatSeconds(range.end)}</strong>
                              <span>{textSnippet(range.sourceText || range.detail || range.reason || smartDeleteReasonLabel(range.reason), 42)}</span>
                            </button>
                            <div className="manual-editor-smart-suggestion-actions">
                              <button type="button" className="button small secondary" disabled={!session.editable} onClick={() => dismissSmartDeleteSuggestion(range)}>撤销</button>
                              <button type="button" className="button small danger" disabled={!session.editable} onClick={() => confirmSmartDeleteSuggestion(range)}>确认剪掉</button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : null}
                    <div className="manual-editor-rule-memory">规则候选只用于定位复核，不会直接进入待剪区间；智能废片必须逐条确认后才允许进入最终剪辑决策。规则设置已全局记忆。</div>
                  </>
                ) : null}
              </div>

            </div>
          </div>
        </section>

        <section className="manual-editor-timeline">
          <div className="manual-editor-preview-head">
            <strong>统一时间轴</strong>
            <span className="muted">移动只显示时间，单击才定位监看；字幕和预览共用同一播放头。</span>
          </div>

          <div
            ref={unifiedTimelineRef}
            className={classNames("manual-editor-unified-timeline", previewDisabled && "disabled")}
            style={unifiedTimelineStyle}
            onPointerMove={previewUnifiedTimelineAtPointer}
            onClick={commitUnifiedTimelinePointer}
            onPointerLeave={() => setTimelineHoverSourceTime(null)}
            aria-label="源片统一时间轴"
          >
            {previewDisabled ? (
              <div className="notice">缺少可预览原片，时间轴定位暂不可用。</div>
            ) : null}
            <div className="manual-editor-unified-ruler" aria-hidden="true">
              {timelineRulerTicks.map((tick) => (
                <span key={tick.key} style={{ left: `${tick.leftPercent}%` }}>
                  {tick.label}
                </span>
              ))}
            </div>
            <div className="manual-editor-unified-hover" aria-hidden="true">
              <span>{timelineHoverSourceTime == null ? "" : formatSeconds(timelineHoverSourceTime)}</span>
            </div>
            <div className="manual-editor-unified-playhead" aria-hidden="true">
              <span>{formatSeconds(timelinePlayheadSourceTime)}</span>
            </div>

            <div className="manual-editor-unified-clip">
              <div className="manual-editor-unified-clip-head">
                <strong>{job?.source_name ?? session.source_name}</strong>
                <span>源 {formatSeconds(sourceTimelineDuration)} / 输出 {formatSeconds(totalOutputDuration)}</span>
              </div>
              <div className="manual-editor-unified-traces" aria-label="剪辑痕迹">
                {sourceKeepTimelineItems.map((range, index) => (
                  <button
                    key={`keep-${range.start}-${range.end}-${index}`}
                    type="button"
                    className="manual-editor-unified-trace keep"
                    style={{ left: `${range.leftPercent}%`, width: `${Math.max(range.widthPercent, 0.4)}%` }}
                    onClick={(event) => {
                      event.stopPropagation();
                      jumpToSourceTime(range.start);
                    }}
                    title={`保留 ${formatSeconds(range.start)} - ${formatSeconds(range.end)}`}
                  />
                ))}
                {sourceCutTimelineItems.map((range, index) => (
                  <button
                    key={`cut-${range.start}-${range.end}-${index}`}
                    type="button"
                    className="manual-editor-unified-trace cut"
                    style={{ left: `${range.leftPercent}%`, width: `${Math.max(range.widthPercent, 0.4)}%` }}
                    onClick={(event) => {
                      event.stopPropagation();
                      jumpToSourceTime(range.start);
                    }}
                    title={`待剪 ${formatSeconds(range.start)} - ${formatSeconds(range.end)}`}
                  />
                ))}
              </div>
              <div className="manual-editor-unified-thumbnails">
                {unifiedThumbnailItems.length ? (
                  unifiedThumbnailItems.map((item, index) => (
                    <button
                      key={`${item.url}-${index}`}
                      type="button"
                      className="manual-editor-unified-thumb"
                      style={{
                        left: `${item.leftPercent}%`,
                        width: `${item.widthPercent}%`,
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        selectSubtitleNearSourceTime(item.timeSec);
                        jumpToSourceTime(item.timeSec);
                      }}
                      title={`源 ${formatSeconds(item.timeSec)}`}
                    >
                      <img src={item.url} alt="" loading="lazy" />
                    </button>
                  ))
                ) : (
                  <div className="manual-editor-unified-thumb-empty">预览素材已就绪</div>
                )}
              </div>
              <div className="manual-editor-unified-wave" aria-label="音频概览">
                {unifiedWaveformBars.map((peak, index) => (
                  <span key={index} style={{ height: `${Math.round(peak * 100)}%` }} />
                ))}
              </div>
            </div>

            {sourceTranscriptSubtitles.length ? (
              <div className="manual-editor-unified-subtitles" aria-label="源片字幕定位轨">
                {sourceTranscriptSubtitles.map((subtitle) => {
                  const left = sourceTimelineDuration > 0 ? (subtitle.start_time / sourceTimelineDuration) * 100 : 0;
                  const width = sourceTimelineDuration > 0 ? ((subtitle.end_time - subtitle.start_time) / sourceTimelineDuration) * 100 : 0;
                  const sourceOutputTime = sourceTimeToActiveOutputTime(subtitle.start_time, projection.ranges);
                  const selected = sourceOutputTime != null && selectedSubtitle?.index === projection.remapped[findSubtitleIndexNearOutputTime(projection.remapped, sourceOutputTime)]?.index;
                  const cut = !isSourceRangeKept(subtitle.start_time, subtitle.end_time, effectiveSegments);
                  return (
                    <button
                      key={`${subtitle.index}-${subtitle.start_time}-timeline`}
                      type="button"
                      className={classNames("manual-editor-unified-subtitle", selected && "active", cut && "cut")}
                      style={{ left: `${clamp(left, 0, 100)}%`, width: `${Math.max(width, 0.8)}%` }}
                      onClick={(event) => {
                        event.stopPropagation();
                        selectSubtitleNearSourceTime(subtitle.start_time);
                        jumpToSourceTime(subtitle.start_time);
                      }}
                      title={`${formatSeconds(subtitle.start_time)} - ${formatSeconds(subtitle.end_time)} ${subtitleText(subtitle)}`}
                    >
                      <span>{subtitle.index + 1}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          <div className="manual-editor-wave-shell top-gap">
            <div
              ref={waveformRef}
              className={classNames("manual-editor-waveform", !waveformUrl && "disabled")}
              aria-label="可调保留段波形"
            />
            <div ref={waveformTimelineRef} className="manual-editor-wave-timeline" />
            {waveformUrl && (!waveformReady || waveformError) ? (
              <div className="manual-editor-wave-loading">
                {waveformError || "正在加载完整源片波形"}
              </div>
            ) : null}
          </div>
          <div className="manual-editor-wave-tools">
            <span className="status-pill done">绿色保留</span>
            <span className="status-pill failed">暗段待剪</span>
            <span className="muted">拖动绿色区块即可微调边界；点击源片时间轴只定位，不会跳过被剪片段。</span>
            <label className="manual-editor-wave-zoom">
              <span>缩放</span>
              <input
                type="range"
                min={4}
                max={80}
                step={1}
                value={waveformZoom}
                onChange={(event) => setWaveformZoom(Number(event.target.value))}
              />
            </label>
          </div>

          {previewAssets ? (
            <div className="manual-editor-preview-assets">
              <div className="manual-editor-preview-asset-status">
                <span>{previewAssetStatusLabel(previewAssets)}</span>
                <span>{previewAssetStageLabel(previewAssets.stage)}</span>
                <span>{previewAssetProgressPercent != null ? `${previewAssetProgressPercent}%` : previewAssets.ready ? "100%" : "0%"}</span>
                <span>{previewAssets.ready ? `${previewAssets.peak_count} peaks` : previewAssets.video_url ? "使用视频代理预览" : "等待视频代理"}</span>
                {previewAssets.video_url ? <span>{(previewAssets.video_sources?.length || 0) > 1 ? "多编码视频代理" : "浏览器兼容视频代理"}</span> : null}
                {previewAssets.ready ? <span>{previewMeasuredLufs.toFixed(1)} LUFS 至 {previewTargetLufs.toFixed(0)} LUFS</span> : null}
                {previewAssets.ready ? <span>增益 {previewAutoVolumeGain.toFixed(2)}x</span> : null}
                {previewAssets.asset_version ? <span>v{previewAssets.asset_version}</span> : null}
              </div>
              {previewAssetProgress != null ? (
                <div
                  className={classNames("manual-editor-asset-progress", previewAssets.error && "failed")}
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={previewAssetProgressPercent ?? 0}
                >
                  <span style={{ width: `${previewAssetProgressPercent ?? 0}%` }} />
                </div>
              ) : null}
              {previewAssets.error ? <p className="manual-editor-asset-error">{previewAssets.error}</p> : null}
              {!previewAssets.error && previewAssets.detail ? <p className="manual-editor-asset-detail">{previewAssets.detail}</p> : null}
            </div>
          ) : null}

          <label className="form-field top-gap">
            <span className="field-label">修改备注</span>
            <textarea
              className="input textarea"
              rows={3}
              value={editorNote}
              onChange={(event) => setEditorNote(event.target.value)}
              placeholder="例如：删掉开头空镜，收紧第二段边界"
            />
          </label>

        </section>
      </div>

      <section className="manual-editor-term-review">
        <div className="manual-editor-preview-head">
          <div>
            <strong>高频词核对</strong>
            <div className="muted compact-top">优先显示低置信、术语名词、专名型号和英文品牌类候选；批量替换会写入字幕修改并随保存重渲染。</div>
          </div>
          <div className="manual-editor-actions">
            <label className="manual-editor-term-filter">
              <span>将</span>
              <input
                className="input"
                value={manualTermDraft}
                onChange={(event) => setManualTermDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applySubtitleReplacement(manualTermDraft, manualReplacementDraft, { clearManualDraft: true });
                  }
                }}
                placeholder="例如：快开提"
              />
            </label>
            <label className="manual-editor-term-filter">
              <span>替换为</span>
              <input
                className="input"
                value={manualReplacementDraft}
                onChange={(event) => setManualReplacementDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applySubtitleReplacement(manualTermDraft, manualReplacementDraft, { clearManualDraft: true });
                  }
                }}
                placeholder="例如：快开鳍"
              />
            </label>
            <button
              type="button"
              className="button primary"
              disabled={!manualTermDraft.trim() || !manualReplacementDraft.trim() || manualTermDraft.trim() === manualReplacementDraft.trim() || countSubtitleMatches(projection.remapped, manualTermDraft.trim()) <= 0}
              onClick={() => applySubtitleReplacement(manualTermDraft, manualReplacementDraft, { clearManualDraft: true })}
            >
              批量替换
            </button>
            <label className="manual-editor-term-filter">
              <span>筛选</span>
              <input
                className="input"
                value={termReviewFilter}
                onChange={(event) => setTermReviewFilter(event.target.value)}
                placeholder="词 / 类型"
              />
            </label>
            <label className="manual-editor-term-filter compact">
              <span>至少</span>
              <input
                className="input"
                type="number"
                min={1}
                max={99}
                value={minTermCount}
                onChange={(event) => setMinTermCount(Math.max(1, Number(event.target.value || 1)))}
              />
              <span>次</span>
            </label>
            <span className="status-pill pending">候选 {visibleFrequentTerms.length}</span>
          </div>
        </div>

        {visibleFrequentTerms.length ? (
          <div className="manual-editor-term-grid">
            {visibleFrequentTerms.map((term) => {
              const active = term.subtitleIndexes.includes(selectedSubtitle?.index ?? -1);
              const replacement = termReplacementDrafts[term.normalized] || "";
              return (
                <article key={term.normalized} className={classNames("manual-editor-term-card", active && "active")}>
                  <div className="manual-editor-term-title">
                    <strong>{term.term}</strong>
                    <span className="status-pill pending">{term.count} 次</span>
                    <span className="status-pill">{term.kind}</span>
                    {term.manuallyAdded ? <span className="status-pill success">手工</span> : null}
                  </div>
                  {term.relatedTerms?.length ? (
                    <div className="muted compact-top">已合并：{term.relatedTerms.slice(0, 5).join(" / ")}</div>
                  ) : null}
                  <div className="manual-editor-term-occurrences">
                    {term.occurrences.slice(0, 3).map((subtitle) => (
                      <button key={`${term.normalized}-${subtitle.index}`} type="button" onClick={() => selectSubtitle(subtitle)}>
                        {formatSeconds(subtitle.start_time)} {subtitleText(subtitle).slice(0, 36)}
                      </button>
                    ))}
                    {term.occurrences.length > 3 ? <span>另 {term.occurrences.length - 3} 条</span> : null}
                  </div>
                  <div className="manual-editor-term-replace-row">
                    <input
                      className="input"
                      value={replacement}
                      onChange={(event) => setTermReplacementDrafts((current) => ({ ...current, [term.normalized]: event.target.value }))}
                      placeholder={`替换“${term.term}”`}
                    />
                    <button
                      type="button"
                      className="button primary"
                      disabled={!replacement.trim() || replacement.trim() === term.term}
                      onClick={() => replaceTermAcrossSubtitles(term)}
                    >
                      批量替换
                    </button>
                    <button
                      type="button"
                      className="button ghost"
                      onClick={() => setHiddenTermKeys((current) => new Set([...current, term.normalized]))}
                    >
                      忽略
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="notice">当前筛选条件下没有足够高频的候选词。</div>
        )}
      </section>

      <section className="manual-editor-subtitle-editor" data-subtitle-selection-scope="true">
        <div className="manual-editor-preview-head">
          <div>
            <strong>字幕时间表</strong>
            <div className="muted compact-top">按输出时间轴编辑字幕文本和起止时间，保存后进入重渲染字幕层。</div>
          </div>
          <div className="manual-editor-actions">
            <button
              type="button"
              className="button primary"
              disabled={!session.editable || !projection.remapped.length}
              onMouseDown={rememberSelectedSubtitleText}
              onClick={openSubtitleReplaceDialog}
            >
              一键替换
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={() => nudgeSelectedSubtitle(-0.1)}>
              -100ms
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={() => nudgeSelectedSubtitle(0.1)}>
              +100ms
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={() => setSelectedSubtitleBoundaryFromPlayhead("start")}>
              播放头设开始
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={() => setSelectedSubtitleBoundaryFromPlayhead("end")}>
              播放头设结束
            </button>
            <button type="button" className="button ghost" disabled={!projection.remapped.length} onClick={() => selectAdjacentSubtitle(-1)}>
              上一条
            </button>
            <button type="button" className="button ghost" disabled={!projection.remapped.length} onClick={() => selectAdjacentSubtitle(1)}>
              下一条
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={splitSelectedSubtitle}>
              拆分
            </button>
            <button type="button" className="button ghost" disabled={!selectedSubtitle} onClick={mergeSelectedSubtitleWithNext}>
              合并下一条
            </button>
            <label className="manual-editor-shift-control">
              <span>批量</span>
              <input
                className="input"
                type="number"
                step={10}
                value={batchShiftMs}
                onChange={(event) => setBatchShiftMs(Number(event.target.value || 0))}
              />
              <span>ms</span>
            </label>
            <button type="button" className="button ghost" onClick={() => shiftAllSubtitles(-batchShiftMs / 1000)}>
              左移
            </button>
            <button type="button" className="button ghost" onClick={() => shiftAllSubtitles(batchShiftMs / 1000)}>
              右移
            </button>
            <button type="button" className="button ghost" onClick={enforceSubtitleGaps}>
              最小间隔
            </button>
            <span className="status-pill pending">已改 {subtitleOverrides.length}</span>
            {deletedSubtitleCount ? <span className="status-pill failed">已删 {deletedSubtitleCount}</span> : null}
            <span className={classNames("status-pill", diagnostics.issueCount ? "failed" : "done")}>
              问题 {diagnostics.issueCount}
            </span>
          </div>
        </div>

        {subtitleTableWindow.clipped ? (
          <div className="notice manual-editor-window-notice">
            为保持页面响应速度，当前只渲染第 {subtitleTableWindow.start + 1} - {subtitleTableWindow.end} 条字幕，共 {visibleSubtitles.length} 条；定位到其他字幕后窗口会自动切换。
          </div>
        ) : null}

        <div className="manual-editor-subtitle-table">
          <div className="manual-editor-subtitle-row header">
            <span>#</span>
            <span>开始</span>
            <span>结束</span>
            <span>状态</span>
            <span>字幕</span>
            <span>操作</span>
          </div>
          {subtitleTableWindow.rows.map((subtitle) => {
            const deleted = Boolean(subtitle.deleted);
            const selected = selectedSubtitleIndex === subtitle.index;
            const changed = Boolean(subtitleDrafts[subtitle.index]) && subtitleOverrideChanged(
              baseProjection.remapped.find((item) => item.index === subtitle.index),
              subtitleDrafts[subtitle.index],
            );
            const rowWarnings = deleted ? [] : diagnostics.warnings[subtitle.index] || [];
            const autoCorrection = !changed && !deleted && !rowWarnings.length ? subtitleAutoCorrectionSummary(subtitle) : null;
            return (
              <div key={`${subtitle.index}-${subtitle.start_time}-${deleted ? "deleted" : "active"}`} className={classNames("manual-editor-subtitle-row", selected && "active", changed && "changed", deleted && "deleted", rowWarnings.length > 0 && "warning", autoCorrection && "auto-corrected")}>
                <button type="button" className="manual-editor-subtitle-index" onClick={() => (deleted ? setSelectedSubtitleIndex(subtitle.index) : selectSubtitle(subtitle))}>
                  {subtitle.index + 1}
                </button>
                <input
                  className="input"
                  type="number"
                  step={0.01}
                  min={0}
                  max={totalOutputDuration}
                  value={subtitle.start_time}
                  disabled={deleted}
                  onFocus={() => setSelectedSubtitleIndex(subtitle.index)}
                  onChange={(event) => updateSubtitleDraft(subtitle, { start_time: Number(event.target.value || 0) })}
                />
                <input
                  className="input"
                  type="number"
                  step={0.01}
                  min={0}
                  max={totalOutputDuration}
                  value={subtitle.end_time}
                  disabled={deleted}
                  onFocus={() => setSelectedSubtitleIndex(subtitle.index)}
                  onChange={(event) => updateSubtitleDraft(subtitle, { end_time: Number(event.target.value || 0) })}
                />
                <span className={classNames("manual-editor-subtitle-state", deleted && "deleted", rowWarnings.length > 0 && "warning")}>
                  {deleted ? "已删除" : rowWarnings.length ? rowWarnings.join(" / ") : changed ? "已修改" : autoCorrection ? autoCorrection.label : "正常"}
                </span>
                <div className="manual-editor-subtitle-text-cell">
                  <input
                    className="input"
                    value={subtitleText(subtitle)}
                    disabled={deleted}
                    onFocus={() => setSelectedSubtitleIndex(subtitle.index)}
                    onSelect={rememberSelectedSubtitleText}
                    onChange={(event) => updateSubtitleDraft(subtitle, { text_final: event.target.value })}
                  />
                  {autoCorrection ? (
                    <div className="manual-editor-subtitle-auto-diff" title="自动校正来源">
                      <span>原文</span>
                      <del>{autoCorrection.source}</del>
                      <span>当前</span>
                      <ins>{autoCorrection.current}</ins>
                    </div>
                  ) : null}
                </div>
                <div className="manual-editor-actions">
                  <button type="button" className="button ghost" disabled={deleted} onClick={() => selectSubtitle(subtitle)}>
                    定位
                  </button>
                  {deleted ? (
                    <button type="button" className="button ghost" onClick={() => restoreDeletedSubtitle(subtitle)}>
                      恢复
                    </button>
                  ) : (
                    <button type="button" className="button ghost" disabled={!changed} onClick={() => resetSubtitleDraft(subtitle)}>
                      还原
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </section>
  );
}

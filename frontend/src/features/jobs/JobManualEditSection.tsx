import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type SyntheticEvent } from "react";
import type WaveSurfer from "wavesurfer.js";
import type { RegionsPlugin as RegionsPluginInstance } from "wavesurfer.js/dist/plugins/regions.esm.js";

import type { Job, JobManualEditApplyPayload, JobManualEditPreviewAssets, JobManualEditSession, JobManualEditSilence, JobManualEditSubtitle, JobManualEditSubtitleOverride, JobManualEditWord, JobManualSubtitleReplacement, JobManualVideoTransform } from "../../types";
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

type SubtitleTextDraft = {
  text_final?: string | null;
};

type TimelineThumbnailItem = {
  url: string;
  time_sec: number;
  output_time: number | null;
  kept: boolean;
};

type UnifiedTimelineThumbnailItem = TimelineThumbnailItem & {
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

type TranscriptTokenKind = "char" | "pause";
type TranscriptBreakKind = "soft" | "paragraph";

type TranscriptToken = {
  key: string;
  kind: TranscriptTokenKind;
  text: string;
  subtitleIndex: number | null;
  start: number;
  end: number;
  kept: boolean;
  pauseDuration?: number;
  inferredPunctuation?: string;
  breakAfter?: TranscriptBreakKind;
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
  pauseThresholdSec: number;
  fillers: string;
};

type SmartCutRuleKind = "filler" | "repeated" | "pause";

type SmartCutRuleMatch = KeepSegment & {
  kind: SmartCutRuleKind;
};

type SmartCutRuleAnalysis = {
  filler: SmartCutRuleMatch[];
  repeated: SmartCutRuleMatch[];
  pause: SmartCutRuleMatch[];
};

const REGION_COLOR = "rgba(34, 197, 94, 0.22)";
const REGION_ACTIVE_COLOR = "rgba(20, 184, 166, 0.36)";
const MIN_SUBTITLE_DURATION_SEC = 0.08;
const MIN_SUBTITLE_GAP_SEC = 0.02;
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
  fillerEnabled: false,
  repeatedEnabled: false,
  pauseEnabled: true,
  pauseThresholdSec: 0.8,
  fillers: DEFAULT_SMART_CUT_FILLERS,
};

function normalizeSmartCutRules(value: Partial<SmartCutRules> | null | undefined): SmartCutRules {
  const pauseThresholdSec = Number(value?.pauseThresholdSec);
  return {
    fillerEnabled: typeof value?.fillerEnabled === "boolean" ? value.fillerEnabled : DEFAULT_SMART_CUT_RULES.fillerEnabled,
    repeatedEnabled: typeof value?.repeatedEnabled === "boolean" ? value.repeatedEnabled : DEFAULT_SMART_CUT_RULES.repeatedEnabled,
    pauseEnabled: typeof value?.pauseEnabled === "boolean" ? value.pauseEnabled : DEFAULT_SMART_CUT_RULES.pauseEnabled,
    pauseThresholdSec: Number.isFinite(pauseThresholdSec) ? clamp(pauseThresholdSec, 0.1, 5) : DEFAULT_SMART_CUT_RULES.pauseThresholdSec,
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

function subtitleText(subtitle: JobManualEditSubtitle) {
  return subtitle.text_final ?? subtitle.text_norm ?? subtitle.text_raw ?? "";
}

function subtitleTranscriptSourceText(subtitle: JobManualEditSubtitle) {
  return String(subtitle.text_raw || subtitle.text_norm || subtitle.text_final || "").trim();
}

function compactTranscriptText(value: string) {
  return value.replace(/[\s，,。.!！?？、；;：:“”"'‘’（）()[\]【】]+/g, "");
}

function shouldPreferSourceTranscriptText(sourceText: string, projectedText: string | undefined) {
  const sourceKey = compactTranscriptText(sourceText);
  const projectedKey = compactTranscriptText(projectedText || "");
  if (!sourceKey) return false;
  if (!projectedKey) return true;
  return sourceKey.length > projectedKey.length && sourceKey.includes(projectedKey);
}

function subtitleSourceIndex(subtitle: Pick<JobManualEditSubtitle, "index" | "source_index">) {
  return Number.isFinite(Number(subtitle.source_index)) ? Number(subtitle.source_index) : Number(subtitle.index);
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
  if (previewAssets.status === "failed" || previewAssets.error) return "预览资产生成失败";
  if (previewAssets.warming || previewAssets.status === "warming") return "预览资产生成中";
  return "预览资产待生成";
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

function remapSubtitles(subtitles: JobManualEditSubtitle[], keepSegments: KeepSegment[]) {
  const { ranges, totalDuration } = buildOutputRanges(keepSegments);
  const remapped = subtitles
    .flatMap((subtitle, index) => {
      const subtitleStart = Number(subtitle.start_time || 0);
      const subtitleEnd = Number(subtitle.end_time || 0);
      const mappedRanges = sourceRangeToOutputRanges(subtitleStart, subtitleEnd, ranges);
      if (!mappedRanges.length || subtitleEnd <= subtitleStart + 0.001) return [];
      const fragmentTexts = splitRemappedSubtitleText(subtitle, mappedRanges, subtitleStart, subtitleEnd);
      return mappedRanges.flatMap((mappedRange, fragmentIndex) => {
        const fragmentText = fragmentTexts[fragmentIndex]?.trim() || "";
        if (!fragmentText) return [];
        const remappedSubtitle = withRemappedSubtitleText({
          ...subtitle,
          index: subtitle.index ?? index,
          start_time: Number(mappedRange.outputStart.toFixed(3)),
          end_time: Number(mappedRange.outputEnd.toFixed(3)),
        }, fragmentText);
        return [remappedSubtitle];
      });
    })
    .sort((left, right) => left.start_time - right.start_time || left.index - right.index);

  return { remapped, ranges, totalDuration };
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
      const mappedRanges = sourceRanges.flatMap((range) => sourceRangeToOutputRanges(range.start, range.end, ranges));
      if (!mappedRanges.length) return [];
      const startTime = Math.min(...mappedRanges.map((range) => range.outputStart));
      const endTime = Math.max(...mappedRanges.map((range) => range.outputEnd));
      if (endTime <= startTime + 0.05) return [];
      return [withRemappedSubtitleText({
        ...subtitle,
        index: subtitle.index ?? index,
        start_time: Number(startTime.toFixed(3)),
        end_time: Number(endTime.toFixed(3)),
      }, subtitleText(subtitle))];
    })
    .sort((left, right) => left.start_time - right.start_time || left.index - right.index);

  return { remapped, ranges, totalDuration };
}

function withRemappedSubtitleText(subtitle: JobManualEditSubtitle, text: string) {
  return {
    ...subtitle,
    text_raw: subtitle.text_raw == null ? subtitle.text_raw : text,
    text_norm: subtitle.text_norm == null ? subtitle.text_norm : text,
    text_final: text,
  };
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

function splitRemappedSubtitleText(
  subtitle: JobManualEditSubtitle,
  mappedRanges: MappedSubtitleRange[],
  subtitleStart: number,
  subtitleEnd: number,
) {
  const text = subtitleText(subtitle).trim();
  if (!text) return mappedRanges.map(() => "");
  const hasSpaces = text.includes(" ");
  const tokens = hasSpaces ? text.split(/\s+/).filter(Boolean) : Array.from(text);
  if (!tokens.length) return mappedRanges.map(() => "");
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

function sourceTimeToOutputThumbnailItem(item: { url: string; time_sec: number }, ranges: OutputRange[]): TimelineThumbnailItem {
  const sourceTime = Math.max(0, Number(item.time_sec || 0));
  const activeRange = ranges.find((range) => sourceTime >= range.sourceStart && sourceTime <= range.sourceEnd);
  return {
    ...item,
    output_time: activeRange ? sourceTimeToOutputTime(sourceTime, ranges) : null,
    kept: Boolean(activeRange),
  };
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

function sourceSubtitlesForTranscript(session: Pick<JobManualEditSession, "source_subtitles" | "projected_subtitles">) {
  const source = session.source_subtitles.length ? session.source_subtitles : session.projected_subtitles;
  return sortedSubtitles(source);
}

export function buildSourceTranscriptSubtitlesForTimeline(
  session: Pick<JobManualEditSession, "source_subtitles" | "projected_subtitles">,
  projectedSubtitles: JobManualEditSubtitle[],
  subtitleDrafts: Record<number, SubtitleTextDraft>,
) {
  const projectedTextsBySourceIndex = new Map<number, string[]>();
  for (const subtitle of projectedSubtitles) {
    const sourceIndex = subtitleSourceIndex(subtitle);
    const text = subtitleText(subtitle).trim();
    if (!text) continue;
    const bucket = projectedTextsBySourceIndex.get(sourceIndex) ?? [];
    bucket.push(text);
    projectedTextsBySourceIndex.set(sourceIndex, bucket);
  }
  return sourceSubtitlesForTranscript(session).map((subtitle) => {
    const draft = subtitleDrafts[subtitle.index];
    const projectedText = projectedTextsBySourceIndex.get(subtitleSourceIndex(subtitle))?.join("");
    const sourceText = subtitleTranscriptSourceText(subtitle);
    const nextText = draft?.text_final
      ?? (shouldPreferSourceTranscriptText(sourceText, projectedText) ? sourceText : undefined)
      ?? projectedText
      ?? sourceText
      ?? subtitleText(subtitle);
    return {
      ...subtitle,
      text_final: nextText,
    };
  });
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
  if (gapAfter >= 1.1 || (sentenceEnd && paragraphCharCount >= 42) || paragraphCharCount >= 86) return "paragraph";
  if (gapAfter >= 0.45 || sentenceEnd || Array.from(trimmed).length >= 22) return "soft";
  return undefined;
}

const TRANSCRIPT_TIMED_CHAR_RE = /[\u4e00-\u9fffA-Za-z0-9]/;

type TimedTranscriptChar = {
  text: string;
  start: number;
  end: number;
};

function isTranscriptTimedChar(char: string) {
  return TRANSCRIPT_TIMED_CHAR_RE.test(char);
}

function normalizeTranscriptTimingChar(char: string) {
  return char.toLocaleLowerCase();
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

function buildTimedTranscriptCharTokens(
  subtitle: JobManualEditSubtitle,
  text: string,
  segments: KeepSegment[],
  options: { sourceIndex: number },
): TranscriptToken[] | null {
  const { sourceIndex } = options;
  const timedChars = timedCharsFromWords(subtitle.words);
  if (!timedChars.length) return null;
  const chars = Array.from(text);
  const timingCharCount = chars.filter(isTranscriptTimedChar).length;
  if (!timingCharCount) return null;

  const tokens: TranscriptToken[] = [];
  let timedCursor = 0;
  let matchedTimingChars = 0;
  let previousEnd = subtitle.start_time;

  chars.forEach((char, charIndex) => {
    let start = previousEnd;
    let end = previousEnd;
    if (isTranscriptTimedChar(char)) {
      const normalizedChar = normalizeTranscriptTimingChar(char);
      let matchIndex = -1;
      for (let index = timedCursor; index < Math.min(timedCursor + 8, timedChars.length); index += 1) {
        if (normalizeTranscriptTimingChar(timedChars[index].text) === normalizedChar) {
          matchIndex = index;
          break;
        }
      }
      if (matchIndex >= 0) {
        const match = timedChars[matchIndex];
        start = match.start;
        end = match.end;
        timedCursor = matchIndex + 1;
        matchedTimingChars += 1;
      } else {
        const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
        start = subtitle.start_time + duration * (charIndex / Math.max(1, chars.length));
        end = subtitle.start_time + duration * ((charIndex + 1) / Math.max(1, chars.length));
      }
    }
    previousEnd = Math.max(previousEnd, end);
    tokens.push({
      key: `char-${sourceIndex}-${charIndex}`,
      kind: "char",
      text: char,
      subtitleIndex: sourceIndex,
      start: Number(start.toFixed(3)),
      end: Number(end.toFixed(3)),
      kept: isSourceRangeKept(start, end, segments),
    });
  });

  if (matchedTimingChars / timingCharCount < 0.6) return null;
  return tokens;
}

export function buildTranscriptTokens(subtitles: JobManualEditSubtitle[], segments: KeepSegment[], silenceRanges: SilenceRange[] = []) {
  const charTokens: TranscriptToken[] = [];
  let paragraphCharCount = 0;
  subtitles.forEach((subtitle, subtitlePosition) => {
    const sourceIndex = subtitleSourceIndex(subtitle);
    const text = subtitleText(subtitle);
    const chars = Array.from(text);
    const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
    const nextSubtitle = subtitles[subtitlePosition + 1];
    const gapAfter = nextSubtitle ? Math.max(0, nextSubtitle.start_time - subtitle.end_time) : 0;
    const inferredPunctuation = inferTranscriptBoundaryPunctuation(text, gapAfter);
    const nextParagraphCharCount = paragraphCharCount + chars.filter((char) => char.trim()).length;
    const breakAfter = inferTranscriptBreakAfter(inferredPunctuation ? `${text}${inferredPunctuation}` : text, gapAfter, nextParagraphCharCount);
    const timedTokens = buildTimedTranscriptCharTokens(subtitle, text, segments, { sourceIndex });
    const tokens: TranscriptToken[] = timedTokens ?? chars.map((char, charIndex): TranscriptToken => {
      const start = subtitle.start_time + duration * (charIndex / Math.max(1, chars.length));
      const end = subtitle.start_time + duration * ((charIndex + 1) / Math.max(1, chars.length));
      return {
        key: `char-${sourceIndex}-${charIndex}`,
        kind: "char" as const,
        text: char,
        subtitleIndex: sourceIndex,
        start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
        kept: isSourceRangeKept(start, end, segments),
      };
    });
    const lastToken = tokens[tokens.length - 1];
    if (lastToken) {
      lastToken.inferredPunctuation = inferredPunctuation;
      lastToken.breakAfter = breakAfter;
    }
    charTokens.push(...tokens);
    paragraphCharCount = breakAfter === "paragraph" ? 0 : nextParagraphCharCount;
  });

  const pauseTokens = silenceRanges.map((range, index) => {
    const pauseDuration = Math.max(0, range.end - range.start);
    return {
      key: `pause-${range.source || "audio"}-${index}-${range.start}`,
      kind: "pause" as const,
      text: `[...,${pauseDuration.toFixed(1)}s]`,
      subtitleIndex: null,
      start: range.start,
      end: range.end,
      kept: isSourceRangeKept(range.start, range.end, segments),
      pauseDuration,
      breakAfter: pauseDuration >= 1.1 ? "paragraph" as const : undefined,
    };
  });

  return [...charTokens, ...pauseTokens].sort((left, right) => (
    left.start - right.start
    || (left.kind === "pause" ? -1 : 1)
    || left.end - right.end
  ));
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
    .filter((token) => token.kind === "char")
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
    pauseCount,
  };
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

function parseSmartCutFillers(value: string) {
  return value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);
}

const SMART_CUT_BOUNDARY_PATTERN = /[\s,，、。.!！?？;；:：()[\]（）【】"'“”‘’]/;
const SMART_CUT_HESITATION_FILLERS = new Set(["嗯", "呃", "额", "呃呃", "嗯嗯"]);

function isSmartCutBoundary(char: string | undefined) {
  return !char || SMART_CUT_BOUNDARY_PATTERN.test(char);
}

function findTextRangesInSubtitle(subtitle: JobManualEditSubtitle, needle: string) {
  const text = subtitleText(subtitle);
  if (!text || !needle) return [];
  const ranges: KeepSegment[] = [];
  const chars = Array.from(text);
  const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
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
    ranges.push({
      start: Number((subtitle.start_time + duration * (startChar / Math.max(1, chars.length))).toFixed(3)),
      end: Number((subtitle.start_time + duration * (endChar / Math.max(1, chars.length))).toFixed(3)),
    });
    searchFrom = matchIndex + needle.length;
  }
  return ranges;
}

function sourceRangeForSubtitleChars(subtitle: JobManualEditSubtitle, startChar: number, endChar: number) {
  const text = subtitleText(subtitle);
  const chars = Array.from(text);
  const duration = Math.max(0.001, subtitle.end_time - subtitle.start_time);
  const clampedStart = clamp(startChar, 0, chars.length);
  const clampedEnd = clamp(endChar, clampedStart, chars.length);
  return {
    start: Number((subtitle.start_time + duration * (clampedStart / Math.max(1, chars.length))).toFixed(3)),
    end: Number((subtitle.start_time + duration * (clampedEnd / Math.max(1, chars.length))).toFixed(3)),
  };
}

function findRepeatedSpeechRangesInSubtitle(subtitle: JobManualEditSubtitle) {
  const text = subtitleText(subtitle);
  if (!text) return [];
  const ranges: KeepSegment[] = [];
  const repeatedMatches = text.matchAll(/([\u4e00-\u9fff]{1,3})([\s，,、]*)\1/g);
  for (const match of repeatedMatches) {
    const separator = match[2] || "";
    const keepFirst = match[1] || "";
    if (keepFirst.length <= 1 && !separator.trim() && !/[，,、]/.test(separator)) continue;
    const matchIndex = match.index ?? 0;
    const removeStartChar = Array.from(text.slice(0, matchIndex)).length + Array.from(keepFirst + separator).length;
    const removeEndChar = removeStartChar + Array.from(keepFirst).length;
    const range = sourceRangeForSubtitleChars(subtitle, removeStartChar, removeEndChar);
    if (range.end > range.start + 0.02) ranges.push(range);
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

function pauseRangeOverlapsMeaningfulSubtitle(range: SilenceRange, subtitles: JobManualEditSubtitle[], fillers: string[]) {
  return subtitles.some((subtitle) => {
    const overlap = Math.min(range.end, subtitle.end_time) - Math.max(range.start, subtitle.start_time);
    if (overlap <= 0.08) return false;
    return smartCutMeaningfulText(subtitleTranscriptSourceText(subtitle) || subtitleText(subtitle), fillers).length >= 2;
  });
}

export function buildSmartCutRuleAnalysis(subtitles: JobManualEditSubtitle[], rules: SmartCutRules, silenceRanges: SilenceRange[] = []): SmartCutRuleAnalysis {
  const analysis: SmartCutRuleAnalysis = {
    filler: [],
    repeated: [],
    pause: [],
  };
  const fillers = parseSmartCutFillers(rules.fillers);
  for (const subtitle of subtitles) {
    for (const filler of fillers) {
      analysis.filler.push(...findTextRangesInSubtitle(subtitle, filler).map((range) => ({ ...range, kind: "filler" as const })));
    }
    analysis.repeated.push(...findRepeatedSpeechRangesInSubtitle(subtitle).map((range) => ({ ...range, kind: "repeated" as const })));
  }
  for (const range of silenceRanges) {
    const pause = range.end - range.start;
    if (pauseRangeOverlapsMeaningfulSubtitle(range, subtitles, fillers)) continue;
    if (pause >= rules.pauseThresholdSec) {
      analysis.pause.push({
        start: Number(range.start.toFixed(3)),
        end: Number(range.end.toFixed(3)),
        kind: "pause",
      });
    }
  }
  return {
    filler: analysis.filler.filter((range) => range.end > range.start + 0.02),
    repeated: analysis.repeated.filter((range) => range.end > range.start + 0.02),
    pause: analysis.pause.filter((range) => range.end > range.start + 0.02),
  };
}

export function autoSmartCutRuleRanges(analysis: SmartCutRuleAnalysis, rules: SmartCutRules) {
  return [
    ...(rules.fillerEnabled ? analysis.filler : []),
    ...(rules.repeatedEnabled ? analysis.repeated : []),
    ...(rules.pauseEnabled ? analysis.pause : []),
  ];
}

function smartCutRulesSignature(rules: SmartCutRules) {
  const normalized = normalizeSmartCutRules(rules);
  return JSON.stringify({
    fillerEnabled: normalized.fillerEnabled,
    repeatedEnabled: normalized.repeatedEnabled,
    pauseEnabled: normalized.pauseEnabled,
    pauseThresholdSec: normalized.pauseThresholdSec,
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
  const resumeTimelineAfterSubtitleEditRef = useRef(false);
  const currentEditSnapshotRef = useRef<ManualEditUndoSnapshot | null>(null);
  const undoStackRef = useRef<ManualEditUndoSnapshot[]>([]);
  const [segments, setSegments] = useState<KeepSegment[]>([]);
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(0);
  const [editorNote, setEditorNote] = useState("");
  const [videoSummary, setVideoSummary] = useState("");
  const [currentSourceTime, setCurrentSourceTime] = useState(0);
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false);
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
  const [timelineHoverOutputTime, setTimelineHoverOutputTime] = useState<number | null>(null);
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
    setEditorNote(restored.editorNote);
    setVideoSummary(restored.videoSummary);
    setVideoTransform(restored.videoTransform);
    setRotationDraft(restored.videoTransform.rotation_cw);
    setResolutionDraft(restored.videoTransform);
    setRotationDialogOpen(false);
    setResolutionDialogOpen(false);
    resumeAfterSubtitleEditRef.current = false;
    resumeTimelineAfterSubtitleEditRef.current = false;
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
    lastAutoSmartCutSignatureRef.current = "";
    setManualTermDraft("");
    setManualReplacementDraft("");
    setManualTermKeys([]);
    setEditorNote("");
    setVideoSummary(session.video_summary || "");
    setCurrentSourceTime(0);
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
    resumeTimelineAfterSubtitleEditRef.current = false;
  }, [session.job_id, session.timeline_id, session.timeline_version, session.keep_segments, session.subtitle_overrides, session.video_transform, session.video_summary]);

  useEffect(() => {
    currentEditSnapshotRef.current = buildUndoSnapshot();
  }, [currentSubtitleDraftText, editorNote, editingSubtitleIndex, segments, selectedSegmentIndex, selectedSubtitleIndex, subtitleDrafts, subtitleReplacementHistory, videoSummary, videoTransform]);

  const effectiveSegments = useMemo(
    () => segments.filter((segment) => segment.end > segment.start + 0.05),
    [segments],
  );

  const baseProjection = useMemo(
    () => {
      const sessionKeepSegments = session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end }));
      if (
        session.projected_subtitles.length
        && keepSegmentsEquivalent(effectiveSegments, sessionKeepSegments)
      ) {
        const { ranges, totalDuration } = buildOutputRanges(effectiveSegments);
        return {
          ranges,
          totalDuration,
          remapped: sortedSubtitles(session.projected_subtitles),
        };
      }
      if (session.projected_subtitles.length) {
        return remapProjectedSubtitlesFromBaseTimeline(
          session.projected_subtitles,
          sessionKeepSegments,
          effectiveSegments,
        );
      }
      const fallbackProjection = remapSubtitles(session.source_subtitles, effectiveSegments);
      return fallbackProjection;
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
    return buildSourceTranscriptSubtitlesForTimeline(session, projection.remapped, subtitleDrafts);
  }, [projection.remapped, session.source_subtitles, session.projected_subtitles, subtitleDrafts]);
  const sourceSilenceRanges = useMemo(() => {
    const audioSilences = previewAssets?.silence_intervals?.length
      ? previewAssets.silence_intervals
      : session.silence_segments || [];
    return normalizeSilenceRanges(
      [
        ...subtitlePauseIntervals(sourceTranscriptSubtitles),
        ...audioSilences,
      ],
      session.source_duration_sec,
    );
  }, [previewAssets?.silence_intervals, session.silence_segments, session.source_duration_sec, sourceTranscriptSubtitles]);
  const transcriptTokens = useMemo(
    () => buildTranscriptTokens(sourceTranscriptSubtitles, effectiveSegments, sourceSilenceRanges),
    [effectiveSegments, sourceSilenceRanges, sourceTranscriptSubtitles],
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
    () => transcriptTokens.findIndex((token) => currentSourceTime >= token.start - 0.015 && currentSourceTime <= token.end + 0.015),
    [currentSourceTime, transcriptTokens],
  );

  const activeSubtitleIndex = useMemo(
    () => {
      if (activePreviewOutputTime == null) return -1;
      return projection.remapped.findIndex((item) => activePreviewOutputTime >= item.start_time && activePreviewOutputTime <= item.end_time + 0.02);
    },
    [activePreviewOutputTime, projection.remapped],
  );

  const visibleSubtitles = projection.remapped;
  const smartCutRuleAnalysis = useMemo(
    () => buildSmartCutRuleAnalysis(sourceTranscriptSubtitles, smartCutRules, sourceSilenceRanges),
    [smartCutRules, sourceSilenceRanges, sourceTranscriptSubtitles],
  );
  const smartCutRuleRanges = useMemo(
    () => autoSmartCutRuleRanges(smartCutRuleAnalysis, smartCutRules),
    [smartCutRuleAnalysis, smartCutRules],
  );
  const smartCutRuleCounts = useMemo(
    () => ({
      filler: smartCutRuleAnalysis.filler.length,
      repeated: smartCutRuleAnalysis.repeated.length,
      pause: smartCutRuleAnalysis.pause.length,
    }),
    [smartCutRuleAnalysis],
  );
  const smartCutRuleKeptRangeCount = useMemo(
    () => smartCutRuleRanges.filter((range) => isSourceRangeKept(range.start, range.end, effectiveSegments)).length,
    [effectiveSegments, smartCutRuleRanges],
  );

  const totalOutputDuration = projection.totalDuration;
  const activeSubtitle = activeSubtitleIndex >= 0 ? projection.remapped[activeSubtitleIndex] : null;
  const baseKeepSegments = session.base_keep_segments?.length ? session.base_keep_segments : session.keep_segments;
  const baseVideoSummary = (session.base_video_summary || "").trim();
  const currentVideoSummary = videoSummary.trim();
  const baseVideoTransform = useMemo(() => normalizeVideoTransform(session.base_video_transform), [session.base_video_transform]);
  const currentVideoTransform = useMemo(() => normalizeVideoTransform(videoTransform), [videoTransform]);
  const baseVideoRotation = baseVideoTransform.rotation_cw;
  const currentVideoRotation = currentVideoTransform.rotation_cw;
  const hasVideoTransformEdits = JSON.stringify(currentVideoTransform) !== JSON.stringify(baseVideoTransform);
  const hasVideoSummaryEdits = currentVideoSummary !== baseVideoSummary;
  const previewVideoUrl = previewAssets?.ready && previewAssets.video_url ? previewAssets.video_url : session.source_url;
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
  const timelineThumbnailItems = useMemo(
    () => thumbnailItems.map((item) => sourceTimeToOutputThumbnailItem(item, projection.ranges)),
    [projection.ranges, thumbnailItems],
  );
  const unifiedThumbnailItems = useMemo<UnifiedTimelineThumbnailItem[]>(() => {
    const keptItems = timelineThumbnailItems.filter((item) => item.kept && item.output_time != null);
    if (!keptItems.length || totalOutputDuration <= 0) return [];
    const estimatedWidth = clamp(100 / Math.max(8, keptItems.length), 3.5, 8);
    return keptItems.map((item, index) => ({
      ...item,
      leftPercent: clamp(((item.output_time ?? 0) / totalOutputDuration) * 100, 0, 100),
      widthPercent: index === keptItems.length - 1
        ? estimatedWidth
        : clamp((((keptItems[index + 1].output_time ?? 0) - (item.output_time ?? 0)) / totalOutputDuration) * 100, estimatedWidth, 10),
    }));
  }, [timelineThumbnailItems, totalOutputDuration]);
  const unifiedWaveformBars = useMemo(
    () => buildOutputWaveformBars(previewAssets?.peaks, projection.ranges, totalOutputDuration, session.source_duration_sec, 220),
    [previewAssets?.peaks, projection.ranges, session.source_duration_sec, totalOutputDuration],
  );
  const timelineRulerTicks = useMemo(
    () => Array.from({ length: 7 }, (_, index) => {
      const ratio = index / 6;
      return {
        key: index,
        leftPercent: ratio * 100,
        label: formatSeconds(totalOutputDuration * ratio),
      };
    }),
    [totalOutputDuration],
  );
  const timelinePlayheadOutputTime = clamp(currentOutputTime, 0, Math.max(0, totalOutputDuration));
  const unifiedTimelineStyle = {
    "--playhead-left": `${totalOutputDuration > 0 ? (timelinePlayheadOutputTime / totalOutputDuration) * 100 : 0}%`,
    "--hover-left": timelineHoverOutputTime == null || totalOutputDuration <= 0
      ? "-100%"
      : `${clamp((timelineHoverOutputTime / totalOutputDuration) * 100, 0, 100)}%`,
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
      note: editorNote.trim() || undefined,
    }),
    [currentVideoSummary, currentVideoTransform, effectiveSegments, editorNote, session.render_plan_version, session.timeline_id, session.timeline_version, subtitleOverrides, subtitleReplacements],
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
  useEffect(() => {
    onStateChange?.({
      payload: manualEditorPayload,
      canApply: session.editable && Boolean(onApply) && hasMaterialEdits && effectiveSegments.length > 0,
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
    saveImpactSummary,
    savePlanLabel,
    session.editable,
    subtitleOverrides.length,
  ]);
  const selectedSubtitlePosition = selectedSubtitle
    ? projection.remapped.findIndex((subtitle) => subtitle.index === selectedSubtitle.index)
    : activeSubtitleIndex;
  const subtitleTableWindow = useMemo(() => {
    const subtitles = projection.remapped;
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
  }, [projection.remapped, selectedSubtitlePosition]);

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

    const activeRangeIndex = projection.ranges.findIndex((range) => sourceTime >= range.sourceStart && sourceTime < range.sourceEnd - 0.02);
    if (activeRangeIndex >= 0) {
      const activeRange = projection.ranges[activeRangeIndex];
      if (sourceTime >= activeRange.sourceEnd - 0.03) {
        const nextRange = projection.ranges[activeRangeIndex + 1];
        if (nextRange) {
          video.currentTime = nextRange.sourceStart;
          setPreviewSourceTime(nextRange.sourceStart, true);
        } else {
          timelinePlaybackRef.current = false;
          void video.pause();
        }
      }
      return;
    }

    const nextRange = projection.ranges.find((range) => range.sourceStart > sourceTime);
    if (nextRange) {
      video.currentTime = nextRange.sourceStart;
      setPreviewSourceTime(nextRange.sourceStart, true);
      return;
    }
    timelinePlaybackRef.current = false;
    void video.pause();
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
    const alreadyThere = Math.abs(Number(video.currentTime || 0) - nextSourceTime) <= 0.015;
    waveSurferRef.current?.setTime(nextSourceTime);
    setPreviewSourceTime(nextSourceTime, true);
    if (alreadyThere && !video.seeking) {
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

  const jumpToOutputTime = (outputTime: number) => {
    const video = videoRef.current;
    if (!video || !projection.ranges.length) return;
    const sourceTime = outputTimeToSourceTime(outputTime, projection.ranges);
    void seekPreviewToSourceTime(video, sourceTime);
  };

  const jumpToSourceTime = (sourceTime: number) => {
    const nextSourceTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
    const video = videoRef.current;
    if (video) {
      void seekPreviewToSourceTime(video, nextSourceTime);
      return;
    }
    waveSurferRef.current?.setTime(nextSourceTime);
    setPreviewSourceTime(nextSourceTime, true);
  };

  const reanchorPreviewToSegments = (nextSegments: KeepSegment[], outputTime = currentOutputTime) => {
    const nextSourceTime = outputTimeToSourceTimeForSegments(outputTime, nextSegments);
    jumpToSourceTime(nextSourceTime);
  };

  const selectSubtitleNearOutputTime = (outputTime: number) => {
    if (editingSubtitleIndex != null) return;
    const subtitleIndex = findSubtitleIndexNearOutputTime(projection.remapped, outputTime);
    const subtitle = projection.remapped[subtitleIndex];
    if (subtitle) setSelectedSubtitleIndex(subtitle.index);
  };

  const outputTimeFromUnifiedTimelinePointer = (event: { clientX: number }) => {
    const timeline = unifiedTimelineRef.current;
    if (!timeline || totalOutputDuration <= 0) return null;
    const rect = timeline.getBoundingClientRect();
    if (rect.width <= 0) return null;
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    return totalOutputDuration * ratio;
  };

  const previewUnifiedTimelineAtPointer = (event: ReactPointerEvent<HTMLElement>) => {
    const outputTime = outputTimeFromUnifiedTimelinePointer(event);
    if (outputTime == null) return;
    setTimelineHoverOutputTime(outputTime);
  };

  const commitUnifiedTimelinePointer = (event: { clientX: number }) => {
    const outputTime = outputTimeFromUnifiedTimelinePointer(event);
    if (outputTime == null || !projection.ranges.length) return;
    setTimelineHoverOutputTime(outputTime);
    selectSubtitleNearOutputTime(outputTime);
    jumpToOutputTime(outputTime);
  };

  const playEditedTimeline = async () => {
    const video = videoRef.current;
    if (!video || !projection.ranges.length) return;
    timelinePlaybackRef.current = true;
    const currentRange = projection.ranges.find((range) => currentSourceTime >= range.sourceStart && currentSourceTime <= range.sourceEnd);
    const shouldRestart = !currentRange || currentOutputTime >= Math.max(0, totalOutputDuration - 0.08);
    if (shouldRestart) {
      await seekPreviewToSourceTime(video, projection.ranges[0].sourceStart);
    }
    applyPreviewAudioSettings(previewVolume, previewMuted, previewAutoVolumeEnabled, true);
    await video.play();
    startPreviewClock();
  };

  const pauseEditedTimeline = () => {
    timelinePlaybackRef.current = false;
    setIsPreviewPlaying(false);
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

  useEffect(() => () => {
    stopPreviewClock();
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
    resumeTimelineAfterSubtitleEditRef.current = timelinePlaybackRef.current;
    if (video && !video.paused) void video.pause();
    timelinePlaybackRef.current = false;
  };

  const resumeAfterSubtitleEdit = (options?: { force?: boolean }) => {
    const shouldResume = resumeAfterSubtitleEditRef.current;
    const shouldResumeTimeline = resumeTimelineAfterSubtitleEditRef.current;
    resumeAfterSubtitleEditRef.current = false;
    resumeTimelineAfterSubtitleEditRef.current = false;
    if (!shouldResume && !options?.force) return;
    if (shouldResumeTimeline || options?.force) {
      void playEditedTimeline();
      return;
    }
    void videoRef.current?.play();
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
    resumeTimelineAfterSubtitleEditRef.current = false;
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
  };

  const handlePreviewVideoError = (event: SyntheticEvent<HTMLVideoElement>) => {
    const code = event.currentTarget.error?.code;
    const message = code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED
      ? "浏览器无法解码当前预览视频，正在使用兼容代理仍失败。请重新生成预览资产或检查 ffmpeg。"
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

  const selectTranscriptToken = (tokenIndex: number) => {
    const token = transcriptTokens[tokenIndex];
    if (!token) return;
    const nextSelection = transcriptSelectionFromTokenRange(transcriptTokens, tokenIndex, tokenIndex);
    setTranscriptSelection(nextSelection);
    setTranscriptSelectionPopover(transcriptSelectionPopoverPositionFromRect(transcriptTokenRefs.current.get(tokenIndex)?.getBoundingClientRect() ?? null));
    jumpToSourceTime(token.start);
    if (token.subtitleIndex != null) {
      const subtitle = projection.remapped.find((item) => subtitleSourceIndex(item) === token.subtitleIndex)
        ?? projection.remapped.find((item) => item.index === token.subtitleIndex);
      if (subtitle) setSelectedSubtitleIndex(subtitle.index);
    }
  };

  const cutTranscriptSelection = () => {
    if (!transcriptSelection) return;
    const range = { start: transcriptSelection.sourceStart, end: transcriptSelection.sourceEnd };
    const nextSegments = removeSourceRangesFromSegments(effectiveSegments, [range]);
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
    clearTranscriptSelection();
  };

  const restoreTranscriptSelection = () => {
    if (!transcriptSelection) return;
    const range = { start: transcriptSelection.sourceStart, end: transcriptSelection.sourceEnd };
    recordUndoSnapshot();
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

  const applySmartCutRuleRanges = (ranges: KeepSegment[]) => {
    const baseSegments = baseKeepSegments.map((segment) => ({ start: segment.start, end: segment.end }));
    if (!baseSegments.length) return;
    const keptRanges = ranges.filter((range) => isSourceRangeKept(range.start, range.end, baseSegments));
    const nextSegments = keptRanges.length
      ? removeSourceRangesFromSegments(baseSegments, keptRanges)
      : baseSegments;
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
    if (!session.editable || !baseKeepSegments.length) return;
    const signature = [
      session.job_id,
      session.timeline_id,
      session.timeline_version,
      JSON.stringify(baseKeepSegments.map((segment) => [segment.start, segment.end])),
      smartCutRulesSignature(smartCutRules),
      JSON.stringify(smartCutRuleRanges.map((range) => [range.kind, range.start, range.end])),
    ].join(":");
    if (signature === lastAutoSmartCutSignatureRef.current) return;
    lastAutoSmartCutSignatureRef.current = signature;
    applySmartCutRuleRanges(smartCutRuleRanges);
  }, [baseKeepSegments, session.editable, session.job_id, session.timeline_id, session.timeline_version, smartCutRuleRanges, smartCutRules]);

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
    playEditedTimeline,
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
  }, [currentVideoRotation, currentVideoTransform.aspect_ratio, previewDisabled, previewVideoUrl, sourceVideoSize]);

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
  }, [previewDisabled, previewVideoUrl, session.job_id]);

  useEffect(() => {
    setFloatingPreviewPosition(null);
    floatingPreviewDragRef.current = null;
  }, [session.job_id, previewVideoUrl]);

  useEffect(() => {
    setPreviewVideoLoadError(null);
    setPreviewVideoLoadProgress(null);
    setPreviewVideoLoading(Boolean(previewVideoUrl));
    setPreviewVideoLoadingLabel("正在载入视频");
  }, [previewVideoUrl]);

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
            基于当前时间线做人工删段和边界微调，字幕会按同一套保留段实时前移预览。保存后会从渲染开始重跑，继续生成特效和数字人版本。
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
                <video src={session.source_url ?? undefined} muted playsInline preload="metadata" onLoadedMetadata={rememberVideoMetadata} />
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
        <span><kbd>Space</kbd> 播放/暂停</span>
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
                <div className="notice">当前机器拿不到原片本地路径，暂时不能内嵌预览，但仍可调整并保存时间线。</div>
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
                    aria-label={isPreviewPlaying ? "暂停输出时间轴预览" : "播放输出时间轴预览"}
                  >
                    <div className="manual-editor-video-stage">
                      <video
                        key={previewVideoUrl ?? "manual-preview"}
                        ref={videoRef}
                        className="manual-editor-video"
                        src={previewVideoUrl ?? undefined}
                        preload="metadata"
                        playsInline
                        onLoadStart={() => {
                          setPreviewVideoLoading(true);
                          setPreviewVideoLoadingLabel("正在载入视频");
                          setPreviewVideoLoadProgress(null);
                        }}
                        onLoadedMetadata={(event) => {
                          rememberVideoMetadata(event);
                          fallbackPreviewElementVolume(event.currentTarget, previewVolume, previewMuted, previewAutoVolumeEnabled);
                        }}
                        onLoadedData={(event) => {
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                        }}
                        onProgress={(event) => updatePreviewVideoLoadProgress(event.currentTarget)}
                        onCanPlay={(event) => {
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                        }}
                        onWaiting={(event) => {
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(true);
                          setPreviewVideoLoadingLabel("正在缓冲视频");
                        }}
                        onPlaying={(event) => {
                          updatePreviewVideoLoadProgress(event.currentTarget);
                          setPreviewVideoLoading(false);
                          setIsPreviewPlaying(true);
                          startPreviewClock();
                        }}
                        onPlay={() => {
                          setIsPreviewPlaying(true);
                          startPreviewClock();
                        }}
                        onError={handlePreviewVideoError}
                        onTimeUpdate={syncPreviewTime}
                        onSeeked={syncPreviewTime}
                        onPause={() => {
                          if (videoRef.current?.paused) {
                            timelinePlaybackRef.current = false;
                            setIsPreviewPlaying(false);
                            stopPreviewClock();
                          }
                        }}
                        onEnded={() => {
                          timelinePlaybackRef.current = false;
                          setIsPreviewPlaying(false);
                          stopPreviewClock();
                        }}
                      />
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
                        disabled={previewDisabled || !effectiveSegments.length}
                        onClick={toggleEditedTimelinePlayback}
                        aria-label={isPreviewPlaying ? "暂停输出时间轴预览" : "播放输出时间轴预览"}
                      >
                        {isPreviewPlaying ? "暂停" : "播放"}
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
                      <span>{formatSeconds(currentOutputTime)} / {formatSeconds(totalOutputDuration)}</span>
                    </div>
                  </div>
                </div>
              )}
              {currentVideoRotation ? <div className="manual-editor-rotation-status">当前预览已顺时针旋转 {currentVideoRotation}°，该参数会自动保存并用于重渲染。</div> : null}

              <div className="manual-editor-controls">
                <button type="button" className="button primary" disabled={previewDisabled || !effectiveSegments.length} onClick={toggleEditedTimelinePlayback}>
                  {isPreviewPlaying ? "暂停输出预览" : "播放输出预览"}
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
                    const breakNode = token.breakAfter ? (
                      <span className={classNames("manual-editor-transcript-break", token.breakAfter === "paragraph" && "paragraph")} aria-hidden="true">
                        <br />
                      </span>
                    ) : null;
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
                            className={classNames("manual-editor-transcript-pause", !token.kept && "cut", active && "active", selected && "selected")}
                            data-transcript-token-index={index}
                            onClick={() => selectTranscriptToken(index)}
                            title={`停顿 ${formatSeconds(token.start)} - ${formatSeconds(token.end)}`}
                          >
                            {token.text}
                          </button>
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
                          className={classNames("manual-editor-transcript-token", !token.kept && "cut", active && "active", selected && "selected")}
                          data-transcript-token-index={index}
                          onClick={() => selectTranscriptToken(index)}
                          title={`${formatSeconds(token.start)} - ${formatSeconds(token.end)}`}
                        >
                          {token.text}
                        </span>
                        {token.inferredPunctuation ? <span className={classNames("manual-editor-transcript-punctuation", !token.kept && "cut")} aria-hidden="true">{token.inferredPunctuation}</span> : null}
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
                  <span className="status-pill pending">规则命中 待剪 {smartCutRuleKeptRangeCount}</span>
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
                    </div>
                    <input
                      className="input"
                      value={smartCutRules.fillers}
                      onChange={(event) => updateSmartCutRule({ fillers: event.target.value })}
                      placeholder="自定义语气词，用逗号分隔"
                    />
                    <div className="manual-editor-rule-memory">规则设置已全局记忆；勾选后的语气词、重复口误和长停顿会进入待剪区间。</div>
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
            onPointerLeave={() => setTimelineHoverOutputTime(null)}
            aria-label="统一时间轴"
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
              <span>{timelineHoverOutputTime == null ? "" : formatSeconds(timelineHoverOutputTime)}</span>
            </div>
            <div className="manual-editor-unified-playhead" aria-hidden="true">
              <span>{formatSeconds(timelinePlayheadOutputTime)}</span>
            </div>

            <div className="manual-editor-unified-clip">
              <div className="manual-editor-unified-clip-head">
                <strong>{job?.source_name ?? session.source_name}</strong>
                <span>{formatSeconds(totalOutputDuration)}</span>
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
                        selectSubtitleNearOutputTime(item.output_time ?? 0);
                        jumpToSourceTime(item.time_sec);
                      }}
                      title={`输出 ${formatSeconds(item.output_time ?? 0)} / 源 ${formatSeconds(item.time_sec)}`}
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

            {projection.remapped.length ? (
              <div className="manual-editor-unified-subtitles" aria-label="字幕定位轨">
                {projection.remapped.map((subtitle) => {
                  const left = totalOutputDuration > 0 ? (subtitle.start_time / totalOutputDuration) * 100 : 0;
                  const width = totalOutputDuration > 0 ? ((subtitle.end_time - subtitle.start_time) / totalOutputDuration) * 100 : 0;
                  const selected = selectedSubtitle?.index === subtitle.index;
                  const warning = Boolean(diagnostics.warnings[subtitle.index]?.length);
                  return (
                    <button
                      key={`${subtitle.index}-${subtitle.start_time}-timeline`}
                      type="button"
                      className={classNames("manual-editor-unified-subtitle", selected && "active", warning && "warning")}
                      style={{ left: `${clamp(left, 0, 100)}%`, width: `${Math.max(width, 0.8)}%` }}
                      onClick={(event) => {
                        event.stopPropagation();
                        selectSubtitle(subtitle);
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

          {previewAssets ? (
            <div className="manual-editor-preview-assets">
              <div className="manual-editor-preview-asset-status">
                <span>{previewAssetStatusLabel(previewAssets)}</span>
                <span>{previewAssetStageLabel(previewAssets.stage)}</span>
                <span>{previewAssetProgressPercent != null ? `${previewAssetProgressPercent}%` : previewAssets.ready ? "100%" : "0%"}</span>
                <span>{previewAssets.ready ? `${previewAssets.peak_count} peaks` : "使用原片预览"}</span>
                {previewAssets.ready && previewAssets.video_url ? <span>浏览器兼容视频代理</span> : null}
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
            <span className={classNames("status-pill", diagnostics.issueCount ? "failed" : "done")}>
              问题 {diagnostics.issueCount}
            </span>
          </div>
        </div>

        {subtitleTableWindow.clipped ? (
          <div className="notice manual-editor-window-notice">
            为保持页面响应速度，当前只渲染第 {subtitleTableWindow.start + 1} - {subtitleTableWindow.end} 条字幕，共 {projection.remapped.length} 条；定位到其他字幕后窗口会自动切换。
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
            const selected = selectedSubtitle?.index === subtitle.index;
            const changed = Boolean(subtitleDrafts[subtitle.index]) && subtitleOverrideChanged(
              baseProjection.remapped.find((item) => item.index === subtitle.index),
              subtitleDrafts[subtitle.index],
            );
            const rowWarnings = diagnostics.warnings[subtitle.index] || [];
            return (
              <div key={`${subtitle.index}-${subtitle.start_time}`} className={classNames("manual-editor-subtitle-row", selected && "active", changed && "changed", rowWarnings.length > 0 && "warning")}>
                <button type="button" className="manual-editor-subtitle-index" onClick={() => selectSubtitle(subtitle)}>
                  {subtitle.index + 1}
                </button>
                <input
                  className="input"
                  type="number"
                  step={0.01}
                  min={0}
                  max={totalOutputDuration}
                  value={subtitle.start_time}
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
                  onFocus={() => setSelectedSubtitleIndex(subtitle.index)}
                  onChange={(event) => updateSubtitleDraft(subtitle, { end_time: Number(event.target.value || 0) })}
                />
                <span className={classNames("manual-editor-subtitle-state", rowWarnings.length > 0 && "warning")}>
                  {rowWarnings.length ? rowWarnings.join(" / ") : "正常"}
                </span>
                <input
                  className="input"
                  value={subtitleText(subtitle)}
                  onFocus={() => setSelectedSubtitleIndex(subtitle.index)}
                  onSelect={rememberSelectedSubtitleText}
                  onChange={(event) => updateSubtitleDraft(subtitle, { text_final: event.target.value })}
                />
                <div className="manual-editor-actions">
                  <button type="button" className="button ghost" onClick={() => selectSubtitle(subtitle)}>
                    定位
                  </button>
                  <button type="button" className="button ghost" disabled={!changed} onClick={() => resetSubtitleDraft(subtitle)}>
                    还原
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </section>
  );
}

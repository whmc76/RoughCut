import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import type { RegionsPlugin as RegionsPluginInstance } from "wavesurfer.js/dist/plugins/regions.esm.js";
import TimelinePlugin from "wavesurfer.js/dist/plugins/timeline.esm.js";

import type { Job, JobManualEditApplyPayload, JobManualEditPreviewAssets, JobManualEditSession, JobManualEditSubtitle, JobManualEditSubtitleOverride } from "../../types";
import { classNames } from "../../utils";

type JobManualEditSectionProps = {
  job?: Job;
  session: JobManualEditSession;
  previewAssets?: JobManualEditPreviewAssets;
  saving: boolean;
  onApply?: (payload: JobManualEditApplyPayload) => void;
};

type KeepSegment = {
  start: number;
  end: number;
};

type OutputRange = {
  sourceStart: number;
  sourceEnd: number;
  outputStart: number;
  outputEnd: number;
};

type SubtitleDraft = {
  start_time?: number | null;
  end_time?: number | null;
  text_final?: string | null;
  delete?: boolean;
  virtual?: boolean;
};

const REGION_COLOR = "rgba(34, 197, 94, 0.22)";
const REGION_ACTIVE_COLOR = "rgba(20, 184, 166, 0.36)";
const MIN_SUBTITLE_DURATION_SEC = 0.08;
const MIN_SUBTITLE_GAP_SEC = 0.02;
const INITIAL_WAVEFORM_ZOOM = 18;

function regionIdForIndex(index: number) {
  return `keep-${index}`;
}

function subtitleText(subtitle: JobManualEditSubtitle) {
  return subtitle.text_final || subtitle.text_norm || subtitle.text_raw || "";
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
    case "proxy_audio":
      return "生成音频代理";
    case "waveform_peaks":
      return "计算波形峰值";
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

function isTextEntryTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}

function remapSubtitles(subtitles: JobManualEditSubtitle[], keepSegments: KeepSegment[]) {
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

  const remapped = subtitles
    .map((subtitle, index) => {
      const subtitleStart = Number(subtitle.start_time || 0);
      const subtitleEnd = Number(subtitle.end_time || 0);
      let bestDuration = 0;
      let bestWindow: { start: number; end: number } | null = null;
      for (const range of ranges) {
        const overlapStart = Math.max(subtitleStart, range.sourceStart);
        const overlapEnd = Math.min(subtitleEnd, range.sourceEnd);
        const overlapDuration = overlapEnd - overlapStart;
        if (overlapDuration <= bestDuration) continue;
        bestDuration = overlapDuration;
        bestWindow = {
          start: range.outputStart + (overlapStart - range.sourceStart),
          end: range.outputStart + (overlapEnd - range.sourceStart),
        };
      }
      if (!bestWindow || bestWindow.end <= bestWindow.start + 0.05) return null;
      return {
        ...subtitle,
        index: subtitle.index ?? index,
        start_time: Number(bestWindow.start.toFixed(3)),
        end_time: Number(bestWindow.end.toFixed(3)),
      };
    })
    .filter(Boolean) as JobManualEditSubtitle[];

  return { remapped, ranges, totalDuration: outputCursor };
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

function outputTimeToSourceTime(outputTime: number, ranges: OutputRange[]) {
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

function sourceTimeToOutputTime(sourceTime: number, ranges: OutputRange[]) {
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

export function JobManualEditSection({ job, session, previewAssets, saving, onApply }: JobManualEditSectionProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const waveformRef = useRef<HTMLDivElement | null>(null);
  const waveformTimelineRef = useRef<HTMLDivElement | null>(null);
  const waveSurferRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPluginInstance | null>(null);
  const syncingRegionsRef = useRef(false);
  const timelinePlaybackRef = useRef(false);
  const [segments, setSegments] = useState<KeepSegment[]>([]);
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(0);
  const [editorNote, setEditorNote] = useState("");
  const [currentSourceTime, setCurrentSourceTime] = useState(0);
  const [selectedSubtitleIndex, setSelectedSubtitleIndex] = useState<number | null>(null);
  const [subtitleDrafts, setSubtitleDrafts] = useState<Record<number, SubtitleDraft>>({});
  const [batchShiftMs, setBatchShiftMs] = useState(100);
  const [waveformZoom, setWaveformZoom] = useState(INITIAL_WAVEFORM_ZOOM);
  const [waveformReady, setWaveformReady] = useState(false);
  const [waveformError, setWaveformError] = useState<string | null>(null);

  useEffect(() => {
    setSegments(session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end })));
    setSelectedSegmentIndex(0);
    setSelectedSubtitleIndex(null);
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
    setEditorNote("");
    setCurrentSourceTime(0);
    setWaveformReady(false);
    setWaveformError(null);
    timelinePlaybackRef.current = false;
  }, [session.job_id, session.timeline_id, session.timeline_version, session.keep_segments, session.subtitle_overrides]);

  const effectiveSegments = useMemo(
    () => segments.filter((segment) => segment.end > segment.start + 0.05),
    [segments],
  );

  const baseProjection = useMemo(
    () => remapSubtitles(session.source_subtitles, effectiveSegments),
    [session.source_subtitles, effectiveSegments],
  );

  const projection = useMemo(
    () => ({
      ...baseProjection,
      remapped: applySubtitleDrafts(baseProjection.remapped, subtitleDrafts),
    }),
    [baseProjection, subtitleDrafts],
  );

  const currentOutputTime = useMemo(
    () => sourceTimeToOutputTime(currentSourceTime, projection.ranges),
    [currentSourceTime, projection.ranges],
  );

  const activeSubtitleIndex = useMemo(
    () => projection.remapped.findIndex((item) => currentOutputTime >= item.start_time && currentOutputTime <= item.end_time + 0.02),
    [currentOutputTime, projection.remapped],
  );

  const visibleSubtitles = useMemo(() => {
    if (!projection.remapped.length) return [];
    if (activeSubtitleIndex < 0) return projection.remapped.slice(0, 8);
    const start = Math.max(0, activeSubtitleIndex - 2);
    return projection.remapped.slice(start, start + 8);
  }, [activeSubtitleIndex, projection.remapped]);

  const selectedSegment = effectiveSegments[selectedSegmentIndex] ?? effectiveSegments[0] ?? null;
  const totalOutputDuration = projection.totalDuration;
  const activeSubtitle = activeSubtitleIndex >= 0 ? projection.remapped[activeSubtitleIndex] : null;
  const waveformUrl = previewAssets?.ready && previewAssets.audio_url ? previewAssets.audio_url : session.source_url || "";
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
  const thumbnailStripStyle = {
    "--thumb-width": `${Math.max(76, Math.min(180, waveformZoom * 4))}px`,
  } as CSSProperties;
  const previewAssetProgress = previewAssets?.progress == null ? null : clamp(previewAssets.progress, 0, 1);
  const previewAssetProgressPercent = previewAssetProgress == null ? null : Math.round(previewAssetProgress * 100);
  const selectedSubtitle = useMemo(
    () => projection.remapped.find((subtitle) => subtitle.index === selectedSubtitleIndex) ?? activeSubtitle ?? projection.remapped[0] ?? null,
    [activeSubtitle, projection.remapped, selectedSubtitleIndex],
  );
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
  const diagnostics = useMemo(
    () => subtitleDiagnostics(projection.remapped, totalOutputDuration),
    [projection.remapped, totalOutputDuration],
  );
  const hasTimelineEdits = useMemo(() => {
    if (session.keep_segments.length !== effectiveSegments.length) return true;
    return session.keep_segments.some((segment, index) => {
      const current = effectiveSegments[index];
      return !current || Math.abs(segment.start - current.start) > 0.02 || Math.abs(segment.end - current.end) > 0.02;
    });
  }, [effectiveSegments, session.keep_segments]);
  const initialOutputDuration = useMemo(
    () => session.keep_segments.reduce((total, segment) => total + Math.max(0, segment.end - segment.start), 0),
    [session.keep_segments],
  );
  const outputDurationDelta = totalOutputDuration - initialOutputDuration;
  const hasMaterialEdits = hasTimelineEdits || subtitleOverrides.length > 0;
  const savePlanLabel = hasTimelineEdits
    ? "剪辑变更：重建时间线/特效"
    : subtitleOverrides.length
      ? "字幕变更：复用剪辑/特效计划"
      : "暂无实质修改";
  const saveImpactSummary = hasTimelineEdits
    ? "会保存新的剪辑时间线，并从 render 开始重新生成成片、特效和数字人版本。"
    : subtitleOverrides.length
      ? "会保存字幕文本/时间修改，复用当前剪辑和特效计划重新烧录字幕层。"
      : "当前没有检测到剪辑或字幕修改。";
  const outputDurationDeltaLabel = `${outputDurationDelta >= 0 ? "+" : "-"}${formatSeconds(Math.abs(outputDurationDelta))}`;

  useEffect(() => {
    const waveformElement = waveformRef.current;
    const timelineElement = waveformTimelineRef.current;
    if (!waveformUrl || !waveformElement || !timelineElement) return;

    setWaveformReady(false);
    setWaveformError(null);

    const regionsPlugin = RegionsPlugin.create();
    const timelinePlugin = TimelinePlugin.create({
      container: timelineElement,
      height: 24,
      formatTimeCallback: formatSeconds,
    });
    const waveSurfer = WaveSurfer.create({
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

    return () => {
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
  }, [session.job_id, session.source_duration_sec, session.timeline_id, session.timeline_version, waveformDuration, waveformPeaks, waveformUrl]);

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

  const syncPreviewTime = () => {
    const video = videoRef.current;
    if (!video) return;
    const sourceTime = Number(video.currentTime || 0);
    setCurrentSourceTime(sourceTime);
    if (!timelinePlaybackRef.current || !projection.ranges.length) return;

    const activeRangeIndex = projection.ranges.findIndex((range) => sourceTime >= range.sourceStart && sourceTime < range.sourceEnd - 0.02);
    if (activeRangeIndex >= 0) {
      const activeRange = projection.ranges[activeRangeIndex];
      if (sourceTime >= activeRange.sourceEnd - 0.03) {
        const nextRange = projection.ranges[activeRangeIndex + 1];
        if (nextRange) {
          video.currentTime = nextRange.sourceStart;
          setCurrentSourceTime(nextRange.sourceStart);
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
      setCurrentSourceTime(nextRange.sourceStart);
      return;
    }
    timelinePlaybackRef.current = false;
    void video.pause();
  };

  const jumpToOutputTime = (outputTime: number) => {
    const video = videoRef.current;
    if (!video || !projection.ranges.length) return;
    const sourceTime = outputTimeToSourceTime(outputTime, projection.ranges);
    video.currentTime = sourceTime;
    setCurrentSourceTime(sourceTime);
  };

  const jumpToSourceTime = (sourceTime: number) => {
    const nextSourceTime = clamp(sourceTime, 0, session.source_duration_sec || sourceTime);
    const video = videoRef.current;
    if (video) video.currentTime = nextSourceTime;
    waveSurferRef.current?.setTime(nextSourceTime);
    setCurrentSourceTime(nextSourceTime);
  };

  const jumpToSegment = (index: number) => {
    const segment = effectiveSegments[index];
    if (!segment) return;
    setSelectedSegmentIndex(index);
    const video = videoRef.current;
    if (video) {
      video.currentTime = segment.start;
      setCurrentSourceTime(segment.start);
    }
  };

  const playEditedTimeline = async () => {
    const video = videoRef.current;
    if (!video || !projection.ranges.length) return;
    timelinePlaybackRef.current = true;
    const currentRange = projection.ranges.find((range) => currentSourceTime >= range.sourceStart && currentSourceTime <= range.sourceEnd);
    if (!currentRange) {
      video.currentTime = projection.ranges[0].sourceStart;
      setCurrentSourceTime(projection.ranges[0].sourceStart);
    }
    await video.play();
  };

  const pauseEditedTimeline = () => {
    timelinePlaybackRef.current = false;
    void videoRef.current?.pause();
  };

  const restoreInitialSegments = () => {
    setSegments(session.keep_segments.map((segment) => ({ start: segment.start, end: segment.end })));
    setSelectedSegmentIndex(0);
    setSelectedSubtitleIndex(null);
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
  };

  const removeSelectedSegment = () => {
    if (selectedSegmentIndex < 0 || selectedSegmentIndex >= effectiveSegments.length) return;
    setSegments((current) => current.filter((_, index) => index !== selectedSegmentIndex));
    setSelectedSegmentIndex((current) => Math.max(0, current - 1));
  };

  const updateSelectedSegment = (field: "start" | "end", nextValue: number) => {
    setSegments((current) =>
      current.map((segment, index) => {
        if (index !== selectedSegmentIndex) return segment;
        const previous = current[index - 1];
        const following = current[index + 1];
        if (field === "start") {
          const minStart = previous ? previous.end + 0.02 : 0;
          const maxStart = Math.max(minStart, segment.end - 0.1);
          return { ...segment, start: Number(clamp(nextValue, minStart, maxStart).toFixed(3)) };
        }
        const minEnd = segment.start + 0.1;
        const maxEnd = following ? following.start - 0.02 : session.source_duration_sec;
        return { ...segment, end: Number(clamp(nextValue, minEnd, maxEnd).toFixed(3)) };
      }),
    );
  };

  const updateSubtitleDraft = (subtitle: JobManualEditSubtitle, patch: SubtitleDraft) => {
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

  const selectSubtitle = (subtitle: JobManualEditSubtitle) => {
    setSelectedSubtitleIndex(subtitle.index);
    jumpToOutputTime(subtitle.start_time);
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
        `片段数：${session.keep_segments.length} -> ${effectiveSegments.length}`,
        `输出时长变化：${outputDurationDeltaLabel}`,
        `字幕修改：${subtitleOverrides.length} 条`,
        saveImpactSummary,
      ].join("\n"),
    );
    if (!confirmed) return;
    onApply({
      keep_segments: effectiveSegments.map((segment) => ({
        start: Number(segment.start.toFixed(3)),
        end: Number(segment.end.toFixed(3)),
      })),
      subtitle_overrides: subtitleOverrides,
      base_timeline_id: session.timeline_id,
      base_timeline_version: session.timeline_version,
      base_render_plan_version: session.render_plan_version,
      note: editorNote.trim() || undefined,
    });
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const textEntryTarget = isTextEntryTarget(event.target);
      const saveShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s";
      if (saveShortcut) {
        event.preventDefault();
        if (session.editable && !saving && onApply) handleApply();
        return;
      }
      if (textEntryTarget) return;

      if (event.code === "Space") {
        event.preventDefault();
        const video = videoRef.current;
        if (video && !video.paused) {
          pauseEditedTimeline();
        } else {
          void playEditedTimeline();
        }
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

      if ((event.key === "Delete" || event.key === "Backspace") && session.editable && effectiveSegments.length > 1) {
        event.preventDefault();
        removeSelectedSegment();
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
    removeSelectedSegment,
    saveImpactSummary,
    savePlanLabel,
    saving,
    session.editable,
    session.keep_segments.length,
    subtitleOverrides.length,
  ]);

  const previewDisabled = !session.source_url;

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
          <span className="status-pill pending">时间线 v{session.timeline_version}</span>
        </div>
      </div>

      {session.detail ? <div className="notice compact-top">{session.detail}</div> : null}
      <div className="manual-editor-shortcuts" aria-label="手动编辑快捷键">
        <span><kbd>Space</kbd> 播放/暂停</span>
        <span><kbd>←/→</kbd> 跳 1s</span>
        <span><kbd>Alt</kbd> + <kbd>←/→</kbd> 逐帧</span>
        <span><kbd>[</kbd>/<kbd>]</kbd> 字幕 ±100ms</span>
        <span><kbd>Alt</kbd> + <kbd>[</kbd>/<kbd>]</kbd> 字幕 ±10ms</span>
        <span><kbd>A</kbd>/<kbd>S</kbd> 设字幕起止</span>
        <span><kbd>J</kbd>/<kbd>K</kbd> 上/下字幕</span>
        <span><kbd>Ctrl/⌘</kbd> + <kbd>S</kbd> 保存</span>
      </div>

      <div className="manual-editor-stats top-gap">
        <article className="activity-card">
          <div className="muted">保留片段</div>
          <strong>{effectiveSegments.length}</strong>
        </article>
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
      <div className={classNames("manual-editor-save-impact", hasTimelineEdits && "timeline", subtitleOverrides.length > 0 && !hasTimelineEdits && "subtitle")}>
        <strong>{savePlanLabel}</strong>
        <span>{saveImpactSummary}</span>
        <span>片段 {session.keep_segments.length}{" -> "}{effectiveSegments.length}</span>
        <span>输出时长变化 {outputDurationDeltaLabel}</span>
        <span>字幕修改 {subtitleOverrides.length} 条</span>
      </div>

      <div className="manual-editor-grid top-gap">
        <section className="manual-editor-preview">
          <div className="manual-editor-preview-head">
            <strong>{job?.source_name ?? session.source_name}</strong>
            <span className="muted">输出预览 {formatSeconds(currentOutputTime)} / {formatSeconds(totalOutputDuration)}</span>
          </div>
          {previewDisabled ? (
            <div className="notice">当前机器拿不到原片本地路径，暂时不能内嵌预览，但仍可调整并保存时间线。</div>
          ) : (
            <video
              ref={videoRef}
              className="manual-editor-video"
              src={session.source_url ?? undefined}
              controls
              preload="metadata"
              playsInline
              onTimeUpdate={syncPreviewTime}
              onSeeked={syncPreviewTime}
              onPause={() => {
                if (videoRef.current?.paused) timelinePlaybackRef.current = false;
              }}
            />
          )}

          <div className="manual-editor-controls">
            <button type="button" className="button primary" disabled={previewDisabled || !effectiveSegments.length} onClick={() => void playEditedTimeline()}>
              播放输出时间轴
            </button>
            <button type="button" className="button ghost" disabled={previewDisabled} onClick={pauseEditedTimeline}>
              暂停
            </button>
            <button type="button" className="button ghost" disabled={!selectedSegment} onClick={() => selectedSegment && jumpToOutputTime(sourceTimeToOutputTime(selectedSegment.start, projection.ranges))}>
              跳到当前片段
            </button>
          </div>

          <div className="manual-editor-subtitle-stage">
            <div className="muted">当前字幕</div>
            <div className="manual-editor-subtitle-current">
              {activeSubtitle ? subtitleText(activeSubtitle) : "当前时间点没有字幕"}
            </div>
            <div className="manual-editor-subtitle-list">
              {visibleSubtitles.map((subtitle) => (
                <button
                  key={`${subtitle.index}-${subtitle.start_time}`}
                  type="button"
                  className={classNames("manual-editor-subtitle-chip", activeSubtitle?.index === subtitle.index && "active")}
                  onClick={() => jumpToOutputTime(subtitle.start_time)}
                >
                  <span>{formatSeconds(subtitle.start_time)} - {formatSeconds(subtitle.end_time)}</span>
                  <strong>{subtitleText(subtitle)}</strong>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="manual-editor-timeline">
          <div className="manual-editor-preview-head">
            <strong>波形时间轴</strong>
            <span className="muted">绿色区域是保留片段，拖动边界后字幕按同一映射实时前移</span>
          </div>

          <div className="manual-editor-wave-shell">
            {previewDisabled ? (
              <div className="notice">缺少可预览原片，波形编辑暂不可用。</div>
            ) : null}
            {!previewDisabled && !waveformReady && !waveformError ? (
              <div className="manual-editor-wave-loading">正在解析音频波形...</div>
            ) : null}
            {waveformError ? <div className="notice">{waveformError}</div> : null}
            <div ref={waveformRef} className={classNames("manual-editor-waveform", previewDisabled && "disabled")} />
            <div ref={waveformTimelineRef} className="manual-editor-wave-timeline" />
          </div>

          <div className="manual-editor-wave-tools">
            <label className="manual-editor-zoom-control">
              <span>时间轴缩放</span>
              <input
                className="slider"
                type="range"
                min={8}
                max={80}
                step={2}
                value={waveformZoom}
                onChange={(event) => setWaveformZoom(Number(event.target.value || INITIAL_WAVEFORM_ZOOM))}
              />
              <strong>{waveformZoom}px/s</strong>
            </label>
          </div>

          {previewAssets ? (
            <div className="manual-editor-preview-assets">
              <div className="manual-editor-preview-asset-status">
                <span>{previewAssetStatusLabel(previewAssets)}</span>
                <span>{previewAssetStageLabel(previewAssets.stage)}</span>
                <span>{previewAssetProgressPercent != null ? `${previewAssetProgressPercent}%` : previewAssets.ready ? "100%" : "0%"}</span>
                <span>{previewAssets.ready ? `${previewAssets.peak_count} peaks` : "使用原片预览"}</span>
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
              {thumbnailItems.length ? (
                <div className="manual-editor-thumbnail-strip" style={thumbnailStripStyle} aria-label="预览缩略图时间轴">
                  {thumbnailItems.map((item, index) => (
                    <button
                      key={`${item.url}-${index}`}
                      type="button"
                      className={classNames(
                        "manual-editor-thumbnail-button",
                        Math.abs(currentSourceTime - item.time_sec) <= Math.max(0.4, waveformZoom / 30) && "active",
                      )}
                      onClick={() => jumpToSourceTime(item.time_sec)}
                      title={`跳到 ${formatSeconds(item.time_sec)}`}
                    >
                      <img src={item.url} alt="" loading="lazy" />
                      <span>{formatSeconds(item.time_sec)}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="manual-editor-track compact-top" aria-label="输出片段概览">
            {effectiveSegments.map((segment, index) => {
              const width = totalOutputDuration > 0 ? ((segment.end - segment.start) / totalOutputDuration) * 100 : 0;
              return (
                <button
                  key={`${segment.start}-${segment.end}-${index}`}
                  type="button"
                  className={classNames("manual-editor-segment", index === selectedSegmentIndex && "active")}
                  style={{ width: `${Math.max(width, 4)}%` }}
                  onClick={() => jumpToSegment(index)}
                  title={`${formatSeconds(segment.start)} - ${formatSeconds(segment.end)}`}
                >
                  <span>{index + 1}</span>
                </button>
              );
            })}
          </div>

          {selectedSegment ? (
            <div className="manual-editor-inspector">
              <div className="toolbar">
                <strong>片段 {selectedSegmentIndex + 1}</strong>
                <span className="status-pill pending">{formatSeconds(selectedSegment.end - selectedSegment.start)}</span>
              </div>

              <label className="form-field">
                <span className="field-label">开始时间</span>
                <div className="manual-editor-input-row">
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={session.source_duration_sec}
                    step={0.01}
                    value={selectedSegment.start}
                    onChange={(event) => updateSelectedSegment("start", Number(event.target.value || 0))}
                  />
                  <input
                    className="slider"
                    type="range"
                    min={0}
                    max={session.source_duration_sec}
                    step={0.01}
                    value={selectedSegment.start}
                    onChange={(event) => updateSelectedSegment("start", Number(event.target.value || 0))}
                  />
                </div>
              </label>

              <label className="form-field">
                <span className="field-label">结束时间</span>
                <div className="manual-editor-input-row">
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={session.source_duration_sec}
                    step={0.01}
                    value={selectedSegment.end}
                    onChange={(event) => updateSelectedSegment("end", Number(event.target.value || 0))}
                  />
                  <input
                    className="slider"
                    type="range"
                    min={0}
                    max={session.source_duration_sec}
                    step={0.01}
                    value={selectedSegment.end}
                    onChange={(event) => updateSelectedSegment("end", Number(event.target.value || 0))}
                  />
                </div>
              </label>

              <div className="manual-editor-actions">
                <button type="button" className="button danger" disabled={!session.editable || effectiveSegments.length <= 1} onClick={removeSelectedSegment}>
                  删除当前片段
                </button>
                <button type="button" className="button ghost" onClick={restoreInitialSegments}>
                  恢复当前版本
                </button>
              </div>
            </div>
          ) : (
            <div className="notice">当前没有可编辑片段。</div>
          )}

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

          <div className="manual-editor-actions top-gap">
            <button type="button" className="button primary" disabled={!session.editable || saving || !onApply || !hasMaterialEdits} onClick={handleApply}>
              {saving ? "保存并重渲染中..." : "保存修改并重新渲染"}
            </button>
            <button type="button" className="button ghost" onClick={restoreInitialSegments}>
              放弃本地改动
            </button>
          </div>
        </section>
      </div>

      <section className="manual-editor-subtitle-editor">
        <div className="manual-editor-preview-head">
          <div>
            <strong>字幕时间表</strong>
            <div className="muted compact-top">按输出时间轴编辑字幕文本和起止时间，保存后进入重渲染字幕层。</div>
          </div>
          <div className="manual-editor-actions">
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

        <div className="manual-editor-subtitle-table">
          <div className="manual-editor-subtitle-row header">
            <span>#</span>
            <span>开始</span>
            <span>结束</span>
            <span>状态</span>
            <span>字幕</span>
            <span>操作</span>
          </div>
          {projection.remapped.map((subtitle) => {
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

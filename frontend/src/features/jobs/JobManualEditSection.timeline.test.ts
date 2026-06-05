import { describe, expect, it } from "vitest";

import {
  DEFAULT_SMART_CUT_CATCHPHRASES,
  DEFAULT_SMART_CUT_FILLERS,
  applySmartCutRuleRangesToSegments,
  autoSmartCutRuleRanges,
  blockAutoSmartCutRangesForSmartDeleteReview,
  buildManualEditChangeList,
  buildManualTimelineSemanticMarkers,
  resolveManualTimelineSemanticFocus,
  buildSourceTranscriptProjectedBaseline,
  buildSmartCutRuleAnalysis,
  buildSmartDeleteSuggestions,
  buildTranscriptTokens,
  buildVisibleSubtitleRows,
  buildSourceTranscriptSubtitlesForTimeline,
  buildOutputWaveformBars,
  findSubtitleIndexNearOutputTime,
  buildSmartCutRulePreviews,
  intersectInferredPausesWithAudioSilence,
  manualEditorAuthoritativeSmartCutKinds,
  normalizeAdjacentSubtitleTextOverlaps,
  normalizeReviewPauseRanges,
  normalizeStoredSmartCutFillers,
  outputTimeToSourceTimeForSegments,
  outputTimeToSourceTime,
  projectedTranscriptMissesKeptSpeech,
  parseSmartCutCatchphrases,
  parseSmartCutFillers,
  projectedSubtitlesHaveDuplicateSourceOverlap,
  removeTranscriptSelectionTextFromSubtitleDrafts,
  remapSubtitles,
  remapProjectedSubtitlesFromBaseTimeline,
  resolveEditedPlaybackSyncDecision,
  sourceTimeToEditedPlaybackStartTime,
  sourceTimeToActiveOutputTime,
  sourceTimeToOutputTime,
  sourceRangeOverlapsCutRanges,
  smartDeleteSuggestionRanges,
  smartCutRuleManagedRanges,
  transcriptTokenSmartCutVisualState,
  subtitleAutoCorrectionSummary,
  transcriptCutRangesForSelection,
  wordTimingPauseIntervals,
} from "./JobManualEditSection";

const ranges = [
  {
    sourceStart: 1.56,
    sourceEnd: 41.07,
    outputStart: 0,
    outputEnd: 39.51,
  },
  {
    sourceStart: 42.21,
    sourceEnd: 86.73,
    outputStart: 39.51,
    outputEnd: 84.03,
  },
];

describe("manual editor timeline mapping", () => {
  it("summarizes automatic subtitle text corrections", () => {
    expect(subtitleAutoCorrectionSummary({
      index: 0,
      start_time: 0,
      end_time: 1,
      text_raw: "最近这三次NFC的发烧太难了",
      text_norm: "最近这三次NOC的发烧太难了",
    })).toEqual({
      label: "规则清理",
      source: "最近这三次NFC的发烧太难了",
      current: "最近这三次NOC的发烧太难了",
    });

    expect(subtitleAutoCorrectionSummary({
      index: 1,
      start_time: 1,
      end_time: 2,
      text_raw: "这个也算是我这次的欧气",
      text_norm: "这个也算是我这次的欧气",
      text_final: "这个也算是我这次的运气",
    })?.label).toBe("LLM精修");

    expect(subtitleAutoCorrectionSummary({
      index: 2,
      start_time: 2,
      end_time: 3,
      text_raw: "没有变化",
      text_norm: "没有变化",
      text_final: "没有变化",
    })).toBeNull();
  });

  it("summarizes pending manual editor changes for the top change list", () => {
    const changes = buildManualEditChangeList({
      baseSegments: [
        { start: 0, end: 10 },
        { start: 20, end: 30 },
      ],
      effectiveSegments: [
        { start: 0, end: 9 },
        { start: 20, end: 30 },
      ],
      outputDurationDeltaSec: -1,
      subtitleOverrides: [
        { index: 1, start_time: 1.2, text_final: "新字幕" },
        { index: 2, delete: true },
      ],
      baseSubtitles: [
        { index: 1, start_time: 1, end_time: 2, text_final: "旧字幕" },
        { index: 2, start_time: 3, end_time: 4, text_final: "删除字幕" },
      ],
      subtitleReplacements: [{ original: "旧", replacement: "新", occurrence_count: 3 }],
      baseVideoTransform: { rotation_cw: 0, aspect_ratio: "source", resolution_mode: "source", resolution_preset: "1080p" },
      currentVideoTransform: { rotation_cw: 90, aspect_ratio: "9:16", resolution_mode: "specified", resolution_preset: "2160p" },
      hasVideoSummaryEdits: true,
    });

    expect(changes.map((item) => item.title)).toEqual([
      "剪辑时间线",
      "画面旋转",
      "画面比例",
      "输出分辨率",
      "字幕修改",
      "术语替换",
      "视频摘要",
    ]);
    expect(changes[0].detail).toContain("输出时长变化 -0:01.00");
    expect(changes[4].detail).toBe("2 条（文本 1 / 时间 1 / 删除 1）");
  });

  it("restores source ASR words over stale transcript drafts after refresh", () => {
    const rows = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 3,
            text_final: "小玩具也是耗尽了我这次的欧气啊",
            transcript_text: "小玩具啊嗯这个也是耗尽了我这次的欧气啊我靠我",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {
        0: { text_final: "小玩具也是耗尽了我这次的欧气啊" },
      },
    );

    expect(rows.map((row) => row.text_final).join("")).toBe("小玩具啊嗯这个也是耗尽了我这次的欧气啊我靠我");
  });

  it("keeps canonical text when raw ASR is a shorter scrambled fragment", () => {
    const rows = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 17,
            end_time: 20.8,
            text_final: "太难了，难上加难",
            transcript_text: "太了难",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(rows.map((row) => row.text_final).join("")).toBe("太难了，难上加难");
  });

  it("keeps split source-subtitle fragments addressable with unique row indexes", () => {
    const projection = remapSubtitles(
      [{ index: 20, start_time: 1, end_time: 5, text_final: "那身份卡啊所以还很期待" }],
      [
        { start: 1, end: 2 },
        { start: 4, end: 5 },
      ],
    );

    expect(projection.remapped).toHaveLength(2);
    expect(new Set(projection.remapped.map((subtitle) => subtitle.index)).size).toBe(2);
    expect(projection.remapped.map((subtitle) => subtitle.source_index)).toEqual([20, 20]);
    expect(projection.remapped.map((subtitle) => subtitle.source_indexes)).toEqual([[20], [20]]);
    expect(projection.remapped.map((subtitle) => subtitle.source_fragment_index)).toEqual([0, 1]);
  });

  it("builds semantic timeline markers from timed focus spans for the source timeline", () => {
    const markers = buildManualTimelineSemanticMarkers(
      {
        job_id: "job-1",
        status: "done",
        review_step_status: "done",
        workflow_mode: "standard",
        enhancement_modes: [],
        ocr_evidence: {},
        transcript_evidence: {},
        entity_resolution_trace: {},
        draft: null,
        final: {
          content_understanding: {
            timed_focus_spans: [
              {
                type: "hook",
                timestamp: "00:00-00:02",
                start_time: 0,
                end_time: 2,
                text: "先抛出结论",
              },
            ],
            evidence_spans: [
              {
                type: "comparison",
                timestamp: "00:02-00:05",
                start_time: 2,
                end_time: 5,
                text: "亮度对比",
              },
            ],
          },
          video_understanding: {
            global_understanding: {
              video_type: "tutorial",
            },
          },
        },
        memory: null,
      },
      10,
    );

    expect(markers).toHaveLength(2);
    expect(markers[0]).toMatchObject({
      label: "开场 Hook",
      timestamp: "00:00-00:02",
      start: 0,
      end: 2,
    });
    expect(markers[1]).toMatchObject({
      label: "对比段",
      timestamp: "00:02-00:05",
      start: 2,
      end: 5,
    });
    expect(markers[1].leftPercent).toBe(20);
  });

  it("resolves the active semantic focus around the current source time", () => {
    const markers = [
      {
        key: "hook",
        label: "开场 Hook",
        text: "先抛结论",
        timestamp: "00:00-00:02",
        leftPercent: 0,
        widthPercent: 20,
        start: 0,
        end: 2,
        detail: [],
      },
      {
        key: "comparison",
        label: "对比段",
        text: "亮度对比",
        timestamp: "00:02-00:05",
        leftPercent: 20,
        widthPercent: 30,
        start: 2,
        end: 5,
        detail: [],
      },
    ];

    expect(resolveManualTimelineSemanticFocus(markers, 2.4)).toMatchObject({
      primary: expect.objectContaining({ key: "comparison" }),
    });
    expect(resolveManualTimelineSemanticFocus(markers, 2.4).active).toHaveLength(1);
    expect(resolveManualTimelineSemanticFocus(markers, null)).toEqual({
      primary: null,
      active: [],
    });
  });

  it("starts edited preview from the next kept range when the playhead is inside a cut", () => {
    expect(sourceTimeToEditedPlaybackStartTime(41.5, ranges)).toBe(42.21);
    expect(sourceTimeToEditedPlaybackStartTime(10, ranges)).toBe(10);
    expect(sourceTimeToEditedPlaybackStartTime(90, ranges)).toBeNull();
  });

  it("keeps output preview moving across cut gaps and range boundaries", () => {
    const introRanges = [
      { sourceStart: 0.96, sourceEnd: 1.32, outputStart: 0, outputEnd: 0.36 },
      { sourceStart: 1.62, sourceEnd: 4.06, outputStart: 0.36, outputEnd: 2.8 },
      { sourceStart: 5.91, sourceEnd: 8.37, outputStart: 2.8, outputEnd: 5.26 },
    ];

    expect(resolveEditedPlaybackSyncDecision(2.4, introRanges)).toEqual({ action: "none" });
    expect(resolveEditedPlaybackSyncDecision(4.061, introRanges)).toEqual({ action: "seek", sourceTime: 5.91 });
    expect(resolveEditedPlaybackSyncDecision(4.8, introRanges)).toEqual({ action: "seek", sourceTime: 5.91 });
    expect(resolveEditedPlaybackSyncDecision(8.38, introRanges)).toEqual({ action: "stop" });
  });

  it("shows an empty manual editor change list item when the draft is unchanged", () => {
    const changes = buildManualEditChangeList({
      baseSegments: [{ start: 0, end: 10 }],
      effectiveSegments: [{ start: 0, end: 10 }],
      outputDurationDeltaSec: 0,
      subtitleOverrides: [],
      baseSubtitles: [],
      subtitleReplacements: [],
      baseVideoTransform: { rotation_cw: 0, aspect_ratio: "source", resolution_mode: "source", resolution_preset: "1080p" },
      currentVideoTransform: { rotation_cw: 0, aspect_ratio: "source", resolution_mode: "source", resolution_preset: "1080p" },
      hasVideoSummaryEdits: false,
    });

    expect(changes).toEqual([
      expect.objectContaining({
        title: "暂无改动",
        tone: "empty",
      }),
    ]);
  });

  it("maps the reported output preview time back to the kept source time", () => {
    expect(outputTimeToSourceTime(11.46, ranges)).toBeCloseTo(13.02, 3);
    expect(sourceTimeToOutputTime(13.02, ranges)).toBeCloseTo(11.46, 3);
    expect(sourceTimeToActiveOutputTime(13.02, ranges)).toBeCloseTo(11.46, 3);
  });

  it("does not activate subtitles while the source player is outside a kept range", () => {
    expect(sourceTimeToOutputTime(0, ranges)).toBe(0);
    expect(sourceTimeToActiveOutputTime(0, ranges)).toBeNull();
    expect(sourceTimeToOutputTime(41.5, ranges)).toBeCloseTo(39.51, 3);
    expect(sourceTimeToActiveOutputTime(41.5, ranges)).toBeNull();
  });

  it("reanchors the preview to the same output timestamp after smart cut rules change segments", () => {
    const nextSegments = [
      { start: 1.56, end: 41.07 },
      { start: 50, end: 86.73 },
    ];

    expect(outputTimeToSourceTimeForSegments(40, nextSegments)).toBeCloseTo(50.49, 3);
    expect(sourceTimeToActiveOutputTime(41.5, [
      { sourceStart: 1.56, sourceEnd: 41.07, outputStart: 0, outputEnd: 39.51 },
      { sourceStart: 50, sourceEnd: 86.73, outputStart: 39.51, outputEnd: 76.24 },
    ])).toBeNull();
  });

  it("anchors subtitle lists near the playhead when no subtitle is active", () => {
    const subtitles = [
      { start_time: 0.04, end_time: 3.08 },
      { start_time: 3.1, end_time: 7.8 },
      { start_time: 8.44, end_time: 14.76 },
      { start_time: 95.2, end_time: 98.4 },
    ];

    expect(findSubtitleIndexNearOutputTime(subtitles, 6)).toBe(1);
    expect(findSubtitleIndexNearOutputTime(subtitles, 40)).toBe(3);
    expect(findSubtitleIndexNearOutputTime(subtitles, 120)).toBe(3);
  });

  it("prefers the later subtitle when adjacent projected rows overlap slightly", () => {
    const subtitles = [
      { start_time: 439.0, end_time: 441.52 },
      { start_time: 441.44, end_time: 443.52 },
    ];

    expect(findSubtitleIndexNearOutputTime(subtitles, 441.48)).toBe(1);
  });

  it("anchors to the next subtitle across a gap instead of sticking to the previous end", () => {
    const subtitles = [
      { start_time: 409.68, end_time: 411.36 },
      { start_time: 413.84, end_time: 415.52 },
    ];

    expect(findSubtitleIndexNearOutputTime(subtitles, 412.2)).toBe(1);
  });

  it("keeps projected subtitle text intact when a local deletion changes keep segments", () => {
    const projection = remapProjectedSubtitlesFromBaseTimeline(
      [
        { index: 0, start_time: 0, end_time: 2, text_final: "前一句完整字幕" },
        { index: 1, start_time: 2, end_time: 5, text_final: "这个产品真的不错" },
        { index: 2, start_time: 5, end_time: 6, text_final: "后一句" },
      ],
      [{ start: 10, end: 16 }],
      [
        { start: 10, end: 12 },
        { start: 15, end: 16 },
      ],
    );

    expect(projection.remapped.map((subtitle) => subtitle.text_final)).toEqual(["前一句完整字幕", "后一句"]);
    expect(projection.remapped[1].start_time).toBeCloseTo(2, 3);
    expect(projection.remapped[1].end_time).toBeCloseTo(3, 3);
  });

  it("rejects projected subtitles that drop kept source words like this-also", () => {
    const source = [
      { index: 0, start_time: 0, end_time: 5, text_final: "最后的一款小玩具啊这个也是耗尽了我这次的欧气啊" },
    ];
    const projected = [
      { index: 0, start_time: 0, end_time: 5, text_final: "最后的一款小玩具啊也是耗尽了我这次的欧气啊" },
    ];

    expect(projectedTranscriptMissesKeptSpeech(projected, source, [{ start: 0, end: 5 }])).toBe(true);
  });

  it("trims projected subtitle text when a leading filler is cut from the source timeline", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: true,
      fillerSentenceTailEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "呃",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 10,
          end_time: 15,
          text_raw: "呃没想到啊",
          text_final: "呃没想到啊",
          words: [
            { word: "呃", start: 10, end: 11 },
            { word: "没想到啊", start: 11, end: 15 },
          ],
        },
      ],
      rules,
      [],
    );
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 10, end: 15 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      15,
    );
    const projection = remapProjectedSubtitlesFromBaseTimeline(
      [{ index: 0, source_index: 0, start_time: 0, end_time: 5, text_final: "呃没想到啊" }],
      [{ start: 10, end: 15 }],
      nextSegments,
    );

    expect(analysis.filler).toEqual([{ start: 10, end: 11, kind: "filler", fillerMode: "sentence_head", sourceText: "呃" }]);
    expect(nextSegments).toEqual([{ start: 11, end: 15 }]);
    expect(projection.remapped.map((subtitle) => subtitle.text_final)).toEqual(["没想到啊"]);
    expect(projection.remapped[0].start_time).toBeCloseTo(0, 3);
    expect(projection.remapped[0].end_time).toBeCloseTo(4, 3);
  });

  it("does not auto-gray rule cuts inside an unconfirmed smart delete review range", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 10, end_time: 11, text_final: "前一句" },
        { index: 1, start_time: 13, end_time: 14, text_final: "后一句" },
      ],
      rules,
      [{ start: 11, end: 13, duration_sec: 2, source: "word_timing" }],
      [{ start: 10, end: 14, duration_sec: 4, kind: "smart_delete", reason: "timing_trim", source: "manual_editor_rule_candidate" }],
    );
    const autoRanges = autoSmartCutRuleRanges(analysis, rules);
    const blockedAutoRanges = blockAutoSmartCutRangesForSmartDeleteReview(
      autoRanges,
      analysis.smartDelete,
      rules,
      [],
    );
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 10, end: 14 }],
      blockedAutoRanges,
      smartCutRuleManagedRanges(analysis),
      14,
    );

    expect(autoRanges).toEqual([{ start: 11, end: 13, kind: "pause" }]);
    expect(blockedAutoRanges).toEqual([]);
    expect(smartDeleteSuggestionRanges(analysis, rules)).toHaveLength(1);
    expect(nextSegments).toEqual([{ start: 10, end: 14 }]);
  });

  it("allows confirmed smart delete review ranges to enter the actual cut timeline", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 10, end_time: 11, text_final: "前一句" },
        { index: 1, start_time: 13, end_time: 14, text_final: "后一句" },
      ],
      rules,
      [{ start: 11, end: 13, duration_sec: 2, source: "word_timing" }],
      [{ start: 10, end: 14, duration_sec: 4, kind: "smart_delete", reason: "timing_trim", source: "manual_editor_rule_candidate" }],
    );
    const confirmed = [{ start: 10, end: 14 }];
    const blockedAutoRanges = blockAutoSmartCutRangesForSmartDeleteReview(
      autoSmartCutRuleRanges(analysis, rules),
      analysis.smartDelete,
      rules,
      confirmed,
    );
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 10, end: 14 }],
      [
        ...blockedAutoRanges,
        ...confirmed.map((range) => ({ ...range, kind: "smart_delete" as const })),
      ],
      smartCutRuleManagedRanges(analysis),
      14,
    );

    expect(blockedAutoRanges).toEqual([{ start: 11, end: 13, kind: "pause" }]);
    expect(nextSegments).toEqual([{ start: 10, end: 10.08 }, { start: 13.92, end: 14 }]);
  });

  it("does not split Chinese words when projected subtitle fragments cross a cut boundary", () => {
    const projection = remapProjectedSubtitlesFromBaseTimeline(
      [
        {
          index: 0,
          source_index: 0,
          start_time: 0,
          end_time: 4,
          text_final: "好，今天我们直奔主题",
          words: [
            { word: "好", start: 0, end: 0.3 },
            { word: "今天", start: 0.8, end: 1.5 },
            { word: "我们直奔主题", start: 1.5, end: 4 },
          ],
        },
      ],
      [{ start: 10, end: 14 }],
      [
        { start: 10, end: 11.1 },
        { start: 11.3, end: 14 },
      ],
    );

    expect(projection.remapped.map((subtitle) => subtitle.text_final)).toEqual([
      "好，",
      "今天我们直奔主题",
    ]);
    expect(projection.remapped.map((subtitle) => subtitle.text_final)).not.toEqual([
      "好，今",
      "天我们直奔主题",
    ]);
  });

  it("marks transcript tokens as cut when they overlap the current source cut ranges", () => {
    const tokens = buildTranscriptTokens(
      [{ index: 0, start_time: 10, end_time: 15, text_raw: "呃没想到啊", text_final: "呃没想到啊" }],
      [{ start: 11, end: 15 }],
      [],
    );
    const cutRanges = [{ start: 10, end: 11 }];

    expect(tokens[0].text).toBe("呃");
    expect(tokens[0].kept).toBe(false);
    expect(sourceRangeOverlapsCutRanges(tokens[0].start, tokens[0].end, cutRanges)).toBe(true);
    expect(sourceRangeOverlapsCutRanges(tokens[1].start, tokens[1].end, cutRanges)).toBe(false);
  });

  it("does not collapse ASR text into a pause chip when silence metadata overlaps speech", () => {
    const tokens = buildTranscriptTokens(
      [{ index: 0, start_time: 10, end_time: 15, text_final: "这一段其实还有完整语音内容" }],
      [{ start: 0, end: 20 }],
      [{ start: 10, end: 15, duration_sec: 5, source: "audio_vad" }],
    );

    expect(tokens.some((token) => token.kind === "pause")).toBe(false);
    expect(tokens.filter((token) => token.kind === "char").map((token) => token.text).join("")).toBe("这一段其实还有完整语音内容");
  });

  it("does not auto-cut audio VAD pauses inside subtitle text without trusted word timings", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [{ index: 0, start_time: 0, end_time: 4, text_final: "收到了第三次" }],
      rules,
      [{ start: 0.8, end: 1.8, duration_sec: 1.0, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([]);
  });

  it("keeps inferred transcript punctuation selectable as a source boundary range", () => {
    const subtitles = [
      { index: 0, start_time: 10, end_time: 11, text_final: "前一句内容" },
      { index: 1, start_time: 11.8, end_time: 13, text_final: "后一句内容" },
    ];
    const tokens = buildTranscriptTokens(subtitles, [{ start: 10, end: 13 }], []);
    const punctuationIndex = tokens.findIndex((token) => token.kind === "punctuation");

    expect(punctuationIndex).toBeGreaterThan(-1);
    expect(["，", "。"]).toContain(tokens[punctuationIndex].text);
    expect(tokens[punctuationIndex].inferredPunctuation).toBe(tokens[punctuationIndex].text);
    expect(transcriptCutRangesForSelection(
      subtitles,
      tokens,
      { startTokenIndex: punctuationIndex, endTokenIndex: punctuationIndex },
      20,
    )).toEqual([{ start: 11, end: 11.8 }]);
  });

  it("samples waveform peaks on the output timeline across source gaps", () => {
    const bars = buildOutputWaveformBars([0.1, 0.2, 0.9, 0.3, 0.8, 0.4], ranges, 84.03, 90, 6);

    expect(bars).toHaveLength(6);
    expect(Math.max(...bars)).toBeGreaterThan(0.3);
    expect(bars.every((bar) => bar >= 0.08 && bar <= 1)).toBe(true);
  });

  it("keeps the later subtitle when overlapping timestamps carry fuzzy duplicate speech", () => {
    const normalized = normalizeAdjacentSubtitleTextOverlaps([
      { index: 0, start_time: 76.8, end_time: 77.45, text_final: "这个一直来说" },
      { index: 1, start_time: 77.31, end_time: 78.1, text_final: "值来说它还是不错" },
    ]);

    expect(normalized[0].text_final).toBe("这个");
    expect(normalized[0].end_time).toBeLessThan(77.45);
    expect(normalized[1].text_final).toBe("值来说它还是不错");
  });

  it("trims single-character duplicate projection boundaries at zero gap", () => {
    const normalized = normalizeAdjacentSubtitleTextOverlaps([
      { index: 0, start_time: 10, end_time: 12, text_final: "这个一把是EDC37是" },
      { index: 1, start_time: 12, end_time: 15, text_final: "是之前我一直经常会EDC用的" },
      { index: 2, start_time: 15, end_time: 16, text_final: "一根线一个手绳没啥好说电池" },
      { index: 3, start_time: 16, end_time: 17, text_final: "池然后一根线" },
    ]);

    expect(normalized.map((item) => item.text_final)).toEqual([
      "这个一把是EDC37",
      "是之前我一直经常会EDC用的",
      "一根线一个手绳没啥好说电",
      "池然后一根线",
    ]);
  });

  it("does not fuzzy-trim similar sentence boundaries when timestamps do not overlap", () => {
    const normalized = normalizeAdjacentSubtitleTextOverlaps([
      { index: 0, start_time: 10, end_time: 11, text_final: "整体来说" },
      { index: 1, start_time: 11.3, end_time: 12, text_final: "来说这个做工不错" },
    ]);

    expect(normalized[0].text_final).toBe("整体来说");
    expect(normalized[1].text_final).toBe("来说这个做工不错");
  });

  it("rejects projected transcript gaps that hide kept source speech", () => {
    const projected = [
      { index: 0, start_time: 95.92, end_time: 100.6, text_final: "但是这个确实是" },
      { index: 1, start_time: 113.82, end_time: 118.6, text_final: "我们总归是需要有" },
    ];
    const source = [
      { index: 26, start_time: 99.26, end_time: 101.18, text_final: "但是这个确实是" },
      { index: 27, start_time: 101.18, end_time: 104.993, text_final: "拿习惯了还是蛮小巧的" },
      { index: 28, start_time: 104.993, end_time: 109.1, text_final: "它作为一个揣兜里的这个EDC的手电来说" },
      { index: 29, start_time: 109.1, end_time: 114.22, text_final: "稍微有点重" },
    ];

    expect(projectedTranscriptMissesKeptSpeech(projected, source, [{ start: 1.32, end: 121.5 }])).toBe(true);
    expect(projectedTranscriptMissesKeptSpeech(projected, source, [{ start: 1.32, end: 100.6 }, { start: 113.82, end: 121.5 }])).toBe(false);
  });

  it("rejects projected transcript text that drops real source words inside a kept range", () => {
    const projected = [
      { index: 0, start_time: 0, end_time: 3, text_final: "最后的一款小玩具啊也是耗尽了我这次的欧气啊" },
    ];
    const source = [
      { index: 0, start_time: 0, end_time: 3, text_final: "最后的一款小玩具啊这个也是耗尽了我这次的欧气啊" },
    ];

    expect(projectedTranscriptMissesKeptSpeech(projected, source, [{ start: 0, end: 3 }])).toBe(true);
  });

  it("rejects projected transcript text that is noisier than the source row", () => {
    const projected = [
      { index: 0, start_time: 0, end_time: 2, text_final: "这个一把是EDC37是是之前我一直用的" },
      { index: 1, start_time: 2, end_time: 4, text_final: "那支电池池然后一根线" },
    ];
    const source = [
      { index: 0, start_time: 0, end_time: 2, text_final: "这个一把是EDC37是之前我一直用的" },
      { index: 1, start_time: 2, end_time: 4, text_final: "那支电池然后一根线" },
    ];

    expect(projectedTranscriptMissesKeptSpeech(projected, source, [{ start: 0, end: 4 }])).toBe(true);
  });

  it("keeps full-text transcript timing and source text on the source timeline", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 26, start_time: 99.26, end_time: 101.18, text_final: "源字幕" },
        ],
        projected_subtitles: [],
      },
      [
        { index: 26, start_time: 97.94, end_time: 99.86, text_final: "投影字幕" },
      ],
      {},
    );

    expect(transcript).toEqual([
      { index: 26, start_time: 99.26, end_time: 101.18, text_final: "源字幕" },
    ]);
  });

  it("uses source_index only for timing lookup and does not replace source transcript text", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 52, start_time: 188.807, end_time: 192.22, text_final: "源字幕" },
        ],
        projected_subtitles: [],
      },
      [
        { index: 65, source_index: 52, start_time: 180.117, end_time: 183.51, text_final: "投影字幕" },
      ],
      {},
    );

    expect(transcript).toEqual([
      { index: 52, start_time: 188.807, end_time: 192.22, text_final: "源字幕" },
    ]);
  });

  it("keeps source transcript text when projected text belongs to a different phrase", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 41, start_time: 137.0, end_time: 138.4, text_raw: "那身份卡啊", text_final: "那身份卡啊" },
        ],
        projected_subtitles: [],
      },
      [
        { index: 72, source_index: 41, start_time: 102.2, end_time: 104.0, text_final: "那个NOC要出保卡了不对" },
      ],
      {},
    );

    expect(transcript[0].text_final).toBe("那身份卡啊");
  });

  it("does not let incomplete projected subtitles hide raw ASR in full-text editing", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 41, start_time: 137.0, end_time: 138.4, text_raw: "那身份卡啊，所以还很期待", text_final: "那身份卡啊，所以还很期待" },
        ],
        projected_subtitles: [
          { index: 70, source_index: 41, start_time: 100, end_time: 101, text_final: "那身份牌" },
        ],
      },
      [
        { index: 70, source_index: 41, start_time: 100, end_time: 101, text_final: "那身份牌" },
      ],
      {},
    );

    expect(transcript[0].text_final).toBe("那身份卡啊，所以还很期待");
  });

  it("detects duplicate projected subtitle alternatives on the same source span", () => {
    expect(projectedSubtitlesHaveDuplicateSourceOverlap([
      { index: 70, source_index: 41, source_indexes: [41], start_time: 100, end_time: 101.2, text_final: "那身份牌啊" },
      { index: 71, source_index: 41, source_indexes: [41], start_time: 100.02, end_time: 101.18, text_final: "那身份卡啊" },
    ])).toBe(true);
  });

  it("keeps the full source text when a deleted prefix is missing from projected subtitles", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 12, start_time: 10, end_time: 12, text_raw: "挺明显的还是", text_final: "挺明显的还是" },
        ],
        projected_subtitles: [],
      },
      [
        { index: 88, source_index: 12, start_time: 9.4, end_time: 9.9, text_final: "的还是" },
      ],
      {},
    );

    expect(transcript[0].text_final).toBe("挺明显的还是");
  });

  it("does not let ASR word timing text override canonical subtitle body", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 9,
            start_time: 7.4,
            end_time: 9.3,
            text_raw: "小玩具也是耗尽了",
            text_final: "小玩具也是耗尽了",
            words: [
              { word: "小玩具", start: 7.4, end: 7.82 },
              { word: "然后呢", start: 7.82, end: 8.18 },
              { word: "也是", start: 8.18, end: 8.48 },
              { word: "耗尽了", start: 8.48, end: 9.3 },
            ],
          },
        ],
        projected_subtitles: [],
      },
      [
        { index: 9, start_time: 7.4, end_time: 9.3, text_final: "小玩具也是耗尽了" },
      ],
      {},
    );

    expect(transcript[0].text_final).toBe("小玩具也是耗尽了");
    expect(buildTranscriptTokens(transcript, [{ start: 0, end: 10 }]).map((token) => token.text).join("")).not.toContain("然后呢");
  });

  it("does not render ASR word timing text for empty source subtitle rows", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 66,
            start_time: 58.77,
            end_time: 59,
            text_raw: "",
            text_final: "",
            words: [
              { word: "你看啊啊好不过好在呢", start: 39.42, end: 42.18 },
              { word: "还算抢到了啊", start: 42.18, end: 44.94 },
            ],
            alignment_diagnostics: { status: "warning", issues: ["missing_display_text"], matched_ratio: 0 },
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("");
    expect(buildTranscriptTokens(transcript, [{ start: 0, end: 60 }]).map((token) => token.text).join("")).toBe("");
  });

  it("keeps raw filler-only source rows visible in the full transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 0, start_time: 0, end_time: 0.4, text_raw: "嗯", text_final: "" },
          { index: 1, start_time: 0.4, end_time: 1.4, text_raw: "我们开始", text_final: "我们开始" },
        ],
        projected_subtitles: [
          { index: 0, source_index: 1, start_time: 0, end_time: 1, text_final: "我们开始" },
        ],
      },
      [
        { index: 0, source_index: 1, start_time: 0, end_time: 1, text_final: "我们开始" },
      ],
      {},
    );

    expect(transcript.map((item) => item.text_final)).toEqual(["嗯", "我们开始"]);
  });

  it("keeps standalone fillers visible but hides suppressed noise rows in the full transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          { index: 0, start_time: 0, end_time: 0.4, text_raw: "嗯", text_final: "", display_suppressed_reason: "standalone_filler" },
          { index: 1, start_time: 0.4, end_time: 0.9, text_raw: "噪音", text_final: "", display_suppressed_reason: "asr_noise_marker" },
          { index: 2, start_time: 0.9, end_time: 1.6, text_raw: "我们开始", text_final: "我们开始" },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript.map((item) => item.text_final)).toEqual(["嗯", "", "我们开始"]);
    const rendered = buildTranscriptTokens(transcript, [{ start: 0, end: 2 }]).map((token) => token.text).join("");
    expect(rendered).toContain("嗯");
    expect(rendered).toContain("我们开始");
    expect(rendered).not.toContain("噪音");
  });

  it("keeps cleaned ASR text before noisy raw text in the full transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_raw: "NNOCOC的的这个个发发售售太太难难了了",
            text_final: "NOC的这个发售太难了",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("NOC的这个发售太难了");
  });

  it("applies conservative word-level ASR corrections without rewriting the transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_final: "612一把呢，就是现在这个",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("另外一把呢，就是现在这个");
  });

  it("reveals raw ASR fillers only when word timings support them", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_raw: "嗯我们开始啊",
            text_final: "我们开始",
            words: [
              { word: "嗯", start: 0, end: 0.16 },
              { word: "我们", start: 0.2, end: 0.54 },
              { word: "开始", start: 0.54, end: 0.82 },
              { word: "啊", start: 0.84, end: 0.98 },
            ],
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("嗯我们开始啊");
  });

  it("suppresses filler-only transcript extras when there is no timing support for them", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_final: "我们开始",
            transcript_text: "嗯我们开始啊",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("我们开始");
  });

  it("keeps denoised ASR transcript words before cleaned subtitle text in the full transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_final: "很多兄弟一样耗尽了我这次的欧气",
            transcript_text: "很多兄弟一样饮恨耗尽了我这次的欧气啊我靠",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("很多兄弟一样饮恨耗尽了我这次的欧气啊我靠");
  });

  it("keeps ASR filler words from transcript_text available for filler rules when timings support them", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_final: "我们开始",
            transcript_text: "嗯嗯我们开始吧呀",
            words: [
              { word: "嗯嗯", start: 0, end: 0.2 },
              { word: "我们", start: 0.24, end: 0.54 },
              { word: "开始", start: 0.54, end: 0.78 },
              { word: "吧呀", start: 0.8, end: 0.98 },
            ],
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("嗯嗯我们开始吧呀");
  });

  it("denoises mechanical ASR duplicate text before using transcript_text", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 1,
            text_final: "NOC的这个发售太难了",
            transcript_text: "NNOCOC的的这个个发发售售太太难难了了",
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript[0].text_final).toBe("NOC的这个发售太难了");
  });

  it("syncs full-text transcript rendering when a source row draft replaces old transcript_text", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 2,
            text_final: "这个3G啊",
            transcript_text: "这个3G啊",
            alignment_tokens: Array.from("这个3G啊").map((text, index) => ({
              text,
              start: index * 0.3,
              end: (index + 1) * 0.3,
            })),
          },
        ],
        projected_subtitles: [],
      },
      [],
      { 0: { text_final: "这个37啊" } },
    );
    const rendered = buildTranscriptTokens(transcript, [{ start: 0, end: 2 }])
      .filter((token) => token.kind === "char")
      .map((token) => token.text)
      .join("");

    expect(transcript[0].transcript_text).toBe("这个37啊");
    expect(rendered).toBe("这个37啊");
  });

  it("applies batch subtitle replacements to source full-text transcript rows", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 0,
            start_time: 0,
            end_time: 3,
            text_final: "这个3G和EC啊",
            transcript_text: "这个3G和EC啊",
            alignment_tokens: Array.from("这个3G和EC啊").map((text, index) => ({
              text,
              start: index * 0.25,
              end: (index + 1) * 0.25,
            })),
          },
        ],
        projected_subtitles: [
          { index: 10, source_index: 0, start_time: 0, end_time: 3, text_final: "这个37和EDC啊" },
        ],
      },
      [],
      {},
      [
        { original: "3G", replacement: "37", occurrence_count: 1 },
        { original: "EC", replacement: "EDC", occurrence_count: 1 },
      ],
    );
    const rendered = buildTranscriptTokens(transcript, [{ start: 0, end: 3 }])
      .filter((token) => token.kind === "char")
      .map((token) => token.text)
      .join("");

    expect(transcript[0].text_final).toBe("这个37和EDC啊");
    expect(rendered).toBe("这个37和EDC啊");
  });

  it("keeps full-text transcript on raw source even when a projected baseline exists", () => {
    const session = {
      source_subtitles: [
        { index: 10, start_time: 10, end_time: 12, text_raw: "源字幕原文", text_final: "源字幕原文" },
      ],
      projected_subtitles: [
        { index: 88, source_index: 10, start_time: 0, end_time: 2, text_final: "稳定投影全文" },
      ],
    };
    const currentOutputProjection = [
      { index: 88, source_index: 10, start_time: 0, end_time: 2, text_final: "稳定投影" },
    ];

    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      session,
      buildSourceTranscriptProjectedBaseline(session, {}),
      {},
    );
    const unstableTranscript = buildSourceTranscriptSubtitlesForTimeline(session, currentOutputProjection, {});

    expect(transcript[0].text_final).toBe("源字幕原文");
    expect(unstableTranscript[0].text_final).toBe("源字幕原文");
  });

  it("does not repeat full-row timing text for split source transcript rows", () => {
    const text = "而且这个是有 DLC 涂层的嘛，本身它就有一定的润滑的作用，呃，摸起来真是啊，确实不错啊，呃，钢合金这个版本比我预想的还是要嗯更好一点，然后尾部呢还有一个这个，啊，这个。";
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        source_subtitles: [
          {
            index: 100,
            start_time: 100,
            end_time: 113,
            text_raw: text,
            text_final: text,
            words: Array.from(text).map((word, index) => ({
              word,
              start: 100 + index * 0.04,
              end: 100 + (index + 1) * 0.04,
            })),
            alignment_tokens: Array.from(text).map((token, index) => ({
              text: token,
              start: 100 + index * 0.04,
              end: 100 + (index + 1) * 0.04,
            })),
          },
        ],
        projected_subtitles: [],
      },
      [],
      {},
    );
    const rendered = buildTranscriptTokens(transcript, [{ start: 100, end: 113 }], [])
      .filter((token) => token.kind === "char")
      .map((token) => token.text)
      .join("");

    expect(transcript.length).toBeGreaterThan(1);
    expect(transcript.some((subtitle) => subtitle.alignment_tokens?.length)).toBe(true);
    expect(transcript.flatMap((subtitle) => subtitle.alignment_tokens || []).map((token) => token.text).join("")).toBe(text);
    expect(rendered.replace(/\s/g, "")).toBe(transcript.map((subtitle) => subtitle.text_final).join("").replace(/\s/g, ""));
    expect(rendered.match(/涂层/g)?.length).toBe(1);
    expect(rendered).not.toContain("涂层涂层");
    expect(rendered).not.toContain("的的的");
  });

  it("renders canonical punctuation even when backend alignment tokens only contain timed characters", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 10,
          start_time: 10,
          end_time: 12,
          text_final: "NOC的这个发售，太难了。",
          alignment_tokens: Array.from("NOC的这个发售太难了").map((text, index) => ({
            text,
            start: 10 + index * 0.04,
            end: 10 + (index + 1) * 0.04,
          })),
        },
      ],
      [{ start: 10, end: 12 }],
      [],
    );

    expect(tokens.filter((token) => token.kind === "char").map((token) => token.text).join("")).toBe("NOC的这个发售，太难了。");
  });

  it("keeps canonical text order when timing metadata is not monotonic", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 10,
          start_time: 10,
          end_time: 12,
          text_final: "NOC的，这个发售啊，嗯，太难了。",
          alignment_tokens: [
            { text: "N", start: 10.0, end: 10.1 },
            { text: "O", start: 10.1, end: 10.2 },
            { text: "C", start: 10.2, end: 10.3 },
            { text: "的", start: 10.3, end: 10.5 },
            { text: "这", start: 10.42, end: 10.52 },
            { text: "个", start: 10.52, end: 10.62 },
            { text: "发", start: 10.62, end: 10.72 },
            { text: "售", start: 10.72, end: 10.82 },
            { text: "啊", start: 10.82, end: 10.92 },
            { text: "嗯", start: 10.9, end: 11.0 },
            { text: "太", start: 11.0, end: 11.1 },
            { text: "难", start: 11.1, end: 11.2 },
            { text: "了", start: 11.2, end: 11.3 },
          ],
        },
      ],
      [{ start: 10, end: 12 }],
      [],
    );

    expect(tokens.filter((token) => token.kind === "char").map((token) => token.text).join("")).toBe("NOC的，这个发售啊，嗯，太难了。");
  });

  it("splits backend alignment spans into per-character transcript tokens", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 12,
          start_time: 30,
          end_time: 31,
          text_final: "我只能说是",
          alignment_tokens: [
            { text: "我只能", start: 30.0, end: 30.45 },
            { text: "说是", start: 30.45, end: 30.8 },
          ],
        },
      ],
      [{ start: 30, end: 31 }],
      [],
    ).filter((token) => token.kind === "char");

    expect(tokens.map((token) => token.text)).toEqual(["我", "只", "能", "说", "是"]);
    expect(tokens).toHaveLength(5);
    expect(tokens[0]?.start).toBe(30);
    expect(tokens[4]?.end).toBe(30.8);
  });

  it("treats rule overlaps as suggestions instead of deleted transcript tokens", () => {
    const [token] = buildTranscriptTokens(
      [
        {
          index: 13,
          start_time: 40,
          end_time: 41,
          text_final: "然后",
          alignment_tokens: [{ text: "然后", start: 40, end: 40.4 }],
        },
      ],
      [{ start: 40, end: 41 }],
      [],
    );

    expect(token).toBeTruthy();
    expect(transcriptTokenSmartCutVisualState(
      token!,
      [],
      [{ start: 40, end: 40.4, kind: "catchphrase", sourceText: "然后" }],
    )).toEqual(expect.objectContaining({
      cut: false,
      cutKind: null,
      suggestionKind: "catchphrase",
    }));
  });

  it("does not project hidden raw fillers onto visible transcript timing during local rule scans", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 15,
          start_time: 2.32,
          end_time: 4.0,
          text_raw: "啊，呃，今天我们直奔主题啊，呃，",
          text_norm: "啊，呃，今天我们直奔主题啊，呃，",
          text_final: "今天我们直奔主题啊",
          words: [
            { word: "今", start: 2.64, end: 2.76 },
            { word: "天", start: 2.76, end: 2.88 },
            { word: "我", start: 2.88, end: 3.0 },
            { word: "们", start: 3.0, end: 3.12 },
            { word: "直", start: 3.12, end: 3.24 },
            { word: "奔", start: 3.24, end: 3.36 },
            { word: "主", start: 3.36, end: 3.48 },
            { word: "题", start: 3.48, end: 3.6 },
            { word: "啊", start: 3.6, end: 3.78 },
          ],
        },
      ],
      {
        fillerEnabled: true,
        fillerStandaloneEnabled: true,
        fillerSentenceHeadEnabled: true,
        fillerSentenceTailEnabled: true,
        fillers: "啊,呃",
        catchphraseEnabled: false,
        catchphrases: "",
        repeatedEnabled: false,
        pauseEnabled: false,
        pauseThresholdSec: 0.8,
        smartDeleteEnabled: false,
      },
    );

    expect(analysis.filler.some((range) => range.sourceText === "呃")).toBe(false);
    expect(analysis.filler.some((range) => range.sourceText === "啊" && range.start < 2.5)).toBe(false);
    expect(analysis.filler.some((range) => range.sourceText === "啊" && range.fillerMode === "sentence_tail" && range.start >= 3.55)).toBe(true);
  });

  it("keeps backend authority scoped to the rule kinds whose settings still match the session", () => {
    const sessionRules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      fillers: "嗯，呃",
      catchphraseEnabled: true,
      catchphrases: "就是，然后",
      repeatedEnabled: true,
      pauseEnabled: true,
      pauseThresholdSec: 0.8,
      smartDeleteEnabled: true,
    };
    expect(manualEditorAuthoritativeSmartCutKinds(true, sessionRules, sessionRules)).toEqual([
      "smart_delete",
      "filler",
      "catchphrase",
      "repeated",
      "pause",
    ]);
    expect(
      manualEditorAuthoritativeSmartCutKinds(
        true,
        { ...sessionRules, fillerSentenceHeadEnabled: true },
        sessionRules,
      ),
    ).toEqual(["smart_delete", "catchphrase", "repeated", "pause"]);
    expect(manualEditorAuthoritativeSmartCutKinds(false, sessionRules, sessionRules)).toEqual([]);
  });

  it("keeps explicit cut state separate from suggestion attribution", () => {
    const [token] = buildTranscriptTokens(
      [
        {
          index: 14,
          start_time: 50,
          end_time: 51,
          text_final: "呃",
          alignment_tokens: [{ text: "呃", start: 50, end: 50.2 }],
        },
      ],
      [],
      [],
    );

    expect(token).toBeTruthy();
    expect(transcriptTokenSmartCutVisualState(
      token!,
      [{ start: 50, end: 50.2 }],
      [{ start: 50, end: 50.2, kind: "filler", sourceText: "呃", fillerMode: "standalone" }],
    )).toEqual(expect.objectContaining({
      cut: true,
      cutKind: "filler",
      suggestionKind: null,
    }));
  });

  it("keeps full-text editing on source transcript even when projected subtitles look cleaner", () => {
    const session = {
      keep_segments: [{ start: 0, end: 30 }],
      source_subtitles: [
        {
          index: 9,
          start_time: 17.12,
          end_time: 20.78,
          text_raw: "NC的这个发售太难了难上加难",
          text_final: "NC的这个发售太难了难上加难",
        },
      ],
      projected_subtitles: [
        { index: 90, source_index: 9, source_indexes: [9], start_time: 17.12, end_time: 18.9, text_final: "NOC的这个发售" },
        { index: 91, source_index: 9, source_indexes: [9], start_time: 19.6, end_time: 20.78, text_final: "太难了难上加难" },
      ],
    };

    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      session,
      buildSourceTranscriptProjectedBaseline(session, {}),
      {},
    );

    expect(transcript.map((item) => item.text_final).join("")).toBe("NC的这个发售太难了难上加难");
    expect(transcript.map((item) => [item.start_time, item.end_time])).toEqual([[17.12, 20.78]]);
  });

  it("does not splice output subtitle projection text back into the full source transcript", () => {
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        keep_segments: [{ start: 1.6, end: 39.42 }],
        source_subtitles: [
          { index: 49, source_index: 0, start_time: 1.6, end_time: 5.05, text_final: "哦，今天终于收到了年前的" },
          { index: 50, source_index: 0, start_time: 5.05, end_time: 8.5, text_final: "最后的一款小玩具啊，嗯，" },
        ],
        projected_subtitles: [
          { index: 1, source_index: 0, start_time: 0.1, end_time: 0.5, text_final: "今天终于收到了年前最后的一款小玩具我这这次的气欧啊" },
          { index: 2, source_index: 0, start_time: 0.5, end_time: 0.8, text_final: "NOCNO的C的这个发售" },
        ],
      },
      [
        { index: 1, source_index: 0, start_time: 0.1, end_time: 0.5, text_final: "今天终于收到了年前最后的一款小玩具我这这次的气欧啊" },
        { index: 2, source_index: 0, start_time: 0.5, end_time: 0.8, text_final: "NOCNO的C的这个发售" },
      ],
      {},
    );

    const text = transcript.map((item) => item.text_final).join("");
    expect(text).toBe("哦，今天终于收到了年前的最后的一款小玩具啊，嗯，");
    expect(text).not.toContain("NOCNO");
    expect(text).not.toContain("我这这次");
  });

  it("splits source fallback subtitles so preview rows do not regress into long lines", () => {
    const projection = remapSubtitles(
      [
        {
          index: 9,
          start_time: 0,
          end_time: 8,
          text_final: "没有这个像很多兄弟一样隐恨总算这个年还能过不然这个真的是难受能难受好久",
        },
      ],
      [{ start: 0, end: 8 }],
    );
    const transcript = buildSourceTranscriptSubtitlesForTimeline(
      {
        keep_segments: [{ start: 0, end: 8 }],
        source_subtitles: projection.remapped,
        projected_subtitles: [],
      },
      [],
      {},
    );

    expect(transcript.length).toBeGreaterThan(1);
    expect(transcript.every((item) => Array.from(String(item.text_final || "")).length <= 32)).toBe(true);
    expect(transcript.map((item) => item.text_final).join("")).toBe("没有这个像很多兄弟一样隐恨总算这个年还能过不然这个真的是难受能难受好久");
  });

  it("uses raw source text for filler rule analysis and auto ranges", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 0.4, text_raw: "嗯", text_final: "嗯" },
        { index: 1, start_time: 0.4, end_time: 1.4, text_raw: "我们开始", text_final: "我们开始" },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" },
      [],
    );

    expect(analysis.filler).toHaveLength(1);
    expect(autoSmartCutRuleRanges(analysis, { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" })).toEqual([
      { start: 0, end: 0.4, kind: "filler", fillerMode: "standalone", sourceText: "嗯" },
    ]);
  });

  it("ships a default filler set that still covers standalone particles", () => {
    expect(DEFAULT_SMART_CUT_FILLERS).toContain("嗯");
    expect(DEFAULT_SMART_CUT_FILLERS).toContain("呃");
    expect(DEFAULT_SMART_CUT_FILLERS).toContain("额");
    expect(DEFAULT_SMART_CUT_FILLERS).toContain("啊");
    expect(DEFAULT_SMART_CUT_FILLERS).toContain("吧");
  });

  it("normalizes both old default filler presets and the previous expanded preset back to the shared default", () => {
    expect(normalizeStoredSmartCutFillers("嗯，呃，额，呃呃，嗯嗯")).toBe(DEFAULT_SMART_CUT_FILLERS);
    expect(normalizeStoredSmartCutFillers("嗯，呃，额，啊，呀，呢，吧，嘛，哦，喔，哎，唉，诶，欸，呃呃，嗯嗯")).toBe(DEFAULT_SMART_CUT_FILLERS);
  });

  it("keeps genuinely customized filler presets instead of overwriting them with the default set", () => {
    expect(normalizeStoredSmartCutFillers("嗯，呃，打个比方")).toBe("嗯，呃，打个比方");
  });

  it("parses filler separators across english and chinese punctuation", () => {
    expect(parseSmartCutFillers("嗯，呃、啊;吧；嘛 哦")).toEqual(["嗯", "呃", "啊", "吧", "嘛", "哦"]);
  });

  it("ships a default catchphrase set for common low-information spoken phrases", () => {
    expect(DEFAULT_SMART_CUT_CATCHPHRASES).toContain("就是");
    expect(DEFAULT_SMART_CUT_CATCHPHRASES).toContain("然后");
    expect(DEFAULT_SMART_CUT_CATCHPHRASES).toContain("我觉得");
  });

  it("parses catchphrase separators across english and chinese punctuation", () => {
    expect(parseSmartCutCatchphrases("就是，然后、其实;你知道 我觉得")).toEqual(["你知道", "我觉得", "就是", "然后", "其实"]);
  });

  it("matches filler rules against transcript source text when timings support the spoken filler", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 1.2,
          text_final: "我们开始",
          transcript_text: "嗯我们开始",
          words: [
            { word: "嗯", start: 0, end: 0.16 },
            { word: "我们", start: 0.24, end: 0.56 },
            { word: "开始", start: 0.56, end: 1.02 },
          ],
        },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" },
      [],
    );

    expect(analysis.filler).toHaveLength(1);
    expect(analysis.filler[0]).toEqual(expect.objectContaining({ kind: "filler", fillerMode: "sentence_head" }));
  });

  it("does not invent filler rule matches from unsupported transcript-only noise", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 1.2,
          text_final: "我们开始",
          transcript_text: "嗯我们开始",
        },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" },
      [],
    );

    expect(analysis.filler).toEqual([]);
  });

  it("matches standalone fillers and auto-cuts them by default", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯,啊",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 2,
          text_final: "嗯，今天我们开始",
          words: [
            { word: "嗯", start: 0, end: 0.22 },
            { word: "今天", start: 0.36, end: 0.86 },
            { word: "我们", start: 0.86, end: 1.24 },
            { word: "开始", start: 1.24, end: 1.8 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.filler).toEqual([{ start: 0, end: 0.22, kind: "filler", fillerMode: "standalone", sourceText: "嗯" }]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([{ start: 0, end: 0.22, kind: "filler", fillerMode: "standalone", sourceText: "嗯" }]);
  });

  it("matches standalone fillers from raw source text even when final text has already been cleaned", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "啊",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 1.2,
          text_raw: "啊，今天我们开始",
          text_norm: "啊，今天我们开始",
          text_final: "今天我们开始",
        },
      ],
      rules,
      [],
    );

    expect(analysis.filler).toHaveLength(1);
    expect(analysis.filler[0]).toEqual(expect.objectContaining({ kind: "filler", fillerMode: "standalone", sourceText: "啊" }));
  });

  it("classifies sentence-tail particles separately and keeps them off by default", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "啊",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 2,
          text_final: "小玩具啊",
          words: [
            { word: "小玩具", start: 0, end: 0.5 },
            { word: "啊", start: 0.5, end: 0.7 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.filler).toEqual([{ start: 0.5, end: 0.7, kind: "filler", fillerMode: "sentence_tail", sourceText: "啊" }]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, { ...rules, fillerSentenceTailEnabled: true })).toEqual([
      { start: 0.5, end: 0.7, kind: "filler", fillerMode: "sentence_tail", sourceText: "啊" },
    ]);
  });

  it("treats pause-separated fillers as standalone even when punctuation is missing", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "呃",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 2.2,
          text_final: "这个呃我们开始",
          transcript_text: "这个呃我们开始",
          words: [
            { word: "这个", start: 0, end: 0.45 },
            { word: "呃", start: 0.72, end: 0.92 },
            { word: "我们开始", start: 1.18, end: 2.0 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.filler).toEqual([{ start: 0.72, end: 0.92, kind: "filler", fillerMode: "standalone", sourceText: "呃" }]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([
      { start: 0.72, end: 0.92, kind: "filler", fillerMode: "standalone", sourceText: "呃" },
    ]);
  });

  it("matches configured catchphrases inside spoken sentences as an independent rule", () => {
    const rules = {
      fillerEnabled: false,
      catchphraseEnabled: true,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯,呃",
      catchphrases: "就是,你知道",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 2.4,
          text_final: "这个功能就是很顺手你知道",
          transcript_text: "这个功能就是很顺手你知道",
          words: [
            { word: "这个功能", start: 0, end: 0.5 },
            { word: "就是", start: 0.5, end: 0.8 },
            { word: "很顺手", start: 0.8, end: 1.4 },
            { word: "你知道", start: 1.4, end: 1.9 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.catchphrase).toEqual([
      { start: 0.5, end: 0.8, kind: "catchphrase", sourceText: "就是" },
      { start: 1.4, end: 1.9, kind: "catchphrase", sourceText: "你知道" },
    ]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([
      { start: 0.5, end: 0.8, kind: "catchphrase", sourceText: "就是" },
      { start: 1.4, end: 1.9, kind: "catchphrase", sourceText: "你知道" },
    ]);
  });

  it("prefers backend filler rule ranges when cleaned transcript text no longer exposes the particle", () => {
    const rules = { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 1.2,
          text_final: "我们开始",
          transcript_text: "嗯我们开始",
        },
      ],
      rules,
      [],
      [
        {
          start: 0,
          end: 0.18,
          duration_sec: 0.18,
          kind: "filler",
          reason: "filler_word",
          source: "manual_editor_rule_candidate",
          auto_applied: false,
        },
      ],
    );

    expect(analysis.filler).toEqual([
      expect.objectContaining({ start: 0, end: 0.18, kind: "filler", reason: "filler_word" }),
    ]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([
      expect.objectContaining({ start: 0, end: 0.18, kind: "filler" }),
    ]);
  });

  it("detects repeated phrase retakes beyond short duplicated words", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const text = "找了一个小兄弟找了一个小兄弟";
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 0,
          start_time: 0,
          end_time: 1.4,
          text_final: text,
          words: Array.from(text).map((word, index) => ({
            word,
            start: index * 0.1,
            end: (index + 1) * 0.1,
          })),
        },
      ],
      rules,
      [],
    );

    expect(analysis.repeated).toEqual([{ start: 0.7, end: 1.4, kind: "repeated" }]);
    expect(applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 1.4 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      1.4,
    )).toEqual([{ start: 0, end: 0.7 }]);
  });

  it("does not auto-cut repeated text from estimated character timing", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [{ index: 0, start_time: 0, end_time: 6, text_final: "落在中间会落在中间会有点滑手" }],
      rules,
      [],
    );

    expect(analysis.repeated).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
  });

  it("does not mark protected model text or conversational connector repeats as repeated speech", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 0,
          end_time: 4,
          text_final: "这个这个经常会EDEDC用的啊",
          words: [
            { word: "这个", start: 0, end: 0.3 },
            { word: "这个", start: 0.3, end: 0.6 },
            { word: "经常会", start: 0.8, end: 1.2 },
            { word: "EDEDC", start: 1.2, end: 1.8 },
            { word: "用的啊", start: 1.8, end: 2.3 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.repeated).toEqual([]);
  });

  it("detects single-character stutter repeats when timing shows a real restart gap", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 27,
          start_time: 113.8,
          end_time: 120.52,
          text_final: "所以呢我们总归啊是需需要有这么一个呃又轻便又易用",
          words: [
            { word: "所以呢", start: 113.8, end: 114.2 },
            { word: "我们", start: 114.2, end: 114.52 },
            { word: "总归啊是", start: 115.48, end: 116.04 },
            { word: "需", start: 116.04, end: 116.28 },
            { word: "需", start: 117.08, end: 117.16 },
            { word: "要有这么一个", start: 117.16, end: 118.12 },
            { word: "呃", start: 118.28, end: 118.6 },
            { word: "又轻便又易用", start: 118.68, end: 120.52 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.repeated).toEqual([{ start: 117.08, end: 117.16, kind: "repeated" }]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([{ start: 117.08, end: 117.16, kind: "repeated" }]);
  });

  it("does not mark natural doubled words like 沉甸甸 as repeated speech", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 24,
          start_time: 145.08,
          end_time: 148.76,
          text_final: "沉甸甸的好沉啊赶紧开",
          words: [
            { word: "沉", start: 145.08, end: 145.24 },
            { word: "甸", start: 145.24, end: 145.4 },
            { word: "甸", start: 145.4, end: 145.56 },
            { word: "的好沉啊赶紧开", start: 145.56, end: 148.76 },
          ],
        },
      ],
      rules,
      [],
    );

    expect(analysis.repeated).toEqual([]);
  });

  it("does not auto-cut long VAD pauses inside meaningful subtitle text", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "大家看到现在这个镜头里有两把手电",
        },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" },
      [{ start: 8.37, end: 9.45, duration_sec: 1.08, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" })).toEqual([]);
  });

  it("does not auto-cut audio silence inside subtitle text when word timings are stale", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 8,
          start_time: 29.894,
          end_time: 34.609,
          text_final: "购难度直线上升没想",
          words: [
            { word: "也", start: 30.88, end: 30.96 },
            { word: "是", start: 30.96, end: 31.28 },
            { word: "啊", start: 31.28, end: 31.44 },
            { word: "我", start: 31.44, end: 31.6 },
          ],
        },
      ],
      rules,
      [{ start: 29.72, end: 30.78, duration_sec: 1.06, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
  });

  it("does not auto-cut a VAD pause that overlaps orphan transcript speech", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 9,
          start_time: 1.6,
          end_time: 2.04,
          text_raw: "然后呢",
          text_final: "然后呢",
          words: [
            { word: "然", start: 1.6, end: 1.72 },
            { word: "后", start: 1.72, end: 1.9 },
            { word: "呢", start: 1.9, end: 2.04 },
          ],
        },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" },
      [{ start: 1.2, end: 3.2, duration_sec: 2.0, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([]);
  });

  it("does not auto-cut a VAD pause that touches the next spoken word", () => {
    const rules = { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "大家看到现在这个镜头里有两把手电",
          words: [
            { word: "这个", start: 7.68, end: 8.16 },
            { word: "镜头", start: 9.4, end: 9.76 },
          ],
        },
      ],
      rules,
      [{ start: 8.37, end: 9.45, duration_sec: 1.08, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
  });

  it("prefers backend pause rule ranges over stale local pause inference", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "大家看到现在这个镜头里有两把手电",
        },
      ],
      rules,
      [{ start: 8.37, end: 9.45, duration_sec: 1.08, source: "audio_vad" }],
      [
        {
          start: 8.37,
          end: 9.3,
          duration_sec: 0.93,
          kind: "pause",
          reason: "silence",
          source: "auto_edit_decision",
          auto_applied: true,
        },
      ],
    );

    expect(analysis.pause).toEqual([
      expect.objectContaining({ start: 8.37, end: 9.3, kind: "pause", reason: "silence" }),
    ]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([
      expect.objectContaining({ start: 8.37, end: 9.3, kind: "pause" }),
    ]);
  });

  it("keeps backend short pause candidates below the threshold out of auto-cut pause ranges", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 2, text_final: "前一句内容" },
        { index: 1, start_time: 2.6, end_time: 4, text_final: "后一句内容" },
      ],
      rules,
      [],
      [
        {
          start: 2.1,
          end: 2.5,
          duration_sec: 0.4,
          kind: "pause",
          reason: "silence",
          source: "manual_editor_rule_candidate",
          auto_applied: false,
        },
      ],
    );

    expect(analysis.pauseCandidates).toEqual([
      expect.objectContaining({ start: 2.1, end: 2.5, kind: "pause", reason: "silence" }),
    ]);
    expect(analysis.pause).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
  });

  it("auto-cuts long VAD pauses between word timings inside a coarse subtitle row", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "大家看到现在这个镜头里有两把手电",
          words: [
            { word: "这个", start: 7.68, end: 8.16 },
            { word: "镜头", start: 9.46, end: 9.76 },
          ],
        },
      ],
      rules,
      [{ start: 8.37, end: 9.45, duration_sec: 1.08, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([{ start: 8.37, end: 9.3, kind: "pause" }]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([{ start: 8.37, end: 9.3, kind: "pause" }]);
  });

  it("does not auto-cut sparse short subtitle rows whose word timings leave a huge internal speech gap", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 40,
          start_time: 229.72,
          end_time: 234.52,
          text_final: "看啊刃面",
          text_raw: "呃，看啊，刃面。",
          words: [
            { word: "看", start: 229.72, end: 229.88 },
            { word: "啊", start: 229.88, end: 230.12 },
            { word: "刃", start: 234.12, end: 234.2 },
            { word: "面", start: 234.2, end: 234.52 },
          ],
        },
      ],
      rules,
      [
        { start: 230.7, end: 231.15, duration_sec: 0.45, source: "audio_vad" },
        { start: 232.14, end: 234.06, duration_sec: 1.92, source: "audio_vad" },
      ],
    );

    expect(analysis.pause).toEqual([]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
  });

  it("cuts the silent part of a long mixed timing gap instead of dropping the whole gap because of an edge word", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 348,
          start_time: 903.49,
          end_time: 904.25,
          text_final: "食指开",
          words: [
            { word: "食", start: 903.49, end: 903.8 },
            { word: "指", start: 903.8, end: 904.11 },
            { word: "开", start: 904.11, end: 904.25 },
          ],
        },
        {
          index: 349,
          start_time: 921.89,
          end_time: 922.43,
          text_final: "累了",
          words: [
            { word: "累", start: 921.89, end: 922.16 },
            { word: "了", start: 922.16, end: 922.43 },
          ],
        },
      ],
      rules,
      [{ start: 904.25, end: 922.11, duration_sec: 17.86, source: "mixed" }],
    );

    expect(analysis.pause).toEqual([{ start: 904.25, end: 921.73, kind: "pause" }]);
  });

  it("uses real word timings for full-text transcript tokens", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "大家看到现在这个镜头里有两把手电",
          words: [
            { word: "大", start: 5.92, end: 6.0 },
            { word: "家", start: 6.0, end: 6.4 },
            { word: "看", start: 6.4, end: 6.56 },
            { word: "到", start: 6.56, end: 7.04 },
            { word: "现", start: 7.2, end: 7.36 },
            { word: "在", start: 7.36, end: 7.68 },
            { word: "这", start: 7.68, end: 7.76 },
            { word: "个", start: 7.76, end: 8.16 },
            { word: "镜", start: 9.44, end: 9.6 },
            { word: "头", start: 9.6, end: 9.76 },
            { word: "里", start: 9.76, end: 9.92 },
          ],
        },
      ],
      [{ start: 1.32, end: 8.36 }, { start: 9.46, end: 29.9 }],
      [],
    );

    const text = tokens.map((token) => token.text).join("");
    const mirrorIndex = text.indexOf("镜");
    const lensIndex = text.indexOf("头");
    const insideIndex = text.indexOf("里");

    expect(tokens[mirrorIndex].start).toBeCloseTo(9.44, 3);
    expect(tokens[lensIndex].start).toBeCloseTo(9.6, 3);
    expect(tokens[insideIndex].start).toBeCloseTo(9.76, 3);
    expect(tokens[mirrorIndex].kept).toBe(false);
    expect(tokens[lensIndex].kept).toBe(true);
    expect(tokens[insideIndex].kept).toBe(true);
  });

  it("uses backend alignment tokens before local word/text reconstruction", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 3,
          source_index: 3,
          start_time: 17.12,
          end_time: 20,
          text_final: "NOC的这个发售太难了",
          words: [
            { word: "太", start: 19.6, end: 19.84 },
            { word: "难", start: 19.84, end: 20 },
          ],
          alignment_tokens: [
            { text: "太", start: 19.6, end: 19.84, source: "span_alignment" },
            { text: "难", start: 19.84, end: 20, source: "span_alignment" },
          ],
          alignment_diagnostics: {
            status: "warning",
            matched_ratio: 0.8,
            issues: ["unmatched_text_suffix"],
          },
        },
        {
          index: 4,
          source_index: 4,
          start_time: 20,
          end_time: 20.78,
          text_final: "太难了难上加难",
          words: [
            { word: "了", start: 20, end: 20.14 },
            { word: "难", start: 20.14, end: 20.22 },
            { word: "上", start: 20.3, end: 20.38 },
            { word: "加", start: 20.38, end: 20.54 },
            { word: "难", start: 20.54, end: 20.78 },
          ],
          alignment_tokens: [
            { text: "了", start: 20, end: 20.14, source: "span_alignment" },
            { text: "难", start: 20.14, end: 20.22, source: "span_alignment" },
            { text: "上", start: 20.3, end: 20.38, source: "span_alignment" },
            { text: "加", start: 20.38, end: 20.54, source: "span_alignment" },
            { text: "难", start: 20.54, end: 20.78, source: "span_alignment" },
          ],
          alignment_diagnostics: {
            status: "warning",
            matched_ratio: 0.55,
            issues: ["unmatched_text_prefix"],
          },
        },
      ],
      [{ start: 19.6, end: 20.78 }],
      [],
    );

    const charTokens = tokens.filter((token): token is typeof token & { kind: "char" } => token.kind === "char");
    expect(charTokens.map((token) => token.text).join("")).toBe("太难了难上加难");
    expect(charTokens.every((token) => token.timingSource === "alignment")).toBe(true);
  });

  it("shows pauses that are only visible in ASR word timing gaps", () => {
    const subtitles = [
      {
        index: 1,
        start_time: 10,
        end_time: 15,
        text_final: "我说天敌真是天生设计",
        words: [
          { word: "我说", start: 10.1, end: 10.4 },
          { word: "天敌真是", start: 10.4, end: 10.9 },
          { word: "天生", start: 12.1, end: 12.4 },
          { word: "设计", start: 12.4, end: 12.8 },
        ],
      },
    ];
    const pauses = wordTimingPauseIntervals(subtitles);
    const tokens = buildTranscriptTokens(subtitles, [{ start: 10, end: 15 }], pauses);

    expect(pauses).toEqual([{ start: 10.98, end: 12.02, duration_sec: 1.04, source: "word_gap" }]);
    expect(tokens.some((token) => token.kind === "pause" && token.text === "[...,1.0s]")).toBe(true);
  });

  it("ignores word timing gaps when the words belong to a different subtitle row", () => {
    const subtitles = [
      {
        index: 7,
        start_time: 25.178,
        end_time: 29.894,
        text_final: "了难上加难导致这个抢",
        words: [
          { word: "没", start: 26.32, end: 26.4 },
          { word: "想", start: 26.4, end: 26.56 },
          { word: "到", start: 26.56, end: 26.72 },
          { word: "啊", start: 26.72, end: 26.96 },
          { word: "N", start: 27.467, end: 27.538 },
          { word: "O", start: 27.538, end: 27.609 },
          { word: "C", start: 27.609, end: 27.68 },
        ],
      },
      {
        index: 8,
        start_time: 29.894,
        end_time: 34.609,
        text_final: "购难度直线上升没想",
        words: [
          { word: "也", start: 30.88, end: 30.96 },
          { word: "是", start: 30.96, end: 31.28 },
          { word: "啊", start: 31.28, end: 31.44 },
          { word: "我", start: 31.44, end: 31.6 },
        ],
      },
    ];
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };

    expect(wordTimingPauseIntervals(subtitles)).toEqual([]);
    expect(buildSmartCutRuleAnalysis(subtitles, rules, [{ start: 29.72, end: 30.72, duration_sec: 1, source: "word_gap" }]).pause).toEqual([]);
  });

  it("falls back to estimated transcript timing when backend alignment is implausibly compressed", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 7,
          start_time: 25.178,
          end_time: 29.894,
          text_final: "了难上加难导致这个抢",
          alignment_tokens: [
            { text: "了", start: 28.88, end: 28.881 },
            { text: "难", start: 28.881, end: 28.882 },
            { text: "上", start: 28.882, end: 28.883 },
            { text: "加", start: 28.883, end: 28.884 },
            { text: "难", start: 28.884, end: 28.885 },
            { text: "导", start: 28.885, end: 28.886 },
            { text: "致", start: 28.886, end: 28.887 },
            { text: "这", start: 28.88, end: 29.04 },
            { text: "个", start: 29.04, end: 29.041 },
            { text: "抢", start: 29.041, end: 29.042 },
          ],
        },
      ],
      [{ start: 25.178, end: 29.894 }],
      [],
    );

    const speechTokens = tokens.filter((token) => token.kind === "char");
    expect(speechTokens[0]).toEqual(expect.objectContaining({ text: "了", timingSource: "estimated" }));
    expect(speechTokens[0]?.start).toBe(25.178);
    expect(speechTokens.some((token) => token.end <= token.start + 0.006)).toBe(false);
  });

  it("uses audio VAD to bound untranscribed ASR gaps but still displays nearby fragments as one pause chip", () => {
    const inferredPauses = [
      { start: 3.76, end: 5.66, duration_sec: 1.9, source: "word_gap" },
    ];
    const audioSilences = [
      { start: 4.34, end: 4.76, duration_sec: 0.42, source: "audio_vad" },
      { start: 5.42, end: 5.92, duration_sec: 0.5, source: "audio_vad" },
    ];
    const boundedPauses = intersectInferredPausesWithAudioSilence(inferredPauses, audioSilences);

    expect(boundedPauses).toEqual([
      { start: 4.34, end: 4.76, duration_sec: 0.42, source: "word_gap+audio_vad" },
      { start: 5.42, end: 5.66, duration_sec: 0.24, source: "word_gap+audio_vad" },
    ]);
    const tokens = buildTranscriptTokens([], [{ start: 0, end: 8 }], boundedPauses);
    expect(tokens.filter((token) => token.kind === "pause").map((token) => token.text)).toEqual(["[...,1.3s]"]);
    expect(tokens.filter((token) => token.kind === "pause").map((token) => token.pauseCount)).toEqual([2]);
  });

  it("uses real ASR alignment gaps for long split transcript rows", () => {
    const beforePause = Array.from("哦今天终于收到了年前的").map((text, index) => ({
      text,
      start: Number((1.7 + index * 0.12).toFixed(3)),
      end: Number((1.78 + index * 0.12).toFixed(3)),
    }));
    const afterPause = Array.from("最后的一款小玩具啊嗯这个也是耗尽了我这次的欧气啊").map((text, index) => ({
      text,
      start: Number((6.3 + index * 0.12).toFixed(3)),
      end: Number((6.38 + index * 0.12).toFixed(3)),
    }));
    const sourceSubtitle = {
      index: 49,
      start_time: 1.6,
      end_time: 13.8,
      text_final: "哦，今天终于收到了年前的最后的一款小玩具啊，嗯，这个也是耗尽了我这次的欧气啊",
      alignment_tokens: [...beforePause, ...afterPause],
    };
    const displayRows = buildSourceTranscriptSubtitlesForTimeline(
      { keep_segments: [{ start: 1.6, end: 13.8 }], source_subtitles: [sourceSubtitle], projected_subtitles: [] },
      [],
      {},
    );
    const pauses = wordTimingPauseIntervals([sourceSubtitle]);
    const tokens = buildTranscriptTokens(displayRows, [{ start: 1.6, end: 13.8 }], pauses);
    const pauseIndex = tokens.findIndex((token) => token.kind === "pause");
    const nextVisibleToken = tokens.slice(pauseIndex + 1).find((token) => token.kind === "char");

    expect(displayRows.length).toBeGreaterThan(1);
    expect(displayRows.some((subtitle) => subtitle.alignment_tokens?.length)).toBe(true);
    expect(pauses).toEqual([{ start: 3.06, end: 6.22, duration_sec: 3.16, source: "alignment_gap" }]);
    expect(pauseIndex).toBeGreaterThan(-1);
    expect(tokens[pauseIndex - 1]?.text).toBe("的");
    expect(nextVisibleToken?.text).toBe("最");
  });

  it("coalesces final display pause tokens even when keep segments split the silence", () => {
    const tokens = buildTranscriptTokens(
      [],
      [{ start: 0, end: 1 }, { start: 2, end: 3 }],
      [{ start: 0, end: 3, duration_sec: 3, source: "audio_vad" }],
    );

    expect(tokens.map((token) => ({
      kind: token.kind,
      start: token.start,
      end: token.end,
      kept: token.kept,
      pauseDuration: token.pauseDuration,
      pauseCount: token.pauseCount,
      pauseRanges: token.pauseRanges,
    }))).toEqual([
      {
        kind: "pause",
        start: 0,
        end: 3,
        kept: false,
        pauseDuration: 3,
        pauseCount: 3,
        pauseRanges: [{ start: 0, end: 1 }, { start: 1, end: 2 }, { start: 2, end: 3 }],
      },
    ]);
  });

  it("renders adjacent visible pause fragments as one pause chip", () => {
    const tokens = buildTranscriptTokens(
      [],
      [{ start: 2, end: 3 }],
      [
        { start: 0, end: 1.3, duration_sec: 1.3, source: "word_gap" },
        { start: 1.3, end: 1.6, duration_sec: 0.3, source: "audio_vad" },
      ],
    );

    expect(tokens.map((token) => ({
      kind: token.kind,
      start: token.start,
      end: token.end,
      kept: token.kept,
      pauseDuration: token.pauseDuration,
      pauseCount: token.pauseCount,
      pauseRanges: token.pauseRanges,
    }))).toEqual([
      {
        kind: "pause",
        start: 0,
        end: 1.6,
        kept: false,
        pauseDuration: 1.6,
        pauseCount: 2,
        pauseRanges: [{ start: 0, end: 1.3 }, { start: 1.3, end: 1.6 }],
      },
    ]);
  });

  it("renders nearby pause fragments as one pause chip when no speech is between them", () => {
    const tokens = buildTranscriptTokens(
      [],
      [{ start: 2, end: 3 }],
      [
        { start: 0, end: 0.3, duration_sec: 0.3, source: "audio_vad" },
        { start: 0.78, end: 1.12, duration_sec: 0.34, source: "word_gap" },
      ],
    );

    expect(tokens.map((token) => ({
      kind: token.kind,
      start: token.start,
      end: token.end,
      pauseDuration: token.pauseDuration,
      pauseCount: token.pauseCount,
      pauseRanges: token.pauseRanges,
    }))).toEqual([
      {
        kind: "pause",
        start: 0,
        end: 1.12,
        pauseDuration: 1.12,
        pauseCount: 2,
        pauseRanges: [{ start: 0, end: 0.3 }, { start: 0.78, end: 1.12 }],
      },
    ]);
  });

  it("coalesces final adjacent pause tokens even after display ordering", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 0,
          start_time: 0.9,
          end_time: 1.05,
          text_final: "好",
          words: [{ word: "好", start: 0.9, end: 1.05 }],
        },
        {
          index: 1,
          start_time: 1.6,
          end_time: 2.4,
          text_final: "今天我们直奔主题",
          words: [{ word: "今天我们直奔主题", start: 1.6, end: 2.4 }],
        },
      ],
      [{ start: 0, end: 3 }],
      [
        { start: 0, end: 0.7, duration_sec: 0.7, source: "audio_vad" },
        { start: 0.72, end: 0.88, duration_sec: 0.16, source: "word_gap" },
        { start: 1.08, end: 1.24, duration_sec: 0.16, source: "word_gap" },
        { start: 1.3, end: 1.42, duration_sec: 0.12, source: "audio_vad" },
        { start: 1.48, end: 1.58, duration_sec: 0.1, source: "audio_vad" },
      ],
    );

    expect(tokens.map((token) => token.text).join("")).toBe("[...,0.9s]好。[...,0.3s]今天我们直奔主题");
    expect(tokens.filter((token) => token.kind === "pause").map((token) => ({
      start: token.start,
      end: token.end,
      pauseCount: token.pauseCount,
      pauseRanges: token.pauseRanges,
    }))).toEqual([
      {
        start: 0,
        end: 0.88,
        pauseCount: 2,
        pauseRanges: [{ start: 0, end: 0.7 }, { start: 0.72, end: 0.88 }],
      },
      {
        start: 1.08,
        end: 1.42,
        pauseCount: 2,
        pauseRanges: [{ start: 1.08, end: 1.24 }, { start: 1.3, end: 1.42 }],
      },
    ]);
  });

  it("does not coalesce display pause tokens across visible transcript text", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 0,
          start_time: 0.45,
          end_time: 0.55,
          text_final: "好",
          words: [{ word: "好", start: 0.45, end: 0.55 }],
        },
      ],
      [{ start: 0, end: 1 }],
      [
        { start: 0, end: 0.3, duration_sec: 0.3, source: "audio_vad" },
        { start: 0.7, end: 1, duration_sec: 0.3, source: "audio_vad" },
      ],
    );

    expect(tokens.map((token) => token.text).join("")).toBe("[...,0.3s]好[...,0.3s]");
    expect(tokens.filter((token) => token.kind === "pause")).toHaveLength(2);
  });

  it("marks transcript sentence boundaries as real line breaks", () => {
    const tokens = buildTranscriptTokens(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "前一句内容" },
        { index: 1, start_time: 2.3, end_time: 3, text_final: "后一句内容" },
      ],
      [{ start: 0, end: 3 }],
      [],
    );
    const boundaryToken = tokens.find((token) => token.kind === "punctuation" && token.subtitleIndex === 0);

    expect(boundaryToken?.breakAfter).toBe("soft");
  });

  it("keeps dense phrase pauses in transcript order without cutting intervening text", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 1,
          start_time: 0,
          end_time: 5,
          text_final: "前面中间后面",
          words: [
            { word: "前面", start: 0, end: 0.5 },
            { word: "中间", start: 1.1, end: 1.5 },
            { word: "后面", start: 2.2, end: 2.8 },
          ],
        },
      ],
      [{ start: 0, end: 5 }],
      [
        { start: 0.6, end: 0.9, duration_sec: 0.3, source: "audio_vad" },
        { start: 1.7, end: 2.0, duration_sec: 0.3, source: "audio_vad" },
      ],
    );
    const pauseTokens = tokens.filter((token) => token.kind === "pause");
    const cutRanges = transcriptCutRangesForSelection(
      [],
      tokens,
      {
        startTokenIndex: tokens.findIndex((token) => token.kind === "pause"),
        endTokenIndex: tokens.findIndex((token) => token.kind === "pause"),
      },
      5,
    );

    expect(tokens.map((token) => token.text).join("")).toBe("前面[...,0.3s]中间[...,0.3s]后面");
    expect(pauseTokens).toHaveLength(2);
    expect(pauseTokens.map((token) => ({
      start: token.start,
      end: token.end,
      pauseDuration: token.pauseDuration,
      pauseRanges: token.pauseRanges,
    }))).toEqual([
      { start: 0.6, end: 0.9, pauseDuration: 0.3, pauseRanges: [{ start: 0.6, end: 0.9 }] },
      { start: 1.7, end: 2, pauseDuration: 0.3, pauseRanges: [{ start: 1.7, end: 2 }] },
    ]);
    expect(cutRanges).toEqual([{ start: 0.6, end: 0.9 }]);
  });

  it("keeps pause auto-cuts away from neighboring word edges", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        {
          index: 1,
          start_time: 4.88,
          end_time: 11.52,
          text_final: "那身份卡啊所以还很期待",
          words: [
            { word: "那身份卡啊", start: 4.88, end: 5.42 },
            { word: "所以", start: 5.62, end: 5.9 },
            { word: "还很期待", start: 7.1, end: 7.7 },
          ],
        },
      ],
      rules,
      [{ start: 5.88, end: 7.12, duration_sec: 1.24, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([{ start: 6.06, end: 6.94, kind: "pause" }]);
  });

  it("expands a fully selected subtitle cut to the hidden subtitle timing edges", () => {
    const subtitles = [
      {
        index: 7,
        start_time: 20,
        end_time: 27,
        text_final: "不对这么难拆啊",
        words: [
          { word: "不对", start: 20.6, end: 21.0 },
          { word: "这么难拆啊", start: 24.0, end: 25.4 },
        ],
      },
    ];
    const tokens = buildTranscriptTokens(subtitles, [{ start: 20, end: 27 }], wordTimingPauseIntervals(subtitles));
    const cutRanges = transcriptCutRangesForSelection(
      subtitles,
      tokens,
      { startTokenIndex: 0, endTokenIndex: tokens.length - 1 },
      30,
    );

    expect(cutRanges).toEqual([{ start: 20, end: 27 }]);
  });

  it("does not render a VAD pause inside a real ASR word as a separate transcript token", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 1,
          start_time: 10,
          end_time: 11.3,
          text_final: "因为之前",
          words: [
            { word: "因为", start: 10, end: 10.9 },
            { word: "之前", start: 10.9, end: 11.3 },
          ],
        },
      ],
      [{ start: 10, end: 11.3 }],
      [{ start: 10.2, end: 10.8, duration_sec: 0.6, source: "audio_vad" }],
    );

    expect(tokens.map((token) => token.text).join("")).toBe("因为之前");
    expect(tokens.some((token) => token.kind === "pause")).toBe(false);
  });

  it("does not render audio VAD pauses over coarse backend alignment speech", () => {
    const tokens = buildTranscriptTokens(
      [
        {
          index: 1,
          start_time: 2.12,
          end_time: 8.36,
          text_final: "今天终于收到了年前的最后的一个小玩具",
          alignment_tokens: [
            { text: "收", start: 3.22, end: 3.7, source: "span_alignment" },
            { text: "到", start: 3.22, end: 3.7, source: "span_alignment" },
            { text: "了", start: 3.7, end: 3.84, source: "span_alignment" },
            { text: "年", start: 3.84, end: 4.7, source: "span_alignment" },
            { text: "前", start: 3.84, end: 4.7, source: "span_alignment" },
            { text: "最", start: 5.0, end: 6.56, source: "span_alignment" },
            { text: "后", start: 5.0, end: 6.56, source: "span_alignment" },
          ],
        },
      ],
      [{ start: 2.12, end: 8.36 }],
      [{ start: 5.85, end: 6.21, duration_sec: 0.36, source: "audio_vad" }],
    );

    expect(tokens.some((token) => token.kind === "pause")).toBe(false);
  });

  it("still auto-cuts long VAD pauses between subtitle rows", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "前一句内容" },
        { index: 1, start_time: 3, end_time: 4, text_final: "后一句内容" },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" },
      [{ start: 1.2, end: 2.6, duration_sec: 1.4, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([{ start: 1.2, end: 2.6, kind: "pause" }]);
  });

  it("auto-cuts nearby short pause fragments once the pause group reaches the threshold", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "前一句内容" },
        { index: 1, start_time: 2.2, end_time: 3, text_final: "后一句内容" },
      ],
      rules,
      [
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.45, end: 1.9, duration_sec: 0.45, source: "audio_vad" },
      ],
    );

    expect(analysis.pauseCandidates).toEqual([
      { start: 1, end: 1.35, kind: "pause" },
      { start: 1.45, end: 1.9, kind: "pause" },
    ]);
    expect(analysis.pause).toEqual([
      { start: 1, end: 1.35, kind: "pause" },
      { start: 1.45, end: 1.9, kind: "pause" },
    ]);
  });

  it("applies clustered pause cuts as pause-only ranges while retaining the threshold duration", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.6, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "前一句内容" },
        { index: 1, start_time: 2.2, end_time: 3, text_final: "后一句内容" },
      ],
      rules,
      [
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.45, end: 1.9, duration_sec: 0.45, source: "audio_vad" },
      ],
    );

    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 3 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      3,
      [],
      rules,
    );
    const tokens = buildTranscriptTokens(
      [],
      nextSegments,
      [
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.45, end: 1.9, duration_sec: 0.45, source: "audio_vad" },
      ],
    );

    expect(nextSegments).toEqual([{ start: 0, end: 1.3 }, { start: 1.35, end: 1.45 }, { start: 1.6, end: 3 }]);
    expect(tokens.map((token) => ({
      kind: token.kind,
      start: token.start,
      end: token.end,
      kept: token.kept,
      pauseDuration: token.pauseDuration,
    }))).toEqual([
      { kind: "pause", start: 1, end: 1.9, kept: false, pauseDuration: 0.9 },
    ]);
  });

  it("never applies pause cuts across protected ASR speech timings", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 2 }],
      [{ start: 0.4, end: 1.6, kind: "pause" }],
      [{ start: 0.4, end: 1.6, kind: "pause" }],
      2,
      [],
      rules,
      [{ start: 0.9, end: 1.05 }],
    );
    const tokens = buildTranscriptTokens(
      [{ index: 0, start_time: 0.9, end_time: 1.05, text_final: "好", words: [{ word: "好", start: 0.9, end: 1.05 }] }],
      nextSegments,
      [],
    );

    expect(tokens.find((token) => token.text === "好")?.kept).toBe(true);
    expect(nextSegments).toEqual([{ start: 0, end: 0.8 }, { start: 0.87, end: 1.08 }, { start: 1.2, end: 2 }]);
  });

  it("normalizes raw pause evidence into visible review pause units", () => {
    const normalized = normalizeReviewPauseRanges(
      [
        { start: 0.2, end: 0.7, duration_sec: 0.5, source: "audio_vad" },
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.45, end: 1.9, duration_sec: 0.45, source: "word_gap" },
        { start: 3, end: 3.7, duration_sec: 0.7, source: "audio_vad" },
        { start: 4, end: 4.92, duration_sec: 0.92, source: "audio_vad" },
      ],
      [],
      { fillers: [] },
    );

    expect(normalized).toEqual([
      { start: 0.2, end: 1.9, duration_sec: 1.7, source: "mixed" },
      { start: 3, end: 4.92, duration_sec: 1.92, source: "audio_vad" },
    ]);
  });

  it("keeps fragmented short pauses separate across meaningful speech", () => {
    const normalized = normalizeReviewPauseRanges(
      [
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.5, end: 1.95, duration_sec: 0.45, source: "audio_vad" },
      ],
      [{ index: 1, start_time: 1.38, end_time: 1.48, text_final: "中间" }],
      { fillers: [] },
    );

    expect(normalized).toEqual([
      { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
      { start: 1.5, end: 1.95, duration_sec: 0.45, source: "audio_vad" },
    ]);
  });

  it("merges adjacent pauses inside a coarse subtitle row when no timed speech sits between them", () => {
    const normalized = normalizeReviewPauseRanges(
      [
        { start: 0.6, end: 0.9, duration_sec: 0.3, source: "audio_vad" },
        { start: 1.08, end: 1.42, duration_sec: 0.34, source: "word_gap" },
      ],
      [
        {
          index: 1,
          start_time: 0,
          end_time: 3,
          text_final: "前面后面",
          words: [
            { word: "前面", start: 0, end: 0.5 },
            { word: "后面", start: 1.8, end: 2.3 },
          ],
        },
      ],
      { fillers: [] },
    );

    expect(normalized).toEqual([{ start: 0.6, end: 1.42, duration_sec: 0.82, source: "mixed" }]);
  });

  it("does not merge adjacent pauses when timed speech sits between them", () => {
    const normalized = normalizeReviewPauseRanges(
      [
        { start: 0.6, end: 0.9, duration_sec: 0.3, source: "audio_vad" },
        { start: 1.18, end: 1.5, duration_sec: 0.32, source: "audio_vad" },
      ],
      [
        {
          index: 1,
          start_time: 0,
          end_time: 3,
          text_final: "前中后",
          words: [
            { word: "前", start: 0, end: 0.5 },
            { word: "中", start: 0.98, end: 1.08 },
            { word: "后", start: 1.8, end: 2.3 },
          ],
        },
      ],
      { fillers: [] },
    );

    expect(normalized).toEqual([
      { start: 0.6, end: 0.9, duration_sec: 0.3, source: "audio_vad" },
      { start: 1.18, end: 1.5, duration_sec: 0.32, source: "audio_vad" },
    ]);
  });

  it("uses dense short pause groups for threshold detection while cutting only pause ranges", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "前一句内容" },
        { index: 1, start_time: 1.38, end_time: 1.48, text_final: "中间" },
        { index: 2, start_time: 2.2, end_time: 3, text_final: "后一句内容" },
      ],
      rules,
      [
        { start: 1, end: 1.35, duration_sec: 0.35, source: "audio_vad" },
        { start: 1.5, end: 1.95, duration_sec: 0.45, source: "audio_vad" },
      ],
    );

    expect(analysis.pauseCandidates).toEqual([
      { start: 1, end: 1.35, kind: "pause" },
      { start: 1.5, end: 1.95, kind: "pause" },
    ]);
    expect(analysis.pause).toEqual([
      { start: 1, end: 1.35, kind: "pause" },
      { start: 1.5, end: 1.95, kind: "pause" },
    ]);
    expect(sourceRangeOverlapsCutRanges(1.38, 1.48, autoSmartCutRuleRanges(analysis, rules))).toBe(false);
  });

  it("recomputes rule-managed pauses from the restored baseline instead of preserving stale short cuts", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 0.5, text_final: "开头" },
        { index: 1, start_time: 0.9, end_time: 1.3, text_final: "继续" },
        { index: 2, start_time: 2.5, end_time: 3, text_final: "后面" },
      ],
      rules,
      [
        { start: 0.5, end: 0.9, duration_sec: 0.4, source: "audio_vad" },
        { start: 1.3, end: 2.5, duration_sec: 1.2, source: "audio_vad" },
      ],
    );

    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 0.5 }, { start: 0.9, end: 1.3 }, { start: 2.5, end: 3 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      3,
    );

    expect(analysis.pause).toEqual([
      { start: 0.5, end: 0.9, kind: "pause" },
      { start: 1.3, end: 2.5, kind: "pause" },
    ]);
    expect(nextSegments).toEqual([{ start: 0, end: 1.3 }, { start: 2.1, end: 3 }]);
  });

  it("does not auto-cut a pause range after the user manually restores it", () => {
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 1 }, { start: 2, end: 3 }],
      [{ start: 1, end: 2 }],
      [{ start: 1, end: 2 }],
      3,
      [{ start: 1, end: 2 }],
    );

    expect(nextSegments).toEqual([{ start: 0, end: 3 }]);
  });

  it("uses the pause threshold as the retained pause duration when shrinking deleted pause ranges", () => {
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 1 }, { start: 2, end: 3 }],
      [{ start: 1, end: 2, kind: "pause" }],
      [{ start: 1, end: 2, kind: "pause" }],
      3,
      [],
      { pauseThresholdSec: 0.4 },
    );

    expect(nextSegments).toEqual([{ start: 0, end: 1.2 }, { start: 1.8, end: 3 }]);
  });

  it("still cuts the unrestored sides of a partially restored pause range", () => {
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 1 }, { start: 2, end: 3 }],
      [{ start: 1, end: 2 }],
      [{ start: 1, end: 2 }],
      3,
      [{ start: 1.4, end: 1.6 }],
    );

    expect(nextSegments).toEqual([{ start: 0, end: 1 }, { start: 1.4, end: 1.6 }, { start: 2, end: 3 }]);
  });

  it("keeps backend smart-delete waste segments as confirm-required suggestions", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [],
      rules,
      [],
      [{ start: 12.3456, end: 14.9, duration_sec: 2.554, kind: "smart_delete", reason: "restart_retake", source: "llm_cut_review" }],
    );

    expect(analysis.smartDelete).toEqual([expect.objectContaining({ start: 12.346, end: 14.9, kind: "smart_delete" })]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
    expect(smartDeleteSuggestionRanges(analysis, rules)).toEqual([expect.objectContaining({ start: 12.346, end: 14.9, kind: "smart_delete" })]);
  });

  it("restores unconfirmed backend smart-delete cuts instead of applying them by default", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [],
      rules,
      [],
      [{ start: 10, end: 12, duration_sec: 2, kind: "smart_delete", reason: "restart_retake", source: "llm_cut_review" }],
    );

    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 10 }, { start: 12, end: 20 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      20,
    );

    expect(nextSegments).toEqual([{ start: 0, end: 20 }]);
  });

  it("protects model identity text from backend smart-delete ranges", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 10, end_time: 12, text_final: "新兄弟EDC17光荣取代了" },
      ],
      rules,
      [],
      [{ start: 10, end: 12, duration_sec: 2, kind: "smart_delete", reason: "low_signal_subtitle", source: "llm_cut_review" }],
    );

    expect(analysis.smartDelete).toEqual([expect.objectContaining({ start: 10, end: 12, kind: "smart_delete", protected: true })]);
    expect(autoSmartCutRuleRanges(analysis, rules)).toEqual([]);
    expect(smartCutRuleManagedRanges(analysis)).toEqual([expect.objectContaining({ start: 10, end: 12, kind: "smart_delete", protected: true })]);
  });

  it("restores previously cut protected smart-delete model text through managed ranges", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 10, end_time: 12, text_final: "新兄弟EDC17光荣取代了" },
      ],
      rules,
      [],
      [{ start: 10, end: 12, duration_sec: 2, kind: "smart_delete", reason: "low_signal_subtitle", source: "llm_cut_review" }],
    );

    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 10 }, { start: 12, end: 20 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      20,
    );

    expect(nextSegments).toEqual([{ start: 0, end: 20 }]);
  });

  it("uses only smart-delete as the authoritative fallback when the current rule set no longer matches the session", () => {
    expect(manualEditorAuthoritativeSmartCutKinds(false)).toEqual([]);
    expect(
      manualEditorAuthoritativeSmartCutKinds(
        true,
        { fillerSentenceHeadEnabled: true, catchphraseEnabled: true, fillers: "嗯", catchphrases: "就是" },
        { fillerSentenceHeadEnabled: false, catchphraseEnabled: false, fillers: "呃", catchphrases: "然后" },
      ),
    ).toEqual(["smart_delete", "repeated"]);
  });

  it("prefers backend authoritative repeated ranges over local transcript rescans when cut analysis is available", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: true, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 2, text_final: "这个这个型号不错" },
      ],
      rules,
      [],
      [
        { start: 0.62, end: 0.94, duration_sec: 0.32, kind: "repeated", reason: "repeated_speech", source: "manual_editor_rule_candidate" },
      ],
      { authoritativeKinds: ["repeated"] },
    );

    expect(analysis.repeated).toEqual([
      expect.objectContaining({ start: 0.62, end: 0.94, kind: "repeated", reason: "repeated_speech" }),
    ]);
  });

  it("accepts backend smart-cut filler and catchphrase rule segments", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      catchphraseEnabled: true,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯",
      catchphrases: "就是",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "嗯我们开始" },
        { index: 1, start_time: 1, end_time: 2, text_final: "这个就是重点" },
      ],
      rules,
      [],
      [
        { start: 0.0, end: 0.12, duration_sec: 0.12, kind: "filler", reason: "filler_word", source: "manual_editor_rule_candidate", filler_mode: "standalone", source_text: "嗯" },
        { start: 1.2, end: 1.45, duration_sec: 0.25, kind: "catchphrase", reason: "catchphrase_phrase", source: "manual_editor_rule_candidate", source_text: "就是" },
      ],
    );

    expect(analysis.filler).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: "filler", sourceText: "嗯", fillerMode: "standalone" }),
    ]));
    expect(analysis.catchphrase).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: "catchphrase", sourceText: "就是" }),
    ]));
  });

  it("prefers backend authoritative filler and catchphrase ranges when provided", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      catchphraseEnabled: true,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯",
      catchphrases: "就是",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "嗯我们开始" },
        { index: 1, start_time: 1, end_time: 2, text_final: "这个就是重点" },
      ],
      rules,
      [],
      [
        { start: 0.0, end: 0.12, duration_sec: 0.12, kind: "filler", reason: "filler_word", source: "manual_editor_rule_candidate", filler_mode: "standalone", source_text: "嗯" },
        { start: 1.28, end: 1.46, duration_sec: 0.18, kind: "catchphrase", reason: "catchphrase_phrase", source: "manual_editor_rule_candidate", source_text: "就是" },
      ],
      { authoritativeKinds: ["filler", "catchphrase"] },
    );

    expect(analysis.filler).toEqual([
      expect.objectContaining({ start: 0, end: 0.12, kind: "filler", sourceText: "嗯", fillerMode: "standalone" }),
    ]);
    expect(analysis.catchphrase).toEqual([
      expect.objectContaining({ start: 1.28, end: 1.46, kind: "catchphrase", sourceText: "就是" }),
    ]);
  });

  it("does not fall back to local filler and catchphrase rescans when backend authoritative analysis is empty", () => {
    const rules = {
      fillerEnabled: true,
      fillerStandaloneEnabled: true,
      fillerSentenceHeadEnabled: false,
      fillerSentenceTailEnabled: false,
      catchphraseEnabled: true,
      repeatedEnabled: false,
      pauseEnabled: false,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯",
      catchphrases: "就是",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "嗯我们开始" },
        { index: 1, start_time: 1, end_time: 2, text_final: "这个就是重点" },
      ],
      rules,
      [],
      [],
      { authoritativeKinds: ["filler", "catchphrase"] },
    );

    expect(analysis.filler).toEqual([]);
    expect(analysis.catchphrase).toEqual([]);
  });

  it("prefers backend authoritative pause ranges when provided", () => {
    const rules = {
      fillerEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: true,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯,呃",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [],
      rules,
      [{ start: 2, end: 3.1, duration_sec: 1.1, source: "audio_vad" }],
      [
        { start: 2, end: 3.1, duration_sec: 1.1, kind: "pause", reason: "silence", source: "manual_editor_rule_candidate" },
      ],
      { authoritativeKinds: ["pause"] },
    );

    expect(analysis.pauseCandidates).toEqual([
      expect.objectContaining({ start: 2, end: 3.1, kind: "pause", reason: "silence" }),
    ]);
    expect(analysis.pause).toEqual([
      expect.objectContaining({ start: 2, end: 3.1, kind: "pause", reason: "silence" }),
    ]);
  });

  it("does not fall back to local pause rescans when backend authoritative pause analysis is empty", () => {
    const rules = {
      fillerEnabled: false,
      repeatedEnabled: false,
      pauseEnabled: true,
      smartDeleteEnabled: false,
      pauseThresholdSec: 0.8,
      fillers: "嗯,呃",
    };
    const analysis = buildSmartCutRuleAnalysis(
      [],
      rules,
      [{ start: 2, end: 3.1, duration_sec: 1.1, source: "audio_vad" }],
      [],
      { authoritativeKinds: ["pause"] },
    );

    expect(analysis.pauseCandidates).toEqual([]);
    expect(analysis.pause).toEqual([]);
  });

  it("uses backend smart-delete rule segments as the primary source without duplicate smart-delete payloads", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 10, end_time: 12, text_final: "新兄弟EDC17光荣取代了" },
      ],
      rules,
      [],
      [
        { start: 10, end: 12, duration_sec: 2, kind: "smart_delete", reason: "low_signal_subtitle", source: "llm_cut_review", detail: "低信息字幕废片" },
      ],
      { authoritativeKinds: ["smart_delete"] },
    );

    expect(analysis.smartDelete).toEqual([
      expect.objectContaining({ start: 10, end: 12, kind: "smart_delete", reason: "low_signal_subtitle" }),
    ]);
  });

  it("builds rule previews from real matched source text", () => {
    const rules = { fillerEnabled: true, catchphraseEnabled: true, repeatedEnabled: true, pauseEnabled: true, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃", catchphrases: "就是" };
    const subtitles = [
      { index: 0, start_time: 0, end_time: 1, text_final: "嗯我们开始" },
      { index: 1, start_time: 2, end_time: 3, text_final: "这个这个型号不错" },
      { index: 2, start_time: 3, end_time: 4, text_final: "这个就是重点" },
    ];
    const analysis = buildSmartCutRuleAnalysis(
      subtitles,
      rules,
      [{ start: 1.1, end: 1.95, duration_sec: 0.85 }],
      [{ start: 4, end: 5, duration_sec: 1, kind: "smart_delete", reason: "restart_retake", detail: "开头重说" }],
    );

    const previews = buildSmartCutRulePreviews(analysis, rules, subtitles);

    expect(previews.map((preview) => preview.label)).toEqual(["语气词", "口头禅", "重复口误", "停顿", "智能删减"]);
    expect(previews.find((preview) => preview.kind === "filler")?.sampleText).toBe("嗯");
    expect(previews.find((preview) => preview.kind === "catchphrase")?.sampleText).toBe("就是");
    expect(previews.find((preview) => preview.kind === "pause")?.sampleText).toBe("[0.8s]");
    expect(previews.find((preview) => preview.kind === "smart_delete")?.reason).toContain("开头重说");
  });

  it("groups smart-delete pacing fragments into one readable suggestion", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const subtitles = [
      { index: 0, start_time: 10, end_time: 11, text_final: "前面这句正常" },
      { index: 1, start_time: 11, end_time: 12.4, text_final: "这里说错了重来" },
      { index: 2, start_time: 12.4, end_time: 13.5, text_final: "正式开始" },
    ];
    const analysis = buildSmartCutRuleAnalysis(
      subtitles,
      rules,
      [],
      [
        { start: 10.9, end: 12.1, duration_sec: 1.2, kind: "smart_delete", reason: "rollback_instruction", detail: "前面这段删掉重来" },
        { start: 12.18, end: 12.5, duration_sec: 0.32, kind: "smart_delete", reason: "timing_trim", detail: "规则候选：节奏边界修剪" },
      ],
    );

    const suggestions = buildSmartDeleteSuggestions(analysis, rules, subtitles);

    expect(suggestions).toHaveLength(1);
    expect(suggestions[0]?.sourceRanges).toEqual([{ start: 10.9, end: 12.1 }, { start: 12.18, end: 12.5 }]);
    expect(suggestions[0]?.reasonSummary).toContain("明确的剪辑口令");
    expect(suggestions[0]?.detailSummary).toContain("前面这段删掉重来");
    expect(suggestions[0]?.detailSummary).toContain("句子边角修剪");
  });

  it("removes selected transcript text from subtitle drafts when cutting text from preview", () => {
    const drafts = removeTranscriptSelectionTextFromSubtitleDrafts(
      [
        {
          index: 65,
          source_index: 10,
          start_time: 100,
          end_time: 104,
          text_final: "它就不会有硌手的感觉好就很轻松了很轻松",
        },
      ],
      Array.from("它就不会有硌手的感觉好就很轻松了很轻松").map((text, index) => ({
        key: `char-10-${index}`,
        kind: "char" as const,
        text,
        subtitleIndex: 10,
        start: 100 + index * 0.1,
        end: 100 + (index + 1) * 0.1,
        kept: true,
      })),
      { startTokenIndex: 10, endTokenIndex: 15 },
      {},
    );

    expect(drafts[65]?.text_final).toBe("它就不会有硌手的感觉很轻松");
    expect(drafts[10]).toBeUndefined();
  });

  it("keeps deleted subtitle rows visible with source restore ranges", () => {
    const rows = buildVisibleSubtitleRows(
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "保留字幕" },
      ],
      {
        remapped: [
          { index: 0, start_time: 0, end_time: 1, text_final: "保留字幕" },
        ],
        ranges: [{ sourceStart: 10, sourceEnd: 11, outputStart: 0, outputEnd: 1 }],
      },
      { 1: { delete: true } },
      [{ start: 10, end: 14 }],
      [
        { index: 0, start_time: 0, end_time: 1, text_final: "保留字幕" },
        { index: 1, start_time: 1, end_time: 3, text_final: "被删字幕" },
      ],
    );

    expect(rows.map((row) => ({ index: row.index, deleted: Boolean(row.deleted), text: row.text_final }))).toEqual([
      { index: 0, deleted: false, text: "保留字幕" },
      { index: 1, deleted: true, text: "被删字幕" },
    ]);
    expect(rows[1].restoreRanges).toEqual([{ start: 11, end: 13 }]);
  });
});

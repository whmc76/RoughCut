import { describe, expect, it } from "vitest";

import {
  applySmartCutRuleRangesToSegments,
  autoSmartCutRuleRanges,
  buildManualEditChangeList,
  buildSourceTranscriptProjectedBaseline,
  buildSmartCutRuleAnalysis,
  buildTranscriptTokens,
  buildVisibleSubtitleRows,
  buildSourceTranscriptSubtitlesForTimeline,
  buildOutputWaveformBars,
  findSubtitleIndexNearOutputTime,
  buildSmartCutRulePreviews,
  normalizeAdjacentSubtitleTextOverlaps,
  outputTimeToSourceTimeForSegments,
  outputTimeToSourceTime,
  projectedTranscriptMissesKeptSpeech,
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

  it("trims projected subtitle text when a leading filler is cut from the source timeline", () => {
    const rules = { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "呃" };
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

    expect(analysis.filler).toEqual([{ start: 10, end: 11, kind: "filler" }]);
    expect(nextSegments).toEqual([{ start: 11, end: 15 }]);
    expect(projection.remapped.map((subtitle) => subtitle.text_final)).toEqual(["没想到啊"]);
    expect(projection.remapped[0].start_time).toBeCloseTo(0, 3);
    expect(projection.remapped[0].end_time).toBeCloseTo(4, 3);
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

  it("lets long audio VAD pauses become smart-cut candidates without word timings", () => {
    const rules = { fillerEnabled: false, repeatedEnabled: false, pauseEnabled: true, smartDeleteEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const analysis = buildSmartCutRuleAnalysis(
      [{ index: 0, start_time: 0, end_time: 4, text_final: "收到了第三次" }],
      rules,
      [{ start: 0.8, end: 1.8, duration_sec: 1.0, source: "audio_vad" }],
    );

    expect(analysis.pause).toEqual([{ start: 0.8, end: 1.8, kind: "pause" }]);
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

  it("keeps full-text transcript timing on the source timeline", () => {
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

  it("uses source_index instead of projected row index when rebuilding full-text transcript", () => {
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

  it("uses corrected canonical subtitle text before raw ASR text in the full transcript", () => {
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

  it("keeps full-text editing on source subtitles even when projected subtitles look cleaner", () => {
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
      { start: 0, end: 0.4, kind: "filler" },
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

  it("splits long pause chips by actual kept and cut timeline ranges", () => {
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
    }))).toEqual([
      { kind: "pause", start: 0, end: 1, kept: true },
      { kind: "pause", start: 1, end: 2, kept: false },
      { kind: "pause", start: 2, end: 3, kept: true },
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
    }))).toEqual([
      { kind: "pause", start: 0, end: 1.6, kept: false, pauseDuration: 1.6 },
    ]);
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

  it("renders audio VAD pauses inside coarse backend alignment spans", () => {
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

    expect(tokens.some((token) => token.kind === "pause" && token.start === 5.85 && token.end === 6.21)).toBe(true);
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
    expect(analysis.pause).toEqual(analysis.pauseCandidates);
  });

  it("does not group short pauses across meaningful speech", () => {
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
    expect(analysis.pause).toEqual([]);
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

    expect(analysis.pause).toEqual([{ start: 1.3, end: 2.5, kind: "pause" }]);
    expect(nextSegments).toEqual([{ start: 0, end: 1.38 }, { start: 2.42, end: 3 }]);
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

  it("uses the configured pause breath when shrinking deleted pause ranges", () => {
    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 1 }, { start: 2, end: 3 }],
      [{ start: 1, end: 2, kind: "pause" }],
      [{ start: 1, end: 2, kind: "pause" }],
      3,
      [],
      { pauseBreathSec: 0.2 },
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
      [{ start: 12.3456, end: 14.9, duration_sec: 2.554, reason: "restart_retake", source: "llm_cut_review" }],
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
      [{ start: 10, end: 12, duration_sec: 2, reason: "restart_retake", source: "llm_cut_review" }],
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
      [{ start: 10, end: 12, duration_sec: 2, reason: "low_signal_subtitle", source: "llm_cut_review" }],
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
      [{ start: 10, end: 12, duration_sec: 2, reason: "low_signal_subtitle", source: "llm_cut_review" }],
    );

    const nextSegments = applySmartCutRuleRangesToSegments(
      [{ start: 0, end: 10 }, { start: 12, end: 20 }],
      autoSmartCutRuleRanges(analysis, rules),
      smartCutRuleManagedRanges(analysis),
      20,
    );

    expect(nextSegments).toEqual([{ start: 0, end: 20 }]);
  });

  it("builds rule previews from real matched source text", () => {
    const rules = { fillerEnabled: true, repeatedEnabled: true, pauseEnabled: true, smartDeleteEnabled: true, pauseThresholdSec: 0.8, fillers: "嗯,呃" };
    const subtitles = [
      { index: 0, start_time: 0, end_time: 1, text_final: "嗯我们开始" },
      { index: 1, start_time: 2, end_time: 3, text_final: "这个这个型号不错" },
    ];
    const analysis = buildSmartCutRuleAnalysis(
      subtitles,
      rules,
      [{ start: 1.1, end: 1.95, duration_sec: 0.85 }],
      [{ start: 4, end: 5, duration_sec: 1, reason: "restart_retake", detail: "开头重说" }],
    );

    const previews = buildSmartCutRulePreviews(analysis, rules, subtitles);

    expect(previews.map((preview) => preview.label)).toEqual(["语气词", "重复口误", "长停顿", "智能废片"]);
    expect(previews.find((preview) => preview.kind === "filler")?.sampleText).toBe("嗯");
    expect(previews.find((preview) => preview.kind === "pause")?.sampleText).toBe("[0.8s]");
    expect(previews.find((preview) => preview.kind === "smart_delete")?.reason).toContain("开头重说");
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

import { describe, expect, it } from "vitest";

import {
  autoSmartCutRuleRanges,
  buildSmartCutRuleAnalysis,
  buildSourceTranscriptSubtitlesForTimeline,
  buildOutputWaveformBars,
  findSubtitleIndexNearOutputTime,
  normalizeAdjacentSubtitleTextOverlaps,
  outputTimeToSourceTimeForSegments,
  outputTimeToSourceTime,
  projectedTranscriptMissesKeptSpeech,
  remapProjectedSubtitlesFromBaseTimeline,
  sourceTimeToActiveOutputTime,
  sourceTimeToOutputTime,
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
      { index: 26, start_time: 99.26, end_time: 101.18, text_final: "投影字幕" },
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
      { index: 52, start_time: 188.807, end_time: 192.22, text_final: "投影字幕" },
    ]);
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

  it("uses raw source text for filler rule analysis and auto ranges", () => {
    const analysis = buildSmartCutRuleAnalysis(
      [
        { index: 0, start_time: 0, end_time: 0.4, text_raw: "嗯", text_final: "嗯" },
        { index: 1, start_time: 0.4, end_time: 1.4, text_raw: "我们开始", text_final: "我们开始" },
      ],
      { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" },
    );

    expect(analysis.filler).toHaveLength(1);
    expect(autoSmartCutRuleRanges(analysis, { fillerEnabled: true, repeatedEnabled: false, pauseEnabled: false, pauseThresholdSec: 0.8, fillers: "嗯" })).toEqual([
      { start: 0, end: 0.4, kind: "filler" },
    ]);
  });

});

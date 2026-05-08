import { describe, expect, it } from "vitest";

import {
  outputTimeToSourceTime,
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
});

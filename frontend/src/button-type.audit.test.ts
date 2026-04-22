import { describe, expect, it } from "vitest";

const sourceFiles = import.meta.glob("./**/*.{ts,tsx}", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;
const buttonTagPattern = new RegExp("<" + "button\\b[\\s\\S]*?>", "g");

describe("button type audit", () => {
  it("requires every button element to declare an explicit type", () => {
    const missingTypes: string[] = [];

    for (const [filePath, source] of Object.entries(sourceFiles)) {
      if (filePath.endsWith("button-type.audit.test.ts")) continue;

      const buttonTags = source.matchAll(buttonTagPattern);
      for (const match of buttonTags) {
        const tag = match[0];
        if (/\btype\s*=/.test(tag)) continue;

        const line = source.slice(0, match.index).split(/\r?\n/).length;
        missingTypes.push(`${filePath}:${line}`);
      }
    }

    expect(missingTypes).toEqual([]);
  });
});

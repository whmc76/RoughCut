import { describe, expect, it } from "vitest";

import { buildFrequentTerms, buildManualFrequentTerm } from "./JobManualEditSection";
import type { JobManualEditSubtitle } from "../../types";

function subtitle(index: number, text: string, patch?: Partial<JobManualEditSubtitle>): JobManualEditSubtitle {
  return {
    index,
    start_time: index,
    end_time: index + 1,
    text_raw: text,
    text_norm: text,
    text_final: text,
    ...patch,
  };
}

describe("manual editor frequent term review candidates", () => {
  it("filters common spoken words out of frequent review candidates", () => {
    const terms = buildFrequentTerms([
      subtitle(1, "我们再轻松一点只要打开这个版本"),
      subtitle(2, "这个操作很轻松一点也不复杂"),
      subtitle(3, "只要看到这里就可以开始"),
      subtitle(4, "轻松一点只要这样就行"),
    ]);

    expect(terms.map((term) => term.term)).not.toEqual(expect.arrayContaining(["轻松", "一点", "只要"]));
  });

  it("keeps repeated model, brand, and domain terms", () => {
    const terms = buildFrequentTerms([
      subtitle(1, "这个 Sony A7C II 版本要核对"),
      subtitle(2, "Sony A7C II 这个版本和参数不同"),
      subtitle(3, "A7C II 的版本配置再看一下"),
    ]);
    const labels = terms.map((term) => term.term.toLowerCase());

    expect(labels).toContain("sony");
    expect(labels.some((term) => term.includes("a7c"))).toBe(true);
    expect(terms.find((term) => term.term === "版本")?.kind).toBe("名词/术语");
  });

  it("keeps repeated terms from unstable subtitle rows as low-confidence candidates", () => {
    const terms = buildFrequentTerms([
      subtitle(1, "银色钛金属外壳", { text_raw: "银色太金属外壳", text_final: "银色钛金属外壳" }),
      subtitle(2, "钛金属边框很轻", { text_raw: "太金属边框很轻", text_final: "钛金属边框很轻" }),
      subtitle(3, "这个钛金属版本更稳", { text_raw: "这个太金属版本更稳", text_final: "这个钛金属版本更稳" }),
    ]);

    expect(terms.find((term) => term.term === "金属")?.kind).toBe("低置信词");
  });

  it("keeps spoken digit sequences as model-like shorthand but drops obvious number words", () => {
    const terms = buildFrequentTerms([
      subtitle(1, "三三这个版本比三十几块的不同"),
      subtitle(2, "三二和三三都是型号简称"),
      subtitle(3, "三二这版不要和几十几混在一起"),
      subtitle(4, "二零二四版本也可能是特殊指代"),
    ]);
    const labels = terms.map((term) => term.term);

    expect(labels).toEqual(expect.arrayContaining(["三三", "三二", "二零二四"]));
    expect(terms.find((term) => term.term === "三三")?.kind).toBe("专名/型号");
    expect(labels).not.toEqual(expect.arrayContaining(["三十几", "几十几"]));
  });

  it("builds a manual candidate and merges related frequent fragments", () => {
    const subtitles = [
      subtitle(1, "这个开提结构需要统一"),
      subtitle(2, "开提打开以后很顺"),
      subtitle(3, "开题这个词其实也是同一个结构"),
      subtitle(4, "后面又说了一次开题"),
    ];
    const term = buildManualFrequentTerm("开提", subtitles, []);

    expect(term?.manuallyAdded).toBe(true);
    expect(term?.term).toBe("开提");
    expect(term?.relatedTerms).toContain("开题");
    expect(term?.count).toBe(2);
  });

  it("uses the manually supplied full phrase as the review candidate, not the merged fragment", () => {
    const subtitles = [
      subtitle(1, "这个快开提结构需要统一"),
      subtitle(2, "快开提打开以后很顺"),
      subtitle(3, "系统高频词可能只看到开提"),
      subtitle(4, "这里又单独说了一次开提"),
    ];
    const frequentTerms = buildFrequentTerms(subtitles);
    const term = buildManualFrequentTerm("快开提", subtitles, frequentTerms);

    expect(term?.term).toBe("快开提");
    expect(term?.count).toBe(2);
    expect(term?.relatedTerms).toContain("开提");
    expect(term?.occurrences.map((item) => item.index)).toEqual([1, 2]);
  });
});

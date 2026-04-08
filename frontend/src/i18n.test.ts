import { describe, expect, it } from "vitest";

import { translate } from "./i18n";

describe("watch roots naming", () => {
  it("keeps the navigation entry and page title aligned with watch roots in Chinese", () => {
    expect(translate("zh-CN", "app.nav.watchRoots")).toBe("监看目录");
    expect(translate("zh-CN", "watch.page.title")).toBe("监看目录");
  });

  it("keeps the navigation entry and page title aligned with watch roots in English", () => {
    expect(translate("en-US", "app.nav.watchRoots")).toBe("Watch Roots");
    expect(translate("en-US", "watch.page.title")).toBe("Watch Roots");
  });
});

import { describe, expect, it } from "vitest";

import { translate } from "./i18n";

describe("watch roots naming", () => {
  it("renames the navigation entry and page title to automation plans in Chinese", () => {
    expect(translate("zh-CN", "app.nav.watchRoots")).toBe("自动方案");
    expect(translate("zh-CN", "watch.page.title")).toBe("自动方案");
  });

  it("renames the navigation entry and page title to automation plans in English", () => {
    expect(translate("en-US", "app.nav.watchRoots")).toBe("Automation Plans");
    expect(translate("en-US", "watch.page.title")).toBe("Automation Plans");
  });
});

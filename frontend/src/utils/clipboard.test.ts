// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { writeTextToClipboard } from "./clipboard";

const originalExecCommand = document.execCommand;
const originalClipboard = navigator.clipboard;

afterEach(() => {
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: originalExecCommand,
  });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: originalClipboard,
  });
  vi.restoreAllMocks();
});

describe("writeTextToClipboard", () => {
  it("uses the real selection copy path before reporting success", async () => {
    let selectedText = "";
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => {
        const active = document.activeElement;
        selectedText = active instanceof HTMLTextAreaElement ? active.value : "";
        return true;
      }),
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn(),
      },
    });

    const result = await writeTextToClipboard("真实复制内容");

    expect(result).toEqual({ ok: true, method: "selection" });
    expect(selectedText).toBe("真实复制内容");
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("falls back to the async Clipboard API when selection copy is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    const result = await writeTextToClipboard("fallback copy");

    expect(result).toEqual({ ok: true, method: "clipboard-api" });
    expect(writeText).toHaveBeenCalledWith("fallback copy");
  });

  it("reports failure when no browser copy mechanism succeeds", async () => {
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => false),
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });

    await expect(writeTextToClipboard("not copied")).resolves.toEqual({ ok: false });
  });
});

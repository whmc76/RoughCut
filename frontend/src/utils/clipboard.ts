export type ClipboardWriteResult =
  | { ok: true; method: "selection" | "clipboard-api" }
  | { ok: false; error?: unknown };

export async function writeTextToClipboard(value: string): Promise<ClipboardWriteResult> {
  const text = String(value || "");
  if (!text.trim()) {
    return { ok: false };
  }

  const selectionResult = writeTextWithSelection(text);
  if (selectionResult.ok) {
    return selectionResult;
  }

  const clipboard = navigator.clipboard;
  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(text);
      return { ok: true, method: "clipboard-api" };
    } catch (error) {
      return { ok: false, error };
    }
  }

  return selectionResult;
}

function writeTextWithSelection(text: string): ClipboardWriteResult {
  if (typeof document === "undefined" || !document.body || typeof document.execCommand !== "function") {
    return { ok: false };
  }

  const previousActiveElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const selection = document.getSelection();
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
  const textArea = document.createElement("textarea");

  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.setAttribute("aria-hidden", "true");
  textArea.style.position = "fixed";
  textArea.style.top = "0";
  textArea.style.left = "-9999px";
  textArea.style.width = "1px";
  textArea.style.height = "1px";
  textArea.style.opacity = "0";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  textArea.setSelectionRange(0, text.length);

  try {
    return document.execCommand("copy") ? { ok: true, method: "selection" } : { ok: false };
  } catch (error) {
    return { ok: false, error };
  } finally {
    document.body.removeChild(textArea);
    if (selection) {
      selection.removeAllRanges();
      if (previousRange) {
        selection.addRange(previousRange);
      }
    }
    previousActiveElement?.focus({ preventScroll: true });
  }
}

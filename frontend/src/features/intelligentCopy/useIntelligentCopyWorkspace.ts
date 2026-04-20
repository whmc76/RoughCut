import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api";
import type { IntelligentCopyInspect, IntelligentCopyResult } from "../../types";

export function useIntelligentCopyWorkspace() {
  const [folderPath, setFolderPath] = useState("");
  const [copyStyle, setCopyStyle] = useState("attention_grabbing");
  const [inspection, setInspection] = useState<IntelligentCopyInspect | null>(null);
  const [result, setResult] = useState<IntelligentCopyResult | null>(null);
  const [copyFeedback, setCopyFeedback] = useState("");

  const inspect = useMutation({
    mutationFn: (path: string) => api.inspectIntelligentCopyFolder(path),
    onSuccess: (payload) => {
      setInspection(payload);
      setResult(null);
    },
  });

  const generate = useMutation({
    mutationFn: (payload: { folderPath: string; copyStyle: string }) =>
      api.generateIntelligentCopy(payload.folderPath, payload.copyStyle),
    onSuccess: (payload) => {
      setInspection(payload.inspection);
      setResult(payload);
    },
  });

  const openFolder = useMutation({
    mutationFn: (path: string) => api.openIntelligentCopyFolder(path),
  });

  async function copyText(text: string, successLabel: string) {
    if (!text.trim()) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyFeedback(successLabel);
    } catch {
      setCopyFeedback("复制失败，请检查系统剪贴板权限。");
    }
    window.setTimeout(() => setCopyFeedback(""), 1800);
  }

  return {
    folderPath,
    setFolderPath,
    copyStyle,
    setCopyStyle,
    inspection,
    result,
    inspect,
    generate,
    openFolder,
    copyText,
    copyFeedback,
  };
}

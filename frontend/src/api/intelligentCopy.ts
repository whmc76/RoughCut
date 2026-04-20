import type { IntelligentCopyInspect, IntelligentCopyResult } from "../types";
import { request } from "./core";

export const intelligentCopyApi = {
  inspectIntelligentCopyFolder: (folderPath: string) =>
    request<IntelligentCopyInspect>("/intelligent-copy/inspect", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
  generateIntelligentCopy: (folderPath: string, copyStyle?: string) =>
    request<IntelligentCopyResult>("/intelligent-copy/generate", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, copy_style: copyStyle || null }),
    }),
  openIntelligentCopyFolder: (folderPath: string) =>
    request<{ path: string; kind: string }>("/intelligent-copy/open-folder", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
};

import type { IntelligentCopyInspect, IntelligentCopyResult, PublicationPlan, PublicationPlatformPublishOptions } from "../types";
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
  getIntelligentPublishPlan: (
    folderPath: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>("/intelligent-copy/publication/plan", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, ...body }),
    }),
  publishIntelligentFolder: (
    folderPath: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>("/intelligent-copy/publication/publish", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, ...body }),
    }),
  openIntelligentCopyFolder: (folderPath: string) =>
    request<{ path: string; kind: string }>("/intelligent-copy/open-folder", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
};
